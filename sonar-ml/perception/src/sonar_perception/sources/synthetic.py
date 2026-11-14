from __future__ import annotations

from collections.abc import Iterator
import math
from dataclasses import asdict, replace

import numpy as np

from ..config import EnvironmentConfig, SensorConfig, SimConfig, SweepConfig
from ..frame import SonarFrame
from ..grid import apply_sensor_response, extract_points, rasterize
from ..sim import Scene, random_scene, simulate_returns
from ..sim.shapes import rotation, transform
from .base import SensorSource


def simulate_frame(
    scene: Scene,
    sensor: SensorConfig,
    env: EnvironmentConfig,
    sim: SimConfig,
    rng: np.random.Generator,
    timestamp: float = 0.0,
    scene_id: int | None = None,
) -> SonarFrame:
    """Scene -> labeled SonarFrame (returns -> volume -> blur/TVG/noise -> points).

    With sensor.tilt_deg != 0 the scene is simulated in the tilted sensor frame
    (the volume lives there), and the extracted points are rotated back to the
    level body frame, as a real system would do with an IMU.
    """
    grid = sensor.grid()
    rot = rotation(pitch=math.radians(sensor.tilt_deg))  # columns = sensor axes in level frame
    sim_scene = scene
    if sensor.tilt_deg:
        sim_scene = Scene([replace(o, surface=transform(o.surface, rot.T)) for o in scene.objects])
    ret = simulate_returns(sim_scene, sensor, env, sim, rng)
    vol, label_vol, inst_vol = rasterize(ret, grid)
    vol = apply_sensor_response(vol, grid, sensor, env, rng)
    points, labels, insts = extract_points(
        vol, grid, sensor.point_threshold_db, label_vol, inst_vol, noise_margin_db=sensor.noise_margin_db
    )
    if sensor.tilt_deg and len(points):
        points = points.copy()
        points[:, :3] = points[:, :3] @ rot.T
    n = len(points)
    return SonarFrame(
        timestamp=timestamp,
        grid=grid,
        volume=vol,
        points=points,
        meta={
            "source": "synthetic",
            "sensor_id": sensor.sensor_id,
            "speed_of_sound_assumed": sensor.speed_of_sound_assumed,
            "tilt_deg": sensor.tilt_deg,
            "temperature_c": env.temperature_c,
            "conditions": asdict(env),
            "scene_id": scene_id,
            "objects": scene.class_counts(),
            "object_list": scene.object_list(),
        },
        point_labels=labels if labels is not None else np.full(n, -1, np.int16),
        point_instances=insts if insts is not None else np.full(n, -1, np.int32),
    )


def _voxel_fuse(points: np.ndarray, labels: np.ndarray, insts: np.ndarray, voxel: float,
                pose_ids: np.ndarray | None = None, min_views: int = 1):
    """Voxel-downsample fused points; keep the strongest point (and its labels) per voxel.

    With min_views > 1, a voxel survives only if points from at least that many
    distinct poses fell in it or its 26 neighbors (a little slack for pose blur).
    """
    if len(points) == 0:
        return points, labels, insts
    keys = np.floor(points[:, :3] / voxel).astype(np.int64)
    order = np.argsort(-points[:, 3], kind="stable")  # strongest first
    uniq, first = np.unique(keys[order], axis=0, return_index=True)
    keep = order[first]
    if min_views > 1 and pose_ids is not None:
        # set of poses per voxel, as a bitmask
        _, inv = np.unique(keys, axis=0, return_inverse=True)
        inv = inv.ravel()
        masks = np.zeros(len(uniq), np.int64)
        np.bitwise_or.at(masks, inv, (1 << pose_ids.astype(np.int64)))
        lookup = {tuple(k): m for k, m in zip(uniq.tolist(), masks.tolist())}
        offsets = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)]
        ok = np.zeros(len(uniq), bool)
        for i, k in enumerate(uniq.tolist()):
            m = 0
            for dx, dy, dz in offsets:
                m |= lookup.get((k[0] + dx, k[1] + dy, k[2] + dz), 0)
            ok[i] = bin(m).count("1") >= min_views
        keep = keep[ok]
    return points[keep], labels[keep], insts[keep]


