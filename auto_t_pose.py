"""
Auto T-Pose for humanoid armatures in Blender.

Designed for exported/deform skeletons (Mixamo, many FBX/GLB rigs, etc.).
It tries bone names first and falls back to geometry/hierarchy heuristics.

IMPORTANT:
- This does NOT rig an unrigged mesh.
- It aligns the upper-arm + forearm chains into a T shape.
- Bone roll / palm orientation is preserved as much as possible; it is not
  guaranteed to match a specific engine's canonical hand roll.
- APPLY_AS_REST_POSE is destructive. Save a backup first.
"""

import bpy
import json
import re
import sys
from collections import deque
from pathlib import Path
from mathutils import Vector, Matrix

REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"
for candidate in (str(REPO_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

# -----------------------------------------------------------------------------
# SETTINGS
# -----------------------------------------------------------------------------

APPLY_AS_REST_POSE = False   # True = bake current T-pose as the new rest pose.
RESET_POSE_FIRST = True      # Start from the armature's rest transforms.
STRAIGHTEN_FOREARMS = True   # Make elbow->wrist collinear with shoulder->elbow.
MUTE_CONSTRAINTS = False     # Try True for simple constrained rigs that resist posing.
RESTORE_CONSTRAINTS = True   # Restore constraint mute states after the operation.
VERBOSE = True

# Detection tuning
MIN_NAMED_UPPER_ARM_SCORE = 7.0
MAX_FOREARM_DEPTH = 3
BIND_METHOD = "AUTO"  # AUTO, DISTANCE, or BONE_HEAT for generated rigs.


# -----------------------------------------------------------------------------
# LOGGING / UTILITIES
# -----------------------------------------------------------------------------

def log(*args):
    if VERBOSE:
        print("[Auto T-Pose]", *args)


def compact_name(name):
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def lower_name(name):
    return name.lower()


def side_hint(name):
    """Return 'L', 'R', or None from common bone naming conventions."""
    raw = lower_name(name)
    comp = compact_name(name)

    if "left" in comp:
        return "L"
    if "right" in comp:
        return "R"

    # Suffix/prefix conventions: upper_arm.L, upperarm_l, L_UpperArm, etc.
    if re.search(r"(^|[._:\-\s])l($|[._:\-\s])", raw):
        return "L"
    if re.search(r"(^|[._:\-\s])r($|[._:\-\s])", raw):
        return "R"

    if re.search(r"[._\-]l(?:\.\d+)?$", raw) or comp.endswith("upperarml") or comp.endswith("forearml") or comp.endswith("lowerarml"):
        return "L"
    if re.search(r"[._\-]r(?:\.\d+)?$", raw) or comp.endswith("upperarmr") or comp.endswith("forearmr") or comp.endswith("lowerarmr"):
        return "R"

    if comp.startswith(("lupperarm", "larm", "lforearm", "llowerarm")):
        return "L"
    if comp.startswith(("rupperarm", "rarm", "rforearm", "rlowerarm")):
        return "R"

    return None


def bone_length(pb):
    return max((pb.tail - pb.head).length, 1e-8)


def descendants_with_depth(pb, max_depth=3):
    out = []
    frontier = [(child, 1) for child in pb.children]
    while frontier:
        b, depth = frontier.pop(0)
        out.append((b, depth))
        if depth < max_depth:
            frontier.extend((c, depth + 1) for c in b.children)
    return out


def common_ancestor_distance(a, b, max_depth=12):
    """Return summed distance to nearest common ancestor, or None."""
    amap = {}
    cur = a
    d = 0
    while cur and d <= max_depth:
        amap[cur.name] = d
        cur = cur.parent
        d += 1

    cur = b
    d2 = 0
    best = None
    while cur and d2 <= max_depth:
        if cur.name in amap:
            total = amap[cur.name] + d2
            if best is None or total < best:
                best = total
        cur = cur.parent
        d2 += 1
    return best


def looks_like_control_or_non_arm(name):
    c = compact_name(name)
    bad = (
        "finger", "thumb", "index", "middle", "ring", "pinky", "toe",
        "foot", "calf", "shin", "thigh", "upleg", "lowerleg",
        "head", "neck", "spine", "pelvis", "hip", "jaw", "eye",
        "breast", "weapon", "socket", "twist", "roll", "helper",
        "ik", "pole", "target", "ctrl", "control", "mch", "org",
    )
    return any(x in c for x in bad)


# -----------------------------------------------------------------------------
# ARMATURE PICKING
# -----------------------------------------------------------------------------

def find_armature():
    obj = bpy.context.active_object

    if obj:
        if obj.type == 'ARMATURE':
            return obj
        if obj.type == 'MESH':
            arm = obj.find_armature()
            if arm:
                return arm

    selected_arms = [o for o in bpy.context.selected_objects if o.type == 'ARMATURE']
    if selected_arms:
        return max(selected_arms, key=lambda o: len(o.data.bones))

    arms = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    if arms:
        return max(arms, key=lambda o: len(o.data.bones))

    return None


def scene_object_summary():
    counts = {}
    for obj in bpy.context.scene.objects:
        counts[obj.type] = counts.get(obj.type, 0) + 1
    return ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items())) or "empty scene"


def scene_meshes():
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("Cannot auto-rig: the imported scene contains no mesh geometry.")
    return meshes


def mesh_max_edge_length(meshes):
    max_length = 0.0
    for mesh in meshes:
        world_vertices = [mesh.matrix_world @ vertex.co for vertex in mesh.data.vertices]
        for edge in mesh.data.edges:
            max_length = max(
                max_length,
                (world_vertices[edge.vertices[0]] - world_vertices[edge.vertices[1]]).length,
            )
    return max_length


