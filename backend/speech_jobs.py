"""Cooperative cancellation for a reply, including model loading and synthesis."""
from threading import Event, Lock


class SpeechCancelled(RuntimeError):
    pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set(): raise SpeechCancelled('Speech request cancelled')


class SpeechJob:
    def __init__(self): self.cancel_event = Event()
    def cancel(self):
        self.cancel_event.set()
        return self.future.cancel()
    def done(self): return self.future.done()
    def result(self):
        check_cancel(self.cancel_event)
        result = self.future.result()
        check_cancel(self.cancel_event)
        return result


class SpeechJobs:
    def __init__(self, worker):
        self.worker = worker
        self.lock = Lock()
        self.jobs = set()
        self.closed = False

    def submit(self, function, *args, **kwargs):
        job = SpeechJob()
        def run():
            check_cancel(job.cancel_event)
            return function(*args, **kwargs, cancel=job.cancel_event)
        with self.lock:
            if self.closed: raise SpeechCancelled('Speech session closed')
            job.future = self.worker.submit(run)
            self.jobs.add(job)
        def finished(_):
            with self.lock: self.jobs.discard(job)
        job.future.add_done_callback(finished)
        return job

    def close(self):
        with self.lock:
            self.closed = True
            jobs = list(self.jobs)
        for job in jobs: job.cancel()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
