"""Metadata regression tests. Every depth/range fixture here is SYNTHETIC."""
import json
import asyncio
from dataclasses import replace

import pytest

from lidar_mapper import protocol
from lidar_mapper.mapper import Mapper
from lidar_mapper.server import LiveMapper, write_record
from lidar_mapper.sim import stream
from lidar_mapper.sonar import SonarFusion


@pytest.fixture(scope="module")
def frame():
    return next(stream(1))


@pytest.mark.parametrize("delivery,sources,expected", [
    ("live", ["lidar"], "live"),
    ("live", ["arkit"], "live"),
    ("live", ["sim"], "simulated"),
    ("recorded", ["sim"], "simulated"),
    ("recorded", ["lidar"], "live"),
    ("recorded", ["legacy-unknown"], "recorded"),
    ("live", ["legacy-unknown"], "recorded"),
    ("live", ["sim", "lidar"], "simulated"),
    ("live", ["lidar", "sim"], "simulated"),
    ("live", ["lidar", "legacy-unknown"], "recorded"),
    ("simulated", [], "simulated"),
    ("live", [], "recorded"),
    ("recorded", [], "recorded"),
])
def test_snapshot_preserves_delivery_and_accumulated_acquisition(frame, delivery, sources, expected):
    live = LiveMapper(Mapper(), delivery=delivery)
    for seq, source in enumerate(sources):
        live.ingest(protocol.encode(replace(frame, source=source, seq=seq)))
    raw = json.loads(live.snapshot())
    assert set(raw) == {"protocol_version", "type", "sequence", "timestamp", "source",
                        "acquisition_source", "frame", "detections"}
    assert raw["protocol_version"] == "0.1" and raw["type"] == "sonar_frame"
    assert raw["source"] == delivery
    assert raw["acquisition_source"] == raw["frame"]["meta"]["source"] == expected
    assert all(len(row) == 4 for row in raw["frame"]["points"])


def test_metadata_does_not_change_geometry(frame):
    frames = []
    for delivery in ("live", "simulated", "recorded"):
        live = LiveMapper(Mapper(), delivery=delivery)
        live.ingest(protocol.encode(frame))
        frames.append(json.loads(live.snapshot())["frame"]["points"])
    assert frames[0] == frames[1] == frames[2]


def test_invalid_delivery_is_rejected():
    with pytest.raises(ValueError, match="delivery"):
        LiveMapper(Mapper(), delivery="invented")


@pytest.mark.parametrize("command,source,delivery,acquisition", [
    ("sim", "sim", "simulated", "simulated"),
    ("replay", "sim", "recorded", "simulated"),
    ("replay", "lidar", "recorded", "live"),
    ("replay", "unknown", "recorded", "recorded"),
])
def test_cli_served_modes(monkeypatch, tmp_path, frame, command, source, delivery, acquisition):
    from lidar_mapper import __main__ as cli
    captured = []

    async def paced(live, messages, port):
        live.ingest(messages[0])
        captured.append(json.loads(live.snapshot()))

    monkeypatch.setattr(cli, "_paced", paced)
    monkeypatch.setattr(cli, "_finish", lambda *args: None)
    if command == "sim":
        args = ["sim", "--frames", "1", "--serve", "--sonar-sim"]
    else:
        path = tmp_path / "synthetic.esd"
        with path.open("wb") as fh:
            write_record(fh, protocol.encode(replace(frame, source=source)))
        args = ["replay", str(path), "--serve"]
    monkeypatch.setattr("sys.argv", ["lidar_mapper", *args])
    cli.main()
    assert captured[0]["source"] == delivery
    assert captured[0]["acquisition_source"] == acquisition
    if command == "sim":
        assert captured[0]["frame"]["meta"]["sonar"]["synthetic"] is True


def test_sonar_sidecar_does_not_invent_original_provenance(frame):
    live = LiveMapper(Mapper(), delivery="recorded")
    live.sonar = SonarFusion()
    live.sonar_replay = {frame.seq: 0.8}
    live.ingest(protocol.encode(frame))
    raw = json.loads(live.snapshot())
    assert raw["acquisition_source"] == "simulated"  # Known depth source.
    sonar = raw["frame"]["meta"]["sonar"]
    assert sonar["acquisition_source"] == "recorded"  # Scalar sidecar has no source field.
    assert sonar["synthetic"] is False


def test_binary_phone_to_viewer_websockets_preserve_simulated_acquisition(frame):
    """Exercise the real server handlers on ephemeral ports; no phone or serial device."""
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve

    async def exchange():
        live = LiveMapper(Mapper(), verbose=False)
        worker = asyncio.create_task(live.worker())
        try:
            async with serve(live.phone_handler, "127.0.0.1", 0) as phone, \
                    serve(live.viewer_handler, "127.0.0.1", 0,
                          origins=["http://127.0.0.1:4173"]) as viewer:
                phone_port = phone.sockets[0].getsockname()[1]
                viewer_port = viewer.sockets[0].getsockname()[1]
                async with connect(f"ws://127.0.0.1:{phone_port}/depth") as publisher, \
                        connect(f"ws://127.0.0.1:{viewer_port}/ws",
                                origin="http://127.0.0.1:4173", max_size=6_000_000) as client:
                    await publisher.send(protocol.encode(frame))
                    while True:
                        raw = json.loads(await asyncio.wait_for(client.recv(), timeout=10))
                        if raw["frame"]["points"]:
                            break
                    assert raw["source"] == "live"  # Live transport, synthetic acquisition.
                    assert raw["acquisition_source"] == "simulated"
                    assert raw["frame"]["meta"]["source"] == "simulated"
                    assert live.mapped == 1 and live.bad == 0
        finally:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

    asyncio.run(exchange())
