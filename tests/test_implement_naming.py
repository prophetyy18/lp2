"""The one naming rule both enforcement layers and the role prompts share.

The rule exists because module names are hyphenated and capability ids are
dotted, and neither survives verbatim as a Python module path. The tests
below are deliberately written against those real shapes rather than against
tidy fixtures: the bug this module fixes survived review precisely because
every fixture in the repository used `alpha` / `one`, the one pair of names
for which the broken rule is accidentally correct.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.implement import naming

REPO_ROOT = Path(__file__).resolve().parent.parent


class SlugTests(unittest.TestCase):
    def test_hyphens_and_dots_both_become_single_underscores(self) -> None:
        self.assertEqual(naming.slug("market-data"), "market_data")
        self.assertEqual(naming.slug("series.get"), "series_get")
        self.assertEqual(
            naming.slug("reports.evidence_adapter.t101_view"),
            "reports_evidence_adapter_t101_view",
        )

    def test_runs_of_separators_collapse_and_edges_trim(self) -> None:
        self.assertEqual(naming.slug("a..b"), "a_b")
        self.assertEqual(naming.slug("--a--"), "a")

    def test_underscores_survive_unchanged(self) -> None:
        self.assertEqual(naming.slug("t101_view"), "t101_view")


class TestPathTests(unittest.TestCase):
    def test_the_canonical_path_is_importable(self) -> None:
        self.assertEqual(
            naming.test_rel_path("market-data", "series.get"),
            "tests/test_market_data_series_get.py",
        )
        self.assertEqual(
            naming.test_module_path("market-data", "series.get"),
            "tests.test_market_data_series_get",
        )

    def test_the_path_and_the_module_path_never_contain_a_separator_character(self) -> None:
        """The property that was false before, stated so it stays true.

        unittest resolves its argument as a module name, so a hyphen or a
        dot in the file's own stem is a failure there and in `import`
        alike. A path and a module path derived from the same stem is the
        cheapest way to keep them honest.
        """
        for name in (
            naming.test_rel_path("robinhood-storage", "storage.writer.append_event"),
            naming.test_module_path("robinhood-storage", "storage.writer.append_event"),
        ):
            stem = Path(name).stem if name.endswith(".py") else name.split(".")[-1]
            self.assertTrue(stem.replace("_", "").isalnum(), name)

    def test_the_documented_command_carries_no_py_suffix(self) -> None:
        """`python -m unittest tests.test_x.py` fails; `.py` is not an argument."""
        command = naming.unittest_command("market-data", "series.get")
        self.assertEqual(
            command, "./bin/python -m unittest tests.test_market_data_series_get -v"
        )
        self.assertNotIn(".py", command)

    def test_the_module_wide_prefix_ignores_the_capability(self) -> None:
        self.assertEqual(naming.module_test_prefix("market-data"), "test_market_data")
        self.assertTrue("test_market_data_series_get".startswith("test_market_data"))


class ArtifactPathTests(unittest.TestCase):
    def test_artifacts_keep_the_capability_dots(self) -> None:
        """Markdown paths, not Python paths: these are not translated."""
        self.assertEqual(
            naming.artifact_path("docs/implement", "market-data", "series.get", "manifest"),
            Path("docs/implement/market-data/series.get.manifest.md"),
        )

    def test_artifact_in_takes_the_directory_directly(self) -> None:
        """The primitive the other one is built from.

        `_archive_mvp_manifest` already holds a path inside the module
        directory, so passing it as a *root* would nest the module name a
        second time and write the archive where nothing looks for it.
        """
        self.assertEqual(
            naming.artifact_in(Path("docs/implement/market-data"), "series.get", "review"),
            Path("docs/implement/market-data/series.get.review.md"),
        )

    def test_every_declared_kind_is_usable(self) -> None:
        for kind in naming.ARTIFACT_KINDS:
            path = naming.artifact_path("root", "mod", "cap.one", kind)
            self.assertEqual(path.name, f"cap.one.{kind}.md")


class DocumentedCommandTests(unittest.TestCase):
    """The point of the CLI: a role prompt can ask instead of guessing."""

    def test_the_cli_prints_the_paths_and_the_test_command(self) -> None:
        out = subprocess.run(
            [sys.executable, "-m", "tools.implement.naming", "market-data", "series.get"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertIn("tests/test_market_data_series_get.py", out)
        self.assertIn("./bin/python -m unittest tests.test_market_data_series_get -v", out)

    def test_the_command_it_prints_actually_runs(self) -> None:
        """The documented invocation, executed against a real test file.

        A naming rule that no test ever imports can drift back into prose
        and nothing notices. This runs the exact argument list the CLI hands
        a developer, in a throwaway tree, and requires it to execute the
        tests rather than fail in the loader.

        The interpreter is `sys.executable` rather than the `./bin/python`
        the string starts with, so the test does not depend on the conda env
        existing. The point under test is the *argument* — a module path built
        from the rule, no `.py` suffix — not which interpreter resolves it.
        `DocumentedInterpreterTests` covers the shim itself.
        """
        argv = naming.unittest_command("market-data", "series.get").split()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "tests").mkdir()
            (Path(tmp) / "tests/__init__.py").write_text("", encoding="utf-8")
            test_file = Path(tmp) / naming.test_rel_path("market-data", "series.get")
            test_file.write_text(
                "import unittest\n\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_ok(self) -> None:\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            run = subprocess.run(
                [sys.executable, *argv[1:]],
                cwd=tmp,
                capture_output=True,
                text=True,
                env=dict(os.environ, PYTHONPATH=tmp),
            )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Ran 1 test", run.stderr + run.stdout)

    def test_the_old_argument_list_would_not_have_worked(self) -> None:
        """The bug, kept as a test.

        `tests.test_market_data_series.get.py` — what the documents said
        before — is not a module name unittest can resolve. Asserting the
        failure keeps the reason for the rule from being forgotten when
        somebody tidies the prose back toward the readable-but-wrong form.
        """
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "tests").mkdir()
            (Path(tmp) / "tests/__init__.py").write_text("", encoding="utf-8")
            run = subprocess.run(
                [sys.executable, "-m", "unittest", "tests.test_market_data_series.get.py"],
                cwd=tmp,
                capture_output=True,
                text=True,
                env=dict(os.environ, PYTHONPATH=tmp),
            )
        self.assertNotEqual(run.returncode, 0)


class DocumentedInterpreterTests(unittest.TestCase):
    """`./bin/python` is the interpreter every documented command names.

    Not `python`: there is no `python` on this PATH, and the shell that runs
    these commands reads no profile, so an interpreter that only appears
    after `conda activate` is one the developer and reviewer subagents
    cannot reach. This is the check that a role prompt's command is not
    quietly pointing at nothing.
    """

    def test_the_shim_exists_and_is_executable(self) -> None:
        shim = REPO_ROOT / "bin" / "python"
        self.assertTrue(shim.is_file(), f"{shim} is missing")
        self.assertTrue(os.access(shim, os.X_OK), f"{shim} is not executable")

    @unittest.skipUnless(
        os.access(REPO_ROOT / "bin" / "python", os.X_OK),
        "bin/python is not executable",
    )
    def test_the_shim_runs_the_toolchain(self) -> None:
        run = subprocess.run(
            ["./bin/python", "-m", "tools.implement.naming", "market-data", "series.get"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("tests/test_market_data_series_get.py", run.stdout)

    def test_the_shim_reports_a_missing_env_instead_of_failing_silently(self) -> None:
        run = subprocess.run(
            ["./bin/python", "-V"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=dict(os.environ, LP2_PYTHON="/nonexistent/python"),
        )
        self.assertEqual(run.returncode, 127)
        self.assertIn("no interpreter at", run.stderr)


if __name__ == "__main__":
    unittest.main()
