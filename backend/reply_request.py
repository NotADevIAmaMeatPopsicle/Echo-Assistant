"""Cancellable loopback request. Cancelling a reply cannot undo an accepted home action."""
import asyncio
import time
import httpx
from .speech_jobs import check_cancel


def post_text(text, token, *, cancel=None, transport=None,calendar_review=False):
    async def request():
        check_cancel(cancel)
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8768',timeout=45,
                trust_env=False,follow_redirects=False,transport=transport,
                headers={'Authorization':'Bearer '+token}) as client:
            body={'text':text}
            if calendar_review:body['calendar_review']=True
            pending = asyncio.create_task(client.post('/v1/text',json=body))
            deadline = time.monotonic()+45
            try:
                while True:
                    check_cancel(cancel)
                    if time.monotonic()>=deadline: raise httpx.TimeoutException('Local reply timed out')
                    done,_ = await asyncio.wait({pending},timeout=.05)
                    if done:
                        check_cancel(cancel)
                        return pending.result()
            finally:
                if not pending.done(): pending.cancel()
                await asyncio.gather(pending,return_exceptions=True)
    return asyncio.run(request())
