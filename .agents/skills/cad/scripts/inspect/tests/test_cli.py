from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest


class InspectCliWrapperTests(unittest.TestCase):
    def test_inspect_directory_invokes_cli(self) -> None:
        skill_root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            [sys.executable, "scripts/inspect", "--help"],
            cwd=skill_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertIn("usage: inspect", result.stdout)

    def test_inspect_help_does_not_import_ocp_or_render(self) -> None:
        skill_root = Path(__file__).resolve().parents[3]
        code = (
            "import sys; "
            "sys.path[:0]=['scripts','scripts/inspect']; "
            "import inspect_refs.cli; "
            "print('OCP.OCP' in sys.modules); "
            "print('render.cli' in sys.modules); "
            "print('common.step_scene' in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=skill_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertEqual(["False", "False", "False"], result.stdout.strip().splitlines())

    def test_scripts_inspect_rejects_render_subcommand(self) -> None:
        skill_root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            [sys.executable, "scripts/inspect", "render", "--help"],
            cwd=skill_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("invalid choice", result.stderr)

    def test_scripts_inspect_worker_reads_jsonl(self) -> None:
        skill_root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            [sys.executable, "scripts/inspect", "worker"],
            cwd=skill_root,
            input='{"id":"bad","argv":["refs"]}\n',
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertIn('"id":"bad"', result.stdout)
        self.assertIn('"exitCode":2', result.stdout)


if __name__ == "__main__":
    unittest.main()
