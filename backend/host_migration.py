"""Validate and re-encrypt a one-time host transfer before replacing any live files."""
import base64
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from .settings import EchoSettings,SettingsStore,SettingsUpdate,default_protector
from .memory import MemoryStore
from .core import Assistant
from .home_access import HomeAccessStore
from .agent_runtime import HermesRuntime,configuration_fingerprint
from .spotify_credentials import SpotifyCredentials


def protected(protector,value):
    return {'version':1,'protected':base64.b64encode(protector.encrypt(json.dumps(value).encode())).decode()}


def apply_migration(root,bundle,protector=None):
    protector=protector or default_protector()
    local=root/'local';local.mkdir(exist_ok=True)
    identifier=bundle.get('id','')
    if not isinstance(identifier,str) or not re.fullmatch('[0-9a-f]{32}',identifier):
        raise ValueError('Invalid migration identity')
    marker=local/'host-migration.json'
    if marker.exists():
        completed=json.loads(marker.read_text())
        if completed.get('id')!=identifier:raise ValueError('A different host migration is already installed')
        return completed
    settings=EchoSettings.model_validate(bundle['settings'])
    keys=bundle['keys']
    if not isinstance(keys,dict) or any(k not in {'azure','openai','anthropic','local'} or
            not isinstance(v,str) or not 1<=len(v)<=1024 for k,v in keys.items()):
        raise ValueError('Invalid provider credentials')
    # In the container this staging directory is tmpfs. Facts and credentials are
    # written encrypted even here, except the receiver's bounded live cache.
    with TemporaryDirectory(prefix='echo-migration-') as directory:
        stage=Path(directory);staged=stage/'local';staged.mkdir()
        store=SettingsStore(stage,protector);store.keys=dict(keys)
        store.save(SettingsUpdate(settings=settings))
        (staged/'echo-memory.json').write_text(json.dumps(protected(protector,bundle['memory'])))
        source_memory=MemoryStore(stage,protector).snapshot()
        existing=MemoryStore(root,protector).snapshot()
        merged={record['id']:record for record in existing}
        for record in source_memory:
            old=merged.get(record['id'])
            if old is None or record['updated_at']>=old['updated_at']:merged[record['id']]=record
        MemoryStore(stage,protector)._commit(list(merged.values()))
        access=HomeAccessStore(stage,protector,synchronizer=lambda policy:None)
        access.update(bundle['home_access'],access.snapshot()['revision'])
        timers=bundle['timers']
        timer_path=staged/'timers.json';timer_path.write_text(json.dumps(timers))
        source_timers=Assistant(storage=timer_path);source_timers.timer_states()
        existing_path=local/'timers.json'
        if existing_path.exists():
            Assistant(storage=existing_path).timer_states()
            merged_timers={record['id']:record for record in json.loads(existing_path.read_text())}
            merged_timers.update({record['id']:record for record in timers})
            timers=list(merged_timers.values());timer_path.write_text(json.dumps(timers))
            Assistant(storage=timer_path).timer_states()
        agent=bundle['agent']
        if agent.get('configuration')!=configuration_fingerprint(settings,keys):
            raise ValueError('Agent configuration does not match the transferred provider')
        (staged/'remote-agent.json').write_text(json.dumps(protected(protector,agent)))
        HermesRuntime(stage,protector).connection()
        if bundle.get('spotify'):
            cache=stage/'spotify';cache.mkdir()
            receiver=SpotifyCredentials(stage,cache,protector)
            receiver.runtime.write_text(json.dumps(bundle['spotify']));receiver.persist()
        files=[path.name for path in staged.iterdir()]
        backup=local/('before-migration-'+identifier);backup.mkdir(exist_ok=True)
        for name in files:
            destination=local/name
            if destination.exists() and not (backup/name).exists():shutil.copyfile(destination,backup/name)
        for name in files:
            temporary=local/(name+'.migration-tmp')
            shutil.copyfile(staged/name,temporary);temporary.replace(local/name)
        result={'id':identifier,'memory_count':len(merged),'timer_count':len(timers),
                'provider_key_count':len(keys),'spotify_credentials':bool(bundle.get('spotify'))}
        temporary=marker.with_suffix('.tmp');temporary.write_text(json.dumps(result));temporary.replace(marker)
        return result
