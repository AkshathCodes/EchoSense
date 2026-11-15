"""lidar_frame v1 validation, live hub, recording and replay over loopback sockets."""
import asyncio
import io
import json

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from sonar_bridge.lidar import (LidarHub, LidarReplay, read_recording, start_lidar,
                                validate_lidar_frame)

ORIGIN = "http://localhost:5173"
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0.5, 0, -1.0, 1]


def frame(**changes):
    value = {"type": "lidar_frame", "schema_version": 1, "session_id": "s1", "device_id": "test-phone",
             "sequence": 0, "timestamp": 12.5, "source": "arkit_scene_depth",
             "coordinate_frame": "arkit_world", "units": "meters", "tracking": "normal",
             "camera_to_world": IDENTITY, "points": [[0.5, -1.2, -2.0], [0.6, 0.1, -2.1]],
             "confidences": [2, 1]}
    value.update(changes)
    return json.dumps(value)


def url(server, path):
    return f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}{path}"


async def receive(client):
    return json.loads(await asyncio.wait_for(client.recv(), 2))


def test_valid_frame_keeps_arkit_coordinates_untouched():
    parsed = validate_lidar_frame(frame())
    assert parsed["points"] == [[0.5, -1.2, -2.0], [0.6, 0.1, -2.1]]
    assert parsed["camera_to_world"] == IDENTITY and parsed["confidences"] == [2, 1]


def missing(key):
    value = json.loads(frame())
    del value[key]
    return json.dumps(value)


@pytest.mark.parametrize("bad", [
    "not json", "[]", missing("session_id"), missing("camera_to_world"), frame(extra=1),
    frame(schema_version=2), frame(type="sonar_frame"), frame(session_id=""), frame(sequence=-1),
    frame(sequence=1.5), frame(timestamp="now"), frame(source="sonar"), frame(tracking="great"),
    frame(coordinate_frame="sonar_body"), frame(units="feet"), frame(camera_to_world=[0] * 15),
    frame(camera_to_world=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 2]),
    frame(points=[[1, 2]], confidences=[2]), frame(points=[[1, 2, float("nan")]], confidences=[2]),
    frame(points=[[1, 2, 5000]], confidences=[2]), frame(confidences=[2]), frame(confidences=[2, 3]),
    frame(confidences=[2, 1.0]), frame(points=[[0, 0, 0]] * 5001, confidences=[2] * 5001)])
def test_malformed_frames_are_rejected(bad):
    with pytest.raises(ValueError):
        validate_lidar_frame(bad)


def test_live_frames_reach_viewer_with_status_and_late_join_backlog():
    async def scenario():
        hub = LidarHub()
        async with start_lidar(hub, host="127.0.0.1", port=0) as server:
            async with connect(url(server, "/lidar/view"), origin=ORIGIN, proxy=None) as viewer:
                first = await receive(viewer)
                assert first["type"] == "lidar_status" and first["publisher_connected"] is False
                async with connect(url(server, "/lidar/publish"), proxy=None) as phone:
                    assert (await receive(viewer))["publisher_connected"] is True
                    await phone.send(frame())
                    assert (await receive(viewer))["session_id"] == "s1"     # status: new session
                    got = await receive(viewer)
                    assert got["type"] == "lidar_frame" and got["points"][0] == [0.5, -1.2, -2.0]
                    await phone.send("garbage")
                    await phone.send(frame(sequence=0))                       # repeated sequence
                    await phone.send(frame(sequence=1))
                    assert (await receive(viewer))["sequence"] == 1
                    assert hub.rejected == 2 and hub.accepted == 2
                    async with connect(url(server, "/lidar/view"), origin=ORIGIN, proxy=None) as late:
                        assert (await receive(late))["type"] == "lidar_status"
                        assert [(await receive(late))["sequence"] for _ in range(2)] == [0, 1]
                assert (await receive(viewer))["publisher_connected"] is False
            for _ in range(100):
                if not hub.viewers:
                    break
                await asyncio.sleep(0.01)
            assert not hub.viewers and hub.publisher is None
    asyncio.run(scenario())


def test_new_session_clears_backlog_so_origins_are_never_merged():
    hub = LidarHub()
    hub.accept(frame(sequence=5))
    hub.accept(frame(sequence=6))
    hub.accept(frame(session_id="s2", sequence=0))
    assert hub.session_id == "s2"
    assert [json.loads(m)["session_id"] for m in hub.history] == ["s2"]


