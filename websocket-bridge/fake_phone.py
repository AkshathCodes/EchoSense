"""Stand-in for the iPhone app: pushes a SYNTHETIC room sweep to /ingest.

Use it to work on the viewer without a phone:
    python -B -m sonar_bridge --lidar --origin http://127.0.0.1:4173
    python -B fake_phone.py
Frames are labeled live LiDAR by the bridge because that is what the ingest
path carries. The sensor_id says FAKE so a saved map can be told apart.
"""
import argparse
import asyncio
import json
import math

from websockets.asyncio.client import connect


def sweep(heading: float) -> list[list[float]]:
    """Points a phone at the middle of a 5 x 4 m room would see, 60 degree view."""
    points = []
    for column in range(-30, 31, 2):
        angle = heading + math.radians(column)
        dx, dy = math.cos(angle), math.sin(angle)
        # Distance to the nearest wall of the box x in [-2.5, 2.5], y in [-2, 2].
        reach = min((2.5 if dx > 0 else -2.5) / dx if dx else math.inf,
                    (2.0 if dy > 0 else -2.0) / dy if dy else math.inf)
        for row in range(-6, 7):
            z = row * 0.15
            # Rotate into the phone's own frame: X forward, Y left.
            x, y = reach * math.cos(math.radians(column)), reach * math.sin(math.radians(column))
            points.append([round(x, 2), round(y, 2), round(z, 2), 2])
    return points


async def main(url: str, fps: float) -> None:
    async with connect(url, proxy=None, max_size=None) as phone:
        frame = 0
        while True:
            await phone.send(json.dumps({
                "type": "lidar_frame", "version": "0.1", "timestamp": frame / fps,
                "sensor_id": "FAKE-phone-sweep", "tracking": "normal", "reference": "sensor",
                "points": sweep(frame / fps * 0.4)}))
            frame += 1
            await asyncio.sleep(1 / fps)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ingest")
    parser.add_argument("--fps", type=float, default=8.0)
    arguments = parser.parse_args()
    try:
        asyncio.run(main(arguments.url, arguments.fps))
    except KeyboardInterrupt:
        pass
