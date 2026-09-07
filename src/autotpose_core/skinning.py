"""Topology-independent skinning weights for imported character meshes."""

from __future__ import annotations

from math import exp

from .contracts import MeshSnapshot, RigSnapshot, SkinningOptions


def _distance_to_segment(vertex, head, tail):
    axis_x, axis_y, axis_z = tail.x - head.x, tail.y - head.y, tail.z - head.z
    length_squared = axis_x * axis_x + axis_y * axis_y + axis_z * axis_z
    if length_squared <= 1e-12:
        return ((vertex.x - head.x) ** 2 + (vertex.y - head.y) ** 2 + (vertex.z - head.z) ** 2) ** 0.5
    factor = max(0.0, min(1.0, (
        (vertex.x - head.x) * axis_x + (vertex.y - head.y) * axis_y + (vertex.z - head.z) * axis_z
    ) / length_squared))
    nearest_x, nearest_y, nearest_z = head.x + factor * axis_x, head.y + factor * axis_y, head.z + factor * axis_z
    return ((vertex.x - nearest_x) ** 2 + (vertex.y - nearest_y) ** 2 + (vertex.z - nearest_z) ** 2) ** 0.5


def compute_skin_weights(mesh: MeshSnapshot, rig: RigSnapshot, options: SkinningOptions = SkinningOptions()):
    """Return normalized bone influences for every mesh vertex.

    This fallback needs only vertex positions and bone segments, so it remains
    usable for non-manifold or disconnected GLB geometry that defeats bone heat.
    """
    if options.max_influences < 1:
        raise ValueError("max_influences must be at least 1")
    bones = [bone for bone in rig.bones if bone.deform]
    if not bones:
        raise ValueError("Rig must contain at least one deform bone.")

    influences = []
    for vertex in mesh.vertices:
        scored = sorted(
            ((bone.name, exp(-_distance_to_segment(vertex, bone.head, bone.tail) ** 2)) for bone in bones),
            key=lambda item: item[1],
            reverse=True,
        )[:options.max_influences]
        total = sum(weight for _, weight in scored)
        normalized = [(name, weight / total) for name, weight in scored if weight / total >= options.prune_weight]
        if not normalized:
            normalized = [(scored[0][0], 1.0)]
        else:
            normalization = sum(weight for _, weight in normalized)
            normalized = [(name, weight / normalization) for name, weight in normalized]
        influences.append(tuple(normalized))
    return tuple(influences)
