"""Personal Hermes contract against a fake provider; no live tools or credentials."""
import asyncio
from copy import deepcopy
import json
from threading import Event
import unittest
from unittest.mock import patch,Mock

import httpx
from backend.agent import ProviderUnavailable
from backend.member_agent import MemberAgents
from backend.member_hermes import MemberHermes,endpoint_url
from backend.members import Members
from tests import test_members as member_fixtures


TOKEN='personal-synthetic-credential-'*3


class PersonalHermesTests(unittest.TestCase):
    setUp=member_fixtures.MemberTests.setUp
    enroll=member_fixtures.MemberTests.enroll
    save=member_fixtures.MemberTests.save
    profile=member_fixtures.MemberTests.profile
    account=member_fixtures.MemberTests.account
    share=member_fixtures.MemberTests.share
    login=member_fixtures.MemberTests.login

    def config(self,a,**changes):
        body={'revision':self.app.state.members.records[a['id']]['revision'],'enabled':True,
              'url':'https://alex-agent.example','token':TOKEN,'isolation_confirmed':True,**changes}
        return self.client.put('/v1/members/'+a['id']+'/hermes',headers=self.owner,json=body)

    def personal(self):
        a=self.account();self.share(a)
        self.assertEqual(self.config(a).status_code,200)
        headers=self.login(a)
        self.assertEqual(self.client.put('/v1/member/preferences',headers=headers,json={
            'personality':'Explain gently','memory_enabled':True,'hermes_enabled':True}).status_code,200)
        principal=self.app.state.members.resolve('display:'+self.paired['id'])
        router=MemberAgents(self.app.state.members,self.settings,self.provider,None,None)
        return a,principal,router

    def respond(self,router,p,text='Explain astronomy',**kwargs):
        return router.respond(text,p,before=self.app.state.members.profile_for(p),**kwargs)

    def test_owner_only_redacted_setup_and_secret_validation(self):
        a=self.account();self.share(a);headers=self.login(a)
        path='/v1/members/'+a['id']+'/hermes'
        self.assertEqual(self.client.get(path,headers=headers).status_code,403)
        self.assertEqual(self.client.put(path,headers=headers,json={'revision':0}).status_code,403)
        r=self.config(a);self.assertEqual(r.status_code,200,r.text)
        self.assertNotIn(TOKEN,r.text)
        self.assertNotIn(TOKEN,self.client.get('/v1/members',headers=self.owner).text)
        self.assertNotIn(TOKEN,self.client.get(path,headers=self.owner).text)
        self.assertEqual(self.app.state.members.sessions,{})
        for changes in ({'token':'invalid-private-secret'},{'isolation_confirmed':False},
                        {'url':'https://user:private@example.com'},{'token':TOKEN+'\n'}):
            r=self.config(a,**changes);self.assertEqual(r.status_code,422,r.text)
            self.assertNotIn('invalid-private-secret',r.text);self.assertNotIn(TOKEN,r.text)
        headers=self.login(a)
        prefs=self.client.get('/v1/member/preferences',headers=headers).json()
        self.assertFalse(prefs['hermes_enabled']);self.assertNotIn('url',prefs['hermes']);self.assertNotIn('token',prefs['hermes'])

    def test_reject_shared_origins_tokens_household_and_stale_configuration(self):
        a,b=self.account(),self.account('Blair')
        self.assertEqual(self.config(a).status_code,200)
        self.assertEqual(self.config(b,token='blair-key-'*5).status_code,422)
        self.assertEqual(self.config(b,url='https://blair.example').status_code,422)
        self.assertEqual(self.config(b,url='http://127.0.0.1:18643',token='blair-key-'*5).status_code,422)
        self.assertEqual(self.config(a,revision=0).status_code,409)
        runtime=Mock();runtime.connection.return_value={'url':'https://household.example','token':'household-secret-'*3}
        hermes=MemberHermes(self.app.state.members,household_runtime=runtime)
        for url,token in [('https://household.example','different-key-'*5),('https://separate.example','household-secret-'*3)]:
            with self.assertRaises(ValueError):hermes.configure(b['id'],0,enabled=True,url=url,token=token,isolation_confirmed=True)
        self.assertEqual(endpoint_url('http://127.0.0.1:9999'),endpoint_url('http://[::1]:9999/'))

    def test_encrypted_restart_old_records_and_connection_removal(self):
        members=Members(self.root,self.protector)
        members.base_profile=lambda _: {'profile':self.profile(),'profile_revision':0}
        a=members.create('Private synthetic account')
        hermes=MemberHermes(members)
        hermes.configure(a['id'],0,enabled=True,url='https://alex-agent.example',token=TOKEN,isolation_confirmed=True)
        saved=members.path.read_text()
        for secret in (TOKEN,'alex-agent.example','Private synthetic'):self.assertNotIn(secret,saved)
        restored=Members(self.root,self.protector)
        self.assertFalse(restored.error);self.assertEqual(restored.sessions,{})
        self.assertEqual(restored.records[a['id']]['hermes']['token'],TOKEN)
        hermes.configure(a['id'],1,enabled=False,url='',token='',isolation_confirmed=False)
        self.assertIsNone(members.records[a['id']]['hermes'])
        old=deepcopy(members.records[a['id']]);old.pop('hermes');old['preferences'].pop('hermes_enabled')
        Members.validate(a['id'],old)

    def test_real_runs_protocol_isolated_payload_and_personal_fact_commands(self):
        a,p,router=self.personal();members=self.app.state.members
        members.memory(p).save('I like astronomy')
        calls=[]
        def fake(request):
            calls.append(request)
            if request.method=='POST':return httpx.Response(202,json={'run_id':'run_synthetic'})
            return httpx.Response(200,json={'status':'completed','output':'Personal stars','completed':True})
        router.hermes.transport=httpx.MockTransport(fake)
        with patch('backend.agent.HermesRuntime.complete',side_effect=AssertionError('Household runtime used')):
            reply=self.respond(router,p)
        self.assertEqual(reply['status'],'complete',reply);self.assertEqual(reply['text'],'Personal stars')
        self.provider.complete.assert_not_called()
        payload=json.loads(calls[0].content)
        self.assertEqual(calls[0].url.path,'/v1/runs');self.assertEqual(calls[1].url.path,'/v1/runs/run_synthetic')
        self.assertEqual(set(payload),{'input','instructions','conversation_history'})
        self.assertEqual(payload['conversation_history'],[]);self.assertNotIn('X-Hermes-Session-Key',calls[0].headers)
        self.assertIn('I like astronomy',payload['instructions']);self.assertIn('Explain gently',payload['instructions'])
        self.assertNotIn('PRIVATE HOUSEHOLD',str(payload));self.assertNotIn(TOKEN,str(payload))
        self.assertEqual(calls[0].headers['Authorization'],'Bearer '+TOKEN)
        self.assertEqual(self.respond(router,p,'Remember that I enjoy stars')['capability'],'memory')
        self.assertEqual(len(calls),2)

    def test_default_and_explicit_lookup_use_direct_provider(self):
        a=self.account();self.share(a);self.config(a);self.login(a)
        members=self.app.state.members;p=members.resolve('display:'+self.paired['id'])
        router=MemberAgents(members,self.settings,self.provider,None,None)
        router.hermes.complete=Mock(side_effect=AssertionError('Opt-in required'))
        self.assertEqual(self.respond(router,p)['status'],'complete')
        prefs=members.preferences(p);prefs['hermes_enabled']=True;members.preferences(p,prefs)
        self.assertEqual(self.respond(router,p,lookup=True)['status'],'complete')
        self.assertTrue(self.provider.complete.call_args.kwargs['lookup'])

    def test_two_people_use_distinct_endpoints_facts_and_histories(self):
        a,p,router=self.personal();members=self.app.state.members;b=self.account('Blair')
        other_token='blair-separate-credential-'*3
        self.assertEqual(self.config(b,url='https://blair-agent.example',token=other_token).status_code,200)
        other=members.login('owner-secondary',b['id'],b['passcode'])
        members.preferences(other,{'personality':'Brief replies','memory_enabled':True,'hermes_enabled':True})
        members.memory(p).save('I enjoy astronomy');members.memory(other).save('I enjoy pottery')
        calls=[]
        def fake(request):
            calls.append(request)
            if request.method=='POST':return httpx.Response(202,json={'run_id':'run_separate'})
            return httpx.Response(200,json={'status':'completed','output':'A separate answer'})
        router.hermes.transport=httpx.MockTransport(fake)
        self.assertEqual(self.respond(router,p)['status'],'complete')
        self.assertEqual(self.respond(router,other,'Explain pottery')['status'],'complete')
        requests=[r for r in calls if r.method=='POST']
        self.assertEqual([r.url.host for r in requests],['alex-agent.example','blair-agent.example'])
        self.assertEqual(requests[1].headers['Authorization'],'Bearer '+other_token)
        payload=json.loads(requests[1].content)
        self.assertEqual(payload['conversation_history'],[])
        self.assertIn('pottery',payload['instructions']);self.assertNotIn('astronomy',str(payload))
        self.assertNotIn(TOKEN,str(payload));self.provider.complete.assert_not_called()

    def test_configured_failure_never_falls_back_to_another_provider(self):
        _,p,router=self.personal()
        router.hermes.transport=httpx.MockTransport(lambda _:httpx.Response(403,json={'error':TOKEN}))
        reply=self.respond(router,p)
        self.assertEqual(reply['status'],'unavailable');self.assertNotIn(TOKEN,str(reply))
        self.provider.complete.assert_not_called()

    def test_switch_discards_reply_stops_admitted_run_and_drops_history(self):
        a,p,router=self.personal();members=self.app.state.members;b=self.account('Blair')
        members.lock_session(str(p));self.share(a,b);self.login(a);p=members.resolve(str(p))
        # Display assignment changes invalidate the original grant snapshot before
        # this request begins; use the current one for admission.
        members.on_lock=lambda principal:router.clear(principal)
        calls=[]
        def fake(request):
            calls.append(request.url.path)
            if request.url.path=='/v1/runs':
                members.login(str(p),b['id'],b['passcode'])
                return httpx.Response(202,json={'run_id':'run_oldperson'})
            return httpx.Response(200,json={'status':'cancelled'})
        router.hermes.transport=httpx.MockTransport(fake)
        reply=self.respond(router,p)
        self.assertEqual(reply['status'],'unavailable');self.assertNotIn(p.nonce,router.agents)
        self.assertEqual(calls,['/v1/runs','/v1/runs/run_oldperson/stop'])
        new=members.resolve(str(p));self.assertEqual(new.member,b['id']);self.assertEqual(router.agent(new).messages(new),[])

    def test_expiry_and_revision_change_discard_late_completion(self):
        for change in ('expiry','grants','memory','settings'):
            with self.subTest(change=change):
                a,p,router=self.personal();members=self.app.state.members
                def fake(request):
                    if request.url.path=='/v1/runs':return httpx.Response(202,json={'run_id':'run_late'})
                    if request.url.path.endswith('/stop'):return httpx.Response(200,json={'status':'cancelled'})
                    if change=='expiry':members.sessions[str(p)]['expires']=0
                    elif change=='grants':members.change(a['id'],members.item(a['id'])['revision'],profile=self.profile())
                    elif change=='memory':members.memory(p).save('A changed fact')
                    else:self.settings.revision+=1
                    return httpx.Response(200,json={'status':'completed','output':'PRIVATE LATE ANSWER'})
                router.hermes.transport=httpx.MockTransport(fake)
                reply=self.respond(router,p)
                self.assertEqual(reply['status'],'unavailable',reply);self.assertNotIn('PRIVATE LATE',str(reply))
                self.assertEqual(router.agent(p).messages(p) if change in ('memory','settings') else [],[])
                # Use distinct account names in this fixture for the next case.
                members.change(a['id'],members.item(a['id'])['revision'],delete=True)

    def test_api_chat_reaches_configured_personal_provider(self):
        a,p,_=self.personal()
        before=self.app.state.members.profile_for(p)
        headers={**self.guest,'X-Echo-Profile-Revision':str(before['profile_revision'])}
        calls=[]
        def fake(request):
            calls.append(request.url.path)
            return httpx.Response(202,json={'run_id':'run_api'}) if request.method=='POST' else httpx.Response(200,json={'status':'completed','output':'API personal answer'})
        real_client=httpx.AsyncClient
        def client(**kwargs):
            kwargs['transport']=httpx.MockTransport(fake);return real_client(**kwargs)
        with patch('backend.member_hermes.httpx.AsyncClient',side_effect=client):
            result=self.client.post('/v1/chat',headers=headers,json={'text':'Explain a nebula'})
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['text'],'API personal answer')
        self.assertEqual(calls,['/v1/runs','/v1/runs/run_api'])


