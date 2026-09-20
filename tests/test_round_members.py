"""Mini accounts use the real API and synthetic wire, never physical audio."""
from concurrent.futures import Future
from unittest import TestCase
from unittest.mock import patch
import httpx
from backend.display_profiles import DisplayProfile
from backend.round_access import RoundAccess,RemoteRoundProfile
from backend.round_members import RoundMembers
from backend.round_profile import RoundProfileUnavailable
from tests import test_display_profiles as fixtures


class RoundMemberTests(TestCase):
    with_runtime=True
    setUp=fixtures.DisplayProfileTests.setUp
    enroll=fixtures.DisplayProfileTests.enroll
    profile=fixtures.DisplayProfileTests.profile

    def headers(self,revision=0):return {**self.owner,'X-Echo-Endpoint':'round','X-Echo-Access-Revision':str(revision)}
    def account(self):return self.client.post('/v1/members',headers=self.owner,json={'name':'Alex'}).json()
    def share(self,a,ready=True):
        self.app.state.members.round_ready=lambda:ready
        return self.client.put('/v1/round/profile',headers=self.owner,json={'revision':0,'profile':DisplayProfile(members=[a['id']]).model_dump()})
    def login(self,a):
        r=self.client.post('/v1/member/session',headers=self.headers(1),json={'member':a['id'],'passcode':a['passcode']})
        self.assertEqual(r.status_code,200,r.text)
        return self.headers(r.json()['profile_revision'])

    def test_firmware_gate_and_explicit_assignment(self):
        a=self.account();self.assertEqual(self.share(a,False).status_code,409)
        self.assertEqual(self.client.get('/v1/members/available',headers=self.headers()).json()['items'],[])
        self.assertEqual(self.share(a).status_code,200)
        self.assertEqual(self.client.get('/v1/members/available',headers=self.headers(1)).json()['items'][0]['id'],a['id'])
        self.assertEqual(self.client.get('/v1/round/session',headers=self.owner).status_code,403)

    def test_mini_memory_persists_in_same_account_and_never_reaches_hermes(self):
        a=self.account();self.share(a);headers=self.login(a)
        with patch('backend.agent.HermesRuntime.complete',side_effect=AssertionError('Personal Mini reached shared Hermes')):
            r=self.client.post('/v1/text',headers=headers,json={'text':'Remember that I enjoy astronomy'})
            self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['capability'],'memory')
            self.assertEqual(self.client.post('/v1/text',headers=headers,json={'text':'Tell me about astronomy'}).json()['status'],'complete')
        self.assertEqual(self.client.get('/v1/memory',headers=self.owner).json()['items'],[])
        endpoint=self.paired['id'];profile=DisplayProfile(members=[a['id']]).model_dump()
        self.client.put('/v1/displays/'+endpoint+'/profile',headers=self.owner,json={'revision':0,'profile':profile}).raise_for_status()
        result=self.client.post('/v1/member/session',headers=self.guest,json={'member':a['id'],'passcode':a['passcode']}).json()
        deck={**self.guest,'X-Echo-Profile-Revision':str(result['profile_revision'])}
        self.assertIn('astronomy',self.client.get('/v1/memory',headers=deck).json()['items'][0]['text'])
        for path in ['/v1/tasks','/v1/household','/v1/music/groups','/v1/settings']:
            self.assertEqual(self.client.get(path,headers=headers).status_code,403,path)

    def test_personal_cards_filter_base_household_and_disable_read_only_actions(self):
        a=self.account();self.share(a)
        self.client.put('/v1/members/'+a['id']+'/profile',headers=self.owner,json={'revision':0,'profile':self.profile(home_devices={'light.guest':'read'})}).raise_for_status()
        headers=self.login(a);r=self.client.get('/v1/home',headers=headers)
        self.assertEqual(r.status_code,200,r.text);self.assertNotIn('private',r.text.lower())
        self.assertEqual(r.json()['permissions']['lights'],0)
        self.assertEqual(r.json()['speakers']['choices'],[])

    def test_logout_and_lost_firmware_invalidate_old_queued_requests(self):
        a=self.account();self.share(a);headers=self.login(a)
        state=self.client.get('/v1/round/session',headers=self.headers(1)).json()
        self.assertTrue(state['profile']['personal']);self.assertLess(state['profile_revision'],2**53)
        self.client.delete('/v1/member/session',headers=headers).raise_for_status()
        self.assertEqual(self.client.post('/v1/text',headers=headers,json={'text':'Remember old data'}).status_code,409)
        headers=self.login(a);self.app.state.members.round_ready=lambda:False
        self.assertFalse(self.client.get('/v1/round/session',headers=headers).json()['profile'].get('personal',False))
        self.assertEqual(self.client.post('/v1/text',headers=headers,json={'text':'Hello'}).status_code,409)


class DeferredWorker:
    def __init__(self):self.futures=[]
    def submit(self,fn):
        future=Future();self.futures.append((future,fn));return future


class RoundAccountTransportTests(TestCase):
    def test_remote_refresh_does_not_block_audio_and_stale_cache_fails_closed(self):
        worker=DeferredWorker();now=[0.0]
        with httpx.Client(base_url='http://test',transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'profile':DisplayProfile().model_dump(),'profile_revision':4}))) as client:
            remote=RemoteRoundProfile(client,worker,clock=lambda:now[0])
            with self.assertRaises(RoundProfileUnavailable):remote.snapshot()
            self.assertEqual(len(worker.futures),1)
            future,fn=worker.futures[0];future.set_result(fn());self.assertEqual(remote.snapshot()['profile_revision'],4)
            now[0]=3
            with self.assertRaises(RoundProfileUnavailable):remote.snapshot()
            self.assertEqual(len(worker.futures),2)

    def test_wire_login_redacts_code_and_retains_captured_revision(self):
        captured=[];wire=[];worker=DeferredWorker()
        class Store:
            def snapshot(self):return {'profile':DisplayProfile().model_dump(),'profile_revision':7}
        access=RoundAccess(None,store=Store());access.observe('STATUS access_profile=1 member_accounts=1')
        with httpx.Client(base_url='http://test',transport=httpx.MockTransport(lambda r:(captured.append(r) or httpx.Response(401,json={'detail':'do not forward arbitrary server text'})))) as client:
            adapter=RoundMembers(access,client,worker,wire.append)
            self.assertTrue(adapter.receive('EVENT account_login='+'a'*32+' code=12345678'))
            access.state['profile_revision']=8
            future,fn=worker.futures[0];future.set_result(fn());adapter.pump()
            self.assertEqual(captured[0].headers['X-Echo-Access-Revision'],'7')
            self.assertEqual(wire,[b'ACCOUNT_ERROR :Passcode not accepted\n'])
            self.assertNotIn('12345678',str(wire)+str(access.health()))

    def test_wire_personal_revision_and_obsolete_list_are_discarded(self):
        worker=DeferredWorker();wire=[]
        class Store:
            def snapshot(self):return {'profile':{**DisplayProfile(mode='guest').model_dump(),'personal':True,'name':'Alex'},'profile_revision':2**48+1}
        access=RoundAccess(None,store=Store());access.observe('STATUS access_profile=1 member_accounts=1');access.configure(wire.append)
        self.assertEqual(wire,[f'PROFILE_SET {2**48+1} 2 1 :Alex\n'.encode()])
        with httpx.Client(base_url='http://test') as client:
            adapter=RoundMembers(access,client,worker,wire.append);adapter.receive('EVENT account_list');adapter.changed();adapter.pump()
        self.assertEqual(len(wire),1)
