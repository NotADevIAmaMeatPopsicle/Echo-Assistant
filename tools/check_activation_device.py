"""Quiet cue/readiness timing check; no speech recognition or recording is saved."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.activation import Activation
from backend.cable import Decoder
from tools.check_device import fresh_status
from tools.device_transport import make_transport


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',required=True)
    parser.add_argument('--wifi',action='store_true')
    parser.add_argument('--max-volume',type=int,choices=(1,2,3),default=1)
    args=parser.parse_args()
    port=make_transport(args)
    try:
        port.open();status=fresh_status(port,timeout=4)
        assert status.get('cue_ready')=='1','Cue-readiness firmware required'
        assert 0<int(status.get('volume',99))<=args.max_volume,'Volume outside approved test ceiling'
        assert status.get('muted')=='0','Microphone is muted'
        decoder=Decoder();activation=Activation(True)
        port.write(b'VOICE_ARM\n')
        until=time.monotonic()+.25
        while time.monotonic()<until: decoder.feed(port.read(4096))
        started=ping=time.monotonic();port.write(activation.begin())
        ready_at=first_mic=None;frames=0
        while time.monotonic()-started<3:
            now=time.monotonic()
            if now-ping>=1: port.write(b'VOICE_PING\n');ping=now
            packets,lines=decoder.feed(port.read(4096))
            for line in lines: activation.receive(line)
            if activation.ready:
                if ready_at is None: ready_at=time.monotonic()
                if packets:
                    if first_mic is None: first_mic=time.monotonic()
                    frames+=len(packets)
            if ready_at and frames>=20: break
        assert ready_at is not None,'Board did not confirm cue completion'
        assert .45<=ready_at-started<2,'Cue completion outside expected timing'
        assert first_mic is not None and first_mic-ready_at<.2,'Microphone did not follow the cue promptly'
        assert frames>=20 and decoder.errors==0,'Missing or corrupt command audio'
        result={'result':'PASS','firmware':status['version'],'volume':status['volume'],
                'cue_ready_ms':round((ready_at-started)*1000,1),
                'first_mic_after_ready_ms':round((first_mic-ready_at)*1000,1),
                'microphone_frames':frames,'recording_saved':False}
        print(json.dumps(result))
    finally:
        if port.is_open: port.write(b'VOICE_TIMEOUT\nVOICE_OFF\n');port.close()


if __name__=='__main__':main()
