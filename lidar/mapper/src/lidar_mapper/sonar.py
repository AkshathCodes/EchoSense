"""HC-SR04 ultrasonic range sensor alongside the LiDAR: cross-check and sonar-only surfaces.

The sensor is fixed to the phone and points the same way as the LiDAR. It is
read over USB serial from a microcontroller (hardware/hcsr04/ at the repo
root): one line per ping, the distance in meters ("1.234") or "timeout".

What it adds. An ultrasonic ping reflects from glass, mirrors and other
surfaces that LiDAR light passes through or bounces off, and it is not
affected by darkness, smoke or fog. So for every depth frame this module
compares the sonar range with the LiDAR depths inside the sonar's cone:

  agree            sonar matches the nearest LiDAR surface in the cone
  sonar_closer     sonar hears something clearly nearer than LiDAR sees
  lidar_no_return  LiDAR has almost nothing in the cone but sonar has an echo
  sonar_farther    LiDAR sees something nearer than the sonar echo (soft or
                   angled surfaces often send no echo back)
  no_sonar         no fresh, in-range sonar reading

`sonar_closer` and `lidar_no_return`, held for a few frames in a row, are
recorded as a sonar-only surface: one point on the camera axis at the sonar
range. The real reflector can be anywhere in the cone, so that point is
accurate in range and only approximate sideways (range x tan(half angle)).

Limits: one reading per ping, about 15 a second, 0.03 to 4 m. The sonar does
not improve the 3D map or the phone's position.
"""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field

import numpy as np

MIN_RANGE = 0.03   # m; the HC-SR04 cannot time echoes closer than about 2 cm
MAX_RANGE = 4.0    # m; beyond this the echo is too weak to trust
STATES = ("no_sonar", "agree", "sonar_closer", "lidar_no_return", "sonar_farther")


def parse_line(line: str) -> float | None:
    """One serial line -> meters, or None for 'timeout' and anything unreadable."""
    text = line.strip()
    if not text or text == "timeout":
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def cone_ranges(depth: np.ndarray, K: np.ndarray, half_angle_deg: float, offset_deg=(0.0, 0.0),
                max_range: float = 4.5) -> tuple[np.ndarray, float]:
    """LiDAR ranges (along each ray, meters) inside the sonar cone, and the fraction of cone pixels with a return.

    `offset_deg` is the sonar axis relative to the camera axis as (right, down) degrees.
    """
    h, w = depth.shape
    v, u = np.mgrid[0:h, 0:w]
    x = (u - K[0, 2]) / K[0, 0]
    y = (v - K[1, 2]) / K[1, 1]
    ax, ay = math.tan(math.radians(offset_deg[0])), math.tan(math.radians(offset_deg[1]))
    # Angle between each pixel ray and the sonar axis.
    dot = (x * ax + y * ay + 1) / (np.sqrt(x * x + y * y + 1) * math.sqrt(ax * ax + ay * ay + 1))
    cone = np.arccos(np.clip(dot, -1, 1)) <= math.radians(half_angle_deg)
    d = depth[cone]
    ok = np.isfinite(d) & (d > 0.05) & (d <= max_range)
    scale = np.sqrt(x[cone] ** 2 + y[cone] ** 2 + 1)[ok]
    return d[ok] * scale, float(ok.mean()) if cone.any() else 0.0


def compare(sonar_m: float | None, ranges: np.ndarray, valid_fraction: float) -> dict:
    """Classify one sonar reading against the LiDAR ranges in its cone. Pure function."""
    result = {"state": "no_sonar", "range_m": None, "lidar_near_m": None, "lidar_median_m": None}
    if len(ranges) >= 20:
        # The sonar reports the nearest strong reflector, so compare with the near edge of the cone.
        result["lidar_near_m"] = round(float(np.percentile(ranges, 10)), 3)
        result["lidar_median_m"] = round(float(np.median(ranges)), 3)
    if sonar_m is None or not MIN_RANGE <= sonar_m <= MAX_RANGE:
        return result
    result["range_m"] = round(float(sonar_m), 3)
    near, median = result["lidar_near_m"], result["lidar_median_m"]
    if near is None or valid_fraction < 0.2:
        result["state"] = "lidar_no_return"
        return result
    tolerance = max(0.10, 0.08 * sonar_m)   # what a wall test should achieve; reported, not enforced
    if sonar_m < near - max(0.25, 0.15 * near):
        result["state"] = "sonar_closer"
    elif sonar_m > median + max(0.25, 0.15 * median):
        result["state"] = "sonar_farther"
    else:
        # Within the margins, including the band that is too close to call either way.
        result["state"] = "agree"
    result["agrees_within_m"] = round(tolerance, 3)
    return result


