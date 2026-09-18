"""Fetch only the two immutable native sources used by the Remote host build."""
import hashlib
from pathlib import Path
import urllib.request

PINS = {
    'librespot-0.8.0.crate': (
        'https://static.crates.io/crates/librespot/librespot-0.8.0.crate',
        '030c5e98cc06f20283b5948ae23bdac1de0dec58dee2c5ec4c8dafc7aaa796ab'),
    'aec_audio_processing-1.0.1.tar.gz': (
        'https://files.pythonhosted.org/packages/9e/f1/d4c91eeaed6a2d91b448eb3eb17c150a505973aa7c5495d8772325918e38/aec_audio_processing-1.0.1.tar.gz',
        'f03a3ce3f45bf15a04a8504d0f692a651180ca2d3171bd9f3de0516e5f2b8360'),
}


def fetch(root):
    directory = root/'local/runtime'; directory.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in PINS.items():
        path = directory/name
        if path.exists(): data = path.read_bytes()
        else:
            with urllib.request.urlopen(url, timeout=30) as response: data = response.read(8_000_001)
        if len(data)>8_000_000 or hashlib.sha256(data).hexdigest()!=digest:
            raise RuntimeError('Native source checksum mismatch: '+name)
        if not path.exists(): path.write_bytes(data)


if __name__=='__main__': fetch(Path(__file__).resolve().parents[1])
