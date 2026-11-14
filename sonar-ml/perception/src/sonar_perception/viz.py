"""Quick matplotlib 3D viewer for a SonarFrame (reference only; the app team builds the real UI)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .frame import SonarFrame
from .sim import CLASSES

COLORS = {-1: "#9e9e9e", 0: "#5470c6", 1: "#91cc75", 2: "#fac858", 3: "#ee6666", 4: "#9a60b4"}


def plot_frame(frame: SonarFrame, color_by: str = "label", cluster_ids: np.ndarray | None = None, out: str | Path | None = None, title: str | None = None):
    import matplotlib

    if out is not None:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    p = frame.points
    fig = plt.figure(figsize=(9, 7))
    ax = fig.add_subplot(projection="3d")
    if color_by == "label" and frame.point_labels is not None:
        for lab in np.unique(frame.point_labels):
            m = frame.point_labels == lab
            ax.scatter(p[m, 0], p[m, 1], p[m, 2], s=2, c=COLORS.get(int(lab), "k"), label=CLASSES.get(int(lab), "noise"))
        ax.legend(markerscale=5, loc="upper left")
    elif color_by == "cluster" and cluster_ids is not None:
        ax.scatter(p[:, 0], p[:, 1], p[:, 2], s=2, c=cluster_ids, cmap="tab20")
    else:
        ax.scatter(p[:, 0], p[:, 1], p[:, 2], s=2, c=p[:, 3], cmap="viridis")
    ax.scatter([0], [0], [0], marker="^", s=80, c="k")
    ax.set_xlabel("x forward (m)"), ax.set_ylabel("y left (m)"), ax.set_zlabel("z up (m)")
    ax.set_box_aspect((np.ptp(p[:, 0]) + 1e-3, np.ptp(p[:, 1]) + 1e-3, np.ptp(p[:, 2]) + 1e-3)) if len(p) else None
    ax.set_title(title or f"{frame.meta.get('source')} · {frame.meta.get('conditions', {}).get('name', '')} · {len(p)} points")
    if out is not None:
        fig.savefig(out, dpi=130, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()
    return fig
