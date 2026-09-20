"""Owner-managed Mini profile, stored encrypted and shared by API/voice processes."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import re
from threading import RLock

from fastapi import HTTPException
from .display_profiles import DisplayProfile,guest_allowed


class RoundProfileUnavailable(RuntimeError):pass


class RoundProfile:
    def __init__(self,root,protector):
        self.path=Path(root)/'local/echo-round-profile.json' if root else None
        self.protector,self.lock=protector,RLock()
        self.current={'profile':DisplayProfile().model_dump(),'profile_revision':0}
        self.stamp=None

    def snapshot(self):
        with self.lock:
            if self.path:
                try:
                    if self.path.exists():
                        stat=self.path.stat();stamp=(stat.st_mtime_ns,stat.st_size)
                        if stat.st_size>100000:raise ValueError()
                        if stamp!=self.stamp:
                            envelope=json.loads(self.path.read_text())
                            if envelope['version']!=1:raise ValueError()
                            value=json.loads(self.protector.decrypt(base64.b64decode(envelope['protected'],validate=True)))
                            if set(value)!={'profile','profile_revision'} or type(value['profile_revision']) is not int or value['profile_revision']<0:raise ValueError()
                            value['profile']=DisplayProfile.model_validate(value['profile']).model_dump()
                            self.current=value;self.stamp=stamp
                    elif self.stamp is not None:
                        # Removing a saved policy must not silently restore household access.
                        raise ValueError()
                except (OSError,ValueError,KeyError,TypeError,RuntimeError):
                    raise RoundProfileUnavailable('Mini access could not be read. Restore its saved profile before using it.') from None
            return deepcopy(self.current)

    def save(self,profile,revision):
        with self.lock:
            if self.snapshot()['profile_revision']!=revision:raise HTTPException(409,'Mini access changed. Reload before saving.')
            value={'profile':DisplayProfile.model_validate(profile).model_dump(),'profile_revision':revision+1}
            if self.path:
                try:
                    self.path.parent.mkdir(parents=True,exist_ok=True)
                    document={'version':1,'protected':base64.b64encode(self.protector.encrypt(json.dumps(value).encode())).decode()}
                    temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps(document));temporary.replace(self.path)
                except (OSError,RuntimeError):raise RoundProfileUnavailable('Mini access could not be saved.') from None
            self.current=value;self.stamp=None
            return self.snapshot()

    def authorize(self,request):
        from .display_auth import allowed
        path=request.url.path;method=request.method;state=self.snapshot();profile=state['profile']
        # Only the authenticated host uses this endpoint identity. It is never an
        # alternate credential for a browser or firmware; the board has no API key.
        permitted=allowed(method,path) or method=='POST' and path=='/v1/text'
        if path=='/v1/round/profile' and method=='GET':return 'round'
        if request.headers.get('x-echo-access-revision')!=str(state['profile_revision']):
            raise HTTPException(409,'Mini access changed. Wait for its controls to refresh.')
        if not permitted:raise HTTPException(403,'Use the owner workspace to administer Echo')
        if profile['mode']=='guest':
            if method=='POST' and path=='/v1/text':permitted=profile['conversation']
            elif method=='POST' and (path in {'/v1/home/thermostat/actions','/v1/home/soundbar/actions','/v1/home/speakers/select','/v1/home/speakers/control'} or re.fullmatch(r'/v1/home/rooms/(bedroom|living_room|dining_room|patio)/actions',path)):
                permitted=True  # The Mini home projection checks exact entity grants.
            else:permitted=guest_allowed(method,path,profile)
            if not permitted:raise HTTPException(403,'This feature is not shared with Echo Mini')
        return 'round'