def person_range(sonar_m: float | None, depth: np.ndarray, K: np.ndarray, R: np.ndarray, t: np.ndarray,
                 boxes: list[dict], half_angle_deg: float = 10.0, offset_deg=(0.0, 0.0),
                 min_share: float = 0.15, front_margin: float = 0.15) -> dict:
    """Is the sonar reading the distance to a detected person? Pure function.

    `boxes` are detections in world metres ({"min": [x, y, z], "max": [...]}); R, t are world <- camera.
    The sonar hears the nearest strong reflector anywhere in its cone, so its reading is only the
    distance to a person when the person fills a fair share of the cone AND nothing in the cone is
    clearly nearer than them. Otherwise the reading cannot be assigned to the person.

      no_person   no detection box is inside the cone
      ambiguous   a person is in the cone but so is something nearer, or they fill too little of it
      person      the person is the nearest thing in the cone: `range_m` is the distance to them
                  (the sonar reading when there is one, else the LiDAR range)
    """
    h, w = depth.shape
    v, u = np.mgrid[0:h, 0:w]
    x = (u - K[0, 2]) / K[0, 0]
    y = (v - K[1, 2]) / K[1, 1]
    ax, ay = math.tan(math.radians(offset_deg[0])), math.tan(math.radians(offset_deg[1]))
    dot = (x * ax + y * ay + 1) / (np.sqrt(x * x + y * y + 1) * math.sqrt(ax * ax + ay * ay + 1))
    cone = (np.arccos(np.clip(dot, -1, 1)) <= math.radians(half_angle_deg)) & np.isfinite(depth) & (depth > 0.05)
    out = {"state": "no_person", "range_m": None, "source": None, "sonar_m": None, "lidar_person_m": None,
           "lidar_nearest_m": None, "cone_share": 0.0}
    if sonar_m is not None and MIN_RANGE <= sonar_m <= MAX_RANGE:
        out["sonar_m"] = round(float(sonar_m), 3)
    if cone.sum() < 20 or not boxes:
        return out
    d = depth[cone]
    cam = np.stack([x[cone] * d, y[cone] * d, d], -1)
    ranges = np.linalg.norm(cam, axis=1)
    world = cam @ np.asarray(R).T + np.asarray(t)
    nearest = float(np.percentile(ranges, 10))
    out["lidar_nearest_m"] = round(nearest, 3)
    best = None
    for box in boxes:
        inside = np.all((world >= np.asarray(box["min"]) - 0.05) & (world <= np.asarray(box["max"]) + 0.05), axis=1)
        share = float(inside.mean())
        if inside.sum() >= 20 and (best is None or share > best[0]):
            best = (share, float(np.percentile(ranges[inside], 10)), float(np.median(ranges[inside])))
    if best is None:
        return out
    share, person_near, person_median = best
    out.update(cone_share=round(share, 2), lidar_person_m=round(person_median, 3))
    if share < min_share or person_near > nearest + front_margin:
        out["state"] = "ambiguous"
        return out
    out["state"] = "person"
    if out["sonar_m"] is not None:
        out.update(range_m=out["sonar_m"], source="sonar")
    else:
        out.update(range_m=round(person_near, 3), source="lidar")
    return out


