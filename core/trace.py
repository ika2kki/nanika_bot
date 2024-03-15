import logging

import aiohttp

__all__ = ("aiohttp_trace_thing",)

LOGGER = logging.getLogger(__name__)

class aiohttp_trace_thing(aiohttp.TraceConfig):
    def __init__(self):
        super().__init__()
        self.on_request_end.append(self.request_end_event)

    async def request_end_event(self, session, ctx, params):
        response = params.response
        if 400 <= response.status < 500:
            if response.status != 429:
                message = [f"api {response.status} exception {response.method} {response.url}"]
                for name, value in response.headers.items():
                    message.append(f"{name} {value}")
                LOGGER.warning("\n".join(message))
