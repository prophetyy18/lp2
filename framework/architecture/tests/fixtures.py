"""Shared test helpers: build throwaway architecture trees on disk."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import yaml

from framework.architecture import loader


def write_tree(root: Path, contracts: dict[str, dict], modules: dict[str, dict],
               schemas: dict[str, dict] | None = None) -> Path:
    cdir = root / "architecture" / "contracts"
    mdir = root / "architecture" / "modules"
    cdir.mkdir(parents=True, exist_ok=True)
    mdir.mkdir(parents=True, exist_ok=True)
    for name, body in contracts.items():
        (cdir / f"{name}.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    for name, body in modules.items():
        target = mdir / name
        target.mkdir(parents=True, exist_ok=True)
        (target / "module.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    if schemas:
        sdir = root / "architecture" / "schemas"
        sdir.mkdir(parents=True, exist_ok=True)
        for name, body in schemas.items():
            (sdir / f"{name}.yaml").write_text(
                yaml.safe_dump(body, sort_keys=False), encoding="utf-8"
            )
    return root


def base_contracts() -> dict[str, dict]:
    return {
        "alpha-api": {
            "name": "alpha-api",
            "version": 1,
            "requires": [],
            "provides": [{"id": "alpha.one"}, {"id": "alpha.two"}],
        },
        "beta-api": {
            "name": "beta-api",
            "version": 1,
            "requires": ["alpha-api"],
            "provides": [{"id": "beta.one"}],
        },
    }


def base_modules() -> dict[str, dict]:
    return {
        "alpha": {"name": "alpha", "provides_contracts": ["alpha-api"], "depends_on": []},
        "beta": {
            "name": "beta",
            "provides_contracts": ["beta-api"],
            "depends_on": [{"contract": "alpha-api", "uses": ["alpha.one"]}],
        },
    }


def load_real() -> object:
    """The actual project architecture in the repo root."""
    return loader.load(Path(__file__).resolve().parents[3])


CONTRACT_INSUFFICIENT_YAML = dedent(
    """
    name: alpha-api
    version: 1
    requires: []
    provides:
      - id: alpha.one
    """
)
