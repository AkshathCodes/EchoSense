"""Synthetic depth/transport fixtures only; no physical phone or serial device."""
import asyncio
from dataclasses import replace
import json

import pytest

from lidar_mapper import protocol
from lidar_mapper.mapper import Mapper
from lidar_mapper.server import LiveMapper
from lidar_mapper.sim import stream


@pytest.fixture(scope="module")
def frame():
    return next(stream(1))


def snapshot(live):
    return json.loads(live.snapshot())


def test_successful_ingestion_not_snapshot_frequency_controls_stall_and_resume(monkeypatch, frame):
    clock = [100.0]
    monkeypatch.setattr("lidar_mapper.server.time.monotonic", lambda: clock[0])
    live = LiveMapper(Mapper(), view="map")
    live._phones.add(1)  # Synthetic connected transport fixture.
    assert snapshot(live)["frame"]["meta"]["capture"]["state"] == "waiting"
    message = protocol.encode(replace(frame, source="lidar"))  # Test source-header semantics only.
    live.ingest(message, phone=1)
    first = snapshot(live)
    assert first["frame"]["meta"]["capture"] == {
        "mode": "live", "state": "active", "age_s": 0.0, "stall_after_s": 3.0}
    clock[0] = 103.0
    assert snapshot(live)["frame"]["meta"]["capture"]["state"] == "active"
    clock[0] = 104.0
    for _ in range(5):
        stale = snapshot(live)
        assert stale["frame"]["meta"]["capture"]["state"] == "stalled"
        assert stale["frame"]["points"] == first["frame"]["points"]
        assert live.last_ingested_at == 100.0
    with pytest.raises(Exception):
        live.ingest(b"not a depth frame")
    assert live.last_ingested_at == 100.0
    clock[0] = 105.0
    live.ingest(message, phone=1)
    assert snapshot(live)["frame"]["meta"]["capture"]["state"] == "active"
    live._phones.clear()
    assert snapshot(live)["frame"]["meta"]["capture"]["state"] == "disconnected"


@pytest.mark.parametrize("delivery,source,mode", [
    ("simulated", "sim", "simulated"), ("recorded", "sim", "replay"),
    ("recorded", "lidar", "replay"), ("live", "sim", "simulated"),
    ("live", "legacy-unknown", "unknown"),
])
def test_capture_mode_never_promotes_simulation_or_replay_to_phone(monkeypatch, frame, delivery, source, mode):
    clock = [10.0]
    monkeypatch.setattr("lidar_mapper.server.time.monotonic", lambda: clock[0])
    live = LiveMapper(Mapper(), delivery=delivery, capture_stall_s=5)
    if delivery == "live":
        live._phones.add(1)
    live.ingest(protocol.encode(replace(frame, source=source)), phone=1 if delivery == "live" else None)
    assert snapshot(live)["frame"]["meta"]["capture"]["mode"] == mode
    if delivery != "live":
        live.finish_capture()
        capture = snapshot(live)["frame"]["meta"]["capture"]
        assert capture["state"] == "complete" and capture["age_s"] == 0
    else:
        clock[0] += 6
        assert snapshot(live)["frame"]["meta"]["capture"]["state"] == "stalled"


@pytest.mark.parametrize("threshold", [0, -1, float("nan"), float("inf")])
def test_invalid_stall_threshold_rejected(threshold):
    with pytest.raises(ValueError, match="finite and positive"):
        LiveMapper(Mapper(), capture_stall_s=threshold)


def test_failed_mapping_does_not_refresh_success_time(monkeypatch, frame):
    live = LiveMapper(Mapper())
    def fail(_):
        raise ValueError("synthetic mapping failure")
    monkeypatch.setattr(live.mapper, "process", fail)
    with pytest.raises(ValueError, match="mapping failure"):
        live.ingest(protocol.encode(frame))
    assert live.last_ingested_at is None


def test_phone_connection_lifecycle_without_hardware():
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve

    async def exchange():
        live = LiveMapper(Mapper(), verbose=False)
        async with serve(live.phone_handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}/depth"):
                assert snapshot(live)["frame"]["meta"]["capture"]["state"] == "waiting"
            for _ in range(100):
                if snapshot(live)["frame"]["meta"]["capture"]["state"] == "disconnected":
                    break
                await asyncio.sleep(0.01)
            assert snapshot(live)["frame"]["meta"]["capture"]["state"] == "disconnected"
    asyncio.run(exchange())


def test_reconnected_phone_requires_its_own_successful_depth(frame):
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve

    async def exchange():
        live = LiveMapper(Mapper(), view="map", verbose=False, capture_stall_s=30)

        async def wait_for(state):
            async def until():
                while snapshot(live)["frame"]["meta"]["capture"]["state"] != state:
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(until(), 5)

        async with serve(live.phone_handler, "127.0.0.1", 0) as server:
            url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/depth"
            worker = asyncio.create_task(live.worker())
            try:
                async with connect(url) as phone:
                    await phone.send(protocol.encode(replace(frame, source="lidar")))
                    await wait_for("active")
                await wait_for("disconnected")
                previous = snapshot(live)["frame"]["points"]
                assert previous
                async with connect(url) as phone:
                    capture = snapshot(live)["frame"]["meta"]["capture"]
                    assert capture["state"] == "waiting" and capture["age_s"] is None
                    # Work left in the previous socket's queue cannot reactivate capture.
                    live.ingest(protocol.encode(replace(frame, source="lidar", seq=1)), phone=1)
                    assert snapshot(live)["frame"]["meta"]["capture"]["state"] == "waiting"
                    assert snapshot(live)["frame"]["points"] == previous
                    await phone.send(protocol.encode(replace(frame, source="lidar", seq=1)))
                    await wait_for("active")
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
    asyncio.run(exchange())


def test_cli_passes_configured_threshold(monkeypatch):
    from lidar_mapper import __main__ as cli
    seen = []
    async def paced(live, messages, port):
        seen.append(live.capture_stall_s)
    monkeypatch.setattr(cli, "_paced", paced)
    monkeypatch.setattr(cli, "_finish", lambda *args: None)
    cli.main(["sim", "--frames", "1", "--serve", "--capture-stall-seconds", "4.5"])
    assert seen == [4.5]
