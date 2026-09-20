"""Owner account administration and endpoint-bound personal sign-in."""
from fastapi import Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from .display_profiles import DisplayProfile
from .members import MemberPreferences,PersonalPrincipal


class CreateMember(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    name:str=Field(min_length=1,max_length=60)


class MemberLogin(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    member:str=Field(pattern=r'^[a-f0-9]{32}$')
    passcode:str=Field(min_length=1,max_length=32)


class MemberChange(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision:int=Field(ge=0)


class MemberGrants(MemberChange):
    profile:DisplayProfile


def install(app,members,personal,authorize,owner,validate,conversations,clear_shared):
    @app.get('/v1/members',dependencies=[Depends(owner)])
    def roster():return {'items':members.roster(),'limit':16}

    @app.post('/v1/members',dependencies=[Depends(owner)])
    def create(body:CreateMember):
        try:return members.create(body.name)
        except ValueError as error:raise HTTPException(422,str(error)) from None

    @app.put('/v1/members/{identifier}/profile',dependencies=[Depends(owner)])
    def grants(identifier:str,body:MemberGrants):
        with members.lock:
            previous=members.item(identifier)
            validate(body.profile.model_dump(),{'profile':previous['profile']})
            try:return members.change(identifier,body.revision,profile=body.profile)
            except ValueError as error:raise HTTPException(422,str(error)) from None

    @app.post('/v1/members/{identifier}/passcode',dependencies=[Depends(owner)])
    def reset(identifier:str,body:MemberChange):return members.change(identifier,body.revision,reset=True)

    @app.delete('/v1/members/{identifier}',dependencies=[Depends(owner)])
    def remove(identifier:str,body:MemberChange):
        result=members.change(identifier,body.revision,delete=True)
        return result

    @app.get('/v1/members/available')
    def available(principal=Depends(authorize)):
        return {'items':members.available(str(principal)),'session_minutes':15,'supported':principal!='round' or members.round_ready()}

    @app.post('/v1/member/session')
    def login(body:MemberLogin,principal=Depends(authorize)):
        with members.lock:
            if conversations.snapshot(str(principal)).get('active'):
                conversations.clear(str(principal));raise HTTPException(409,'The current request is stopping. Sign in when it finishes.')
            active=members.login(str(principal),body.member,body.passcode);clear_shared(str(principal))
            return members.profile_for(active)

    @app.delete('/v1/member/session')
    def logout(principal=Depends(authorize)):
        with members.lock:members.lock_session(str(principal))
        return {'locked':True}

    def personal_only(principal):
        if not isinstance(principal,PersonalPrincipal):raise HTTPException(403,'Sign in to your personal account first')

    @app.get('/v1/member/preferences')
    def preferences(principal=Depends(authorize)):
        personal_only(principal);return members.preferences(principal)

    @app.put('/v1/member/preferences')
    def save_preferences(body:MemberPreferences,principal=Depends(authorize)):
        personal_only(principal);personal.clear(principal)
        return members.preferences(principal,body)