def remove_overstretched_faces(meshes, max_edge_length):
    if max_edge_length <= 0:
        raise ValueError("max_edge_length must be positive")

    removed_faces = 0
    for obj in meshes:
        mesh = obj.data
        world_vertices = [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
        face_indices = []
        for polygon in mesh.polygons:
            vertices = list(polygon.vertices)
            for index, first in enumerate(vertices):
                second = vertices[(index + 1) % len(vertices)]
                if (world_vertices[first] - world_vertices[second]).length > max_edge_length:
                    face_indices.append(polygon.index)
                    break

        if not face_indices:
            continue

        import bmesh

        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        faces = [bm.faces[index] for index in face_indices if index < len(bm.faces)]
        bmesh.ops.delete(bm, geom=faces, context="FACES_ONLY")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
        removed_faces += len(face_indices)

    return removed_faces


def remove_rough_edge_faces(meshes, min_long_edge, min_aspect_ratio=15.0):
    if min_long_edge <= 0:
        raise ValueError("min_long_edge must be positive")
    if min_aspect_ratio <= 1:
        raise ValueError("min_aspect_ratio must be greater than 1")

    removed_faces = 0
    for obj in meshes:
        mesh = obj.data
        world_vertices = [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
        face_indices = []
        for polygon in mesh.polygons:
            vertices = list(polygon.vertices)
            lengths = [
                (world_vertices[vertices[index]] - world_vertices[vertices[(index + 1) % len(vertices)]]).length
                for index in range(len(vertices))
            ]
            positive_lengths = [length for length in lengths if length > 1e-9]
            if not positive_lengths:
                face_indices.append(polygon.index)
                continue

            longest = max(positive_lengths)
            shortest = min(positive_lengths)
            if longest >= min_long_edge and longest / shortest >= min_aspect_ratio:
                face_indices.append(polygon.index)

        if not face_indices:
            continue

        import bmesh

        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        faces = [bm.faces[index] for index in face_indices if index < len(bm.faces)]
        bmesh.ops.delete(bm, geom=faces, context="FACES_ONLY")
        loose_edges = [edge for edge in bm.edges if not edge.link_faces]
        if loose_edges:
            bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
        loose_vertices = [vertex for vertex in bm.verts if not vertex.link_edges]
        if loose_vertices:
            bmesh.ops.delete(bm, geom=loose_vertices, context="VERTS")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
        removed_faces += len(face_indices)

    return removed_faces


def remove_tiny_mesh_islands(meshes, max_extent, max_faces=8):
    if max_extent <= 0:
        raise ValueError("max_extent must be positive")
    if max_faces < 1:
        raise ValueError("max_faces must be at least 1")

    removed_faces = 0
    for obj in meshes:
        mesh = obj.data

        import bmesh

        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

        seen = set()
        faces_to_delete = []
        for face in bm.faces:
            if face in seen:
                continue
            queue = deque([face])
            seen.add(face)
            component_faces = []
            component_vertices = set()
            while queue:
                current = queue.popleft()
                component_faces.append(current)
                component_vertices.update(current.verts)
                for edge in current.edges:
                    for neighbor in edge.link_faces:
                        if neighbor not in seen:
                            seen.add(neighbor)
                            queue.append(neighbor)

            if len(component_faces) > max_faces:
                continue
            world_vertices = [obj.matrix_world @ vertex.co for vertex in component_vertices]
            extent = 0.0
            for axis in ("x", "y", "z"):
                values = [getattr(vertex, axis) for vertex in world_vertices]
                extent = max(extent, max(values) - min(values))
            if extent <= max_extent:
                faces_to_delete.extend(component_faces)

        if faces_to_delete:
            bmesh.ops.delete(bm, geom=faces_to_delete, context="FACES_ONLY")
            removed_faces += len(faces_to_delete)
        loose_edges = [edge for edge in bm.edges if not edge.link_faces]
        if loose_edges:
            bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
        loose_vertices = [vertex for vertex in bm.verts if not vertex.link_edges]
        if loose_vertices:
            bmesh.ops.delete(bm, geom=loose_vertices, context="VERTS")

        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

    return removed_faces


def smooth_mesh_normals(meshes):
    for obj in meshes:
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        obj.data.update()


def detect_mesh_landmarks(meshes):
    source_dir = Path(__file__).resolve().parent / "src"
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))
    from autotpose_core import MeshSnapshot, Vec3, detect_humanoid_landmarks

    vertices = tuple(
        Vec3(float(point.x), float(point.y), float(point.z))
        for mesh in meshes
        for point in (mesh.matrix_world @ vertex.co for vertex in mesh.data.vertices)
    )
    if not vertices:
        raise RuntimeError("Cannot auto-rig: imported mesh objects contain no vertices.")
    return detect_humanoid_landmarks(MeshSnapshot(vertices, source_name=" + ".join(mesh.name for mesh in meshes)))


def deform_bone_names(armature):
    return [bone.name for bone in armature.data.bones if bone.use_deform]


def weight_coverage(mesh, bone_names):
    indices = {group.index for group in mesh.vertex_groups if group.name in bone_names}
    if not indices or not mesh.data.vertices:
        return 0.0
    return sum(
        any(assignment.group in indices and assignment.weight > 1e-6 for assignment in vertex.groups)
        for vertex in mesh.data.vertices
    ) / len(mesh.data.vertices)


def clear_generated_binding(mesh, armature, bone_names):
    for modifier in list(mesh.modifiers):
        if modifier.type == "ARMATURE" and modifier.object == armature:
            mesh.modifiers.remove(modifier)
    for name in bone_names:
        group = mesh.vertex_groups.get(name)
        if group:
            mesh.vertex_groups.remove(group)
    if mesh.parent == armature:
        world = mesh.matrix_world.copy()
        mesh.parent = None
        mesh.matrix_world = world


def rig_snapshot_world(armature):
    from autotpose_core import BoneSnapshot, RigSnapshot, Vec3

    world = armature.matrix_world
    return RigSnapshot(tuple(
        BoneSnapshot(
            bone.name,
            bone.parent.name if bone.parent else None,
            Vec3.from_value(world @ bone.head_local),
            Vec3.from_value(world @ bone.tail_local),
            bone.use_deform,
            tuple(child.name for child in bone.children),
        )
        for bone in armature.data.bones
    ), source_name=armature.name)


def bind_distance_weights(mesh, armature):
    from autotpose_core import MeshSnapshot, SkinningOptions, Vec3, compute_skin_weights

    bone_names = deform_bone_names(armature)
    clear_generated_binding(mesh, armature, bone_names)
    vertices = tuple(
        Vec3.from_value(mesh.matrix_world @ vertex.co)
        for vertex in mesh.data.vertices
    )
    influences = compute_skin_weights(
        MeshSnapshot(vertices, source_name=mesh.name),
        rig_snapshot_world(armature),
        SkinningOptions(max_influences=4, prune_weight=0.01),
    )
    groups = {name: mesh.vertex_groups.new(name=name) for name in bone_names}
    for index, vertex_influences in enumerate(influences):
        for name, weight in vertex_influences:
            groups[name].add([index], weight, "REPLACE")
    modifier = mesh.modifiers.new(name="AutoTPose Armature", type="ARMATURE")
    modifier.object = armature
    modifier.use_vertex_groups = True
    modifier.use_bone_envelopes = False
    world = mesh.matrix_world.copy()
    mesh.parent = armature
    mesh.matrix_parent_inverse = armature.matrix_world.inverted()
    mesh.matrix_world = world
    if weight_coverage(mesh, bone_names) < 0.999:
        raise RuntimeError(f"Distance weights did not cover every vertex in {mesh.name}.")
    log(f"Distance-weighted {mesh.name}: 100% vertex coverage.")


