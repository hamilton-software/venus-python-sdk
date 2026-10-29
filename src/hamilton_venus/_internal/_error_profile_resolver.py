"""Error profile resolver — translates instrument error events to recovery submissions.

The ``ErrorProfileResolver`` handles the full ``on_instrument_error`` lifecycle:
classification, profile lookup, retry tracking, deadline suspension, and
recovery submission to the VENUS WebAPI.

The resolver depends on three injected collaborators:

* ``VenusClient`` — REST submission of error recovery/action payloads.
* ``CommandDeadlineControl`` — suspends command timeouts during recovery.
* ``ErrorClassifier`` — maps raw ``ErrorData`` to (category, error_type) pairs.

The resolver is instrument-agnostic; the same class is used for STAR,
Vantage, and other supported instruments.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from hamilton_venus.error_handling.access_actions import is_access_action_recovery
from hamilton_venus.error_handling.actions import ALLOWED_ACTIONS
from hamilton_venus.error_handling.profile import ErrorEntry, ErrorProfile
from hamilton_venus.models.error_types import ActionKind, OperationCategory, RecoveryAction
from hamilton_venus.models.instrument_errors import (
    DetailedError,
    DetailedErrorRecovery,
    ErrorData,
    ErrorRecovery,
    InstrumentErrorHandled,
    RecoveryActionDescriptor,
)

if TYPE_CHECKING:
    from hamilton_venus._internal._error_classifier import ErrorClassifier
    from hamilton_venus.venus_client import VenusClient

_logger = logging.getLogger(__name__)

# Per-channel ``selectedActionId`` sent with the legacy-dialog fallback (the top-level one is -1).
_LEGACY_DIALOG_CHANNEL_ACTION_ID = 0

_EXECUTE_ACTION_NAME = "execute"

_DEFAULT_RETRY_TRACKING_TTL_SECONDS = 900
_DEFAULT_SUSPENSION_TIMEOUT_SECONDS = 600.0
_POST_SUBMIT_RECHECK_DELAY_SECONDS = 1.0
_POST_SUBMIT_RECHECK_MAX_ATTEMPTS = 2
# How long to wait for VENUS to publish an error again after an access action
# (door / loading tray) before asking the operator again without it.
_ACCESS_ACTION_REPUBLISH_TIMEOUT_SECONDS = 15.0


@runtime_checkable
class CommandDeadlineControl(Protocol):
    """Protocol for suspending command timeouts during instrument error recovery.

    Call ``suspend()`` when beginning to handle an instrument error and
    ``resume()`` when recovery is complete (or has been handed off to the
    server).  The implementor manages the deadline counter and any fallback
    timer internally.
    """

    def suspend(self) -> None:
        """Increment the suspension counter, pausing the active command timeout."""
        ...

    def resume(self) -> None:
        """Decrement the suspension counter, restoring the timeout when it hits zero."""
        ...

    def pause_suspension_fallback(self) -> None:
        """Drop the suspension fallback timer while an operator callback is deciding."""
        ...

    def hold_for_operator(self) -> None:
        """Keep the in-flight command's timeout suspended until that command finishes.

        Used after handing an error to VENUS's operator dialog, whose "handled"
        event arrives as soon as the handoff is accepted, not when it is answered.
        """
        ...

    def get_operation_context(self) -> str | None:
        """Return a string identifying the most recently dispatched command.

        Used by the classifier to resolve context-dependent error codes that
        require knowing the operation type (e.g. aspirate vs dispense).
        Returns ``None`` when no command has been dispatched yet.
        """
        ...


@dataclass
class OperatorEscalationContext:
    """Context information passed to operator escalation callbacks.

    Attributes
    ----------
    error:
        The raw ``ErrorData`` from the instrument.
    entry:
        The ``ErrorEntry`` that was active for this error (captures the profile
        entry whose retries were exhausted).
    operation_category:
        The classified operation category (e.g., TIP_PICKUP, ASPIRATE).
        ``None`` if classification failed.
    error_type:
        The classified error type within the operation.
        ``None`` if classification failed.
    top_level_actions:
        Recovery actions available at the top level of the error.
        Use these for main error-level choices (e.g., Execute, Abort, Cancel).
    per_channel_actions:
        Recovery actions common to all per-channel errors (if any).
        Use these for per-channel-level choices.
    is_per_channel_escalation:
        ``True`` if escalation is due to per-channel action chain exhaustion,
        ``False`` if it's a top-level action exhaustion.
    """

    error: ErrorData
    entry: ErrorEntry
    operation_category: OperationCategory | None
    error_type: Enum | None
    top_level_actions: list[RecoveryActionDescriptor]
    per_channel_actions: list[RecoveryActionDescriptor]
    is_per_channel_escalation: bool


OperatorEscalationCallback = Callable[
    ["OperatorEscalationContext"],
    RecoveryAction | ErrorRecovery | Awaitable[RecoveryAction | ErrorRecovery | None] | None,
]
"""Callback invoked when an error escalates to operator intervention.

Both synchronous and asynchronous callables are supported. Sync callbacks
are run in a thread executor so they do not block the event loop (safe for
GUI dialogs that block). Async callbacks are awaited directly.

The callback can return:
- A ``RecoveryAction`` enum: the resolver automatically dispatches to the
  correct submission path (top-level vs per-channel based on context).
- An ``ErrorRecovery`` payload: submitted directly to the VENUS API with
  full user control over action IDs and per-channel selections.
- ``None``: falls back to ABORT.

Parameters
----------
context:
    An ``OperatorEscalationContext`` containing the error, entry, classification
    info, and available actions (both top-level and per-channel).
