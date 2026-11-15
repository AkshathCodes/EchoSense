"""SYNTHETIC stand-in for the iPhone app. Not real LiDAR data.

Publishes lidar_frame v1 messages with source "synthetic": a scanner walking
through a 5 x 4 m box room with a table and a crate. Use it to work on the bridge and viewer without
the phone:
    python -B -m sonar_bridge --lidar --origin http://127.0.0.1:4173
    python -B fake_phone.py
"""
import argparse
import asyncio
import json
import math
import random
import uuid

from websockets.asyncio.client import connect

ROOM_X, ROOM_Z, FLOOR, CEILING = 2.5, 2.0, -1.3, 1.2
# Synthetic furniture as boxes: (x0, x1, y0, y1, z0, z1). A table and a low crate.
BOXES = ((1.0, 2.0, FLOOR, FLOOR + 0.75, -0.3, 0.3), (-1.8, -1.3, FLOOR, FLOOR + 0.5, 1.0, 1.5))


def box_hit(origin, direction, box) -> float:
    """Distance along the ray to the box, or infinity. Slab test."""
    near, far = 0.0, math.inf
    for o, d, lo, hi in zip(origin, direction, box[0::2], box[1::2]):
        if abs(d) < 1e-9:
            if not lo <= o <= hi:
                return math.inf
            continue
        a, b = (lo - o) / d, (hi - o) / d
        near, far = max(near, min(a, b)), min(far, max(a, b))
    return near if near <= far and near > 0 else math.inf


def frame(sequence: int, session: str, rng: random.Random) -> dict:
    t = sequence / 3
    # Camera walks a small loop and turns as it goes. ARKit world: +Y up, -Z ahead at start.
    cx, cz = 0.8 * math.sin(t * 0.15), 0.6 * math.cos(t * 0.15) - 0.6
    yaw = t * 0.25
    points, confidences = [], []
    for _ in range(900):
        azimuth = yaw + rng.uniform(-0.5, 0.5)
        pitch = rng.uniform(-0.6, 0.4)
        dx, dy, dz = -math.sin(azimuth) * math.cos(pitch), math.sin(pitch), -math.cos(azimuth) * math.cos(pitch)
        reach = min((ROOM_X - cx) / dx if dx > 0 else (-ROOM_X - cx) / dx if dx < 0 else math.inf,
                    (ROOM_Z - cz) / dz if dz > 0 else (-ROOM_Z - cz) / dz if dz < 0 else math.inf,
                    CEILING / dy if dy > 0 else FLOOR / dy if dy < 0 else math.inf)
        reach = min(reach, *(box_hit((cx, 0.0, cz), (dx, dy, dz), box) for box in BOXES))
        if reach > 5:
            continue
        points.append([round(cx + dx * reach, 3), round(dy * reach, 3), round(cz + dz * reach, 3)])
        confidences.append(2)
    cos, sin = math.cos(yaw), math.sin(yaw)
    pose = [cos, 0, -sin, 0, 0, 1, 0, 0, sin, 0, cos, 0, round(cx, 3), 0, round(cz, 3), 1]
    return {"type": "lidar_frame", "schema_version": 1, "session_id": session, "device_id": "SYNTHETIC-fake-phone",
            "sequence": sequence, "timestamp": round(t, 3), "source": "synthetic",
            "coordinate_frame": "arkit_world", "units": "meters", "tracking": "normal",
            "camera_to_world": pose, "points": points, "confidences": confidences}


async def main(url: str, fps: float, count: int | None) -> None:
    rng = random.Random(7)
    # A fresh id each run, as the real app does: the bridge refuses to merge runs.
    session = "synthetic-" + uuid.uuid4().hex[:12]
    async with connect(url, proxy=None, max_size=None) as phone:
        sequence = 0
        while count is None or sequence < count:
            await phone.send(json.dumps(frame(sequence, session, rng)))
            sequence += 1
            await asyncio.sleep(1 / fps)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8765/lidar/publish")
    parser.add_argument("--fps", type=float, default=3.0)
    parser.add_argument("--frames", type=int, help="stop after this many frames")
    arguments = parser.parse_args()
    try:
        asyncio.run(main(arguments.url, arguments.fps, arguments.frames))
    except KeyboardInterrupt:
        pass
