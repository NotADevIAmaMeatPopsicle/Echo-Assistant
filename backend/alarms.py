"""Persistent timer state on the display and acknowledged audible delivery."""
import time
import re
from .speech import synthesize
from .speech_jobs import SpeechJobs


class Alarms:
    def __init__(self, client, worker, write, speech_jobs=None):
        self.client, self.worker, self.write = client, worker, write
        self.speech_jobs = speech_jobs or SpeechJobs(worker)
        self.poll = self.action = self.speech = None
        self.timers = []
        self.index = 0
        self.next_poll = 0.
        self.delivering = None
        self.next_alarm = 0.
        self.action_id = None
        self.available = False
        self.action_kind = None
        self.select_id = None

    def _request(self, method, path, body=None):
        response = self.client.request(method, path, **({'json': body} if body is not None else {})); response.raise_for_status()
        return response.json()

    def receive(self, line):
        match = re.fullmatch(r'EVENT timer_start=(\d{1,4})', line)
        if match:
            seconds = int(match[1])
            if not self.available:
                self.write(b'TIMER_RESULT Timer service unavailable\n')
            elif self.action:
                pass  # Ignore repeated taps while the first request is pending.
            elif len(self.timers) >= 16:
                self.write(b'TIMER_RESULT Dismiss a timer first\n')
            elif 60 <= seconds <= 7200 and seconds % 60 == 0:
                self.action_kind = 'create'; self.action_id = None
                self.action = self.worker.submit(self._request, 'POST', '/v1/timers',
                    {'seconds': seconds, 'label': f'{seconds//60} minute timer'})
            else:
                self.write(b'TIMER_RESULT Choose 1 to 120 minutes\n')
        elif line == 'EVENT timer_action=next':
            self.index = (self.index+1) % max(1, len(self.timers)); self.render()
        elif line == 'EVENT timer_action=dismiss' and self.timers and not self.action:
            timer_id = self.timers[self.index % len(self.timers)]['id']
            self.action_id = timer_id
            self.action_kind = 'dismiss'
            self.action = self.worker.submit(self._request, 'DELETE', '/v1/timers/'+timer_id)
            if timer_id == self.delivering:
                self.retry()
                return True
        return False

    def render(self):
        if not self.available:
            self.write(b'TIMER_UNAVAILABLE\n'); return
        if not self.timers:
            self.write(b'TIMER_STATE 0 0 0\n'); return
        self.index %= len(self.timers)
        timer = self.timers[self.index]
        self.write(f"TIMER_STATE {len(self.timers)} {round(timer['remaining_seconds'])} {int(timer['finished'])}\n".encode())
        label = re.sub(r'[^ -~]', ' ', str(timer.get('label', 'Timer')))[:28]
        self.write(f'TIMER_LABEL {label}\n'.encode('ascii'))

    def pump(self):
        now = time.monotonic()
        if self.action and self.action.done():
            try:
                result = self.action.result()
                # Discard any state request begun before this mutation completed.
                if self.poll: self.poll.cancel(); self.poll = None
                if self.action_kind == 'create':
                    self.select_id = result['id']
                    self.write(b'TIMER_RESULT Timer started\n')
                else:
                    self.timers = [timer for timer in self.timers if timer['id'] != self.action_id]
                    if self.action_kind == 'dismiss': self.write(b'TIMER_RESULT Timer dismissed\n')
            except Exception:
                self.next_alarm = now+5
                self.write(b'TIMER_RESULT Timer request failed\n')
            if self.delivering == self.action_id: self.delivering = None
            self.action = None; self.action_id = None; self.action_kind = None; self.next_poll = 0
        if self.poll and self.poll.done():
            try:
                self.timers = self.poll.result()['timers']; self.available = True
                if self.select_id:
                    self.index = next((i for i, timer in enumerate(self.timers) if timer['id'] == self.select_id), 0)
                    self.select_id = None
            except Exception:
                self.timers = []; self.available = False
            self.poll = None; self.render()
        if not self.poll and now >= self.next_poll:
            self.poll = self.worker.submit(self._request, 'GET', '/v1/state'); self.next_poll = now+1
        if not self.delivering and not self.speech and not self.action and now >= self.next_alarm:
            timer = next((timer for timer in self.timers if timer['finished'] and not timer['notified']), None)
            if timer:
                self.delivering = timer['id']
                self.index = self.timers.index(timer); self.render()
                self.speech = self.speech_jobs.submit(synthesize, 'Your timer is ready.')

    def take(self):
        if self.speech and self.speech.done():
            try: pcm = self.speech.result()
            except Exception:
                self.retry(); return None
            self.speech = None
            return pcm
        return None

    def finished(self):
        if self.delivering and not self.action:
            self.action_id = self.delivering
            self.action_kind = 'ack'
            self.action = self.worker.submit(self._request, 'POST', '/v1/timers/'+self.delivering+'/ack')

    def retry(self):
        if self.speech: self.speech.cancel()
        self.delivering = None; self.speech = None; self.next_alarm = time.monotonic()+5
