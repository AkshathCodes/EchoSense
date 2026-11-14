"""PyTorch cluster classifiers (ADR-0007). Requires `pip install -e ".[torch]"`.

Imported lazily so the rest of the package works without torch.
"""

MODEL_NAMES = ("pointnet", "bev", "voxel")
