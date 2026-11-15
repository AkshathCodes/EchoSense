"""Phone ingest -> viewer relay over real loopback sockets."""
import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from sonar_bridge.protocol import encode_lidar_ingest
from sonar_bridge.relay import LiveRelay, start_relay

ORIGIN = "http://localhost:5173"


def phone_frame(**changes):
    frame = {"type": "lidar_frame", "version": "0.1", "timestamp": 1.5, "sensor_id": "test-phone",
             "tracking": "normal", "reference": "sensor", "points": [[1.2, -0.3, 0.1, 2]]}
    frame.update(changes)
    return json.dumps(frame)


def url(server, path):
    return f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}{path}"


def test_ingest_wraps_points_in_viewer_envelope():
    message = json.loads(encode_lidar_ingest(phone_frame(), 4))
    assert message["type"] == "sonar_frame" and message["sequence"] == 4
    assert message["source"] == message["acquisition_source"] == "live"
    assert message["frame"]["points"] == [[1.2, -0.3, 0.1, 2]]
    assert message["frame"]["meta"]["modality"] == "lidar"
    assert message["frame"]["meta"]["reference"] == "sensor"
    assert message["detections"] is None


@pytest.mark.parametrize("bad", [
    "not json", "[]", phone_frame(type="sonar_frame"), phone_frame(version="9"),
    phone_frame(points=[[1, 2, 3]]), phone_frame(points=[[1, 2, 3, 5]]),
    phone_frame(points=[[1, 2, float("nan"), 1]]), phone_frame(tracking="great"),
    phone_frame(reference="moon"), phone_frame(timestamp="now"), phone_frame(extra=1),
    phone_frame(points=[[0, 0, 0, 1]] * 20_001)])
def test_ingest_rejects_malformed_frames(bad):
    with pytest.raises(ValueError):
        encode_lidar_ingest(bad, 0)


def test_phone_frames_reach_viewers_and_bad_frames_are_skipped():
    async def scenario():
        relay = LiveRelay()
        async with start_relay(relay, host="127.0.0.1", port=0) as server:
            async with connect(url(server, "/ws"), origin=ORIGIN, proxy=None) as viewer, \
                       connect(url(server, "/ingest"), proxy=None) as phone:
                await phone.send(phone_frame())
                first = json.loads(await asyncio.wait_for(viewer.recv(), 2))
                assert first["sequence"] == 0 and first["frame"]["meta"]["sensor_id"] == "test-phone"
                await phone.send("garbage")
                await phone.send(phone_frame(timestamp=2.0, reference="world"))
                second = json.loads(await asyncio.wait_for(viewer.recv(), 2))
                assert second["timestamp"] == 2.0 and second["frame"]["meta"]["reference"] == "world"
                assert relay.rejected == 1
                # A viewer that connects late still gets the most recent frame.
                async with connect(url(server, "/ws"), origin=ORIGIN, proxy=None) as late:
                    assert json.loads(await asyncio.wait_for(late.recv(), 2))["timestamp"] == 2.0
            for _ in range(100):
                if relay.viewers == 0 and relay.producer is None:
                    break
                await asyncio.sleep(0.01)
            assert relay.viewers == 0 and relay.producer is None
    asyncio.run(scenario())


def test_slow_viewer_skips_to_newest_frame():
    async def scenario():
        relay = LiveRelay()
        async with start_relay(relay, host="127.0.0.1", port=0) as server:
            async with connect(url(server, "/ingest"), proxy=None) as phone:
                for stamp in range(5):
                    await phone.send(phone_frame(timestamp=float(stamp)))
                while relay.sequence < 5:
                    await asyncio.sleep(0.01)
                async with connect(url(server, "/ws"), origin=ORIGIN, proxy=None) as viewer:
                    assert json.loads(await asyncio.wait_for(viewer.recv(), 2))["timestamp"] == 4.0
    asyncio.run(scenario())


@pytest.mark.parametrize("path, origin, status", [
    ("/ws", None, 403), ("/ws", "https://untrusted.example", 403),
    ("/ingest", ORIGIN, 403), ("/other", ORIGIN, 404)])
def test_relay_handshake_restrictions(path, origin, status):
    async def scenario():
        async with start_relay(LiveRelay(), host="127.0.0.1", port=0) as server:
            with pytest.raises(InvalidStatus) as error:
                async with connect(url(server, path), origin=origin, proxy=None):
                    pass
            assert error.value.response.status_code == status
    asyncio.run(scenario())


def test_second_phone_is_turned_away():
    async def scenario():
        async with start_relay(LiveRelay(), host="127.0.0.1", port=0) as server:
            async with connect(url(server, "/ingest"), proxy=None) as first:
                await first.send(phone_frame())
                async with connect(url(server, "/ingest"), proxy=None) as second:
                    await asyncio.wait_for(second.wait_closed(), 2)
                    assert second.close_code == 1013
    asyncio.run(scenario())


def test_accepts_the_exact_text_the_iphone_app_writes():
    # Mirrors WireFormat.message in ios/EchoSenseLiDAR/ScanPoint.swift: fixed two decimals.
    text = ('{"type":"lidar_frame","version":"0.1","timestamp":51234.50,"sensor_id":"iphone-lidar",'
            '"tracking":"limited","reference":"sensor","points":[[1.20,-0.05,0.00,2],[4.99,1.00,-1.31,0]]}')
    message = json.loads(encode_lidar_ingest(text, 0))
    assert message["frame"]["points"] == [[1.2, -0.05, 0.0, 2], [4.99, 1.0, -1.31, 0]]
    assert message["frame"]["meta"]["tracking"] == "limited"
