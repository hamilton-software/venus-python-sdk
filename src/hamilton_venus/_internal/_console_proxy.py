"""Console proxy for capturing print() and input() in the run log."""

from __future__ import annotations

import builtins
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hamilton_venus._internal._run_log import RunLog


class ConsoleProxy:
    """Intercepts ``builtins.print`` and ``builtins.input`` to record console I/O in the run log.

    The proxy stores references to the original builtins and restores them on
    :meth:`uninstall`, even if an exception occurs.

    **Capture scope:**
    - ``print()`` calls that write to stdout (default) are captured.
    - ``print()`` calls with an explicit `file` argument targeting a different stream are **not** captured.
    - ``input()`` calls are always captured regardless of the prompt.
    """

    def __init__(
        self,
        run_log: RunLog,
        *,
        input_fn: Any | None = None,
    ) -> None:
        self._run_log = run_log
        self._original_print = builtins.print
        self._original_input = input_fn if input_fn is not None else builtins.input
        self._installed = False

    def install(self) -> None:
        """Replace ``builtins.print`` and ``builtins.input`` with logging wrappers."""
        if self._installed:
            return

        original_print = self._original_print
        original_input = self._original_input
        run_log = self._run_log

        def _proxy_print(*args: Any, **kwargs: Any) -> None:
            original_print(*args, **kwargs)
            # Only log prints that go to stdout (the default).
            # If a user explicitly passes file=something_else, we don't capture it.
            file = kwargs.get("file", sys.stdout)
            if file is not sys.stdout:
                return
            # Build the message the same way print() does.
            sep = kwargs.get("sep", " ")
            if sep is None:
                sep = " "
            end = kwargs.get("end", "\n")
            if end is None:
                end = "\n"
            message = sep.join(str(a) for a in args) + end
            # Strip the trailing newline for cleaner log entries.
            message = message.rstrip("\n")
            run_log.record("Console", "Out", "script_output", {"message": message})

        def _proxy_input(prompt: str = "") -> str:
            result = original_input(prompt)
            run_log.record("Console", "In", "operator_input", {"prompt": prompt, "value": result})
            return result

        builtins.print = _proxy_print
        builtins.input = _proxy_input  # type: ignore[assignment]
        self._installed = True

    def uninstall(self) -> None:
        """Restore the original ``builtins.print`` and ``builtins.input``."""
        if not self._installed:
            return
        builtins.print = self._original_print
        builtins.input = self._original_input
        self._installed = False

