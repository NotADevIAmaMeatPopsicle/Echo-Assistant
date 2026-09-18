"""Explicit, editable personal facts. No automatic transcript or audio retention."""
import base64
import json
import math
from pathlib import Path
import re
from threading import RLock
import time
import uuid
from .settings import default_protector


class MemoryUnavailable(RuntimeError):
    pass


def memory_request(text):
    text=text.strip()
    save=re.fullmatch(r'(?:please\s+)?remember\s+(?:that\s+)?(.+)',text,re.I|re.S)
    if save: return 'save',save[1]
    if re.fullmatch(r'(?:what do you remember(?: about me)?|(?:show|list) (?:my |your )?(?:saved )?memories)[?.!]*',text,re.I):
        return 'list',''
    forget=re.fullmatch(r'(?:please\s+)?forget\s+(?:that\s+)?(.+)',text,re.I|re.S)
    if forget: return 'forget',forget[1]
    return None


def canonical(text):
    return ' '.join(text.casefold().split()).rstrip('.!?')


class MemoryStore:
    def __init__(self, root:Path|None=None, protector=None):
        self.path=root/'local/echo-memory.json' if root else None
        self.protector=protector or default_protector()
        self.lock=RLock();self.records=[];self.revision=0;self.error=False
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size>300_000: raise ValueError()
                payload=json.loads(self.path.read_text(encoding='utf-8'))
                if payload['version']!=1: raise ValueError()
                records=json.loads(self.protector.decrypt(base64.b64decode(payload['protected'],validate=True)))
                if not isinstance(records,list) or len(records)>200: raise ValueError()
                seen=set()
                for item in records:
                    if not isinstance(item,dict) or set(item)!={'id','text','created_at','updated_at'}: raise ValueError()
                    if not isinstance(item['id'],str) or not re.fullmatch('[0-9a-f]{32}',item['id']) or item['id'] in seen: raise ValueError()
                    self.validate_text(item['text']);seen.add(item['id'])
                    if any(type(item[k]) not in (float,int) or not math.isfinite(item[k]) or item[k]<0 for k in ('created_at','updated_at')): raise ValueError()
                self.records=records
            except (OSError,ValueError,KeyError,TypeError,RuntimeError):
                self.error=True  # Preserve unreadable data; never replace it silently.

    @staticmethod
    def validate_text(text):
        if not isinstance(text,str) or not 1<=len(text.strip())<=600 or any(ord(c)<32 and c not in '\r\n\t' for c in text):
            raise ValueError('Use a memory between 1 and 600 characters.')
        return ' '.join(text.split())

    def _require(self):
        if self.error: raise MemoryUnavailable('Saved memory could not be read. The existing file has been preserved.')

    def snapshot(self):
        with self.lock:
            self._require()
            return [dict(item) for item in self.records]

    def _commit(self,records):
        self._require()
        if len(records)>200: raise ValueError('Memory is full. Remove a saved item before adding another.')
        if self.path:
            temporary=self.path.with_suffix('.tmp')
            try:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                plaintext=json.dumps(records,ensure_ascii=False).encode('utf-8')
                if len(plaintext)>180_000: raise ValueError('Memory is full. Remove a saved item before adding another.')
                protected=self.protector.encrypt(plaintext)
                temporary.write_text(json.dumps({'version':1,'protected':base64.b64encode(protected).decode('ascii')}),encoding='utf-8')
                temporary.replace(self.path)
            except (OSError,RuntimeError):
                raise MemoryUnavailable('Memory could not be saved. The previous memories are unchanged.') from None
        self.records=records;self.revision+=1

    def save(self,text,identifier=None):
        text=self.validate_text(text)
        with self.lock:
            self._require();records=self.snapshot();now=time.time()
            if identifier:
                item=next((r for r in records if r['id']==identifier),None)
                if item is None: raise KeyError(identifier)
                item.update(text=text,updated_at=now)
            else:
                existing=next((r for r in records if canonical(r['text'])==canonical(text)),None)
                if existing: return existing
                item={'id':uuid.uuid4().hex,'text':text,'created_at':now,'updated_at':now};records.append(item)
            self._commit(records)
            return dict(item)

    def delete(self,identifier):
        with self.lock:
            records=self.snapshot()
            if not any(r['id']==identifier for r in records): raise KeyError(identifier)
            self._commit([r for r in records if r['id']!=identifier])

    def clear(self):
        with self.lock:self._commit([])

    def relevant(self,text):
        words=set(re.findall(r'\w+',text.casefold()))-{'what','which','do','does','how','the','a','an','is','are','my','i','me','you','to','of','and'}
        records=self.snapshot()
        scored=[(len(words&set(re.findall(r'\w+',r['text'].casefold()))),r) for r in records]
        scored.sort(key=lambda pair:(pair[0],pair[1]['updated_at']),reverse=True)
        # With a small profile, provide the profile; otherwise retrieve matching
        # facts only. Never silently stuff hundreds of personal facts into a call.
        selected=[r for score,r in scored if score or len(records)<=8][:8]
        result=[];size=0
        for item in selected:
            if size+len(item['text'])>3000: break
            result.append(item);size+=len(item['text'])
        return result