def bind_meshes(meshes, armature, method):
    method = method.upper()
    if method not in {"AUTO", "DISTANCE", "BONE_HEAT"}:
        raise ValueError("Binding method must be AUTO, DISTANCE, or BONE_HEAT.")
    bone_names = deform_bone_names(armature)
    for mesh in meshes:
        if method != "DISTANCE":
            clear_generated_binding(mesh, armature, bone_names)
            bpy.ops.object.select_all(action="DESELECT")
            mesh.select_set(True)
            armature.select_set(True)
            bpy.context.view_layer.objects.active = armature
            try:
                bpy.ops.object.parent_set(type="ARMATURE_AUTO", keep_transform=True)
            except RuntimeError:
                pass
            if weight_coverage(mesh, bone_names) >= 0.985:
                log(f"Bone heat weighted {mesh.name}.")
                continue
            clear_generated_binding(mesh, armature, bone_names)
            if method == "BONE_HEAT":
                raise RuntimeError(f"Bone heat did not sufficiently weight {mesh.name}.")
            log(f"Bone heat failed for {mesh.name}; using distance-weight fallback.")
        bind_distance_weights(mesh, armature)


def bake_generated_tpose_as_rest(armature, bind_method):
    """Bake the visible T-pose mesh shape before changing generated bone rest axes."""
    meshes = [mesh for mesh in scene_meshes() if mesh.find_armature() == armature]
    if not meshes:
        raise RuntimeError("Cannot bake generated T-pose: no meshes are bound to the generated armature.")

    bpy.ops.object.mode_set(mode="OBJECT")
    for mesh in meshes:
        modifiers = [
            modifier.name
            for modifier in mesh.modifiers
            if modifier.type == "ARMATURE" and modifier.object == armature
        ]
        if len(modifiers) != 1:
            raise RuntimeError(f"Cannot bake generated T-pose: expected one armature modifier on {mesh.name}.")
        bpy.context.view_layer.objects.active = mesh
        bpy.ops.object.modifier_apply(modifier=modifiers[0])

    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.armature_apply(selected=False)
    bind_meshes(meshes, armature, bind_method)


def create_basic_humanoid_rig(bind_method=BIND_METHOD):
    """Create and bind a landmark-derived biped armature."""
    meshes = scene_meshes()
    landmarks = detect_mesh_landmarks(meshes)
    if landmarks.confidence < 0.5:
        raise RuntimeError(
            f"Auto-rig confidence {landmarks.confidence:.2f} is below 0.50. "
            "Use an upright, roughly symmetric humanoid mesh without large merged props."
        )
    for warning in landmarks.warnings:
        log("WARNING:", warning)
    points = {landmark.name: Vector(landmark.position.to_list()) for landmark in landmarks.landmarks}
    height = float(landmarks.metadata["height"])

    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
    armature = bpy.context.object
    armature.name = "AutoTPose_Rig"
    armature.data.name = "AutoTPose_Rig"
    edit_bones = armature.data.edit_bones
    edit_bones.remove(edit_bones[0])

    bones = {}

    def add_bone(name, head, tail, parent=None, connect=False, deform=True):
        bone = edit_bones.new(name)
        bone.head = head
        bone.tail = tail
        if parent is not None:
            bone.parent = bones[parent]
            bone.use_connect = connect and (bone.head - bone.parent.tail).length < height * 0.01
        bone.use_deform = deform
        bones[name] = bone

    pelvis = points["pelvis"]
    add_bone("root", pelvis - Vector((0, 0, max(height * 0.075, 0.02))), pelvis, deform=False)
    add_bone("pelvis", pelvis, points["spine"], "root", connect=True)
    add_bone("spine", points["spine"], points["chest"], "pelvis", connect=True)
    add_bone("neck", points["chest"], points["neck"], "spine", connect=True)
    add_bone("head", points["neck"], points["head"], "neck", connect=True)

    for side in ("L", "R"):
        add_bone(f"clavicle.{side}", points["chest"], points[f"shoulder.{side}"], "spine", connect=True)
        add_bone(f"upper_arm.{side}", points[f"shoulder.{side}"], points[f"elbow.{side}"], f"clavicle.{side}", connect=True)
        add_bone(f"forearm.{side}", points[f"elbow.{side}"], points[f"wrist.{side}"], f"upper_arm.{side}", connect=True)
        add_bone(f"hand.{side}", points[f"wrist.{side}"], points[f"hand_tip.{side}"], f"forearm.{side}", connect=True)
        add_bone(f"thigh.{side}", points[f"hip.{side}"], points[f"knee.{side}"], "pelvis")
        add_bone(f"shin.{side}", points[f"knee.{side}"], points[f"ankle.{side}"], f"thigh.{side}", connect=True)

    bpy.ops.object.mode_set(mode="OBJECT")
    bind_meshes(meshes, armature, bind_method)
    log(f"Created and weighted landmark-derived armature: {armature.name}")
    return armature


# -----------------------------------------------------------------------------
# NAME-BASED DETECTION
# -----------------------------------------------------------------------------

def upper_arm_name_score(pb, wanted_side=None):
    name = pb.name
    c = compact_name(name)
    s = 0.0

    if "upperarm" in c or "uparm" in c or "armupper" in c:
        s += 14.0
    elif "leftarm" in c or "rightarm" in c:
        s += 12.0
    elif c.endswith("arm") or "armfk" in c or "armdef" in c:
        s += 7.0
    elif "arm" in c:
        s += 4.0

    # Things that are not the upper arm.
    if any(x in c for x in ("forearm", "lowerarm", "hand", "wrist")):
        s -= 18.0
    if any(x in c for x in ("twist", "roll", "helper", "ik", "pole", "target")):
        s -= 10.0
    if any(x in c for x in ("finger", "thumb", "leg", "foot", "spine", "neck", "head")):
        s -= 20.0

    sh = side_hint(name)
    if wanted_side:
        if sh == wanted_side:
            s += 6.0
        elif sh is not None and sh != wanted_side:
            s -= 20.0

    if pb.bone.use_deform:
        s += 1.0

    if pb.parent:
        pc = compact_name(pb.parent.name)
        if any(x in pc for x in ("clavicle", "shoulder", "chest", "spine")):
            s += 3.0

    for ch in pb.children:
        cc = compact_name(ch.name)
        if "forearm" in cc or "lowerarm" in cc:
            s += 4.0
            break

    return s


