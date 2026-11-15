"""Exclusive, bounded range JSONL recordings with processing-policy provenance."""
from __future__ import annotations
from dataclasses import asdict
import json
from pathlib import Path
from .range_processing import Policy,RangeProcessor
from .range_protocol import MAX_BYTES,decode,encode,parse_json
MAX_FILE_BYTES=16*1024*1024
MAX_RECORDS=10000


class RangeRecorder:
    def __init__(self,path:Path,policy:Policy,*,max_bytes:int=MAX_FILE_BYTES):
        if not 1<=max_bytes<=MAX_FILE_BYTES: raise ValueError("invalid capture byte limit")
        self.path=path.resolve()
        self.max_bytes=max_bytes
        self.count=0
        if path.is_symlink(): raise ValueError("recording symlinks not supported")
        header=json.dumps({"type":"range_recording","schema_version":1,"processing":asdict(policy)},allow_nan=False,separators=(",",":"))+"\n"
        if len(header.encode())>max_bytes: raise ValueError("recording quota smaller than header")
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open("x",encoding="utf-8",newline="\n") as file: file.write(header)
        self.bytes=len(header.encode())

    def append(self,o:dict) -> None:
        data=(encode(o)+"\n").encode()
        if self.count>=MAX_RECORDS or self.bytes+len(data)>self.max_bytes: raise OSError("range recording quota reached")
        with self.path.open("ab") as file: file.write(data); file.flush()
        self.bytes+=len(data); self.count+=1


def read_range_recording(path:Path) -> tuple[Policy,list[dict]]:
    if path.stat().st_size>MAX_FILE_BYTES: raise ValueError("range recording too large")
    with path.open("rb") as file:
        line=file.readline(MAX_BYTES+2)
        if not line.endswith(b"\n"): raise ValueError("incomplete range header")
        header=parse_json(line.decode())
        if type(header) is not dict or set(header)!={"type","schema_version","processing"} or header["type"]!="range_recording" or type(header["schema_version"]) is not int or header["schema_version"]!=1:
            raise ValueError("unknown range recording")
        if type(header["processing"]) is not dict or set(header["processing"])!={"window_size","min_valid","max_spread_m","outlier_m","reference_m"}:
            raise ValueError("invalid saved range policy")
        policy=Policy(**header["processing"])
        checker=RangeProcessor(policy)
        frames=[]; total=len(line)
        while line:=file.readline(MAX_BYTES+2):
            total+=len(line)
            if total>MAX_FILE_BYTES or len(frames)>=MAX_RECORDS or not line.endswith(b"\n"):
                raise ValueError("range recording bounds/incomplete line")
            o=decode(line.decode())
            checker.add(o)
            frames.append(o)
        if not frames: raise ValueError("empty range recording")
    return policy,frames
