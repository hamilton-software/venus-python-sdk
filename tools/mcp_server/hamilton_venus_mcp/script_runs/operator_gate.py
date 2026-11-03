"""The human-only path for answering a run's prompts.

An error the SDK cannot recover from by itself, or a tip/liquid reload request, pauses the script
until a *human* decides. MCP cannot tell a person from an agent, so the decision is not an
ordinary tool argument: it needs the operator token (``HAMILTON_MCP_OPERATOR_TOKEN``), which no
tool ever returns and which is stripped from the environment of every script. An agent can see a
prompt and its options (``get_run_events``, ``get_spoke_state``) but cannot answer it; a person
answers through the operator page (``operator_http``) or the hub dashboard, both of which hold
the token.

Repeated wrong tokens lock the gate for a while, so the token cannot be guessed by trial.
"""

from __future__ import annotations

import hmac
import os
import time
from collections import deque
from typing import Any

from hamilton_venus_mcp.script_runs.manager import OPERATOR_TOKEN_ENV, RunManager

MAX_FAILURES = 5
FAILURE_WINDOW_S = 60.0
LOCKOUT_S = 120.0


class OperatorAuthError(PermissionError):
    """The operator token was missing, wrong, or the gate is locked."""


class OperatorGate:
    def __init__(self, manager: RunManager, *, clock: Any = time.monotonic) -> None:
        self._manager = manager
        self._clock = clock
        self._failures: deque[float] = deque()
        self._locked_until = 0.0

    @property
    def configured(self) -> bool:
        return bool(os.environ.get(OPERATOR_TOKEN_ENV, "").strip())

    def verify(self, token: str | None) -> None:
        now = self._clock()
        if now < self._locked_until:
            raise OperatorAuthError(f"Too many wrong tokens; try again in {int(self._locked_until - now) + 1}s.")
        expected = os.environ.get(OPERATOR_TOKEN_ENV, "").strip()
        if not expected:
            raise OperatorAuthError(f"{OPERATOR_TOKEN_ENV} is not set on this spoke, so prompts cannot be answered.")
        if token and hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
            self._failures.clear()
            return
        self._failures.append(now)
        while self._failures and now - self._failures[0] > FAILURE_WINDOW_S:
            self._failures.popleft()
        if len(self._failures) >= MAX_FAILURES:
            self._locked_until = now + LOCKOUT_S
            self._failures.clear()
        raise OperatorAuthError("Wrong operator token.")

    def resolve(
        self,
        token: str | None,
        run_id: str | None,
        prompt_id: str,
        *,
        action: str | None = None,
        channel_actions: dict[str, int] | None = None,
        operator: str | None = None,
        source: str = "operator",
    ) -> dict[str, Any]:
        self.verify(token)
        return self._manager.resolve_prompt(
            run_id,
            prompt_id,
            action=action,
            channel_actions=channel_actions,
            operator=operator,
            source=source,
        )