def find_named_upper_arms(arm):
    bones = list(arm.pose.bones)
    left = max(bones, key=lambda b: upper_arm_name_score(b, "L"), default=None)
    right = max(bones, key=lambda b: upper_arm_name_score(b, "R"), default=None)

    if left and right:
        ls = upper_arm_name_score(left, "L")
        rs = upper_arm_name_score(right, "R")
        if left != right and ls >= MIN_NAMED_UPPER_ARM_SCORE and rs >= MIN_NAMED_UPPER_ARM_SCORE:
            log(f"Name detection: L={left.name} ({ls:.1f}), R={right.name} ({rs:.1f})")
            return left, right

    return None


def find_joint_node_upper_arms(arm):
    """Handle glTF rigs whose joint names label the segment's distal endpoint."""
    result = {}
    for side in ("L", "R"):
        shoulders = [
            bone for bone in arm.pose.bones
            if "shoulder" in compact_name(bone.name) and side_hint(bone.name) == side
        ]
        for shoulder in shoulders:
            elbow = next(
                (
                    child for child in shoulder.children
                    if "elbow" in compact_name(child.name) and side_hint(child.name) == side
                ),
                None,
            )
            if elbow and any(
                "wrist" in compact_name(child.name) and side_hint(child.name) == side
                for child in elbow.children
            ):
                result[side] = elbow
                break

    if "L" in result and "R" in result:
        log(
            "Joint-node detection: "
            f"L={result['L'].name}, R={result['R'].name} "
            "(shoulder nodes treated as clavicles)"
        )
        return result["L"], result["R"]
    return None


# -----------------------------------------------------------------------------
# GEOMETRY/HIERARCHY FALLBACK
# -----------------------------------------------------------------------------

def percentile(values, p):
    if not values:
        return 0.0
    vals = sorted(values)
    idx = max(0, min(len(vals) - 1, int(round((len(vals) - 1) * p))))
    return vals[idx]


def has_reasonable_child_chain(pb):
    L = bone_length(pb)
    for child, depth in descendants_with_depth(pb, 2):
        cl = bone_length(child)
        if 0.30 * L <= cl <= 1.70 * L and not looks_like_control_or_non_arm(child.name):
            return True
    return False


def geometry_candidate_bones(arm):
    bones = [b for b in arm.pose.bones if b.bone.use_deform]
    if len(bones) < 2:
        bones = list(arm.pose.bones)

    lengths = [bone_length(b) for b in bones]
    min_len = percentile(lengths, 0.55)

    out = []
    for b in bones:
        c = compact_name(b.name)
        if bone_length(b) < min_len:
            continue
        if looks_like_control_or_non_arm(b.name):
            continue
        if any(x in c for x in ("hand", "wrist", "clavicle", "shoulder")):
            continue
        if not has_reasonable_child_chain(b):
            continue
        out.append(b)
    return out


def pair_geometry_score(a, b):
    if a == b:
        return -1e9

    la = bone_length(a)
    lb = bone_length(b)
    avg = 0.5 * (la + lb)
    if avg < 1e-8:
        return -1e9

    ratio = min(la, lb) / max(la, lb)
    if ratio < 0.45:
        return -1e9

    hd = (a.head - b.head).length
    td = (a.tail - b.tail).length
    if hd < 0.20 * avg or hd > 4.0 * avg:
        return -1e9

    midpoint = (a.head + b.head) * 0.5
    out_a = (a.head - midpoint)
    out_b = (b.head - midpoint)
    if out_a.length < 1e-8 or out_b.length < 1e-8:
        return -1e9
    out_a.normalize()
    out_b.normalize()

    da = (a.tail - a.head).normalized()
    db = (b.tail - b.head).normalized()

    # Upper arms usually head outward from a shoulder pair. A-pose/downward arms
    # still retain a useful outward component.
    outward_a = da.dot(out_a)
    outward_b = db.dot(out_b)
    if outward_a < 0.05 or outward_b < 0.05:
        return -1e9

    anc = common_ancestor_distance(a, b)
    if anc is None or anc > 10:
        return -1e9

    # Mirrored limbs tend to spread more at their tails than at shoulders.
    spread_gain = (td - hd) / avg

    score = 0.0
    score += ratio * 8.0
    score += (outward_a + outward_b) * 7.0
    score += max(-2.0, min(4.0, spread_gain * 4.0))
    score += max(0.0, 6.0 - 0.65 * anc)

    # Give weak name evidence a boost even if side labels are absent.
    score += max(0.0, upper_arm_name_score(a, None)) * 0.25
    score += max(0.0, upper_arm_name_score(b, None)) * 0.25

    return score


def find_geometric_upper_arms(arm):
    candidates = geometry_candidate_bones(arm)
    if len(candidates) < 2:
        return None

    best = None
    best_score = -1e9
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            score = pair_geometry_score(a, b)
            if score > best_score:
                best_score = score
                best = (a, b)

    if best is not None and best_score > 4.0:
        log(f"Geometry fallback: A={best[0].name}, B={best[1].name}, score={best_score:.2f}")
        return best

    return None


# -----------------------------------------------------------------------------
# FOREARM DETECTION
# -----------------------------------------------------------------------------

def forearm_name_score(pb, expected_side=None, depth=1):
    c = compact_name(pb.name)
    s = 0.0

    if "forearm" in c or "lowerarm" in c:
        s += 15.0
    elif "arm" in c and "upperarm" not in c:
        s += 5.0

    if any(x in c for x in ("hand", "wrist", "finger", "thumb")):
        s -= 16.0
    if any(x in c for x in ("twist", "roll", "helper", "ik", "pole", "target", "ctrl", "control")):
        s -= 8.0

    sh = side_hint(pb.name)
    if expected_side:
        if sh == expected_side:
            s += 3.0
        elif sh is not None and sh != expected_side:
            s -= 10.0

    if pb.bone.use_deform:
        s += 1.0
    s -= 0.75 * max(0, depth - 1)
    return s


def find_forearm(upper, target_direction):
    side = side_hint(upper.name)
    desc = descendants_with_depth(upper, MAX_FOREARM_DEPTH)
    if not desc:
        return None

    if "elbow" in compact_name(upper.name):
        wrist = next(
            (
                child for child in upper.children
                if "wrist" in compact_name(child.name) and side_hint(child.name) == side
            ),
            None,
        )
        if wrist:
            log(f"Forearm for {upper.name}: {wrist.name} (joint-node hierarchy)")
            return wrist

    # First prefer strong names.
    named = []
    for b, depth in desc:
        sc = forearm_name_score(b, side, depth)
        named.append((sc, b, depth))
    named.sort(key=lambda x: x[0], reverse=True)

    if named and named[0][0] >= 8.0:
        log(f"Forearm for {upper.name}: {named[0][1].name} (name score {named[0][0]:.1f})")
        return named[0][1]

    # Geometry fallback: comparable length, close to the upper-arm tail, and
    # generally continuing outward. This also skips short twist helpers.
    ulen = bone_length(upper)
    best = None
    best_score = -1e9

    for b, depth in desc:
        c = compact_name(b.name)
        if any(x in c for x in ("hand", "wrist", "finger", "thumb", "ik", "pole", "target", "ctrl", "control")):
            continue

        blen = bone_length(b)
        ratio = min(blen, ulen) / max(blen, ulen)
        if ratio < 0.28:
            continue

        d = (b.head - upper.tail).length / ulen
        direction = (b.tail - b.head).normalized()
        outward = direction.dot(target_direction)

        score = ratio * 6.0
        score += max(-2.0, outward * 4.0)
        score += max(0.0, 4.0 - d * 5.0)
        score -= 0.75 * (depth - 1)

        if "twist" in c or "roll" in c:
            score -= 5.0

        if score > best_score:
            best_score = score
            best = b

    if best:
        log(f"Forearm for {upper.name}: {best.name} (geometry score {best_score:.1f})")
    return best


