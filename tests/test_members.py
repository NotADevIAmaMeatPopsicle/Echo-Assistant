"""Personal accounts exercised through the real API, using synthetic data only."""
from pathlib import Path
import unittest
from unittest.mock import patch,Mock
from fastapi import HTTPException
from backend.display_profiles import DisplayProfile
from backend.members import Members
from tests import test_display_profiles as fixtures


class MemberTests(unittest.TestCase):
    setUp=fixtures.DisplayProfileTests.setUp
    enroll=fixtures.DisplayProfileTests.enroll
    save=fixtures.DisplayProfileTests.save
    profile=fixtures.DisplayProfileTests.profile

    def account(self,name='Alex'):
        r=self.client.post('/v1/members',headers=self.owner,json={'name':name})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def share(self,*accounts):
        current=self.client.get('/v1/display/session',headers=self.guest).json()
        profile=DisplayProfile(members=[a['id'] for a in accounts]).model_dump()
        self.assertEqual(self.save(profile,current['profile_revision']).status_code,200)

    def login(self,account):
        r=self.client.post('/v1/member/session',headers=self.guest,json={'member':account['id'],'passcode':account['passcode']})
        self.assertEqual(r.status_code,200,r.text)
        return {**self.guest,'X-Echo-Profile-Revision':str(r.json()['profile_revision'])}

    def test_account_assignment_and_no_secret_roster(self):
        a=self.account()
        self.assertEqual(self.client.post('/v1/member/session',headers=self.guest,json={'member':a['id'],'passcode':a['passcode']}).status_code,403)
        self.assertNotIn(a['passcode'],self.client.get('/v1/members',headers=self.owner).text)
        self.share(a);headers=self.login(a)
        for path in ['/v1/members','/v1/settings','/v1/household']:
            self.assertEqual(self.client.get(path,headers=headers).status_code,403,path)
        self.assertEqual(self.client.get('/v1/memory',headers=self.guest).status_code,409)

    def test_separate_memory_and_stale_request_cannot_write_next_account(self):
        a,b=self.account(),self.account('Blair');self.share(a,b)
        old=self.login(a)
        item=self.client.post('/v1/memory',headers=old,json={'text':'Alex likes astronomy'}).json()['item']
        self.client.delete('/v1/member/session',headers=old)
        new=self.login(b)
        self.assertEqual(self.client.get('/v1/memory',headers=new).json()['items'],[])
        self.assertEqual(self.client.post('/v1/memory',headers=old,json={'text':'Wrong account'}).status_code,409)
        self.assertEqual(self.client.delete('/v1/memory/'+item['id'],headers=new).status_code,404)
        self.client.delete('/v1/member/session',headers=new)
        self.assertEqual(self.client.get('/v1/memory',headers=self.owner).json()['items'],[])
        self.assertEqual(self.client.get('/v1/memory',headers=self.login(a)).json()['items'][0]['text'],'Alex likes astronomy')

    def test_provider_uses_personal_facts_and_personality_without_hermes(self):
        a=self.account();self.share(a);headers=self.login(a)
        self.client.post('/v1/memory',headers=headers,json={'text':'Alex likes astronomy'})
        self.client.post('/v1/memory',headers=self.owner,json={'text':'PRIVATE HOUSEHOLD MEMORY'})
        with patch('backend.agent.HermesRuntime.complete',side_effect=AssertionError('Personal request used shared Hermes')):
            r=self.client.post('/v1/chat',headers=headers,json={'text':'Tell me about astronomy'})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['status'],'complete',r.text)
        args,kwargs=self.provider.complete.call_args
        self.assertNotIn('PRIVATE',str(args)+str(kwargs));self.assertIn('Alex likes astronomy',str(kwargs))
        self.assertEqual(args[0].agent_runtime,'direct')

    def test_expiry_revokes_captured_principal_memory_and_request(self):
        a=self.account();self.share(a);headers=self.login(a);members=self.app.state.members
        principal=members.resolve('display:'+self.paired['id']);memory=members.memory(principal)
        with patch.object(members,'clock',return_value=members.clock()+901):
            with self.assertRaises(HTTPException):memory.save('Expired write')
            self.assertEqual(self.client.post('/v1/chat',headers=headers,json={'text':'Hello'}).status_code,409)
        self.assertEqual(members.records[a['id']]['memory'],[])

    def test_encryption_restart_lockout_reset_and_delete(self):
        members=Members(self.root,self.protector);members.base_profile=lambda _: {'profile':DisplayProfile().model_dump(),'profile_revision':0}
        a=members.create('Synthetic account');p=members.login('owner',a['id'],a['passcode']);members.memory(p).save('Synthetic private fact')
        raw=members.path.read_text();self.assertNotIn(a['passcode'],raw);self.assertNotIn('Synthetic',raw)
        for _ in range(5):
            with self.assertRaises(HTTPException):members.login('owner',a['id'],'invalid')
        loaded=Members(self.root,self.protector);loaded.base_profile=members.base_profile
        self.assertEqual(loaded.sessions,{})
        self.assertEqual(loaded.records[a['id']]['memory'][0]['text'],'Synthetic private fact')
        with self.assertRaises(HTTPException) as error:loaded.login('owner',a['id'],a['passcode'])
        self.assertEqual(error.exception.status_code,429)
        reset=loaded.change(a['id'],0,reset=True);p=loaded.login('owner',a['id'],reset['passcode']);memory=loaded.memory(p)
        loaded.change(a['id'],1,delete=True)
        with self.assertRaises(HTTPException):memory.snapshot()
        self.assertEqual(Members(self.root,self.protector).records,{})

    def test_member_and_display_grants_intersect(self):
        a=self.account();profile=self.profile(home_voice=True,home_devices={'light.private':'control','light.guest':'control'})
        self.assertEqual(self.client.put('/v1/members/'+a['id']+'/profile',headers=self.owner,json={'revision':0,'profile':profile}).status_code,200)
        self.save(self.profile(members=[a['id']],home_voice=False,home_devices={'light.guest':'read'}))
        self.login(a);principal=self.app.state.members.resolve('display:'+self.paired['id']);effective=self.app.state.members.profile_for(principal)['profile']
        self.assertEqual(effective['home_devices'],{'light.guest':'read'});self.assertFalse(effective['home_voice'])

    def test_logout_during_synthesis_discards_audio(self):
        from backend.display_voice import wave_bytes
        a=self.account();self.share(a);headers=self.login(a);pipeline=self.app.state.display_voice
        pipeline.injected=True;pipeline.worker=Mock();pipeline.worker.transcribe.return_value='Explain the Moon'
        def synthesize(*args,**kwargs):
            self.app.state.members.lock_session('display:'+self.paired['id'])
            return bytes(9600),{'sample_rate':48000}
        pipeline.synthesizer=synthesize
        r=self.client.post('/v1/display/voice',headers={**headers,'Content-Type':'audio/wav'},content=wave_bytes(bytes(3200),16000))
        self.assertIn(r.status_code,[401,409]);self.assertNotIn('"audio"',r.text)

if __name__=='__main__':unittest.main()
