"""Synthetic loopback integration with original sonar and LiDAR services."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed,InvalidStatus
from sonar_bridge.range_adapter import Profile,ObservationBuilder
from sonar_bridge.range_server import RangeHub,RangeReplay,start_range_server
from sonar_bridge.range_processing import Policy
from sonar_bridge.range_recording import RangeRecorder,read_range_recording
from sonar_bridge.server import Bridge
from sonar_bridge.lidar import LidarHub
from sonar_bridge.sources import demo_messages
from test_lidar import frame as lidar_fixture
ORIGIN="http://127.0.0.1:4180"


def observations(lines=("1.01","timeout","0.99","1.02","1.00")):
    b=ObservationBuilder(Profile("synthetic-sensor"),session_id="synthetic-session",now_ms=lambda:1735689600000)
    return [b.line(line,"meters-line") for line in lines]


@asynccontextmanager
async def running(ranges,lidar=None):
    async with start_range_server(Bridge(demo_messages),ranges,lidar=lidar,port=0,origins=(ORIGIN,)) as server:
        yield f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"


async def receive(client,kind):
    async with asyncio.timeout(3):
        while True:
            message=json.loads(await client.recv())
            if message["type"]==kind: return message


async def until(predicate):
    for _ in range(100):
        if predicate(): return
        await asyncio.sleep(0.01)
    assert predicate()


def test_range_record_replay_and_original_sonar_lidar_coexist(tmp_path):
    async def scenario():
        path=tmp_path/"synthetic.jsonl"
        ranges=RangeHub(origins=(ORIGIN,),record=RangeRecorder(path,Policy()))
        lidar=LidarHub(origins=(ORIGIN,))
        originals=[]
        async with running(ranges,lidar) as url:
            async with connect(url+"/range/view",origin=ORIGIN,proxy=None) as viewer, connect(url+"/range/publish",proxy=None) as publisher:
                for o in observations():
                    await publisher.send(json.dumps(o))
                    got=await receive(viewer,"range_update")
                    assert got["observation"]==o and got["delivery"]=="synthetic"
                    originals.append(got)
                async with connect(url+"/ws",origin=ORIGIN,proxy=None) as sonar:
                    assert (await receive(sonar,"sonar_frame"))["source"]=="simulated"
                async with connect(url+"/lidar/view",origin=ORIGIN,proxy=None) as lv, connect(url+"/lidar/publish",proxy=None) as lp:
                    await lp.send(lidar_fixture(source="synthetic"))
                    assert (await receive(lv,"lidar_frame"))["points"]==json.loads(lidar_fixture())["points"]
        assert not ranges.viewers and not ranges.publishers
        policy,recorded=read_range_recording(path)
        assert recorded==observations() and policy==Policy()
        replay=RangeReplay(path,fps=30,origins=(ORIGIN,))
        async with running(replay) as url:
            for _ in range(2):
                async with connect(url+"/range/view",origin=ORIGIN,proxy=None) as viewer:
                    replayed=[await receive(viewer,"range_update") for _ in originals]
                    await viewer.wait_closed()
                    assert viewer.close_code==1000 and viewer.close_reason=="source complete"
                    assert replayed==[{**entry,"delivery":"replay"} for entry in originals]
    asyncio.run(scenario())


def test_duplicates_rejected_reconnect_and_sensor_identity():
    async def scenario():
        hub=RangeHub(origins=(ORIGIN,))
        async with running(hub) as url:
            async with connect(url+"/range/view",origin=ORIGIN,proxy=None) as viewer:
                async with connect(url+"/range/publish",proxy=None) as first:
                    await first.send(json.dumps(observations()[0])); await receive(viewer,"range_update")
                    async with connect(url+"/range/publish",proxy=None) as conflict:
                        await conflict.send(json.dumps(observations()[0])); await conflict.wait_closed()
                        assert conflict.close_code==1008
                await until(lambda:not hub.publishers)
                async with connect(url+"/range/publish",proxy=None) as second:
                    o={**observations()[0],"sequence":1}
                    await second.send(json.dumps(o)); assert (await receive(viewer,"range_update"))["observation"]["sequence"]==1
                    await second.send(json.dumps(o)); await second.wait_closed()
                    assert second.close_code==1008
        assert hub.accepted==2
    asyncio.run(scenario())


def test_multiple_sensors_and_bounded_viewers():
    async def scenario():
        hub=RangeHub(origins=(ORIGIN,),backlog=2)
        # Reuse original transport outbox; force slow-viewer pressure deterministically.
        from sonar_bridge.lidar import _Viewer
        slow=_Viewer(2); hub.viewers.add(slow)
        values=observations(tuple("1.0" for _ in range(20)))
        for o in values: await hub.accept(json.dumps(o))
        assert len(slow.outbox)==2 and hub.dropped==18
        second={**values[0],"sensor_id":"synthetic-other"}
        await hub.accept(json.dumps(second))
        assert len(hub.latest)==2
        hub.viewers.clear()
        async with running(hub) as url:
            async with connect(url+"/range/view",origin=ORIGIN,proxy=None) as a, connect(url+"/range/view",origin=ORIGIN,proxy=None) as b:
                assert (await receive(a,"range_update"))["observation"]["sensor_id"] in hub.latest
                assert (await receive(b,"range_update"))["observation"]["sensor_id"] in hub.latest
    asyncio.run(scenario())


@pytest.mark.parametrize("path,origin,status",[("/range/view",None,403),("/range/publish",ORIGIN,403),("/bad",ORIGIN,404)])
def test_range_access(path,origin,status):
    async def scenario():
        async with running(RangeHub(origins=(ORIGIN,))) as url:
            with pytest.raises(InvalidStatus) as error:
                async with connect(url+path,origin=origin,proxy=None): pass
            assert error.value.response.status_code==status
    asyncio.run(scenario())


def test_bad_recordings_and_no_overwrite(tmp_path):
    path=tmp_path/"test.jsonl"; recorder=RangeRecorder(path,Policy())
    for o in observations(): recorder.append(o)
    before=path.read_bytes()
    with pytest.raises(FileExistsError): RangeRecorder(path,Policy())
    assert path.read_bytes()==before
    with path.open("ab") as file: file.write(b"{truncated")
    with pytest.raises(ValueError): read_range_recording(path)


def test_recording_quota_does_not_forward(tmp_path):
    async def scenario():
        recorder=RangeRecorder(tmp_path/"small.jsonl",Policy(),max_bytes=250)
        hub=RangeHub(record=recorder)
        with pytest.raises(OSError): await hub.accept(json.dumps(observations()[0]))
        assert hub.accepted==0 and not hub.latest
    asyncio.run(scenario())
