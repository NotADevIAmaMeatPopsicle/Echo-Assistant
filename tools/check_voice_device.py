"""Silently check microphone mute, heartbeat expiry and optional Wi-Fi reconnection.

Requires a stopped bridge and output already at 0%. Microphone samples are counted
in RAM, never saved or recognized. No playback or home actions are sent.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.cable import Decoder
from device_transport import make_transport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port')
    parser.add_argument('--wifi', action='store_true')
    parser.add_argument('--reconnect', action='store_true', help='Interrupt and reauthenticate paired Wi-Fi while muted')
    parser.add_argument('--busy-mute', action='store_true', help='Check mute after a burst of microphone-mode commands')
    args = parser.parse_args()
    if args.reconnect and not args.wifi: parser.error('--reconnect requires --wifi')
    port = make_transport(args); port.open()
    decoder=Decoder(); latest={}; frames=0; query=0; original_muted=None
    previous_errors=previous_gaps=0
    result=None
    def receive(seconds, heartbeat=True):
        nonlocal latest,frames
        deadline=time.monotonic()+seconds; ping=0; count=0
        while time.monotonic()<deadline:
            if heartbeat and time.monotonic()-ping>=1:
                port.write(b'VOICE_PING\n'); ping=time.monotonic()
            packets,lines=decoder.feed(port.read(4096)); count+=len(packets);frames+=len(packets)
            for line in lines:
                if line.startswith('STATUS '): latest=dict(re.findall(r'(\w+)=([^ ]+)',line))
        return count
    def fresh_status():
        nonlocal query
        query += 1
        port.write(f'STATUS {query}\n'.encode())
        deadline=time.monotonic()+2
        while latest.get('query')!=str(query) and time.monotonic()<deadline: receive(.05,False)
        assert latest.get('query')==str(query), 'A fresh status reply did not arrive'
    try:
        fresh_status()
        assert latest.get('product')=='round-voice' and latest.get('protocol')=='1', latest
        assert latest.get('volume')=='0', 'This silent check requires speaker volume already at 0%'
        original_muted=latest.get('muted')=='1'
        baseline={name:int(latest[name]) for name in ('audio_errors','stream_drops','usb_drops')}
        # UNMUTE is accepted only while armed. Preserve the initial preference
        # in finally, including when this test starts with the microphone muted.
        port.write(b'VOICE_ARM\nUNMUTE\n'); active=receive(2)
        assert active>80, f'Only {active} PCM frames'
        if args.busy_mute: port.write(b'MIC_DUPLEX 0\n'*32)
        port.write(b'MUTE\n'); receive(.5)
        muted=receive(1)
        fresh_status()
        assert muted==0, f'Muted microphone still sent {muted} frames'
        assert latest.get('muted')=='1' and latest.get('stream')=='0', 'Capture did not stop after mute'
        reconnected=False
        if args.reconnect:
            # No VOICE_OFF first: exercise a lost socket, not graceful disarm.
            previous_errors,previous_gaps=decoder.errors,decoder.gaps
            port.close()
            port=make_transport(args); port.open(); decoder=Decoder(); latest={}
            fresh_status()
            assert latest.get('wake')=='0' and latest.get('stream')=='0', 'Old connection remained armed'
            assert latest.get('muted')=='1' and latest.get('volume')=='0', 'Preferences changed on reconnect'
            port.write(b'VOICE_ARM\n')
            assert receive(1)==0, 'Arming bypassed the saved microphone mute'
            reconnected=True
        port.write(b'UNMUTE\n'); resumed=receive(2)
        assert resumed>80, f'Only {resumed} PCM frames after unmute'
        receive(6,False)
        fresh_status()
        assert latest.get('wake')=='0' and latest.get('stream')=='0', latest
        assert int(latest.get('heartbeat_ms',0))>=5000, latest
        assert receive(1,False)==0, 'Microphone continued after heartbeat expiry'
        assert latest.get('volume')=='0', 'Silent output setting changed'
        assert all(int(latest[name])==value for name,value in baseline.items()), 'Device error/drop counter increased'
        assert previous_errors+decoder.errors==0 and previous_gaps+decoder.gaps==0, 'Framing error or sequence gap'
        result={'result':'PASS','transport':latest.get('transport','usb'),'initial_frames':active,'muted_frames':muted,'resumed_frames':resumed,
                          'total_frames':frames,'crc_errors':previous_errors+decoder.errors,'sequence_gaps':previous_gaps+decoder.gaps,
                          'heartbeat_disarmed':True,'muted_reconnect':reconnected,'busy_mute':args.busy_mute,
                          'new_device_errors':0,'volume':0,'playback_started':False,'restored_muted':original_muted}
    finally:
        if not port.is_open and original_muted is not None:
            port=make_transport(args); port.open(); decoder=Decoder(); latest={}
        if port.is_open:
            if original_muted is not None:
                port.write(b'VOICE_ARM\n')
                port.write(b'MUTE\n' if original_muted else b'UNMUTE\n')
            port.write(b'VOICE_OFF\n')
            if original_muted is not None:
                fresh_status()
                assert latest.get('muted')==str(int(original_muted)), 'Original microphone preference was not restored'
            port.close()
    if result is not None: print(json.dumps(result))


if __name__=='__main__': main()
