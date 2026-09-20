"""Configure an opt-in, user-owned PulseAudio/WebRTC path on a dedicated Pi.

This writes configuration only. It does not start capture, select devices in
Echo, change volume, or replace a running desktop audio server. See PI_VOICE.md.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil

MARKER='# Managed by Echo echo-cancelled audio'
BEGIN='# BEGIN ECHO ECHO-CANCELLED AUDIO'
END='# END ECHO ECHO-CANCELLED AUDIO'


def pcm(value):
    if not isinstance(value,str) or not re.fullmatch(r'(?:plug)?hw:(?:CARD=)?[A-Za-z0-9_]{1,40}(?:,DEV=|,)\d{1,2}',value):
        raise ValueError('Select an explicit named hardware PCM, such as plughw:CARD=USB,DEV=0')
    return value


def files(home):
    home=Path(home)
    return (home/'.asoundrc',home/'.config/echo-display/echo-audio.pa',
            home/'.config/systemd/user/echo-audio.service')


def contents(home,source,sink,uid):
    source,sink=pcm(source),pcm(sink)
    if type(uid) is not int or uid<1:raise ValueError('Use the normal Pi desktop user')
    server=f'unix:/run/user/{uid}/echo-audio/native'
    alsa=f'''{BEGIN}
pcm.echo_cancelled {{
    type pulse
    server "{server}"
    device "echo_cancelled"
    hint {{ show on ioid "Input" description "Echo microphone with speaker echo cancellation" }}
}}
pcm.echo_processed {{
    type pulse
    server "{server}"
    device "echo_processed"
    hint {{ show on ioid "Output" description "Echo speaker with echo reference" }}
}}
{END}'''
    pulse=f'''{MARKER}
.fail
load-module module-native-protocol-unix auth-cookie-enabled=0
load-module module-alsa-sink sink_name=echo_playback_master device={sink} rate=48000 channels=2 tsched=0
load-module module-alsa-source source_name=echo_capture_master device={source} rate=48000 channels=1 tsched=0
load-module module-echo-cancel source_name=echo_cancelled sink_name=echo_processed source_master=echo_capture_master sink_master=echo_playback_master rate=48000 channels=1 aec_method=webrtc aec_args="analog_gain_control=0 digital_gain_control=0 noise_suppression=1 high_pass_filter=1" save_aec=0
load-module module-suspend-on-idle timeout=2
set-default-source echo_cancelled
set-default-sink echo_processed
'''
    unit=f'''{MARKER}
[Unit]
Description=Echo speaker echo cancellation
Before=echo-display-bridge.service

[Service]
Type=simple
Environment=PULSE_RUNTIME_PATH=%t/echo-audio
Environment=PULSE_STATE_PATH=%h/.local/state/echo-display/pulse
RuntimeDirectory=echo-audio
RuntimeDirectoryMode=0700
ExecStart=/usr/bin/pulseaudio --daemonize=no --exit-idle-time=-1 --use-pid-file=no --disable-shm=yes --log-target=journal -n --file="%h/.config/echo-display/echo-audio.pa"
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
UMask=0077

[Install]
WantedBy=default.target
'''
    return alsa,pulse,unit


def old_files(home):
    result={}
    for path in files(home):
        if path.is_symlink():raise ValueError('Inspect existing configuration symlinks before changing audio')
        if path.exists() and (not path.is_file() or path.stat().st_size>200_000):raise ValueError('Unexpected audio configuration')
        value=path.read_text() if path.exists() else ''
        if path.name!='.asoundrc' and value and not value.startswith(MARKER):raise ValueError('An unmanaged audio file would be replaced')
        result[path]=value
    value=result[files(home)[0]]
    if value.count(BEGIN)!=value.count(END) or value.count(BEGIN)>1 or BEGIN in value and value.index(END)<value.index(BEGIN):
        raise ValueError('The existing Echo ALSA block is incomplete')
    return result


def atomic(path,text):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_name(path.name+'.echo-new')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as out:out.write(text)
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def configure(home,source,sink,uid):
    old=old_files(home);paths=files(home);block,pulse,unit=contents(home,source,sink,uid)
    prior=old[paths[0]]
    if BEGIN in prior:
        start=prior.index(BEGIN);end=prior.index(END)+len(END)
        alsa=prior[:start]+block+prior[end:]
    else:
        if re.search(r'\bpcm\.(echo_cancelled|echo_processed)\b',prior):raise ValueError('An unmanaged Echo PCM already exists')
        alsa=prior.rstrip()+'\n\n'+block+'\n'
    existed={path for path in paths if path.exists()}
    for path in paths:
        backup=path.with_name(path.name+'.before-echo-aec')
        if backup.is_symlink() or backup.exists() and not backup.is_file():
            raise ValueError('Inspect the existing audio backup before changing configuration')
    changed=[]
    try:
        for path,value in zip(paths,(alsa,pulse,unit)):
            if value==old[path]:continue
            backup=path.with_name(path.name+'.before-echo-aec')
            if path.exists() and not backup.exists():shutil.copy2(path,backup)
            atomic(path,value);changed.append(path)
        (Path(home)/'.local/state/echo-display/pulse').mkdir(parents=True,exist_ok=True,mode=0o700)
    except OSError:
        for path in reversed(changed):
            if path in existed:atomic(path,old[path])
            else:path.unlink(missing_ok=True)
        raise


def remove(home):
    old=old_files(home);paths=files(home);text=old[paths[0]]
    if BEGIN in text:
        start=text.index(BEGIN);end=text.index(END)+len(END)
        atomic(paths[0],text[:start]+text[end:])
    for path in paths[1:]:
        if path.exists():path.unlink()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    for name in ('check','configure','remove'):mode.add_argument('--'+name,action='store_true')
    parser.add_argument('--input');parser.add_argument('--output');args=parser.parse_args()
    if args.check:
        print(json.dumps({'programs':{n:bool(shutil.which(n)) for n in ('pulseaudio','pactl','arecord','aplay')},
                          'configured':files(Path.home())[1].is_file(),'input':'echo_cancelled','output':'echo_processed'}));return
    if os.name!='posix' or os.geteuid()==0:raise SystemExit('Run as the normal Pi desktop user, without sudo.')
    if args.remove:remove(Path.home());print('Echo audio configuration removed. Reload user systemd after stopping its service.');return
    configure(Path.home(),args.input,args.output,os.getuid())
    print('Configuration written. Follow PI_VOICE.md to start the dedicated audio service and select both Echo PCMs. No audio was opened.')


if __name__=='__main__':main()
