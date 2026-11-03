"""Sample/well status storage. This is generic storage + status-update
plumbing only -- there is no generic notion of "which SDK command touches
which sample" in the framework, so a workflow app populates the sample->well
mapping itself (typically from its Setup tab) and drives set_status() from its
own StepObserver (built from the workflow spec, since that mapping is
domain-specific per workflow) rather than this class inferring it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from hamilton_venus import OperatorEscalationContext

from hamilton_workflow_framework.execution_engine import SendFn
from hamilton_workflow_framework.session import EscalationObserver, WorkflowSession

from .models import SampleWellMapping

_now_iso = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731


class SampleTracker:
    """One instance per WorkflowSession/ExecutionEngine pairing."""

    def __init__(self) -> None:
        self.mappings: dict[str, SampleWellMapping] = {}

    def set_mapping(self, sample_id: str, plate_id: str, well: str) -> SampleWellMapping:
        mapping = SampleWellMapping(sample_id=sample_id, plate_id=plate_id, well=well)
        self.mappings[sample_id] = mapping
        return mapping

    async def set_status(
        self, sample_id: str, status: Literal["pending", "in_progress", "complete", "error"], send: SendFn
    ) -> None:
        mapping = self.mappings.get(sample_id)
        if mapping is None:
            return
        mapping.status = status
        await send({
            "type": "sample_status_update",
            "sample_id": sample_id,
            "plate_id": mapping.plate_id,
            "well": mapping.well,
            "status": status,
        })

    async def log_event(
        self, send: SendFn, event_type: Literal["scan", "status_change", "error"], detail: str, sample_id: str | None = None
    ) -> None:
        await send({
            "type": "sample_event",
            "event_type": event_type,
            "sample_id": sample_id,
            "detail": detail,
            "timestamp": _now_iso(),
        })


def make_escalation_event_observer(session: WorkflowSession) -> EscalationObserver:
    """Bridges a StarClient operator escalation into the Run Monitoring tab's
    event timeline (a `sample_event` WS message with event_type="error"),
    alongside (not instead of) the operator_prompt dialog session.py already
    pushes. Register via WorkflowSession(escalation_observers=[...]) -- runs
    synchronously on the SDK's escalation worker thread, so it only pushes onto
    session.log_queue (thread-safe) rather than awaiting anything.
    """

    def _observer(context: OperatorEscalationContext) -> None:
        error = context.error
        detail = f"Operator escalation ({error.code}): {error.title or error.message or 'Unknown instrument error.'}"
        session.push_message_threadsafe({
            "type": "sample_event",
            "event_type": "error",
            "sample_id": None,
            "detail": detail,
            "timestamp": _now_iso(),
        })

    return _observer
