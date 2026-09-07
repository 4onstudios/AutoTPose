"""Solver protocol shared by Python and future compiled implementations."""

from __future__ import annotations

from typing import Protocol

from .contracts import RigSnapshot, SolveRequest, SolveResult


class Solver(Protocol):
    """A pose solver consumes a rig snapshot and returns transform targets.

    The Blender adapter is responsible for extracting the snapshot and applying
    the returned targets. A future compiled implementation can satisfy this
    same contract through a thin Python extension without exposing Blender
    objects.
    """

    def solve(self, rig: RigSnapshot, request: SolveRequest) -> SolveResult:
        ...
