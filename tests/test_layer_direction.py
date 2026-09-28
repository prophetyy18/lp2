"""Cross-module import isolation: every module's source must be hermetic."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from tools.check_imports.scan import scan_module


def _write(root: Path, module: str, files: dict[str, str]) -> None:
    pkg = root / "modules" / module
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for name, body in files.items():
        (pkg / name).write_text(textwrap.dedent(body), encoding="utf-8")


class LayerDirectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_clean_module_has_no_findings(self) -> None:
        _write(
            self.root,
            "alpha",
            {
                "core.py": (
                    """
                    import json
                    from dataclasses import dataclass

                    @dataclass
                    class X:
                        pass
                    """
                ),
            },
        )
        findings = scan_module("alpha", self.root / "modules")
        self.assertEqual(findings, [])

    def test_cross_module_import_is_a_violation(self) -> None:
        _write(
            self.root,
            "alpha",
            {"core.py": "from modules.beta.engine import run\n"},
        )
        _write(self.root, "beta", {"__init__.py": ""})
        findings = scan_module("alpha", self.root / "modules")
        codes = {f.code for f in findings}
        self.assertIn("BOUNDARY_VIOLATION", codes)
        bad = next(f for f in findings if f.code == "BOUNDARY_VIOLATION")
        self.assertIn("modules.beta", bad.message)

    def test_own_module_self_import_is_allowed(self) -> None:
        _write(
            self.root,
            "alpha",
            {
                "a.py": "from modules.alpha.b import Y\n",
                "b.py": "class Y: pass\n",
            },
        )
        findings = scan_module("alpha", self.root / "modules")
        self.assertEqual(findings, [])

    def test_legacy_package_is_forbidden(self) -> None:
        _write(
            self.root,
            "alpha",
            {"core.py": "from robinhood_lp.protocol import ids\n"},
        )
        findings = scan_module("alpha", self.root / "modules")
        codes = {f.code for f in findings}
        self.assertIn("LEGACY_LEAK", codes)

    def test_framework_public_api_is_allowed(self) -> None:
        _write(
            self.root,
            "alpha",
            {"core.py": "from framework.architecture import load, validate\n"},
        )
        findings = scan_module("alpha", self.root / "modules")
        self.assertEqual(findings, [])

    def test_framework_private_path_is_an_internal_leak(self) -> None:
        _write(
            self.root,
            "alpha",
            {"core.py": "from framework.architecture._private import thing\n"},
        )
        findings = scan_module("alpha", self.root / "modules")
        codes = {f.code for f in findings}
        self.assertIn("INTERNAL_LEAK", codes)


if __name__ == "__main__":
    unittest.main()