"""Real loopback WebSocket lifecycle tests, no hardware or frontend."""
import asyncio
import json
import time

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from sonar_bridge.server import Bridge, start_server
from sonar_bridge.sources import demo_messages

ORIGIN = "http://localhost:5173"


def url(server, path="/ws"):
    return f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}{path}"


async def wait_released(bridge):
    for _ in range(100):
        if bridge.active_clients == 0:
            return
        await asyncio.sleep(0.01)
    assert bridge.active_clients == 0


def test_stream_pacing_disconnect_and_reconnect():
    async def scenario():
        bridge = Bridge(demo_messages, fps=10)
        async with start_server(bridge, port=0) as server:
            assert server.sockets[0].getsockname()[0] == "127.0.0.1"
            async with connect(url(server), origin=ORIGIN, proxy=None) as client:
                start = time.monotonic()
                messages = [json.loads(await asyncio.wait_for(client.recv(), 2)) for _ in range(3)]
                assert time.monotonic() - start >= 0.15
                assert [m["sequence"] for m in messages] == [0, 1, 2]
                assert all(m["source"] == "simulated" for m in messages)
            await wait_released(bridge)
            async with connect(url(server), origin=ORIGIN, proxy=None) as client:
                assert json.loads(await client.recv())["sequence"] == 0
            await wait_released(bridge)
    asyncio.run(scenario())


@pytest.mark.parametrize("path, origin, status", [("/other", ORIGIN, 404), ("/ws?x=1", ORIGIN, 404),
                                                   ("/ws", "https://untrusted.example", 403),
                                                   ("/ws", None, 403), ("/ws", "null", 403)])
def test_handshake_restrictions(path, origin, status):
    async def scenario():
        async with start_server(Bridge(demo_messages), port=0) as server:
            with pytest.raises(InvalidStatus) as error:
                async with connect(url(server, path), origin=origin, proxy=None):
                    pass
            assert error.value.response.status_code == status
    asyncio.run(scenario())


def test_explicit_no_origin_opt_in():
    async def scenario():
        async with start_server(Bridge(demo_messages), port=0, allow_no_origin=True) as server:
            async with connect(url(server), proxy=None) as client:
                assert json.loads(await client.recv())["source"] == "simulated"
    asyncio.run(scenario())


def test_source_completion_and_cleanup():
    closed = []
    def source():
        try:
            yield next(demo_messages())
        finally:
            closed.append(True)
    async def scenario():
        bridge = Bridge(source, fps=30)
        async with start_server(bridge, port=0) as server:
            async with connect(url(server), origin=ORIGIN, proxy=None) as client:
                await client.recv()
                with pytest.raises(ConnectionClosed) as error:
                    await client.recv()
                assert error.value.rcvd.code == 1000
            await wait_released(bridge)
        assert closed == [True]
    asyncio.run(scenario())


def test_invalid_source_closes_without_payload():
    def source():
        raise ValueError("invalid private input")
        yield
    async def scenario():
        bridge = Bridge(source)
        async with start_server(bridge, port=0) as server:
            async with connect(url(server), origin=ORIGIN, proxy=None) as client:
                with pytest.raises(ConnectionClosed) as error:
                    await client.recv()
                assert error.value.rcvd.code == 1011
                assert error.value.rcvd.reason == "source rejected"
            await wait_released(bridge)
    asyncio.run(scenario())


def test_client_capacity():
    async def scenario():
        bridge = Bridge(demo_messages, max_clients=1)
        async with start_server(bridge, port=0) as server:
            async with connect(url(server), origin=ORIGIN, proxy=None) as first:
                await first.recv()
                async with connect(url(server), origin=ORIGIN, proxy=None) as second:
                    with pytest.raises(ConnectionClosed) as error:
                        await second.recv()
                    assert error.value.rcvd.code == 1013
                assert bridge.active_clients == 1
            await wait_released(bridge)
    asyncio.run(scenario())


def test_slow_consumer_closed_and_source_released():
    # Deterministically exercise send timeout without relying on OS buffer sizes.
    class SlowConnection:
        def __init__(self):
            self.closed = asyncio.Event()
            self.code = None
        async def send(self, message):
            await self.closed.wait()
        async def close(self, code, reason):
            self.code = code
            self.closed.set()
    async def scenario():
        bridge = Bridge(demo_messages, send_timeout=0.01)
        connection = SlowConnection()
        await bridge.handler(connection)
        assert connection.code == 1013
        assert bridge.active_clients == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("fps", [0, -1, 31, float("nan"), float("inf")])
def test_invalid_pacing(fps):
    with pytest.raises(ValueError):
        Bridge(demo_messages, fps=fps)


def test_server_shutdown_closes_connected_client():
    async def scenario():
        bridge = Bridge(demo_messages)
        async with start_server(bridge, port=0) as server:
            client = await connect(url(server), origin=ORIGIN, proxy=None)
            await client.recv()
        with pytest.raises(ConnectionClosed) as error:
            await client.recv()
        assert error.value.rcvd.code == 1001
        assert bridge.active_clients == 0
        await client.close()
    asyncio.run(scenario())


def test_bad_recording_error_is_sanitized():
    import zipfile
    def source():
        raise zipfile.BadZipFile("private path or captured contents")
        yield
    async def scenario():
        bridge = Bridge(source)
        async with start_server(bridge, port=0) as server:
            async with connect(url(server), origin=ORIGIN, proxy=None) as client:
                with pytest.raises(ConnectionClosed) as error:
                    await client.recv()
                assert error.value.rcvd.code == 1011
                assert error.value.rcvd.reason == "source rejected"
            await wait_released(bridge)
    asyncio.run(scenario())
