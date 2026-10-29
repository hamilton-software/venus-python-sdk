"""Operator prompt callback infrastructure for compound commands.

This module defines dedicated callback channels used by compound commands to
ask the operator a yes/no coordination question (e.g. "please reload the tip
rack" or "please refill the diluent trough"). They are intentionally separate
from :mod:`hamilton_venus._internal._operator_escalation_bridge`, which is
bound to post-retry instrument-error escalation and carries ``ErrorData``
payloads with a different return contract.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar


@dataclass(frozen=True)
class TipReloadPromptContext:
    """Payload passed to a :data:`TipReloadPromptCallback`.

    Attributes:
        tip_pool: Name of the tip pool that is short on tips.
        required: Number of tips the caller needs.
        available: Number of tips currently reported by the pool.
        command: Name of the compound command issuing the prompt (e.g.
            ``"add_reagent"``).
        attempt: 1-based attempt counter within a single
            :func:`ensure_tips_available` call. Increments per re-prompt.
    """

    tip_pool: str
    required: int
    available: int
    command: str
    attempt: int


TipReloadPromptCallback = Callable[
    [TipReloadPromptContext],
    bool | Awaitable[bool],
]
"""Callable invoked by ``ensure_tips_available`` when tips are short.

Returning ``True`` (or an awaitable resolving to ``True``) signals that the
operator has reloaded the tip rack and the compound command should retry.
Returning ``False`` / ``None`` (or an awaitable thereof) signals cancellation;
the caller will raise :class:`~hamilton_venus.exceptions.OperatorCancelledError`.
"""


@dataclass(frozen=True)
class LiquidReloadPromptContext:
    """Payload passed to a :data:`LiquidReloadPromptCallback`.

    The callback name is deliberately generic: it serves both diluent (serial
    dilution) and reagent reloads, so it is named for the liquid being
    reloaded rather than any single command.

    Attributes:
        sources: The ordered list of source selectors the caller consumes.
        active_source: The source selector that has run dry.
        required: Per-channel volume (µL) the next aspiration needs.
        available: Estimated per-channel volume (µL) remaining in
            ``active_source`` (the min across active channels).
        command: Name of the compound command issuing the prompt (e.g.
            ``"serial_dilution"``).
        attempt: 1-based attempt counter within a single
            :func:`ensure_liquid_available` call. Increments per re-prompt.
    """

    sources: tuple[str, ...]
    active_source: str
    required: float
    available: float
    command: str
    attempt: int


LiquidReloadPromptCallback = Callable[
    [LiquidReloadPromptContext],
    bool | Awaitable[bool],
]
"""Callable invoked by ``ensure_liquid_available`` when a liquid source is exhausted.

Returning ``True`` (or an awaitable resolving to ``True``) signals that the
operator has refilled / replaced the source and the compound command should
re-read the level and retry.  Returning ``False`` / ``None`` (or an awaitable
thereof) signals cancellation; the caller will raise
:class:`~hamilton_venus.exceptions.OperatorCancelledError`.
"""


_ContextT = TypeVar("_ContextT")


def _invoke_callback(
    callback: Callable[[_ContextT], bool | Awaitable[bool]],
    context: _ContextT,
) -> bool:
    """Invoke *callback* with *context* and return its boolean result.

    Supports both synchronous and ``async`` callbacks.  Async callbacks are
    dispatched via :func:`asyncio.run` because the reload-loop helpers are
    always called from the synchronous compound-command thread (no event loop
    is running on the calling thread).

    Any non-truthy return value (``False``, ``None``, ``0``, etc.) is
    normalised to ``False``.
    """

    async def _await_result(awaitable: Awaitable[bool]) -> bool:
        return await awaitable

    if inspect.iscoroutinefunction(callback):
        result: bool | Awaitable[bool] = asyncio.run(callback(context))
    else:
        raw = callback(context)
        result = asyncio.run(_await_result(raw)) if inspect.isawaitable(raw) else raw
    return bool(result)
