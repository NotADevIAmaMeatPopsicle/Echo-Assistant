"""Shared identity-checked transport for explicit hardware acceptance tools."""
from pathlib import Path
import time
import serial
from serial.tools import list_ports
from backend.transport import MAC, WifiTransport, load_wifi

ROOT = Path(__file__).resolve().parents[1]


def make_transport(args):
    if (ROOT/'local/host-target.json').exists():
        raise RuntimeError('This board belongs to the migrated server. Use server-side checks or reconcile a deliberate host rollback before taking direct ownership.')
    if (ROOT/'local/voice-process.json').exists():
        raise RuntimeError('Stop the voice bridge before hardware acceptance')
    if args.wifi:
        config = load_wifi(ROOT)
        if not config: raise RuntimeError('Pair the board before wireless acceptance')
        class Deadline:
            end = time.monotonic()+35
            def stopped(self): return time.monotonic()>self.end
        return WifiTransport(config, Deadline())
    if not any(p.device == args.port and (p.vid, p.pid) == (0x303A, 0x1001)
               and (p.serial_number or '').lower() == MAC for p in list_ports.comports()):
        raise RuntimeError('Expected round board is not present')
    port = serial.Serial(port=None, baudrate=115200, timeout=.01, write_timeout=.3)
    port.dtr = port.rts = False; port.port = args.port
    return port
