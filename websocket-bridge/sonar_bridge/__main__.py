"""Run the local bridge; simulated source by default."""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .server import Bridge, DEFAULT_ORIGINS, start_server
from .sources import demo_messages, recorded_messages


async def run(args: argparse.Namespace) -> None:
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
    parser.add_argument("--fps", type=float, default=10.0, help="send rate, >0 and <=30 (default 10)")
    parser.add_argument("--origin", action="append", help="exact allowed browser Origin; repeat to allow several")
    parser.add_argument("--allow-no-origin", action="store_true", help="allow non-browser clients without Origin")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Cannot start bridge: {exc}\n")


if __name__ == "__main__":
    main()
