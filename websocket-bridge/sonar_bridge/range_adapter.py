"""Model-agnostic serial/fixture adapter. No firmware, wiring or inferred pose.

Line input is explicitly selected. Only --serial with --hardware-verified may
claim hardware; fixtures are SYNTHETIC and stdin is manual. pyserial is optional.
"""
from __future__ import annotations
import argparse
import asyncio
from dataclasses import dataclass
import math
from pathlib import Path
import re
import sys
import time
import uuid
from typing import Any,AsyncIterator,Callable
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from .range_protocol import SCALES,ID,MODALITIES,encode,parse_json,validate,number,label

MAX_LINE=4096
DECIMAL=re.compile(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)\Z")


@dataclass(frozen=True)
class Profile:
    sensor_id:str
    model:str="NOT YET VERIFIED"
    modality:str="unknown"
    source:str="synthetic"
    transport:str="fixture"
    min_m:float=0.001
    max_m:float=50.0

    def __post_init__(self):
        if type(self.sensor_id) is not str or not ID.fullmatch(self.sensor_id): raise ValueError("invalid sensor ID")
        label(self.model)
        if self.modality not in MODALITIES: raise ValueError("invalid modality")
        allowed={"hardware":("serial","controller_rpc"),"manual":("manual",),"synthetic":("fixture","mock_serial")}
        if self.source not in allowed or self.transport not in allowed[self.source]: raise ValueError("invalid profile provenance")
        if self.source=="synthetic" and not self.sensor_id.startswith("synthetic-"): raise ValueError("synthetic sensor ID required")
        if self.source!="synthetic" and self.sensor_id.startswith("synthetic-"): raise ValueError("real/manual sensor cannot use synthetic ID")
        number(self.min_m,low=1e-12,high=100000); number(self.max_m,low=1e-12,high=100000)
        if not math.isfinite(self.min_m) or not math.isfinite(self.max_m) or not 0<self.min_m<self.max_m<=100000:
            raise ValueError("invalid sensor-specific limits")


class ObservationBuilder:
    def __init__(self,profile:Profile,*,session_id:str|None=None,now_ms:Callable[[],int]|None=None):
        self.profile=profile
        self.session=session_id or (("synthetic-" if profile.source=="synthetic" else "")+uuid.uuid4().hex)
        self.now_ms=now_ms or (lambda:int(time.time()*1000))
        self.sequence=0

    def event(self,status:str,*,raw:float|None=None,unit:str="m",timestamp:int|None=None,
              basis:str="host_receive_unix_ms",sequence:int|None=None,detail:str|None=None,quality:dict|None=None) -> dict:
        distance=raw*SCALES[unit] if raw is not None and unit in SCALES else None
        if status=="valid" and (distance is None or not self.profile.min_m<=distance<=self.profile.max_m):
            status="invalid"; detail="out_of_range"
        o={"type":"range_observation","schema_version":1,"session_id":self.session,
           "sensor_id":self.profile.sensor_id,"sensor_model":self.profile.model,"sensor_modality":self.profile.modality,
           "sequence":self.sequence if sequence is None else sequence,
           "capture_timestamp":self.now_ms() if timestamp is None else timestamp,"timestamp_basis":basis,
           "distance_m":distance if status=="valid" else None,"raw_distance":raw,"raw_unit":unit,
           "valid":status=="valid","timed_out":status=="timeout","status":status,
           "source":self.profile.source,"transport":self.profile.transport,
           "coordinate_frame":"unregistered","calibration_status":"unverified","sensor_pose":None,"quality":quality}
        if detail: o["status_detail"]=detail
        validate(o)
        self.sequence=max(self.sequence,o["sequence"]+1)
        return o

    def line(self,line:str,mode:str) -> dict:
        """Malformed input becomes an explicit invalid event, never a zero reading."""
        try:
            value=line.strip()
            if len(line.encode())>MAX_LINE: raise ValueError("line bound")
            if mode=="meters-line":
                if value=="timeout": return self.event("timeout",detail="device_timeout")
                if not DECIMAL.fullmatch(value): raise ValueError("expected positive decimal meters")
                raw=float(value)
                if not math.isfinite(raw) or raw<=0: raise ValueError("invalid range")
                return self.event("valid",raw=raw)
            if mode!="structured": raise ValueError("unknown line parser")
            item=parse_json(value)
            required={"distance","units","status"}
            optional={"sequence","timestamp","timestamp_basis","quality"}
            if type(item) is not dict or not required<=item.keys() or item.keys()-required-optional:
                raise ValueError("unexpected controller fields")
            if ("timestamp" in item)!=("timestamp_basis" in item): raise ValueError("timestamp needs basis")
            if item["units"] not in SCALES or item["status"] not in ("valid","timeout","no_return"):
                raise ValueError("unknown controller unit/status")
            raw=item["distance"]
            if item["status"]=="valid":
                if type(raw) not in (int,float) or not math.isfinite(raw) or raw<=0: raise ValueError("invalid range")
            elif raw is not None: raise ValueError("missing return needs null")
            return self.event(item["status"],raw=raw,unit=item["units"],timestamp=item.get("timestamp"),
                              basis=item.get("timestamp_basis","host_receive_unix_ms"),sequence=item.get("sequence"),quality=item.get("quality"))
        except (ValueError,TypeError,OverflowError,KeyError,UnicodeError):
            return self.event("invalid",unit="m" if mode=="meters-line" else "unknown",detail="malformed")


