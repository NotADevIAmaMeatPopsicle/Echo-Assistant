"""Verify software mic mute survives a real reset, restoring the initial preference. No playback."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.cable import Decoder
from backend.transport import MAC
from tools.device_transport import make_transport


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port')
    args=parser.parse_args(); args.wifi=False
    port=make_transport(args); decoder=Decoder(); original=None; query=97000
    esptool=Path.home()/'.platformio/packages/tool-esptoolpy/esptool.py'
    if not esptool.is_file(): raise SystemExit('Cached esptool is required; use the PlatformIO Python runtime')
    def status():
        nonlocal query
        query+=1; end=time.monotonic()+5; requested=0
        while time.monotonic()<end:
            if time.monotonic()-requested>.3:
                port.write(f'STATUS {query}\n'.encode()); requested=time.monotonic()
            _,lines=decoder.feed(port.read(4096))
            for line in lines:
                if line.startswith('STATUS '):
                    fields=dict(re.findall(r'(\w+)=([^ ]+)',line))
                    if fields.get('query')==str(query): return fields
        raise RuntimeError('Fresh board status did not arrive')
    try:
        port.open(); before=status()
        if before.get('volume')!='0': raise RuntimeError('This silent test requires speaker volume already 0%')
        original=before.get('muted')=='1'
        port.write(b'MUTE\nVOICE_OFF\n'); muted=status()
        if muted.get('muted')!='1': raise RuntimeError('Microphone mute was not acknowledged')
        port.close()
        probe=subprocess.run([sys.executable,str(esptool),'--chip','esp32s3','--port',args.port,
                              '--before','default_reset','--after','hard_reset','read_mac'],
                             capture_output=True,text=True,check=True)
        if 'MAC: '+MAC not in probe.stdout: raise RuntimeError('Unexpected chip identity during reset')
        port=make_transport(args); port.open(); decoder=Decoder(); after=status()
        if (after.get('muted'),after.get('volume'),after.get('wake'),after.get('stream'))!=('1','0','0','0'):
            raise RuntimeError('Saved mute or quiet setting did not survive reset')
        port.write(b'VOICE_ARM\n'); frames=0; end=time.monotonic()+1
        while time.monotonic()<end:
            packets,_=decoder.feed(port.read(4096)); frames+=len(packets)
        if frames: raise RuntimeError('Arming after restart bypassed the saved mute')
        result={'result':'PASS','firmware':after.get('version'),'mute_survived_restart':True,
                'muted_frames_after_arm':frames,'volume':0,'restored_muted':original,'playback_started':False}
    finally:
        if original is not None:
            if not port.is_open: port=make_transport(args); port.open(); decoder=Decoder()
            port.write(b'VOICE_ARM\n'+(b'MUTE\n' if original else b'UNMUTE\n')+b'VOICE_OFF\n')
            restored=status()
            if restored.get('muted')!=str(int(original)) or restored.get('volume')!='0':
                raise RuntimeError('Original preference was not restored')
        port.close()
    print(json.dumps(result))
    (Path(__file__).resolve().parents[1]/'local/mute-restart-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')


if __name__=='__main__': main()
