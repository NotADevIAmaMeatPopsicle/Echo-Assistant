"""Response headers without wrapping or consuming the request's disconnect stream."""
from starlette.datastructures import MutableHeaders


class BrowserHeadersMiddleware:
    def __init__(self, app, call_origins=lambda:[]): self.app,self.call_origins = app,call_origins

    async def __call__(self, scope, receive, send):
        async def add_headers(message):
            if message['type'] == 'http.response.start':
                headers = MutableHeaders(scope=message)
                headers['Cache-Control'] = 'no-store'
                headers['X-Content-Type-Options'] = 'nosniff'
                headers['Referrer-Policy'] = 'no-referrer'
                headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
                if scope.get('path') == '/display/video-player':
                    # Only this explicit player context contacts YouTube. Its
                    # lease is in a fragment, which is never part of a Referer.
                    headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
                    headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
                    headers['Content-Security-Policy'] = (
                        "default-src 'self'; script-src 'self' https://www.youtube.com https://s.ytimg.com; "
                        "style-src 'self'; connect-src 'self'; img-src 'self' data:; "
                        "frame-src https://www.youtube-nocookie.com; frame-ancestors 'none'; "
                        "base-uri 'none'; form-action 'none'; object-src 'none'"
                    )
                if scope.get('path') == '/display':
                    origins=self.call_origins()
                    if origins:
                        headers['Content-Security-Policy']=headers['Content-Security-Policy'].replace("connect-src 'self'", "connect-src 'self' "+' '.join(origins))
                    # Optional photos are browser-local object URLs, never uploaded.
                    headers['Content-Security-Policy'] = headers['Content-Security-Policy'].replace("img-src 'self' data:", "img-src 'self' data: blob:")
                    headers['Content-Security-Policy'] += '; media-src \'self\' blob: https:'
            await send(message)
        await self.app(scope, receive, add_headers)
