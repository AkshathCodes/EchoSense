"""Primitive surfaces and labeled object builders.

Objects are represented as surface samples with outward normals and an
edge flag — the format the acoustic model needs. Meshes (ModelNet etc.) could
be added later by sampling into the same `Surface` format.

Object builders place the object's floor contact at z = 0 in its local frame;
`place()` moves it into the sensor frame where the floor is at FLOOR_Z.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

CLASSES: dict[int, str] = {0: "wall", 1: "doorway", 2: "furniture", 3: "debris", 4: "person", 5: "noise"}
CLASS_IDS: dict[str, int] = {v: k for k, v in CLASSES.items()}
NOISE = -1  # POINT-level label: ghost / unlabeled point
NOISE_CLASS = 5  # CLUSTER-level class: a cluster made mostly of noise points (ADR-0009)
OBJECT_CLASSES = (0, 1, 2, 3, 4)  # classes that correspond to physical objects

# Relative acoustic reflectivity. In air almost any solid reflects strongly
# (huge impedance mismatch); porous materials (fabric, clothing, upholstery)
# absorb some. GUESSES — validate with real captures.
REFLECTIVITY: dict[int, float] = {0: 1.0, 1: 1.0, 2: 0.7, 3: 0.9, 4: 0.5}

FLOOR_Z = -1.3  # sensor ~1.3 m above floor (chest height)


@dataclass
class Surface:
    points: np.ndarray  # [M, 3]
    normals: np.ndarray  # [M, 3], unit, outward
    is_edge: np.ndarray  # [M] bool

    def __len__(self) -> int:
        return len(self.points)


def concat(surfaces: list[Surface]) -> Surface:
    return Surface(
        np.concatenate([s.points for s in surfaces]),
        np.concatenate([s.normals for s in surfaces]),
        np.concatenate([s.is_edge for s in surfaces]),
    )


def rotation(yaw: float = 0.0, pitch: float = 0.0, roll: float = 0.0) -> np.ndarray:
    """R = Rz(yaw) @ Ry(pitch) @ Rx(roll)."""
    cy, sy, cp, sp, cr, sr = (math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch), math.cos(roll), math.sin(roll))
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    return rz @ ry @ rx


def transform(s: Surface, rot: np.ndarray, t: np.ndarray | tuple = (0.0, 0.0, 0.0)) -> Surface:
    return Surface(s.points @ rot.T + np.asarray(t, dtype=float), s.normals @ rot.T, s.is_edge.copy())


# ---------------------------------------------------------------- primitives


def box(size: tuple[float, float, float], spacing: float) -> Surface:
    """Axis-aligned box centered at the origin."""
    size = np.asarray(size, dtype=float)
    pts, nrm, edge = [], [], []
    for a in range(3):
        u, v = [i for i in range(3) if i != a]
        nu = max(2, int(math.ceil(size[u] / spacing)) + 1)
        nv = max(2, int(math.ceil(size[v] / spacing)) + 1)
        gu, gv = np.meshgrid(np.linspace(-size[u] / 2, size[u] / 2, nu), np.linspace(-size[v] / 2, size[v] / 2, nv), indexing="ij")
        gu, gv = gu.ravel(), gv.ravel()
        is_edge = (np.abs(gu) >= size[u] / 2 - 1.01 * spacing) | (np.abs(gv) >= size[v] / 2 - 1.01 * spacing)
        for sign in (-1.0, 1.0):
            p = np.zeros((len(gu), 3))
            p[:, a] = sign * size[a] / 2
            p[:, u], p[:, v] = gu, gv
            n = np.zeros_like(p)
            n[:, a] = sign
            pts.append(p), nrm.append(n), edge.append(is_edge)
    return Surface(np.concatenate(pts), np.concatenate(nrm), np.concatenate(edge))


def cylinder(radius: float, height: float, spacing: float) -> Surface:
    """Capped cylinder, base at origin, axis +z."""
    nt = max(8, int(math.ceil(2 * math.pi * radius / spacing)))
    nh = max(2, int(math.ceil(height / spacing)) + 1)
    th, h = np.meshgrid(np.linspace(0, 2 * math.pi, nt, endpoint=False), np.linspace(0, height, nh), indexing="ij")
    th, h = th.ravel(), h.ravel()
    side_p = np.stack([radius * np.cos(th), radius * np.sin(th), h], axis=1)
    side_n = np.stack([np.cos(th), np.sin(th), np.zeros_like(th)], axis=1)
    side_e = (h <= 1.01 * spacing) | (h >= height - 1.01 * spacing)
    g = np.arange(-radius, radius + 1e-9, spacing)
    gx, gy = np.meshgrid(g, g, indexing="ij")
    inside = gx**2 + gy**2 <= radius**2
    gx, gy = gx[inside], gy[inside]
    rim = np.sqrt(gx**2 + gy**2) >= radius - 1.01 * spacing
    caps_p, caps_n, caps_e = [], [], []
    for z, nz in ((0.0, -1.0), (height, 1.0)):
        caps_p.append(np.stack([gx, gy, np.full_like(gx, z)], axis=1))
        caps_n.append(np.tile([0.0, 0.0, nz], (len(gx), 1)))
        caps_e.append(rim)
    return Surface(
        np.concatenate([side_p, *caps_p]), np.concatenate([side_n, *caps_n]), np.concatenate([side_e, *caps_e])
    )


def sphere(radius: float, spacing: float) -> Surface:
    """Fibonacci-sampled sphere centered at the origin."""
    n = max(20, int(math.ceil(4 * math.pi * radius**2 / spacing**2)))
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    theta = math.pi * (1 + 5**0.5) * i
    d = np.stack([np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)], axis=1)
    return Surface(radius * d, d, np.zeros(n, dtype=bool))


# ---------------------------------------------------------------- objects


@dataclass
class SceneObject:
    class_id: int
    name: str
    surface: Surface
    center_xy: np.ndarray
    radius_xy: float
    point_label: int | None = None  # label written onto returns; defaults to class_id (floor uses NOISE)
    reflectivity_override: float | None = None
    variant: str = ""  # e.g. person pose or furniture kind; recorded in frame meta for diagnostics

    @property
    def reflectivity(self) -> float:
        return self.reflectivity_override if self.reflectivity_override is not None else REFLECTIVITY[self.class_id]

    @property
    def label(self) -> int:
        return self.class_id if self.point_label is None else self.point_label


def place(local: Surface, class_id: int, name: str, x: float, y: float, yaw: float, variant: str = "") -> SceneObject:
    s = transform(local, rotation(yaw=yaw), (x, y, FLOOR_Z))
    c = np.array([x, y])
    r = float(np.max(np.linalg.norm(s.points[:, :2] - c, axis=1))) if len(s) else 0.0
    return SceneObject(class_id, name, s, c, r, variant=variant)


def _at(s: Surface, t: tuple[float, float, float], rot: np.ndarray | None = None) -> Surface:
    return transform(s, np.eye(3) if rot is None else rot, t)


def wall_local(width: float, height: float, sp: float, thickness: float = 0.12, z0: float = 0.0, y0: float = 0.0) -> Surface:
    """Wall whose large faces have normals ±x (faces the sensor at yaw≈0); bottom at z0, centered at y0."""
    return _at(box((thickness, width, height), sp), (0, y0, z0 + height / 2))


def doorway_local(rng: np.random.Generator, sp: float) -> tuple[Surface, float, float]:
    """Door frame (two jambs + lintel). Returns (surface, outer half-width, top height)."""
    gap = rng.uniform(0.8, 1.0)
    h = rng.uniform(2.0, 2.1)
    depth, jw = 0.15, 0.10
    parts = [
        _at(box((depth, jw, h), sp), (0, side * (gap / 2 + jw / 2), h / 2)) for side in (-1, 1)
    ]
    parts.append(_at(box((depth, gap + 2 * jw, 0.12), sp), (0, 0, h + 0.06)))
    return concat(parts), gap / 2 + jw, h + 0.12


def doorway_wall_local(rng: np.random.Generator, sp: float, half_width: float, top: float, height: float = 2.6) -> Surface:
    """Wall segments surrounding a door frame: left, right, and header above the lintel."""
    wl, wr = rng.uniform(0.6, 2.0), rng.uniform(0.6, 2.0)
    parts = [
        wall_local(wl, height, sp, y0=half_width + wl / 2),
        wall_local(wr, height, sp, y0=-(half_width + wr / 2)),
    ]
    if height - top > 0.05:
        parts.append(wall_local(2 * half_width, height - top, sp, z0=top))
    return concat(parts)


def floor_local(sp: float, x_range: tuple[float, float] = (0.3, 6.5), y_half: float = 4.5) -> Surface:
    """Single upward-facing plane at z = 0 (sampled 2x coarser: it's large and only partly visible)."""
    s = 2 * sp
    gx, gy = np.meshgrid(np.arange(x_range[0], x_range[1], s), np.arange(-y_half, y_half, s), indexing="ij")
    pts = np.stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)], axis=1)
    return Surface(pts, np.tile([0.0, 0.0, 1.0], (len(pts), 1)), np.zeros(len(pts), dtype=bool))


