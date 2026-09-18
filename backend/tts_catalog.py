"""Speech-engine availability without importing neural runtimes into the host API."""
import json
from pathlib import Path
from .runtime_paths import worker_python

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VOICES = {'sapi': '', 'kokoro': 'bm_george', 'pocket': 'george'}
POCKET_VOICES = ['george', 'charles', 'michael', 'javert', 'marius', 'alba']


def catalog(root=ROOT, sapi_voices=None):
    from .speech import voices, available
    windows = voices() if sapi_voices is None else sapi_voices
    result = [{'id':'sapi','name':'Windows SAPI','available':available(),'pace':True,
               'default_voice':'','voices':[{'id':'','name':'Windows default'}]+[{'id':v,'name':v} for v in windows]}]
    ready = {}
    if root:
        try: ready = json.loads((root/'local/tts-runtime-ready.json').read_text(encoding='utf-8'))
        except (OSError, ValueError): pass
    if not isinstance(ready,dict) or not isinstance(ready.get('engines',{}),dict): ready = {}
    for engine, directory, filename, label in [
        ('kokoro','kokoro-82m-official','kokoro-v1_0.pth','Kokoro · natural voices'),
        ('pocket','pocket-tts-english-official','languages/english/model.safetensors','Pocket · conversational')]:
        installed = bool(root and worker_python(root,'tts').is_file() and
                         (root/'local/models'/directory/filename).is_file() and ready.get('engines',{}).get(engine) is True)
        if engine == 'kokoro':
            identifiers = sorted(p.stem for p in (root/'local/models'/directory/'voices').glob('*.pt')) if root else []
            names = [{'id':v,'name':v[3:].replace('_',' ').title()+' · '+('British' if v[0]=='b' else 'American')+' '+('male' if v[1]=='m' else 'female')}
                     for v in identifiers if v[:3] in {'am_','af_','bm_','bf_'}]
            names.sort(key=lambda v:(v['id']!='bm_george',v['name']))
        else: names = [{'id':v,'name':v.title()} for v in POCKET_VOICES]
        result.append({'id':engine,'name':label,'available':installed,'pace':engine!='pocket',
                       'default_voice':DEFAULT_VOICES[engine],'voices':names})
    return result


def validate_selection(settings, root=ROOT, sapi_voices=None):
    item = next(item for item in catalog(root,sapi_voices) if item['id']==settings.tts_engine)
    if not item['available']: raise ValueError('That speech engine is not ready on this host')
    voice = settings.tts_voice or item['default_voice']
    if voice not in {v['id'] for v in item['voices']}: raise ValueError('Choose an installed voice for the selected engine')
    if not item['pace'] and settings.tts_rate != 0: raise ValueError('Pocket uses its natural pace; set speaking pace to normal')


def selected_status(settings, root=ROOT):
    item = next(item for item in catalog(root,[]) if item['id']==settings.tts_engine)
    return 'local_'+('windows_sapi' if settings.tts_engine=='sapi' else settings.tts_engine) if item['available'] else 'unavailable'
