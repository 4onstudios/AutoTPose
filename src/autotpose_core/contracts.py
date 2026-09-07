"""Serializable, Blender-independent data contracts for pose solving.

Keep this module deliberately boring: plain dataclasses, primitive types, and no
`bpy`/`mathutils` imports. A future compiled core should be able to mirror
these structures directly.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Vec3:
    x: float
    y: float
    z: float

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.z]

    @classmethod
    def from_value(cls, value: "Vec3 | list[float] | tuple[float, float, float]") -> "Vec3":
        if isinstance(value, cls):
            return value
        if len(value) != 3:
            raise ValueError("Vec3 requires exactly three components")
        return cls(float(value[0]), float(value[1]), float(value[2]))


@dataclass(frozen=True, slots=True)
class BoneSnapshot:
    name: str
    parent: str | None
    head: Vec3
    tail: Vec3
    deform: bool = True
    children: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RigSnapshot:
    bones: tuple[BoneSnapshot, ...]
    source_name: str = ""

    def by_name(self) -> dict[str, BoneSnapshot]:
        return {bone.name: bone for bone in self.bones}


@dataclass(frozen=True, slots=True)
class MeshSnapshot:
    vertices: tuple[Vec3, ...]
    source_name: str = ""


@dataclass(frozen=True, slots=True)
class Landmark:
    name: str
    position: Vec3


@dataclass(frozen=True, slots=True)
class LandmarkDetectionResult:
    landmarks: tuple[Landmark, ...]
    confidence: float
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def by_name(self) -> dict[str, Landmark]:
        return {landmark.name: landmark for landmark in self.landmarks}


@dataclass(frozen=True, slots=True)
class SkinningOptions:
    max_influences: int = 4
    prune_weight: float = 0.01


@dataclass(frozen=True, slots=True)
class SolveRequest:
    target_pose: str = "T"
    straighten_forearms: bool = True
    preserve_roll: bool = True


@dataclass(frozen=True, slots=True)
class PoseBoneTarget:
    bone: str
    direction: Vec3
    confidence: float = 1.0
    role: str = ""


@dataclass(frozen=True, slots=True)
class SolveResult:
    targets: tuple[PoseBoneTarget, ...]
    confidence: float
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation for adapter/native boundaries."""
        raw = asdict(self)
        return raw
