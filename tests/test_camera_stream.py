"""Real streaming parser and relay exercised with synthetic MJPEG, never home cameras."""
import asyncio
import unittest
from unittest.mock import patch

import httpx

from backend.camera_stream import CameraStream, JpegParts, MAX_FRAME
from backend.experiences import Experiences, SourceStore
from backend.home import HomeBridge, HomeConfig
from backend.display_auth import allowed


FRAME = b'\xff\xd8\xfftest frame\xff\xd9'


def part(frame=FRAME, length=True):
    return (b'--sample\r\nContent-Type: image/jpeg\r\n' +
            (b'Content-Length: '+str(len(frame)).encode()+b'\r\n' if length else b'') +
            b'\r\n'+frame+b'\r\n')


class ParserTests(unittest.TestCase):
    def test_arbitrary_network_splits_and_missing_length(self):
        raw = part()+part(length=False)+b'--sample--\r\n'
        for size in (1, 7, 29, len(raw)):
            parser = JpegParts('multipart/x-mixed-replace; boundary="sample"')
            frames = []
            for i in range(0,len(raw),size): frames.extend(parser.feed(raw[i:i+size]))
            self.assertEqual(frames,[FRAME,FRAME]); self.assertTrue(parser.done)

    def test_bounds_and_non_images_rejected(self):
        for mime in ('text/html', 'multipart/x-mixed-replace; boundary="bad\r\nheader"'):
            with self.assertRaises(ValueError): JpegParts(mime)
        for raw in (b'--sample\r\nContent-Type: text/html\r\n\r\n',
                    b'--sample\r\nContent-Type: image/jpeg\r\nContent-Length: 5000001\r\n\r\n',
                    part(b'<script>bad</script>'), b'x'*4097):
            with self.assertRaises(ValueError): JpegParts('multipart/x-mixed-replace; boundary=sample').feed(raw)
        self.assertTrue(allowed('GET','/v1/display/cameras/camera.porch/stream'))
        self.assertFalse(allowed('GET','/v1/display/cameras/../stream'))


class Chunks(httpx.AsyncByteStream):
    def __init__(self): self.closed=False
    async def __aiter__(self):
        yield part()
        await asyncio.sleep(0)
        yield part(b'\xff\xd8\xffsecond\xff\xd9')
        yield b'--sample--\r\n'
    async def aclose(self): self.closed=True


class RelayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.requests=[]; self.streams=[]; self.response=None; self.authorized=True
        def respond(request):
            self.requests.append(request)
            if self.response is not None:return self.response
            stream=Chunks();self.streams.append(stream)
            return httpx.Response(200,stream=stream,headers={'Content-Type':'multipart/x-mixed-replace; boundary=sample'})
        home=HomeBridge(HomeConfig(True,'http://127.0.0.1:8123','synthetic-token',{'weather':'weather.demo'}),httpx.MockTransport(respond))
        self.store=SourceStore(None,None);self.store.save({'cameras':['camera.porch']},0)
        self.experiences=Experiences(home,self.store)

    def check(self):
        if not self.authorized:raise PermissionError('Display access revoked')

    def relay(self,identifier='camera.porch'):return CameraStream(self.experiences,identifier,self.check)

    async def test_selected_stream_normalized_and_closed(self):
        relay=await self.relay().open(); frames=[frame async for frame in relay.body()]
        self.assertEqual(len(frames),2);self.assertTrue(frames[0].startswith(b'--echo-frame\r\n'))
        self.assertTrue(all(s.closed for s in self.streams));self.assertFalse(relay.acquired)
        request=self.requests[0];self.assertEqual(request.url.path,'/api/camera_proxy_stream/camera.porch')
        self.assertEqual(request.headers['authorization'],'Bearer synthetic-token')
        self.assertNotIn('synthetic-token',str(request.url))

    async def test_revoke_display_or_camera_stops_before_next_frame(self):
        for display in (True,False):
            self.authorized=True;self.store.save({'cameras':['camera.porch']},self.store.revision)
            relay=await self.relay().open();body=relay.body();await anext(body)
            if display:self.authorized=False
            else:self.store.save({},self.store.revision)
            self.assertEqual([x async for x in body],[]);self.assertFalse(relay.acquired)
        count=len(self.requests)
        with self.assertRaises(PermissionError):await self.relay('camera.private').open()
        self.assertEqual(len(self.requests),count)

    async def test_redirect_failure_and_cancellation_release_resources(self):
        self.response=httpx.Response(302,headers={'Location':'https://untrusted.example/'})
        relay=self.relay()
        with self.assertRaises(httpx.HTTPStatusError):await relay.open()
        self.assertFalse(relay.acquired);self.assertEqual(len(self.requests),1)
        self.response=None
        relay=await self.relay().open();body=relay.body();await anext(body);await body.aclose()
        self.assertTrue(self.streams[-1].closed);self.assertFalse(relay.acquired)


if __name__=='__main__':unittest.main()
