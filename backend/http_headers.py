"""Response headers without wrapping or consuming the request's disconnect stream."""
from starlette.datastructures import MutableHeaders


class BrowserHeadersMiddleware:
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        async def add_headers(message):
            if message['type'] == 'http.response.start':
                headers = MutableHeaders(scope=message)
                headers['Cache-Control'] = 'no-store'
                headers['X-Content-Type-Options'] = 'nosniff'
                headers['Referrer-Policy'] = 'no-referrer'
                headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            await send(message)
        await self.app(scope, receive, add_headers)
