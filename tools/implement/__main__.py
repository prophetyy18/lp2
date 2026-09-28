"""`./bin/python -m tools.implement` CLI entry."""

import sys

from .naming import main as naming_main
from .scope import main as scope_main
from .state import main as state_main


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "scope":
        return scope_main(argv[1:])
    if argv and argv[0] == "naming":
        return naming_main(argv[1:])
    return state_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