def straighten_chain_below(forearm, target_direction, torso_reference, max_depth=2):
    """Align wrist/hand bones below an already aligned forearm."""
    straightened = []
    for b, depth in descendants_with_depth(forearm, max_depth):
        c = compact_name(b.name)
        if any(x in c for x in (
            "finger", "thumb", "index", "middle", "ring", "pinky",
            "twist", "roll", "ik", "pole", "target", "ctrl", "control",
        )):
            continue
        rotate_pose_bone_axis_to(b, target_direction, torso_reference=torso_reference)
        bpy.context.view_layer.update()
        straightened.append(b.name)
    if straightened:
        log(f"Straightened below {forearm.name}: {', '.join(straightened)}")
    return straightened


# -----------------------------------------------------------------------------
# POSE OPERATIONS
# -----------------------------------------------------------------------------

def rotate_pose_bone_axis_to(pb, target_direction, torso_reference=None):
    """Rotate a pose bone so its outward axis aligns with target_direction.

    Some auto-rig outputs reverse the local head/tail ordering relative to the
    torso. When a torso reference is supplied, orient from the nearer endpoint to
    the farther endpoint from the torso, which matches the geometric outward
    direction regardless of how the rig authored head/tail. The pivot must stay at
    the torso-side endpoint so the distal end can be moved outward instead of
    leaving the more distant endpoint fixed in place.
    """
    target = Vector(target_direction)
    if target.length < 1e-8:
        raise ValueError("Target direction is zero-length")
    target.normalize()

    if torso_reference is not None:
        head_dist = (pb.head - torso_reference).length
        tail_dist = (pb.tail - torso_reference).length
        if max(head_dist, tail_dist) > 1e-8:
            if head_dist <= tail_dist:
                current = pb.tail - pb.head
                pivot = pb.head.copy()
            else:
                current = pb.head - pb.tail
                pivot = pb.tail.copy()
        else:
            current = pb.tail - pb.head
            pivot = pb.head.copy()
    else:
        current = pb.tail - pb.head
        pivot = pb.head.copy()

    if current.length < 1e-8:
        return
    current.normalize()

    dot = max(-1.0, min(1.0, current.dot(target)))
    if dot > 0.999999:
        return

    # If the bone is authored with a reversed head/tail, rotating around the
    # torso-side endpoint (not always head) correctly moves the distal end outward.
    q = current.rotation_difference(target)
    around_pivot = Matrix.Translation(pivot) @ q.to_matrix().to_4x4() @ Matrix.Translation(-pivot)
    pb.matrix = around_pivot @ pb.matrix
    bpy.context.view_layer.update()


def mute_constraints(arm):
    states = []
    if not MUTE_CONSTRAINTS:
        return states
    for pb in arm.pose.bones:
        for con in pb.constraints:
            if hasattr(con, "mute"):
                states.append((con, con.mute))
                con.mute = True
    if states:
        log(f"Muted {len(states)} constraints temporarily.")
    return states


def restore_constraints(states):
    if not RESTORE_CONSTRAINTS:
        return
    for con, old_mute in states:
        try:
            con.mute = old_mute
        except ReferenceError:
            pass


def arm_outward_direction(bone, torso_center, preferred_axis=None):
    """Return the arm direction away from the torso, regardless of bone head/tail orientation.

    When a preferred axis is supplied (typically the shoulder anchor direction for a
    specific left/right side), it is used to break tie cases where the bone's head and
    tail are almost equidistant from the torso center but only one endpoint points away
    from the body.
    """
    if bone is None:
        return None

    head_vec = bone.head - torso_center
    tail_vec = bone.tail - torso_center
    if head_vec.length < 1e-6 and tail_vec.length < 1e-6:
        return None

    if preferred_axis is not None:
        preferred_axis = preferred_axis.normalized()
        head_score = head_vec.length + 0.75 * abs(head_vec.dot(preferred_axis))
        tail_score = tail_vec.length + 0.75 * abs(tail_vec.dot(preferred_axis))
        direction = head_vec if head_score >= tail_score else tail_vec
        if direction.length < 1e-6:
            return None
        return direction.normalized()

    head_to_center = head_vec.length
    tail_to_center = tail_vec.length
    tip = bone.head if head_to_center >= tail_to_center else bone.tail
    direction = tip - torso_center
    if direction.length < 1e-6:
        return None
    return direction.normalized()


