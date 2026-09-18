"""Explicit background research with sources, Stop, and bounded RAM-only results."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import RLock
import time
from uuid import uuid4
from .agent import Provider, ProviderUnavailable
from .conversation_activity import ConversationActivity


class ResearchTasks:
    def __init__(self, store, provider=None):
        self.store=store
        self.provider=provider or Provider(timeout=180)
        self.lock=RLock();self.jobs=OrderedDict();self.closed=False
        self.executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix='echo-research')

    def _prune(self):
        for identifier,job in list(self.jobs.items()):
            finished=job['activity'].finished
            if finished and time.time()-finished>1800:self.jobs.pop(identifier)

    def _view(self, job):
        return {**job['activity'].snapshot(),'title':job['title'],'result':deepcopy(job['result']),
                'expires_after_seconds':1800,'persistent':False}

    def list(self, owner):
        with self.lock:
            self._prune()
            return [self._view(j) for j in reversed(list(self.jobs.values())) if j['owner'] in {owner,'device'}]

    def start(self, owner, prompt):
        prompt=prompt.strip()
        if not 3<=len(prompt)<=2400:raise ValueError('Describe your research question in 3–2400 characters')
        settings,keys,_=self.store.snapshot()
        if settings.provider not in {'azure','openai'} or settings.web_lookup!='auto':
            raise ValueError('Research needs web lookup enabled with Azure or OpenAI in Settings')
        if not settings.model or not keys.get(settings.provider):raise ValueError('Configure your conversation model and key in Settings')
        with self.lock:
            self._prune()
            if self.closed:raise ValueError('Echo is stopping')
            if any(j['owner']==owner and j['activity'].finished is None for j in self.jobs.values()):
                raise ValueError('A research task is running. Stop it or wait for its result.')
            if sum(j['activity'].finished is None for j in self.jobs.values())>=2:
                raise ValueError('Echo is already researching two questions. Wait for one to finish.')
            if len(self.jobs)>=16:raise ValueError('Clear a finished task before starting another')
            activity=ConversationActivity();activity.progress('searching')
            job={'owner':owner,'title':prompt[:160],'activity':activity,'result':None}
            self.jobs[activity.id]=job
            # Separate from conversational locks; no home, memory-write or audio tools.
            self.executor.submit(self._run,job,settings.model_copy(update={'max_output_tokens':4096}),dict(keys),prompt)
            return self._view(job)

    def _run(self, job, settings, keys, prompt):
        activity=job['activity'];result=None
        try:
            answer=self.provider.complete(settings,keys,[{'role':'user','content':prompt}],
                lookup=True,detailed=True,cancel=activity.cancel)
            if not activity.cancel.is_set():
                result={'status':'complete','text':str(answer),'display_text':answer.display_text,'sources':answer.sources}
        except ProviderUnavailable as error:
            result={'status':'unavailable','text':str(error),'sources':[]}
        except Exception:
            result={'status':'unavailable','text':'Research could not finish. Check the model connection in Settings.','sources':[]}
        finally:
            with self.lock:
                job['result']=None if activity.cancel.is_set() else result
                activity.finish(result)
            keys.clear()

    def stop(self, owner, identifier):
        with self.lock:
            job=self.jobs.get(identifier)
            if not job or job['owner'] not in {owner,'device'}:raise KeyError(identifier)
            job['activity'].request_stop()
            return self._view(job)

    def delete(self, owner, identifier):
        with self.lock:
            job=self.jobs.get(identifier)
            if not job or job['owner'] not in {owner,'device'}:raise KeyError(identifier)
            if job['activity'].finished is None:
                job['activity'].request_stop()
                raise ValueError('Stopping research. Delete it after the worker has stopped.')
            job['activity'].request_stop();self.jobs.pop(identifier)

    def clear(self, owner):
        with self.lock:
            for identifier,job in list(self.jobs.items()):
                if job['owner']==owner:job['activity'].request_stop();self.jobs.pop(identifier)

    def close(self):
        with self.lock:
            self.closed=True
            for job in self.jobs.values():job['activity'].request_stop()
            self.jobs.clear()
        self.executor.shutdown(wait=False,cancel_futures=True)
