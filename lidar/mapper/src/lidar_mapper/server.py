"""Live server: iPhone depth stream in, 3D map out to the EchoSense viewer.

  phone  --(binary depth frames, PROTOCOL.md)-->  ws://0.0.0.0:<port>/depth
  viewer <--(sonar_frame JSON envelope 0.1)--     ws://127.0.0.1:<viewer_port>/ws

The viewer side reuses the envelope the EchoSense viewer already decodes
(websocket-bridge/PROTOCOL.md) with `meta.kind = "lidar_map"`, so no viewer
change is needed. Points are world-frame (z up), which the viewer reads as
x forward, y left, z up.
"""

from __future__ import annotations

import asyncio
import json
import struct
import threading
import time
from pathlib import Path

import numpy as np
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from . import protocol
from .geometry import backproject
from .mapper import Mapper, _pack, floor_check

VIEWER_ORIGINS = ["http://127.0.0.1:4173", "http://localhost:4173", "http://127.0.0.1:5173",
                  "http://localhost:5173", "http://127.0.0.1:3000", "http://localhost:3000"]
MAX_VIEWER_POINTS = 20000  # EchoSense viewer limit
MAX_DENSE_POINTS = 800000  # viewer.html (WebGL handles this easily)
VIEWER_HTML = Path(__file__).with_name("viewer.html")
FRAME_POINTS = 2500  # current frame, drawn on top of the map


def write_record(fh, message: bytes) -> None:
    fh.write(struct.pack("<I", len(message)))
    fh.write(message)


def read_records(path: str | Path):
    with open(path, "rb") as fh:
        while True:
            head = fh.read(4)
            if len(head) < 4:
                return
            (n,) = struct.unpack("<I", head)
            yield fh.read(n)