def validate_t_pose_quality(upper_left, upper_right, forearms=()):
    """Reject obviously broken, collapsed, or mirrored-wrong arm poses.

    This is intentionally conservative: it is designed to catch the common bad
    cases (arms pointing toward the same side, shoulders collapsed together, or a
    forearm continuing into the torso) before the cleaned GLB is exported.
    """
    if upper_left is None or upper_right is None:
        raise RuntimeError("T-pose validation requires both upper arms to be detected.")

    middle = (upper_left.head + upper_right.head) * 0.5
    shoulder_axis = (upper_right.head - upper_left.head)
    if shoulder_axis.length < 1e-6:
        raise RuntimeError("T-pose validation failed: shoulder axis is degenerate.")
    side_axis = shoulder_axis.normalized()

    left_vec = arm_outward_direction(upper_left, middle, preferred_axis=upper_left.head - middle)
    right_vec = arm_outward_direction(upper_right, middle, preferred_axis=upper_right.head - middle)
    if left_vec is None or right_vec is None:
        raise RuntimeError("T-pose validation failed: upper arm direction is degenerate.")

    shoulder_separation = (upper_right.head - upper_left.head).length
    if shoulder_separation < 0.05:
        raise RuntimeError(
            "T-pose validation failed: shoulder separation is too small, which usually means "
            "the detected arms are collapsed or from the wrong skeleton."
        )

    left_tip = upper_left.head if (upper_left.head - middle).length >= (upper_left.tail - middle).length else upper_left.tail
    right_tip = upper_right.head if (upper_right.head - middle).length >= (upper_right.tail - middle).length else upper_right.tail
    left_outward = (left_tip - middle).normalized()
    right_outward = (right_tip - middle).normalized()

    left_outward_score = left_vec.dot(left_outward)
    right_outward_score = right_vec.dot(right_outward)
    if left_outward_score < 0.10 or right_outward_score < 0.10:
        raise RuntimeError(
            "T-pose validation failed: at least one arm points toward the torso instead of away from it. "
            f"left={left_outward_score:.2f}, right={right_outward_score:.2f}"
        )

    left_side_projection = left_vec.dot(side_axis)
    right_side_projection = right_vec.dot(side_axis)
    if left_side_projection > -0.85 or right_side_projection < 0.85:
        raise RuntimeError(
            "T-pose validation failed: the arms are not aligned with the shoulder-to-shoulder T axis. "
            f"left_side={left_side_projection:.2f}, right_side={right_side_projection:.2f}"
        )

    mirrored_alignment = left_vec.dot(right_vec)
    if mirrored_alignment > -0.75:
        raise RuntimeError(
            "T-pose validation failed: the arms are not mirrored correctly and point in roughly the same direction. "
            f"alignment={mirrored_alignment:.2f}"
        )

    for bone in forearms:
        if bone is None:
            continue
        if bone.parent is None:
            continue
        expected_upper = upper_left if bone.parent == upper_left else upper_right if bone.parent == upper_right else None
        if expected_upper is None:
            continue
        forearm_head = bone.head - middle
        forearm_tail = bone.tail - middle
        preferred = expected_upper.head - middle
        candidate_vectors = []
        if forearm_head.length > 1e-6:
            candidate_vectors.append(forearm_head.normalized())
        if forearm_tail.length > 1e-6:
            candidate_vectors.append(forearm_tail.normalized())
        if not candidate_vectors:
            raise RuntimeError(f"T-pose validation failed: forearm {bone.name} is degenerate.")
        expected_upper_vec = arm_outward_direction(expected_upper, middle, preferred_axis=preferred)
        if expected_upper_vec is None:
            raise RuntimeError(f"T-pose validation failed: expected upper arm {expected_upper.name} has no valid direction.")
        best_projection = max(v.dot(expected_upper_vec) for v in candidate_vectors)
        if best_projection < 0.70:
            raise RuntimeError(
                f"T-pose validation failed: forearm {bone.name} is not continuing the expected outward direction. "
                f"projection={best_projection:.2f}"
            )

    return {
        "shoulder_separation": float(shoulder_separation),
        "left_outward_score": float(left_outward_score),
        "right_outward_score": float(right_outward_score),
        "left_side_projection": float(left_side_projection),
        "right_side_projection": float(right_side_projection),
        "mirrored_alignment": float(mirrored_alignment),
    }


def armature_meshes(armature):
    meshes = []
    for mesh in scene_meshes():
        if mesh.find_armature() == armature:
            meshes.append(mesh)
            continue
        if any(modifier.type == "ARMATURE" and modifier.object == armature for modifier in mesh.modifiers):
            meshes.append(mesh)
    return meshes


def validate_mesh_tpose_reach(armature, upper_left, upper_right, forearms=()):
    """Ensure the visible mesh follows the generated T-pose arm span."""
    meshes = armature_meshes(armature)
    if not meshes:
        raise RuntimeError("T-pose mesh validation failed: no meshes are bound to the generated armature.")

    middle = (upper_left.head + upper_right.head) * 0.5
    shoulder_axis = upper_right.head - upper_left.head
    if shoulder_axis.length < 1e-6:
        raise RuntimeError("T-pose mesh validation failed: shoulder axis is degenerate.")
    right_axis = shoulder_axis.normalized()
    left_axis = -right_axis

    def projected_endpoint_reach(axis, bones):
        reach = 0.0
        for bone in bones:
            if bone is None:
                continue
            reach = max(reach, (bone.head - middle).dot(axis), (bone.tail - middle).dot(axis))
        return reach

    left_bones = [upper_left] + [bone for bone in forearms if bone and bone.parent == upper_left]
    right_bones = [upper_right] + [bone for bone in forearms if bone and bone.parent == upper_right]
    left_bone_reach = projected_endpoint_reach(left_axis, left_bones)
    right_bone_reach = projected_endpoint_reach(right_axis, right_bones)
    if left_bone_reach <= 1e-6 or right_bone_reach <= 1e-6:
        raise RuntimeError("T-pose mesh validation failed: arm reach is degenerate.")

    left_mesh_reach = 0.0
    right_mesh_reach = 0.0
    for mesh in meshes:
        for vertex in mesh.data.vertices:
            world = mesh.matrix_world @ vertex.co
            left_mesh_reach = max(left_mesh_reach, (world - middle).dot(left_axis))
            right_mesh_reach = max(right_mesh_reach, (world - middle).dot(right_axis))

    left_ratio = left_mesh_reach / left_bone_reach
    right_ratio = right_mesh_reach / right_bone_reach
    if left_ratio < 0.70 or right_ratio < 0.70:
        raise RuntimeError(
            "T-pose mesh validation failed: generated bones reached a T-pose, but the skinned mesh did not follow. "
            f"left_ratio={left_ratio:.2f}, right_ratio={right_ratio:.2f}"
        )

    return {
        "left_mesh_reach": float(left_mesh_reach),
        "right_mesh_reach": float(right_mesh_reach),
        "left_bone_reach": float(left_bone_reach),
        "right_bone_reach": float(right_bone_reach),
    }


def reset_pose(arm):
    for pb in arm.pose.bones:
        try:
            pb.matrix_basis = Matrix.Identity(4)
        except Exception:
            pass
    bpy.context.view_layer.update()


