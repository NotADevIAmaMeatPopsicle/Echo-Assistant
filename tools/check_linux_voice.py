"""Synthetic board acceptance in an isolated, network-disabled test container.

Sends zero-valued microphone/reference frames; never opens real audio or a device.
Requires fresh tmpfs local data, with reviewed models mounted read-only.
"""
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import struct
import subprocess
import sys
from threading import Thread
import time
import urllib.request
import zlib

ROOT=Path('/opt/echo')
sys.path.insert(0,str(ROOT))


def main():
    from backend.cable import HEADER
    from backend.container_host import Host
    from backend.lifecycle import request_stop
    from backend.settings import EchoSettings, SettingsStore, SettingsUpdate
    from backend.transport import IDENTITY, MAC
    assert os.environ.get('ECHO_SYNTHETIC_CHECK')=='1'
    local=ROOT/'local'
    assert not any(local.iterdir()), 'Refusing to overwrite an existing installation'
    os.umask(0o077)
    Path('/run/echo/storage.key').write_bytes(secrets.token_bytes(32))
    token=secrets.token_urlsafe(40)
    (local/'api-token').write_text(token)
    (local/'models').symlink_to('/models')
    pairing=secrets.token_hex(32)
    (local/'wifi.json').write_text(json.dumps({'enabled':True,'host':'127.0.0.1','key':pairing,'mac':MAC}))
    SettingsStore(ROOT).save(SettingsUpdate(settings=EchoSettings(tts_engine='pocket',tts_voice='george')))
    env=dict(os.environ,PYTHONHOME='/opt/python312',LD_LIBRARY_PATH='/opt/python312/lib',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    subprocess.run(['/opt/python312/bin/python3.12','tools/prepare_tts.py'],cwd=ROOT,env=env,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
    (local/'tts-runtime-ready.json').write_text(json.dumps({'engines':{'pocket':True}}))
    # No internal home-tools credential is needed and no HA configuration exists.
    os.environ.pop('ECHO_HOME_TOOLS_TOKEN_FILE',None)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    host=Host(ROOT,True); failures=[]; receipt={}
    def api(path, method='GET'):
        request=urllib.request.Request('http://127.0.0.1:8768'+path,
            headers={'Authorization':'Bearer '+token},method=method)
        with opener.open(request,timeout=3) as response: return json.load(response)
    def board():
        connection=None
        try:
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname=False; context.verify_mode=ssl.CERT_NONE
            context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_2
            context.set_ciphers('PSK-AES128-GCM-SHA256')
            context.set_psk_client_callback(lambda hint:(IDENTITY,bytes.fromhex(pairing)))
            deadline=time.monotonic()+90
            generation=None; applied=False; reconnects=0; last_check=0; armed=False
            outage_until=0.; outage_generation=None; outage_checked=False; outage_recovered=False
            data=bytearray(); next_pcm=0; sequence=0
            while time.monotonic()<deadline:
                if connection is None:
                    if time.monotonic()<outage_until:
                        if outage_until-time.monotonic()<2 and not outage_checked:
                            state=api('/v1/voice');health=api('/health')
                            assert state['status']=='connecting' and time.time()-state['updated_at']<2
                            assert health['device_transport']=='wifi_waiting'
                            assert health['speaker_muted'] is None
                            outage_checked=True
                        time.sleep(.1);continue
                    try:
                        raw=socket.create_connection(('127.0.0.1',8769),timeout=.5)
                        connection=context.wrap_socket(raw,server_hostname=None)
                        connection.settimeout(.005); data.clear(); armed=False; sequence=0
                        reconnects+=1
                    except OSError:
                        time.sleep(.1);continue
                try:
                    block=connection.recv(4096)
                    if not block: connection.close();connection=None;continue
                    data.extend(block)
                    assert b'RV1!' not in data, 'Unexpected speaker PCM in silent test'
                    while b'\n' in data:
                        line,_,rest=data.partition(b'\n');data=bytearray(rest)
                        if line==b'STATUS':
                            connection.sendall(b'STATUS product=round-voice protocol=1 duplex=1 cue_ready=1 version=synthetic volume=2 muted=0 transport=wifi network=connected\n')
                        elif line==b'VOICE_ARM': armed=True
                        elif line==b'VOICE_OFF': armed=False
                except socket.timeout: pass
                except (ConnectionResetError,BrokenPipeError): connection.close();connection=None;continue
                now=time.monotonic()
                if armed and now>=next_pcm:
                    body=HEADER.pack(b'RV1!',3,1024,sequence)+bytes(1024)
                    connection.sendall(body+struct.pack('<I',zlib.crc32(body)))
                    sequence=(sequence+1)&0xffffffff;next_pcm=now+.016
                if now-last_check<.5: continue
                last_check=now
                status=json.loads((local/'voice-status.json').read_text())
                if status.get('status')!='armed' or status.get('speech_worker')!='ready' or status.get('pcm_frames',0)<60: continue
                assert status['recognition']['echo']=='ready'
                assert status['usb_errors']==0 and status['usb_gaps']==0
                assert status.get('spoken_replies',0)==0 and not status['speaker']['active']
                current=json.loads((local/'voice-process.json').read_text())['run_id']
                if outage_generation is None:
                    outage_generation=current;outage_until=now+7
                    connection.close();connection=None;armed=False
                    continue
                if not outage_recovered:
                    assert current==outage_generation, 'Connection loss restarted the voice process'
                    assert outage_checked
                    outage_recovered=True
                if not applied:
                    generation=current; api_pid=host.api.pid
                    result=api('/v1/settings/apply-speech','POST')
                    assert result['status']=='restarting'
                    applied=True
                elif current!=generation:
                    assert host.api.pid==api_pid and host.api.poll() is None
                    health=api('/health');assert health['device_transport']=='wifi_connected'
                    receipt.update(synthetic_board=True,real_audio=False,reconnections=reconnects,
                        voice_restart=True,api_preserved=True,echo='ready',speech_worker='ready',
                        framing_errors=0,pcm_frames=status['pcm_frames'],
                        waiting_status_fresh=outage_checked,transport_recovered_without_restart=outage_recovered)
                    break
            else: raise AssertionError('Synthetic voice acceptance timed out')
        except Exception as error: failures.append(type(error).__name__+': '+str(error))
        finally:
            if connection: connection.close()
            request_stop(ROOT,'host')
    driver=Thread(target=board);driver.start()
    host.run();driver.join(5)
    assert not driver.is_alive() and not failures, failures
    print(json.dumps(receipt))


if __name__=='__main__': main()
