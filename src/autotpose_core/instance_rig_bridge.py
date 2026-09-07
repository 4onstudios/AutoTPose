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
        "from pathlib import Path\n"
        "from instancerig.InstanceRig import InstanceRig\n"
        f"input_path = Path({str(input_file)!r})\n"
        f"output_path = Path({str(output_file)!r})\n"
        "rigger = InstanceRig()\n"
        "rigger.on_progress = lambda message: print(message)\n"
        "rigger.auto_rig(str(input_path), str(output_path))\n"
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
