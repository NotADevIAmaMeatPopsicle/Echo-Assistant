"""Bounded Mini account UI transport. Passcodes are never included in status/logs."""
import re
import httpx


class RoundMembers:
    def __init__(self,access,base,worker,write):
        self.access,self.base,self.worker,self.write=access,base,worker,write
        self.pending=None;self.epoch=0
    def changed(self):
        self.epoch+=1
        if self.pending:self.pending[0].cancel()
        self.pending=None
    def receive(self,line):
        if not self.access.members:return False
        if line=='EVENT account_list':kind='list';body=None
        elif line=='EVENT account_lock':kind='lock';body={}
        else:
            match=re.fullmatch(r'EVENT account_login=([a-f0-9]{32}) code=([0-9]{8})',line)
            if not match:return False
            kind='login';body={'member':match[1],'passcode':match[2]}
        if self.pending:
            self.write(b'ACCOUNT_ERROR :Please wait\n');return True
        client=self.access.client(self.base)
        def request():
            path='/v1/members/available' if kind=='list' else '/v1/member/session'
            response=client.request('GET' if kind=='list' else 'DELETE' if kind=='lock' else 'POST',path,**({} if body is None else {'json':body}))
            if response.status_code==429:return {'error':'Wait five minutes'}
            if response.status_code==401:return {'error':'Passcode not accepted'}
            if response.status_code==409:return {'error':'Wait, then try again'}
            if response.status_code!=200:return {'error':'Account unavailable'}
            return response.json()
        self.pending=(self.worker.submit(request),kind,self.epoch);return True
    def pump(self):
        if not self.pending or not self.pending[0].done():return
        task,kind,epoch=self.pending;self.pending=None
        if epoch!=self.epoch:return
        try:value=task.result()
        except (httpx.HTTPError,ValueError,KeyError,TypeError):value={'error':'Host unavailable'}
        if value.get('error'):
            self.write(('ACCOUNT_ERROR :'+value['error']+'\n').encode('ascii'));return
        if kind!='list':
            self.access.next_poll=0;self.write(b'ACCOUNT_DONE\n');return
        items=value.get('items',[])
        if not isinstance(items,list) or len(items)>16:self.write(b'ACCOUNT_ERROR :Account unavailable\n');return
        self.write(f'ACCOUNT_LIST {len(items)}\n'.encode('ascii'))
        for index,item in enumerate(items):
            identifier=item.get('id','');name=re.sub(r'[^ -~]','',str(item.get('name','')))[:24] or 'Account'
            if not re.fullmatch('[a-f0-9]{32}',identifier):self.write(b'ACCOUNT_ERROR :Account unavailable\n');return
            self.write(f'ACCOUNT_ITEM {index} {identifier} :{name}\n'.encode('ascii'))