def ensure_armature_active_in_pose_mode(arm):
    active = bpy.context.active_object
    if active and active.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass

    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    arm.hide_set(False)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='POSE')


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def make_t_pose(auto_rig=False, bind_method=BIND_METHOD, apply_rest_pose=None):
    """Create a T-pose for the active armature.

    When apply_rest_pose is None, the module-level APPLY_AS_REST_POSE setting is
    used for backward compatibility. Passing True/False explicitly makes the
    behavior obvious for script-level and agent-driven use.
    """
    if apply_rest_pose is None:
        apply_rest_pose = APPLY_AS_REST_POSE

    arm = find_armature()
    if not arm:
        if auto_rig:
            arm = create_basic_humanoid_rig(bind_method)
        else:
            raise RuntimeError(
                "No armature found after import "
                f"(scene objects: {scene_object_summary()}). AutoTPose requires a rigged "
                "model with an armature; use --auto-rig to create a basic humanoid rig."
            )
    if not arm:
        raise RuntimeError(
            "No armature found after import "
            f"(scene objects: {scene_object_summary()}). AutoTPose requires a rigged "
            "model with an armature; it does not create a rig for an unrigged mesh."
        )

    log(f"Using armature: {arm.name} ({len(arm.data.bones)} bones)")
    ensure_armature_active_in_pose_mode(arm)

    constraint_states = mute_constraints(arm)

    try:
        if RESET_POSE_FIRST:
            reset_pose(arm)

        pair = find_joint_node_upper_arms(arm)
        if pair is None:
            pair = find_named_upper_arms(arm)
        if pair is None:
            pair = find_geometric_upper_arms(arm)

        if pair is None:
            raise RuntimeError(
                "Could not confidently detect both upper arms. "
                "Rename them with common names such as upper_arm.L / upper_arm.R, "
                "LeftArm / RightArm, or UpperArm_L / UpperArm_R and run again."
            )

        arm_a, arm_b = pair

        # The shoulder-to-shoulder line is coordinate-system independent, so it
        # works even when the imported rig isn't aligned to Blender's X/Z axes.
        shoulder_mid = (arm_a.head + arm_b.head) * 0.5
        shoulder_axis = (arm_b.head - arm_a.head)
        if shoulder_axis.length < 1e-6:
            shoulder_axis = arm_b.tail - arm_a.tail

        if shoulder_axis.length > 1e-6:
            side_axis = shoulder_axis.normalized()
            target_a = -side_axis
            target_b = side_axis
        else:
            target_a = arm_outward_direction(arm_a, shoulder_mid, preferred_axis=arm_a.head - shoulder_mid)
            target_b = arm_outward_direction(arm_b, shoulder_mid, preferred_axis=arm_b.head - shoulder_mid)

        if target_a is None or target_b is None:
            # Extremely unusual fallback: use the separation of the bone anchors.
            target_a = arm_a.head - shoulder_mid
            target_b = arm_b.head - shoulder_mid
            if target_a.length < 1e-8 or target_b.length < 1e-8:
                target_a = arm_a.tail - arm_b.tail
                target_b = -target_a

        if target_a is not None:
            target_a = target_a.normalized()
        if target_b is not None:
            target_b = target_b.normalized()

        if shoulder_axis.length > 1e-6:
            side_axis = shoulder_axis.normalized()
            if target_a.dot(side_axis) > 0.0:
                target_a = -target_a
            if target_b.dot(side_axis) < 0.0:
                target_b = -target_b

        # Pose the upper arms first; child pose coordinates then update.
        rotate_pose_bone_axis_to(arm_a, target_a, torso_reference=shoulder_mid)
        rotate_pose_bone_axis_to(arm_b, target_b, torso_reference=shoulder_mid)
        bpy.context.view_layer.update()

        forearms = []
        forearm_bones = []
        if STRAIGHTEN_FOREARMS:
            fa = find_forearm(arm_a, target_a)
            fb = find_forearm(arm_b, target_b)

            if fa:
                rotate_pose_bone_axis_to(fa, target_a, torso_reference=shoulder_mid)
                bpy.context.view_layer.update()
                straighten_chain_below(fa, target_a, shoulder_mid)
                forearm_bones.append(fa)
                forearms.append(fa.name)
            else:
                log(f"WARNING: Could not identify forearm under {arm_a.name}")

            if fb:
                rotate_pose_bone_axis_to(fb, target_b, torso_reference=shoulder_mid)
                bpy.context.view_layer.update()
                straighten_chain_below(fb, target_b, shoulder_mid)
                forearm_bones.append(fb)
                forearms.append(fb.name)
            else:
                log(f"WARNING: Could not identify forearm under {arm_b.name}")

        bpy.context.view_layer.update()

        validation = validate_t_pose_quality(arm_a, arm_b, tuple(forearm_bones))
        log("Upper arms:", arm_a.name, ",", arm_b.name)
        if forearms:
            log("Forearms:", ", ".join(forearms))
        log("Pose validation passed:", validation)

        if apply_rest_pose:
            if auto_rig:
                bake_generated_tpose_as_rest(arm, bind_method)
                mesh_validation = validate_mesh_tpose_reach(arm, arm_a, arm_b, tuple(forearm_bones))
                log("Mesh validation passed:", mesh_validation)
            else:
                bpy.ops.pose.armature_apply(selected=False)
            log("Applied T-pose as NEW REST POSE.")
        else:
            log("T-pose created as a pose only. Rest pose was NOT changed.")
            log("Set apply_rest_pose=True if you want to bake it as the bind/rest pose.")

    finally:
        restore_constraints(constraint_states)
        bpy.context.view_layer.update()

    return arm, (arm_a.name, arm_b.name), tuple(forearms)


def use_preposed_instance_rig():
    """Return the already T-posed rig produced by the weighted backend."""
    arm = find_armature()
    if not arm:
        raise RuntimeError("instance-rig output did not contain an armature")

    pair = find_joint_node_upper_arms(arm)
    if pair is None:
        raise RuntimeError("instance-rig output did not contain the expected shoulder/elbow/wrist chains")
    arm_a, arm_b = pair
    forearm_a = find_forearm(arm_a, Vector((1.0, 0.0, 0.0)))
    forearm_b = find_forearm(arm_b, Vector((-1.0, 0.0, 0.0)))
    if forearm_a is None or forearm_b is None:
        raise RuntimeError("instance-rig output did not contain both forearms")

    log("Using weighted T-pose produced by instance-rig.")
    log("Upper arms:", arm_a.name, ",", arm_b.name)
    log("Forearms:", forearm_a.name, ",", forearm_b.name)
    return arm, (arm_a.name, arm_b.name), (forearm_a.name, forearm_b.name)


def prepare_instance_rigged_input(input_path):
    """Use the project-local instance-rig backend as the primary auto-rig path.

    The native Blender rig builder is retained only as a compatibility fallback for
    cases where the ML-backed library is unavailable or cannot process a mesh. This
    keeps the repo's app-facing workflow aligned with the working auto-rigging
    backend while preserving a safety net for smaller or unusual cases.
    """
    try:
        from autotpose_core.instance_rig_bridge import generate_instance_rigged_model
    except Exception as exc:
        log(f"instance-rig bridge unavailable: {exc}")
        return None

    temp_output = Path(input_path).with_name(f".{Path(input_path).stem}_instancerig.glb")
    try:
        log(f"Using project-local instance-rig backend for {input_path}")
        result = generate_instance_rigged_model(
            input_path,
            temp_output,
            on_progress=lambda step: log(f"[instance-rig] {step}"),
        )
        if result.exists():
            return result
    except Exception as exc:
        log(f"instance-rig backend failed; falling back to native rigging: {exc}")
    return None


