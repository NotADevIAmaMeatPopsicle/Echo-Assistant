"""Advertise only Echo's reachable Docker Spotify receiver on the Windows LAN."""
import argparse
import ipaddress
import json
import logging
import os
from pathlib import Path
import socket
import time
import urllib.request
import uuid
from zeroconf import IPVersion, ServiceInfo, Zeroconf

ROOT=Path(__file__).resolve().parent
SERVICE='_spotify-connect._tcp.local.'
logging.disable(logging.CRITICAL)


def receiver(host, port):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://{host}:{port}/?action=getInfo',timeout=2) as response:
        value=json.loads(response.read(65537))
    identity=value.get('deviceID','')
    if value.get('status')!=101 or not isinstance(identity,str) or not identity.isalnum() or len(identity)>64:
        raise ValueError('Receiver is unavailable')
    name=value.get('remoteName','')
    if not isinstance(name,str) or not 1<=len(name)<=63 or any(ord(c)<32 for c in name):
        raise ValueError('Receiver name is invalid')
    return identity,name


def main(seconds=None):
    import msvcrt
    lock=(ROOT/'discovery.lock').open('a+b')
    lock.seek(0)
    if not lock.read(1): lock.write(b'0');lock.flush()
    lock.seek(0)
    try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError: lock.close();return
    identity=uuid.uuid4().hex
    (ROOT/'discovery-process.json').write_text(json.dumps({'pid':os.getpid(),'run_id':identity}))
    zc=info=None; current=None; started=time.monotonic()
    try:
        while seconds is None or time.monotonic()-started<seconds:
            try: stop=(ROOT/'discovery-stop').read_text()==identity
            except FileNotFoundError: stop=False
            if stop: break
            config=json.loads((ROOT/'discovery.json').read_text())
            if config.get('enabled') is not True: break
            host=config['host'];port=config['port']
            address=ipaddress.ip_address(host)
            if address.version!=4 or not address.is_private or address.is_unspecified or address.is_loopback or port!=18899:
                raise ValueError('Discovery requires the configured home receiver')
            state='waiting_for_receiver'
            try:
                device,name=receiver(host,port)
                wanted=(host,port,device,name)
                if wanted!=current:
                    if zc: zc.close()
                    zc=Zeroconf(interfaces=[host],ip_version=IPVersion.V4Only)
                    info=ServiceInfo(SERVICE,device+'.'+SERVICE,
                        addresses=[socket.inet_aton(host)],port=port,
                        properties={'VERSION':'1.0','CPath':'/'},
                        server='echo-'+device[:12]+'.local.',host_ttl=30,other_ttl=30)
                    zc.register_service(info,allow_name_change=False)
                    current=wanted
                state='advertised'
            except (OSError,ValueError):
                if zc: zc.close()
                zc=info=current=None
            status=ROOT/'discovery-status.json'; temporary=status.with_suffix('.tmp')
            temporary.write_text(json.dumps({'state':state,'updated_at':time.time(),'run_id':identity,
                'host':host,'port':port}))
            temporary.replace(status)
            time.sleep(2)
    finally:
        if zc: zc.close()
        (ROOT/'discovery-process.json').unlink(missing_ok=True)
        (ROOT/'discovery-status.json').write_text(json.dumps({'state':'stopped','updated_at':time.time()}))
        lock.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int)
    options=parser.parse_args()
    try: main(options.seconds)
    except Exception:
        # Discovery has no account or audio access. Keep failures content-free.
        (ROOT/'discovery-status.json').write_text(json.dumps({'state':'failed','updated_at':time.time()}))
        raise SystemExit(1)
