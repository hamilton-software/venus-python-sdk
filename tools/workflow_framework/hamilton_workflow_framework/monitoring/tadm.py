"""TADM (Aspiration/Dispense Control) result extraction, as a StepObserver plugin.

Confirmed directly against hamilton_venus.models.command_types:
ChannelAspirationResponse/ChannelDispenseResponse.return_parameters.tadm is a
real ``ChannelTADM`` object (present whenever the step was called with
``adc=True``), containing ``tadm_curves: list[ChannelTADMCurve]`` -- each with
a real ``curve_flagged``/``error`` pass-fail signal and a ``curve_points``
list of {timeMs, pressure} samples. Whether real firmware populates non-empty
curve_points in practice is unverified here (nothing in this repo's tests/docs
exercises it) -- treat curve_points as present-but-unverified telemetry (an
inspectable raw list, not a guaranteed-populated chart), while curve_flagged/
error is the one signal to treat as fully real and always surface.

Compound commands (add_reagent, copy_plate, ...) flatten their per-iteration
aspirate/dispense TADM curves onto a ``tadm_curves`` property already
implemented in hamilton_venus.models.compound_results -- reused here via
getattr rather than re-deriving it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hamilton_workflow_framework.execution_engine import SendFn, Step
from hamilton_workflow_framework.registry import RegistryEntry

_ADC_COMMANDS = {"aspirate", "aspirate_5ml", "dispense", "dispense_5ml"}

# command_ids whose result exposes a flattened `tadm_curves` property (see
# hamilton_venus.models.compound_results) when adc=True was set on the
# relevant settings sub-object.
_COMPOUND_TADM_COMMANDS = {
    "add_reagent",
    "copy_plate",
    "hit_picking",
    "pool_samples",
    "replicate_samples",
    "serial_dilution_by_volume",
    "serial_dilution_by_dilution_factor",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _curve_to_message(position: str, curve: Any, timestamp: str) -> dict[str, Any]:
    curve_points = [
        {"time_ms": p.time_ms, "pressure": p.pressure}
        for p in (getattr(curve, "curve_points", None) or [])
    ]
    return {
        "type": "tadm_result",
        "position": position,
        "channel": getattr(curve, "channel_number", 0),
        "step_type_name": getattr(curve, "step_type_name", ""),
        "curve_flagged": bool(getattr(curve, "curve_flagged", 0)),
        "error_code": str(getattr(curve, "error", 0)) if getattr(curve, "error", 0) else None,
        "curve_points": curve_points,
        "timestamp": timestamp,
    }


class TadmObserver:
    """Emits a `tadm_result` WS message per TADM curve found on a step's result,
    only when the step actually requested ADC (adc=True). Stateless -- just
    forwards results.
    """

    async def after_step(
        self, entry: RegistryEntry, kwargs: dict[str, Any], result: Any, step: Step, send: SendFn
    ) -> None:
        if not kwargs.get("adc"):
            return

        position = kwargs.get("positions") if isinstance(kwargs.get("positions"), str) else ""
        timestamp = _now_iso()

        if entry.method_name in _ADC_COMMANDS:
            tadm = getattr(getattr(result, "return_parameters", None), "tadm", None)
            curves = getattr(tadm, "tadm_curves", None) or []
            for curve in curves:
                await send(_curve_to_message(position, curve, timestamp))
            return

        if entry.command_id in _COMPOUND_TADM_COMMANDS:
            curves = getattr(result, "tadm_curves", None) or []
            for curve in curves:
                await send(_curve_to_message(position, curve, timestamp))
