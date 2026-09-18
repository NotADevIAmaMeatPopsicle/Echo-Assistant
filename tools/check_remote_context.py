"""Quiet live timer/context check in a disposable browser session.

Creates two ten/twenty-minute timers, removes both before contacting the model,
and clears only this check's conversation. Does not play audio or actuate HA.
Only content-free verification and timings are written to the local receipt.
"""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from tools.remote_device import client


def body(response):
    response.raise_for_status()
    return response.json()


def main():
    with client() as owner:
        before = body(owner.get('/v1/voice'))
        assert before['status'] == 'armed' and not before['speaker']['active']
        assert before['device']['volume'] == '2'
        assert body(owner.get('/v1/settings/agent'))['status'] == 'active'
        activity = body(owner.get('/v1/echo'))['activity']['state']
        assert activity not in {'starting','thinking','checking','acting'}
        original_timers = {item['id'] for item in body(owner.get('/v1/state'))['timers']}
        ticket = body(owner.post('/v1/ui/ticket'))['ticket']
        created = []; timings = []
        with httpx.Client(base_url=str(owner.base_url), headers={'X-Echo-Request':'1'},
                          timeout=65, trust_env=False) as qa:
            body(qa.post('/v1/ui/session', json={'ticket':ticket}))
            try:
                def command(text):
                    started = time.monotonic()
                    response = body(qa.post('/v1/text', json={'text':text}))
                    timings.append(round((time.monotonic()-started)*1000, 1))
                    assert response['status'] == 'complete'
                    return response
                first = command('set a timer for ten minutes'); created.append(first['timer_id'])
                second = command('set a timer for twenty minutes'); created.append(second['timer_id'])
                status = command('how long is left')
                assert status['timer_id'] == second['timer_id'] and status['timer_action'] == 'status'
                assert command('cancel it')['timer_id'] == second['timer_id']
                assert command('cancel it')['timer_action'] == 'missing'
                remaining = {item['id'] for item in body(qa.get('/v1/state'))['timers']}
                assert first['timer_id'] in remaining and second['timer_id'] not in remaining
                # Remove the other synthetic timer before waiting on any model.
                body(qa.delete('/v1/timers/'+first['timer_id']))
                started = time.monotonic()
                answer = body(qa.post('/v1/chat', json={
                    'text':'How many minutes long was the timer I asked you to cancel? Answer with its duration.'}))
                model_seconds = round(time.monotonic()-started, 2)
                assert answer['status'] == 'complete'
                assert any(term in answer['text'].lower() for term in ('20 minutes', 'twenty minutes'))
                assert not answer.get('home_actions')
                assert body(owner.get('/v1/voice'))['connection_id'] == before['connection_id']
                receipt = {'version':body(owner.get('/health'))['version'],
                           'timer_target_and_repeat_verified':True,'live_model_context_verified':True,
                           'local_command_milliseconds':timings,'model_seconds':model_seconds,
                           'board_connection_preserved':True,'audio_requested':False,'home_actions_requested':False}
            finally:
                for timer_id in created:
                    response = qa.delete('/v1/timers/'+timer_id)
                    assert response.status_code in {200,404}
                body(qa.delete('/v1/chat'))
                body(qa.delete('/v1/ui/session'))
        after = body(owner.get('/v1/voice'))
        assert {item['id'] for item in body(owner.get('/v1/state'))['timers']} == original_timers
        assert after['device']['volume'] == '2' and not after['speaker']['active']
        assert after.get('playback_errors',0) == before.get('playback_errors',0)
        receipt.update(timers_restored=True,qa_context_cleared=True,volume='2')
        (ROOT/'local/remote-022-context.json').write_text(json.dumps(receipt,indent=2))
        print(json.dumps(receipt))


if __name__ == '__main__': main()
