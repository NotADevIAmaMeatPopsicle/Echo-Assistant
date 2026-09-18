"""Prove Docker's LAN TLS-PSK path with synthetic bytes, never a physical board."""
import json
import secrets
import socket
import ssl
import subprocess
import sys
import time

SERVER=r'''
import json,sys,time
from backend.transport import WifiTransport
payload=json.loads(sys.stdin.readline());key=payload['key']
class Stop:
    end=time.monotonic()+30
    def stopped(self):return time.monotonic()>self.end
transport=WifiTransport({'host':payload['host'],'key':key},Stop())
try:
    transport.open()
    received=b''
    while len(received)<65536: received+=transport.read(4096)
    assert received==bytes(range(256))*256
    transport.write(received)
    print('verified',flush=True)
finally:transport.close()
'''


def main():
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from backend import deployment
    from backend.transport import IDENTITY
    key=secrets.token_hex(32)
    process=subprocess.Popen(['docker','--context',deployment.docker_context(),'run','--rm','-i','--init',
        '--name','echo-tls-lan-check','--label','org.echo.owner=round-voice',
        '--network','echo_default','--user','10000:10000','--log-driver','none',
        '--cpus','1','--memory','128m','-p',deployment.device_host()+':8769:8769',
        '-e','ECHO_WIFI_BIND=0.0.0.0','--entrypoint','python','echo-host:validation-0.1',
        '-c',SERVER],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    process.stdin.write(json.dumps({'key':key,'host':deployment.device_host()}).encode()+b'\n');process.stdin.flush()
    def connect(secret,identity):
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
        context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_2
        context.set_ciphers('PSK-AES128-GCM-SHA256')
        context.set_psk_client_callback(lambda hint:(identity,bytes.fromhex(secret)))
        deadline=time.monotonic()+12
        while True:
            try:raw=socket.create_connection((deployment.device_host(),8769),timeout=2);break
            except (ConnectionRefusedError,TimeoutError):
                if time.monotonic()>deadline:raise
                time.sleep(.2)
        try:return context.wrap_socket(raw,server_hostname=None)
        except Exception:raw.close();raise
    try:
        for secret,identity in [(secrets.token_hex(32),IDENTITY),(key,'wrong-device')]:
            try:
                bad=connect(secret,identity);bad.close()
                raise AssertionError('Invalid pairing was accepted')
            except (ssl.SSLError,ConnectionResetError):pass
        with connect(key,IDENTITY) as client:
            payload=bytes(range(256))*256;client.sendall(payload);received=b''
            while len(received)<len(payload):received+=client.recv(8192)
            assert received==payload
        output,errors=process.communicate(timeout=10)
        assert process.returncode==0 and output.strip()==b'verified', 'LAN transport server failed'
        print(json.dumps({'host':deployment.device_host(),'port':8769,'tls':'PSK-AES128-GCM-SHA256',
            'wrong_key_rejected':True,'wrong_identity_rejected':True,'roundtrip_bytes':len(payload),'real_audio':False}))
    finally:
        if process.poll() is None:
            # This dedicated test container is the only resource this helper stops.
            subprocess.run(['docker','--context',deployment.docker_context(),'stop','-t','2','echo-tls-lan-check'],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
            process.communicate(timeout=10)


if __name__=='__main__': main()