def command_line_options(arguments):
    """Parse the small, explicit option surface used after Blender's `--`.

    Auto-rigging defaults to the project-local instance-rig backend when the
    repository's environment is available, while the native Blender rigger is
    retained as a compatibility fallback only. Use --native-rig-only to force the
    older path when needed for debugging or comparison.
    """
    options = {
        "input": None,
        "output": None,
        "report": None,
        "auto_rig": True,
        "prefer_instance_rig": True,
        "bind_method": BIND_METHOD,
        "apply_rest_pose": False,
        "straighten_forearms": True,
    }
    iterator = iter(arguments)
    for argument in iterator:
        if argument == "--input":
            options["input"] = next(iterator, None)
        elif argument == "--output":
            options["output"] = next(iterator, None)
        elif argument == "--report":
            options["report"] = next(iterator, None)
        elif argument in {"--auto-rig", "--prefer-instance-rig"}:
            options["auto_rig"] = True
            options["prefer_instance_rig"] = True
        elif argument in {"--no-auto-rig", "--native-rig-only"}:
            if argument == "--native-rig-only":
                options["prefer_instance_rig"] = False
            else:
                options["auto_rig"] = False
        elif argument == "--bind-method":
            options["bind_method"] = next(iterator, None)
        elif argument == "--apply-rest-pose":
            options["apply_rest_pose"] = True
        elif argument == "--no-straighten-forearms":
            options["straighten_forearms"] = False
        else:
            raise ValueError(f"Unknown option: {argument}")

    if arguments and (not options["input"] or not options["output"] or not options["report"]):
        raise ValueError("Agent mode requires --input, --output, and --report")
    if options["bind_method"] is None or options["bind_method"].upper() not in {"AUTO", "DISTANCE", "BONE_HEAT"}:
        raise ValueError("--bind-method must be AUTO, DISTANCE, or BONE_HEAT")
    options["bind_method"] = options["bind_method"].upper()
    return options


def supported_path(path, allowed_extensions, option):
    resolved = Path(path).expanduser().resolve()
    if resolved.suffix.lower() not in allowed_extensions:
        formats = ", ".join(sorted(allowed_extensions))
        raise ValueError(f"{option} must use one of: {formats}")
    return resolved


def load_input(path):
    input_path = supported_path(path, {".blend", ".glb", ".gltf"}, "--input")
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    if input_path.suffix.lower() == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(input_path))
    else:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        bpy.ops.import_scene.gltf(filepath=str(input_path))
    return input_path


def write_output(path):
    output_path = supported_path(path, {".blend", ".glb"}, "--output")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".blend":
        bpy.ops.wm.save_as_mainfile(filepath=str(output_path))
    else:
        bpy.ops.export_scene.gltf(filepath=str(output_path), export_format="GLB", use_selection=False)
    return output_path


def write_report(path, status, **details):
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({"status": status, **details}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_from_command_line():
    global APPLY_AS_REST_POSE, STRAIGHTEN_FOREARMS

    try:
        separator = sys.argv.index("--")
    except ValueError:
        make_t_pose()
        print("\n[Auto T-Pose] Done.")
        return

    options = command_line_options(sys.argv[separator + 1:])
    APPLY_AS_REST_POSE = options["apply_rest_pose"]
    STRAIGHTEN_FOREARMS = options["straighten_forearms"]

    try:
        input_path = load_input(options["input"])
        source_max_edge_length = mesh_max_edge_length(scene_meshes())
        output_path = supported_path(options["output"], {".blend", ".glb"}, "--output")
        if input_path == output_path:
            raise ValueError("--output must differ from --input")

        auto_rig_used = False
        cleanup = None
        if options["auto_rig"] and options["prefer_instance_rig"]:
            instance_rig_output = prepare_instance_rigged_input(str(input_path))
            if instance_rig_output is not None:
                auto_rig_used = True
                bpy.ops.object.select_all(action="SELECT")
                bpy.ops.object.delete(use_global=False)
                bpy.ops.import_scene.gltf(filepath=str(instance_rig_output))
                input_path = instance_rig_output

        if auto_rig_used:
            arm, upper_arms, forearms = use_preposed_instance_rig()
        else:
            arm, upper_arms, forearms = make_t_pose(
                auto_rig=options["auto_rig"],
                bind_method=options["bind_method"],
                apply_rest_pose=options["apply_rest_pose"],
            )
        if options["auto_rig"]:
            stretch_limit = max(source_max_edge_length * 1.8, 1e-6)
            meshes = armature_meshes(arm)
            removed_faces = remove_overstretched_faces(meshes, stretch_limit)
            rough_edge_limit = max(source_max_edge_length * 0.5, 1e-6)
            removed_rough_faces = remove_rough_edge_faces(meshes, rough_edge_limit)
            island_extent_limit = max(source_max_edge_length * 0.95, 1e-6)
            removed_island_faces = remove_tiny_mesh_islands(meshes, island_extent_limit)
            smooth_mesh_normals(meshes)
            cleanup = {
                "source_max_edge_length": source_max_edge_length,
                "stretch_edge_limit": stretch_limit,
                "removed_overstretched_faces": removed_faces,
                "rough_edge_limit": rough_edge_limit,
                "removed_rough_edge_faces": removed_rough_faces,
                "tiny_island_extent_limit": island_extent_limit,
                "removed_tiny_island_faces": removed_island_faces,
            }
            if removed_faces:
                log(f"Removed {removed_faces} overstretched faces before export.")
            if removed_rough_faces:
                log(f"Removed {removed_rough_faces} rough edge faces before export.")
            if removed_island_faces:
                log(f"Removed {removed_island_faces} tiny island faces before export.")
        output_path = write_output(output_path)
        write_report(
            options["report"],
            "success",
            armature=arm.name,
            upper_arms=list(upper_arms),
            forearms=list(forearms),
            applied_as_rest_pose=APPLY_AS_REST_POSE,
            auto_rigged=options["auto_rig"],
            backend="instance-rig" if auto_rig_used else "native-blender",
            bind_method=options["bind_method"] if options["auto_rig"] else None,
            straighten_forearms=STRAIGHTEN_FOREARMS,
            validation_passed=True,
            cleanup=cleanup,
            input=str(input_path),
            output=str(output_path),
        )
        print("\n[Auto T-Pose] Done.")
    except Exception as exc:
        write_report(options["report"], "error", error=str(exc))
        print("\n[Auto T-Pose] ERROR:", exc)
        sys.exit(1)


if __name__ == "__main__":
    run_from_command_line()
