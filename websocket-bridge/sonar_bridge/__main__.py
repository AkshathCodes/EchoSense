"""Run the bridge. Simulated source by default; --lidar relays a phone's LiDAR."""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import socket

from .relay import LiveRelay, start_relay
from .server import Bridge, DEFAULT_ORIGINS, start_server
from .sources import demo_messages, recorded_messages


def lan_address() -> str:
    """Best guess at this machine's LAN IPv4 address. Sends no packets."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            return probe.getsockname()[0]
    except OSError:
        return "<this-computer's-IP>"


async def run_lidar(args: argparse.Namespace) -> None:
    relay = LiveRelay(origins=tuple(args.origin or DEFAULT_ORIGINS),
                      allow_no_origin=args.allow_no_origin)
    async with start_relay(relay, host=args.host):
        print(f"ECHO bridge LIVE LiDAR relay\n  viewer: ws://127.0.0.1:8765/ws\n"
              f"  phone:  enter {lan_address()} in the EchoSense LiDAR app "
              f"(ws://{lan_address()}:8765/ingest)", flush=True)
        await asyncio.Future()


async def run(args: argparse.Namespace) -> None:
    if args.lidar:
        await run_lidar(args)
        return
    factory = demo_messages if args.manifest is None else lambda: recorded_messages(args.manifest)
    bridge = Bridge(factory, fps=args.fps)
    async with start_server(bridge, origins=tuple(args.origin or DEFAULT_ORIGINS),
                            allow_no_origin=args.allow_no_origin):
        print("ECHO bridge ws://127.0.0.1:8765/ws | " +
              ("SIMULATED demo (no classifier)" if args.manifest is None else "RECORDED replay"), flush=True)
        await asyncio.Future()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="JSONL manifest of saved NPZ frames and detection JSON")
    parser.add_argument("--lidar", action="store_true",
                        help="relay live frames pushed by the iPhone app to /ingest (binds to the LAN)")
    parser.add_argument("--host", default="0.0.0.0", help="bind address for --lidar (default 0.0.0.0)")
    parser.add_argument("--fps", type=float, default=10.0, help="send rate, >0 and <=30 (default 10)")
    parser.add_argument("--origin", action="append", help="exact allowed browser Origin; repeat to allow several")
    parser.add_argument("--allow-no-origin", action="store_true", help="allow non-browser clients without Origin")
    args = parser.parse_args()
    if args.lidar and args.manifest is not None:
        parser.error("--lidar and --manifest are different sources; choose one")
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Cannot start bridge: {exc}\n")


if __name__ == "__main__":
    main()