class LiveMapper:
    """Keeps only the newest phone frame (no queue), maps it, and serves snapshots to viewers."""

    def __init__(self, mapper: Mapper, view: str = "both", record: str | None = None, verbose: bool = True):
        self.mapper = mapper
        self.view = view
        self.lock = threading.Lock()
        self.latest: bytes | None = None
        self.event = asyncio.Event()
        self.frame_points = np.zeros((0, 3))
        self.last = None
        self.rx = self.mapped = self.dropped = self.bad = 0
        self.seq = 0
        self.verbose = verbose
        self.record_fh = open(record, "ab") if record else None
        self.started = time.time()
        self._disp, self._disp_size, self._disp_map = None, 0, None
        self._disp_voxel = 0.05

    # ---------------------------------------------------------------- phone side
    async def phone_handler(self, conn) -> None:
        peer = conn.remote_address
        print(f"[phone] connected {peer}")
        try:
            async for msg in conn:
                if not isinstance(msg, bytes):
                    continue
                self.rx += 1
                if self.record_fh:
                    write_record(self.record_fh, msg)
                if self.latest is not None:
                    self.dropped += 1
                self.latest = msg
                self.event.set()
        except ConnectionClosed:
            pass
        print(f"[phone] disconnected {peer}")

    def ingest(self, msg: bytes):
        """Decode + map one message (runs in a worker thread)."""
        f = protocol.decode(msg)
        with self.lock:
            r = self.mapper.process(f)
            pts = backproject(f.depth, f.K, f.confidence, self.mapper.min_conf, max_range=self.mapper.max_range,
                              stride=2)
            self.frame_points = pts @ r.R.T + r.t
            self.last = (f, r)
            self.mapped += 1
        return f, r

    async def worker(self) -> None:
        while True:
            await self.event.wait()
            self.event.clear()
            msg, self.latest = self.latest, None
            if msg is None:
                continue
            try:
                await asyncio.to_thread(self.ingest, msg)
            except Exception as e:  # bad frame: count it, keep going
                self.bad += 1
                if self.bad <= 5:
                    print(f"[phone] rejected frame: {e}")

    # ---------------------------------------------------------------- viewer side
    def _display_map(self, n: int) -> tuple[np.ndarray, np.ndarray]:
        """The whole map, evenly thinned to <= n points (coarser grid as the map grows).

        A random sample of a 500k-voxel map showed ~3% of it and made the map look like it
        wasn't accumulating (first phone runs, 2026-11-14). Cached; rebuilt when the map grows 2%.
        """
        size = len(self.mapper.map)
        if self._disp is not None and abs(size - self._disp_size) <= 0.02 * max(self._disp_size, 1) \
                and self._disp_map is self.mapper.map:
            return self._disp
        p, c = self.mapper.map.points(2)
        voxel = max(0.05, self._disp_voxel / 1.25)  # the map only grows: start near last time's size
        while True:
            _, idx = np.unique(_pack(np.floor(p / voxel).astype(np.int64)), return_index=True)
            if len(idx) <= n or len(p) == 0:
                break
            voxel *= 1.25
        self._disp_voxel = voxel
        self._disp, self._disp_size, self._disp_map = (p[idx], c[idx]), size, self.mapper.map
        return self._disp

    def snapshot(self) -> str:
        with self.lock:
            rows = []
            if self.view in ("map", "both"):
                n = MAX_VIEWER_POINTS - (FRAME_POINTS if self.view == "both" else 0)
                p, c = self._display_map(n)
                rows += [[round(float(x), 3), round(float(y), 3), round(float(z), 3), float(min(k, 50))]
                         for (x, y, z), k in zip(p, c)]
            if self.view in ("frame", "both") and len(self.frame_points):
                fp = self.frame_points
                if len(fp) > FRAME_POINTS:
                    fp = fp[np.random.default_rng(self.seq).choice(len(fp), FRAME_POINTS, replace=False)]
                rows += [[round(float(x), 3), round(float(y), 3), round(float(z), 3), 100.0] for x, y, z in fp]
            t = float(self.last[0].t) if self.last else 0.0
        self.seq += 1
        return json.dumps({
            "protocol_version": "0.1", "type": "sonar_frame", "sequence": self.seq, "timestamp": t,
            "source": "live", "acquisition_source": "live",
            "frame": {"format_version": "0.2",
                      "meta": {"format_version": "0.2", "source": "live", "sensor_id": "iphone-lidar",
                               "tilt_deg": 0.0, "kind": "lidar_map", "view": self.view},
                      "points": rows[:MAX_VIEWER_POINTS]},
            "detections": None,
        })

    async def viewer_handler(self, conn, fps: float = 5.0) -> None:
        print("[viewer] connected")
        try:
            while True:
                await asyncio.wait_for(conn.send(self.snapshot()), timeout=5)
                await asyncio.sleep(1 / fps)
        except (ConnectionClosed, asyncio.TimeoutError):
            pass
        print("[viewer] disconnected")

    # ---------------------------------------------------------------- dense viewer (viewer.html)
    def dense_snapshot(self, send_map: bool) -> bytes:
        """Binary message for viewer.html: JSON header + float32 xyz (map, live frame, trajectory)."""
        with self.lock:
            m = self.mapper
            mp = np.zeros((0, 3), np.float32)
            if send_map:
                p, _ = m.map.points(2)
                if len(p) > MAX_DENSE_POINTS:  # thin evenly, never randomly
                    voxel = m.map.voxel
                    while len(p) > MAX_DENSE_POINTS:
                        voxel *= 1.25
                        _, idx = np.unique(_pack(np.floor(p / voxel).astype(np.int64)), return_index=True)
                        p = p[idx]
                mp = p.astype(np.float32)
            fp = self.frame_points.astype(np.float32)
            if len(fp) > 30000:
                fp = fp[::int(np.ceil(len(fp) / 30000))]
            tr = np.asarray(m.trajectory[-5000:], np.float32).reshape(-1, 3)
            f, r = self.last if self.last else (None, None)
            hdr = {"n_map": int(len(mp)) if send_map else -1, "n_frame": int(len(fp)), "n_traj": int(len(tr)),
                   "status": r.status if r else "waiting", "voxels": len(m.map),
                   "valid": f.valid_fraction if f else None,
                   "pose": [float(x) for x in r.t] if r else None, "segments": len(m.segments)}
        hb = json.dumps(hdr).encode()
        pad = (4 - (4 + len(hb)) % 4) % 4
        return (struct.pack("<I", len(hb)) + hb + b"\0" * pad + mp.tobytes() + fp.tobytes() + tr.tobytes())

    async def dense_handler(self, conn, fps: float = 4.0) -> None:
        print("[map viewer] connected")
        last_size, last_sent = -1, 0.0
        try:
            while True:
                size, now = len(self.mapper.map), time.time()
                send_map = last_size < 0 or (size != last_size and now - last_sent > 1.0)
                msg = await asyncio.to_thread(self.dense_snapshot, send_map)
                if send_map:
                    last_size, last_sent = size, now
                await asyncio.wait_for(conn.send(msg), timeout=10)
                await asyncio.sleep(1 / fps)
        except (ConnectionClosed, asyncio.TimeoutError):
            pass
        print("[map viewer] disconnected")

    # ---------------------------------------------------------------- status
    def status_line(self) -> str:
        if not self.last:
            return f"[map] waiting for frames (received {self.rx}, rejected {self.bad})"
        f, r = self.last
        lux = f"{f.ambient_lux:.0f} lux" if f.ambient_lux is not None else "lux n/a"
        return (f"[map] rx {self.rx} mapped {self.mapped} dropped {self.dropped} | {r.status:8s} "
                f"pos ({r.t[0]:+.2f},{r.t[1]:+.2f},{r.t[2]:+.2f}) m | valid depth {f.valid_fraction:.0%} | "
                f"rmse {r.rmse * 100:.1f} cm | grav err {r.gravity_err_deg:.1f} deg | {lux} | "
                f"map {len(self.mapper.map)} voxels")

    async def status(self, every: float = 1.0) -> None:
        while True:
            await asyncio.sleep(every)
            if self.verbose:
                print(self.status_line(), flush=True)

    def close(self) -> None:
        if self.record_fh:
            self.record_fh.close()