def furniture_local(rng: np.random.Generator, sp: float) -> tuple[Surface, str]:
    kind = str(rng.choice(["chair", "table", "cabinet", "sofa"]))
    if kind == "chair":
        seat_h, w = rng.uniform(0.42, 0.5), rng.uniform(0.4, 0.5)
        parts = [_at(box((w, w, 0.05), sp), (0, 0, seat_h)), _at(box((0.05, w, 0.5), sp), (w / 2, 0, seat_h + 0.25))]
        parts += [_at(box((0.04, 0.04, seat_h), sp), (sx * (w / 2 - 0.02), sy * (w / 2 - 0.02), seat_h / 2)) for sx in (-1, 1) for sy in (-1, 1)]
    elif kind == "table":
        lx, ly, h = rng.uniform(0.6, 0.9), rng.uniform(0.8, 1.5), rng.uniform(0.7, 0.78)
        parts = [_at(box((lx, ly, 0.04), sp), (0, 0, h))]
        parts += [_at(box((0.05, 0.05, h), sp), (sx * (lx / 2 - 0.05), sy * (ly / 2 - 0.05), h / 2)) for sx in (-1, 1) for sy in (-1, 1)]
    elif kind == "cabinet":
        lx, ly, h = rng.uniform(0.4, 0.6), rng.uniform(0.6, 1.2), rng.uniform(0.8, 1.9)
        parts = [_at(box((lx, ly, h), sp), (0, 0, h / 2))]
    else:  # sofa
        ly = rng.uniform(1.6, 2.2)
        parts = [_at(box((0.9, ly, 0.45), sp), (0, 0, 0.225)), _at(box((0.2, ly, 0.4), sp), (0.35, 0, 0.65))]
    return concat(parts), kind


