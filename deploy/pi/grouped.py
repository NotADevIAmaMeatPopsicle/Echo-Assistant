"""Optional isolated Sendspin process, with Pi-local configuration and transient status."""
import json
import os
from pathlib import Path
import stat
import subprocess
import threading
import time

from spotify import outputs,validate_config,Unavailable


def private_json(path):
    if path.is_symlink() or path.stat().st_size>16384:raise ValueError('Use a regular private configuration file')
    info=path.stat()
    if os.name=='posix' and (stat.S_IMODE(info.st_mode)&0o077 or info.st_uid!=os.geteuid()):raise ValueError('Configuration must belong to this user with mode 600')
    return json.loads(path.read_text(encoding='utf-8'))


def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_suffix('.new')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(value,stream)
    os.replace(temporary,path)


class GroupReceiver:
    def __init__(self,connection,*,home=None,popen=subprocess.Popen):
        self.home=Path(home or Path.home());self.connection=Path(connection);self.popen=popen
        self.path=self.home/'.config/echo-display/group-music.json'
        self.python=self.home/'.local/share/echo-display/runtime/group-music/bin/python'
        runtime=Path(os.environ.get('XDG_RUNTIME_DIR',self.home/'.cache/echo-display'))
        self.status_path=runtime/'echo-group-music/status.json'
        self.config={'enabled':False,'name':'Echo Display','output':'','volume':2}
        self.error=None;self.process=None;self.lock=threading.RLock();self.stop=threading.Event()
        if self.path.exists():
            try:self.config=validate_config(private_json(self.path))
            except (OSError,ValueError,KeyError):self.error='Saved grouped-music settings could not be read; the original file was preserved'

    def snapshot(self):
        with self.lock:
            state={'phase':'disabled' if not self.config['enabled'] else 'starting'}
            if self.process and self.process.poll() is None:
                try:
                    saved=private_json(self.status_path)
                    if 0<=time.time()-saved.get('at',0)<6:state=saved
                except (OSError,ValueError,TypeError):pass
            elif self.config['enabled']:state={'phase':'unavailable'}
            return {'supported':True,'installed':self.python.is_file(),'config':dict(self.config),'outputs':outputs(),
                    'state':state,'error':self.error}

    def configure(self,value):
        checked=validate_config(value)
        if checked['enabled'] and not self.python.is_file():raise Unavailable('Install the optional grouped-music runtime first')
        if checked['enabled'] and checked['output'] not in {d['id'] for d in outputs()}:raise ValueError('Choose an attached output')
        with self.lock:
            if self.error:raise Unavailable(self.error)
            atomic(self.path,checked);self.config=checked;self.terminate()
        return self.snapshot()

    def terminate(self):
        process,self.process=self.process,None
        if process:
            try:process.terminate();process.wait(timeout=3)
            except (OSError,subprocess.TimeoutExpired):
                try:process.kill();process.wait(timeout=2)
                except (OSError,subprocess.TimeoutExpired):pass

    def run(self):
        while not self.stop.wait(2):
            with self.lock:
                if self.error or not self.config['enabled'] or not self.python.is_file():continue
                if self.process and self.process.poll() is None:continue
                args=[str(self.python),str(Path(__file__).with_name('sendspin_player.py')),'--config',str(self.path),
                      '--connection',str(self.connection),'--status',str(self.status_path)]
                try:self.process=self.popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                except OSError:continue
    def start(self):
        self.thread=threading.Thread(target=self.run,name='pi-group-music',daemon=True);self.thread.start()
    def close(self):
        self.stop.set()
        with self.lock:self.terminate()
        if hasattr(self,'thread'):self.thread.join(3)


def worker_volume(volume,factor):
    # Sendspin 7.5 uses amplitude=(volume/100)^1.5. Preserve Echo's linear output
    # percentage, including fractional attenuation, without touching ALSA gains.
    return 100*(max(0,min(30,volume))/100*max(0,min(1,factor)))**(2/3)
