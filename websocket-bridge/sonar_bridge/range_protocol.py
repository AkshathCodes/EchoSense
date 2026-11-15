"""Independent range_observation v1. A distance is NOT a measured 3D point."""
from __future__ import annotations
import json
import math
import re
from typing import Any

MAX_BYTES=8192
MAX_SEQUENCE=2**53-1
REQUIRED={"type","schema_version","session_id","sensor_id","sensor_model","sensor_modality",
          "sequence","capture_timestamp","timestamp_basis","distance_m","raw_distance","raw_unit",
          "valid","timed_out","status","source","transport","coordinate_frame","calibration_status"}
OPTIONAL={"sensor_pose","quality","status_detail"}
STATUSES=("valid","timeout","no_return","invalid","disconnected")
MODALITIES=("ultrasonic","optical_tof","radar","other","unknown")
SCALES={"m":1.0,"cm":0.01,"mm":0.001}
ID=re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")


def number(value: Any, *, low: float=0, high: float=1e9) -> None:
    if type(value) not in (int,float): raise ValueError("expected finite number")
    try: good=math.isfinite(value) and low<=value<=high
    except OverflowError: good=False
    if not good: raise ValueError("number outside finite bounds")


def label(value: Any, limit: int=80) -> None:
    if type(value) is not str or not 0<len(value)<=limit or not value.isprintable():
        raise ValueError("invalid text label")


def validate(observation: Any) -> dict[str,Any]:
    o=observation
    if type(o) is not dict or not REQUIRED<=o.keys() or o.keys()-REQUIRED-OPTIONAL:
        raise ValueError("missing or unexpected range fields")
    if o["type"]!="range_observation" or type(o["schema_version"]) is not int or o["schema_version"]!=1:
        raise ValueError("unsupported range version")
    for key in ("session_id","sensor_id","coordinate_frame"):
        if type(o[key]) is not str or not ID.fullmatch(o[key]): raise ValueError("invalid identity/frame")
    label(o["sensor_model"])
    if o["sensor_modality"] not in MODALITIES: raise ValueError("unknown modality")
    if type(o["sequence"]) is not int or not 0<=o["sequence"]<=MAX_SEQUENCE: raise ValueError("invalid sequence")
    if type(o["capture_timestamp"]) is not int or not 0<=o["capture_timestamp"]<=MAX_SEQUENCE:
        raise ValueError("invalid timestamp")
    if o["timestamp_basis"] not in ("unix_ms","host_receive_unix_ms","device_monotonic_ms"):
        raise ValueError("timestamp basis required")
    if o["timestamp_basis"]!="device_monotonic_ms" and not 946684800000<=o["capture_timestamp"]<=4102444800000:
        raise ValueError("expected Unix epoch milliseconds, 2000..2100")
    transports={"hardware":("serial","controller_rpc"),"manual":("manual",),"synthetic":("fixture","mock_serial")}
    if type(o["source"]) is not str or o["source"] not in transports or o["transport"] not in transports[o["source"]]:
        raise ValueError("invalid acquisition provenance")
    prefixes=[o[k].startswith("synthetic-") for k in ("sensor_id","session_id")]
    if (o["source"]=="synthetic" and not all(prefixes)) or (o["source"]!="synthetic" and any(prefixes)):
        raise ValueError("synthetic provenance/IDs disagree")
    if o["status"] not in STATUSES or type(o["valid"]) is not bool or type(o["timed_out"]) is not bool:
        raise ValueError("invalid availability status")
    if o["valid"]!=(o["status"]=="valid") or o["timed_out"]!=(o["status"]=="timeout"):
        raise ValueError("inconsistent validity/timeout flags")
    if o["raw_unit"] not in (*SCALES,"unknown"): raise ValueError("unsupported raw unit")
    if o["raw_distance"] is not None:
        number(o["raw_distance"],low=1e-12)
        if o["raw_unit"]=="unknown": raise ValueError("raw reading needs units")
    if o["valid"]:
        number(o["distance_m"],low=1e-12,high=100000)
        if o["raw_distance"] is None or not math.isclose(o["distance_m"],o["raw_distance"]*SCALES[o["raw_unit"]],rel_tol=1e-9,abs_tol=1e-12):
            raise ValueError("distance/raw unit mismatch")
    elif o["distance_m"] is not None:
        raise ValueError("invalid/missing returns must not become numeric distances")
    if o["status"] in ("timeout","no_return","disconnected") and o["raw_distance"] is not None:
        raise ValueError("missing readings must have null raw range")
    pose=o.get("sensor_pose")
    if o["calibration_status"]=="unverified":
        if pose is not None or o["coordinate_frame"]!="unregistered":
            raise ValueError("unknown alignment cannot carry a spatial pose")
    elif o["calibration_status"]=="pose_verified":
        if type(pose) is not dict or set(pose)!={"position_m","direction_unit","calibration_id"} or o["coordinate_frame"]=="unregistered":
            raise ValueError("verified pose requires calibration/frame")
        label(pose["calibration_id"])
        for key in ("position_m","direction_unit"):
            if type(pose[key]) is not list or len(pose[key])!=3: raise ValueError("pose vectors require 3 values")
            for value in pose[key]: number(value,low=-10000,high=10000)
        if abs(sum(x*x for x in pose["direction_unit"])-1)>1e-6: raise ValueError("beam direction must be unit length")
    else: raise ValueError("invalid calibration status")
    if o.get("quality") is not None:
        q=o["quality"]
        if type(q) is not dict or set(q)!={"name","value","units"}: raise ValueError("invalid optional quality")
        label(q["name"],64); label(q["units"],32); number(q["value"],low=-1e12,high=1e12)
    if "status_detail" in o:
        if o["status_detail"] not in ("malformed","out_of_range","serial_timeout","line_timeout","disconnected","device_timeout","no_return"):
            raise ValueError("unknown status detail")
    return o


def _pairs(items):
    result={}
    for key,value in items:
        if key in result: raise ValueError("duplicate JSON key")
        result[key]=value
    return result


def parse_json(text: str) -> Any:
    if type(text) is not str or len(text.encode("utf-8"))>MAX_BYTES: raise ValueError("range message too large/not text")
    def reject(value): raise ValueError("nonfinite JSON")
    try: return json.loads(text,object_pairs_hook=_pairs,parse_constant=reject)
    except (RecursionError,UnicodeError,OverflowError) as exc: raise ValueError("invalid JSON") from exc


def decode(text: str) -> dict[str,Any]: return validate(parse_json(text))


def encode(observation: dict[str,Any]) -> str:
    text=json.dumps(validate(observation),allow_nan=False,separators=(",",":"))
    if len(text.encode())>MAX_BYTES: raise ValueError("range message too large")
    return text
