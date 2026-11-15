"""Run the bridge. Simulated sonar by default; --lidar and --lidar-replay serve LiDAR."""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import socket
import sys

from .lidar import LidarHub, LidarReplay, read_recording, start_lidar
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
    origins = tuple(args.origin or DEFAULT_ORIGINS)
    where = lan_address() if args.host == "0.0.0.0" else args.host
    if args.lidar_replay is not None:
        service = LidarReplay(read_recording(args.lidar_replay), fps=args.fps if args.fps_given else 3.0,
                              origins=origins, allow_no_origin=args.allow_no_origin)
        async with start_lidar(service, host=args.host):
            print(f"ECHO bridge LiDAR REPLAY of {args.lidar_replay.name} "
                  f"({len(service.messages)} frames)\n  viewer: ws://127.0.0.1:8765/lidar/view", flush=True)
            await asyncio.Future()
    record = args.record.open("a", encoding="utf-8") if args.record is not None else None
    try:
        hub = LidarHub(origins=origins, allow_no_origin=args.allow_no_origin, record=record)
        async with start_lidar(hub, host=args.host):
            print(f"ECHO bridge LIVE LiDAR\n  viewer: ws://127.0.0.1:8765/lidar/view\n"
                  f"  phone:  enter {where} in the app (ws://{where}:8765/lidar/publish)"
                  + (f"\n  recording to {args.record}" if record else ""), flush=True)
            await asyncio.Future()
    finally:
        if record is not None:
            record.close()


async def run_ranges(args: argparse.Namespace) -> None:
    from contextlib import ExitStack
    from .range_processing import Policy
    from .range_recording import RangeRecorder
    from .range_server import RangeHub,RangeReplay,start_range_server
    origins=tuple(args.origin or DEFAULT_ORIGINS)
    policy=Policy(args.range_window,args.range_min_valid,args.range_max_spread,args.range_outlier,args.range_reference)
    if args.range_replay:
        ranges=RangeReplay(args.range_replay,fps=args.range_fps,origins=origins,allow_no_origin=args.allow_no_origin)
    else:
        recorder=RangeRecorder(args.range_record,policy) if args.range_record else None
        ranges=RangeHub(policy=policy,record=recorder,origins=origins,allow_no_origin=args.allow_no_origin)
    factory=demo_messages if args.manifest is None else lambda:recorded_messages(args.manifest)
    with ExitStack() as stack:
        lidar=None
        if args.lidar:
            record=stack.enter_context(args.record.open("a",encoding="utf-8")) if args.record else None
            lidar=LidarHub(origins=origins,allow_no_origin=args.allow_no_origin,record=record)
        elif args.lidar_replay:
            lidar=LidarReplay(read_recording(args.lidar_replay),fps=args.fps if args.fps_given else 3.0,
                              origins=origins,allow_no_origin=args.allow_no_origin)
        async with start_range_server(Bridge(factory,fps=args.fps),ranges,lidar=lidar,host=args.host or "127.0.0.1",
                                      port=args.port,origins=origins,allow_no_origin=args.allow_no_origin) as server:
            print(f"ECHO range bridge ws://{args.host or '127.0.0.1'}:{server.sockets[0].getsockname()[1]}/range/view | "
                  f"{'REPLAY' if args.range_replay else 'no fabricated data; waiting for adapter'}",flush=True)
            await asyncio.Future()


async def run(args: argparse.Namespace) -> None:
    if args.range or args.range_replay is not None:
        await run_ranges(args)
        return
    if args.lidar or args.lidar_replay is not None:
        args.host=args.host or "0.0.0.0"
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
                        help="LiDAR mode: phone publishes to /lidar/publish, viewers read /lidar/view")
    parser.add_argument("--record", type=Path, help="with --lidar: append accepted frames to this JSONL file")
    parser.add_argument("--lidar-replay", type=Path, metavar="JSONL",
                        help="replay a recorded LiDAR session to /lidar/view (default 3 fps)")
    parser.add_argument("--host", default=None,
                        help="bind address for LiDAR modes (default 0.0.0.0, all interfaces)")
    parser.add_argument("--fps", type=float, default=10.0, help="send rate, >0 and <=30 (default 10)")
    parser.add_argument("--origin", action="append", help="exact allowed browser Origin; repeat to allow several")
    parser.add_argument("--allow-no-origin", action="store_true", help="allow non-browser clients without Origin")
    parser.add_argument("--range",action="store_true",help="add independent /range endpoints alongside original services")
    parser.add_argument("--range-record",type=Path,help="exclusive range JSONL capture; no overwrite")
    parser.add_argument("--range-replay",type=Path,help="replay validated range recording without hardware")
    parser.add_argument("--range-fps",type=float,default=5)
    parser.add_argument("--range-window",type=int,default=5)
    parser.add_argument("--range-min-valid",type=int,default=3)
    parser.add_argument("--range-max-spread",type=float,default=0.35)
    parser.add_argument("--range-outlier",type=float)
    parser.add_argument("--range-reference",type=float,help="operator-supplied tape distance, meters")
    parser.add_argument("--port",type=int,default=8765,help="integrated range server port; original modes unchanged")
    args = parser.parse_args()
    if args.range_record and (not args.range or args.range_replay): parser.error("--range-record needs live --range")
    if args.range and args.range_replay: parser.error("choose --range or --range-replay")
    args.fps_given = any(item == "--fps" or item.startswith("--fps=") for item in sys.argv[1:])
    if sum((args.lidar, args.lidar_replay is not None, args.manifest is not None)) > 1:
        parser.error("--lidar, --lidar-replay and --manifest are different sources; choose one")
    if args.record is not None and not args.lidar:
        parser.error("--record needs --lidar")
    logging.basicConfig(level=logging.INFO if args.range or args.range_replay else logging.WARNING)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Cannot start bridge: {exc}\n")


if __name__ == "__main__":
    main()
