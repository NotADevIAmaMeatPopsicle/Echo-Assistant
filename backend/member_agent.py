"""Personal memory and temporary conversations, with explicitly scoped home commands."""
from .agent import EchoAgent
from .lookup import lookup_request
from .settings import PERSONALITY


class MemberSettings:
    def __init__(self,store,members,identifier):
        self.store,self.members,self.identifier=store,members,identifier
        self.path=None;self.protector=store.protector
    @property
    def revision(self):
        # Read the atomically replaced record without acquiring members.lock while
        # EchoAgent holds history_lock (sign-out clears history in reverse order).
        return self.store.revision,self.members.records.get(self.identifier,{}).get('revision',-1)
    def snapshot(self):
        settings,keys,revision=self.store.snapshot()
        with self.members.lock:
            item=self.members.item(self.identifier);prefs=item['preferences']
            personality=PERSONALITY+' This is a personal conversation. Saved facts belong only to this account. Never claim access to household lists, files, calendars or Hermes tools.'
            if prefs['personality']:personality+='\nPersonal preferences:\n'+prefs['personality']
            return settings.model_copy(update={'agent_runtime':'direct','personality':personality,
                'memory_enabled':settings.memory_enabled and prefs['memory_enabled']}),keys,(revision,item['revision'])


class MemberAgents:
    def __init__(self,members,store,provider,home,assistant):
        self.members,self.store,self.provider,self.home,self.assistant=members,store,provider,home,assistant
        self.agents={}
    def agent(self,principal):
        with self.members.lock:
            self.members.current(principal)
            if principal.nonce not in self.agents:
                agent=EchoAgent(MemberSettings(self.store,self.members,principal.member),self.provider,self.members.memory(principal))
                agent.local_assistant=self.assistant
                self.agents[principal.nonce]=agent
            return self.agents[principal.nonce]
    def respond(self,text,principal,lookup=False,*,before,**kwargs):
        self.members.current(principal)
        if self.home and not lookup and not lookup_request(text):
            result=self.home.respond(text,principal,before,allow_home=kwargs.get('allow_home_actions',False),cancel=kwargs.get('cancel'))
            if result is not None:return result
        kwargs.update(allow_home_actions=False,calendar_review=False)
        return self.agent(principal).respond(text,principal,lookup,**kwargs)
    def clear(self,principal):
        agent=self.agents.pop(principal.nonce,None)
        if agent:agent.clear(str(principal))
    def changed_memory(self,principal):
        for agent in list(self.agents.values()):
            if agent.store.identifier==principal.member:agent.clear()
