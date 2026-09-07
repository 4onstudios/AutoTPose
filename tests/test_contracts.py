import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autotpose_core import (  # noqa: E402
    BoneSnapshot,
    MeshSnapshot,
    SkinningOptions,
    PoseBoneTarget,
    RigSnapshot,
    SolveResult,
    Vec3,
    detect_humanoid_landmarks,
    compute_skin_weights,
)
from autotpose_core.instance_rig_bridge import instance_rig_available


class ContractTests(unittest.TestCase):
    def test_vec3_conversion(self):
        self.assertEqual(Vec3.from_value((1, 2, 3)), Vec3(1.0, 2.0, 3.0))
        self.assertEqual(Vec3(1, 2, 3).to_list(), [1, 2, 3])

    def test_snapshot_index(self):
        root = BoneSnapshot("root", None, Vec3(0, 0, 0), Vec3(0, 0, 1))
        arm = BoneSnapshot("upper_arm.L", "root", Vec3(0, 0, 1), Vec3(1, 0, 1))
        rig = RigSnapshot((root, arm), source_name="demo")
        self.assertIs(rig.by_name()["upper_arm.L"], arm)

    def test_solve_result_is_serializable_shape(self):
        result = SolveResult(
            targets=(PoseBoneTarget("upper_arm.L", Vec3(1, 0, 0), role="upper_arm_left"),),
            confidence=0.9,
            warnings=("demo",),
            metadata={"engine": "python"},
        )
        raw = result.to_dict()
        self.assertEqual(raw["targets"][0]["bone"], "upper_arm.L")
        self.assertEqual(raw["metadata"]["engine"], "python")

    def test_humanoid_landmarks_cover_basic_biped(self):
        mesh = MeshSnapshot((
            Vec3(-1, -0.2, 0), Vec3(1, 0.2, 0), Vec3(-1, -0.2, 2),
            Vec3(1, 0.2, 2),
        ))
        result = detect_humanoid_landmarks(mesh)
        self.assertGreaterEqual(result.confidence, 0.5)
        self.assertTrue({"shoulder.L", "wrist.R", "ankle.L"}.issubset(result.by_name()))
        self.assertGreater(
            result.by_name()["shoulder.L"].position.x,
            result.by_name()["shoulder.R"].position.x,
        )

    def test_distance_skinning_limits_and_normalizes_influences(self):
        rig = RigSnapshot((
            BoneSnapshot("root", None, Vec3(0, 0, 0), Vec3(0, 0, 1), deform=False),
            BoneSnapshot("spine", "root", Vec3(0, 0, 0), Vec3(0, 0, 1)),
            BoneSnapshot("arm", "spine", Vec3(0, 0, 1), Vec3(1, 0, 1)),
        ))
        weights = compute_skin_weights(
            MeshSnapshot((Vec3(0.8, 0, 1),)),
            rig,
            SkinningOptions(max_influences=2),
        )
        self.assertLessEqual(len(weights[0]), 2)
        self.assertAlmostEqual(sum(weight for _, weight in weights[0]), 1.0)

    def test_instance_rig_backend_is_project_local(self):
        self.assertTrue(instance_rig_available())


if __name__ == "__main__":
    unittest.main()
