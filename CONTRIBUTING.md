# Contributing to AutoTPose

Thanks for helping improve AutoTPose.

## Project Boundaries

AutoTPose is Python-first. Do not add native dependencies unless an issue or
proposal includes a concrete reason, benchmark, and distribution plan.

Keep Blender-specific code and solver logic conceptually separate:

- Blender adapter responsibilities: `bpy`, scene access, pose application, UI,
  import/export, Blender constraints.
- Core responsibilities: skeleton graph analysis, role detection, pose targets,
  scoring, optimization, and host-neutral math.
- `src/autotpose_core` must not import `bpy` or `mathutils`.

See `docs/ARCHITECTURE.md` before introducing new cross-cutting architecture.

## Bug Reports

When reporting automatic bone-detection problems, please include:

- Blender version.
- Model/rig source if it can legally be shared.
- Upper-arm, forearm, shoulder/clavicle, and hand bone names.
- A short description of the starting pose.
- The console output produced by AutoTPose.

Do not upload models or assets that you do not have permission to redistribute.

## Pull Requests

Keep changes focused and explain why they improve detection or pose generation.
New skeleton-specific logic should avoid breaking existing generic detection where possible.

For Blender-neutral changes, run:

```bash
make sync
make test
```

Use `make help` to list all supported development commands.

For edits to `auto_t_pose.py`, at minimum verify that the file compiles with
Python and test the behavior in a supported Blender version before release.

## Future Compiled-Core Contributions

Compiled code is not part of the repository today. Before adding it, open a
design issue that demonstrates one of the triggers described in
`docs/COMPILED_CORE.md`. A compiled implementation should preserve the
`RigSnapshot -> SolveResult` boundary and retain a Python-compatible fallback
unless a future major release explicitly changes that policy.

By contributing, you agree that your contribution may be distributed under the
project's MIT License.
