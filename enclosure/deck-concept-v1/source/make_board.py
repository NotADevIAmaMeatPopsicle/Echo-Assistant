"""Compose the actual Blender renders into a presentation sheet."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / 'preview'
for name in ['echo-deck-front.png', 'echo-deck-rear.png', 'echo-deck-service.png']:
    path = PREVIEW / name
    with Image.open(path) as raw:
        clean = Image.new('RGB', raw.size)
        clean.paste(raw.convert('RGB'))
        clean.save(path, optimize=True)

W, H = 2600, 1960
BG = '#edf0ee'
INK = '#122c39'
MUTED = '#4f6670'
MINT = '#3eacaa'
im = Image.new('RGB', (W,H), BG)
d = ImageDraw.Draw(im)
font_path = ROOT.parents[1] / 'web' / 'fonts' / 'Manrope-Variable.ttf'
def font(size, bold=False):
    result = ImageFont.truetype(str(font_path), size)
    result.set_variation_by_axes([700 if bold else 400])
    return result
def put(x,y,body,size=30,bold=False,color=INK):
    d.text((x,y), body, font=font(size,bold), fill=color)
def panel(file, box):
    pic=Image.open(PREVIEW/file).convert('RGB')
    fitted=ImageOps.contain(pic, (box[2]-box[0],box[3]-box[1]), Image.Resampling.LANCZOS)
    x=box[0]+(box[2]-box[0]-fitted.width)//2
    y=box[1]+(box[3]-box[1]-fitted.height)//2
    im.paste(fitted,(x,y))

d.ellipse((78,61,146,129), outline=MINT, width=7)
d.ellipse((88,71,136,119), outline='#81cbc8', width=2)
put(170,58,'ECHO DECK',57,True)
put(172,124,'SMART DISPLAY + SMART SPEAKER',23,color=MUTED)
put(1930,68,'ENCLOSURE STUDY 01',25,True)
put(1930,106,'Wood / midnight / woven fabric',23,color=MUTED)
d.line((78,185,W-78,185),fill='#c7d5d3',width=2)

panel('echo-deck-front.png',(25,285,1640,1510))
panel('echo-deck-rear.png',(1690,260,2555,932))
panel('echo-deck-service.png',(1690,1010,2555,1682))
put(87,230,'01  /  THE EVERYDAY VIEW',24,True)
put(1714,222,'02  /  REAR ACCESS',24,True)
put(1714,974,'03  /  INSIDE THE CONCEPT',24,True)

put(88,1535,'Familiar hardware. A cohesive home.',45,True)
put(90,1607,'Your landscape display, Pi 4, CSI camera, USB audio',29,color=MUTED)
put(90,1653,'and salvaged speaker in one serviceable design.',29,color=MUTED)
d.line((78,1740,W-78,1740),fill='#c7d5d3',width=2)
for x,title,desc in [
    (90,'A warm frame','Wood trim recalls the original picture-frame build.'),
    (950,'Room for the hardware','Raised screen, vented back and a substantial base.'),
    (1820,'Echo, on screen','The existing dashboard and blue-green ring.')]:
    put(x,1779,title,30,True)
    words=desc.split(); lines=[]; line=''
    for w in words:
        candidate=(line+' '+w).strip()
        if d.textlength(candidate,font=font(24))>660:
            lines.append(line);line=w
        else:line=candidate
    lines.append(line)
    for i,line in enumerate(lines):put(x,1826+i*32,line,24,color=MUTED)
put(90,1910,'Blender concept render • Hardware envelopes and mounting fit remain provisional • Not print-ready',21,color=MUTED)
im.save(PREVIEW/'echo-deck-concept-board.png')
print(PREVIEW/'echo-deck-concept-board.png')
