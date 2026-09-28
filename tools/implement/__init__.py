"""Implementation workflow tooling.

Two CLIs live here:

  `./bin/python -m tools.implement.state`   capability state machine (STATE.yaml)
  `./bin/python -m tools.implement.scope`   write-scope audit for one module
  `./bin/python -m tools.implement.naming`  the file names one capability's run uses

Submodule names are exposed lazily. Eagerly importing `.state` here would put
it in `sys.modules` before `-m tools.implement.state` executes it, which makes
CPython emit a RuntimeWarning on every documented invocation.
"""

from typing import Any

__all__ = ["STATE_ROOT", "CapabilityState", "ModuleState", "load_state", "save_state"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import state

        return getattr(state, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
