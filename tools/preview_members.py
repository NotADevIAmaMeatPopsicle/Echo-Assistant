"""In-memory accounts for the isolated, synthetic display demonstration."""
from backend.display_profiles import DisplayProfile
from backend.members import Members,PersonalPrincipal,MemberPreferences


class PreviewMembers:
    def __init__(self):
        self.store=Members(None,None)
        self.store.base_profile=lambda _: {'profile':DisplayProfile().model_dump(),'profile_revision':0}

    def read(self,path):
        principal=self.store.resolve('demo')
        if path=='/v1/display/session':
            return {'role':'display',**self.store.profile_for(principal)} if isinstance(principal,PersonalPrincipal) else {'role':'owner','profile_revision':0}
        if path=='/v1/members':return {'items':self.store.roster(),'limit':16}
        if path=='/v1/members/available':return {'items':self.store.available('demo'),'session_minutes':15,'supported':True}
        if isinstance(principal,PersonalPrincipal):
            if path=='/v1/member/preferences':return self.store.preferences(principal)
            if path=='/v1/memory':return {'items':self.store.memory(principal).snapshot(),'scope':'personal'}
        return None

    def mutate(self,method,path,body):
        principal=self.store.resolve('demo')
        if path=='/v1/members' and method=='POST':return self.store.create(body['name'])
        if path.startswith('/v1/members/'):
            parts=path.split('/');identifier=parts[3]
            if path.endswith('/profile'):return self.store.change(identifier,body['revision'],profile=DisplayProfile.model_validate(body['profile']))
            if path.endswith('/passcode'):return self.store.change(identifier,body['revision'],reset=True)
            if method=='DELETE':return self.store.change(identifier,body['revision'],delete=True)
        if path=='/v1/member/session':
            if method=='DELETE':self.store.lock_session('demo');return {'locked':True}
            return self.store.profile_for(self.store.login('demo',body['member'],body['passcode']))
        if isinstance(principal,PersonalPrincipal):
            if path=='/v1/member/preferences':return self.store.preferences(principal,MemberPreferences.model_validate(body))
            if path=='/v1/memory' and method=='POST':return {'item':self.store.memory(principal).save(body['text'])}
            if path.startswith('/v1/memory/') and method=='DELETE':self.store.memory(principal).delete(path.rsplit('/',1)[1]);return {'deleted':True}
        return None
