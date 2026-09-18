"""Platform-specific worker locations; deployment overrides contain paths, not secrets."""
import os
from pathlib import Path


def worker_python(root, kind):
    if kind not in {'tts','aec'}: raise ValueError('Unknown worker runtime')
    configured = os.environ.get('ECHO_'+kind.upper()+'_PYTHON')
    if configured:
        path = Path(configured)
        if not path.is_absolute(): raise ValueError('Worker interpreter must be an absolute path')
        return path
    return root/'local'/f'{kind}-python'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')


def tts_environment():
    home = os.environ.get('ECHO_TTS_HOME')
    if not home: return {}
    path = Path(home)
    if not path.is_absolute(): raise ValueError('Speech runtime home must be absolute')
    return {'PYTHONHOME':str(path),'LD_LIBRARY_PATH':str(path/'lib')}
