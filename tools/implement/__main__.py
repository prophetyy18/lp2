"""`python -m tools.implement` CLI entry."""

import sys

from .state import main as state_main
from .scope import main as scope_main


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "scope":
        return scope_main(argv[1:])
    return state_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
