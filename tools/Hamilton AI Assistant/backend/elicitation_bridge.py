"""Answers MCP form requests (elicitation) from the agent engine.

When the hamilton-venus server asks the user something -- start_session's simulation/live
and deck layout questions -- the engine sends the SDK host an "elicitation" control request
and waits for {"action": "accept" | "decline" | "cancel", "content": {...}}. claude-agent-sdk
0.2.174 has no option for this and rejects the request, which the engine turns into "cancel"
(the server then never gets an answer). install() wraps the SDK's control-request handler so
those requests go to the handler set with set_handler(); everything else passes through.

Pinned to claude-agent-sdk 0.2.174 (pyproject.toml): drop this module once the SDK has its
own elicitation callback.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from claude_agent_sdk._internal import query as _query_module

_logger = logging.getLogger(__name__)

# (request data from the engine) -> {"action": ..., "content": {...}}
ElicitationHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

_handler: ElicitationHandler | None = None
_original = _query_module.Query._handle_control_request


def set_handler(handler: ElicitationHandler | None) -> None:
    global _handler
    _handler = handler


async def _handle_control_request(self, request: dict[str, Any]) -> None:
    data = request.get("request") or {}
    if data.get("subtype") != "elicitation":
        return await _original(self, request)
    answer: dict[str, Any] = {"action": "cancel"}
    if _handler is not None:
        try:
            answer = await _handler(data)
        except Exception:
            _logger.exception("Answering a form request failed; sending cancel")
    response = {
        "type": "control_response",
        "response": {"subtype": "success", "request_id": request["request_id"], "response": answer},
    }
    await self.transport.write(json.dumps(response) + "\n")


def install() -> None:
    _query_module.Query._handle_control_request = _handle_control_request
