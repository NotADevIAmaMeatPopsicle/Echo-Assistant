"""Serve the real web UI with read-only sample data for documentation screenshots.

Standard-library only: python tools/preview_web.py
No private configuration, credentials, audio, models, or integrations are loaded.
Only loopback is bound; all API writes are rejected. Stop with Ctrl+C.
"""
import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT/'web'
STAMP = 1767225600
SETTINGS = {
    'provider': 'openai', 'agent_runtime': 'hermes', 'model': 'example-model',
    'local_url': 'http://127.0.0.1:11434/v1', 'azure_url': '',
    'personality': 'You are Echo: thoughtful, curious, and quietly witty. Keep spoken replies concise. '
                   'Explain complex ideas clearly, ask when a request is ambiguous, and be honest about uncertainty. '
                   'A little dry humour is welcome; being useful comes first.',
    'max_output_tokens': 1024, 'stt_engine': 'whisper', 'tts_engine': 'pocket',
    'tts_voice': 'alba', 'tts_rate': 0, 'web_lookup': 'auto', 'memory_enabled': True,
}


def device(name, entity, room, state, domain='light', access='control', **attributes):
    return dict(name=name, entity_id=entity, room=room, ha_area=room, state=state,
                domain=domain, access=access, available=True, control_supported=True,
                attributes=attributes)


DEVICES = [
    device('Reading lamp', 'light.example_reading', 'Living Room', 'on',
           supported_color_modes=['color_temp'], min_color_temp_kelvin=2200, max_color_temp_kelvin=6500),
    device('Pendant lights', 'light.example_pendant', 'Dining Room', 'off', supported_color_modes=['brightness']),
    device('Bedside lamp', 'light.example_bedside', 'Bedroom', 'off', access='read'),
    device('Patio lantern', 'light.example_patio', 'Patio', 'off'),
    device('Room thermostat', 'climate.example_room', 'Living Room', 'heat', domain='climate',
           temperature=21, temperature_unit='°C', min_temp=16, max_temp=28, hvac_modes=['off', 'heat', 'cool']),
    device('Music speaker', 'media_player.example_music', 'Living Room', 'paused', domain='media_player',
           supported_features=16384|4|8|1),
]
POLICY = {'version': 1, 'default_access': 'read', 'devices': {
    d['entity_id']: {'access': d['access'], 'room': d['room']} for d in DEVICES}}
INVENTORY = dict(devices=DEVICES, policy=POLICY, applied=True, revision='sample-revision',
                 registry_available=True, areas=['Bedroom', 'Living Room', 'Dining Room', 'Patio'],
                 ha_areas=['Bedroom', 'Living Room', 'Dining Room', 'Patio'],
                 counts=dict(available=6, unavailable=0, without_area=0, total=6))