@dataclass
class SonarFusion:
    """Holds the newest sonar reading and turns each depth frame into a status and, sometimes, a surface point."""
    half_angle_deg: float = 10.0          # HC-SR04 effective beam is roughly +-7.5 to +-15 degrees
    offset_deg: tuple = (0.0, 0.0)        # sonar axis vs camera axis: (right, down) degrees
    mount_m: tuple = (0.0, 0.0, 0.0)      # sonar position in the camera frame: right, down, forward (m)
    max_age: float = 0.35                 # s; older readings are ignored
    persist: int = 3                      # consecutive frames before a sonar-only surface is recorded
    synthetic: bool = False               # True when readings are simulated, never from hardware
    surface: list = field(default_factory=list)   # world points (x, y, z) of sonar-only surfaces
    status: dict = field(default_factory=lambda: {"state": "no_sonar"})
    readings: int = 0

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._range: float | None = None
        self._at = -math.inf
        self._streak: list[float] = []
        self._cells: set = set()
        self.sidecar = None

    def update(self, range_m: float | None, at: float | None = None) -> None:
        """Called by the serial reader (any thread) with each ping result."""
        with self._lock:
            self._range, self._at = range_m, time.monotonic() if at is None else at
            self.readings += 1

    def latest(self, now: float | None = None) -> tuple[float | None, float]:
        with self._lock:
            age = (time.monotonic() if now is None else now) - self._at
            return (self._range if age <= self.max_age else None), age

    def observe(self, depth: np.ndarray, K: np.ndarray, R: np.ndarray, t: np.ndarray, tracking: bool,
                seq: int = 0, now: float | None = None) -> dict:
        """Compare the newest reading with one depth frame. R, t are world <- camera (OpenCV)."""
        sonar_m, age = self.latest(now)
        ranges, valid = cone_ranges(depth, K, self.half_angle_deg, self.offset_deg)
        status = compare(sonar_m, ranges, valid)
        status["age_ms"] = None if not math.isfinite(age) else int(age * 1000)
        if self.sidecar is not None:
            self.sidecar.write(json.dumps({"seq": seq, "range_m": sonar_m}) + "\n")
            self.sidecar.flush()
        blind = status["state"] in ("sonar_closer", "lidar_no_return")
        # Only steady readings count: three in a row within 10 cm of each other.
        self._streak = self._streak + [sonar_m] if blind else []
        if (blind and tracking and len(self._streak) >= self.persist
                and max(self._streak[-self.persist:]) - min(self._streak[-self.persist:]) <= 0.10):
            ax, ay = math.tan(math.radians(self.offset_deg[0])), math.tan(math.radians(self.offset_deg[1]))
            axis = np.array([ax, ay, 1.0]) / math.sqrt(ax * ax + ay * ay + 1)
            point = R @ (np.asarray(self.mount_m, float) + axis * sonar_m) + t
            cell = tuple(np.floor(point / 0.10).astype(int))
            if cell not in self._cells and len(self.surface) < 2000:
                self._cells.add(cell)
                self.surface.append(point)
        status.update(surface_points=len(self.surface), synthetic=self.synthetic,
                      cone_half_angle_deg=self.half_angle_deg)
        self.status = status
        return status


class SerialSonar(threading.Thread):
    """Reads distance lines from the microcontroller and feeds a SonarFusion. Needs pyserial."""

    def __init__(self, fusion: SonarFusion, port: str, baud: int = 115200) -> None:
        super().__init__(daemon=True)
        import serial  # imported here so the mapper runs without pyserial when no sonar is used
        self.fusion = fusion
        self.link = serial.Serial(port, baud, timeout=1)
        self.bad = 0

    def run(self) -> None:
        while True:
            try:
                raw = self.link.readline()
            except Exception as exc:  # unplugged cable: stop quietly, the status goes to no_sonar
                print(f"[sonar] serial read failed: {exc}")
                return
            if not raw:
                continue
            try:
                line = raw.decode("ascii")
            except UnicodeDecodeError:
                self.bad += 1
                continue
            value = parse_line(line)
            if value is None and line.strip() not in ("", "timeout"):
                self.bad += 1
                continue
            self.fusion.update(value)


def load_sidecar(path: str) -> dict[int, float | None]:
    """Sonar readings recorded next to an .esd file, keyed by depth frame sequence number."""
    readings: dict[int, float | None] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                item = json.loads(line)
                readings[int(item["seq"])] = item["range_m"]
    return readings
