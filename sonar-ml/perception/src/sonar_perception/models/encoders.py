"""Encoders -> 128-d embedding -> linear head. UNTESTED until torch is installed.

Input shapes (from sonar_perception.views):
  pointnet: [B, 5, N]          (dx, dy, dz, z_abs, intensity) x N points
  bev:      [B, 4, 32, 32]     top + front views, occupancy + max intensity
  voxel:    [B, 2, 16, 16, 16] occupancy + max intensity
"""

from __future__ import annotations

import torch
from torch import nn

EMBED_DIM = 128


class PointNetEncoder(nn.Module):
    def __init__(self, in_dim: int = 5, embed_dim: int = EMBED_DIM) -> None:
        super().__init__()
        layers, dims = [], [in_dim, 64, 128, 256]
        for a, b in zip(dims[:-1], dims[1:]):
            layers += [nn.Conv1d(a, b, 1), nn.BatchNorm1d(b), nn.ReLU()]
        self.mlp = nn.Sequential(*layers)
        self.fc = nn.Sequential(nn.Linear(256, embed_dim), nn.ReLU())

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc(self.mlp(x).max(dim=2).values)


def _conv_block(conv: type[nn.Module], bn: type[nn.Module], pool: type[nn.Module], a: int, b: int) -> nn.Sequential:
    return nn.Sequential(conv(a, b, 3, padding=1), bn(b), nn.ReLU(), pool(2))


class BEVEncoder(nn.Module):
    def __init__(self, in_ch: int = 4, embed_dim: int = EMBED_DIM) -> None:
        super().__init__()
        blk = lambda a, b: _conv_block(nn.Conv2d, nn.BatchNorm2d, nn.MaxPool2d, a, b)  # noqa: E731
        self.net = nn.Sequential(blk(in_ch, 32), blk(32, 64), blk(64, 128), nn.AdaptiveAvgPool2d(1), nn.Flatten())
        self.fc = nn.Sequential(nn.Linear(128, embed_dim), nn.ReLU())

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc(self.net(x))


class VoxelEncoder(nn.Module):
    def __init__(self, in_ch: int = 2, embed_dim: int = EMBED_DIM) -> None:
        super().__init__()
        blk = lambda a, b: _conv_block(nn.Conv3d, nn.BatchNorm3d, nn.MaxPool3d, a, b)  # noqa: E731
        self.net = nn.Sequential(blk(in_ch, 16), blk(16, 32), blk(32, 64), nn.AdaptiveAvgPool3d(1), nn.Flatten())
        self.fc = nn.Sequential(nn.Linear(64, embed_dim), nn.ReLU())

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc(self.net(x))


class ClusterClassifier(nn.Module):
    def __init__(self, encoder: nn.Module, n_classes: int, embed_dim: int = EMBED_DIM) -> None:
        super().__init__()
        self.encoder = encoder
        self.head = nn.Sequential(nn.Dropout(0.3), nn.Linear(embed_dim, n_classes))

    def embed(self, x: torch.Tensor) -> torch.Tensor:
        return self.encoder(x)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.encoder(x))


def make_encoder(name: str) -> nn.Module:
    return {"pointnet": PointNetEncoder, "bev": BEVEncoder, "voxel": VoxelEncoder}[name]()
