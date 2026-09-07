"""Runtime-neutral contracts for AutoTPose.

This package intentionally has no Blender dependency. It defines the data boundary
that a future compiled solver can implement without changing Blender-facing code.
"""

from .contracts import (
    BoneSnapshot,
    Landmark,
    LandmarkDetectionResult,
    MeshSnapshot,
    PoseBoneTarget,
    RigSnapshot,
    SolveRequest,
    SolveResult,
    SkinningOptions,
    Vec3,
)
from .interface import Solver
from .landmarks import detect_humanoid_landmarks
from .skinning import compute_skin_weights

__all__ = [
    "BoneSnapshot",
    "Landmark",
    "LandmarkDetectionResult",
    "MeshSnapshot",
    "PoseBoneTarget",
    "RigSnapshot",
    "SolveRequest",
    "SolveResult",
    "SkinningOptions",
    "Solver",
    "Vec3",
    "detect_humanoid_landmarks",
    "compute_skin_weights",
]