def test_viewer_outbox_is_bounded():
    async def scenario():
        hub = LidarHub(backlog=3)
        for sequence in range(10):
            hub.accept(frame(sequence=sequence))
        assert [json.loads(m)["sequence"] for m in hub.history] == [7, 8, 9]
    asyncio.run(scenario())


def test_record_then_replay_is_deterministic(tmp_path):
    recording = io.StringIO()
    hub = LidarHub(record=recording)
    for sequence in range(3):
        hub.accept(frame(sequence=sequence, timestamp=float(sequence)))
    path = tmp_path / "session.jsonl"
    path.write_text(recording.getvalue(), encoding="utf-8")
    messages = read_recording(path)
    assert messages == list(hub.history)

    async def scenario():
        async with start_lidar(LidarReplay(messages, fps=30), host="127.0.0.1", port=0) as server:
            runs = []
            for _ in range(2):
                async with connect(url(server, "/lidar/view"), origin=ORIGIN, proxy=None) as viewer:
                    assert (await receive(viewer))["mode"] == "replay"
                    runs.append([(await receive(viewer))["timestamp"] for _ in range(3)])
                    await asyncio.wait_for(viewer.wait_closed(), 2)
                    assert viewer.close_code == 1000 and viewer.close_reason == "source complete"
            assert runs == [[0.0, 1.0, 2.0]] * 2
    asyncio.run(scenario())


def test_bad_recordings_are_refused(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_recording(empty)
    broken = tmp_path / "broken.jsonl"
    broken.write_text(frame() + "\n" + frame(units="feet") + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_recording(broken)


@pytest.mark.parametrize("path, origin, status", [
    ("/lidar/view", None, 403), ("/lidar/view", "https://untrusted.example", 403),
    ("/lidar/publish", ORIGIN, 403), ("/ws", ORIGIN, 404), ("/ingest", None, 404)])
def test_handshake_restrictions(path, origin, status):
    async def scenario():
        async with start_lidar(LidarHub(), host="127.0.0.1", port=0) as server:
            with pytest.raises(InvalidStatus) as error:
                async with connect(url(server, path), origin=origin, proxy=None):
                    pass
            assert error.value.response.status_code == status
    asyncio.run(scenario())


def test_second_phone_is_turned_away():
    async def scenario():
        async with start_lidar(LidarHub(), host="127.0.0.1", port=0) as server:
            async with connect(url(server, "/lidar/publish"), proxy=None):
                async with connect(url(server, "/lidar/publish"), proxy=None) as second:
                    await asyncio.wait_for(second.wait_closed(), 2)
                    assert second.close_code == 1013
    asyncio.run(scenario())


def test_synthetic_publisher_frames_validate():
    import random
    from fake_phone import frame as synthetic
    parsed = validate_lidar_frame(json.dumps(synthetic(4, "synthetic-session-1", random.Random(1))))
    assert parsed["source"] == "synthetic" and len(parsed["points"]) > 300


def test_accepts_the_exact_text_the_iphone_app_writes():
    # Mirrors WireFormat.message in ios-lidar/EchoSenseLiDAR/ScanPoint.swift.
    text = ('{"type":"lidar_frame","schema_version":1,"session_id":"0B6F2C1E-5D0A-4C55-9E0B-0C2E5B3D9A11",'
            '"device_id":"iphone-1A2B3C4D","sequence":12,"timestamp":51234.567,"source":"arkit_scene_depth",'
            '"coordinate_frame":"arkit_world","units":"meters","tracking":"normal",'
            '"camera_to_world":[0.99985,0.00000,-0.01745,0.00000,0.00000,1.00000,0.00000,0.00000,'
            '0.01745,0.00000,0.99985,0.00000,0.512,-0.031,-1.204,1.00000],'
            '"points":[[0.500,-1.200,-2.003],[-0.041,0.007,-0.950]],"confidences":[2,1]}')
    parsed = validate_lidar_frame(text)
    assert parsed["points"][1] == [-0.041, 0.007, -0.95] and parsed["camera_to_world"][12:15] == [0.512, -0.031, -1.204]
