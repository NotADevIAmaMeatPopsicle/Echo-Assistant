"""Local simulated installation and bridge tests. No Pi services or hardware."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
import urllib.request
import urllib.error
import httpx

PI=Path(__file__).resolve().parents[1]/'deploy/pi'
sys.path.insert(0,str(PI))
from bridge import Bridge
from connect import NoRedirect
spec=importlib.util.spec_from_file_location('echo_pi_setup',PI/'setup.py')
setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)


class BundleTests(unittest.TestCase):
    def test_first_boot_without_host_retries_without_exposing_credentials(self):
        class Unreachable:
            def open(self,*args,**kwargs):raise urllib.error.URLError('Synthetic network outage')
        class LocalBridge(Bridge):pass
        LocalBridge.configuration={'url':'https://host.invalid/display','credential':'test-private-credential'}
        LocalBridge.opener=Unreachable()
        server=ThreadingHTTPServer(('127.0.0.1',0),LocalBridge)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}',trust_env=False) as client:
                response=client.get('/display');self.assertEqual(response.status_code,503)
                self.assertIn('text/html',response.headers['content-type'])
                self.assertIn('5;url=/display',response.text)
                self.assertNotIn('test-private-credential',response.text)
                self.assertEqual(response.headers['cache-control'],'no-store')
                self.assertEqual(client.get('/v1/household').json()['detail'],'Echo host unavailable. Check its address, connection, and pairing status.')
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_install_idempotence_update_rollback_and_unmanaged_startup(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);home=root/'home';source=root/'source';source.mkdir()
            for name in (*setup.FILES,'runner.py'):shutil.copyfile(PI/name,source/name)
            first=setup.install_bundle(home,source);self.assertIsNone(first['previous'])
            self.assertEqual(setup.install_bundle(home,source),first)
            with (source/'kiosk.py').open('a') as stream:stream.write('\n# simulated new version\n')
            second=setup.install_bundle(home,source);self.assertEqual(second['previous'],first['active'])
            self.assertEqual(setup.rollback(home)['active'],first['active'])
            setup.write_autostart(home,'/usr/bin/python3')
            desktop=home/'.config/autostart/echo-display.desktop';desktop.write_text('User-owned startup')
            with self.assertRaises(ValueError):setup.write_autostart(home,'/usr/bin/python3')
            self.assertEqual(desktop.read_text(),'User-owned startup')

    def test_bridge_hides_credential_blocks_cross_origin_and_returns_revocation(self):
        observed=[];valid=[True]
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                observed.append(self.headers.get('Authorization'))
                raw=json.dumps({'ok':valid[0]}).encode();self.send_response(200 if valid[0] else 401)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
                self.send_header('Set-Cookie','private=never-forward');self.end_headers();self.wfile.write(raw)
        upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        class LocalBridge(Bridge):pass
        LocalBridge.configuration={'url':f'http://127.0.0.1:{upstream.server_port}/display','credential':'test-device-credential'}
        LocalBridge.opener=urllib.request.build_opener(NoRedirect,urllib.request.ProxyHandler({}))
        bridge=ThreadingHTTPServer(('127.0.0.1',0),LocalBridge)
        threads=[Thread(target=server.serve_forever,daemon=True) for server in (upstream,bridge)]
        for thread in threads:thread.start()
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{bridge.server_port}',trust_env=False) as client:
                response=client.get('/v1/display/session');self.assertEqual(response.status_code,200)
                self.assertEqual(observed,['Display test-device-credential'])
                self.assertNotIn('test-device',response.text);self.assertNotIn('set-cookie',response.headers)
                self.assertEqual(client.post('/v1/household',headers={'Origin':'https://untrusted.example','X-Echo-Request':'1'},json={}).status_code,403)
                self.assertEqual(client.get('/v1/display/session',headers={'Host':'untrusted.example'}).status_code,403)
                self.assertEqual(len(observed),1)
                valid[0]=False;response=client.get('/v1/display/session');self.assertEqual(response.status_code,401)
                self.assertEqual(response.headers['x-echo-display-bridge'],'1')
        finally:
            for server in (bridge,upstream):server.shutdown();server.server_close()
            for thread in threads:thread.join(2)
