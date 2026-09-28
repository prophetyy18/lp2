"""One naming rule for the files a run produces.

Module names are hyphenated and capability ids are dotted (`market-data`,
`series.get`). Neither can appear verbatim in a Python module path: a hyphen
is not an identifier character, and a dot is a package separator. So every
place that needed a test file name had to invent its own translation, and
they disagreed:

  - the write-scope audit compared against `tests/test_market-data_series.get`,
    a filename no writer could ever produce, so a developer's own test file
    read as a SCOPE_VIOLATION — the layer AGENTS.md calls "the layer that
    actually holds" was the one thing guaranteed to block the first real run;
  - the state CLI accepted `tests/test_market_data*`, a different rule;
  - four documents spelled the convention as prose, including two
    `./bin/python -m unittest tests.test_<module>_<cap>.py` invocations that cannot
    work for any real module: the `.py` suffix is not a unittest argument,
    and a capability id's dot would be read as attribute access.

None of this survived review because the fixtures used `alpha` / `one` — the
only names in the repository for which the broken rule happens to be correct.

This module is the only place the translation happens. The CLIs call it, the
documents point at it, and `./bin/python -m tools.implement.naming <module> <cap>`
prints the answer for whoever has to write the file by hand.

Usage:
    ./bin/python -m tools.implement.naming <module> <capability>
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# The interpreter every documented command in this repository runs on. Not
# `python`: there is no `python` on this PATH, and the shell that runs these
# commands reads no profile, so an interpreter that only appears after
# `conda activate` is one the workflow cannot rely on. See bin/python.
PYTHON = "./bin/python"

# Artifact kinds written under docs/implement/<module>/. The capability id
# keeps its dots here (`series.get.manifest.md`) because these are Markdown
# paths, not Python module paths; only the test files need translating.
ARTIFACT_KINDS: tuple[str, ...] = (
    "card",
    "manifest",
    "review",
    "design-blocker",
    "mvp-manifest",
    "design-blocker.resolved",
)


def slug(text: str) -> str:
    """Every run of non-identifier characters becomes a single `_`.

    Hyphens and dots both land here, which is the whole point: it is the one
    translation, applied identically wherever a name has to survive as a
    Python identifier.
    """
    return re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_")


def test_stem(module: str, capability: str) -> str:
    """`test_market_data_series_get` — the file's stem, with no extension."""
    return f"test_{slug(module)}_{slug(capability)}"


def test_path_prefix(module: str, capability: str) -> str:
    """Repo-relative path without the extension, for prefix comparisons.

    The write-scope audit matches by prefix so that a developer's own
    `..._helpers.py` next to `..._series_get.py` is also inside the grant.
    """
    return f"tests/{test_stem(module, capability)}"


def test_rel_path(module: str, capability: str) -> str:
    """The canonical test file: `tests/test_market_data_series_get.py`."""
    return test_path_prefix(module, capability) + ".py"


def test_module_path(module: str, capability: str) -> str:
    """The importable dotted path — what `./bin/python -m unittest` takes.

    Not the same string as the file path, and the difference matters:
    unittest resolves its argument as a module name, so passing a `.py`
    filename, a hyphen, or a capability id's dot each fail differently.
    """
    return f"tests.{test_stem(module, capability)}"


def unittest_command(module: str, capability: str) -> str:
    return f"{PYTHON} -m unittest {test_module_path(module, capability)} -v"


def module_test_prefix(module: str) -> str:
    """Files counting as this module's tests, any capability.

    Deliberately wider than `test_path_prefix`: a gate that only knows a
    module cannot know which of its files belong to which capability, so
    `_require_work_exists` asks the weaker question the data can answer. The
    write-scope audit, which does know the capability, asks the exact one.
    """
    return f"test_{slug(module)}"


def artifact_in(directory: str | Path, capability: str, kind: str) -> Path:
    """One capability's artifact, given the directory that holds it."""
    return Path(directory) / f"{capability}.{kind}.md"


def artifact_path(
    root: str | Path, module: str, capability: str, kind: str
) -> Path:
    """`docs/implement/<module>/<capability>.<kind>.md`, by default."""
    return artifact_in(Path(root) / module, capability, kind)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="./bin/python -m tools.implement.naming",
        description="the canonical file names for one capability's run",
    )
    p.add_argument("module")
    p.add_argument("capability")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path("docs/implement") / args.module
    print(f"test file:    {test_rel_path(args.module, args.capability)}")
    print(f"run tests:    {unittest_command(args.module, args.capability)}")
    if not (Path("tests") / "__init__.py").is_file():
        # The command above resolves `tests.<stem>` as a module, so it needs
        # tests/ to be a package. It is in this repository; saying so here
        # beats a bare ModuleNotFoundError if it ever is not.
        print(
            "note:         tests/__init__.py is missing — the command above "
            "resolves tests.<stem> as a module and will fail without it",
            file=sys.stderr,
        )
    print(f"card:         {root / f'{args.capability}.card.md'}")
    print(f"manifest:     {root / f'{args.capability}.manifest.md'}")
    print(f"review:       {root / f'{args.capability}.review.md'}")
    print(f"mvp archive:  {root / f'{args.capability}.mvp-manifest.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
