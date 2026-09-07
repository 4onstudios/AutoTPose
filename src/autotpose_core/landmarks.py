"""Blender-independent heuristic landmarks for upright humanoid meshes."""

from __future__ import annotations

from .contracts import Landmark, LandmarkDetectionResult, MeshSnapshot, Vec3


def detect_humanoid_landmarks(snapshot: MeshSnapshot) -> LandmarkDetectionResult:
    """Estimate a basic biped skeleton from an upright, front-facing mesh."""
    if not snapshot.vertices:
        raise ValueError("Cannot infer landmarks from an empty mesh.")

    minimum = Vec3(
        min(vertex.x for vertex in snapshot.vertices),
        min(vertex.y for vertex in snapshot.vertices),
        min(vertex.z for vertex in snapshot.vertices),
    )
    maximum = Vec3(
        max(vertex.x for vertex in snapshot.vertices),
        max(vertex.y for vertex in snapshot.vertices),
        max(vertex.z for vertex in snapshot.vertices),
    )
    width = maximum.x - minimum.x
    depth = maximum.y - minimum.y
    height = maximum.z - minimum.z
    if width <= 1e-6 or height <= 1e-6:
        raise ValueError("Mesh bounds are too small to infer a humanoid skeleton.")

    center_x = (minimum.x + maximum.x) / 2
    center_y = (minimum.y + maximum.y) / 2

    def point(horizontal: float, vertical: float, depth_offset: float = 0.0) -> Vec3:
        return Vec3(center_x + horizontal, center_y + depth_offset, minimum.z + height * vertical)

    half_width = max(width / 2, height * 0.08)
    landmarks = [
        Landmark("pelvis", point(0, 0.48)),
        Landmark("spine", point(0, 0.56)),
        Landmark("chest", point(0, 0.67)),
        Landmark("neck", point(0, 0.78)),
        Landmark("head", point(0, 0.94)),
    ]
    for suffix, sign in (("L", 1), ("R", -1)):
        landmarks.extend((
            Landmark(f"shoulder.{suffix}", point(sign * half_width * 0.34, 0.67)),
            Landmark(f"elbow.{suffix}", point(sign * half_width * 1.06, 0.61)),
            Landmark(f"wrist.{suffix}", point(sign * half_width * 1.62, 0.55)),
            Landmark(f"hand_tip.{suffix}", point(sign * half_width * 1.82, 0.53)),
            Landmark(f"hip.{suffix}", point(sign * half_width * 0.28, 0.48)),
            Landmark(f"knee.{suffix}", point(sign * half_width * 0.34, 0.26)),
            Landmark(f"ankle.{suffix}", point(sign * half_width * 0.31, 0.07)),
        ))

    width_ratio = width / height
    confidence = 0.7 if 0.18 <= width_ratio <= 1.2 else 0.5
    warnings = []
    if depth > height * 0.9:
        confidence -= 0.1
        warnings.append("Unusually deep mesh bounds may indicate props or a non-humanoid shape.")
    if not 0.18 <= width_ratio <= 1.2:
        warnings.append("Mesh proportions are outside the expected upright humanoid range.")

    return LandmarkDetectionResult(
        landmarks=tuple(landmarks),
        confidence=max(0.0, confidence),
        warnings=tuple(warnings),
        metadata={"height": height, "width": width, "depth": depth},
    )
