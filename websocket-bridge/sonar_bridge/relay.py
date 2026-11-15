"""Live relay: one phone pushes LiDAR frames to /ingest, viewers read /ws.

Unlike Bridge (one replay per client), every viewer sees the same latest frame.
There is no queue: a viewer that falls behind skips to the newest frame.
"""
from __future__ import annotations

import asyncio
import logging
from http import HTTPStatus
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from .protocol import MAX_MESSAGE_BYTES, encode_lidar_ingest
from .server import DEFAULT_ORIGINS

LOGGER = logging.getLogger(__name__)


class LiveRelay:
    def __init__(self, *, origins: tuple[str, ...] = DEFAULT_ORIGINS, allow_no_origin: bool = False,
                 max_viewers: int = 4, send_timeout: float = 5.0) -> None:
        self.origins = set(origins)
        self.allow_no_origin = allow_no_origin
        self.max_viewers = max_viewers
        self.send_timeout = send_timeout
        self.latest: str | None = None
        self.sequence = 0          # frames accepted from the phone
        self.rejected = 0          # frames the phone sent that failed validation
        self.viewers = 0
        self.producer: ServerConnection | None = None
        self._fresh = asyncio.Condition()

    def check_request(self, connection: ServerConnection, request: Any) -> Any:
        origin = request.headers.get("Origin")
        if request.path == "/ingest":
            # Native apps send no Origin. A browser page may not act as the sensor.
            if origin is not None:
                return connection.respond(HTTPStatus.FORBIDDEN, "Sensors only\n")
            return None
        if request.path != "/ws":
            return connection.respond(HTTPStatus.NOT_FOUND, "Use /ws or /ingest\n")
        if origin is None and self.allow_no_origin or origin in self.origins:
            return None
        return connection.respond(HTTPStatus.FORBIDDEN, "Origin not allowed\n")

    async def handler(self, connection: ServerConnection) -> None:
        if connection.request.path == "/ingest":
            await self.ingest(connection)
        else:
            await self.view(connection)

    async def ingest(self, connection: ServerConnection) -> None:
        if self.producer is not None:
            await connection.close(1013, "sensor already connected")
            return
        self.producer = connection
        print("Phone connected.", flush=True)
        try:
            async for raw in connection:
                try:
                    message = encode_lidar_ingest(raw, self.sequence)
                except ValueError as exc:
                    self.rejected += 1
                    if self.rejected in (1, 10, 100):
                        LOGGER.warning("Rejected phone frame (%d so far): %s", self.rejected, exc)
                    continue
                async with self._fresh:
                    self.latest = message
                    self.sequence += 1
                    self._fresh.notify_all()
        except ConnectionClosed:
            pass
        finally:
            self.producer = None
            print(f"Phone disconnected after {self.sequence} frames.", flush=True)

    async def view(self, connection: ServerConnection) -> None:
        if self.viewers >= self.max_viewers:
            await connection.close(1013, "client limit")
            return
        self.viewers += 1
        seen = -1
        try:
            while True:
                async with self._fresh:
                    # The last frame stays available to a viewer that connects late.
                    while self.latest is None or self.sequence == seen:
                        wait = asyncio.ensure_future(self._fresh.wait())
                        closed = asyncio.ensure_future(connection.wait_closed())
                        done, _ = await asyncio.wait({wait, closed}, return_when=asyncio.FIRST_COMPLETED)
                        if wait not in done:
                            wait.cancel()
                            await asyncio.gather(wait, return_exceptions=True)
                            return
                        closed.cancel()
                    message, seen = self.latest, self.sequence
                try:
                    await asyncio.wait_for(connection.send(message), self.send_timeout)
                except TimeoutError:
                    await connection.close(1013, "slow consumer")
                    return
        except ConnectionClosed:
            pass
        finally:
            self.viewers -= 1


def start_relay(relay: LiveRelay, *, host: str = "0.0.0.0", port: int = 8765) -> serve:
    """LAN-reachable so the phone can connect. No TLS and no authentication."""
    return serve(relay.handler, host, port, process_request=relay.check_request,
                 max_size=MAX_MESSAGE_BYTES, max_queue=2, close_timeout=2, compression=None)
