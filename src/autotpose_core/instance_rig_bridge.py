"""Compatibility bridge for the project-local instance-rig library.

Blender ships with its own Python runtime, which is not the same interpreter as
most project-local ML/vision stacks. This bridge avoids importing the library
inside Blender directly and instead calls the project-local virtual environment
through a subprocess, keeping instance-rig isolated to this repository.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional


def straighten_instance_rig_limbs(rigger, rig) -> None:
    """Refine instance-rig's correction into straight arm and leg chains."""
    import numpy as np

    from instancerig import _math
    from instancerig._pose_correction import TPoseConverter

    def rotation_to_axis(vector, target):
        source = np.asarray(vector, dtype=float)
        source_length = np.linalg.norm(source)
        if source_length < 1e-8:
            raise RuntimeError("instance-rig produced a zero-length limb segment")
        source /= source_length

        target = np.asarray(target, dtype=float)
        target /= np.linalg.norm(target)
        cross = np.cross(source, target)
        sine = np.linalg.norm(cross)
        cosine = float(np.clip(np.dot(source, target), -1.0, 1.0))

        if sine < 1e-8:
            if cosine > 0.0:
                return np.zeros(3)
            fallback = np.array([0.0, 0.0, 1.0])
            if abs(source[2]) > 0.9:
                fallback = np.array([0.0, 1.0, 0.0])
            axis = np.cross(source, fallback)
            axis /= np.linalg.norm(axis)
            rotation = -np.eye(3) + 2.0 * np.outer(axis, axis)
        else:
            skew = np.array(
                [
                    [0.0, -cross[2], cross[1]],
                    [cross[2], 0.0, -cross[0]],
                    [-cross[1], cross[0], 0.0],
                ]
            )
            rotation = np.eye(3) + skew + skew @ skew * ((1.0 - cosine) / (sine * sine))
        return np.degrees(_math.get_euler_from_matrix(rotation))

    def align_segments(segments):
        for proximal_name, distal_name, target in segments:
            joints = {joint.name: joint for joint in rig.root_joint}
            if proximal_name not in joints or distal_name not in joints:
                raise RuntimeError(
                    f"instance-rig output is missing required limb joints: "
                    f"{proximal_name}, {distal_name}"
                )
            vector = joints[distal_name].world_position - joints[proximal_name].world_position
            rotation = rotation_to_axis(vector, target)
            TPoseConverter(rig, rigger._mesh)._apply_t_pose({proximal_name: rotation})

    align_segments(
        (
            ("leftShoulder", "leftElbow", (1.0, 0.0, 0.0)),
            ("rightShoulder", "rightElbow", (-1.0, 0.0, 0.0)),
        )
    )
    align_segments(
        (
            ("leftElbow", "leftWrist", (1.0, 0.0, 0.0)),
            ("rightElbow", "rightWrist", (-1.0, 0.0, 0.0)),
        )
    )
    align_segments(
        (
            ("leftHip", "leftKnee", (0.14, -1.0, 0.0)),
            ("rightHip", "rightKnee", (-0.14, -1.0, 0.0)),
        )
    )
    align_segments(
        (
            ("leftKnee", "leftAnkle", (0.14, -1.0, 0.0)),
            ("rightKnee", "rightAnkle", (-0.14, -1.0, 0.0)),
        )
    )


def straighten_instance_rig_arms(rigger, rig) -> None:
    """Backward-compatible alias for the full limb correction."""
    straighten_instance_rig_limbs(rigger, rig)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _project_local_python() -> Optional[Path]:
    root = _project_root()
    candidates = [
        root / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _python_can_import_instance_rig(python: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(python), "-c", "import instancerig; print(instancerig.__file__)"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


def instance_rig_available() -> bool:
    """Return True when the project-local instance-rig backend is usable."""
    if importlib.util.find_spec("instancerig") is not None:
        return True

    python = _project_local_python()
    if python is None:
        return False
    return _python_can_import_instance_rig(python)


def generate_instance_rigged_model(
    input_path: str | Path,
    output_path: str | Path,
    *,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Path:
    """Generate a humanoid rig using the repo-local instance-rig backend.

    The implementation runs inside the project-local Python environment rather
    than Blender's embedded interpreter so the TensorFlow/MediaPipe dependency
    stack remains isolated to this project.
    """
    python = _project_local_python()
    if python is None or not _python_can_import_instance_rig(python):
        raise RuntimeError("instance-rig is not available in the project-local environment")

    input_file = Path(input_path).expanduser()
    output_file = Path(output_path).expanduser()
    output_file.parent.mkdir(parents=True, exist_ok=True)

    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from instancerig.InstanceRig import InstanceRig\n"
        f"sys.path.insert(0, {str(_project_root() / 'src')!r})\n"
        "from autotpose_core.instance_rig_bridge import straighten_instance_rig_limbs\n"
        f"input_path = Path({str(input_file)!r})\n"
        f"output_path = Path({str(output_file)!r})\n"
        "rigger = InstanceRig()\n"
        "rigger.on_progress = lambda message: print(message)\n"
        "rig = rigger.auto_rig(str(input_path), str(output_path))\n"
        "print('straightening full limb chains')\n"
        "straighten_instance_rig_limbs(rigger, rig)\n"
        "rigger.export_method(str(output_path), rigger._mesh, rig)\n"
    )

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", "")

    completed = subprocess.run(
        [str(python), "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    output = "\n".join(filter(None, [completed.stdout, completed.stderr]))
    if on_progress is not None:
        for line in output.splitlines():
            if line.strip():
                on_progress(line.strip())

    if completed.returncode != 0:
        description = output.strip() or "unknown instance-rig backend failure"
        raise RuntimeError(f"instance-rig backend failed: {description}")
    if not output_file.exists():
        raise RuntimeError(f"instance-rig did not create the expected output: {output_file}")
    return output_file