DATA = {
    '/health': dict(deployment_mode='device', device_transport='wifi_connected',
                    speaker_muted=False, wake_word='armed'),
    '/v1/settings': dict(settings=SETTINGS, credentials={p: False for p in ['local', 'openai', 'anthropic', 'azure']}),
    '/v1/echo': dict(runtime='hermes', memory='explicit_facts', lookup='available',
                     status='configured', provider='openai', model='example-model', cloud=True),
    '/v1/chat/activity': dict(state='idle', active=False, events=[], home_actions=[]),
    '/v1/chat': {'messages': [
        {'role': 'user', 'content': 'Why does the Moon change shape?'},
        {'role': 'assistant', 'content': 'The Moon stays round. What changes is how much of its sunlit half '
         'we can see as it travels around Earth. That gives us the familiar crescent, quarter, and full Moon. '
         '\n\nThink of a ball lit by a lamp: walk around it, and the bright part appears to change shape. '
         'Same ball. Different angle.'},
    ]},
    '/v1/settings/agent': dict(status='active'),
    '/v1/settings/speaker-check': dict(status='idle'),
    '/v1/settings/speech': dict(active_stt='whisper', stt=[
        dict(id='vosk', name='Vosk · low latency', available=True),
        dict(id='whisper', name='Whisper base.en · CPU', available=True)], engines=[
        dict(id='pocket', name='Pocket TTS', available=True, pace=False, default_voice='alba',
             voices=[dict(id='alba', name='Alba'), dict(id='george', name='George')]),
        dict(id='kokoro', name='Kokoro', available=True, pace=True, default_voice='af_heart',
             voices=[dict(id='af_heart', name='Heart')]),
        dict(id='sapi', name='Windows voices', available=True, pace=True, default_voice='default',
             voices=[dict(id='default', name='System default')])]),
    '/v1/memory': dict(enabled=True, items=[
        dict(id='sample-1', text='Keep everyday answers short; explain the details when I ask.', updated_at=STAMP),
        dict(id='sample-2', text='Use Celsius for temperatures.', updated_at=STAMP),
        dict(id='sample-3', text='I enjoy astronomy and learning how things work.', updated_at=STAMP)]),
    '/v1/home/devices': INVENTORY,
    '/v1/home': {'lights': dict(status='available', revision='sample-revision', rooms=[
        dict(id=str(i), name=room, state='on' if room=='Living Room' else 'off', count=1,
             on=room=='Living Room', available=True)
        for i, room in enumerate(['Bedroom', 'Living Room', 'Dining Room', 'Patio'])])},
    '/v1/routines': {'items': [
        dict(id='sample-evening', name='Evening reading', revision=1, steps=[
            dict(entity_id='light.example_reading', action='brightness', value=35),
            dict(entity_id='light.example_reading', action='color_temperature', value=2700),
            dict(entity_id='media_player.example_music', action='volume', value=12)]),
        dict(id='sample-lights', name='Lights out downstairs', revision=1, steps=[
            dict(entity_id='light.example_reading', action='turn_off'),
            dict(entity_id='light.example_pendant', action='turn_off')])]},
    '/v1/tasks': {'items': [dict(id='sample-research', title='What to know before building Echo',
        state='completed', active=False, result=dict(text=
            'Start with the Waveshare ESP32-S3-Touch-AMOLED-1.75 and a Windows host. '
            'The board handles touch, display, microphone input, and speaker output; the host runs speech and the assistant.\n\n'
            'Bring up the device over USB first, then pair Wi-Fi. Add Home Assistant and Spotify when the core voice path is working. '
            'Print the small Crescent fit kit before the full enclosure.',
            sources=[dict(title='Echo Assistant · build guide', url='https://github.com/NotADevIAmaMeatPopsicle/Echo-Assistant')]))]},
}


class Preview(BaseHTTPRequestHandler):
    def reply(self, status, body, content_type='application/json; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in DATA:
            return self.reply(200, json.dumps(DATA[path]).encode())
        if path in {'/', '/settings', '/memory', '/devices', '/routines', '/tasks'}:
            html = (WEB/'index.html').read_text(encoding='utf-8')
            banner = '<div style="text-align:center;padding:7px;background:#152a2c;color:#a0f5d5;font:10px Segoe UI,sans-serif;letter-spacing:2px">PRODUCT PREVIEW · SAMPLE DATA</div>'
            return self.reply(200, html.replace('<body>', '<body>'+banner).encode(), 'text/html; charset=utf-8')
        if path in {'/assets/app.js', '/assets/style.css', '/assets/icon.svg'}:
            file = WEB/path.rsplit('/', 1)[-1]
            return self.reply(200, file.read_bytes(), mimetypes.guess_type(file)[0] or 'application/octet-stream')
        self.reply(404, b'{"detail":"No preview fixture for this route"}')

    def do_POST(self):
        self.reply(405, b'{"detail":"Read-only preview. No changes or device actions are performed."}')

    do_PUT = do_DELETE = do_PATCH = do_POST

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8778)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Preview)
    print(f'Sample-data preview: http://127.0.0.1:{args.port}/ (Ctrl+C to stop)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
