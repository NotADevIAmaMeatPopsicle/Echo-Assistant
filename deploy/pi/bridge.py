"""Loopback-only browser bridge. The restricted device credential stays off the page."""
import argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
import stat
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from kiosk import validate_url
from connect import NoRedirect


class Bridge(BaseHTTPRequestHandler):
    configuration=None
    opener=None

    def log_message(self,*args): pass

    def error_reply(self,code,message):
        body=json.dumps({'detail':message}).encode()
        self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers()
        if self.command!='HEAD': self.wfile.write(body)

    def waiting_page(self):
        # This must work before the host's JavaScript has ever loaded, including
        # a boot where Wi-Fi, Tailscale or the API is still starting.
        body=b'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="5;url=/display"><title>Echo is reconnecting</title>
<style>body{margin:0;min-height:100vh;display:grid;place-content:center;text-align:center;
background:radial-gradient(ellipse at top,#183449,#07121f);color:#edf5ff;font:22px system-ui}
h1{font-size:42px;margin:0 0 16px}p{max-width:34em;color:#b2c4d3;line-height:1.5;padding:0 24px}
a{color:#96eadc}span{font-size:15px;letter-spacing:.2em;color:#96eadc}</style>
<span>ECHO / AT HOME</span><h1>A moment to reconnect.</h1>
<p>Your display is ready. Waiting for the private connection to the Echo host.</p>
<p>This page retries automatically. <a href="/display">Try now</a></p></html>'''
        self.send_response(503)
        for key,value in {'Content-Type':'text/html; charset=utf-8','Content-Length':str(len(body)),
                          'Cache-Control':'no-store','Retry-After':'5',
                          'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"}.items():self.send_header(key,value)
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(body)

    def proxy(self):
        host=self.headers.get('Host',''); port=self.server.server_port
        if host not in {f'127.0.0.1:{port}',f'localhost:{port}'}: return self.error_reply(403,'Use the local display address')
        requested=urlsplit(self.path)
        if requested.scheme or requested.netloc or not requested.path.startswith(('/v1/','/assets/')) and requested.path not in {'/','/display','/health'}:
            return self.error_reply(403,'Administration is available in the owner workspace')
        body=None
        if self.command not in {'GET','HEAD'}:
            if self.headers.get('Origin') not in {None,'http://'+host} or self.headers.get('X-Echo-Request')!='1': return self.error_reply(403,'Use the local Echo display')
            try:size=int(self.headers.get('Content-Length','0'))
            except ValueError:return self.error_reply(400,'Invalid request length')
            if not 0<=size<=16_000_000:return self.error_reply(413,'Request is too large')
            body=self.rfile.read(size)
        source=urlsplit(self.configuration['url']); base=f'{source.scheme}://{source.netloc}'
        path='/display' if self.path=='/' else self.path
        display_page=requested.path in {'/','/display'} and self.command in {'GET','HEAD'}
        headers={'Authorization':'Display '+self.configuration['credential'],'X-Echo-Request':'1','Origin':base}
        for key in ('Content-Type','Range','Accept'):
            if self.headers.get(key): headers[key]=self.headers[key]
        request=urllib.request.Request(base+path,data=body,method=self.command,headers=headers)
        started=False
        try:
            try: response=self.opener.open(request,timeout=10 if display_page else 120)
            except urllib.error.HTTPError as error: response=error
            with response:
                if display_page and response.status>=500:return self.waiting_page()
                self.send_response(response.status)
                for key in ('Content-Type','Content-Length','Content-Range','Accept-Ranges','Content-Security-Policy','Referrer-Policy','X-Content-Type-Options'):
                    if response.headers.get(key):self.send_header(key,response.headers[key])
                self.send_header('Cache-Control','no-store'); self.send_header('X-Echo-Display-Bridge','1'); self.end_headers(); started=True
                if self.command!='HEAD':
                    while block:=response.read1(65536):
                        self.wfile.write(block)
                        self.wfile.flush()
        except (urllib.error.URLError,TimeoutError):
            if not started and display_page:return self.waiting_page()
            if not started: return self.error_reply(503,'Echo host unavailable. Check its address, connection, and pairing status.')
            self.close_connection=True
        except (BrokenPipeError,ConnectionResetError): pass

    do_GET=do_HEAD=do_POST=do_PUT=do_PATCH=do_DELETE=proxy


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--port',type=int,default=8790)
    parser.add_argument('--config',type=Path,default=Path.home()/'.config/echo-display/connection.json')
    args=parser.parse_args()
    if args.config.is_symlink(): raise SystemExit('Use a regular, private connection file')
    info=args.config.stat()
    if os.name=='posix' and (stat.S_IMODE(info.st_mode)&0o077 or info.st_uid!=os.geteuid()): raise SystemExit('Connection file must belong to this user with mode 600')
    config=json.loads(args.config.read_text()); validate_url(config['url'])
    Bridge.configuration=config
    Bridge.opener=urllib.request.build_opener(NoRedirect,urllib.request.HTTPSHandler(context=ssl.create_default_context()),urllib.request.ProxyHandler({}))
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Bridge)
    print(f'Echo display bridge listening on loopback port {args.port}. Credentials stay outside the browser.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError):raise SystemExit('Display bridge could not start. Check its private configuration and pairing.') from None
