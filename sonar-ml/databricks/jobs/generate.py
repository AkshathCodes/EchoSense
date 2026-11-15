"""Job task 1: simulate N scenes in parallel with Spark and append them to `landing_frames`.

Each Spark task simulates its own slice of scene indices with
`sonar_perception.lakehouse.simulate_scene` (same RNG stream as the local
`generate` CLI, so scene i of seed s is identical everywhere).
"""

import argparse
import os

from pyspark.sql import SparkSession

from sonar_perception import lakehouse as L


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--n-scenes", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--env-mode", default="random")
    ap.add_argument("--pings", type=int, default=4)
    ap.add_argument("--sweep", type=int, default=1)
    ap.add_argument("--min-views", type=int, default=1)
    ap.add_argument("--tilt", type=float, default=0.0)
    ap.add_argument("--partitions", type=int, default=64)
    a = ap.parse_args()

    spark = SparkSession.builder.getOrCreate()
    fq = f"{a.catalog}.{a.schema}"

    # Landing folders for Auto Loader (recorded .npz frames, acoustic CSVs); empty is fine.
    landing = f"/Volumes/{a.catalog}/{a.schema}/landing"
    for sub in ("frames", "acoustic"):
        os.makedirs(f"{landing}/{sub}", exist_ok=True)

    sensing = {"pings": a.pings, "tilt": a.tilt, "sweep": a.sweep, "min_views": a.min_views}
    scenes = (
        spark.range(a.n_scenes)
        .withColumnRenamed("id", "scene_index")
        .repartition(max(1, min(a.partitions, a.n_scenes)))
    )
    frames = scenes.mapInPandas(
        L.generate_partitions(a.run_id, a.seed, a.env_mode, sensing), schema=L.FRAME_SCHEMA
    )
    frames.write.mode("append").saveAsTable(f"{fq}.landing_frames")

    n = spark.table(f"{fq}.landing_frames").where(f"run_id = '{a.run_id}'").count()
    print(f"run {a.run_id}: wrote {n} frames (seed {a.seed}, env {a.env_mode}, sensing {sensing})")
    if n != a.n_scenes:
        raise RuntimeError(f"expected {a.n_scenes} frames, found {n}")


if __name__ == "__main__":
    main()
