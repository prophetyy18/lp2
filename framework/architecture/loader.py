"""Load architecture metadata from disk.

Layout (repo root):
    architecture/contracts/<contract>.yaml
    architecture/modules/<module>/module.yaml
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .errors import ArchError, INVALID_METADATA
from .model import Architecture, Capability, Contract, Dependency, Module

CONTRACTS_DIR = "architecture/contracts"
MODULES_DIR = "architecture/modules"


def find_root(start: str | os.PathLike[str] | None = None) -> Path:
    """Locate the repo root: the nearest ancestor containing `architecture/`."""
    env = os.environ.get("ARCH_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(start or Path.cwd()).resolve()
    for cand in [here, *here.parents]:
        if (cand / CONTRACTS_DIR).is_dir() or (cand / MODULES_DIR).is_dir():
            return cand
    return here


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - depends on bad input
        raise ArchError(INVALID_METADATA, f"cannot parse {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ArchError(INVALID_METADATA, f"{path}: top level must be a mapping")
    return data


def _require(data: dict[str, Any], key: str, path: Path, types: tuple) -> Any:
    if key not in data or data[key] is None:
        raise ArchError(INVALID_METADATA, f"{path}: missing required field `{key}`")
    val = data[key]
    if types and not isinstance(val, types):
        want = "/".join(t.__name__ for t in types)
        raise ArchError(INVALID_METADATA, f"{path}: `{key}` must be {want}")
    return val


def _str_list(value: Any, path: Path, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ArchError(INVALID_METADATA, f"{path}: `{field_name}` must be a list of strings")
    return tuple(value)


def _load_contract(path: Path, root: Path) -> Contract:
    data = _load_yaml(path)
    name = data.get("name", path.stem)
    if not isinstance(name, str) or not name:
        raise ArchError(INVALID_METADATA, f"{path}: `name` must be a non-empty string")

    provides: list[Capability] = []
    raw_provides = data.get("provides") or []
    if not isinstance(raw_provides, list):
        raise ArchError(INVALID_METADATA, f"{path}: `provides` must be a list")
    for item in raw_provides:
        if isinstance(item, str):
            item = {"id": item}
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ArchError(INVALID_METADATA, f"{path}: each provides entry needs a string `id`")
        provides.append(
            Capability(
                id=item["id"],
                kind=str(item.get("kind", "opaque")),
                signature=str(item.get("signature", "")),
                description=str(item.get("description", "")),
            )
        )

    rel = path.relative_to(root).as_posix()
    return Contract(
        name=name,
        path=rel,
        version=int(data.get("version", 1)),
        description=str(data.get("description", "")),
        provides=tuple(provides),
        requires=_str_list(data.get("requires"), path, "requires"),
    )


def _load_module(path: Path, root: Path) -> Module:
    data = _load_yaml(path)
    name = _require(data, "name", path, (str,))
    src = data.get("source") or f"modules/{name}"

    raw_deps = data.get("depends_on") or []
    if not isinstance(raw_deps, list):
        raise ArchError(INVALID_METADATA, f"{path}: `depends_on` must be a list")
    deps: list[Dependency] = []
    for item in raw_deps:
        if isinstance(item, str):
            item = {"contract": item}
        if not isinstance(item, dict) or not isinstance(item.get("contract"), str):
            raise ArchError(
                INVALID_METADATA, f"{path}: each depends_on entry needs a string `contract`"
            )
        deps.append(
            Dependency(
                contract=item["contract"],
                uses=_str_list(item.get("uses"), path, "depends_on[].uses"),
                reason=str(item.get("reason", "")),
            )
        )

    return Module(
        name=name,
        path=str(src),
        description=str(data.get("description", "")),
        depends_on=tuple(deps),
        owns_contracts=_str_list(data.get("provides_contracts"), path, "provides_contracts"),
        readable_extra=_str_list(data.get("readable_extra"), path, "readable_extra"),
    )


def load(root: str | os.PathLike[str] | None = None) -> Architecture:
    """Load all contracts and modules. Raises ArchError on unusable metadata."""
    root_path = Path(root).resolve() if root else find_root()
    arch = Architecture(root=str(root_path))

    contracts_dir = root_path / CONTRACTS_DIR
    if contracts_dir.is_dir():
        for f in sorted(contracts_dir.glob("*.yaml")) + sorted(contracts_dir.glob("*.yml")):
            contract = _load_contract(f, root_path)
            if contract.name in arch.contracts:
                raise ArchError(
                    INVALID_METADATA,
                    f"{f}: duplicate contract name `{contract.name}` "
                    f"(also defined in {arch.contracts[contract.name].path})",
                )
            arch.contracts[contract.name] = contract

    modules_dir = root_path / MODULES_DIR
    if modules_dir.is_dir():
        for f in sorted(modules_dir.glob("*/module.yaml")) + sorted(
            modules_dir.glob("*/module.yml")
        ):
            module = _load_module(f, root_path)
            if module.name in arch.modules:
                raise ArchError(
                    INVALID_METADATA,
                    f"{f}: duplicate module name `{module.name}` "
                    f"(also defined in {arch.modules[module.name].path})",
                )
            arch.modules[module.name] = module

    return arch
