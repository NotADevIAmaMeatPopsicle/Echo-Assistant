"""Install a pinned, checksum-verified Hermes WebUI without agent/bootstrap changes."""
import argparse
import hashlib
import io
from pathlib import Path, PurePosixPath
import tarfile
import urllib.request

REVISION = 'c3ff9f41c77b674dd3cdfbe407f17169755269da'
SHA256 = 'b6aa0bf8cd979cef94a29f23cc4334a57f42f1c4894dad8f065ce2ae15cfe1d2'
URL = f'https://codeload.github.com/nesquena/hermes-webui/tar.gz/{REVISION}'
TARGET = Path('/opt/echo-webui')


def install(archive=None):
    stamp = TARGET / '.echo-upstream-revision'
    if stamp.exists() and stamp.read_text().strip() == REVISION:
        return
    if TARGET.exists() and any(TARGET.iterdir()):
        raise RuntimeError('WebUI source directory already contains another installation')
    if archive:
        data = Path(archive).read_bytes()
    else:
        with urllib.request.urlopen(URL, timeout=90) as response:
            data = response.read(64 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise RuntimeError('Hermes WebUI archive checksum mismatch')
    TARGET.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as bundle:
        for member in bundle:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != f'hermes-webui-{REVISION}':
                raise RuntimeError('Unexpected source archive root')
            relative = PurePosixPath(*parts[1:])
            if relative.is_absolute() or '..' in relative.parts:
                raise RuntimeError('Unsafe source archive path')
            if not relative.parts or relative.parts[0] not in {
                'api', 'static', 'server.py', 'LICENSE', 'README.md', 'requirements.txt'
            }:
                continue
            destination = TARGET.joinpath(*relative.parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as source:
                    destination.write_bytes(source.read())
                destination.chmod(0o644)
            else:
                raise RuntimeError('Source archive contains a non-regular runtime file')
    stamp.write_text(REVISION + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive')
    install(parser.parse_args().archive)
