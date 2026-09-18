"""Play an offline spoken test through the paired board and verify buffer/clock health."""
import argparse
import json
from pathlib import Path
import re
import sys
import time
import serial
from serial.tools import list_ports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.cable import Decoder
from backend.speaker import Speaker
from backend.speech import synthesize
from device_transport import make_transport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port')
    parser.add_argument('--wifi', action='store_true')
    parser.add_argument('--short', action='store_true')
    parser.add_argument('--max-volume', type=int, choices=(1,2,3), default=1,
                        help='Explicit accepted test ceiling; never changes device volume')
    args = parser.parse_args()
    pcm = synthesize('Hello. This is Echo speaking.' if args.short else 'Hello. I am Echo. My voice is generated locally. You can ask me the time, set a timer, or check the temperature.')
    port = make_transport(args)
    decoder = Decoder(); latest = {}; speaker = Speaker(port.write)
    first_underrun = None; maximum_gap = 0.
    def receive():
        nonlocal latest, first_underrun
        _, lines = decoder.feed(port.read(8192))
        for line in lines:
            if line.startswith('STATUS '): latest = dict(re.findall(r'(\w+)=([^ ]+)', line))
            speaker.receive(line)
            if speaker.underruns and first_underrun is None:
                first_underrun = {'sent':speaker.sent,'received':speaker.received,'consumed':speaker.consumed}
    try:
        port.open(); port.write(b'STATUS\n')
        deadline = time.monotonic()+3
        while not latest and time.monotonic() < deadline: receive()
        assert latest.get('product') == 'round-voice' and latest.get('protocol') == '1', latest
        assert 0 < int(latest.get('volume', 99)) <= args.max_volume, 'Test requires an audible level within the accepted ceiling'
        port.write(b'VOICE_ARM\n')
        started = ping = last_pump = time.monotonic()
        speaker.start(pcm)
        while speaker.active and time.monotonic()-started < 60:
            if time.monotonic()-ping >= 1: port.write(b'VOICE_PING\n'); ping = time.monotonic()
            receive(); speaker.pump()
            now = time.monotonic(); maximum_gap = max(maximum_gap,now-last_pump); last_pump = now
        assert not speaker.active, 'Playback did not complete'
        elapsed = time.monotonic()-started
        assert elapsed >= len(pcm)/96000, 'Device consumed PCM faster than the audio clock'
        port.write(b'STATUS\n')
        deadline = time.monotonic()+.5
        while time.monotonic() < deadline: receive()
        assert latest.get('audio_errors') == '0', latest
        assert decoder.errors == 0, 'Corrupt device frames'
        print(json.dumps({'result': 'PASS' if not speaker.underruns else 'FAIL', 'transport': latest.get('transport', 'usb'), 'speech_seconds': round(len(pcm)/96000, 2),
            'elapsed_seconds': round(elapsed, 2), 'frames_played': speaker.consumed,
            'underruns': speaker.underruns, 'audio_errors': latest.get('audio_errors'), 'volume': latest.get('volume'),
            'first_underrun':first_underrun,'maximum_pump_gap_ms':round(maximum_gap*1000,1)}),flush=True)
        assert speaker.underruns == 0, f'{speaker.underruns} playback underruns'
    finally:
        if port.is_open: port.write(b'AUDIO_STOP\nVOICE_OFF\n'); port.close()


if __name__ == '__main__': main()
