from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from .photos import PhotoUnavailable


def install(app, photos, authorize, owner):
    @app.exception_handler(PhotoUnavailable)
    async def unavailable(request, error): return JSONResponse({'detail': str(error)}, status_code=503)

    @app.get('/v1/display/photos', dependencies=[Depends(authorize)])
    def album(): return photos.snapshot()

    @app.post('/v1/display/photos', dependencies=[Depends(owner)])
    async def upload(request: Request):
        if request.headers.get('content-type', '').split(';')[0] not in {'image/jpeg', 'image/png', 'image/webp'}:
            raise HTTPException(415, 'Choose a JPEG, PNG, or WebP photo')
        raw=bytearray()
        async for block in request.stream():
            raw.extend(block)
            if len(raw)>12_000_000: raise HTTPException(413, 'Photos must be under 12 MB')
        try: return await run_in_threadpool(photos.add, bytes(raw))
        except ValueError as error: raise HTTPException(422, str(error)) from None

    @app.get('/v1/display/photos/{identifier}', dependencies=[Depends(authorize)])
    def photo(identifier: str):
        try: return Response(photos.read(identifier), media_type='image/jpeg')
        except KeyError: raise HTTPException(404, 'Photo not found') from None

    @app.delete('/v1/display/photos/{identifier}', dependencies=[Depends(owner)])
    def delete(identifier: str):
        try: photos.delete(identifier)
        except KeyError: raise HTTPException(404, 'Photo not found') from None
        return {'deleted': True}
