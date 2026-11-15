"""Synthetic labelled scans built on real ones (ADR-0018).

A real *empty-room* recording supplies everything except the target:
  - the phone's real path (live poses saved next to the recording),
  - the real LiDAR depth of the room, with its real noise, dropouts and IMU readings.

A target (a person in some pose, a pet, a blanket, clutter) is modelled as capsules,
ellipsoids and boxes, placed on a free patch of the real floor, and ray-cast into every
frame from the real camera pose. Each depth pixel keeps the nearer of the real room and
the target, so occlusion is correct. LiDAR-style noise is added to target pixels: range
noise, low-frequency wobble, edge "flying pixels" that mix with the background, and
dropouts at grazing angles. The map is then integrated with the same filters as the live
mapper, using the real live poses, so the boxes (computed from the true geometry) line
up with the map by construction.

Output looks like a live scan: `<name>.esd` + `<name>.live.npz` + `<name>.labels.json`,
so `export` and the Databricks pipeline handle it unchanged. Every synthetic scan is
marked `data_origin = synthetic` with its base scan, so it can always be filtered out.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import protocol
from .geometry import backproject, remove_edge_pixels, remove_grazing_pixels
from .mapper import VoxelMap
from .server import read_records, write_record


# ---------------------------------------------------------------------------- primitives
@dataclass
class Capsule:
    a: np.ndarray
    b: np.ndarray
    r: float


@dataclass
class Ellipsoid:
    c: np.ndarray
    radii: np.ndarray
    R: np.ndarray = field(default_factory=lambda: np.eye(3))  # world <- local


@dataclass
class OBox:
    c: np.ndarray
    half: np.ndarray
    R: np.ndarray = field(default_factory=lambda: np.eye(3))


@dataclass
class Part:
    """A labelled object: its primitives and how it should be labelled."""
    label: str
    pose: str
    prims: list
    note: str = ""


def _ray_sphere(o, d, c, r):
    oc = o - c
    b = np.einsum("ij,ij->i", oc, d) if oc.ndim == 2 else d @ oc
    cc = (oc @ oc if oc.ndim == 1 else np.einsum("ij,ij->i", oc, oc)) - r * r
    disc = b * b - cc
    with np.errstate(invalid="ignore"):
        t = -b - np.sqrt(disc)
    return np.where((disc >= 0) & (t > 0), t, np.inf)


def _ray_capsule(o, d, cap: Capsule):
    """o: (3,), d: (N,3) unit rays. Distance to the first hit, inf if none."""
    ba = cap.b - cap.a
    oa = o - cap.a
    baba = ba @ ba
    bard = d @ ba
    baoa = ba @ oa
    rdoa = d @ oa
    oaoa = oa @ oa
    a = baba - bard * bard
    b = baba * rdoa - baoa * bard
    c = baba * oaoa - baoa * baoa - cap.r * cap.r * baba
    h = b * b - a * c
    with np.errstate(invalid="ignore", divide="ignore"):
        t = (-b - np.sqrt(h)) / a
    y = baoa + t * bard
    body = (h >= 0) & (a > 1e-12) & (y > 0) & (y < baba) & (t > 0)
    out = np.where(body, t, np.inf)
    rest = ~body
    if rest.any():
        out[rest] = np.minimum(_ray_sphere(o, d[rest], cap.a, cap.r), _ray_sphere(o, d[rest], cap.b, cap.r))
    return out


def _ray_ellipsoid(o, d, e: Ellipsoid):
    ol = (e.R.T @ (o - e.c)) / e.radii
    dl = (d @ e.R) / e.radii
    a = np.einsum("ij,ij->i", dl, dl)
    b = dl @ ol
    c = ol @ ol - 1
    disc = b * b - a * c
    with np.errstate(invalid="ignore"):
        t = (-b - np.sqrt(disc)) / a
    return np.where((disc >= 0) & (t > 0), t, np.inf)


def _ray_obox(o, d, bx: OBox):
    ol = bx.R.T @ (o - bx.c)
    dl = d @ bx.R
    inv = 1.0 / np.where(np.abs(dl) < 1e-12, 1e-12, dl)
    t1 = (-bx.half - ol) * inv
    t2 = (bx.half - ol) * inv
    tmin = np.max(np.minimum(t1, t2), axis=1)
    tmax = np.min(np.maximum(t1, t2), axis=1)
    return np.where((tmax >= tmin) & (tmin > 0), tmin, np.inf)


def ray_prim(o, d, p):
    if isinstance(p, Capsule):
        return _ray_capsule(o, d, p)
    if isinstance(p, Ellipsoid):
        return _ray_ellipsoid(o, d, p)
    return _ray_obox(o, d, p)


def prim_bounds(p) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(p, Capsule):
        return np.minimum(p.a, p.b) - p.r, np.maximum(p.a, p.b) + p.r
    if isinstance(p, Ellipsoid):
        ext = np.sqrt(((p.R * p.radii[None, :]) ** 2).sum(1))
        return p.c - ext, p.c + ext
    ext = np.abs(p.R) @ p.half
    return p.c - ext, p.c + ext


def sample_surface(p, n: int, rng) -> np.ndarray:
    """Points on (or very near) a primitive's surface, used to fit labels to what the sensor can see."""
    u = rng.normal(size=(n, 3))
    u /= np.linalg.norm(u, axis=1, keepdims=True)
    if isinstance(p, Capsule):
        s = rng.random(n)[:, None]
        return p.a + s * (p.b - p.a) + p.r * u
    if isinstance(p, Ellipsoid):
        return p.c + (u * p.radii) @ p.R.T
    return p.c + (np.clip(u * 1.8, -1, 1) * p.half) @ p.R.T


