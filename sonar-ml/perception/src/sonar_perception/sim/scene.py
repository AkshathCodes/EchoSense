"""Random scene composer: walls + a few objects in front of the sensor.

The floor is intentionally not simulated yet: at grazing incidence it is mostly
specular-invisible, and a floor plane would form one giant cluster. Revisit
once real data shows how much floor clutter the sensor actually sees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..config import SensorConfig, SimConfig
from . import shapes
from .shapes import CLASS_IDS, NOISE, SceneObject


@dataclass
class Scene:
    objects: list[SceneObject] = field(default_factory=list)

    def object_list(self) -> list[dict]:
        """Per-instance metadata; list index == instance id in point_instances."""
        return [
            {"instance": i, "name": o.name, "class_id": int(o.class_id), "variant": o.variant,
             "x": round(float(o.center_xy[0]), 3), "y": round(float(o.center_xy[1]), 3)}
            for i, o in enumerate(self.objects)
        ]

    def class_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for o in self.objects:
            out[o.name] = out.get(o.name, 0) + 1
        return out


ROOM_WALL = "wall"  # room-scale walls: excluded from overlap checks (handled by the depth limit)


def _overlaps(obj: SceneObject, others: list[SceneObject], margin: float = 0.3) -> bool:
    for o in others:
        if o.name in (ROOM_WALL, "floor"):
            continue
        if np.linalg.norm(obj.center_xy - o.center_xy) < obj.radius_xy + o.radius_xy + margin:
            return True
    return False


def build_object(
    kind: str, rng: np.random.Generator, sp: float, x: float, y: float, yaw: float, doorway_in_wall_prob: float = 0.0
) -> list[SceneObject]:
    """One logical object; a doorway may come with its surrounding wall segments (separate wall instance)."""
    if kind == "doorway":
        frame, half_w, top = shapes.doorway_local(rng, sp)
        objs = [shapes.place(frame, CLASS_IDS["doorway"], "doorway", x, y, yaw)]
        if rng.random() < doorway_in_wall_prob:
            walls = shapes.doorway_wall_local(rng, sp, half_w, top)
            objs.append(shapes.place(walls, CLASS_IDS["wall"], "wall_segment", x, y, yaw))
        return objs
    if kind == "furniture":
        local, kind_ = shapes.furniture_local(rng, sp)
        return [shapes.place(local, CLASS_IDS["furniture"], "furniture", x, y, yaw, variant=kind_)]
    if kind == "debris":
        return [shapes.place(shapes.debris_local(rng, sp), CLASS_IDS["debris"], "debris", x, y, yaw)]
    if kind == "person":
        local, pose = shapes.person_local(rng, sp)
        return [shapes.place(local, CLASS_IDS["person"], "person", x, y, yaw, variant=pose)]
    raise ValueError(kind)


def make_floor(sp: float) -> SceneObject:
    """Floor plane. Its returns are labeled NOISE (background), not a class (ADR-0010)."""
    obj = shapes.place(shapes.floor_local(sp), CLASS_IDS["wall"], "floor", 0.0, 0.0, 0.0)
    obj.point_label = NOISE
    obj.reflectivity_override = 0.8
    return obj


def random_scene(rng: np.random.Generator, sim: SimConfig, sensor: SensorConfig) -> Scene:
    sp = sim.sample_spacing_m
    objects: list[SceneObject] = []
    max_r = sensor.max_range_m

    if rng.random() < sim.floor_prob:
        objects.append(make_floor(sp))
    depth_limit = max_r - 0.4
    if rng.random() < sim.back_wall_prob:
        wx = rng.uniform(3.5, max_r - 0.2)
        yaw = float(np.clip(rng.normal(0, math.radians(20)), -math.radians(45), math.radians(45)))
        width = rng.uniform(4.0, 7.0)
        objects.append(shapes.place(shapes.wall_local(width, 2.6, sp), CLASS_IDS["wall"], ROOM_WALL, wx, 0.0, yaw))
        depth_limit = wx - 0.6
    if rng.random() < sim.side_wall_prob:
        side = rng.choice([-1.0, 1.0])
        sy, sx = side * rng.uniform(1.5, 2.5), rng.uniform(2.0, 4.0)
        # yaw 90°: wall faces run along x, nearly parallel to the line of sight
        objects.append(shapes.place(shapes.wall_local(rng.uniform(3.0, 5.0), 2.6, sp), CLASS_IDS["wall"], ROOM_WALL, sx, sy, math.pi / 2))

    kinds = ["doorway", "furniture", "debris", "person"]
    w = np.asarray(sim.object_weights, dtype=float)
    n = int(rng.integers(sim.min_objects, sim.max_objects + 1))
    for _ in range(n):
        kind = str(rng.choice(kinds, p=w / w.sum()))
        for _attempt in range(30):
            x = rng.uniform(1.0, max(1.2, depth_limit))
            az = rng.uniform(-math.radians(45), math.radians(45))
            y = x * math.tan(az)
            yaw = rng.uniform(-math.pi, math.pi) if kind != "doorway" else rng.normal(0, math.radians(15))
            objs = build_object(kind, rng, sp, x, y, yaw, sim.doorway_in_wall_prob)
            if not any(_overlaps(o, objects) for o in objs):
                objects.extend(objs)
                break
    return Scene(objects)
