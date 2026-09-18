"""Release provider work when its caller leaves or the local API stops."""
import asyncio
from threading import Event
from fastapi import HTTPException


async def run_conversation(request, shutdown, function, *args, activity=None):
    if shutdown.is_set():
        if activity:
            activity.cancel.set()
            activity.finish(None)
        raise HTTPException(503, 'Echo is stopping')
    cancel = activity.cancel if activity else Event()
    pending = asyncio.create_task(asyncio.to_thread(function, *args, cancel=cancel))
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=.05)
            if shutdown.is_set():
                raise HTTPException(503, 'Echo is stopping')
            if await request.is_disconnected():
                raise HTTPException(499, 'Conversation caller disconnected')
            if done:
                result = pending.result()
                if activity:
                    activity.finish(result)
                    if cancel.is_set():
                        confirmed = not activity.stop_unconfirmed
                        return {'status':'cancelled' if confirmed else 'unconfirmed','capability':'conversation',
                                'text':'Request stopped. Actions already sent cannot be undone.' if confirmed else
                                       'Stop requested, but the agent could not confirm stopping. Check any home action receipts before retrying.',
                                'home_actions':result.get('home_actions',[]) if isinstance(result,dict) else []}
                return result
    finally:
        if not pending.done(): cancel.set()
        # Cancelling a to_thread task alone does not stop its worker. The provider
        # observes this event, closes its HTTP connection and releases Echo's lock.
        await asyncio.shield(asyncio.gather(pending, return_exceptions=True))
        if activity:
            result = None if pending.cancelled() or pending.exception() is not None else pending.result()
            activity.finish(result)
