"""Start CLI on 8765 and read three SIMULATED frames with a Python client."""
import asyncio
import json
from pathlib import Path
import sys

from websockets.asyncio.client import connect


async def main() -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-B", "-m", "sonar_bridge",
        cwd=Path(__file__).resolve().parent, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    try:
        line = await asyncio.wait_for(process.stdout.readline(), 10)
        if not line or b"SIMULATED" not in line:
            raise RuntimeError("Bridge failed to start; port 8765 may be in use")
        async with connect("ws://127.0.0.1:8765/ws", origin="http://localhost:5173", proxy=None) as client:
            messages = [json.loads(await asyncio.wait_for(client.recv(), 3)) for _ in range(3)]
            assert [m["sequence"] for m in messages] == [0, 1, 2]
            assert all(m["source"] == "simulated" and m["acquisition_source"] == "simulated" for m in messages)
            assert all(len(m["frame"]["points"]) == 45 and m["detections"] is None for m in messages)
            assert all(p[0] == 2.0 for m in messages for p in m["frame"]["points"])
        print("SMOKE PASS: ws://127.0.0.1:8765/ws; 3 SIMULATED frames; sequences 0,1,2; 45 points/frame; detections=null; client disconnected")
    finally:
        if process.returncode is None:
            process.terminate()
        await asyncio.wait_for(process.communicate(), 5)
    print("SMOKE CLEANUP: server process stopped")


if __name__ == "__main__":
    asyncio.run(main())
