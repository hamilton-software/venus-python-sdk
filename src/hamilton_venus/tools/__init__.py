from __future__ import annotations

import sys

from hamilton_venus.tools.generate_catalog import main as _generate_catalog_main
from hamilton_venus.tools.generate_error_simulator_data import main as _generate_error_simulator_main

_COMMANDS = {"generate-catalog", "generate-error-simulator-data"}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] not in _COMMANDS:
        raise SystemExit(f"Usage: venus-sdk [{' | '.join(sorted(_COMMANDS))}] [options]")
    command, *rest = args
    if command == "generate-catalog":
        return _generate_catalog_main(rest)
    if command == "generate-error-simulator-data":
        return _generate_error_simulator_main(rest)
    raise SystemExit(f"Unknown command: {command!r}")  # pragma: no cover


__all__ = ["main"]
