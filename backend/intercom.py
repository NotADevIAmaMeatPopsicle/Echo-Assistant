"""Private live intercom. Calls and subsecond audio buffers exist only in memory."""
from collections import deque
import struct
import time
import uuid


class IntercomConflict(ValueError):pass
class IntercomDenied(PermissionError):pass


class Intercom:
    def __init__(self,rooms,clock=time.monotonic):
        self.rooms,self.clock,self.lock=rooms,clock,rooms.lock
        self.calls={};self.receivers={};self.streams={}
        rooms.intercom_busy=self.busy

    def policy(self):
        self.rooms.require()
        ids=self.rooms.current_ids()
        return {r['id']:r for r in self.rooms.state['policy']['endpoints'] if r['id'] in ids and r['calls_enabled']}

    def busy(self,endpoint):
        with self.lock:
            self.prune()
            return any(c['status']!='ended' and endpoint in (c['caller'],c['callee']) for c in self.calls.values())

    def finish(self,call,reason):
        if call['status']=='ended':return
        call.update(status='ended',reason=reason,ended=self.clock())
        for queue in call['audio'].values():queue.clear()
        for key in list(self.streams):
            if key[0]==call['id']:del self.streams[key]

    def prune(self):
        now=self.clock();policy=self.policy()
        for identifier,call in list(self.calls.items()):
            if call['status']=='ended':
                if now-call['ended']>600:del self.calls[identifier]
                continue
            if not {call['caller'],call['callee']}<=policy.keys():self.finish(call,'access_removed');continue
            if call['status']=='ringing' and now-call['created']>30:self.finish(call,'no_answer');continue
            if call['status']=='active' and now-call['accepted']>900:self.finish(call,'time_limit');continue
            for endpoint in (call['caller'],call['callee']):
                beat=self.receivers.get(endpoint,{})
                if now-beat.get('at',0)>10 or not beat.get('enabled'):
                    self.finish(call,'disconnected');break
                selected=call['clients'].get(endpoint)
                if selected and selected!=beat['client']:self.finish(call,'session_changed');break

    def readiness(self,endpoint,client=None,*,ignore_call=False):
        if endpoint not in self.policy():return False,'disabled'
        if self.rooms.schedules.snapshot()['quiet_active']:return False,'quiet_hours'
        beat=self.receivers.get(endpoint,{})
        if self.clock()-beat.get('at',0)>10:return False,'offline'
        if client and beat.get('client')!=client:return False,'another_session'
        if not beat.get('enabled'):return False,'calls_off'
        if beat.get('busy'):return False,'busy'
        if not ignore_call and self.busy(endpoint):return False,'in_call'
        if endpoint=='round':
            voice=self.rooms.voice()
            if voice.get('device',{}).get('intercom')!='1':return False,'firmware_update'
            if voice.get('muted'):return False,'muted'
            if voice.get('status') not in {'armed','music','intercom'}:return False,'busy_or_offline'
        return True,'ready'

    def snapshot(self,endpoint,client):
        with self.lock:
            self.prune();policy=self.policy();ready,status=self.readiness(endpoint,client)
            call=next((c for c in reversed(list(self.calls.values())) if endpoint in (c['caller'],c['callee']) and
                       (not c['clients'].get(endpoint) or c['clients'][endpoint]==client)),None)
            result={'enabled':endpoint in policy,'ready':ready,'status':status,'revision':self.rooms.state['revision'],
                    'call':self.view(call,endpoint) if call else None,'rooms':[]}
            for identifier,config in policy.items():
                if identifier==endpoint:continue
                can_call,reason=self.readiness(identifier)
                result['rooms'].append({'id':identifier,'room':config['room'],'ready':can_call,'status':reason})
            return result

    def view(self,call,endpoint):
        peer=call['callee'] if endpoint==call['caller'] else call['caller']
        room=self.policy().get(peer,{}).get('room','Other room')
        return {'id':call['id'],'direction':'outgoing' if endpoint==call['caller'] else 'incoming',
                'peer':peer,'room':room,'status':call['status'],'reason':call['reason'],
                'seconds':max(0,int(self.clock()-(call['accepted'] or call['created']))),
                'muted':call['muted'].get(endpoint,True),'peer_muted':call['muted'].get(peer,True)}

    def heartbeat(self,endpoint,client,enabled,busy):
        with self.lock:
            previous=self.receivers.get(endpoint,{})
            if previous.get('client')!=client and previous.get('enabled') and self.clock()-previous.get('at',0)<10:
                return self.snapshot(endpoint,client)
            self.receivers[endpoint]={'client':client,'enabled':enabled,'busy':busy,'at':self.clock()}
            return self.snapshot(endpoint,client)

    def start(self,endpoint,client,identifier,target,revision):
        with self.lock:
            self.prune()
            existing=self.calls.get(identifier)
            if existing:
                if (existing['caller'],existing['clients'].get(endpoint),existing['callee'])!=(endpoint,client,target):raise IntercomConflict('This request belongs to another call')
                return self.view(existing,endpoint)
            if revision!=self.rooms.state['revision']:raise IntercomConflict('Room permissions changed. Reload before calling.')
            if target==endpoint:raise IntercomConflict('Choose another room')
            if not self.readiness(endpoint,client)[0] or not self.readiness(target)[0]:raise IntercomConflict('One of the rooms is unavailable or already in a call')
            if len(self.calls)>=128:raise IntercomConflict('Recent call limit reached. Try again in a few minutes.')
            now=self.clock()
            call={'id':identifier,'caller':endpoint,'callee':target,'clients':{endpoint:client,target:None},
                  'status':'ringing','created':now,'accepted':None,'ended':None,'reason':None,
                  'audio':{endpoint:deque(),target:deque()},'muted':{endpoint:True,target:True},
                  'last_seq':{endpoint:-1,target:-1},'rate':{endpoint:[now,16000.],target:[now,16000.]}}
            self.calls[identifier]=call;return self.view(call,endpoint)

    def participant(self,identifier,endpoint,client):
        self.prune();call=self.calls.get(identifier)
        if not call or endpoint not in (call['caller'],call['callee']):raise IntercomDenied('This call belongs to other rooms')
        selected=call['clients'].get(endpoint)
        if selected and selected!=client:raise IntercomDenied('This call belongs to another session')
        if self.receivers.get(endpoint,{}).get('client')!=client:raise IntercomDenied('Enable calls in this session first')
        return call

    def accept(self,identifier,endpoint,client):
        with self.lock:
            call=self.participant(identifier,endpoint,client)
            if endpoint!=call['callee']:raise IntercomDenied('Only the receiving room can answer')
            if call['status']=='active':return self.view(call,endpoint)
            if call['status']!='ringing' or not self.readiness(endpoint,client,ignore_call=True)[0]:raise IntercomConflict('This call can no longer be answered')
            call['clients'][endpoint]=client;call.update(status='active',accepted=self.clock())
            return self.view(call,endpoint)

    def end(self,identifier,endpoint,client,reason='hangup'):
        with self.lock:
            call=self.participant(identifier,endpoint,client);self.finish(call,reason);return self.view(call,endpoint)

    def mute(self,identifier,endpoint,client,muted):
        with self.lock:
            call=self.participant(identifier,endpoint,client)
            if call['status']!='active':raise IntercomConflict('No active call')
            call['muted'][endpoint]=muted
            if muted:call['audio'][endpoint].clear()
            return self.view(call,endpoint)

    def active(self,identifier,endpoint,client):
        call=self.participant(identifier,endpoint,client)
        if call['status']!='active':raise IntercomConflict('Call is not active')
        return call

    def push(self,identifier,endpoint,client,sequence,pcm):
        if not 640<=len(pcm)<=6400 or len(pcm)%2:raise ValueError('Send 20–200 ms of mono 16 kHz PCM')
        with self.lock:
            call=self.active(identifier,endpoint,client)
            if call['muted'][endpoint]:raise IntercomConflict('Microphone is muted')
            if sequence<=call['last_seq'][endpoint]:return  # A lost acknowledgement cannot replay audio.
            now=self.clock();rate=call['rate'][endpoint];tokens=min(16000.,rate[1]+max(0,now-rate[0])*32000)
            if len(pcm)>tokens:raise IntercomConflict('Audio is arriving faster than real time')
            call['rate'][endpoint]=[now,tokens-len(pcm)];call['last_seq'][endpoint]=sequence
            queue=call['audio'][endpoint]
            queue.append((now,sequence,bytes(pcm)))
            while len(queue)>25 or queue and now-queue[0][0]>.5:queue.popleft()

    def open_stream(self,identifier,endpoint,client):
        with self.lock:
            self.active(identifier,endpoint,client);key=(identifier,endpoint);previous=self.streams.get(key)
            if previous and self.clock()-previous[1]<3:raise IntercomConflict('This room already has an audio stream')
            marker=uuid.uuid4().hex;self.streams[key]=(marker,self.clock());return marker

    def pull(self,identifier,endpoint,client,marker):
        with self.lock:
            call=self.active(identifier,endpoint,client);key=(identifier,endpoint)
            if self.streams.get(key,(None,))[0]!=marker:raise IntercomConflict('Audio stream was replaced')
            now=self.clock();self.streams[key]=(marker,now)
            peer=call['callee'] if endpoint==call['caller'] else call['caller'];queue=call['audio'][peer]
            data=[]
            while queue:
                captured,sequence,pcm=queue.popleft()
                if now-captured<=.5:data.append(struct.pack('<II',sequence,len(pcm))+pcm)
            return b''.join(data)

    def close_stream(self,identifier,endpoint,marker):
        with self.lock:
            key=(identifier,endpoint)
            if self.streams.get(key,(None,))[0]==marker:del self.streams[key]
