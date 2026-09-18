"""Stress USB with numbered status replies, with microphone streaming and playback off."""
import argparse
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.device_transport import make_transport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port')
    parser.add_argument('--seconds', type=int, default=90)
    args = parser.parse_args(); args.wifi=False
    if not 10<=args.seconds<=600: parser.error('Use 10–600 seconds')
    port = make_transport(args); received=queries=unexpected=0; buffer=bytearray(); lines=[]
    started=time.monotonic(); reason=None
    try:
        port.open(); port.write(b'VOICE_OFF\nAUDIO_STOP\n')
        until=time.monotonic()+.3
        while time.monotonic()<until: port.read(4096)
        started=time.monotonic()
        while time.monotonic()-started<args.seconds:
            queries+=1; port.write(f'STATUS {queries}\n'.encode())
            deadline=time.monotonic()+2; replied=False
            while not replied and time.monotonic()<deadline:
                data=port.read(4096); received+=len(data); buffer.extend(data)
                while b'\n' in buffer:
                    line, _, rest=buffer.partition(b'\n'); buffer=bytearray(rest)
                    lines.append(line.rstrip(b'\r'))
                if len(buffer)>4096: raise RuntimeError('Missing status line terminator')
                while len(lines)>=4:
                    group,lines=lines[:4],lines[4:]
                    prefixes=(b'STATUS ',b'NETWORK ',b'USB ',b'UI ')
                    if any(not line.startswith(prefix) for line,prefix in zip(group,prefixes)):
                        # This diagnostic exchanges only STATUS text with capture
                        # disarmed. Do not print unexpected binary bytes.
                        print(json.dumps({'status_prefixes':[line[:48].decode('ascii') if all(32<=c<127 for c in line) else '<non-ASCII>' for line in group]}))
                        unexpected+=1; raise RuntimeError('Status reply prefix/order corrupted or foreign console output inserted')
                    status=dict(re.findall(rb'(\w+)=([^ ]+)', group[0]))
                    query=status.get(b'query')
                    if query not in (b'0',str(queries).encode()): raise RuntimeError('Status query number corrupted')
                    # Firmware also publishes an unsolicited query=0 report every five seconds.
                    replied=replied or query==str(queries).encode()
                    if status.get(b'product')!=b'round-voice' or status.get(b'protocol')!=b'1':
                        raise RuntimeError('Status identity fields corrupted')
                    if status.get(b'wake')!=b'0' or status.get(b'stream')!=b'0':
                        raise RuntimeError('Microphone stream unexpectedly active')
                    if status.get(b'volume')!=b'0': raise RuntimeError('Requires speaker volume already at 0%')
                    if status.get(b'audio_errors')!=b'0': raise RuntimeError('Audio driver error')
            if not replied: raise RuntimeError('Numbered status reply incomplete or absent')
            # About the normal microphone byte rate, with response backpressure.
            target=started+queries/45
            if target>time.monotonic(): time.sleep(target-time.monotonic())
    except (OSError, RuntimeError) as error: reason=str(error)
    finally: port.close()
    result={'result':'FAIL' if reason else 'PASS','seconds':round(time.monotonic()-started,1),
            'queries':queries,'received_bytes':received,'unexpected_lines':unexpected,
            'reason':reason,'microphone_streamed':False,'playback_started':False}
    print(json.dumps(result))
    (Path(__file__).resolve().parents[1]/'local/usb-status-stream.json').write_text(json.dumps(result,indent=2), encoding='utf-8')
    if reason: raise SystemExit(1)


if __name__=='__main__': main()