# ---------------------------------------------------------------------------- models
def _rz(yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def _ry(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _place(local: list, origin: np.ndarray, yaw: float) -> list:
    """Local model (x forward, y left, z up, origin on the floor) -> world."""
    R = _rz(yaw)
    out = []
    for p in local:
        if isinstance(p, Capsule):
            out.append(Capsule(origin + R @ p.a, origin + R @ p.b, p.r))
        elif isinstance(p, Ellipsoid):
            out.append(Ellipsoid(origin + R @ p.c, p.radii, R @ p.R))
        else:
            out.append(OBox(origin + R @ p.c, p.half, R @ p.R))
    return out


def _v(*a):
    return np.array(a, float)


def person(pose: str, height: float = 1.75, rng=None, clothing: float = 0.015) -> list:
    """Capsule person in a local frame (origin on the floor, roughly under the hips)."""
    rng = rng or np.random.default_rng(0)
    s = height / 1.75
    j = lambda: rng.normal(0, 0.02, 3)  # noqa: E731  small per-joint jitter so no two people are identical
    if pose == "standing":
        hip, sh, head = _v(0, 0, 0.92), _v(0, 0, 1.42), _v(0, 0, 1.62)
        P = [Capsule(_v(0, 0.1, 0.06), _v(0, 0.1, 0.90), 0.065), Capsule(_v(0, -0.1, 0.06), _v(0, -0.1, 0.90), 0.065),
             Capsule(hip, sh, 0.15), Ellipsoid(head, _v(0.09, 0.08, 0.115)),
             Capsule(_v(0, 0.22, 1.40), _v(0.05, 0.25, 0.82), 0.045), Capsule(_v(0, -0.22, 1.40), _v(0.05, -0.25, 0.82), 0.045),
             Capsule(_v(0.04, 0.1, 0.03), _v(0.2, 0.1, 0.03), 0.04), Capsule(_v(0.04, -0.1, 0.03), _v(0.2, -0.1, 0.03), 0.04)]
    elif pose == "crouching":  # squatting, torso leaning forward, arms on knees
        P = [Capsule(_v(-0.05, 0.12, 0.08), _v(0.25, 0.14, 0.45), 0.065), Capsule(_v(-0.05, -0.12, 0.08), _v(0.25, -0.14, 0.45), 0.065),
             Capsule(_v(0.25, 0.14, 0.45), _v(-0.12, 0.11, 0.42), 0.075), Capsule(_v(0.25, -0.14, 0.45), _v(-0.12, -0.11, 0.42), 0.075),
             Capsule(_v(-0.1, 0, 0.45), _v(0.12, 0, 0.9), 0.15), Ellipsoid(_v(0.2, 0, 1.08), _v(0.09, 0.08, 0.115)),
             Capsule(_v(0.1, 0.22, 0.88), _v(0.3, 0.18, 0.5), 0.045), Capsule(_v(0.1, -0.22, 0.88), _v(0.3, -0.18, 0.5), 0.045)]
    elif pose == "sitting_floor":
        P = [Capsule(_v(0, 0.1, 0.1), _v(0.45, 0.12, 0.1), 0.07), Capsule(_v(0, -0.1, 0.1), _v(0.45, -0.12, 0.1), 0.07),
             Capsule(_v(-0.05, 0, 0.15), _v(-0.1, 0, 0.6), 0.15), Ellipsoid(_v(-0.08, 0, 0.82), _v(0.09, 0.08, 0.115)),
             Capsule(_v(-0.1, 0.22, 0.6), _v(-0.25, 0.25, 0.12), 0.045), Capsule(_v(-0.1, -0.22, 0.6), _v(-0.25, -0.25, 0.12), 0.045)]
    elif pose in ("lying_back", "lying_front"):
        z = 0.12  # torso centreline height for a body lying flat
        P = [Capsule(_v(-0.45, 0.08, 0.08), _v(-1.25, 0.1, 0.07), 0.075), Capsule(_v(-0.45, -0.08, 0.08), _v(-1.25, -0.1, 0.07), 0.075),
             Capsule(_v(-0.4, 0, z), _v(0.15, 0, z), 0.15), Ellipsoid(_v(0.38, 0, 0.1), _v(0.115, 0.08, 0.09)),
             Capsule(_v(0.12, 0.21, 0.07), _v(-0.45, 0.24, 0.05), 0.05), Capsule(_v(0.12, -0.21, 0.07), _v(-0.45, -0.24, 0.05), 0.05)]
        if pose == "lying_front":
            P[4] = Capsule(_v(0.12, 0.24, 0.06), _v(0.5, 0.3, 0.05), 0.045)  # one arm above the head
    elif pose == "lying_side":  # recovery position: legs bent, one arm forward
        P = [Capsule(_v(-0.4, 0, 0.2), _v(0.15, 0, 0.22), 0.14), Ellipsoid(_v(0.38, 0, 0.18), _v(0.115, 0.09, 0.08)),
             Capsule(_v(-0.42, 0.06, 0.13), _v(-0.65, 0.4, 0.1), 0.07), Capsule(_v(-0.65, 0.4, 0.1), _v(-1.0, 0.35, 0.08), 0.06),
             Capsule(_v(-0.42, -0.04, 0.24), _v(-0.75, 0.25, 0.22), 0.07), Capsule(_v(-0.75, 0.25, 0.22), _v(-1.05, 0.15, 0.1), 0.06),
             Capsule(_v(0.12, 0.08, 0.15), _v(0.35, 0.4, 0.05), 0.045), Capsule(_v(0.1, -0.05, 0.3), _v(-0.2, 0.2, 0.32), 0.045)]
    elif pose == "lying_curled":
        P = [Capsule(_v(-0.25, 0, 0.2), _v(0.2, 0, 0.22), 0.14), Ellipsoid(_v(0.38, 0.12, 0.17), _v(0.11, 0.09, 0.08)),
             Capsule(_v(-0.25, 0.05, 0.14), _v(0.05, 0.4, 0.12), 0.07), Capsule(_v(0.05, 0.4, 0.12), _v(-0.25, 0.45, 0.09), 0.06),
             Capsule(_v(-0.25, -0.05, 0.27), _v(0.08, 0.35, 0.26), 0.07), Capsule(_v(0.08, 0.35, 0.26), _v(-0.2, 0.5, 0.2), 0.06),
             Capsule(_v(0.15, 0.1, 0.18), _v(0.3, 0.35, 0.1), 0.045)]
    else:
        raise ValueError(f"unknown pose {pose}")
    out = []
    for p in P:
        if isinstance(p, Capsule):
            out.append(Capsule(p.a * s + j(), p.b * s + j(), p.r * s + clothing))
        else:
            out.append(Ellipsoid(p.c * s + j(), p.radii * s, p.R))
    if pose.startswith("lying"):
        # Clothes and soft tissue fill the valleys between limbs and torso; without this a lying
        # capsule person shows separate "sticks", while real lying people map as one low mound.
        # One flattened ellipsoid per pair of adjacent body parts, lower than the parts themselves.
        body = [p for p in out if isinstance(p, Capsule)]
        for a in range(len(body)):
            for b in range(a + 1, len(body)):
                pa, pb = body[a], body[b]
                ca, cb = (pa.a + pa.b) / 2, (pb.a + pb.b) / 2
                if np.linalg.norm(ca - cb) > 0.8:
                    continue
                lo = np.minimum(np.minimum(pa.a, pa.b), np.minimum(pb.a, pb.b))
                hi = np.maximum(np.maximum(pa.a, pa.b), np.maximum(pb.a, pb.b))
                c = (lo + hi) / 2
                top = min(pa.a[2] + pa.r, pb.a[2] + pb.r) * 0.85
                half = (hi - lo) / 2 + 0.06  # reach past the parts so the mound has no valley between them
                out.append(Ellipsoid(_v(c[0], c[1], 0.0), _v(half[0], half[1], top)))
    return out


def pet(kind: str = "dog", rng=None) -> list:
    rng = rng or np.random.default_rng(0)
    if kind == "dog":  # medium dog, standing
        L, H, r = 0.55 * rng.uniform(0.85, 1.15), 0.32, 0.12
    elif kind == "cat":
        L, H, r = 0.38, 0.18, 0.08
    else:  # "dog_lying": curled on the floor
        return [Ellipsoid(_v(0, 0, 0.13), _v(0.33, 0.24, 0.13)), Ellipsoid(_v(0.2, 0.18, 0.12), _v(0.09, 0.08, 0.08))]
    leg = r * 0.35
    return [Ellipsoid(_v(0, 0, H + r * 0.6), _v(L / 2, r, r)),
            Ellipsoid(_v(L / 2 + r * 0.5, 0, H + r * 1.5), _v(r * 0.75, r * 0.6, r * 0.6)),
            *[Capsule(_v(x, y, 0.02), _v(x, y, H + r * 0.3), leg) for x in (L * 0.38, -L * 0.38) for y in (r * 0.5, -r * 0.5)],
            Capsule(_v(-L / 2, 0, H + r * 0.8), _v(-L / 2 - 0.25 * L, 0, H + r * 1.4), leg * 0.7)]


def blanket_over(prims: list, keep_head: bool = True, thickness: float = 0.05) -> list:
    """A blanket draped over a lying person: inflated copies of the covered parts plus a sheet between them."""
    covered = [p for p in prims if not (keep_head and isinstance(p, Ellipsoid))]
    lo = np.min([prim_bounds(p)[0] for p in covered], axis=0)
    hi = np.max([prim_bounds(p)[1] for p in covered], axis=0)
    out = []
    for p in covered:
        if isinstance(p, Capsule):
            out.append(Capsule(p.a, p.b, p.r + thickness))
    c = (lo + hi) / 2
    out.append(Ellipsoid(_v(c[0], c[1], 0.0), _v((hi[0] - lo[0]) / 2 + 0.1, (hi[1] - lo[1]) / 2 + 0.12, hi[2] * 0.85)))
    return out


# ---------------------------------------------------------------------------- scene specs
@dataclass
class SceneSpec:
    scene: str
    parts: list  # list[Part] in a local frame around the scene origin (on the floor)
    footprint: float  # radius of free floor needed, m
    notes: str


def build_scene(scene: str, variant: str, rng) -> SceneSpec:
    h = rng.uniform(1.6, 1.9)
    if scene == "person_standing":
        return SceneSpec(scene, [Part("person", "standing", person("standing", h, rng))], 0.45, "standing")
    if scene == "person_lying":
        pose = variant or "lying_back"
        return SceneSpec(scene, [Part("person", "lying", person(pose, h, rng))], 1.1, pose.replace("_", " "))
    if scene == "person_crouching":
        return SceneSpec(scene, [Part("person", "crouching", person("crouching", h, rng))], 0.55, "crouching")
    if scene == "person_sitting":
        return SceneSpec(scene, [Part("person", "sitting", person("sitting_floor", h, rng))], 0.7, "sitting on floor")
    if scene == "person_partly_covered":
        body = person(variant or "lying_back", h, rng)
        head = [p for p in body if isinstance(p, Ellipsoid)]
        if rng.random() < 0.5 or variant == "lying_curled":
            cover = blanket_over(body)
            what = "blanket over the body, head visible"
            parts = [Part("person", "lying", body + cover, "partly covered by a blanket")]
        else:  # a cardboard box / board lying over the legs
            legs_lo = np.min([prim_bounds(p)[0] for p in body[:2]], axis=0)
            legs_hi = np.max([prim_bounds(p)[1] for p in body[:2]], axis=0)
            c = (legs_lo + legs_hi) / 2
            board = OBox(_v(c[0], c[1], legs_hi[2] + 0.12), _v((legs_hi[0] - legs_lo[0]) / 2 + 0.08, 0.35, 0.12))
            what = "cardboard box over the legs"
            parts = [Part("person", "lying", body, "legs under a box"),
                     Part("clutter", "", [board], "cardboard box")]
        _ = head
        return SceneSpec(scene, parts, 1.15, f"{(variant or 'lying_back').replace('_', ' ')}, {what}")
    if scene == "pet":
        kind = variant or "dog"
        return SceneSpec(scene, [Part("pet", "lying" if kind == "dog_lying" else "standing", pet(kind, rng))], 0.5, kind.replace("_", " "))
    if scene == "mixed":
        pose = variant or "lying_curled"
        parts = [Part("person", pose.split("_")[0], person(pose, h, rng))]
        blo = np.min([prim_bounds(q)[0] for q in parts[0].prims], axis=0)
        bhi = np.max([prim_bounds(q)[1] for q in parts[0].prims], axis=0)
        # boxes/bags hugging the body (10 cm clear), so the whole group fits a small free floor patch
        for side in ("+x", "-y", "-x")[: int(rng.integers(2, 4))]:
            w, d, hh = rng.uniform(0.25, 0.4), rng.uniform(0.25, 0.35), rng.uniform(0.2, 0.55)
            r = math.hypot(w, d) / 2 + 0.1
            if side == "+x":
                x, y = bhi[0] + r, rng.uniform(blo[1], bhi[1])
            elif side == "-x":
                x, y = blo[0] - r, rng.uniform(blo[1], bhi[1])
            else:
                x, y = rng.uniform(blo[0], bhi[0]), blo[1] - r
            parts.append(Part("clutter", "", [OBox(_v(x, y, hh / 2), _v(w / 2, d / 2, hh / 2), _rz(rng.uniform(0, math.pi)))],
                              "box/bag"))
        return SceneSpec(scene, parts, 1.2, f"{pose.replace('_', ' ')} among boxes and bags")
    raise ValueError(scene)


# ---------------------------------------------------------------------------- base scan
@dataclass
class Base:
    esd: Path
    live: dict
    labels: dict
    floor_z: float


def load_base(esd: str | Path) -> Base:
    esd = Path(esd)
    live = dict(np.load(esd.with_suffix(".live.npz")))
    lab_p = esd.with_suffix(".labels.json")
    labels = json.loads(lab_p.read_text()) if lab_p.exists() else {"scene": {}, "boxes": []}
    pts = live["map_points"]
    z = pts[:, 2]
    # floor: the densest horizontal layer in the lowest 30% of heights
    lo = z[z < np.percentile(z, 30)]
    hist, edges = np.histogram(lo, bins=np.arange(lo.min(), lo.max() + 0.02, 0.02))
    floor_z = float(edges[np.argmax(hist)] + 0.01)
    return Base(esd, live, labels, floor_z)


def choose_spot(base: Base, half: np.ndarray, center: np.ndarray, rng, avoid: list | None = None
                ) -> tuple[np.ndarray, float]:
    """A free, well-seen patch of real floor for a footprint rectangle (half-extents `half`, local
    centre `center`): real floor observed under it, (almost) nothing standing on it, and many camera
    positions 1-3.2 m away looking at it. Returns the scene origin on the floor and its yaw."""
    from scipy.spatial import cKDTree
    pts = base.live["map_points"]
    fz = base.floor_z
    floor = pts[np.abs(pts[:, 2] - fz) < 0.04]
    above = pts[(pts[:, 2] > fz + 0.06) & (pts[:, 2] < fz + 1.9)]
    ok = np.isin(base.live["status"], list(MAPPED))
    cams, fwd = base.live["pos"][ok], base.live["R"][ok].reshape(-1, 3, 3)[:, :, 2]
    t_above, t_floor = cKDTree(above[:, :2]), cKDTree(floor[:, :2])
    reach = float(np.linalg.norm(half)) + float(np.linalg.norm(center))
    cand = floor[rng.choice(len(floor), min(2500, len(floor)), replace=False)]
    best, best_score = None, -1.0
    for c in cand:
        if avoid and any(np.linalg.norm(c[:2] - a[:2]) < 1.0 for a in avoid):
            continue
        near_above = above[t_above.query_ball_point(c[:2], reach)][:, :2] - c[:2]
        near_floor = floor[t_floor.query_ball_point(c[:2], reach)][:, :2] - c[:2]
        for yaw in rng.uniform(0, 2 * math.pi, 6):
            R2 = _rz(yaw)[:2, :2]
            def inside(q):
                ql = q @ R2 - center[:2]  # world offset -> local
                return (np.abs(ql) <= half[:2]).all(1)
            n_floor = int(inside(near_floor).sum()) if len(near_floor) else 0
            area = 4 * half[0] * half[1]
            if n_floor < 0.6 * area / 0.02 ** 2 * 0.25:  # at least ~15% of the 2 cm floor cells observed
                continue
            if len(near_above) and inside(near_above).sum() > max(15, 0.03 * n_floor):
                continue
            ctr = np.array([*(c[:2] + R2 @ center[:2]), fz + 0.3])
            v = ctr - cams
            dist = np.linalg.norm(v, axis=1)
            facing = np.einsum("ij,ij->i", v / dist[:, None], fwd) > 0.8
            score = float(((dist > 1.0) & (dist < 3.2) & facing).sum()) + rng.random()
            if score > best_score:
                best, best_score = (c, yaw), score
    if best is not None and best_score < min(40, 0.25 * len(cams)):  # barely seen: useless as a scan
        best = None
    if best is None:
        raise RuntimeError(f"no free, well-seen floor patch of {2 * half[0]:.1f} x {2 * half[1]:.1f} m in {base.esd.name}")
    c, yaw = best
    return np.array([c[0], c[1], fz]), float(yaw)


# ---------------------------------------------------------------------------- rendering
def _rays(K, h, w):
    v, u = np.mgrid[0:h, 0:w]
    r = np.stack([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], np.ones((h, w))], -1).reshape(-1, 3)
    return r  # z = 1, so ray parameter along r = z-depth


def render_parts(R_wc, t, K, h, w, prims, lo, hi):
    """z-depth of the synthetic geometry per pixel (inf where it misses) and the hit index."""
    rc = _rays(K, h, w)
    norm = np.linalg.norm(rc, axis=1)
    dw = (rc / norm[:, None]) @ R_wc.T
    # cull with the bounding sphere of the whole scene
    c, rad = (lo + hi) / 2, np.linalg.norm(hi - lo) / 2
    m = np.isfinite(_ray_sphere(t, dw, c, rad)) | (np.linalg.norm(t - c) < rad)
    dist = np.full(len(dw), np.inf)
    idx = np.full(len(dw), -1)
    if m.any():
        dm = dw[m]
        best = np.full(len(dm), np.inf)
        bi = np.full(len(dm), -1)
        for k, p in enumerate(prims):
            tk = ray_prim(t, dm, p)
            better = tk < best
            best[better], bi[better] = tk[better], k
        dist[m], idx[m] = best, bi
    return (dist / norm).reshape(h, w), idx.reshape(h, w)


def _smooth_noise(rng, h, w, scale=12):
    g = rng.normal(size=(h // scale + 2, w // scale + 2))
    yi = np.linspace(0, g.shape[0] - 1.001, h)
    xi = np.linspace(0, g.shape[1] - 1.001, w)
    y0, x0 = yi.astype(int), xi.astype(int)
    fy, fx = (yi - y0)[:, None], (xi - x0)[None, :]
    a = g[y0][:, x0]; b = g[y0][:, x0 + 1]; c = g[y0 + 1][:, x0]; d = g[y0 + 1][:, x0 + 1]
    return a * (1 - fy) * (1 - fx) + b * (1 - fy) * fx + c * fy * (1 - fx) + d * fy * fx


def real_noise_field(real: np.ndarray, R_wc, t, K, map_pts: np.ndarray, sigma: float = 6.0) -> np.ndarray:
    """This frame's real depth error, measured against the base map and spread smoothly over the image.

    The base map rendered from the frame's pose is a stand-in for the true room; `real - rendered`
    holds the LiDAR's low-frequency "wavy" error and this frame's pose error. Applying that to the
    synthetic pixels makes the target smear exactly like real surfaces do in the same frame.
    """
    from scipy.ndimage import gaussian_filter
    h, w = real.shape
    pc = (map_pts - t) @ R_wc
    pc = pc[(pc[:, 2] > 0.2) & (pc[:, 2] < 5.0)]
    u = np.round(pc[:, 0] / pc[:, 2] * K[0, 0] + K[0, 2]).astype(int)
    v = np.round(pc[:, 1] / pc[:, 2] * K[1, 1] + K[1, 2]).astype(int)
    ok = (u >= 0) & (u < w) & (v >= 0) & (v < h)
    rend = np.full(h * w, np.inf)
    np.minimum.at(rend, v[ok] * w + u[ok], pc[ok, 2])
    rend = rend.reshape(h, w)
    res = real - rend
    good = np.isfinite(res) & (np.abs(res) < 0.2)
    if good.sum() < 500:
        return np.zeros((h, w))
    res = np.where(good, res - np.median(res[good]), 0.0)
    num = gaussian_filter(res, sigma)
    den = gaussian_filter(good.astype(float), sigma)
    return np.where(den > 1e-3, num / np.maximum(den, 1e-3), 0.0)


def composite(real: np.ndarray, synth: np.ndarray, K, rng, hole_filling: bool, field: np.ndarray | None = None):
    """Nearer of real and synthetic depth, with iPhone-LiDAR-like noise on the synthetic pixels."""
    h, w = real.shape
    hit = np.isfinite(synth)
    if not hit.any():
        return real, hit
    d = synth.copy()
    # per-pixel range noise (~0.3 cm + 0.3% of range), plus the frame's real low-frequency error if known
    d[hit] += rng.normal(0, 1, hit.sum()) * (0.003 + 0.003 * d[hit])
    if field is not None:
        d[hit] += field[hit]
    else:
        d += _smooth_noise(rng, h, w) * (0.004 + 0.003 * np.nan_to_num(d, posinf=0))
    # grazing angles: dropouts on surfaces seen edge-on
    graze = np.isnan(remove_grazing_pixels(np.where(hit, d, np.nan), K, 0.2)) & hit
    d[graze & (rng.random((h, w)) < 0.6)] = np.inf
    near = hit & ((d < real) | ~np.isfinite(real))
    out = real.copy()
    out[near] = d[near]
    # silhouette: flying pixels that blend target and background (more with hole filling on)
    edge = near & ~(np.roll(near, 1, 0) & np.roll(near, -1, 0) & np.roll(near, 1, 1) & np.roll(near, -1, 1))
    ring = ~near & (np.roll(near, 1, 0) | np.roll(near, -1, 0) | np.roll(near, 1, 1) | np.roll(near, -1, 1))
    p_mix = 0.45 if hole_filling else 0.15
    for mask in (edge, ring):
        sel = mask & (rng.random((h, w)) < p_mix) & np.isfinite(real)
        a = rng.random(sel.sum())
        fg = np.where(np.isfinite(d[sel]), d[sel], real[sel])
        out[sel] = a * fg + (1 - a) * real[sel]
    if hole_filling:
        # AVFoundation's filtering smooths and fills across the silhouette: blobs, not crisp limbs
        from scipy.ndimage import binary_dilation, gaussian_filter
        band = binary_dilation(near, iterations=3)
        fin = np.isfinite(out)
        num = gaussian_filter(np.where(fin, out, 0.0), 1.8)
        den = gaussian_filter(fin.astype(float), 1.8)
        sm = band & (den > 0.3)
        out[sm] = num[sm] / den[sm]
        near = near | (sm & ~fin)
    out[out <= 0] = np.nan
    out[~np.isfinite(out)] = np.nan
    return out.astype(np.float32), near


# ---------------------------------------------------------------------------- whole scan
MAPPED = ("tracking", "relocalized", "merged", "init")


def synthesize(base_esd: str | Path, scene: str, variant: str, out_dir: str | Path, name: str, seed: int = 0,
               avoid: list | None = None, voxel: float = 0.02, map_max_range: float = 3.5) -> dict:
    rng = np.random.default_rng(seed)
    base = load_base(base_esd)
    spec = build_scene(scene, variant, rng)
    lp = [q for p in spec.parts for q in p.prims]
    llo = np.min([prim_bounds(q)[0] for q in lp], axis=0)
    lhi = np.max([prim_bounds(q)[1] for q in lp], axis=0)
    origin, yaw = choose_spot(base, (lhi - llo) / 2 + 0.08, (lhi + llo) / 2, rng, avoid)
    parts = [Part(p.label, p.pose, _place(p.prims, origin, yaw), p.note) for p in spec.parts]
    prims = [q for p in parts for q in p.prims]
    owner = [i for i, p in enumerate(parts) for _ in p.prims]
    lo = np.min([prim_bounds(p)[0] for p in prims], axis=0)
    hi = np.max([prim_bounds(p)[1] for p in prims], axis=0)
    hole_filling = None  # from the base frames' `filtered` flag (the app's Hole filling toggle)

    live = base.live
    idx = {float(t): i for i, t in enumerate(live["t"])}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    esd_out = out_dir / f"{name}.esd"
    vmap = VoxelMap(voxel)
    vmap.carving = True
    log = []
    bm, bh = live["map_points"], live["map_hits"]
    noise_pts = bm[(bh >= 3) & (np.linalg.norm(bm - (lo + hi) / 2, axis=1) < 4.0)]
    seen_pts: list[list[np.ndarray]] = [[] for _ in parts]  # target points that made it into the depth
    n_int = 0
    with open(esd_out, "wb") as fh:
        for msg in read_records(base.esd):
            f = protocol.decode(msg)
            if hole_filling is None:
                hole_filling = bool(f.filtered)
            j = idx.get(float(f.t))
            if j is None:
                continue  # the live mapper skipped this frame: no trusted pose, leave it out
            R = live["R"][j].reshape(3, 3)
            t = live["pos"][j]
            h, w = f.depth.shape
            syn, hit_idx = render_parts(R, t, f.K, h, w, prims, lo, hi)
            field = real_noise_field(f.depth, R, t, f.K, noise_pts) if np.isfinite(syn).any() else None
            depth, near = composite(f.depth, syn, f.K, rng, hole_filling, field)
            f.depth = depth
            if f.confidence is not None:
                f.confidence = f.confidence.copy()
                f.confidence[near] = 2
            f.source = "synthetic"
            write_record(fh, protocol.encode(f))
            st = str(live["status"][j])
            log.append(j)
            if st not in MAPPED:
                continue
            # same map pipeline as Mapper._process/_accept
            clean = remove_grazing_pixels(remove_edge_pixels(depth, 0.05), f.K, 0.25)
            pts = backproject(clean, f.K, f.confidence, 1, max_range=map_max_range)
            world = pts @ R.T + t
            vmap.add(world)
            n_int += 1
            if n_int % 2 == 0 and len(world):
                vmap.carve(t, world[rng.choice(len(world), min(2000, len(world)), replace=False)])
            # which part each visible target pixel belongs to (for label fitting)
            vis = near & np.isfinite(clean)
            if vis.any():
                v, u = np.nonzero(vis)
                z = clean[v, u]
                pc = np.stack([(u - f.K[0, 2]) * z / f.K[0, 0], (v - f.K[1, 2]) * z / f.K[1, 1], z], 1)
                pw = pc @ R.T + t
                own = np.array(owner)[hit_idx[v, u]]
                for k in range(len(parts)):
                    sel = pw[own == k]
                    if len(sel):
                        seen_pts[k].append(sel[rng.choice(len(sel), min(200, len(sel)), replace=False)])

    mp, mc = vmap.points(2)
    sel = np.array(log)
    np.savez_compressed(
        out_dir / f"{name}.live.npz", map_points=mp.astype(np.float32), map_hits=mc.astype(np.int32),
        t=live["t"][sel], seq=live["seq"][sel], status=live["status"][sel], R=live["R"][sel], pos=live["pos"][sel],
        rmse=live["rmse"][sel], inliers=live["inliers"][sel], segment=live["segment"][sel], voxel=np.array(voxel))

    boxes = []
    for k, p in enumerate(parts):
        if seen_pts[k]:  # snug box around what the sensor saw (+5 cm), down to the floor
            sp = np.concatenate(seen_pts[k])
            blo, bhi = np.percentile(sp, 0.5, axis=0) - 0.05, np.percentile(sp, 99.5, axis=0) + 0.05
        else:
            blo, bhi = prim_bounds(p.prims[0])
        blo[2] = min(blo[2], base.floor_z)
        boxes.append({"label": p.label, "pose": p.pose, "min": blo.tolist(), "max": bhi.tolist(),
                      "note": f"synthetic: {p.note}".strip()})
    bscene = base.labels.get("scene", {})
    labels = {
        "scene": {"lights": bscene.get("lights", "unknown"), "room": bscene.get("room", ""), "scene": scene,
                  "notes": f"SYNTHETIC ({spec.notes}) inserted into real scan {base.esd.name}",
                  "data_origin": "synthetic", "base_scan": base.esd.name, "synth_seed": str(seed),
                  "synth_version": SYNTH_VERSION, "hole_filling": "on" if hole_filling else "off"},
        "boxes": boxes, "scan_file": esd_out.name, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (out_dir / f"{name}.labels.json").write_text(json.dumps(labels, indent=2))
    return {"name": name, "scene": scene, "variant": variant, "base": base.esd.name, "frames": len(log),
            "origin": origin.round(2).tolist(), "map_points": int(len(mp)),
            "visible_target_points": [int(sum(len(a) for a in s)) for s in seen_pts], "boxes": boxes}


SYNTH_VERSION = "0.1"

# What's still missing from the DATA_COLLECTION checklist after the real scans of 2026-11-15.
CHECKLIST_REST = [
    ("person_standing", ""), ("person_standing", ""),
    ("person_lying", "lying_front"), ("person_lying", "lying_side"),
    ("person_crouching", ""), ("person_crouching", ""), ("person_crouching", ""),
    ("person_partly_covered", "lying_back"), ("person_partly_covered", "lying_side"),
    ("person_partly_covered", "lying_curled"), ("person_partly_covered", "lying_front"),
    ("pet", "dog"), ("pet", "cat"), ("pet", "dog_lying"),
    ("mixed", "lying_curled"), ("mixed", "sitting_floor"), ("mixed", "crouching"),
]


def run_plan(bases: list[str], out_dir: str | Path, plan=None, seed: int = 0, workers: int = 4) -> list[dict]:
    """Generate every (scene, variant) in `plan`, rotating over the base scans (falls back to the
    next base when a scan has no free floor big enough)."""
    from concurrent.futures import ProcessPoolExecutor
    plan = plan or CHECKLIST_REST
    counts: dict[str, int] = {}
    jobs = []
    for i, (scene, variant) in enumerate(plan):
        counts[scene] = counts.get(scene, 0) + 1
        name = f"synth-{scene}-{counts[scene]:02d}"
        order = bases[i % len(bases):] + bases[:i % len(bases)]
        jobs.append((order, scene, variant, str(out_dir), name, seed + i))
    with ProcessPoolExecutor(workers) as ex:
        return list(ex.map(_job, jobs))


def _job(job) -> dict:
    order, scene, variant, out_dir, name, seed = job
    last = None
    for base in order:
        try:
            return synthesize(base, scene, variant, out_dir, name, seed=seed)
        except RuntimeError as e:  # no free floor in this base scan: try the next one
            last = e
    return {"name": name, "scene": scene, "error": str(last)}
