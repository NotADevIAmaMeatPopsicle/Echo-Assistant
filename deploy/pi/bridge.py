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
        headers={'Authorization':'Display '+self.configuration['credential'],'X-Echo-Request':'1','Origin':base}
        for key in ('Content-Type','Range','Accept'):
            if self.headers.get(key): headers[key]=self.headers[key]
        request=urllib.request.Request(base+path,data=body,method=self.command,headers=headers)
        started=False
        try:
            try: response=self.opener.open(request,timeout=120)
            except urllib.error.HTTPError as error: response=error
            with response:
                self.send_response(response.status)
                for key in ('Content-Type','Content-Length','Content-Range','Accept-Ranges','Content-Security-Policy','Referrer-Policy','X-Content-Type-Options'):
                    if response.headers.get(key):self.send_header(key,response.headers[key])
                self.send_header('Cache-Control','no-store'); self.send_header('X-Echo-Display-Bridge','1'); self.end_headers(); started=True
                if self.command!='HEAD':
                    while block:=response.read(65536): self.wfile.write(block)
        except (urllib.error.URLError,TimeoutError):
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
