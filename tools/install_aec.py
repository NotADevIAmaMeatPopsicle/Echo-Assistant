"""Install the pinned local WebRTC worker using an existing Python 3.13, without host changes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = 'aec_audio_processing-1.0.1-cp313-cp313-win_amd64.whl'
SHA256 = '25502a35a08a55650d926b0280199118af42e6405cda177039fa5ad04d24671e'


def main():
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 13) or sys.maxsize <= 2**32:
        raise SystemExit('Run with an existing 64-bit Python 3.13: py -3.13 tools/install_aec.py')
    runtime = ROOT/'local/runtime'; runtime.mkdir(parents=True, exist_ok=True)
    wheel = runtime/NAME
    if not wheel.exists():
        with urllib.request.urlopen('https://pypi.org/pypi/aec-audio-processing/1.0.1/json', timeout=20) as response:
            metadata = json.load(response)
        entry = next(item for item in metadata['urls'] if item['filename'] == NAME)
        if entry['digests']['sha256'] != SHA256 or not entry['url'].startswith('https://files.pythonhosted.org/'):
            raise SystemExit('Echo runtime metadata does not match the pin')
        with urllib.request.urlopen(entry['url'], timeout=30) as response:
            data = response.read(2*1024*1024)
        if hashlib.sha256(data).hexdigest() != SHA256: raise SystemExit('Echo wheel checksum mismatch')
        wheel.write_bytes(data)
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != SHA256: raise SystemExit('Echo wheel checksum mismatch')
    environment = ROOT/'local/aec-python'; python = environment/'Scripts/python.exe'
    if not python.exists(): subprocess.run([sys.executable, '-m', 'venv', str(environment)], check=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)], check=True)
    notices = ROOT/'third_party/licenses'; notices.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel) as archive:
        (notices/'aec-audio-processing-BSD.txt').write_bytes(archive.read('aec_audio_processing-1.0.1.dist-info/licenses/LICENSE'))
    print('Pinned local echo runtime installed; no startup, PATH, services or agent settings changed')


if __name__ == '__main__': main()
