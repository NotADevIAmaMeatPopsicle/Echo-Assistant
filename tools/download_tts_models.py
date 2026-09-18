"""Download the reviewed, pinned TTS assets; no model loading, installation or playback."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
from urllib.parse import urlsplit
import httpx

ROOT = Path(__file__).resolve().parents[1]


def digest(path, algorithm, git_blob=False):
    result = hashlib.new(algorithm)
    if git_blob: result.update(f'blob {path.stat().st_size}\0'.encode())
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''): result.update(chunk)
    return result.hexdigest()


def verify(path, asset):
    if not path.is_file() or path.stat().st_size != asset['bytes']: return False
    if asset.get('sha256'): return digest(path, 'sha256') == asset['sha256']
    return digest(path, 'sha1', True) == asset['git_blob_sha1']


def fetch(asset, destination, verify_only=False):
    relative = PurePosixPath(asset['path'])
    if relative.is_absolute() or '..' in relative.parts or '\\' in str(relative): raise ValueError('Unsafe asset path')
    target = destination.joinpath(*relative.parts).resolve()
    if not target.is_relative_to(destination.resolve()): raise ValueError('Asset escapes model directory')
    if target.exists():
        if not verify(target, asset): raise ValueError('Existing asset failed verification; preserved '+asset['path'])
    elif verify_only: raise ValueError('Missing '+asset['path'])
    else:
        url = urlsplit(asset['url'])
        if url.scheme != 'https' or url.hostname not in {'huggingface.co','raw.githubusercontent.com'}:
            raise ValueError('Only reviewed upstream HTTPS sources are permitted')
        if url.username or url.password or url.query or url.fragment: raise ValueError('Invalid source URL')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.name+'.', suffix='.part', delete=False) as stream:
                temporary = Path(stream.name)
                with httpx.Client(timeout=httpx.Timeout(60, connect=15), trust_env=False, follow_redirects=True) as client:
                    with client.stream('GET', asset['url']) as response:
                        if response.status_code != 200: raise RuntimeError(f"Upstream returned HTTP {response.status_code} for {asset['path']}")
                        total = 0
                        for chunk in response.iter_bytes(1024*1024):
                            total += len(chunk)
                            if total > asset['bytes']: raise ValueError('Asset exceeded pinned size')
                            stream.write(chunk)
            if not verify(temporary, asset): raise ValueError('Downloaded hash mismatch for '+asset['path'])
            if target.exists(): raise ValueError('Destination appeared during download; preserved '+asset['path'])
            temporary.replace(target)
        finally:
            if temporary and temporary.exists(): temporary.unlink()
    return {'path': asset['path'], 'bytes': target.stat().st_size, 'sha256': digest(target, 'sha256'), 'verified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='Verify local assets without network requests')
    args = parser.parse_args()
    manifest = json.loads((ROOT/'config/tts-models.json').read_text(encoding='utf-8'))
    result = []
    for model in manifest['models']:
        destination = ROOT/'local/models'/model['directory']
        print(f"{'Verifying' if args.verify else 'Fetching'} {model['name']}: {sum(a['bytes'] for a in model['assets'])/1e6:.1f} MB", flush=True)
        with ThreadPoolExecutor(max_workers=3) as worker:
            assets = list(worker.map(lambda asset: fetch(asset, destination, args.verify), model['assets']))
        receipt = {'name': model['name'], 'source': model['source'], 'revision': model['revision'],
                   'runtime_revision': model['runtime_revision'], 'assets': assets, 'model_loaded': False}
        (destination/'verification.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        result.append({'name': model['name'], 'files': len(assets), 'bytes': sum(a['bytes'] for a in assets)})
        print('Verified '+model['name'], flush=True)
    print(json.dumps({'models': result, 'audio_played': False, 'runtime_changed': False}, indent=2))


if __name__ == '__main__': main()