def simulate_sweep(
    scene: Scene,
    sensor: SensorConfig,
    env: EnvironmentConfig,
    sim: SimConfig,
    sweep: SweepConfig,
    rng: np.random.Generator,
    timestamp: float = 0.0,
    scene_id: int | None = None,
) -> SonarFrame:
    """Simulate one frame per sweep pose and fuse the point clouds (ADR-0013).

    Pose k: yaw_k in [-span/2, +span/2], forward offset x_k in [-step/2, +step/2]
    (so the middle pose is the reference). Each pose's scene is expressed in that
    pose's body frame, simulated (independent noise), and its points mapped back
    to the reference frame. The returned volume is the reference pose's.
    """
    if not sweep.enabled:
        return simulate_frame(scene, sensor, env, sim, rng, timestamp, scene_id)
    yaws = np.radians(np.linspace(-sweep.yaw_span_deg / 2, sweep.yaw_span_deg / 2, sweep.n_poses))
    xs = np.linspace(-sweep.step_m / 2, sweep.step_m / 2, sweep.n_poses)
    pts, labs, insts, poses, ref = [], [], [], [], None
    for k, (yaw, x0) in enumerate(zip(yaws, xs)):
        rz = rotation(yaw=float(yaw))
        t = np.array([x0, 0.0, 0.0])
        # world(reference) -> pose frame: p' = Rz^T (p - t)
        posed = Scene([replace(o, surface=transform(transform(o.surface, np.eye(3), -t), rz.T)) for o in scene.objects])
        f = simulate_frame(posed, sensor, env, sim, rng, timestamp, scene_id)
        if k == sweep.n_poses // 2:
            ref = f
        if len(f.points):
            p = f.points.copy()
            p[:, :3] = p[:, :3] @ rz.T + t  # pose frame -> reference
            pts.append(p)
            labs.append(f.point_labels)
            insts.append(f.point_instances)
            poses.append(np.full(len(p), k))
    if pts:
        P, L, I = _voxel_fuse(np.concatenate(pts), np.concatenate(labs), np.concatenate(insts), sweep.fuse_voxel_m,
                              np.concatenate(poses), sweep.min_views)
    else:
        P, L, I = np.zeros((0, 4), np.float32), np.zeros(0, np.int16), np.zeros(0, np.int32)
    meta = dict(ref.meta)
    meta["sweep"] = asdict(sweep)
    return SonarFrame(timestamp, ref.grid, ref.volume, P.astype(np.float32), meta, L.astype(np.int16), I.astype(np.int32))


class SyntheticSource(SensorSource):
    """Random simulated scenes. `env=None` randomizes conditions per frame."""

    def __init__(
        self,
        n_frames: int | None = None,
        seed: int = 0,
        sensor: SensorConfig | None = None,
        env: EnvironmentConfig | None = None,
        sim: SimConfig | None = None,
        sweep: SweepConfig | None = None,
    ) -> None:
        self.sweep = sweep or SweepConfig()
        self.n_frames = n_frames
        self.seed = seed
        self.sensor = sensor or SensorConfig()
        self.env = env
        self.sim = sim or SimConfig()

    def frame(self, i: int) -> SonarFrame:
        rng = np.random.default_rng([self.seed, i])
        env = self.env or EnvironmentConfig.random(rng)
        scene = random_scene(rng, self.sim, self.sensor)
        return simulate_sweep(scene, self.sensor, env, self.sim, self.sweep, rng, timestamp=float(i), scene_id=i)

    def frames(self) -> Iterator[SonarFrame]:
        i = 0
        while self.n_frames is None or i < self.n_frames:
            yield self.frame(i)
            i += 1
