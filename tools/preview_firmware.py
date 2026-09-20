"""Render the shared firmware scene silently using the existing MSVC installation and Pillow."""
import os
from pathlib import Path
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'local/visual-preview'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    vswhere=Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    install=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
    if not install: raise SystemExit('Existing MSVC C++ tools required; no tools were installed.')
    vcvars=Path(install)/'VC/Auxiliary/Build/vcvars64.bat'
    build=OUT/'build.cmd'
    # Font headers include the Arduino umbrella. The harness already provides
    # the actual GFXfont types; no hardware implementation is linked on Windows.
    (OUT/'Arduino_GFX_Library.h').write_text('#pragma once\n',encoding='ascii')
    build.write_text(f'@call "{vcvars}" >nul\n@cl /nologo /EHsc /std:c++17 /O2 /D_CRT_SECURE_NO_WARNINGS /I"{OUT}" "{ROOT / "tools/render_voice_scene.cpp"}" /Fe:scene.exe /Fo:scene.obj\n',encoding='utf-8')
    subprocess.run(['cmd','/d','/c',str(build)],cwd=OUT,check=True)
    subprocess.run([str(OUT/'scene.exe'),str(OUT)],check=True)
    preview=ROOT/'preview/firmware'
    preview.mkdir(parents=True,exist_ok=True)
    states=['ready','listening','thinking','speaking','muted','offline','reply','notice','music','alarm','recording','playback','chime','mic_unavailable','long-reply']
    controls=['home','thermostat','thermostat-modes','bose','bose-volume','weather','music-controls','settings','connection','timers','new-timer','lights','speakers']
    states+=controls+[s+'-offline' for s in controls]+['thermostat-pending','thermostat-failed','thermostat-unconfirmed','music-muted']
    states+=['thermostat-off-no-target','thermostat-auto-no-target','thermostat-no-data']
    states+=['timers-empty','timers-stale','timers-full','timers-finished-silent','new-timer-pending','new-timer-full',
             'settings-muted','settings-mic-unavailable','settings-dim','settings-bright','connection-usb','connection-retrying']
    states += [f'power-{i}' for i in range(4)]
    states += ['lights-unassigned','lights-partial','lights-pending']
    states += ['spotify-'+s for s in ('not_configured','runtime_missing','unavailable','disconnected','discoverable','connected','playing','stopped','unexpected')]
    states += ['intercom-'+s for s in ('off','rooms','incoming','outgoing','active','muted')]
    states += ['screen-comfort']
    states += ['calendar-'+s for s in ('draft','confirm','pending','accepted','rejected','unconfirmed','deck','wide')]
    for state in states:
        image=Image.open(OUT/f'{state}.ppm').convert('RGBA')
        mask=Image.new('L',image.size);ImageDraw.Draw(mask).ellipse((0,0,465,465),fill=255)
        image.putalpha(mask);image.save(preview/f'{state}.png')
    sheet=Image.new('RGB',(3*510,2*525),'#101719');draw=ImageDraw.Draw(sheet)
    label=ImageFont.truetype(str(Path(os.environ['WINDIR'])/'Fonts/segoeui.ttf'),20)
    for j,state in enumerate(states[:6]):
        x=j%3*510+22;y=j//3*525+12
        im=Image.open(preview/f'{state}.png');sheet.paste(im,(x,y),im)
        draw.text((x+233,y+477),state.capitalize(),font=label,fill='#b6c8c0',anchor='mt')
    sheet.save(preview/'states.png')
    controlSheet=Image.new('RGB',(3*510,2*525),'#101719');controlDraw=ImageDraw.Draw(controlSheet)
    for j,state in enumerate(['home','thermostat','weather','timers','music-controls','settings']):
        x=j%3*510+22;y=j//3*525+12;im=Image.open(preview/f'{state}.png');controlSheet.paste(im,(x,y),im)
        controlDraw.text((x+233,y+477),state.replace('-',' ').title(),font=label,fill='#b6c8c0',anchor='mt')
    controlSheet.save(preview/'controls.png')
    frames=[Image.open(OUT/f'motion-{j:02d}.ppm').convert('RGB') for j in range(28)]
    frames[0].save(preview/'listening.gif',save_all=True,append_images=frames[1:],duration=100,loop=0)
    cards=''.join(f'<figure><img src="{state}.png" alt="{state} firmware state"><figcaption>{state.replace("_"," ").title()}</figcaption></figure>' for state in states)
    (preview/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Round Voice · Firmware gallery</title><style>body{background:#101719;color:#c8d8d0;font:16px system-ui;margin:40px}a{color:#a0f5d5}main{display:flex;gap:28px;flex-wrap:wrap}figure{margin:0;text-align:center}img{width:min(466px,85vw)}figcaption{margin:12px}</style><a href="../">← Design studio</a><h1>The device, in detail.</h1><p>Silent fixtures from the firmware renderer. Sample states and responses, not live device status.</p><main>'+cards+'</main><h2>Listening motion · 10 frames per second</h2><img src="listening.gif" alt="Listening animation">',encoding='utf-8')
    print('Firmware gallery:',preview/'index.html')
    print('Contact sheet:',preview/'states.png')

if __name__=='__main__':main()
