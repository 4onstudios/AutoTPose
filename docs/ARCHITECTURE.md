# AutoTPose Architecture

AutoTPose is intentionally **Python-first today** and **native-core-ready later**.
The goal is to keep Blender integration easy to install while preserving a clean
place to add a faster solver if the project grows into heavy geometry analysis,
automatic rigging, large batch jobs, or cross-DCC tooling.

## Current architecture

```text
Blender
  |
  | bpy / mathutils
  v
auto_t_pose.py
  |-- armature selection
  |-- bone detection
  |-- T-pose target calculation
  `-- pose application / optional rest-pose bake

src/autotpose_core/
  |-- contracts.py   # Blender-independent data structures
  `-- interface.py   # Solver protocol
```

`auto_t_pose.py` remains a self-contained script so a Blender user can download
one file and run it without installing a Python package.

The `src/autotpose_core` package defines the future boundary; it does **not** add
a second solver yet and is not a runtime dependency of the standalone script.

## Design rule: Blender is an adapter

The native/core boundary should never receive `bpy` objects, `PoseBone` objects,
or `mathutils.Matrix` values. Blender-specific code should convert the scene into
plain structures first:

```text
bpy armature
   |
   | extract
   v
RigSnapshot
   |
   | solve
   v
SolveResult
   |
   | apply
   v
bpy pose bones
```

This makes the solver testable without launching Blender and lets another host
(Maya, Houdini, Unreal tooling, a CLI, etc.) reuse the same solver later.

## What belongs in the core

Good candidates for a future core:

- skeleton graph analysis;
- bone-role classification;
- left/right pairing;
- pose scoring;
- geometric heuristics;
- IK/optimization routines;
- retargeting math;
- large-batch analysis.

## What stays in Python/Blender

These should remain in the Blender adapter:

- reading Blender scenes and selections;
- importing/exporting assets through Blender;
- UI panels/operators;
- applying pose matrices;
- muting/restoring Blender constraints;
- applying a pose as the Blender rest pose.

## Compatibility contract

A solver consumes:

- `RigSnapshot`
- `SolveRequest`

and returns:

- `SolveResult`

The result describes *what* each target bone should do, while the Blender adapter
decides *how* that target is applied in Blender.

Do not put Blender types in these contracts. Prefer primitive strings, booleans,
floats, arrays, and small serializable structures.

## Why a compiled core is not included yet

The current workload is dominated by Blender scene access and heuristic quality,
not raw CPU throughput. Adding a compiler, wheels, platform builds, and extension
bindings would increase contributor and installation friction without a proven
performance need.

A compiled implementation becomes justified when profiling shows a meaningful
hotspot or when the core is useful outside Blender.
