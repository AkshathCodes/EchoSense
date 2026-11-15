"""LiDAR transport: lidar_frame v1 validation, live hub, JSONL record and replay.

Separate from the sonar path on purpose. Points stay in ARKit world
coordinates; nothing here rotates, rescales or reorders them.
See LIDAR_PROTOCOL.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from http import HTTPStatus
from pathlib import Path
from typing import Any, TextIO

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from .protocol import number
from .server import DEFAULT_ORIGINS

LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MAX_POINTS = 5_000            # per frame; the phone targets about 1,000
MAX_FRAME_BYTES = 1_000_000
MAX_COORDINATE = 1_000.0      # meters from the ARKit origin
SOURCES = ("arkit_scene_depth", "synthetic")
TRACKING = ("normal", "limited", "not_available")
FIELDS = {"type", "schema_version", "session_id", "device_id", "sequence", "timestamp", "source",
          "coordinate_frame", "units", "tracking", "camera_to_world", "points", "confidences"}


def _label(value: Any, name: str) -> str:
    if type(value) is not str or not 0 < len(value) <= 64 or not value.isprintable():
        raise ValueError(f"{name} must be 1 to 64 printable characters")
    return value


def validate_lidar_frame(raw: str | bytes) -> dict[str, Any]:
    """Parse and check one lidar_frame v1 message. Raises ValueError if it is not valid."""
    if len(raw) > MAX_FRAME_BYTES:
        raise ValueError("frame exceeds byte limit")
    try:
        frame = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise ValueError("frame must be JSON") from exc
    if type(frame) is not dict or set(frame) != FIELDS:
        raise ValueError("frame must have exactly the lidar_frame v1 fields")
    if frame["type"] != "lidar_frame" or frame["schema_version"] != SCHEMA_VERSION:
        raise ValueError("expected lidar_frame schema_version 1")
    _label(frame["session_id"], "session_id")
    _label(frame["device_id"], "device_id")
    if type(frame["sequence"]) is not int or frame["sequence"] < 0:
        raise ValueError("sequence must be a nonnegative integer")
    number(frame["timestamp"], "timestamp")
    if frame["source"] not in SOURCES or frame["tracking"] not in TRACKING:
        raise ValueError("unknown source or tracking state")
    if frame["coordinate_frame"] != "arkit_world" or frame["units"] != "meters":
        raise ValueError("only arkit_world coordinates in meters are accepted")
    pose = frame["camera_to_world"]
    if type(pose) is not list or len(pose) != 16:
        raise ValueError("camera_to_world must be 16 numbers, column-major")
    for value in pose:
        if abs(number(value, "camera_to_world")) > MAX_COORDINATE:
            raise ValueError("camera_to_world out of range")
    if pose[3] != 0 or pose[7] != 0 or pose[11] != 0 or pose[15] != 1:
        raise ValueError("camera_to_world must be a rigid transform (bottom row 0 0 0 1)")
    points, confidences = frame["points"], frame["confidences"]
    if type(points) is not list or type(confidences) is not list or len(points) > MAX_POINTS:
        raise ValueError("points and confidences must be bounded arrays")
    if len(points) != len(confidences):
        raise ValueError("points and confidences must be the same length")
    for point in points:
        if type(point) is not list or len(point) != 3:
            raise ValueError("each point must be [x, y, z]")
        for value in point:
            if abs(number(value, "point")) > MAX_COORDINATE:
                raise ValueError("point out of range")
    for confidence in confidences:
        if type(confidence) is not int or not 0 <= confidence <= 2:
            raise ValueError("confidence must be 0, 1 or 2")
    return frame


def status_message(*, mode: str, publisher: bool, session_id: str | None, recording: bool) -> str:
    return json.dumps({"type": "lidar_status", "schema_version": SCHEMA_VERSION, "mode": mode,
                       "publisher_connected": publisher, "session_id": session_id,
                       "recording": recording}, separators=(",", ":"))


class _Viewer:
    """Bounded outbox. When full, the oldest frame is dropped, never the newest."""

    def __init__(self, backlog: int) -> None:
        self.outbox: deque[str] = deque(maxlen=backlog)
        self.ready = asyncio.Event()

    def push(self, message: str) -> None:
        self.outbox.append(message)
        self.ready.set()


class _Access:
    def __init__(self, origins: tuple[str, ...], allow_no_origin: bool) -> None:
        self.origins = set(origins)
        self.allow_no_origin = allow_no_origin

    def viewer_allowed(self, origin: str | None) -> bool:
        return origin is None and self.allow_no_origin or origin in self.origins


class LidarHub:
    """One phone on /lidar/publish, browsers on /lidar/view."""

    def __init__(self, *, origins: tuple[str, ...] = DEFAULT_ORIGINS, allow_no_origin: bool = False,
                 max_viewers: int = 4, backlog: int = 600, record: TextIO | None = None) -> None:
        self.access = _Access(origins, allow_no_origin)
        self.max_viewers = max_viewers
        self.backlog = backlog
        self.record = record
        self.viewers: set[_Viewer] = set()
        self.publisher: ServerConnection | None = None
        self.session_id: str | None = None
        self.last_sequence = -1
        self.history: deque[str] = deque(maxlen=backlog)   # current session only
        self.accepted = 0
        self.rejected = 0

    def check_request(self, connection: ServerConnection, request: Any) -> Any:
        origin = request.headers.get("Origin")
        if request.path == "/lidar/publish":
            # Native apps send no Origin. A web page may not pose as the sensor.
            return None if origin is None else connection.respond(HTTPStatus.FORBIDDEN, "Sensors only\n")
        if request.path != "/lidar/view":
            return connection.respond(HTTPStatus.NOT_FOUND, "Use /lidar/publish or /lidar/view\n")
        if self.access.viewer_allowed(origin):
            return None
        return connection.respond(HTTPStatus.FORBIDDEN, "Origin not allowed\n")

    async def handler(self, connection: ServerConnection) -> None:
        if connection.request.path == "/lidar/publish":
            await self.publish(connection)
        else:
            await self.view(connection)

    def status(self) -> str:
        return status_message(mode="live", publisher=self.publisher is not None,
                              session_id=self.session_id, recording=self.record is not None)

    def broadcast(self, message: str) -> None:
        for viewer in self.viewers:
            viewer.push(message)

    def accept(self, raw: str | bytes) -> None:
        """Validate one frame, then store, record and forward it."""
        frame = validate_lidar_frame(raw)
        if frame["session_id"] != self.session_id:
            # A new ARKit origin. Earlier geometry is in a different coordinate frame.
            self.session_id = frame["session_id"]
            self.history.clear()
            self.broadcast(self.status())
        elif frame["sequence"] <= self.last_sequence:
            raise ValueError("sequence must increase within a session")
        self.last_sequence = frame["sequence"]
        message = json.dumps(frame, allow_nan=False, separators=(",", ":"))
        self.history.append(message)
        self.accepted += 1
        if self.record is not None:
            self.record.write(message + "\n")
            self.record.flush()
        self.broadcast(message)

    async def publish(self, connection: ServerConnection) -> None:
        if self.publisher is not None:
            await connection.close(1013, "sensor already connected")
            return
        self.publisher = connection
        self.broadcast(self.status())
        print("Phone connected.", flush=True)
        try:
            async for raw in connection:
                try:
                    self.accept(raw)
                except ValueError as exc:
                    self.rejected += 1
                    if self.rejected in (1, 10, 100):
                        LOGGER.warning("Rejected phone frame (%d so far): %s", self.rejected, exc)
        except ConnectionClosed:
            pass
        finally:
            self.publisher = None
            self.broadcast(self.status())
            print(f"Phone disconnected. {self.accepted} frames accepted, {self.rejected} rejected.", flush=True)

    async def view(self, connection: ServerConnection) -> None:
        if len(self.viewers) >= self.max_viewers:
            await connection.close(1013, "client limit")
            return
        viewer = _Viewer(self.backlog)
        viewer.push(self.status())
        for message in self.history:        # a late viewer still gets the current session
            viewer.push(message)
        self.viewers.add(viewer)
        try:
            closed = asyncio.ensure_future(connection.wait_closed())
            while True:
                while viewer.outbox:
                    await asyncio.wait_for(connection.send(viewer.outbox.popleft()), 5)
                viewer.ready.clear()
                if viewer.outbox:
                    continue
                ready = asyncio.ensure_future(viewer.ready.wait())
                await asyncio.wait({ready, closed}, return_when=asyncio.FIRST_COMPLETED)
                if not ready.done():
                    ready.cancel()
                    return
        except TimeoutError:
            await connection.close(1013, "slow consumer")
        except ConnectionClosed:
            pass
        finally:
            self.viewers.discard(viewer)


def read_recording(path: Path) -> list[str]:
    """Load and re-validate a JSONL recording. Order and values are preserved."""
    messages = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                frame = validate_lidar_frame(line)
                messages.append(json.dumps(frame, allow_nan=False, separators=(",", ":")))
    if not messages:
        raise ValueError("recording has no frames")
    return messages


class LidarReplay:
    """Plays one recording to each viewer from the start at a fixed rate, then closes."""

    def __init__(self, messages: list[str], *, fps: float = 3.0,
                 origins: tuple[str, ...] = DEFAULT_ORIGINS, allow_no_origin: bool = False) -> None:
        if not 0 < fps <= 30:
            raise ValueError("fps must be in (0, 30]")
        self.messages = messages
        self.interval = 1 / fps
        self.access = _Access(origins, allow_no_origin)

    def check_request(self, connection: ServerConnection, request: Any) -> Any:
        if request.path != "/lidar/view":
            return connection.respond(HTTPStatus.NOT_FOUND, "Replay serves /lidar/view only\n")
        if self.access.viewer_allowed(request.headers.get("Origin")):
            return None
        return connection.respond(HTTPStatus.FORBIDDEN, "Origin not allowed\n")

    async def handler(self, connection: ServerConnection) -> None:
        try:
            await connection.send(status_message(mode="replay", publisher=False,
                                                 session_id=None, recording=False))
            for message in self.messages:
                await asyncio.wait_for(connection.send(message), 5)
                try:
                    await asyncio.wait_for(connection.wait_closed(), self.interval)
                    return
                except TimeoutError:
                    pass
            await connection.close(1000, "source complete")
        except (ConnectionClosed, TimeoutError):
            pass


def start_lidar(service: LidarHub | LidarReplay, *, host: str, port: int = 8765) -> serve:
    """No TLS and no authentication. Bind to a LAN address only on a network you control."""
    return serve(service.handler, host, port, process_request=service.check_request,
                 max_size=MAX_FRAME_BYTES, max_queue=4, close_timeout=2, compression=None)