class LineFramer:
    """Bounded UTF-8 newline framing; discard oversize/timed-out tails through LF."""
    def __init__(self): self.buffer=bytearray(); self.discard=False

    def feed(self,data:bytes) -> list[str|None]:
        if len(data)>256: raise ValueError("serial chunks must be <=256 bytes")
        result=[]
        for byte in data:
            if self.discard:
                if byte==10: self.discard=False
                continue
            if byte==10:
                try: result.append(bytes(self.buffer).decode("utf-8"))
                except UnicodeError: result.append(None)
                self.buffer.clear()
            else:
                self.buffer.append(byte)
                if len(self.buffer)>MAX_LINE:
                    self.buffer.clear(); self.discard=True; result.append(None)
        return result

    def expire(self) -> bool:
        if self.buffer:
            self.buffer.clear(); self.discard=True; return True
        return False


class SerialSource:
    def __init__(self,profile:Profile,port:str,baud:int,mode:str,*,factory:Callable|None=None,
                 read_timeout:float=0.2,event_interval:float=1.0,reconnect_delay:float=0.5,hardware_verified:bool=False):
        if factory is None and not hardware_verified: raise ValueError("serial access requires explicit verified-hardware authorization")
        if not all(math.isfinite(v) for v in (read_timeout,event_interval,reconnect_delay)): raise ValueError("nonfinite timing")
        if not port or type(baud) is not int or not 1<=baud<=4000000: raise ValueError("explicit port and valid baud required")
        if not 0<read_timeout<=2 or event_interval<=0 or reconnect_delay<0: raise ValueError("invalid read/reconnect limits")
        self.profile=profile; self.port=port; self.baud=baud; self.mode=mode
        self.factory=factory; self.read_timeout=read_timeout; self.event_interval=event_interval; self.reconnect_delay=reconnect_delay

    def _open(self):
        if self.factory: return self.factory(self.port,self.baud,timeout=self.read_timeout)
        try: import serial
        except ImportError as exc: raise RuntimeError("Serial mode requires pip install -e '.[serial]'") from exc
        return serial.Serial(self.port,self.baud,timeout=self.read_timeout)

    async def observations(self,stop:asyncio.Event) -> AsyncIterator[dict]:
        builder=ObservationBuilder(self.profile)
        opened_once=False
        while not stop.is_set():
            serial=None; framer=LineFramer(); last=time.monotonic()
            try:
                serial=await asyncio.to_thread(self._open)
                if opened_once: builder=ObservationBuilder(self.profile)
                opened_once=True
                while not stop.is_set():
                    # At most one blocking read, <=256 bytes; no unbounded producer queue.
                    data=await asyncio.to_thread(serial.read,256)
                    now=time.monotonic()
                    for line in framer.feed(data):
                        if stop.is_set(): break
                        last=now
                        yield builder.event("invalid",unit="unknown",detail="malformed") if line is None else builder.line(line,self.mode)
                    if now-last>=self.event_interval:
                        partial=framer.expire(); last=now
                        yield builder.event("invalid" if partial else "timeout",unit="unknown",
                                            detail="line_timeout" if partial else "serial_timeout")
            except OSError:
                yield builder.event("disconnected",unit="unknown",detail="disconnected")
            finally:
                if serial is not None: await asyncio.to_thread(serial.close)
            if not stop.is_set():
                try: await asyncio.wait_for(stop.wait(),self.reconnect_delay)
                except TimeoutError: pass


