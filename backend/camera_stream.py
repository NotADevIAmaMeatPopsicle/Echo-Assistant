"""Bounded MJPEG relay for owner-selected cameras. No recordings or upstream URLs."""
import asyncio
from email.message import Message
import re
from threading import BoundedSemaphore
import time

import anyio
import httpx
from starlette.exceptions import HTTPException

from .home import HomeUnavailable

MAX_FRAME = 5_000_000
MAX_STREAM = 128_000_000
MAX_SECONDS = 120
_slots = BoundedSemaphore(3)


class JpegParts:
    """Read MIME parts, accepting either Content-Length or boundary-delimited JPEGs."""
    def __init__(self, content_type):
        header = Message(); header['content-type'] = content_type
        boundary = header.get_param('boundary')
        if (header.get_content_type() != 'multipart/x-mixed-replace' or
                not isinstance(boundary, str) or not re.fullmatch(r'[A-Za-z0-9_+.=-]{1,70}', boundary)):
            raise ValueError('Unsupported camera stream')
        self.boundary = b'--' + boundary.encode('ascii')
        self.buffer = bytearray()
        self.headers = None
        self.done = False

    def feed(self, chunk):
        if self.done: return []
        self.buffer.extend(chunk)
        frames = []
        while True:
            if self.headers is None:
                start = self.buffer.find(self.boundary)
                if start < 0:
                    if len(self.buffer) > 4096: raise ValueError('Invalid camera boundary')
                    break
                end = start + len(self.boundary)
                if len(self.buffer) < end + 2: break
                if self.buffer[end:end+2] == b'--': self.done = True; break
                if self.buffer[end:end+2] != b'\r\n': raise ValueError('Invalid camera boundary')
                split = self.buffer.find(b'\r\n\r\n', end)
                if split < 0:
                    if len(self.buffer) > 4096: raise ValueError('Camera headers too large')
                    break
                if split - end > 4096: raise ValueError('Camera headers too large')
                headers = {}
                for line in bytes(self.buffer[end+2:split]).split(b'\r\n'):
                    key, separator, value = line.partition(b':')
                    if not separator: raise ValueError('Invalid camera headers')
                    key = key.strip().lower()
                    if key in headers: raise ValueError('Repeated camera header')
                    headers[key] = value.strip().lower()
                if headers.get(b'content-type') != b'image/jpeg': raise ValueError('Camera stream needs JPEG frames')
                length = headers.get(b'content-length')
                if length is not None:
                    if not length.isdigit() or not 4 <= int(length) <= MAX_FRAME: raise ValueError('Invalid frame length')
                    length = int(length)
                self.headers = (length,)
                del self.buffer[:split+4]
            length = self.headers[0]
            if length is None:
                end = self.buffer.find(b'\r\n' + self.boundary)
                if end < 0:
                    if len(self.buffer) > MAX_FRAME + len(self.boundary) + 2: raise ValueError('Frame too large')
                    break
                length = end
            elif len(self.buffer) < length:
                break
            if length > MAX_FRAME: raise ValueError('Frame too large')
            frame = bytes(self.buffer[:length])
            if not frame.startswith(b'\xff\xd8\xff') or not frame.endswith(b'\xff\xd9'):
                raise ValueError('Invalid JPEG frame')
            del self.buffer[:length]
            self.headers = None
            frames.append(frame)
        if len(self.buffer) > MAX_FRAME + 8192: raise ValueError('Camera buffer too large')
        return frames


def multipart(frame):
    return (b'--echo-frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
            str(len(frame)).encode('ascii') + b'\r\n\r\n' + frame + b'\r\n')


class CameraStream:
    def __init__(self, experiences, identifier, authorize):
        self.experiences, self.identifier, self.authorize = experiences, identifier, authorize
        self.client = self.response = None
        self.acquired = False
        self.first = None

    def check(self):
        self.authorize()
        if self.identifier not in self.experiences.store.snapshot()['sources']['cameras']:
            raise PermissionError('Camera is not selected for displays')
        if not self.experiences.home.config.enabled: raise HomeUnavailable('Home integration is not configured')

    async def open(self):
        self.check()
        if not _slots.acquire(blocking=False): raise HomeUnavailable('All camera views are busy. Close another view and retry.')
        self.acquired = True
        home = self.experiences.home
        try:
            self.client = httpx.AsyncClient(transport=home.transport, timeout=httpx.Timeout(8, connect=5),
                                            trust_env=False, follow_redirects=False)
            self.response = await self.client.send(self.client.build_request('GET',
                home.config.base_url + '/api/camera_proxy_stream/' + self.identifier,
                headers={'Authorization': 'Bearer ' + home.config.token}), stream=True)
            self.response.raise_for_status()
            parser = JpegParts(self.response.headers.get('content-type', ''))
            self.iterator = self.read_frames(parser)
            # Reject unavailable cameras before sending HTTP 200 to the browser.
            async with asyncio.timeout(10): self.first = await anext(self.iterator)
            self.check()
            return self
        except BaseException:
            await self.close()
            raise

    async def read_frames(self, parser):
        size, started = 0, time.monotonic()
        async for block in self.response.aiter_bytes():
            size += len(block)
            if size > MAX_STREAM or time.monotonic() - started > MAX_SECONDS: return
            self.check()
            for frame in parser.feed(block):
                self.check()
                yield frame
            if parser.done: return

    async def body(self):
        try:
            self.check()
            yield multipart(self.first)
            self.first = None
            async for frame in self.iterator:
                self.check()
                yield multipart(frame)
        except (httpx.HTTPError, HTTPException, ValueError, RuntimeError, PermissionError, HomeUnavailable):
            # Never expose camera responses or credentials in a stream error.
            pass
        finally:
            await self.close()

    async def close(self):
        with anyio.CancelScope(shield=True):
            try:
                if self.response is not None: await self.response.aclose()
                if self.client is not None: await self.client.aclose()
            finally:
                if self.acquired: _slots.release(); self.acquired = False
