import tempfile
import unittest
from pathlib import Path

import build123d

from common.step_scene import (
    SelectorOptions,
    SelectorProfile,
    extract_selectors_from_scene,
    load_step_scene,
)


class StepSceneSelectorArtifactTests(unittest.TestCase):
    def test_artifact_topology_uses_glb_face_runs_without_duplicate_face_buffers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cad-topology-v1-") as temp_dir:
            step_path = Path(temp_dir) / "box.step"
            build123d.export_step(build123d.Box(1, 1, 1), step_path)
            scene = load_step_scene(step_path)

            bundle = extract_selectors_from_scene(
                scene,
                cad_ref="fixtures/box",
                profile=SelectorProfile.ARTIFACT,
                options=SelectorOptions(linear_deflection=0.1, angular_deflection=0.1),
            )

            self.assertEqual(1, bundle.manifest["schemaVersion"])
            self.assertEqual(".box.step.glb", bundle.manifest["faceProxy"]["source"])
            self.assertIn("faceRuns", bundle.buffers)
            self.assertTrue(scene.glb_mesh_payloads)
            self.assertNotIn("facePositions", bundle.buffers)
            self.assertNotIn("faceIndices", bundle.buffers)
            self.assertNotIn("faceIds", bundle.buffers)
            face_columns = bundle.manifest["tables"]["faceColumns"]
            triangle_count_column = face_columns.index("triangleCount")
            row_triangle_count = sum(int(row[triangle_count_column]) for row in bundle.manifest["faces"])
            run_triangle_count = sum(int(bundle.buffers["faceRuns"][index + 3]) for index in range(0, len(bundle.buffers["faceRuns"]), 5))
            self.assertEqual(row_triangle_count, run_triangle_count)


if __name__ == "__main__":
    unittest.main()
