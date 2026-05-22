import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from step import cli


class StepCliTests(unittest.TestCase):
    def test_requires_explicit_target(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            cli.main([])
        self.assertEqual(2, cm.exception.code)

    def test_passes_targets_in_order_without_kind_for_generated_sources(self) -> None:
        with mock.patch.object(cli, "generate_step_targets", return_value=0) as generate:
            self.assertEqual(0, cli.main(["parts/second.py", "parts/first.py"]))

        generate.assert_called_once()
        self.assertEqual(["parts/second.py", "parts/first.py"], generate.call_args.args[0])
        self.assertIsNone(generate.call_args.kwargs["direct_step_kind"])
        self.assertFalse(generate.call_args.kwargs["step_options"].has_metadata)
        self.assertIsNone(generate.call_args.kwargs["output"])
        self.assertFalse(generate.call_args.kwargs["skip_explorer"])
        self.assertFalse(generate.call_args.kwargs["verbose"])

    def test_passes_direct_step_kind(self) -> None:
        with mock.patch.object(cli, "generate_step_targets", return_value=0) as generate:
            self.assertEqual(0, cli.main(["--kind", "assembly", "assemblies/second.step", "assemblies/first.step"]))

        generate.assert_called_once()
        self.assertEqual(["assemblies/second.step", "assemblies/first.step"], generate.call_args.args[0])
        self.assertEqual("assembly", generate.call_args.kwargs["direct_step_kind"])
        self.assertFalse(generate.call_args.kwargs["step_options"].has_metadata)
        self.assertIsNone(generate.call_args.kwargs["output"])
        self.assertFalse(generate.call_args.kwargs["verbose"])

    def test_passes_verbose_flag(self) -> None:
        with mock.patch.object(cli, "generate_step_targets", return_value=0) as generate:
            self.assertEqual(0, cli.main(["parts/sample.py", "--verbose"]))

        self.assertTrue(generate.call_args.kwargs["verbose"])

    def test_passes_skip_explorer_flag(self) -> None:
        with mock.patch.object(cli, "generate_step_targets", return_value=0) as generate:
            self.assertEqual(0, cli.main(["parts/sample.py", "--skip-explorer"]))

        self.assertTrue(generate.call_args.kwargs["skip_explorer"])

    def test_passes_output_flag(self) -> None:
        with mock.patch.object(cli, "generate_step_targets", return_value=0) as generate:
            self.assertEqual(0, cli.main(["parts/sample.py", "-o", "STEP/sample.step"]))

        self.assertEqual("STEP/sample.step", generate.call_args.kwargs["output"])

    def test_output_flag_rejects_multiple_targets(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            cli.main(["parts/first.py", "parts/second.py", "-o", "STEP/first.step"])
        self.assertEqual(2, cm.exception.code)

    def test_passes_import_metadata_flags(self) -> None:
        with mock.patch.object(cli, "generate_step_targets", return_value=0) as generate:
            self.assertEqual(
                0,
                cli.main(
                    [
                        "--kind",
                        "part",
                        "imports/sample_part.step",
                        "--stl",
                        "../meshes/sample_part.stl",
                        "--3mf",
                        "../meshes/sample_part.3mf",
                        "--glb",
                        "../meshes/sample_part.glb",
                        "--mesh-tolerance",
                        "0.2",
                        "--mesh-angular-tolerance",
                        "0.25",
                    ]
                ),
            )

        generate.assert_called_once()
        self.assertEqual(["imports/sample_part.step"], generate.call_args.args[0])
        self.assertEqual("part", generate.call_args.kwargs["direct_step_kind"])
        options = generate.call_args.kwargs["step_options"]
        self.assertEqual("../meshes/sample_part.stl", options.stl)
        self.assertEqual("../meshes/sample_part.3mf", options.three_mf)
        self.assertEqual("../meshes/sample_part.glb", options.glb)
        self.assertEqual(0.2, options.mesh_tolerance)
        self.assertEqual(0.25, options.mesh_angular_tolerance)

    def test_rejects_invalid_numeric_flag(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            cli.main(["imports/sample_part.step", "--mesh-tolerance", "nan"])
        self.assertEqual(2, cm.exception.code)

    def test_rejects_removed_inspect_flag(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            cli.main(["parts/sample.step", "--inspect", "refs {cad_token} --facts"])
        self.assertEqual(2, cm.exception.code)

    def test_help_has_current_step_flags_only(self) -> None:
        stream = io.StringIO()
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(stream):
            cli.main(["--help"])
        self.assertEqual(0, cm.exception.code)
        help_text = stream.getvalue()
        self.assertIn("--kind", help_text)
        self.assertIn("--stl", help_text)
        self.assertIn("--3mf", help_text)
        self.assertIn("--glb", help_text)
        self.assertIn("--skip-explorer", help_text)
        self.assertIn("--output", help_text)
        self.assertIn("--mesh-tolerance", help_text)
        self.assertIn("--verbose", help_text)


if __name__ == "__main__":
    unittest.main()
