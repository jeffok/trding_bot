from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _sigmoid(z: float) -> float:
    # numerically stable sigmoid
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


@dataclass
class OnlineLogisticRegression:
    """Lightweight online logistic regression (SGD) for online learning.

    - No heavy deps (no sklearn)
    - partial_fit per sample
    - Persistable via to_dict()/from_dict()
    """

    dim: int
    lr: float = 0.05
    l2: float = 1e-6
    bias: float = 0.0
    w: Optional[List[float]] = None
    seen: int = 0
    version: int = 1

    def __post_init__(self) -> None:
        if self.w is None:
            self.w = [0.0] * int(self.dim)
        if len(self.w) != int(self.dim):
            self.w = (list(self.w)[: int(self.dim)] + [0.0] * int(self.dim))[: int(self.dim)]

    def predict_proba(self, x: List[float]) -> float:
        if not x:
            return 0.5
        z = float(self.bias)
        n = min(len(x), len(self.w or []))
        for i in range(n):
            z += float(self.w[i]) * float(x[i])
        return float(_sigmoid(z))

    def partial_fit(self, x: List[float], y: int) -> float:
        y = 1 if int(y) == 1 else 0
        p = self.predict_proba(x)
        err = p - float(y)
        n = min(len(x), len(self.w or []))
        for i in range(n):
            xi = float(x[i])
            wi = float(self.w[i])
            self.w[i] = wi - self.lr * (err * xi + self.l2 * wi)
        self.bias = float(self.bias) - self.lr * err
        self.seen += 1
        return float(p)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dim": int(self.dim),
            "lr": float(self.lr),
            "l2": float(self.l2),
            "bias": float(self.bias),
            "w": list(self.w or []),
            "seen": int(self.seen),
            "version": int(self.version),
        }

    @staticmethod
    def from_dict(d: Dict[str, Any], *, fallback_dim: int) -> "OnlineLogisticRegression":
        dim = int(d.get("dim") or fallback_dim)
        return OnlineLogisticRegression(
            dim=dim,
            lr=float(d.get("lr") or 0.05),
            l2=float(d.get("l2") or 1e-6),
            bias=float(d.get("bias") or 0.0),
            w=list(d.get("w") or [0.0] * dim),
            seen=int(d.get("seen") or 0),
            version=int(d.get("version") or 1),
        )
