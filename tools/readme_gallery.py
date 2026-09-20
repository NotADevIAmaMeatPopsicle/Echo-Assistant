"""Build README contact sheets from synthetic previews of the actual firmware.

Run preview_firmware.py first. Requires Pillow; no board, network, or audio access.
"""
from pathlib import Path
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'preview/firmware'
DEST = ROOT/'docs/images'


def sheet(filename, items, columns=3):
    width, height = 510, 530
    canvas = Image.new('RGB', (width*columns, height*((len(items)+columns-1)//columns)), '#0a1322')
    draw = ImageDraw.Draw(canvas)
    font_path = Path(os.environ.get('WINDIR', ''))/'Fonts/segoeui.ttf'
    font = ImageFont.truetype(str(font_path), 22) if font_path.is_file() else ImageFont.load_default(size=22)
    for index, (state, label) in enumerate(items):
        x, y = index%columns*width+22, index//columns*height+12
        with Image.open(SOURCE/(state+'.png')) as picture:
            canvas.paste(picture, (x, y), picture)
        draw.text((x+233, y+477), label, font=font, fill='#c4d7ed', anchor='mt')
    canvas.save(DEST/filename, optimize=True)


if __name__ == '__main__':
    DEST.mkdir(parents=True, exist_ok=True)
    sheet('round-calendar.png', [('calendar-draft', 'Review the draft'), ('calendar-confirm', 'Confirm creation')], columns=2)
    sheet('voice-states.png', [(x, x.title()) for x in
          ('ready', 'listening', 'thinking', 'speaking', 'muted', 'offline')])
    sheet('home-controls.png', [('home', 'Home'), ('lights', 'Room lights'),
          ('thermostat', 'Thermostat'), ('bose', 'Speaker controls'),
          ('speakers', 'Choose a speaker'), ('music-controls', 'Music')])
    sheet('everyday-tools.png', [('weather', 'Weather'), ('timers', 'Timers'),
          ('new-timer', 'New timer'), ('settings', 'Settings'),
          ('connection', 'Connection'), ('power-3', 'Battery / charging')])
    print('README galleries generated from synthetic firmware fixtures.')
