"""Run the real voice loop and music API through a synthetic conversation.

Transport, native recognition, synthesis, Spotify and speaker output are fakes.
The API authentication, lifecycle ownership, command mailbox, phase transitions,
speech job completion and deferred music resumption are the real implementations.
No hardware, model provider or audio endpoint is contacted.
"""
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient
from backend import voice
from backend.app import create_app
from backend.cable import encode_pcm
from backend.lifecycle import Lifecycle
from backend.settings import EchoSettings, SettingsStore


class MusicConversationTests(unittest.TestCase):
    def conversation(self, pause):
        with TemporaryDirectory() as directory, ExitStack() as stack:
            root=Path(directory); (root/'local').mkdir()
            token='x'*40; (root/'local/api-token').write_text(token)
            api=stack.enter_context(TestClient(create_app(token,runtime_root=root,
                settings_store=SettingsStore()),base_url='http://localhost'))
            owner=stack.enter_context(Lifecycle(root))
            release=Event(); calls=[]; states=[]; requests=[]; started=time.monotonic()
            music=Mock(status='playing',title='Synthetic',artist='Fixture')
            music.pcm.empty.return_value=False; music.health.side_effect=lambda:{'status':music.status}
            music.read.return_value=bytes(512)
            music.last_pcm=0
            def command(action):
                calls.append(action)
                if action=='pause': music.status='paused'
                elif action=='play': music.status='playing'
                return True
            music.command.side_effect=command
            recognition=Mock(echo_ready=True,echo=None)
            recognition.mode=None; recognition.decoding=Event()
            recognition.health.return_value={'alive':True,'echo':'ready'}
            recognition.set_mode.side_effect=lambda mode:setattr(recognition,'mode',mode)
            emitted=set()
            def events():
                mode=recognition.mode
                if mode=='armed_music' and 'wake' not in emitted:
                    emitted.add('wake'); return [{'kind':'wake','value':'hey echo'}]
                if mode=='listening' and 'command' not in emitted:
                    emitted.add('command'); return [{'kind':'command','value':'A synthetic question'}]
                return []
            recognition.poll.side_effect=events

            class Speaker:
                def __init__(self, write):
                    self.active=False; self.kind='V'; self.consumed=self.underruns=0
                    self.until=0
                def start_stream(self, source): self.active=True; self.kind='M'
                def start(self, pcm):
                    self.active=True; self.kind='V'; self.until=time.monotonic()+.05
                def receive(self, line): pass
                def pump(self):
                    if self.active and self.kind=='V' and time.monotonic()>=self.until:
                        self.active=False; self.consumed=2
                def stop(self): self.active=False

            def current():
                try:return json.loads((root/'local/voice-status.json').read_text())
                except (FileNotFoundError,ValueError):return {}
            class Port:
                is_open=False
                def __init__(self): self.lines=[]; self.sequence=0; self.checked=False
                def open(self): self.is_open=True
                def close(self): self.is_open=False
                def write(self, data):
                    if data==b'STATUS\n':
                        self.lines.append(b'STATUS product=round-voice protocol=1 duplex=1 cue_ready=1 volume=2 muted=0 audio_errors=0\n')
                    elif data.startswith(b'WAKE '):
                        self.lines.append(b'EVENT listening_ready='+data.split()[1]+b'\n')
                def read(self, count):
                    time.sleep(.005)
                    state=current()
                    if state.get('status')=='thinking' and not self.checked:
                        self.checked=True
                        if pause:
                            result=api.post('/v1/music/control',headers={'Authorization':'Bearer '+token},json={'action':'pause'})
                            requests.append(result.status_code)
                        release.set()
                    data=b''.join(self.lines)+encode_pcm(bytes(512),self.sequence)
                    self.lines.clear(); self.sequence+=1
                    return data
            port=Port(); completed_at=[None]
            def stopped():
                if time.monotonic()-started>7: raise AssertionError('Synthetic conversation did not finish')
                state=current()
                if state.get('spoken_replies')==1:
                    if completed_at[0] is None: completed_at[0]=time.monotonic()
                    if time.monotonic()-completed_at[0]>1.1: return True
                return False
            def synthesize(*args,**kwargs):
                if not release.wait(4): raise AssertionError('Synthetic request was not released')
                return bytes(1024)
            original_write=voice.write_status
            def publish(status):
                states.append(dict(status)); return original_write(status)
            alarms=Mock(); alarms.receive.return_value=False; alarms.take.return_value=None
            replacements={
                'ROOT':root,'load_wifi':Mock(return_value={ 'enabled':True }),
                'WifiTransport':Mock(return_value=port),'Recognition':Mock(return_value=recognition),
                'EchoCleaner':Mock(),'Speaker':Speaker,'HomeDisplay':Mock(),'Alarms':Mock(return_value=alarms),
                'speech_settings':Mock(return_value=EchoSettings()),'selected_status':Mock(return_value='ready'),
                'prepare_speech':Mock(return_value={'status':'ready'}),'synthesize':synthesize,
                'post_text':Mock(return_value=httpx.Response(200,json={'status':'complete','text':'Synthetic reply.'},
                    request=httpx.Request('POST','http://localhost/v1/text'))),'write_status':publish,
            }
            for name,value in replacements.items(): stack.enter_context(patch.object(voice,name,value))
            stack.enter_context(patch.object(owner,'stopped',side_effect=stopped))
            with redirect_stdout(io.StringIO()):
                voice.run_session(SimpleNamespace(usb=False,play_music=False),owner,None,{},music)
            self.assertTrue(port.checked); self.assertEqual(emitted,{'wake','command'})
            self.assertTrue(any(s.get('spoken_replies')==1 for s in states))
            self.assertTrue(all(s.get('playback_errors')==0 for s in states))
            return calls,requests,states

    def test_pause_during_answer_finishes_speech_and_prevents_music_resumption(self):
        calls,requests,states=self.conversation(pause=True)
        self.assertEqual(requests,[200]); self.assertNotIn('play',calls)
        self.assertTrue(any(s.get('spoken_replies')==1 and not s['music_resume_pending'] for s in states))

    def test_unpaused_conversation_still_resumes_interrupted_music(self):
        calls,requests,_=self.conversation(pause=False)
        self.assertEqual(requests,[]); self.assertEqual(calls.count('play'),1)


if __name__=='__main__':unittest.main()
