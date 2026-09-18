"""Private Hermes run adapter. Owns cancellation and public activity, not speech."""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
import time
from uuid import uuid4
import httpx


class RuntimeUnavailable(RuntimeError):
    pass


def configuration_fingerprint(settings, keys):
    values = [settings.azure_url, settings.model, keys.get('azure', '')]
    if settings.provider!='azure':
        values=[settings.provider,settings.local_url if settings.provider=='local' else '',settings.model,keys.get(settings.provider,'')]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


class HermesRuntime:
    def __init__(self, root, protector, *, transport=None, timeout=55):
        self.path = Path(root) / 'local/remote-agent.json' if root else None
        self.protector = protector
        self.transport = transport
        self.timeout = timeout
        self.lock = RLock()
        self._activity = {'state': 'idle', 'caption': 'Ready', 'events': []}

    def connection(self):
        try:
            data = json.loads(self.path.read_text())
            value = json.loads(self.protector.decrypt(base64.b64decode(data['protected'])))
            # The deployment uses an authenticated SSH forward, not a public endpoint.
            allowed = {'http://127.0.0.1:18643'}
            if os.environ.get('ECHO_CONTAINER')=='1': allowed.add('http://agent:8642')
            if value['url'] not in allowed or len(value['token']) < 32:
                raise ValueError()
            return value
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise RuntimeUnavailable('The Remote host agent is not provisioned on this host.') from None

    def activity(self):
        with self.lock:
            return {**self._activity, 'events': [dict(v) for v in self._activity['events']]}

    def _event(self, state, caption):
        with self.lock:
            item = {'state': state, 'caption': caption, 'time': time.time()}
            self._activity = {**self._activity, **item, 'events': [*self._activity['events'][-15:], item]}

    def complete(self, settings, keys, messages, *, instructions, cancel=None, progress=None):
        from .agent_apply import AgentApply, ACTIVE
        try:
            job = AgentApply(self.path.parent.parent if self.path else None, None).read()
        except (OSError, ValueError):
            raise RuntimeUnavailable('Echo model settings status is unavailable. Check Settings before trying again.') from None
        if job.get('state') in ACTIVE:
            raise RuntimeUnavailable('Echo model settings are being applied. Please try again when Settings shows Active.')
        value = self.connection()
        if value.get('configuration') != configuration_fingerprint(settings, keys):
            raise RuntimeUnavailable('Apply the saved model settings in Settings before asking Echo.')
        if cancel is not None and cancel.is_set():
            raise RuntimeUnavailable('The conversation was cancelled.')
        with self.lock:
            self._activity = {'state': 'starting', 'caption': 'Connecting to Echo', 'events': []}
        return asyncio.run(self._complete(value, messages, instructions, cancel, progress))

    async def _complete(self, value, messages, instructions, cancel, progress=None):
        def publish(state, caption):
            self._event(state, caption)
            if progress: progress(state)
        headers = {'Authorization': 'Bearer ' + value['token']}
        run_id = None
        observer = None
        finished = False
        deadline = time.monotonic() + self.timeout
        async with httpx.AsyncClient(base_url=value['url'], headers=headers,
                                     transport=self.transport, trust_env=False,
                                     follow_redirects=False, timeout=5) as client:
            async def checked(method, path, **kwargs):
                response = await client.request(method, path, **kwargs)
                if response.status_code in (401, 403):
                    raise RuntimeUnavailable('The Remote host agent rejected its connection credential.')
                if response.status_code >= 400:
                    raise RuntimeUnavailable('The Remote host agent could not complete that request.')
                if len(response.content) > 2_000_000:
                    raise RuntimeUnavailable('The agent response exceeded its size limit.')
                return response.json()

            async def interruptible(coroutine):
                task = asyncio.create_task(coroutine)
                try:
                    while not task.done():
                        if cancel is not None and cancel.is_set():
                            raise RuntimeUnavailable('The conversation was cancelled.')
                        if time.monotonic() >= deadline:
                            raise RuntimeUnavailable('The Remote host agent took too long. Try again.')
                        await asyncio.wait({task}, timeout=.05)
                    return task.result()
                finally:
                    if not task.done(): task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

            async def observe():
                try:
                    async with client.stream('GET', '/v1/runs/' + run_id + '/events', timeout=15) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if len(line) > 65536: return
                            if not line.startswith('data:'): continue
                            event = json.loads(line[5:].strip())
                            kind = event.get('event')
                            if kind == 'tool.started':
                                name = str(event.get('tool', ''))
                                acting = 'home_action' in name
                                caption = 'Controlling your home' if acting else 'Checking your home' if 'home_' in name else 'Using an assistant tool'
                                publish('acting' if acting else 'checking', caption)
                            elif kind == 'tool.completed':
                                publish('thinking', 'Considering the result')
                except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                    # Polling remains authoritative if a progress stream disconnects.
                    return

            try:
                # Admission is bounded but allowed to return a run ID after cancellation,
                # so the finally block can stop that admitted run.
                admitted = await checked('POST', '/v1/runs', headers={**headers,
                    'Idempotency-Key': uuid4().hex}, json={
                    'input': messages[-1]['content'], 'conversation_history': messages[:-1],
                    'instructions': instructions})
                candidate = admitted.get('run_id')
                if not isinstance(candidate, str) or not candidate.startswith('run_') or not candidate[4:].isalnum():
                    raise RuntimeUnavailable('The agent returned an invalid task reference.')
                run_id = candidate
                with self.lock: self._activity['task_id'] = run_id
                publish('thinking', 'Echo is thinking')
                observer = asyncio.create_task(observe())
                while True:
                    try:
                        result = await interruptible(checked('GET', '/v1/runs/' + run_id))
                    except httpx.TransportError:
                        # A missed status observation does not mean the admitted run
                        # stopped. Query that same ID again, within the original
                        # deadline; never repeat admission or any appliance action.
                        publish('thinking', 'Waiting for agent status')
                        await interruptible(asyncio.sleep(.25))
                        continue
                    state = result.get('status')
                    if state == 'completed':
                        if (result.get('completed') is False or result.get('partial') or result.get('interrupted')):
                            raise RuntimeUnavailable('The agent finished only part of the request.')
                        output = result.get('output')
                        if not isinstance(output, str) or not output.strip():
                            raise RuntimeUnavailable('The agent returned no answer.')
                        if cancel is not None and cancel.is_set():
                            raise RuntimeUnavailable('The conversation was cancelled.')
                        finished = True
                        publish('completed', 'Reply ready')
                        return output.strip()
                    if state in ('failed', 'cancelled'):
                        finished = True
                        raise RuntimeUnavailable('The agent cancelled the task.' if state == 'cancelled'
                                                 else 'The agent could not finish that request.')
                    if state not in ('started', 'running', 'queued'):
                        raise RuntimeUnavailable('The agent returned an unsupported task state.')
                    await interruptible(asyncio.sleep(.25))
            except RuntimeUnavailable as error:
                publish('cancelled' if cancel is not None and cancel.is_set() else 'failed', str(error))
                raise
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                publish('failed', 'Remote host connection unavailable')
                raise RuntimeUnavailable('The Remote host agent is unreachable or returned an invalid response.') from None
            finally:
                if observer is not None:
                    observer.cancel()
                    await asyncio.gather(observer, return_exceptions=True)
                if run_id and not finished:
                    try:
                        stop = await client.post('/v1/runs/' + run_id + '/stop', timeout=3)
                        stop.raise_for_status()
                    except httpx.HTTPError:
                        publish('unconfirmed', 'Connection lost; task stop could not be confirmed')