def dense_server(live: LiveMapper, port: int = 8780):
    """http://127.0.0.1:<port>/ serves viewer.html; ws://127.0.0.1:<port>/map streams the full map."""
    from http import HTTPStatus

    def http(connection, request):
        if request.path in ("/", "/index.html"):
            resp = connection.respond(HTTPStatus.OK, VIEWER_HTML.read_text())
            resp.headers["Content-Type"] = "text/html; charset=utf-8"
            return resp
        if request.path != "/map":
            return connection.respond(HTTPStatus.NOT_FOUND, "not found\n")
        return None  # WebSocket upgrade

    async def handler(conn):
        await live.dense_handler(conn)

    return serve(handler, "127.0.0.1", port, process_request=http, max_size=1024, compression=None)


async def run_server(live: LiveMapper, port: int = 8770, viewer_port: int = 8765, host: str = "0.0.0.0",
                     viewer_fps: float = 5.0, origins: list[str] | None = None, map_port: int = 8780) -> None:
    async def phone(conn):
        await live.phone_handler(conn)

    async def viewer(conn):
        await live.viewer_handler(conn, viewer_fps)

    tasks = [asyncio.create_task(live.worker()), asyncio.create_task(live.status())]
    async with serve(phone, host, port, max_size=4 * 1024 * 1024, max_queue=2, compression=None), \
            serve(viewer, "127.0.0.1", viewer_port, origins=(origins or VIEWER_ORIGINS) + [None],
                  max_size=1024, compression=None), \
            dense_server(live, map_port):
        print(f"[server] phone -> ws://{host}:{port}/depth   EchoSense viewer -> ws://127.0.0.1:{viewer_port}/ws")
        print(f"[server] full-density map viewer -> http://127.0.0.1:{map_port}/")
        try:
            await asyncio.Future()
        finally:
            for t in tasks:
                t.cancel()
            live.close()


def map_report(mapper: Mapper) -> dict:
    pts, _ = mapper.map.points(2)
    return {"voxels": len(mapper.map), "points_seen_twice": int(len(pts)), "floor": floor_check(pts)}
