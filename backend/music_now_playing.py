"""Short-lived current-track state, separate from content-free receiver diagnostics."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
from threading import Lock
import time
import urllib.request


def state_path(root):
    return Path('/run/echo/music-now-playing.json') if os.environ.get('ECHO_CONTAINER')=='1' else Path(root)/'local/music-now-playing.json'


def cover_url(value):
    return value if isinstance(value,str) and re.fullmatch(r'https://i\.scdn\.co/image/[a-fA-F0-9]{40}',value) else ''


def track_url(value):
    match=re.fullmatch(r'spotify:(track|episode):([A-Za-z0-9]{22})',str(value))
    return f'https://open.spotify.com/{match[1]}/{match[2]}' if match else ''


def publish(root,state):
    path=state_path(root);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps({**state,'updated_at':time.time()}),encoding='utf-8')
    if os.name!='nt':temporary.chmod(0o600)
    temporary.replace(path)


def snapshot(root):
    empty={'status':'unavailable','available':False,'capabilities':[]}
    if root is None:return empty
    try:
        path=state_path(root)
        if path.stat().st_size>12000:return empty
        state=json.loads(path.read_text(encoding='utf-8'))
        age=time.time()-state['updated_at']
        if not 0<=age<=8:return empty
        position=max(0,int(state.get('position_ms',0)))
        total=max(0,int(state.get('duration_ms',0)))
        if state['status']=='playing':position+=round(age*1000)
        art=cover_url(state.get('cover'))
        key=hashlib.sha256(art.encode()).hexdigest() if art else ''
        return {'status':state['status'],'available':True,
            'title':str(state.get('title',''))[:200],'artist':str(state.get('artist',''))[:400],
            'album':str(state.get('album',''))[:200], 'explicit':state.get('explicit') is True,
            'item_type':'episode' if state.get('item_type')=='Episode' else 'track',
            'position_ms':min(position,total),'duration_ms':total,
            'volume':state.get('volume'),'shuffle':state.get('shuffle'),'repeat':state.get('repeat'),
            'artwork':f'/v1/music/artwork/{key}' if key else None,
            'open_url':track_url(state.get('uri')),
            'capabilities':state.get('capabilities',[])}
    except (OSError,ValueError,TypeError,KeyError,AttributeError,OverflowError):return empty


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class Artwork:
    """One current cover in RAM; never fetch arbitrary URLs or keep listening history."""
    def __init__(self):self.key=None;self.content=None;self.lock=Lock()

    def get(self,root,key):
        with self.lock:
            current=snapshot(root)
            if current.get('artwork')!=f'/v1/music/artwork/{key}':
                self.key=self.content=None
                raise KeyError('Artwork is no longer current')
            if key==self.key:return self.content
            state=json.loads(state_path(root).read_text(encoding='utf-8'))
            url=cover_url(state.get('cover'))
            if not url or hashlib.sha256(url.encode()).hexdigest()!=key:raise KeyError('Track changed')
            opener=urllib.request.build_opener(NoRedirect,urllib.request.ProxyHandler({}))
            with opener.open(urllib.request.Request(url,headers={'Accept':'image/jpeg,image/png'}),timeout=6) as response:
                if response.headers.get_content_type() not in {'image/jpeg','image/png'}:raise ValueError('Invalid cover format')
                content=response.read(3_000_001)
            if len(content)>3_000_000:raise ValueError('Cover too large')
            from PIL import Image
            try:image=Image.open(io.BytesIO(content))
            except Image.DecompressionBombError:raise ValueError('Cover too large') from None
            with image:
                if image.width*image.height>16_000_000:raise ValueError('Cover too large')
                image.thumbnail((640,640));image=image.convert('RGB');output=io.BytesIO()
                image.save(output,format='JPEG',quality=88)
            self.key,self.content=key,output.getvalue()
            return self.content
