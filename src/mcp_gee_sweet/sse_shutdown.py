"""ASGI guard for the SSE stream a server shutdown cuts off (#868).

On SIGTERM, sse_starlette's ``EventSourceResponse`` sees ``AppStatus.should_exit``
and cancels its own task group, so its closing ``http.response.body``
(``more_body=False``) is never sent: the response is left started but incomplete.
mcp's ``sse_app`` endpoint then returns an empty ``Response()``, which Starlette
sends on the same connection, and uvicorn rejects that second
``http.response.start`` with "Exception in ASGI application". A client disconnect
doesn't hit this, because uvicorn turns every send after a disconnect into a no-op.

``SingleResponseGuard`` drops that late second response. If the first one is
still open, it sends the missing closing body first, so the client gets a
properly terminated stream instead of a truncated one. Any other message passes
through untouched, so uvicorn still reports every other ASGI misuse.
"""

import logging

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class SingleResponseGuard:
    """Drop a second ``http.response.start`` on a request that already started one."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False
        complete = False
        discarding = False

        async def guarded_send(message: Message) -> None:
            nonlocal started, complete, discarding
            if discarding:
                return
            if message["type"] == "http.response.start":
                if started:
                    discarding = True
                    logger.debug("Dropping a second response on %s (#868)", scope.get("path"))
                    if not complete:
                        complete = True
                        await send({"type": "http.response.body", "body": b"", "more_body": False})
                    return
                started = True
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                complete = True
            await send(message)

        await self.app(scope, receive, guarded_send)
