"""Set or verify a board volume without playing sound; stop the bridge first."""
import argparse
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.check_device import fresh_status
from tools.device_transport import make_transport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('volume', type=int, choices=range(21))
    parser.add_argument('--port', default='COM3')
    parser.add_argument('--wifi', action='store_true')
    parser.add_argument('--verify', action='store_true', help='Read only; fail if volume differs')
    args = parser.parse_args(); port = make_transport(args)
    def status():
        # Ignore buffered boot/earlier replies; verify this query's current level.
        return fresh_status(port, timeout=4)
    try:
        port.open(); current = status()
        if args.verify:
            assert int(current['volume']) == args.volume, 'Saved volume differs'
        else:
            port.write(b'AUDIO_STOP\nVOICE_OFF\n')
            for _ in range(21):
                level = int(current['volume'])
                if level == args.volume: break
                port.write(b'VOL-\n' if level > args.volume else b'VOL+\n')
                time.sleep(.1); current = status()
            assert int(current['volume']) == args.volume, 'Volume did not reach requested setting'
            # Firmware debounces its NVS write for one second.
            until = time.monotonic()+1.5
            while time.monotonic() < until: port.read(4096)
            current = status()
        print({'volume':current['volume'], 'version':current['version'], 'sound_played':False})
    finally:
        port.close()


if __name__ == '__main__': main()
