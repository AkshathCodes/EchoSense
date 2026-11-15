"""Bounded per-sensor statistics, not an accuracy/confidence estimator.

Median, >=3 valid majority and <=0.35m spread follow acoustic/map.mjs and
acoustic/aggregate.py. Optional residual filtering is explicit and reports counts.
"""
from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
from collections import deque
import statistics
from typing import Any
from .range_protocol import number,validate


@dataclass(frozen=True)
class Policy:
    window_size: int=5
    min_valid: int=3
    max_spread_m: float=0.35
    outlier_m: float|None=None
    reference_m: float|None=None

    def __post_init__(self):
        if type(self.window_size) is not int or not 1<=self.window_size<=101: raise ValueError("window size 1..101")
        if type(self.min_valid) is not int or not 1<=self.min_valid<=self.window_size: raise ValueError("min_valid outside window")
        number(self.max_spread_m,high=100000)
        for value in (self.outlier_m,self.reference_m):
            if value is not None: number(value,low=1e-12,high=100000)


class RangeProcessor:
    def __init__(self,policy: Policy=Policy()) -> None:
        self.policy=policy
        self.windows: dict[tuple[str,str],deque]= {}
        self.last: dict[tuple[str,str],dict]= {}
        self.current: dict[str,tuple[str,str]]= {}
        self.retired:set[tuple[str,str]]=set()

    def check(self,o:dict) -> tuple[str,str]:
        validate(o)
        key=(o["sensor_id"],o["session_id"])
        if key in self.retired: raise ValueError("retired range session")
        previous=self.last.get(key)
        if previous:
            if o["sequence"]<=previous["sequence"] or o["capture_timestamp"]<previous["capture_timestamp"]:
                raise ValueError("range order/timestamp regression")
            for field in ("sensor_model","sensor_modality","source","transport","timestamp_basis","coordinate_frame","calibration_status","sensor_pose"):
                if o.get(field)!=previous.get(field): raise ValueError("sensor identity/calibration changed without new session")
        elif len(self.last)>=128 or (o["sensor_id"] not in self.current and len(self.current)>=32):
            raise ValueError("range stream/session limit")
        return key

    def add(self,o:dict[str,Any]) -> dict[str,Any]:
        key=self.check(o)
        o=deepcopy(o)
        old=self.current.get(o["sensor_id"])
        if old and old!=key: self.retired.add(old)
        self.current[o["sensor_id"]]=key
        window=self.windows.setdefault(key,deque(maxlen=self.policy.window_size))
        window.append(o)
        self.last[key]=o
        values=[item["distance_m"] for item in window if item["valid"]]
        raw_spread=max(values)-min(values) if len(values)>=2 else None
        center=statistics.median(values) if values else None
        inliers=values if self.policy.outlier_m is None else [v for v in values if abs(v-center)<=self.policy.outlier_m]
        spread=max(inliers)-min(inliers) if len(inliers)>=2 else None
        available=(o["valid"] and len(inliers)>=self.policy.min_valid and len(inliers)>len(window)/2
                   and (spread is None or spread<=self.policy.max_spread_m))
        estimate=statistics.median(inliers) if available else None
        return {"sample_count":len(window),"valid_count":len(values),
                "missing_count":sum(item["status"] in ("timeout","no_return") for item in window),
                "invalid_count":sum(item["status"] in ("invalid","disconnected") for item in window),
                "outlier_count":len(values)-len(inliers),"median_m":estimate,"spread_m":spread,
                "raw_spread_m":raw_spread,"available":bool(available),"reference_m":self.policy.reference_m,
                "absolute_error_m":abs(estimate-self.policy.reference_m) if estimate is not None and self.policy.reference_m is not None else None}
