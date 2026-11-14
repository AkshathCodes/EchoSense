"""Local-only paced WebSocket streaming; no producer queues."""
from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable, Iterator
from http import HTTPStatus
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

DEFAULT_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost:3000", "http://127.0.0.1:3000")
LOGGER = logging.getLogger(__name__)


class Bridge:
    """Independent, lazy source per client; cap clients and close slow consumers."""

    def __init__(self, source_factory: Callable[[], Iterator[str]], *, fps: float = 10.0,
                 max_clients: int = 4, send_timeout: float = 5.0) -> None:
        if not math.isfinite(fps) or not 0 < fps <= 30:
            raise ValueError("fps must be in (0, 30]")
        if type(max_clients) is not int or max_clients < 1:
            raise ValueError("max_clients must be a positive integer")
        if not math.isfinite(send_timeout) or send_timeout <= 0:
            raise ValueError("send_timeout must be positive and finite")
        self.source_factory = source_factory
        self.interval = 1 / fps
        self.max_clients = max_clients
        self.send_timeout = send_timeout
        self.active_clients = 0

    async def handler(self, connection: ServerConnection) -> None:
        if self.active_clients >= self.max_clients:
            await connection.close(1013, "client limit")
            return
        self.active_clients += 1
        messages = None
        try:
            messages = self.source_factory()
            while True:
                message = next(messages, None)
                if message is None:
                    await connection.close(1000, "source complete")
                    return
                # No queue: build one frame, await send, then pace. No catch-up bursts.
                # Close before cancelling a blocked send, as websockets recommends.
                send = asyncio.create_task(connection.send(message))
                try:
                    done, _ = await asyncio.wait({send}, timeout=self.send_timeout)
                    if not done:
                        await connection.close(1013, "slow consumer")
                    await send
                    if not done:
                        return
                finally:
                    if not send.done():
                        send.cancel()
                        await asyncio.gather(send, return_exceptions=True)
                try:
                    await asyncio.wait_for(connection.wait_closed(), timeout=self.interval)
                    return
                except TimeoutError:
                    pass
        except ConnectionClosed:
            pass
        except Exception:
            # Don't expose captured data or filesystem details to remote clients.
            LOGGER.warning("Source rejected: invalid or unavailable frame")
            await connection.close(1011, "source rejected")
        finally:
            try:
                if messages is not None:
                    close = getattr(messages, "close", None)
                    if close is not None:
                        close()
            finally:
                self.active_clients -= 1


def check_path(connection: ServerConnection, request: Any) -> Any:
    if request.path != "/ws":
        return connection.respond(HTTPStatus.NOT_FOUND, "Use /ws\n")
    return None


def start_server(bridge: Bridge, *, port: int = 8765,
                 origins: tuple[str, ...] = DEFAULT_ORIGINS,
                 allow_no_origin: bool = False) -> serve:
    """Bind IPv4 loopback only; exact Origin allowlist, never wildcard CORS."""
    allowed: list[str | None] = list(origins)
    if allow_no_origin:
        allowed.append(None)
    return serve(bridge.handler, "127.0.0.1", port, origins=allowed,
                 process_request=check_path, max_size=1024, max_queue=1,
                 write_limit=32768, close_timeout=2, compression=None)
