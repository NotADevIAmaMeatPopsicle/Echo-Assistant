"""Enroll an Echo display using a short-lived owner-approved code (no master key)."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import ssl
import urllib.request
from urllib.parse import urlsplit

from kiosk import validate_url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def private_write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_suffix('.new')
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as stream: json.dump(data,stream)
        temporary.replace(path)
    finally:
        if temporary.exists(): temporary.unlink()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True,help='HTTPS Echo /display URL, or local forwarded HTTP URL')
    parser.add_argument('--replace',action='store_true')
    args=parser.parse_args(); url=validate_url(args.url)
    path=Path.home()/'.config/echo-display/connection.json'
    if path.exists() and not args.replace: raise SystemExit('Already paired. Revoke the old display in Echo first, then use --replace.')
    code=getpass.getpass('Pairing code from Echo Settings (hidden): ').strip()
    if not re.fullmatch('[A-Za-z0-9_-]{32,64}',code): raise SystemExit('Invalid pairing code format')
    origin=urlsplit(url); base=f'{origin.scheme}://{origin.netloc}'
    opener=urllib.request.build_opener(NoRedirect,urllib.request.HTTPSHandler(context=ssl.create_default_context()),urllib.request.ProxyHandler({}))
    request=urllib.request.Request(base+'/v1/displays/enroll',data=json.dumps({'code':code}).encode(),headers={'Content-Type':'application/json','X-Echo-Request':'1','Origin':base})
    with opener.open(request,timeout=20) as response: enrolled=json.loads(response.read(8192))
    if not re.fullmatch(r'[a-f0-9]{32}\.[A-Za-z0-9_-]{40,64}',enrolled.get('credential','')): raise SystemExit('Unexpected enrollment response')
    private_write(path,{'url':url,'credential':enrolled['credential'],'name':enrolled['name']})
    private_write(path.with_name('config.json'),{'url':'http://127.0.0.1:8790/display'})
    print('Display paired. Its restricted credential is stored privately; no host API key was copied.')


if __name__=='__main__':
    try: main()
    except (OSError,ValueError,KeyError): raise SystemExit('Pairing failed. Check the URL, trusted certificate, and unexpired code.') from None
