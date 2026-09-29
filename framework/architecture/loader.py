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
from .model import (
    BEHAVIOR_FIELDS,
    BEHAVIOR_ORDERING,
    BEHAVIOR_TIME,
    BEHAVIOR_TIMEZONES,
    BEHAVIOR_UNITS,
    CAPABILITY_KINDS,
    RECOVERABLE_KINDS,
    Architecture,
    BehaviorTag,
    Capability,
    Contract,
    Dependency,
    ErrorCode,
    Module,
    SchemaRef,
)

CONTRACTS_DIR = "architecture/contracts"
MODULES_DIR = "architecture/modules"
SCHEMAS_DIR = "architecture/schemas"


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
    for idx, item in enumerate(raw_provides):
        if isinstance(item, str):
            item = {"id": item}
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ArchError(
                INVALID_METADATA, f"{path}: each provides entry needs a string `id`"
            )
        provides.append(_load_capability(item, path, idx))

    rel = path.relative_to(root).as_posix()
    return Contract(
        name=name,
        path=rel,
        version=int(data.get("version", 1)),
        description=str(data.get("description", "")),
        provides=tuple(provides),
        requires=_str_list(data.get("requires"), path, "requires"),
    )


def _load_capability(item: dict, path: Path, idx: int) -> Capability:
    cap_id = item["id"]
    prefix = f"{path}: provides[{idx}] {cap_id}"

    kind = item.get("kind", "operation")
    if kind not in CAPABILITY_KINDS:
        raise ArchError(
            INVALID_METADATA,
            f"{prefix}: `kind` must be one of "
            f"{', '.join(CAPABILITY_KINDS)}, got {kind!r}",
        )

    has_input = "input" in item
    has_output = "output" in item
    has_payload = "payload" in item

    input_ref: SchemaRef | None = None
    output_ref: SchemaRef | None = None
    payload_ref: SchemaRef | None = None
    errors: tuple[ErrorCode, ...] = ()

    if kind == "operation":
        if has_payload:
            raise ArchError(
                INVALID_METADATA,
                f"{prefix}: `payload` only allowed for kind `event`",
            )
        input_ref = _parse_schema_ref(item.get("input"), prefix, "input")
        output_ref = _parse_schema_ref(item.get("output"), prefix, "output")
        errors = _parse_errors(item.get("errors", []), prefix)
    elif kind == "event":
        if has_input or has_output:
            raise ArchError(
                INVALID_METADATA,
                f"{prefix}: kind `event` must not declare `input` or `output`",
            )
        payload_ref = _parse_schema_ref(item.get("payload"), prefix, "payload")
    else:  # data
        if has_input or has_payload:
            raise ArchError(
                INVALID_METADATA,
                f"{prefix}: kind `data` must not declare `input` or `payload`",
            )
        output_ref = _parse_schema_ref(item.get("output"), prefix, "output")

    behavior = _parse_behavior(item.get("behavior"), prefix)

    return Capability(
        id=cap_id,
        kind=kind,
        signature=str(item.get("signature", "")),
        description=str(item.get("description", "")),
        input=input_ref,
        output=output_ref,
        payload=payload_ref,
        errors=errors,
        behavior=behavior,
    )


def _parse_schema_ref(raw: Any, prefix: str, field_name: str) -> SchemaRef | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return SchemaRef(schema=raw)
    if isinstance(raw, dict) and isinstance(raw.get("schema"), str):
        return SchemaRef(schema=raw["schema"])
    raise ArchError(
        INVALID_METADATA,
        f"{prefix}: `{field_name}` must be a schema id string or {{schema: <id>}}",
    )


