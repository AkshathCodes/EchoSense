"""Mock serial only: exact electrical hardware remains BLOCKED."""
import asyncio
import json
from types import SimpleNamespace
import pytest
from sonar_bridge.range_adapter import Profile,ObservationBuilder,SerialSource,LineFramer,hardware_gate


def builder(): return ObservationBuilder(Profile("synthetic-mock",transport="mock_serial"),now_ms=lambda:1735689600000)


@pytest.mark.parametrize("line",["nan","inf","-1","0","","150 cm","1e3","{bad}"])
def test_invalid_is_not_zero(line):
    o=builder().line(line,"meters-line")
    assert o["status"]=="invalid" and o["distance_m"] is None


def test_limits_and_controller_clock_preserved():
    b=ObservationBuilder(Profile("synthetic-test",min_m=0.5,max_m=4),now_ms=lambda:1735689600000)
    assert b.line("0.2","meters-line")["status_detail"]=="out_of_range"
    o=b.line('{"distance":200,"units":"cm","status":"valid","timestamp":25,"timestamp_basis":"device_monotonic_ms","sequence":4}',"structured")
    assert o["raw_distance"]==200 and o["distance_m"]==2 and o["capture_timestamp"]==25
    assert b.line('{"distance":1,"units":"feet","status":"valid"}',"structured")["distance_m"] is None


def test_chunk_boundaries_and_oversize_resynchronization():
    f=LineFramer()
    assert f.feed(b"1.")==[]
    assert f.feed(b"2\r\ntimeout\n")==["1.2\r","timeout"]
    invalid=[]
    for _ in range(17): invalid+=f.feed(b"x"*256)
    assert invalid==[None] and len(f.buffer)==0
    assert f.feed(b"tail\n1.0\n")==["1.0"]
    f.feed(b"1."); assert f.expire()
    assert f.feed(b"2\n3.0\n")==["3.0"]


class MockSerial:
    def __init__(self,chunks): self.chunks=iter(chunks); self.closed=False
    def read(self,size):
        assert size==256
        item=next(self.chunks,b"")
        if isinstance(item,Exception): raise item
        return item
    def close(self): self.closed=True


def test_serial_disconnect_reconnect_new_session_and_cleanup():
    async def scenario():
        ports=[MockSerial([b"1.",b"2\n",OSError("unplugged")]),MockSerial([b"1.3\n"])]
        pending=iter(ports)
        source=SerialSource(Profile("synthetic-usb",transport="mock_serial"),"MOCK",9600,"meters-line",
                            factory=lambda *a,**kw:next(pending),reconnect_delay=0)
        stop=asyncio.Event(); results=[]
        async for o in source.observations(stop):
            results.append(o)
            if len(results)==3: stop.set()
        assert [o["status"] for o in results]==["valid","disconnected","valid"]
        assert results[0]["session_id"]!=results[2]["session_id"]
        assert all(p.closed for p in ports)
    asyncio.run(scenario())


def test_serial_timeout_event_is_not_an_echo():
    async def scenario():
        port=MockSerial([])
        source=SerialSource(Profile("synthetic-usb",transport="mock_serial"),"MOCK",9600,"meters-line",
                            factory=lambda *a,**kw:port,event_interval=0.001)
        stop=asyncio.Event()
        async for o in source.observations(stop):
            assert o["status"]=="timeout" and o["distance_m"] is None and o["timestamp_basis"]=="host_receive_unix_ms"
            stop.set()
        assert port.closed
    asyncio.run(scenario())


def test_real_serial_requires_verification_before_any_open():
    with pytest.raises(ValueError): SerialSource(Profile("sensor",source="hardware",transport="serial"),"COM999",9600,"meters-line")
    args=SimpleNamespace(hardware_verified=False,sensor_model=None,baud=None,min_m=None,max_m=None,modality="unknown")
    with pytest.raises(ValueError,match="BLOCKED"): hardware_gate(args)