"""


@dataclass
class _RetryState:
    """Per-UUID retry tracking entry, created at first InstrumentErrorEvent receipt.

    Tracks the progression through the action chain in an ErrorEntry.

    Attributes
    ----------
    profile
        The ErrorProfile that was active when this error was first seen.
    entry
        The ErrorEntry from the profile that applies to this error.
    operation_category
        The classified operation context (e.g., tip_pickup, aspirate).
    error_type
        The classified error type within that operation.
    retry_count
        Number of times the current action at ``action_index`` has been
        submitted. For REPEAT actions, this increments until reaching
        ``entry.max_retries``. For non-REPEAT actions, this is always 0
        (reset each time ``action_index`` advances). This counter is
        per-action-slot, not per-error-lifecycle.
    action_index
        Current position in the ``entry.actions`` sequence. Increments when
        REPEAT budget is exhausted or when any non-REPEAT action is selected.
    created_at
        Wall-clock time when this state was created (used for TTL pruning).
    """

    profile: ErrorProfile
    entry: ErrorEntry
    operation_category: OperationCategory | None
    error_type: Enum | None
    retry_count: int
    action_index: int
    created_at: float = field(default_factory=time.time)
    last_action: RecoveryAction | None = None
    device_id: int = 0
    channel_index: int = -1


class ErrorProfileResolver:
    """Resolves instrument errors using the active ``ErrorProfile``.

    On each instrument error event the resolver:

    1. Classifies the error into an operation category and error type.
    2. Looks up the matching ``ErrorEntry`` from the active profile (exact
       match → operation default → global default).
    3. Skips submission if the server-reported timeout has already expired.
    4. Tracks per-UUID retry state across repeated events for the same error.
    5. Selects the next valid recovery action, skipping any that are not
       permitted for the error type or not advertised by the server.
    6. Submits the recovery payload to VENUS.
    7. Escalates when the action chain is exhausted or when no valid actions
       remain. If ``allow_operator=False`` on the active entry, the SDK
       submits ABORT. If ``allow_operator=True`` and an operator callback is
       registered, the callback is invoked to decide. If ``allow_operator=True``
       but no callback is registered, the SDK submits ``selected_action_id=-1``
       so VENUS falls back to its legacy operator dialog.

    Parameters
    ----------
    venus_client:
        Low-level REST client for submitting error recovery.
    deadline_control:
        Implementor of the ``CommandDeadlineControl`` protocol.
    profile:
        Initial active error profile.
    classifier:
        Instrument-specific error classifier.
    error_handler_key:
        Key passed in every ``ErrorRecovery`` payload so VENUS identifies
        this SDK instance as the registered error handler.
    retry_tracking_ttl_seconds:
        How long (in wall-clock seconds) to keep retry-tracking entries for
        UUIDs that never received a ``DeviceErrorHandledResponse``.
    """

    def __init__(
        self,
        venus_client: VenusClient,
        deadline_control: CommandDeadlineControl,
        profile: ErrorProfile,
        classifier: ErrorClassifier,
        error_handler_key: str,
        retry_tracking_ttl_seconds: int = _DEFAULT_RETRY_TRACKING_TTL_SECONDS,
        on_operator_error_escalation: OperatorEscalationCallback | None = None,
    ) -> None:
        self._venus = venus_client
        self._deadline_control = deadline_control
        self._active_profile = profile
        self._classifier = classifier
        self._error_handler_key = error_handler_key
        self._retry_tracking_ttl_seconds = retry_tracking_ttl_seconds
        self._retry_tracking: dict[str, _RetryState] = {}
        self._retry_lock = asyncio.Lock()
        self._on_operator_error_escalation = on_operator_error_escalation
        _logger.info(
            "ErrorProfileResolver init: operator escalation callback provided=%s",
            on_operator_error_escalation is not None,
        )
        self._detail_map: dict[str, list[str]] = {}
        self._pending_detailed_errors: dict[str, ErrorData] = {}
        self._channel_carry_over: dict[tuple[int, int], _RetryState] = {}
        # UUIDs handed off to the legacy VENUS operator dialog (selected_action_id=-1).
        # For these the command deadline stays suspended until the operator responds
        # (signalled by a DeviceErrorHandledResponse), rather than being resumed at the
        # end of resolution.
        self._pending_operator_handoffs: set[str] = set()
        # UUIDs whose operator callback is waiting for an answer right now.
        self._escalating: set[str] = set()
        # UUIDs for which an access action (door / loading tray) was submitted: the
        # error is not answered, VENUS publishes it again and the operator is asked
        # again with the arguments kept here. The command deadline stays suspended
        # in between (``_suspension_handed_over``).
        self._access_reescalations: dict[str, tuple[ErrorEntry, str, OperationCategory | None, Enum | None, bool]] = {}
        self._suspension_handed_over: set[str] = set()
        self._background_tasks: set[asyncio.Task[None]] = set()

    @property
    def active_profile(self) -> ErrorProfile:
        """The currently active error profile consulted for new error UUIDs."""
        return self._active_profile

    def set_active_profile(self, profile: ErrorProfile) -> None:
        """Replace the active profile for all future (new UUID) error events.

        In-flight retries already pinned to a UUID are unaffected — they
        continue to use the profile captured at error-start.
        """
        _logger.debug("ErrorProfileResolver: switching active profile to %r", profile.name)
        self._active_profile = profile

    async def on_instrument_error(self, error: ErrorData) -> None:
        """Handle an ``InstrumentErrorEvent`` from the SignalR listener.

        Suspends the active command deadline before beginning resolution and
        restores it in a ``try/finally`` guard once resolution completes.

        The one exception is the legacy operator fallback: when resolution defers
        to VENUS's built-in operator dialog (``selected_action_id=-1``), the SDK is
        still waiting on a human to respond via the legacy callback, so the deadline
        is deliberately left suspended. It is resumed later when the corresponding
        ``DeviceErrorHandledResponse`` arrives (see ``on_device_error_handled``), or
        by the deadline control's own suspension fallback timer as a safety net.
        """
        main_code = ""
        if error.code:
            main_code = error.code.split("/")[0] if "/" in error.code else error.code

        if main_code == "00":
            _logger.debug(
                "on_instrument_error: NO_ERROR (MAIN='00') uuid=%s — skipping",
                error.uuid,
            )
            return

        if error.uuid in self._escalating:
            _logger.info(
                "on_instrument_error: uuid=%s published again while an operator is deciding; ignoring",
                error.uuid,
            )
            return

        # After an access action the deadline is still suspended from the event
        # that asked for it, and the operator is asked again without re-running
        # the profile (which would use up retries).
        reescalation = self._access_reescalations.pop(error.uuid, None)
        if reescalation is None:
            self._deadline_control.suspend()
        try:
            if reescalation is None:
                await self._resolve_error(error)
            else:
                entry, reason, operation_category, error_type, is_per_channel_escalation = reescalation
                if error.detailed_errors:
                    async with self._retry_lock:
                        self._pending_detailed_errors[error.uuid] = error
                await self._escalate(
                    error,
                    entry,
                    reason,
                    operation_category=operation_category,
                    error_type=error_type,
                    is_per_channel_escalation=is_per_channel_escalation,
                )
        except Exception:
            _logger.exception(
                "on_instrument_error: unhandled exception during resolution uuid=%s",
                error.uuid,
            )
            await self._submit_abort(error, "unhandled exception in resolver")
        finally:
            if error.uuid in self._pending_operator_handoffs:
                _logger.debug(
                    "on_instrument_error: uuid=%s deferred to legacy operator dialog; "
                    "leaving command deadline suspended until operator responds",
                    error.uuid,
                )
            elif error.uuid in self._suspension_handed_over:
                self._suspension_handed_over.discard(error.uuid)
                _logger.debug(
                    "on_instrument_error: uuid=%s access action submitted; leaving command "
                    "deadline suspended until the error is published again",
                    error.uuid,
                )
            else:
                self._deadline_control.resume()

    async def on_device_error_handled(self, handled: InstrumentErrorHandled) -> None:
        """Handle ``DeviceErrorHandledResponse`` — clean up the retry-tracking entry.

        When a ``DeviceErrorHandledResponse`` arrives for a known error UUID,
        the tracking entry is immediately removed.

        Also performs lazy pruning of stale entries (those older than
        ``retry_tracking_ttl_seconds`` that never received a response). This
        pruning happens opportunistically on each ``DeviceErrorHandledResponse``,
        rather than with a background timer. This means stale entries may
        persist in memory briefly if the instrument becomes stable after an
        error and no further errors occur.
        """
        async with self._retry_lock:
            if handled.uuid in self._detail_map:
                detail_uuids = self._detail_map.pop(handled.uuid)
                self._pending_detailed_errors.pop(handled.uuid, None)
                carried = 0
                removed = 0
                for u in detail_uuids:
                    ch_state = self._retry_tracking.pop(u, None)
                    if ch_state is None:
                        continue
                    if ch_state.last_action is not None and ch_state.channel_index >= 0:
                        carry_key = (ch_state.device_id, ch_state.channel_index)
                        self._channel_carry_over[carry_key] = ch_state
                        carried += 1
                    else:
                        removed += 1
                _logger.warning(
                    "Error resolved: %d channel(s) (uuid=%s)",
                    len(detail_uuids),
                    handled.uuid,
                )
                _logger.debug(
                    "on_device_error_handled: uuid=%s carried=%d channel state(s) removed=%d",
                    handled.uuid,
                    carried,
                    removed,
                )
            elif handled.uuid in self._retry_tracking:
                state = self._retry_tracking.pop(handled.uuid)
                _logger.warning(
                    "Error resolved (uuid=%s)",
                    handled.uuid,
                )
                _logger.debug(
                    "on_device_error_handled: uuid=%s recovery_action=%r retries=%d",
                    handled.uuid,
                    handled.recovery_action,
                    state.retry_count,
                )

            self._prune_stale_state_locked()

        # The error ended (timeout, abort) while its republish after an access
        # action was still awaited: release the suspension kept for it.
        if self._access_reescalations.pop(handled.uuid, None) is not None:
            self._deadline_control.resume()

        # An error deferred to the legacy VENUS operator dialog: VENUS sends this
        # "handled" event as soon as it accepts the handoff (recoveryAction
        # "unknown"), while its dialog is still waiting for the operator -- so the
        # deadline is NOT resumed here. It stays suspended under the operator hold
        # until the in-flight command finishes (see _submit_legacy_operator_fallback).
        if handled.uuid in self._pending_operator_handoffs:
            self._pending_operator_handoffs.discard(handled.uuid)
            _logger.debug(
                "on_device_error_handled: uuid=%s legacy operator handoff accepted by VENUS; "
                "command deadline stays suspended until the command finishes",
                handled.uuid,
            )

    async def on_instrument_error_notification(self, notification: str) -> None:
        """Handle notification-driven retries for pending detailed errors.

        This path only proceeds when all tracked channel states for the top UUID
        are currently on ``REPEAT`` and the server confirms the error is still
        unhandled. If the unhandled check is negative or inconclusive, no
        recovery is submitted.

        When it does proceed, the resolver re-runs detailed resolution so normal
        action progression rules apply (including advancing past exhausted
        ``REPEAT`` budget).
        """
        top_uuid = notification.strip()
        if not top_uuid:
            return

        await asyncio.sleep(0.5)

        async with self._retry_lock:
            detail_uuids = self._detail_map.get(top_uuid)
            if not detail_uuids:
                return

            states: list[_RetryState] = []
            for detail_uuid in detail_uuids:
                state = self._retry_tracking.get(detail_uuid)
                if state is None:
                    return
                states.append(state)

            if not all(state.last_action == RecoveryAction.REPEAT for state in states):
                return

        still_unhandled = await self._is_error_still_unhandled(top_uuid)
        if still_unhandled is not True:
            _logger.debug(
                "on_instrument_error_notification: uuid=%s unhandled check=%r; skipping re-resolve",
                top_uuid,
                still_unhandled,
            )
            return

        state_snapshots: dict[str, tuple[int, int, RecoveryAction | None]] = {}
        async with self._retry_lock:
            detail_uuids = self._detail_map.get(top_uuid)
            if not detail_uuids:
                return

            pending_error = self._pending_detailed_errors.get(top_uuid)
            if pending_error is None:
                return

            states = []
            for detail_uuid in detail_uuids:
                state = self._retry_tracking.get(detail_uuid)
                if state is None:
                    return
                states.append(state)
                state_snapshots[detail_uuid] = (
                    state.action_index,
                    state.retry_count,
                    state.last_action,
                )

            all_repeat = all(state.last_action == RecoveryAction.REPEAT for state in states)
            if not all_repeat:
                return

            exhausted = all(state.retry_count >= state.entry.max_retries for state in states)
            if exhausted:
                for state in states:
                    if state.action_index < len(state.entry.actions):
                        candidate = state.entry.actions[state.action_index]
                        if candidate == RecoveryAction.REPEAT:
                            state.action_index += 1
                            state.retry_count = 0
                _logger.info(
                    "on_instrument_error_notification: uuid=%s still pending after notification "
                    "with REPEAT budget exhausted; advancing and re-resolving",
                    top_uuid,
                )
            else:
                _logger.info(
                    "on_instrument_error_notification: uuid=%s still pending after notification "
                    "with REPEAT action; re-submitting repeat (retry progress continues)",
                    top_uuid,
                )

        operation_context = self._deadline_control.get_operation_context()
        try:
            await self._resolve_detailed_error(
                pending_error,
                operation_context,
                allow_reconcile_retry=False,
            )
        except Exception as exc:
            async with self._retry_lock:
                for detail_uuid, snapshot in state_snapshots.items():
                    state = self._retry_tracking.get(detail_uuid)
                    if state is None:
                        continue
                    action_index, retry_count, last_action = snapshot
                    state.action_index = action_index
                    state.retry_count = retry_count
                    state.last_action = last_action
            _logger.warning(
                "on_instrument_error_notification: uuid=%s re-resolve failed: %s",
                top_uuid,
                exc,
            )

    async def _resolve_error(self, error: ErrorData) -> None:
        """Run the full error resolution algorithm for a single error event.

        State Machine Overview
        ----------------------
        For each error UUID, the resolver maintains a _RetryState that tracks
        progression through the action chain in an ErrorEntry:

        1. On first error: create _RetryState with action_index=0, retry_count=0
        2. For each subsequent error:
           a. Call _select_next_valid_action() to find the next action to submit
           b. REPEAT actions may be submitted multiple times (up to max_retries)
           c. Other actions are submitted once, then advance to next action
           d. Actions can be skipped if not in ALLOWED_ACTIONS or not advertised
        3. When all actions exhausted: escalate (operator callback, legacy
           VENUS operator dialog via selected_action_id=-1, or ABORT)

        For errors with detailed_errors (multi-channel), each channel is
        classified and tracked independently via _resolve_detailed_error().
        """
        operation_context = self._deadline_control.get_operation_context()
        category, error_type = self._classifier.classify(error, operation_context)

        _logger.debug(
            "_resolve_error: uuid=%s classified as (%s, %s) context=%r",
            error.uuid,
            category,
            error_type,
            operation_context,
        )

        _logger.error(
            "Instrument error: %s during %s (device=%d code=%s uuid=%s)",
            error_type.name if error_type is not None and hasattr(error_type, "name") else str(error_type),
            category.value if category is not None else "unknown",
            error.device_id,
            error.code,
            error.uuid,
        )

        if error.timeout != -1 and error.timeout == 0:
            _logger.warning(
                "_resolve_error: uuid=%s timeout already expired (timeout=%ds), skipping submission",
                error.uuid,
                error.timeout,
            )
            return

        if error.detailed_errors:
            await self._resolve_detailed_error(error, operation_context)
            return

        async with self._retry_lock:
            if error.uuid not in self._retry_tracking:
                entry = self._lookup_entry(self._active_profile, category, error_type)
                state = _RetryState(
                    profile=self._active_profile,
                    entry=entry,
                    operation_category=category,
                    error_type=error_type,
                    retry_count=0,
                    action_index=0,
                )
                self._retry_tracking[error.uuid] = state
                _logger.debug(
                    "_resolve_error: uuid=%s new retry state max_retries=%d actions=%s",
                    error.uuid,
                    entry.max_retries,
                    [a.value for a in entry.actions],
                )
            else:
                state = self._retry_tracking[error.uuid]
                entry = state.entry

        selected_action = self._select_next_valid_action(state, error, error_type, error.recovery_actions)

        if selected_action is None:
            _logger.info(
                "_resolve_error: uuid=%s no valid actions remain, escalating",
                error.uuid,
            )
            await self._escalate(
                error,
                entry,
                "no valid actions remain",
                operation_category=category,
                error_type=error_type,
                is_per_channel_escalation=False,
            )
            return

        _logger.warning(
            "_resolve_error: uuid=%s selected action=%r (retry_count %d/%d)",
            error.uuid,
            selected_action.value,
            state.retry_count,
            entry.max_retries,
        )

        recovery = self._build_recovery(error, selected_action, entry)
        await self._submit_recovery(error, selected_action, recovery)

    def _select_next_valid_action(
        self,
        state: _RetryState,
        error: ErrorData,
        error_type: Enum | None,
        advertised_actions: list[RecoveryActionDescriptor] | None,
        *,
        error_wide_actions: list[RecoveryActionDescriptor] | None = None,
    ) -> RecoveryAction | None:
        """Select the next valid action to submit for this error.

        Iterates through the action chain starting at state.action_index,
        skipping actions that are:
        - Not in ALLOWED_ACTIONS for this error type (CANCEL is exempt — always valid)
        - Not advertised by the server (for a channel of a per-channel error, CANCEL also
          counts as advertised when the whole error offers it in *error_wide_actions* --
          VENUS never offers it per channel)

        For REPEAT actions, increments retry_count until reaching max_retries,
        then advances to the next action. For other actions, advances
        immediately after selection.

        Returns the selected action, or None if no valid actions remain.
        """
        entry = state.entry

        while state.action_index < len(entry.actions):
            candidate = entry.actions[state.action_index]

            # CANCEL is always implicitly valid; skip ALLOWED_ACTIONS check for it.
            if candidate != RecoveryAction.CANCEL:
                allowed = ALLOWED_ACTIONS.get(error_type)
                if allowed is not None and candidate not in allowed:
                    _logger.warning(
                        "_select_next_valid_action: uuid=%s action=%r not in ALLOWED_ACTIONS for %s, skipping",
                        error.uuid,
                        candidate.value,
                        error_type,
                    )
                    state.action_index += 1
                    state.retry_count = 0
                    continue

            # Check if action is advertised by the server.
            server_id = self._classifier.action_to_server_id(candidate, advertised_actions)
            if server_id is None and candidate == RecoveryAction.CANCEL and error_wide_actions:
                server_id = self._classifier.action_to_server_id(candidate, error_wide_actions)
            if server_id is None:
                _logger.warning(
                    "_select_next_valid_action: uuid=%s action=%r not advertised by server, skipping",
                    error.uuid,
                    candidate.value,
                )
                state.action_index += 1
                state.retry_count = 0
                continue

            # Handle REPEAT action: check if retry budget is exhausted
            if candidate == RecoveryAction.REPEAT and state.retry_count >= entry.max_retries:
                _logger.debug(
                    "_select_next_valid_action: uuid=%s REPEAT budget exhausted (%d/%d), advancing to next action",
                    error.uuid,
                    state.retry_count,
                    entry.max_retries,
                )
                state.action_index += 1
                state.retry_count = 0
                continue

            # Action is valid; update state for next iteration
            if candidate == RecoveryAction.REPEAT:
                state.retry_count += 1
            else:
                state.action_index += 1
                state.retry_count = 0

            return candidate

        return None

    @staticmethod
    def _extract_main_code(code: str | None) -> str | None:
        """Return the MAIN portion of a raw error code string.

        Strips any device prefix (e.g. ``"P1:"``) then returns the segment
        before the first ``"/"``.  For example ``"P1:102/70"`` → ``"102"``.
        Returns ``None`` for missing/empty values.
        """
        if not code:
            return None
        stripped = code.split(":", 1)[1] if ":" in code else code
        return stripped.split("/", 1)[0]

    def _classify_channel(
        self,
        detail_code: str | None,
        top_main_code: str | None,
        operation_context: str | None,
    ) -> tuple[OperationCategory | None, Enum | None]:
        """Classify a per-channel sub-code using the top-level MAIN code for context.

        Channel ``detail.code`` values are sub-codes (e.g. ``"70"`` extracted
        from ``P1:102/70``).  The MAIN code (``"102"``) carries the operation
        context required for correct classification.  This method reconstructs
        the full code as ``"{top_main_code}/{detail_code}"`` before delegating
        to ``classify_code``.

        Falls back to classifying the bare ``detail_code`` when either part is
        missing.
        """
        full_code: str | None = f"{top_main_code}/{detail_code}" if top_main_code and detail_code else detail_code
        return self._classifier.classify_code(full_code, operation_context)

    async def _resolve_detailed_error(
        self,
        error: ErrorData,
        operation_context: str | None,
        *,
        allow_reconcile_retry: bool = True,
    ) -> None:
        """Resolve a multi-channel error event with independent per-channel handling.

        Each channel in ``error.detailed_errors`` is classified and tracked
        independently. Actions are selected per channel using that channel's
        own ``recovery_actions`` list (fixes the single-channel advertisement
        check that previously used only ``detailed_errors[0]``).

        Channel ``detail.code`` values are sub-codes; they are classified by
        combining the top-level MAIN code with the channel sub-code so that the
        correct operation context is preserved (e.g. ``"102/70"``).

        If any channel resolves to ABORT (either from the profile or because its
        action chain is exhausted), a top-level ABORT is submitted for the whole
        error — ABORT ends the run unconditionally regardless of the other channels.
        If the exhausted channel's entry has ``allow_operator=True``, the
        operator escalation callback is invoked (or, if no callback is
        registered, the SDK defers to the legacy VENUS operator dialog via
        ``selected_action_id=-1``) before falling back to ABORT.

        When all channels have valid non-ABORT actions, a single
        ``POST /recovery`` is submitted with independent per-channel choices.
        """
        top_main_code = self._extract_main_code(error.code)
        detailed_errors: list[DetailedError] = error.detailed_errors or []

        async with self._retry_lock:
            self._pending_detailed_errors[error.uuid] = error
            if error.uuid not in self._detail_map:
                detail_uuids: list[str] = []
                for detail in detailed_errors:
                    cat, err_type = self._classify_channel(detail.code, top_main_code, operation_context)
                    entry = self._lookup_entry(self._active_profile, cat, err_type)
                    carry_key = (error.device_id, detail.index)
                    carry = self._channel_carry_over.pop(carry_key, None)
                    if carry is not None and carry.operation_category == cat and carry.error_type == err_type:
                        state = carry
                        _logger.debug(
                            "_resolve_detailed_error: uuid=%s channel=%s reusing carry-over state"
                            " retry_count=%d action_index=%d",
                            error.uuid,
                            detail.uuid,
                            state.retry_count,
                            state.action_index,
                        )
                    else:
                        state = _RetryState(
                            profile=self._active_profile,
                            entry=entry,
                            operation_category=cat,
                            error_type=err_type,
                            retry_count=0,
                            action_index=0,
                            device_id=error.device_id,
                            channel_index=detail.index,
                        )
                    self._retry_tracking[detail.uuid] = state
                    detail_uuids.append(detail.uuid)
                    _logger.debug(
                        "_resolve_detailed_error: uuid=%s channel=%s classified as (%s, %s)",
                        error.uuid,
                        detail.uuid,
                        cat,
                        err_type,
                    )
                self._detail_map[error.uuid] = detail_uuids

        # Select action for each channel independently
        channel_results: list[tuple[DetailedError, RecoveryAction | None, ErrorEntry]] = []
        channel_state_snapshots: dict[str, tuple[int, int, RecoveryAction | None]] = {}
        for detail in detailed_errors:
            ch_state: _RetryState | None = self._retry_tracking.get(detail.uuid)
            if ch_state is None:
                channel_results.append((detail, None, self._active_profile.default))
                continue
            channel_state_snapshots[detail.uuid] = (
                ch_state.action_index,
                ch_state.retry_count,
                ch_state.last_action,
            )
            action = self._select_next_valid_action(
                ch_state,
                error,
                ch_state.error_type,
                detail.recovery_actions,
                error_wide_actions=error.recovery_actions,
            )
            ch_state.last_action = action
            channel_results.append((detail, action, ch_state.entry))
            _logger.info(
                "_resolve_detailed_error: uuid=%s channel=%s action=%r",
                error.uuid,
                detail.uuid,
                action.value if action else None,
            )

        def _snapshot_to_log(detail_uuid: str) -> dict[str, int | str | None] | None:
            snapshot = channel_state_snapshots.get(detail_uuid)
            if snapshot is None:
                return None
            action_index, retry_count, last_action = snapshot
            return {
                "action_index": action_index,
                "retry_count": retry_count,
                "last_action": last_action.value if last_action else None,
            }

        # CANCEL is error-wide (VENUS offers it for the whole error, never per channel): if
        # any channel's profile picks it, the whole error is cancelled -- the step fails and
        # the method keeps running -- the same way ABORT below is error-wide.
        if any(action == RecoveryAction.CANCEL for _, action, _ in channel_results):
            _logger.warning(
                "Cancelling uuid=%s for all %d channel(s): a channel's profile selected CANCEL",
                error.uuid,
                len(channel_results),
            )
            await self._submit_error_wide(error, RecoveryAction.CANCEL)
            return

        any_abort = any(action is None or action == RecoveryAction.ABORT for _, action, _ in channel_results)
        if any_abort:
            _logger.info(
                "_resolve_detailed_error: uuid=%s user escalation path engaged; profile=%s channel_outcomes=%s",
                error.uuid,
                self._active_profile.name,
                [
                    {
                        "channel_uuid": detail.uuid,
                        "action": action.value if action else None,
                        "allow_operator": entry.allow_operator,
                        "actions": [a.value for a in entry.actions],
                        "max_retries": entry.max_retries,
                        "state_before_selection": _snapshot_to_log(detail.uuid),
                    }
                    for detail, action, entry in channel_results
                ],
            )
            _logger.warning(
                "Recovery actions exhausted for uuid=%s; evaluating operator escalation",
                error.uuid,
            )
            for detail, action, entry in channel_results:
                if action is None and entry.allow_operator:
                    # Get classification info for this channel from retry tracking
                    ch_state = self._retry_tracking.get(detail.uuid)
                    operation_cat = ch_state.operation_category if ch_state else None
                    error_typ = ch_state.error_type if ch_state else None
                    await self._escalate(
                        error,
                        entry,
                        "channel action chain exhausted",
                        operation_category=operation_cat,
                        error_type=error_typ,
                        is_per_channel_escalation=True,
                    )
                    return
            _logger.warning(
                "Operator escalation is not enabled in the active error profile for uuid=%s;"
                " falling back to default abort recovery",
                error.uuid,
            )
            await self._submit_abort(error, "channel action resolved to abort")
            return

        # All channels have valid non-ABORT actions — build per-channel payload
        now_str = datetime.now(UTC).isoformat()
        detailed_recoveries: list[DetailedErrorRecovery] = []
        for detail, ch_action, _entry in channel_results:
            assert ch_action is not None  # guaranteed by any_abort check above
            server_id = self._classifier.action_to_server_id(ch_action, detail.recovery_actions)
            detailed_recoveries.append(
                DetailedErrorRecovery(
                    date=now_str,
                    uuid=detail.uuid,
                    selected_action_id=server_id if server_id is not None else -1,
                )
            )

        execute_id = self._find_execute_action_id(error)
        recovery = ErrorRecovery(
            date=now_str,
            uuid=error.uuid,
            selected_action_id=execute_id,
            selected_action_is_recovery=True,
            detailed_error_recoveries=detailed_recoveries,
            error_handling_key=self._error_handler_key,
        )
        action_counts: dict[str, int] = {}
        for _detail, ch_action, _entry in channel_results:
            if ch_action is None:
                continue
            action_counts[ch_action.value] = action_counts.get(ch_action.value, 0) + 1
        action_summary = ", ".join(f"{action} x{count}" for action, count in sorted(action_counts.items()))
        _logger.warning(
            "Recovering %d channel(s) with action: %s (uuid=%s)",
            len(detailed_recoveries),
            action_summary,
            error.uuid,
        )
        await self._venus.submit_error_recovery(error.uuid, recovery)
        if allow_reconcile_retry:
            await self._reconcile_pending_detailed_error(error, recovery)

    async def _is_error_still_unhandled(self, error_uuid: str) -> bool | None:
        """Return whether ``error_uuid`` is still in server unhandled errors.

        Returns ``True`` when present, ``False`` when absent, and ``None`` when
        the unhandled query fails.
        """
        try:
            unhandled = await self._venus.get_unhandled_errors()
        except Exception as exc:
            _logger.warning(
                "_is_error_still_unhandled: uuid=%s check failed: %s",
                error_uuid,
                exc,
            )
            return None
        return any(item.uuid == error_uuid for item in unhandled)

    async def _reconcile_pending_detailed_error(
        self,
        error: ErrorData,
        recovery: ErrorRecovery,
    ) -> None:
        """Post-submit reconcile for detailed errors with guarded fallback retry.

        After submitting detailed recovery, perform delayed checks against the
        server unhandled list. If the error is cleared, return. If checks are
        inconclusive, return without retrying. If the error remains pending
        across the full reconcile window, perform one guarded re-submit of the
        same payload to avoid stalling when no notification arrives.
        """
        for attempt in range(1, _POST_SUBMIT_RECHECK_MAX_ATTEMPTS + 1):
            await asyncio.sleep(_POST_SUBMIT_RECHECK_DELAY_SECONDS)
            still_pending = await self._is_error_still_unhandled(error.uuid)
            if still_pending is None:
                _logger.warning(
                    "_resolve_detailed_error: uuid=%s reconciliation check %d/%d inconclusive",
                    error.uuid,
                    attempt,
                    _POST_SUBMIT_RECHECK_MAX_ATTEMPTS,
                )
                return

            if not still_pending:
                _logger.info(
                    "_resolve_detailed_error: uuid=%s reconciliation check %d/%d clear",
                    error.uuid,
                    attempt,
                    _POST_SUBMIT_RECHECK_MAX_ATTEMPTS,
                )
                return

            _logger.debug(
                "_resolve_detailed_error: uuid=%s still present in unhandled after submit (check %d/%d)",
                error.uuid,
                attempt,
                _POST_SUBMIT_RECHECK_MAX_ATTEMPTS,
            )
            if attempt < _POST_SUBMIT_RECHECK_MAX_ATTEMPTS:
                _logger.info(
                    "_resolve_detailed_error: uuid=%s waiting for next reconciliation check",
                    error.uuid,
                )
                continue

            _logger.debug(
                "_resolve_detailed_error: uuid=%s still unhandled after %d checks; issuing guarded retry submit",
                error.uuid,
                _POST_SUBMIT_RECHECK_MAX_ATTEMPTS,
            )
            await self._venus.submit_error_recovery(error.uuid, recovery)
            return

    def _lookup_entry(
        self,
        profile: ErrorProfile,
        category: OperationCategory | None,
        error_type: Enum | None,
    ) -> ErrorEntry:
        """Four-tier lookup: exact match → error default → operation default → global default."""
        if category is not None:
            op_name = category.value
            op_dict = profile.get_operation_rules(op_name)
            if error_type is not None and error_type in op_dict:
                _logger.debug(
                    "_lookup_entry: exact match (%s, %s)",
                    op_name,
                    error_type,
                )
                return op_dict[error_type]

            if error_type is not None:
                error_default = profile.error_defaults.get(error_type.name)
                if error_default is not None:
                    _logger.debug("_lookup_entry: error default for %s", error_type.name)
                    return error_default

            op_default = profile.get_operation_default(op_name)
            if op_default is not None:
                _logger.debug("_lookup_entry: operation default for %s", op_name)
                return op_default

            _logger.warning(
                "_lookup_entry: profile has no rules for category=%s, using global default",
                category,
            )

        if error_type is not None:
            error_default = profile.error_defaults.get(error_type.name)
            if error_default is not None:
                _logger.debug("_lookup_entry: error default for %s", error_type.name)
                return error_default

        _logger.debug("_lookup_entry: using global default")
        return profile.default

    def _build_recovery(
        self,
        error: ErrorData,
        action: RecoveryAction,
        entry: ErrorEntry,
    ) -> ErrorRecovery:
        """Build the ``ErrorRecovery`` payload for non-detailed error submission."""
        now_str = datetime.now(UTC).isoformat()
        inputs = list(entry.inputs.get(action, ())) or None

        server_id = self._classifier.action_to_server_id(action, error.recovery_actions)
        return ErrorRecovery(
            date=now_str,
            uuid=error.uuid,
            selected_action_id=server_id if server_id is not None else -1,
            selected_action_is_recovery=(action.kind == ActionKind.RECOVERY),
            detailed_error_recoveries=None,
            inputs=inputs,
            error_handling_key=self._error_handler_key,
        )

    def _find_execute_action_id(self, error: ErrorData) -> int:
        """Find the server-side 'execute' action ID required for detailed errors."""
        for desc in error.recovery_actions:
            if desc.name.lower() == _EXECUTE_ACTION_NAME:
                return desc.id
        _logger.warning(
            "_find_execute_action_id: 'execute' action not found in server list for uuid=%s, using -1 as fallback",
            error.uuid,
        )
        return -1

    def _prune_stale_state_locked(self) -> None:
        now = time.time()
        stale_uuids = [
            uid
            for uid, state in self._retry_tracking.items()
            if now - state.created_at > self._retry_tracking_ttl_seconds
        ]
        for uid in stale_uuids:
            stale = self._retry_tracking.pop(uid)
            _logger.warning(
                "on_device_error_handled: pruning stale entry uuid=%s (age=%.0fs, ttl=%ds, retries=%d)",
                uid,
                now - stale.created_at,
                self._retry_tracking_ttl_seconds,
                stale.retry_count,
            )
        stale_tops = [
            top for top, details in self._detail_map.items() if not any(d in self._retry_tracking for d in details)
        ]
        for top in stale_tops:
            self._detail_map.pop(top, None)
            self._pending_detailed_errors.pop(top, None)
        stale_carry = [
            k for k, s in self._channel_carry_over.items() if now - s.created_at > self._retry_tracking_ttl_seconds
        ]
        for k in stale_carry:
            self._channel_carry_over.pop(k)

    async def _escalate(
        self,
        error: ErrorData,
        entry: ErrorEntry,
        reason: str,
        *,
        operation_category: OperationCategory | None = None,
        error_type: Enum | None = None,
        is_per_channel_escalation: bool = False,
    ) -> None:
        """Escalate after retries exhausted.

        Resolution order:
        - ``allow_operator=False``: submit ABORT.
        - ``allow_operator=True`` with a callback: invoke the callback and
          submit its decision (falling back to ABORT on failure/None).
        - ``allow_operator=True`` without a callback: submit
          ``selected_action_id=-1`` so VENUS falls back to its legacy
          operator dialog on the PC running it.
        """
        _logger.info(
            "_escalate: uuid=%s reason=%s allow_operator=%s callback_registered=%s "
            "actions=%s max_retries=%d profile=%s",
            error.uuid,
            reason,
            entry.allow_operator,
            self._on_operator_error_escalation is not None,
            [a.value for a in entry.actions],
            entry.max_retries,
            self._active_profile.name,
        )
        _logger.warning(
            "Operator escalation triggered for uuid=%s",
            error.uuid,
        )
        if entry.allow_operator and self._on_operator_error_escalation is not None:
            _logger.info(
                "_escalate: uuid=%s invoking operator escalation callback (%s)",
                error.uuid,
                reason,
            )
            # Build escalation context with classification and action information
            _logger.debug(
                "_escalate: uuid=%s error.recovery_actions type=%s len=%s values=%s",
                error.uuid,
                type(error.recovery_actions),
                len(error.recovery_actions) if error.recovery_actions else 0,
                [a.name for a in (error.recovery_actions or [])] if error.recovery_actions else [],
            )

            top_level_actions = error.recovery_actions or []
            _logger.debug(
                "_escalate: uuid=%s top_level_actions count=%d names=%s (raw error.recovery_actions=%s)",
                error.uuid,
                len(top_level_actions),
                [a.name for a in top_level_actions],
                "populated" if error.recovery_actions else "empty/None",
            )
            per_channel_actions = []
            if error.detailed_errors:
                # Extract common per-channel actions across all channels
                all_per_channel_actions = [detail.recovery_actions or [] for detail in error.detailed_errors]
                if all_per_channel_actions and all_per_channel_actions[0]:
                    common_names = {a.name.lower() for a in all_per_channel_actions[0]}
                    for channel_actions in all_per_channel_actions[1:]:
                        common_names &= {a.name.lower() for a in channel_actions}
                    per_channel_actions = [a for a in all_per_channel_actions[0] if a.name.lower() in common_names]
                    _logger.debug(
                        "_escalate: uuid=%s per_channel_actions=%s",
                        error.uuid,
                        [a.name for a in per_channel_actions],
                    )

            context = OperatorEscalationContext(
                error=error,
                entry=entry,
                operation_category=operation_category,
                error_type=error_type,
                top_level_actions=top_level_actions,
                per_channel_actions=per_channel_actions,
                is_per_channel_escalation=is_per_channel_escalation,
            )

            _logger.info(
                "_escalate: uuid=%s context created: top_level=%d per_channel=%d is_per_channel=%s",
                error.uuid,
                len(context.top_level_actions),
                len(context.per_channel_actions),
                context.is_per_channel_escalation,
            )

            # The command deadline is already suspended for this error; also drop the
            # suspension fallback so an operator can take as long as they need. The
            # usual resume after the answer is submitted restores the remaining time.
            pause_fallback = getattr(self._deadline_control, "pause_suspension_fallback", None)
            if pause_fallback is not None:
                pause_fallback()
            self._escalating.add(error.uuid)
            try:
                if inspect.iscoroutinefunction(self._on_operator_error_escalation):
                    selected_action = await self._on_operator_error_escalation(context)
                else:
                    loop = asyncio.get_running_loop()
                    selected_action = await loop.run_in_executor(None, self._on_operator_error_escalation, context)
            except Exception:
                _logger.exception(
                    "_escalate: operator callback raised for uuid=%s, falling back to ABORT",
                    error.uuid,
                )
                await self._submit_abort(error, reason)
                return
            finally:
                self._escalating.discard(error.uuid)

            if selected_action is None:
                await self._submit_abort(error, reason)
                return

            # Handle ErrorRecovery directly from callback (advanced path)
            if isinstance(selected_action, ErrorRecovery):
                _logger.info(
                    "_escalate: uuid=%s callback returned ErrorRecovery payload; submitting directly",
                    error.uuid,
                )
                normalized_selected_action = selected_action
                if normalized_selected_action.uuid != error.uuid:
                    _logger.warning(
                        "_escalate: callback ErrorRecovery uuid=%s does not match current error uuid=%s; overriding",
                        normalized_selected_action.uuid,
                        error.uuid,
                    )
                    normalized_selected_action = normalized_selected_action.model_copy(update={"uuid": error.uuid})
                if not normalized_selected_action.error_handling_key:
                    normalized_selected_action = normalized_selected_action.model_copy(
                        update={"error_handling_key": self._error_handler_key}
                    )
                if is_access_action_recovery(normalized_selected_action):
                    await self._submit_access_action(
                        error,
                        normalized_selected_action,
                        (entry, reason, operation_category, error_type, is_per_channel_escalation),
                    )
                    return
                if not normalized_selected_action.selected_action_is_recovery:
                    _logger.warning(
                        "_escalate: callback ErrorRecovery selected_action_is_recovery=False; "
                        "forcing True for recovery submission"
                    )
                    normalized_selected_action = normalized_selected_action.model_copy(
                        update={"selected_action_is_recovery": True}
                    )
                try:
                    await self._venus.submit_error_recovery(error.uuid, normalized_selected_action)
                    return
                except Exception as exc:
                    _logger.error(
                        "_escalate: uuid=%s failed to submit callback-provided "
                        "ErrorRecovery: %s; falling back to ABORT",
                        error.uuid,
                        exc,
                    )
                    await self._submit_abort(error, reason)
                    return

            # Handle RecoveryAction enum (simple path)
            if not isinstance(selected_action, RecoveryAction):
                _logger.warning(
                    "_escalate: uuid=%s callback returned unsupported type %r; falling back to ABORT",
                    error.uuid,
                    type(selected_action),
                )
                await self._submit_abort(error, reason)
                return

            if selected_action == RecoveryAction.ABORT:
                await self._submit_abort(error, reason)
                return

            # Check if selected action is available as per-channel (preferred) or top-level
            is_per_channel_action = any(a.name.lower() == selected_action.value.lower() for a in per_channel_actions)
            is_top_level_action = any(
                a.name.lower() == selected_action.value.lower() for a in (error.recovery_actions or [])
            )

            if error.detailed_errors:
                now_str = datetime.now(UTC).isoformat()

                # If available as per-channel, apply to each channel
                if is_per_channel_action:
                    detailed_recoveries: list[DetailedErrorRecovery] = []
                    for detail in error.detailed_errors:
                        server_id = self._classifier.action_to_server_id(selected_action, detail.recovery_actions)
                        if server_id is None:
                            _logger.warning(
                                "_escalate: uuid=%s per-channel action=%r not advertised "
                                "for channel=%s; falling back to ABORT",
                                error.uuid,
                                selected_action.value,
                                detail.uuid,
                            )
                            await self._submit_abort(error, reason)
                            return
                        detailed_recoveries.append(
                            DetailedErrorRecovery(
                                date=now_str,
                                uuid=detail.uuid,
                                selected_action_id=server_id,
                            )
                        )

                    execute_id = self._find_execute_action_id(error)
                    recovery = ErrorRecovery(
                        date=now_str,
                        uuid=error.uuid,
                        selected_action_id=execute_id,
                        selected_action_is_recovery=(selected_action.kind == ActionKind.RECOVERY),
                        detailed_error_recoveries=detailed_recoveries,
                        error_handling_key=self._error_handler_key,
                    )
                    async with self._retry_lock:
                        detail_uuids = self._detail_map.get(error.uuid, [])
                        for detail_uuid in detail_uuids:
                            state = self._retry_tracking.get(detail_uuid)
                            if state is None:
                                continue
                            state.last_action = selected_action
                    await self._venus.submit_error_recovery(error.uuid, recovery)
                    return

                # Otherwise, if it's a top-level action, submit as top-level
                if is_top_level_action:
                    server_id = self._classifier.action_to_server_id(selected_action, error.recovery_actions)
                    if server_id is not None:
                        # An error-wide choice (e.g. Cancel) on a per-channel error:
                        # every channel carries the same id, or VENUS rejects it.
                        recovery = ErrorRecovery(
                            date=now_str,
                            uuid=error.uuid,
                            selected_action_id=server_id,
                            selected_action_is_recovery=(selected_action.kind == ActionKind.RECOVERY),
                            detailed_error_recoveries=self._uniform_detail_recoveries(error, server_id, now_str),
                            error_handling_key=self._error_handler_key,
                        )
                        async with self._retry_lock:
                            detail_uuids = self._detail_map.get(error.uuid, [])
                            for detail_uuid in detail_uuids:
                                state = self._retry_tracking.get(detail_uuid)
                                if state is None:
                                    continue
                                state.last_action = selected_action
                        await self._venus.submit_error_recovery(error.uuid, recovery)
                        return
                    else:
                        _logger.warning(
                            "_escalate: uuid=%s top-level action=%r not found in server list; falling back to ABORT",
                            error.uuid,
                            selected_action.value,
                        )
                        await self._submit_abort(error, reason)
                        return

                # Action not found in either list - should not happen
                _logger.warning(
                    "_escalate: uuid=%s action=%r not found in top-level or per-channel actions; falling back to ABORT",
                    error.uuid,
                    selected_action.value,
                )
                await self._submit_abort(error, reason)
                return

            recovery = self._build_recovery(error, selected_action, entry)
            await self._submit_recovery(error, selected_action, recovery)
            return

        if not entry.allow_operator:
            _logger.warning(
                "Operator escalation is not enabled in the active error profile for uuid=%s;"
                " falling back to default abort recovery",
                error.uuid,
            )
            await self._submit_abort(error, reason)
            return

        _logger.warning(
            "No operator escalation callback registered for uuid=%s; deferring to legacy "
            "VENUS operator dialog by submitting selected_action_id=-1",
            error.uuid,
        )
        await self._submit_legacy_operator_fallback(error, reason)

    async def _submit_access_action(
        self,
        error: ErrorData,
        action: ErrorRecovery,
        reescalation: tuple[ErrorEntry, str, OperationCategory | None, Enum | None, bool],
    ) -> None:
        """Submit an access action (door / loading tray) an operator asked for.

        The action does not answer the error: VENUS carries it out and publishes
        the error again with the opposite action listed, and ``on_instrument_error``
        then asks the operator again. If VENUS refuses the action, or does not
        publish the error again in time, the operator is asked again anyway so the
        error is never left without anyone deciding.
        """
        entry, reason, operation_category, error_type, is_per_channel_escalation = reescalation
        self._access_reescalations[error.uuid] = reescalation
        self._suspension_handed_over.add(error.uuid)
        try:
            await self._venus.submit_error_action(error.uuid, action)
        except Exception as exc:
            self._access_reescalations.pop(error.uuid, None)
            self._suspension_handed_over.discard(error.uuid)
            _logger.warning(
                "_submit_access_action: uuid=%s action id=%d refused: %s; asking the operator again",
                error.uuid,
                action.selected_action_id,
                exc,
            )
            current = await self._current_unhandled_error(error)
            if current is not None:
                await self._escalate(
                    current,
                    entry,
                    reason,
                    operation_category=operation_category,
                    error_type=error_type,
                    is_per_channel_escalation=is_per_channel_escalation,
                )
            return
        _logger.warning(
            "_submit_access_action: access action id=%d submitted for uuid=%s",
            action.selected_action_id,
            error.uuid,
        )
        task = asyncio.create_task(self._reescalate_if_not_republished(error))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _current_unhandled_error(self, error: ErrorData) -> ErrorData | None:
        """The server's current copy of *error*, *error* itself if the query fails, ``None`` if it is gone."""
        try:
            unhandled = await self._venus.get_unhandled_errors()
        except Exception as exc:
            _logger.warning("_current_unhandled_error: uuid=%s check failed: %s", error.uuid, exc)
            return error
        return next((item for item in unhandled if item.uuid == error.uuid), None)

    async def _reescalate_if_not_republished(self, error: ErrorData) -> None:
        """Ask the operator again when VENUS did not publish *error* again after an access action."""
        await asyncio.sleep(_ACCESS_ACTION_REPUBLISH_TIMEOUT_SECONDS)
        if error.uuid not in self._access_reescalations:
            return
        current = await self._current_unhandled_error(error)
        if error.uuid not in self._access_reescalations:
            return
        if current is None:
            self._access_reescalations.pop(error.uuid, None)
            self._deadline_control.resume()
            return
        _logger.info(
            "_reescalate_if_not_republished: uuid=%s not published again after an access action; "
            "asking the operator again",
            error.uuid,
        )
        await self.on_instrument_error(current)

    async def _submit_recovery(
        self,
        error: ErrorData,
        action: RecoveryAction,
        recovery: ErrorRecovery,
    ) -> None:
        """Submit the recovery payload via the appropriate REST endpoint."""
        try:
            if action.kind == ActionKind.ACTION:
                await self._venus.submit_error_action(error.uuid, recovery)
                _logger.warning(
                    "_submit_recovery: ACTION %r submitted for uuid=%s",
                    action.value,
                    error.uuid,
                )
            else:
                await self._venus.submit_error_recovery(error.uuid, recovery)
                _logger.warning(
                    "_submit_recovery: RECOVERY %r submitted for uuid=%s",
                    action.value,
                    error.uuid,
                )
        except Exception as exc:
            _logger.warning(
                "_submit_recovery: submission failed uuid=%s action=%r: %s",
                error.uuid,
                action.value,
                exc,
            )

    @staticmethod
    def _uniform_detail_recoveries(
        error: ErrorData, action_id: int, now_str: str
    ) -> list[DetailedErrorRecovery] | None:
        """One DetailedErrorRecovery per channel, all carrying *action_id*.

        For an error-wide action (Cancel / Abort) on a per-channel error: VENUS
        rejects such an error's recovery without detailed_error_recoveries
        ("The detailed error recoveries are missing."), and accepts the
        top-level action's id repeated on every channel. None when the error
        has no channel details.
        """
        if not error.detailed_errors:
            return None
        return [
            DetailedErrorRecovery(date=now_str, uuid=detail.uuid, selected_action_id=action_id)
            for detail in error.detailed_errors
        ]

    async def _submit_error_wide(self, error: ErrorData, action: RecoveryAction) -> None:
        """Submit an error-wide action (CANCEL) for a per-channel error: the top-level
        action id, repeated on every channel as VENUS requires (see
        ``_uniform_detail_recoveries``)."""
        server_id = self._classifier.action_to_server_id(action, error.recovery_actions)
        if server_id is None:
            _logger.error(
                "_submit_error_wide: %r not offered for uuid=%s; falling back to abort",
                action.value,
                error.uuid,
            )
            await self._submit_abort(error, f"{action.value} not offered")
            return
        now_str = datetime.now(UTC).isoformat()
        recovery = ErrorRecovery(
            date=now_str,
            uuid=error.uuid,
            selected_action_id=server_id,
            selected_action_is_recovery=True,
            detailed_error_recoveries=self._uniform_detail_recoveries(error, server_id, now_str),
            error_handling_key=self._error_handler_key,
        )
        try:
            await self._venus.submit_error_recovery(error.uuid, recovery)
        except Exception as exc:
            _logger.error(
                "_submit_error_wide: failed to submit %r for uuid=%s: %s",
                action.value,
                error.uuid,
                exc,
            )

    async def _submit_abort(self, error: ErrorData, reason: str) -> None:
        """Submit ABORT as the final fallback recovery.

        Searches for the ABORT action ID in (1) the top-level ``error.recovery_actions``
        and, for multi-channel errors, (2) each channel's ``detail.recovery_actions``.
        For a multi-channel error the chosen id is also applied to every channel,
        which VENUS requires (see ``_uniform_detail_recoveries``).
        """
        # First, try to find ABORT at the top level
        top_level_abort_id = self._classifier.action_to_server_id(RecoveryAction.ABORT, error.recovery_actions)

        # Track if we found ABORT in per-channel actions
        per_channel_abort_id = None
        if top_level_abort_id is None and error.detailed_errors:
            # Only look for per-channel abort if not found at top level
            for detail in error.detailed_errors:
                per_channel_abort_id = self._classifier.action_to_server_id(
                    RecoveryAction.ABORT, detail.recovery_actions
                )
                if per_channel_abort_id is not None:
                    _logger.debug(
                        "_submit_abort: found ABORT (id=%d) in channel %s recovery_actions",
                        per_channel_abort_id,
                        detail.uuid,
                    )
                    break

        # Determine which abort ID to use and whether to include per-channel details
        server_id = top_level_abort_id or per_channel_abort_id
        if server_id is None:
            _logger.error(
                "_submit_abort: ABORT not found in any recovery_actions for uuid=%s, cannot submit",
                error.uuid,
            )
            return

        now_str = datetime.now(UTC).isoformat()

        # A per-channel error always needs detailed_error_recoveries -- VENUS
        # rejects one without them ("The detailed error recoveries are
        # missing."), even for an error-wide ABORT. Every channel carries the
        # same abort id (see _uniform_detail_recoveries).
        detailed_recoveries = self._uniform_detail_recoveries(error, server_id, now_str)

        recovery = ErrorRecovery(
            date=now_str,
            uuid=error.uuid,
            selected_action_id=server_id,
            selected_action_is_recovery=True,
            detailed_error_recoveries=detailed_recoveries,
            error_handling_key=self._error_handler_key,
        )
        _logger.warning(
            "_submit_abort: uuid=%s reason=%r (top_level_id=%s per_channel_id=%s)",
            error.uuid,
            reason,
            top_level_abort_id,
            per_channel_abort_id,
        )
        try:
            await self._venus.submit_error_recovery(error.uuid, recovery)
        except Exception as exc:
            _logger.error(
                "_submit_abort: failed to submit ABORT for uuid=%s: %s",
                error.uuid,
                exc,
            )

    async def _submit_legacy_operator_fallback(self, error: ErrorData, reason: str) -> None:
        """Defer to the legacy VENUS operator dialog by submitting ``selected_action_id=-1``.

        Used when the active profile entry has ``allow_operator=True`` but no
        operator escalation callback is registered with the client. Instead of
        aborting, the SDK signals VENUS that the host application has declined
        to make a recovery decision; VENUS then surfaces its built-in operator
        dialog on the PC running it so a human can resolve the error directly.

        For a per-channel/detailed error (``error.detailed_errors`` set), VENUS
        rejects a bare top-level submission with ``detailed_error_recoveries=
        None`` (HTTP 400) -- every channel needs its own recovery entry, same
        as a normal per-channel submission (see ``_resolve_detailed_error``).
        The top-level ``selected_action_id`` stays ``-1`` (the "defer to the
        operator dialog" marker); each channel entry carries ``0`` (R&D's
        suggestion, 2026-09-25: with ``-1`` on the channels VENUS answered
        "handled" (``recoveryAction: unknown``) within 0.5 s and never showed
        its dialog), so no channel names a real recovery action.

        Because a human still needs to respond through the legacy dialog, the
        command deadline must remain suspended after this submission. On a
        successful submit the error UUID is recorded in
        ``_pending_operator_handoffs`` so ``on_instrument_error`` skips its usual
        ``resume()``, and the deadline control is put on an operator hold: the
        deadline stays suspended until the in-flight command finishes. VENUS's
        ``DeviceErrorHandledResponse`` for the error arrives as soon as it accepts
        the handoff -- not when the operator answers -- so it must not resume the
        deadline. If the submission itself fails there is no pending handoff, so
        the deadline is resumed normally by the caller.
        """
        now_str = datetime.now(UTC).isoformat()
        detailed_recoveries: list[DetailedErrorRecovery] | None = None
        if error.detailed_errors:
            detailed_recoveries = [
                DetailedErrorRecovery(
                    date=now_str, uuid=detail.uuid, selected_action_id=_LEGACY_DIALOG_CHANNEL_ACTION_ID
                )
                for detail in error.detailed_errors
            ]
        recovery = ErrorRecovery(
            date=now_str,
            uuid=error.uuid,
            selected_action_id=-1,
            selected_action_is_recovery=False,
            detailed_error_recoveries=detailed_recoveries,
            error_handling_key=self._error_handler_key,
        )
        _logger.warning(
            "_submit_legacy_operator_fallback: uuid=%s reason=%r submitting selected_action_id=-1",
            error.uuid,
            reason,
        )
        try:
            await self._venus.submit_error_recovery(error.uuid, recovery)
            self._pending_operator_handoffs.add(error.uuid)
            hold = getattr(self._deadline_control, "hold_for_operator", None)
            if hold is not None:
                hold()
            _logger.debug(
                "_submit_legacy_operator_fallback: uuid=%s handed off to legacy operator "
                "dialog; command deadline kept suspended pending operator response",
                error.uuid,
            )
        except Exception as exc:
            _logger.error(
                "_submit_legacy_operator_fallback: failed to submit legacy fallback for uuid=%s: %s",
                error.uuid,
                exc,
            )

    @property
    def stats(self) -> dict[str, object]:
        """Diagnostic counters for monitoring and integration tests."""
        return {
            "classifier": self._classifier.stats,
            "active_retry_count": len(self._retry_tracking),
        }