def _parse_errors(raw: Any, prefix: str) -> tuple[ErrorCode, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ArchError(
            INVALID_METADATA, f"{prefix}: `errors` must be a list of code strings or objects"
        )
    out: list[ErrorCode] = []
    for idx, item in enumerate(raw):
        if isinstance(item, str):
            out.append(ErrorCode(code=item))
            continue
        if isinstance(item, dict) and isinstance(item.get("code"), str):
            recoverable = str(item.get("recoverable", "transient"))
            if recoverable not in RECOVERABLE_KINDS:
                raise ArchError(
                    INVALID_METADATA,
                    f"{prefix}: errors[{idx}].recoverable must be one of "
                    f"{', '.join(RECOVERABLE_KINDS)}, got {recoverable!r}",
                )
            out.append(ErrorCode(code=item["code"], recoverable=recoverable))
            continue
        raise ArchError(
            INVALID_METADATA,
            f"{prefix}: errors[{idx}] must be a string or {{code, recoverable}}",
        )
    return tuple(out)


def _parse_behavior(raw: Any, prefix: str) -> BehaviorTag | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ArchError(INVALID_METADATA, f"{prefix}: `behavior` must be a mapping")
    unknown = sorted(set(raw) - BEHAVIOR_FIELDS)
    if unknown:
        raise ArchError(
            INVALID_METADATA,
            f"{prefix}: unknown behavior field(s) {unknown}; a behavior block "
            f"may only carry {sorted(BEHAVIOR_FIELDS)}. Unrecognised keys used "
            f"to be dropped silently, so a contract could assert anything here "
            f"and validate clean while promising nothing.",
        )
    kwargs: dict[str, Any] = {}
    if "unit" in raw:
        unit = str(raw["unit"])
        if unit not in BEHAVIOR_UNITS:
            raise ArchError(
                INVALID_METADATA,
                f"{prefix}: behavior.unit must be one of "
                f"{', '.join(u for u in BEHAVIOR_UNITS if u)}, got {unit!r}",
            )
        kwargs["unit"] = unit
    if "time" in raw:
        t = str(raw["time"])
        if t not in BEHAVIOR_TIME:
            raise ArchError(
                INVALID_METADATA,
                f"{prefix}: behavior.time must be one of "
                f"{', '.join(t for t in BEHAVIOR_TIME if t)}, got {t!r}",
            )
        kwargs["time"] = t
    if "timezone" in raw:
        tz = str(raw["timezone"])
        if tz not in BEHAVIOR_TIMEZONES:
            raise ArchError(
                INVALID_METADATA,
                f"{prefix}: behavior.timezone must be one of "
                f"{', '.join(t for t in BEHAVIOR_TIMEZONES if t)}, got {tz!r}",
            )
        kwargs["timezone"] = tz
    if "idempotent" in raw:
        val = raw["idempotent"]
        if not isinstance(val, bool):
            raise ArchError(
                INVALID_METADATA, f"{prefix}: behavior.idempotent must be a boolean"
            )
        kwargs["idempotent"] = val
    if "ordering" in raw:
        o = str(raw["ordering"])
        if o not in BEHAVIOR_ORDERING:
            raise ArchError(
                INVALID_METADATA,
                f"{prefix}: behavior.ordering must be one of "
                f"{', '.join(o for o in BEHAVIOR_ORDERING if o)}, got {o!r}",
            )
        kwargs["ordering"] = o
    if "stale_tolerance" in raw:
        kwargs["stale_tolerance"] = str(raw["stale_tolerance"])
    return BehaviorTag(**kwargs)


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

    schemas_dir = root_path / SCHEMAS_DIR
    if schemas_dir.is_dir():
        for f in sorted(schemas_dir.glob("*.yaml")) + sorted(schemas_dir.glob("*.yml")):
            data = _load_yaml(f)
            # The file name is the owning contract; the top level maps a
            # TypeName to a JSON Schema. A file named for a contract that does
            # not exist is an error, not a stray — otherwise a typo silently
            # produces a schema nothing can reference.
            owner = f.stem
            if owner not in arch.contracts:
                raise ArchError(
                    INVALID_METADATA,
                    f"{f}: schema file names contract `{owner}`, which is not "
                    f"defined in {CONTRACTS_DIR}/",
                )
            for type_name, body in data.items():
                if not isinstance(body, dict):
                    raise ArchError(
                        INVALID_METADATA,
                        f"{f}: schema `{type_name}` must be a mapping (a JSON "
                        f"Schema object), got {type(body).__name__}",
                    )
                key = f"{owner}.{type_name}"
                if key in arch.schemas:
                    raise ArchError(
                        INVALID_METADATA,
                        f"{f}: duplicate schema `{key}` (also defined in "
                        f"{schemas_dir}/{owner}.yaml)",
                    )
                arch.schemas[key] = body

    return arch
