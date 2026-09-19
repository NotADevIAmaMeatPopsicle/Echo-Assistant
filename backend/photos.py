"""A bounded private ambient album, normalized to remove embedded metadata."""
import hashlib
from io import BytesIO
from pathlib import Path
import re
from threading import RLock
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError


class PhotoUnavailable(RuntimeError): pass


class Photos:
    maximum = 60
    def __init__(self, root, protector):
        self.directory = Path(root)/'local/display-photos' if root else None
        self.protector, self.lock, self.memory = protector, RLock(), {}

    def entries(self):
        if not self.directory: return sorted(self.memory)
        try:
            if not self.directory.exists(): return []
            if self.directory.is_symlink(): raise ValueError()
            return sorted(p.stem for p in self.directory.glob('*.photo') if re.fullmatch(r'[a-f0-9]{32}', p.stem) and not p.is_symlink())
        except (OSError, ValueError): raise PhotoUnavailable('The saved photo album is unavailable.') from None

    def snapshot(self):
        with self.lock:
            entries = self.entries()
            return {'items': [{'id': identifier, 'url': '/v1/display/photos/'+identifier} for identifier in entries],
                    'limit': self.maximum, 'storage': 'encrypted' if self.directory else 'session'}

    @staticmethod
    def normalize(raw):
        if not raw or len(raw)>12_000_000: raise ValueError('Choose a JPEG, PNG, or WebP under 12 MB')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as source:
                    if source.format not in {'JPEG', 'PNG', 'WEBP'} or source.width*source.height>32_000_000: raise ValueError()
                    source.seek(0); source.load()
                    image = ImageOps.exif_transpose(source).convert('RGB')
                    image.thumbnail((1920, 1920))
                    # A fresh image carries pixels only: no EXIF, GPS, XMP or comments.
                    clean = Image.new('RGB', image.size); clean.paste(image)
                    output = BytesIO(); clean.save(output, 'JPEG', quality=85, optimize=True)
                    if output.tell()>4_000_000: raise ValueError()
                    return output.getvalue()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ValueError('Use a valid JPEG, PNG, or WebP up to 32 megapixels') from None

    def add(self, raw):
        image = self.normalize(raw); identifier = hashlib.sha256(image).hexdigest()[:32]
        with self.lock:
            entries = self.entries()
            if identifier in entries: return {'id': identifier, 'existing': True}
            if len(entries)>=self.maximum: raise ValueError('The album is full. Remove a photo before adding another.')
            if self.directory:
                try:
                    self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                    target = self.directory/(identifier+'.photo')
                    temporary = self.directory/(identifier+'.tmp')
                    temporary.write_bytes(self.protector.encrypt(image)); temporary.chmod(0o600); temporary.replace(target)
                except (OSError, RuntimeError): raise PhotoUnavailable('Photo could not be saved.') from None
            else: self.memory[identifier] = image
            return {'id': identifier, 'existing': False}

    def read(self, identifier):
        with self.lock:
            if not re.fullmatch(r'[a-f0-9]{32}', identifier) or identifier not in self.entries(): raise KeyError(identifier)
            if not self.directory: return self.memory[identifier]
            try:
                path = self.directory/(identifier+'.photo')
                if path.is_symlink() or path.stat().st_size>6_000_000: raise ValueError()
                return self.protector.decrypt(path.read_bytes())
            except (OSError, ValueError, RuntimeError): raise PhotoUnavailable('This photo could not be opened. Its saved file is preserved.') from None

    def delete(self, identifier):
        with self.lock:
            if not re.fullmatch(r'[a-f0-9]{32}', identifier) or identifier not in self.entries(): raise KeyError(identifier)
            try:
                if self.directory: (self.directory/(identifier+'.photo')).unlink()
                else: self.memory.pop(identifier)
            except OSError: raise PhotoUnavailable('Photo could not be removed.') from None