def debris_local(rng: np.random.Generator, sp: float) -> Surface:
    parts = []
    for _ in range(int(rng.integers(3, 9))):
        size = rng.uniform(0.05, 0.4, size=3)
        rot = rotation(rng.uniform(0, 2 * math.pi), rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6))
        off = rng.uniform(-0.5, 0.5, size=2)
        parts.append(_at(box(tuple(size), sp), (off[0], off[1], size[2] / 2), rot))
    return concat(parts)


def person_local(rng: np.random.Generator, sp: float) -> tuple[Surface, str]:
    """Crude humanoid from cylinders + sphere. Poses: standing, crouching, lying."""
    h = rng.uniform(1.5, 1.9)
    leg_h, torso_h = 0.47 * h, 0.30 * h
    parts = [_at(cylinder(0.07, leg_h, sp), (0, s * 0.1, 0)) for s in (-1, 1)]
    parts.append(_at(cylinder(0.15, torso_h, sp), (0, 0, leg_h)))
    parts.append(_at(sphere(0.10, sp), (0, 0, leg_h + torso_h + 0.12)))
    parts += [_at(cylinder(0.045, 0.35 * h, sp), (0, s * 0.21, 0.42 * h)) for s in (-1, 1)]
    body = concat(parts)
    pose = str(rng.choice(["standing", "crouching", "lying"], p=[0.4, 0.25, 0.35]))
    if pose == "crouching":
        body = Surface(body.points * np.array([1.0, 1.0, 0.6]), body.normals, body.is_edge)  # crude squash
    elif pose == "lying":
        body = transform(body, rotation(pitch=math.pi / 2))
        body = transform(body, np.eye(3), (0.0, 0.0, -body.points[:, 2].min()))
    return body, pose