async def send_observations(url:str,source,*,reconnect_delay:float=0.5) -> None:
    """Backpressure flows through awaited sends; no detached producer queue."""
    while True:
        stop=asyncio.Event()
        generator=source(stop)
        try:
            async with connect(url,proxy=None,compression=None,max_queue=2,write_limit=32768,close_timeout=2) as socket:
                async for observation in generator:
                    await asyncio.wait_for(socket.send(encode(observation)),5)
            return
        except (OSError,ConnectionClosed,TimeoutError):
            print("Range transport disconnected; reconnecting with a new acquisition session",file=sys.stderr,flush=True)
            await asyncio.sleep(reconnect_delay)
        finally:
            stop.set()
            await generator.aclose()


def hardware_gate(args) -> None:
    if not args.hardware_verified or not args.sensor_model or args.sensor_model.lower() in ("unknown","not yet verified"):
        raise ValueError("BLOCKED: exact sensor/controller datasheets and electrical compatibility must be verified; provide model and --hardware-verified")
    if args.baud is None or args.min_m is None or args.max_m is None or args.modality=="unknown":
        raise ValueError("hardware requires explicit baud, modality and datasheet-based min/max meters")


async def run(args) -> None:
    if args.serial:
        hardware_gate(args)
        profile=Profile(args.sensor_id,args.sensor_model,args.modality,"hardware","serial",args.min_m,args.max_m)
        serial=SerialSource(profile,args.serial,args.baud,args.format,hardware_verified=args.hardware_verified)
        await send_observations(args.url,serial.observations)
        return
    if not 0<args.fps<=30: raise ValueError("fixture FPS 0..30")
    source="manual" if args.stdin else "synthetic"
    sensor=args.sensor_id or ("manual-range" if args.stdin else "synthetic-range")
    profile=Profile(sensor,args.sensor_model or "NOT YET VERIFIED",args.modality,source,
                    "manual" if args.stdin else "fixture",args.min_m or 0.001,args.max_m or 50)
    sequence=0
    builder=ObservationBuilder(profile,now_ms=None if args.stdin else lambda:1735689600000+round(sequence*1000/args.fps))
    print("MANUAL observations" if args.stdin else "SYNTHETIC FIXTURE ONLY ? not physical sensor measurements",flush=True)
    file=sys.stdin if args.stdin else args.fixture.open("r",encoding="utf-8")
    try:
        async with connect(args.url,proxy=None,compression=None,write_limit=32768) as socket:
            sequence=0
            while line:=await asyncio.to_thread(file.readline,MAX_LINE+2):
                if len(line.encode())>MAX_LINE or not line.endswith("\n"):
                    raise ValueError("fixture/stdin requires bounded complete newline records")
                observation=builder.line(line,args.format)
                await socket.send(encode(observation))
                sequence+=1
                await asyncio.sleep(1/args.fps)
    finally:
        if not args.stdin: file.close()


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--serial",help="verified controller port; never auto-probe")
    modes.add_argument("--fixture",type=Path,help="SYNTHETIC development lines only; use --range-replay for genuine recordings")
    modes.add_argument("--stdin",action="store_true",help="manually entered observations")
    parser.add_argument("--format",required=True,choices=("meters-line","structured"))
    parser.add_argument("--url",default="ws://127.0.0.1:8765/range/publish")
    parser.add_argument("--sensor-id")
    parser.add_argument("--sensor-model")
    parser.add_argument("--modality",default="unknown",choices=("ultrasonic","optical_tof","radar","other","unknown"))
    parser.add_argument("--baud",type=int)
    parser.add_argument("--min-m",type=float)
    parser.add_argument("--max-m",type=float)
    parser.add_argument("--fps",type=float,default=5)
    parser.add_argument("--hardware-verified",action="store_true")
    args=parser.parse_args()
    if args.serial and not args.sensor_id: parser.error("--serial requires --sensor-id")
    try: asyncio.run(run(args))
    except KeyboardInterrupt: pass
    except (ValueError,RuntimeError,OSError) as exc: parser.exit(2,f"Range adapter: {exc}\n")


if __name__=="__main__": main()
