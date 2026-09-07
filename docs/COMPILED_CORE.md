# Future Compiled Core Plan

A compiled solver is an optional future implementation detail, not a requirement
for AutoTPose users or contributors today.

## Trigger for adding a compiled implementation

Do not add compiled code simply for speed in theory. Introduce it when at least
one of the following is true:

1. profiling identifies solver or geometry code as a real bottleneck;
2. batch processing needs materially better throughput;
3. automatic skeleton inference or rigging adds CPU-heavy geometry work;
4. multiple host applications need one shared solver;
5. a standalone CLI becomes an important product surface.

## Proposed layout when that happens

```text
AutoTPose/
├── auto_t_pose.py
├── src/
│   └── autotpose_core/        # Python contracts + fallback/reference code
├── native/
│   └── autotpose-core/        # future compiled solver implementation
├── bindings/
│   └── python/                # future Python extension package
├── tests/
└── docs/
```

Do not create `native/` or add build metadata until compiled code actually
exists. Empty scaffolding creates maintenance noise and implies support that the
project does not yet provide.

## Integration strategy

Any compiled implementation should expose an API equivalent to:

```python
result = solver.solve(rig_snapshot, solve_request)
```

The Python side should be able to select either implementation:

```text
compiled solver available -> use compiled core
compiled solver unavailable -> use Python implementation
```

A missing compiled extension must never prevent the Blender add-on or script
from loading unless the project intentionally moves to a compiled-required
release.

## Distribution expectations

Before shipping a compiled-backed Blender add-on, CI should build and test
artifacts for the operating systems and Python/Blender combinations the project
claims to support. The repository should avoid requiring end users to install a
compiler toolchain.

## Performance rule

Keep a benchmark that proves the compiled implementation earns its complexity.
Compare identical rig snapshots and verify numerical and semantic output against
the Python reference implementation.
