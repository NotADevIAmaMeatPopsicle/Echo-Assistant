"""Explicit download of the pinned offline model; never called by runtime startup."""
import hashlib
import argparse
from pathlib import Path, PurePosixPath
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    'small': ('vosk-model-small-en-us-0.15', 41205931,
              '30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498'),
    'accurate': ('vosk-model-en-us-0.22-lgraph', 130557655,
                 'd9838b4aaa82a75c4a17f5aca300eaca129aaab2a7cbf951bafbb500eb9c4334'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=MODELS, default='small')
    args = parser.parse_args()
    name, size, checksum = MODELS[args.model]
    url = 'https://alphacephei.com/vosk/models/'+name+'.zip'
    models = ROOT/'local/models'
    models.mkdir(parents=True, exist_ok=True)
    target = models/name
    if target.exists():
        required = ('am/final.mdl', 'conf/model.conf', 'graph/Gr.fst', 'graph/HCLr.fst')
        if not all((target/name).is_file() for name in required):
            raise SystemExit('Existing model is incomplete; preserve and inspect it before replacing it')
        print('Existing local model retained; no download needed')
        return
    archive = models/(name+'.zip')
    if not archive.exists():
        partial = archive.with_suffix('.part')
        with urllib.request.urlopen(url, timeout=30) as response, partial.open('wb') as output:
            count = 0
            while block := response.read(1024*1024):
                count += len(block)
                if count > size: raise RuntimeError('Model archive exceeds expected size')
                output.write(block)
        if partial.stat().st_size != size: raise RuntimeError('Incomplete model archive')
        if hashlib.sha256(partial.read_bytes()).hexdigest() != checksum:
            raise RuntimeError('Model archive checksum mismatch')
        partial.replace(archive)
    if archive.stat().st_size != size or hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
        raise RuntimeError('Cached model archive checksum mismatch')
    with tempfile.TemporaryDirectory(prefix='unpack-', dir=models) as staging:
        with zipfile.ZipFile(archive) as source:
            for entry in source.infolist():
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != name or '\\' in entry.filename:
                    raise RuntimeError('Unexpected path in model archive')
            source.extractall(staging)
        (Path(staging)/name).rename(target)
    print('Pinned offline model verified and installed')


if __name__ == '__main__': main()
