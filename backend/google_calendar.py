"""Explicit Google Calendar account linking and selected-calendar reads.

The client secret and refresh tokens stay encrypted on the host. OAuth uses PKCE,
one-use state, and an authenticated finish step in the originating owner session.
"""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import secrets
from threading import RLock
import time
from urllib.parse import quote, urlencode, urlsplit

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from .home import HomeUnavailable

READ_SCOPES=('https://www.googleapis.com/auth/calendar.calendarlist.readonly',
             'https://www.googleapis.com/auth/calendar.events.readonly')
WRITE_SCOPE='https://www.googleapis.com/auth/calendar.events'
CALLBACK='/v1/calendar/google/callback'


class GoogleConfig(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision:int=Field(ge=0)
    client_id:str=Field(default='',max_length=240)
    client_secret:SecretStr=SecretStr('')
    redirect_uri:str=Field(default='',max_length=500)

    @field_validator('client_id')
    @classmethod
    def client(cls,value):
        if value and not re.fullmatch(r'[A-Za-z0-9._-]{6,210}\.apps\.googleusercontent\.com',value):
            raise ValueError('Use a Google web OAuth client ID')
        return value

    @field_validator('client_secret')
    @classmethod
    def secret(cls,value):
        raw=value.get_secret_value()
        if len(raw)>512 or any(ord(c)<33 or ord(c)>126 for c in raw):raise ValueError('Invalid client secret')
        return value

    @field_validator('redirect_uri')
    @classmethod
    def redirect(cls,value):
        if not value:return value
        u=urlsplit(value)
        if (not u.hostname or u.username is not None or u.password is not None or u.query or u.fragment
            or u.path!=CALLBACK or any(ord(c)<=32 for c in value)
            or not (u.scheme=='https' or u.scheme=='http' and u.hostname in {'127.0.0.1','localhost'})):
            raise ValueError('Use the Echo HTTPS callback URL, or HTTP on loopback')
        _=u.port
        return value


class GoogleAccountLabel(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    label:str=Field(min_length=1,max_length=60)

    @field_validator('label')
    @classmethod
    def readable(cls,value):
        if not value.strip() or any(ord(c)<32 for c in value):raise ValueError('Choose a readable label')
        return value.strip()


class FlowClient(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    client:str=Field(pattern=r'^[a-f0-9]{64}$')


class BeginFlow(GoogleAccountLabel,FlowClient):
    write_access:bool=False


class GoogleRejected(HomeUnavailable):
    """A definitive provider rejection, including a failed ETag precondition."""


class GoogleTransport:
    def json(self,method,url,**kwargs):
        # URLs originate only from fixed Google endpoints and quoted resource IDs.
        try:
            with httpx.Client(timeout=12,trust_env=False,follow_redirects=False) as client:
                with client.stream(method,url,**kwargs) as response:
                    if response.status_code in {400,401,403,404,409,410,412,422}:
                        raise GoogleRejected('Google rejected this request. Refresh the calendar and check account permissions before trying again.')
                    if response.status_code>=300:raise HomeUnavailable('Google Calendar did not accept the request. Check the account connection.')
                    if response.status_code==204 and method=='DELETE':return {}
                    if response.status_code==204 or method=='DELETE':raise HomeUnavailable('Google returned an unexpected response. Check the calendar before retrying.')
                    raw=bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw)>2_000_000:raise HomeUnavailable('Google Calendar returned too much data.')
                    value=json.loads(raw)
            if not isinstance(value,dict):raise ValueError()
            return value
        except (httpx.HTTPError,ValueError):raise HomeUnavailable('Google Calendar could not be reached or returned an invalid response.') from None


class GoogleCalendars:
    def __init__(self,root,protector,transport=None,clock=time.time,enabled=True):
        self.path=Path(root)/'local/echo-google-calendar.json' if root else None
        self.protector,self.transport,self.clock,self.enabled=protector,transport or GoogleTransport(),clock,enabled
        self.lock=RLock();self.config=GoogleConfig(revision=0);self.accounts=[];self.flows={};self.access={};self.error=False
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size>500_000:raise ValueError()
                envelope=json.loads(self.path.read_text())
                if envelope['version']!=1:raise ValueError()
                data=json.loads(protector.decrypt(base64.b64decode(envelope['protected'],validate=True)))
                self.config=GoogleConfig.model_validate(data['config']);self.accounts=data['accounts']
                if not isinstance(self.accounts,list) or len(self.accounts)>8:raise ValueError()
                ids=set()
                for account in self.accounts:
                    if not re.fullmatch('[a-f0-9]{32}',account['id']) or account['id'] in ids:raise ValueError()
                    ids.add(account['id']);GoogleAccountLabel(label=account['label'])
                    if type(account.get('write_access',False)) is not bool:raise ValueError()
                    if not self.valid_token(account['refresh_token']) or not isinstance(account['calendars'],list) or len(account['calendars'])>100:raise ValueError()
                    for item in account['calendars']:
                        if self.entity(account['id'],item['id'])!=item['entity_id']:raise ValueError()
                        if not isinstance(item['name'],str) or len(item['name'])>160:raise ValueError()
            except (OSError,ValueError,RuntimeError,KeyError,TypeError):self.error=True

    @staticmethod
    def valid_token(value):return isinstance(value,str) and 0<len(value)<=8192 and all(33<=ord(c)<=126 for c in value)

    @staticmethod
    def entity(account,calendar):
        if not isinstance(calendar,str) or not 0<len(calendar)<=1024 or any(ord(c)<32 for c in calendar):raise ValueError('Invalid calendar ID')
        return 'calendar.google_'+account+'_'+hashlib.sha256(calendar.encode()).hexdigest()[:24]

    def require(self):
        if self.error:raise HomeUnavailable('Google account settings are unreadable. Existing storage is preserved.')

    def commit(self,config,accounts):
        values=config.model_dump();values['client_secret']=config.client_secret.get_secret_value()
        payload=json.dumps({'config':values,'accounts':accounts}).encode()
        if len(payload)>250_000:raise HomeUnavailable('Google account inventory storage is full. Disconnect an unused account before adding more.')
        if self.path:
            try:
                encrypted=self.protector.encrypt(payload)
                self.path.parent.mkdir(parents=True,exist_ok=True)
                temporary=self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'version':1,'protected':base64.b64encode(encrypted).decode()}))
                temporary.replace(self.path)
            except (OSError,RuntimeError):raise HomeUnavailable('Google account settings could not be saved.') from None
        self.config,self.accounts=config,deepcopy(accounts)

    def settings(self):
        with self.lock:
            self.require()
            return {'revision':self.config.revision,'client_id':self.config.client_id,'redirect_uri':self.config.redirect_uri,
                    'secret_saved':bool(self.config.client_secret.get_secret_value()),'enabled':self.enabled,
                    'accounts':[{'id':a['id'],'label':a['label'],'calendar_count':len(a['calendars']),
                                 'write_access':a.get('write_access',False)} for a in self.accounts]}

    def configure(self,body):
        with self.lock:
            self.require()
            if body.revision!=self.config.revision:raise HTTPException(409,'Google configuration changed. Reload it first.')
            if self.accounts and (body.client_id!=self.config.client_id or body.client_secret.get_secret_value()):
                raise HTTPException(409,'Disconnect linked Google accounts before changing the OAuth client or secret.')
            candidate=body.model_copy(deep=True);candidate.revision+=1
            if not candidate.client_secret.get_secret_value():
                if candidate.client_id!=self.config.client_id and self.config.client_id:raise HTTPException(422,'Enter the secret for this OAuth client.')
                candidate.client_secret=self.config.client_secret
            if not candidate.client_id or not candidate.redirect_uri or not candidate.client_secret.get_secret_value():
                raise HTTPException(422,'Enter the client ID, secret and callback URL.')
            self.commit(candidate,self.accounts);self.flows.clear();self.access.clear();return self.settings()

    def prune(self):
        with self.lock:
            now=self.clock();self.flows={key:f for key,f in self.flows.items() if f['expires']>now}

    def begin(self,label,principal,client,write_access=False):
        with self.lock:
            self.require();self.prune()
            if not self.enabled:raise HTTPException(403,'External account linking is disabled on this host.')
            if not self.config.client_id or not self.config.client_secret.get_secret_value() or not self.config.redirect_uri:
                raise HTTPException(409,'Configure a Google OAuth client first.')
            if len(self.accounts)>=8 or len(self.flows)>=8:raise HTTPException(409,'Account or pending sign-in limit reached.')
            identifier=secrets.token_hex(16);state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
            challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            self.flows[identifier]={'state':hashlib.sha256(state.encode()).hexdigest(),'verifier':verifier,'principal':principal,
                'client':hashlib.sha256(client.encode()).hexdigest(),'label':label,'write_access':write_access is True,
                'revision':self.config.revision,'expires':self.clock()+600,'status':'waiting'}
            query={'client_id':self.config.client_id,'redirect_uri':self.config.redirect_uri,'response_type':'code',
                   'scope':' '.join((*READ_SCOPES,WRITE_SCOPE) if write_access else READ_SCOPES),'state':state,'code_challenge':challenge,'code_challenge_method':'S256',
                   'access_type':'offline','prompt':'consent select_account'}
            return {'id':identifier,'url':'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(query),'expires_at':self.clock()+600}

    def flow(self,identifier,principal,client):
        self.prune();flow=self.flows.get(identifier)
        if (not flow or not secrets.compare_digest(str(flow['principal']),str(principal))
            or not secrets.compare_digest(flow['client'],hashlib.sha256(client.encode()).hexdigest())):
            raise HTTPException(404,'Sign-in expired or belongs to a different Echo session.')
        return flow

    def flow_status(self,identifier,principal,client):
        with self.lock:
            flow=self.flow(identifier,principal,client)
            return {'id':identifier,'status':flow['status'],'label':flow['label'],'expires_at':flow['expires']}

    def cancel(self,identifier,principal,client):
        with self.lock:self.flow(identifier,principal,client);self.flows.pop(identifier);return {'cancelled':True}

    def callback(self,state,code,error):
        with self.lock:
            self.require();self.prune()
            digest=hashlib.sha256(state.encode()).hexdigest()
            found=next(((i,f) for i,f in self.flows.items() if secrets.compare_digest(f['state'],digest)),None)
            if not found or found[1]['status']!='waiting':raise HTTPException(400,'Sign-in expired or has already been used.')
            identifier,flow=found
            if error or not code:flow['status']='declined';return
            flow['status']='exchanging';config=self.config.model_copy(deep=True);verifier=flow['verifier']
        try:
            tokens=self.transport.json('POST','https://oauth2.googleapis.com/token',data={'grant_type':'authorization_code',
                'client_id':config.client_id,'client_secret':config.client_secret.get_secret_value(),
                'code':code,'code_verifier':verifier,'redirect_uri':config.redirect_uri})
            scopes=set(str(tokens.get('scope','')).split())
            event_scope=WRITE_SCOPE in scopes if flow['write_access'] else bool({READ_SCOPES[1],WRITE_SCOPE}&scopes)
            if (not self.valid_token(tokens.get('access_token')) or not self.valid_token(tokens.get('refresh_token'))
                or READ_SCOPES[0] not in scopes or not event_scope):
                raise HomeUnavailable('Google did not grant the required calendar access or offline token.')
            with self.lock:
                if self.flows.get(identifier) is not flow or flow['expires']<=self.clock() or self.config.revision!=config.revision:
                    raise HTTPException(410,'This Echo sign-in was cancelled or configuration changed.')
                flow['tokens']={'refresh_token':tokens['refresh_token']};flow['status']='approved';flow.pop('verifier',None)
        except HomeUnavailable:
            with self.lock:
                if self.flows.get(identifier) is flow:flow['status']='failed';flow.pop('verifier',None)
            raise

    def finish(self,identifier,principal,client):
        with self.lock:
            self.require();flow=self.flow(identifier,principal,client)
            if flow['status']!='approved':raise HTTPException(409,'Approve Google sign-in before finishing.')
            if self.config.revision!=flow['revision']:raise HTTPException(409,'Google configuration changed. Start again.')
            if len(self.accounts)>=8:raise HTTPException(409,'Account limit reached.')
            # Do not overwrite another grant from the same Google account. Each
            # approved connection is isolated and gets fresh local source IDs.
            account={'id':secrets.token_hex(16),'label':flow['label'],'refresh_token':flow['tokens']['refresh_token'],
                     'write_access':flow['write_access'],'calendars':[]}
            self.commit(self.config,[*self.accounts,account]);self.flows.pop(identifier)
            return {'id':account['id'],'label':account['label'],'connected':True}

    def disconnect(self,identifier):
        with self.lock:
            self.require()
            if not any(a['id']==identifier for a in self.accounts):raise HTTPException(404,'Google account not found.')
            self.commit(self.config,[a for a in self.accounts if a['id']!=identifier]);self.access.pop(identifier,None)
            return {'disconnected':True}

    def account(self,identifier):
        self.require();account=next((a for a in self.accounts if a['id']==identifier),None)
        if account is None:raise HomeUnavailable('The Google account was disconnected.')
        return deepcopy(account)

    def token(self,identifier):
        with self.lock:
            if not self.enabled:raise HomeUnavailable('Google Calendar is disabled on this host.')
            account=self.account(identifier);cached=self.access.get(identifier)
            if cached and cached['expires']>self.clock()+60:return cached['token'],account
            value=self.transport.json('POST','https://oauth2.googleapis.com/token',data={'grant_type':'refresh_token',
                'client_id':self.config.client_id,'client_secret':self.config.client_secret.get_secret_value(),
                'refresh_token':account['refresh_token']})
            expiry=value.get('expires_in')
            if not self.valid_token(value.get('access_token')) or type(expiry) not in {int,float} or not 60<=expiry<=86400:
                raise HomeUnavailable('Google returned an invalid access token.')
            self.access[identifier]={'token':value['access_token'],'expires':self.clock()+expiry}
            return value['access_token'],account

    def get(self,identifier,path,params=None):
        token,account=self.token(identifier)
        value=self.transport.json('GET','https://www.googleapis.com/calendar/v3/'+path,
                                  params=params or {},headers={'Authorization':'Bearer '+token})
        with self.lock:
            current=self.account(identifier)
            if current['refresh_token']!=account['refresh_token']:raise HomeUnavailable('Google account access changed.')
        return value

    def sync(self,identifier):
        # Refresh the inventory only on explicit owner request. No new calendar
        # becomes shared automatically when it appears in Google.
        rows=[];page=None
        for _ in range(5):
            result=self.get(identifier,'users/me/calendarList',{'maxResults':100,**({'pageToken':page} if page else {})})
            if not isinstance(result.get('items'),list):raise HomeUnavailable('Google returned an invalid calendar list.')
            rows+=result['items'];page=result.get('nextPageToken')
            if len(rows)>100:raise HomeUnavailable('This account exceeds the 100-calendar inventory limit.')
            if not page:break
            if not isinstance(page,str) or len(page)>2048:raise HomeUnavailable('Invalid Google page token.')
        else:raise HomeUnavailable('Google calendar pagination did not finish.')
        items=[]
        for row in rows:
            if not isinstance(row,dict) or row.get('deleted') or row.get('accessRole') not in {'reader','writer','owner'}:continue
            try:
                remote=row['id'];entity=self.entity(identifier,remote)
                label=row.get('summaryOverride') or row.get('summary') or 'Google calendar'
                if not isinstance(label,str):raise ValueError()
                items.append({'id':remote,'entity_id':entity,'name':label[:160],'timezone':str(row.get('timeZone') or 'UTC')[:80],
                              'access_role':row['accessRole']})
            except (KeyError,ValueError):raise HomeUnavailable('Google returned an invalid calendar entry.') from None
        with self.lock:
            self.account(identifier)
            accounts=deepcopy(self.accounts)
            next(a for a in accounts if a['id']==identifier)['calendars']=items
            self.commit(self.config,accounts)
        return {'calendar_count':len(items)}

    def catalog(self):
        with self.lock:
            self.require()
            if not self.enabled:return []
            return [{'entity_id':c['entity_id'],'kind':'calendar','name':c['name']+' · '+a['label'],
                     **{key:a.get('write_access',False) and c.get('access_role') in {'writer','owner'} for key in ('can_create','can_edit','can_delete')},
                     'can_detect_presence':False,
                     'available':True,'provider':'google'} for a in self.accounts for c in a['calendars']]

    def owns(self,entity):return bool(re.fullmatch(r'calendar\.google_[a-f0-9]{32}_[a-f0-9]{24}',entity))

    def events(self,entity,since,until):
        with self.lock:
            self.require();found=next(((a['id'],c['id']) for a in self.accounts for c in a['calendars'] if c['entity_id']==entity),None)
        if found is None:raise HomeUnavailable('This Google calendar is no longer connected.')
        identifier,remote=found
        result=self.get(identifier,'calendars/'+quote(remote,safe='')+'/events',params={
            'timeMin':since,'timeMax':until,'singleEvents':'true','orderBy':'startTime','maxResults':300,'showDeleted':'false'})
        if not isinstance(result.get('items'),list) or result.get('nextPageToken'):
            raise HomeUnavailable('This calendar window exceeds the 300-event limit. Choose fewer days.')
        rows=[]
        for item in result['items']:
            if not isinstance(item,dict) or item.get('status')=='cancelled':continue
            start,end=item.get('start'),item.get('end')
            if not isinstance(start,dict) or not isinstance(end,dict):continue
            row=self.event_row(item)
            with self.lock:writable=self.account(identifier).get('write_access',False)
            if not writable:row.pop('uid',None)
            rows.append(row)
        return rows

    @staticmethod
    def event_row(item):
        from .google_calendar_write import editable_event
        result={'summary':item.get('summary','Untitled event'),'description':item.get('description',''),
                'location':item.get('location',''),'start':item.get('start'),'end':item.get('end'),
                'rrule':'GOOGLE_RECURRING' if item.get('recurringEventId') or item.get('recurrence') else None,
                '_google':True,'_google_etag':item.get('etag')}
        if editable_event(item):
            result['uid']=item['id']
            if item.get('recurringEventId'):result['recurrence_id']=item['recurringEventId']
        return result


def install(app,google,authorize,owner):
    from fastapi import Depends, Query
    from fastapi.responses import HTMLResponse
    app.state.google_calendars=google
    def call(action):
        try:return action()
        except HomeUnavailable as error:raise HTTPException(503,str(error)) from None

    @app.get('/v1/calendar/google',dependencies=[Depends(owner)])
    def settings():return call(google.settings)

    @app.put('/v1/calendar/google',dependencies=[Depends(owner)])
    def configure(body:GoogleConfig):return call(lambda:google.configure(body))

    @app.post('/v1/calendar/google/flows',dependencies=[Depends(owner)])
    def begin(body:BeginFlow,principal=Depends(authorize)):return call(lambda:google.begin(body.label,principal,body.client,body.write_access))

    @app.get('/v1/calendar/google/flows/{identifier}',dependencies=[Depends(owner)])
    def flow(identifier:str,client:str=Query(pattern=r'^[a-f0-9]{64}$'),principal=Depends(authorize)):return google.flow_status(identifier,principal,client)

    @app.delete('/v1/calendar/google/flows/{identifier}',dependencies=[Depends(owner)])
    def cancel(identifier:str,body:FlowClient,principal=Depends(authorize)):return google.cancel(identifier,principal,body.client)

    @app.post('/v1/calendar/google/flows/{identifier}/finish',dependencies=[Depends(owner)])
    def finish(identifier:str,body:FlowClient,principal=Depends(authorize)):return call(lambda:google.finish(identifier,principal,body.client))

    @app.get(CALLBACK)
    def callback(state:str=Query(min_length=32,max_length=128),code:str=Query(default='',max_length=4096),error:str=Query(default='',max_length=120)):
        call(lambda:google.callback(state,code,error))
        return HTMLResponse('<!doctype html><html lang="en"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Echo · Google sign-in</title><h1>Return to Echo Settings.</h1><p>Your sign-in response was received. Return to the Echo tab where you started and choose Finish connecting. You may close this tab.</p></html>')

    @app.post('/v1/calendar/google/accounts/{identifier}/sync',dependencies=[Depends(owner)])
    def sync(identifier:str):return call(lambda:google.sync(identifier))

    @app.delete('/v1/calendar/google/accounts/{identifier}',dependencies=[Depends(owner)])
    def disconnect(identifier:str):return call(lambda:google.disconnect(identifier))
