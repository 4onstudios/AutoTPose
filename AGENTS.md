# AutoTPose Agent Tool Contract

Use AutoTPose through its headless Blender interface when processing assets
programmatically. Do not modify the source asset in place.

## Preconditions

- Blender is installed and callable as `blender`, or provide its path through
  the `BLENDER` Make variable.
- The input is a `.blend`, `.glb`, or `.gltf` file containing a rigged humanoid
  mesh or armature.
- The requested output and report paths are writable and differ from the input.

A GLB with no glTF skin or joints imports as a mesh-only scene. To add a basic
humanoid armature and automatic weights before posing, use `make rig-pose`.

## Non-destructive operation

```bash
make pose \
  INPUT=/absolute/path/source.glb \
  OUTPUT=/absolute/path/tpose.glb \
  REPORT=/absolute/path/tpose-report.json
```

This creates a pose only; it does not alter the rig's rest pose.

## Auto-rig an unrigged humanoid

```bash
make rig-pose \
  INPUT=/absolute/path/source.glb \
  OUTPUT=/absolute/path/rigged-tpose.glb \
  REPORT=/absolute/path/rigged-tpose-report.json
```

This estimates a biped skeleton from the mesh bounds, creates a basic humanoid
armature, and binds it with Blender bone heat. When bone heat fails, AutoTPose
uses deterministic, topology-independent distance weights. Set
`BIND_METHOD=DISTANCE` to use the fallback directly or `BIND_METHOD=BONE_HEAT`
to reject fallback behavior. It is appropriate only for upright, front-facing
humanoid meshes; inspect and refine the weights in Blender before animation
production.

`make rig-pose` preserves the detected pose as the rig rest pose. To export a
static T-posed GLB, use `make rig-pose-rest`; it bakes the T-pose as the rest
pose.

## Destructive rest-pose operation

Use this only when explicitly requested:

```bash
make pose-rest \
  INPUT=/absolute/path/source.glb \
  OUTPUT=/absolute/path/rest-pose.glb \
  REPORT=/absolute/path/rest-pose-report.json
```

## Result contract

The process exits with code `0` on success and nonzero on failure. It writes a
JSON report with either:

```json
{
  "status": "success",
  "armature": "Armature",
  "upper_arms": ["upper_arm.L", "upper_arm.R"],
  "forearms": ["forearm.L", "forearm.R"],
  "auto_rigged": false,
  "applied_as_rest_pose": false,
  "output": "/absolute/path/tpose.glb"
}
```

or:

```json
{
  "status": "error",
  "error": "Explanation of the failure"
}
```

Check both the exit code and `status` before treating an output as usable.
