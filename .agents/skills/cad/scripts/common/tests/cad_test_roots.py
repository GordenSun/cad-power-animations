from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path
from unittest import mock

from common import assembly_spec, catalog, generation, render


IGNORED_TEST_ROOT = Path(__file__).resolve().parents[6] / "tmp" / "cad-skill-tests"


class IsolatedCadRoots:
    def __init__(self, testcase: unittest.TestCase, *, prefix: str) -> None:
        IGNORED_TEST_ROOT.mkdir(parents=True, exist_ok=True)
        self._tempdir = tempfile.TemporaryDirectory(prefix=prefix, dir=IGNORED_TEST_ROOT)
        testcase.addCleanup(self._tempdir.cleanup)

        self.root = Path(self._tempdir.name)
        self.cad_root = self.root / "workspace"
        self.cad_root.mkdir(parents=True, exist_ok=True)

        patches = [
            mock.patch.object(assembly_spec, "CAD_ROOT", self.cad_root),
            mock.patch.object(catalog, "CAD_ROOT", self.cad_root),
            mock.patch.object(render, "CAD_ROOT", self.cad_root),
            mock.patch.object(generation, "CAD_ROOT", self.cad_root),
        ]
        render_tool_cli = sys.modules.get("render.cli")
        if render_tool_cli is not None:
            patches.extend(
                (
                    mock.patch.object(render_tool_cli, "CAD_ROOT", self.cad_root),
                )
            )
        for patcher in patches:
            patcher.start()
            testcase.addCleanup(patcher.stop)

    def temporary_cad_directory(self, *, prefix: str) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix=prefix, dir=self.cad_root)