class HermesTransportTests(unittest.TestCase):
    def runtime(self,handler,timeout=1):
        return MemberHermes(None,transport=httpx.MockTransport(handler),timeout=timeout)
    def run_fake(self,runtime,cancel=None):
        return runtime.complete({'url':'https://personal.example','token':TOKEN},[{'role':'user','content':'Synthetic question'}],'Instructions',cancel=cancel)
    def test_error_and_final_answer_redaction(self):
        for error in (True,False):
            def fake(request):
                if request.method=='POST':return httpx.Response(202,json={'run_id':'run_redact'})
                return httpx.Response(403,json={'error':TOKEN}) if error else httpx.Response(200,json={'status':'completed','output':'Do not echo '+TOKEN})
            if error:
                with self.assertRaises(ProviderUnavailable) as raised:self.run_fake(self.runtime(fake))
                self.assertNotIn(TOKEN,str(raised.exception))
            else:self.assertNotIn(TOKEN,self.run_fake(self.runtime(fake)))
    def test_waiting_approval_stops_without_approval_request(self):
        calls=[]
        def fake(request):
            calls.append(request.url.path)
            if request.url.path=='/v1/runs':return httpx.Response(202,json={'run_id':'run_approval'})
            return httpx.Response(200,json={'status':'waiting_for_approval','command':TOKEN})
        with self.assertRaisesRegex(ProviderUnavailable,'approval'):self.run_fake(self.runtime(fake))
        self.assertEqual(calls[-1],'/v1/runs/run_approval/stop');self.assertFalse(any(x.endswith('/approval') for x in calls))
    def test_cancel_interrupts_poll_and_stop_failure_is_honest(self):
        for broken_stop in (False,True):
            cancel=Event();calls=[]
            async def fake(request):
                calls.append(request.url.path)
                if request.url.path=='/v1/runs':return httpx.Response(202,json={'run_id':'run_cancel'})
                if request.url.path.endswith('/stop'):return httpx.Response(503 if broken_stop else 200,json={'status':'cancelled'})
                cancel.set();await asyncio.sleep(10)
            with self.assertRaises(ProviderUnavailable) as raised:self.run_fake(self.runtime(fake),cancel)
            self.assertIn('/v1/runs/run_cancel/stop',calls)
            if broken_stop:self.assertIn('could not be confirmed',str(raised.exception))
    def test_no_admission_retry_after_network_failure(self):
        calls=[]
        def fake(request):
            calls.append(request);raise httpx.ReadError(TOKEN)
        with self.assertRaises(ProviderUnavailable) as raised:self.run_fake(self.runtime(fake))
        self.assertEqual(len(calls),1);self.assertNotIn(TOKEN,str(raised.exception))


if __name__=='__main__':unittest.main()
