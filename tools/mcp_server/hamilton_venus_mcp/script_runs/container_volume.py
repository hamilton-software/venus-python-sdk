"""Labware container geometry: nominal capacity and reservoir classification.

Ported from ``python_script_manager_app/backend/script_runner.py``'s
``_segment_volume_ul``/``_resolve_container_max_volume``/``_is_reservoir_labware`` (proven
against real labware definitions in that app), generalized to take a plain
``get_definition(labware_id) -> LabwareDefinition`` callable instead of a live client directly,
so it can be unit tested with fixtures and reused by both the run's live tracking (percent-full)
and anything else that needs a labware's nominal volume.

Every ``hamilton_venus`` labware:v1 length field (height/diameter/width/depth) is already in mm,
so ``1 mm^3 == 1 uL`` and no unit conversion is needed beyond the geometry itself.
"""

from __future__ import annotations

import math
import threading
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from hamilton_venus.models.labware_definition import LabwareDefinition, VolumeSegment


class DefinitionLookup(Protocol):
    def __call__(self, labware_id: str) -> "LabwareDefinition | None": ...


def segment_volume_ul(segment: "VolumeSegment") -> float:
    """Volume of one ``VolumeSegment``, by its shape. An unknown/future shape, or one missing
    the fields its own shape needs, contributes ``0.0`` rather than raising -- a labware
    definition this SDK doesn't fully model yet should undercount that one segment, not blow up
    volume tracking for the whole run."""
    height = segment.height or 0.0
    if height <= 0:
        return 0.0
    kind = (segment.type or "").strip().lower()
    if kind == "cylinder":
        radius = (segment.diameter or 0.0) / 2.0
        return math.pi * radius * radius * height
    if kind == "rectangular_prism":
        return (segment.width or 0.0) * (segment.depth or 0.0) * height
    if kind == "conical_frustum":
        # Frustum of a cone: V = (pi*h/12) * (D1^2 + D1*D2 + D2^2), D=diameter.
        d1, d2 = segment.diameter_bottom or 0.0, segment.diameter_top or 0.0
        return (math.pi * height / 12.0) * (d1 * d1 + d1 * d2 + d2 * d2)
    if kind == "rectangular_frustum":
        # Frustum of a pyramid: V = (h/3) * (A1 + A2 + sqrt(A1*A2)).
        a1 = (segment.width_bottom or 0.0) * (segment.depth_bottom or 0.0)
        a2 = (segment.width_top or 0.0) * (segment.depth_top or 0.0)
        return (height / 3.0) * (a1 + a2 + math.sqrt(a1 * a2))
    if kind == "spherical_cap":
        # Cap of height h with a flat circular base of radius a (diameter is that base's
        # diameter, not the parent sphere's): V = (pi*h/6)*(3a^2+h^2).
        a = (segment.diameter or 0.0) / 2.0
        return (math.pi * height / 6.0) * (3 * a * a + height * height)
    return 0.0


def is_reservoir(definition: "LabwareDefinition | None") -> bool:
    """A reservoir is identified by ``labwareClass == "reservoir"`` on its own definition, not
    the connected-container flag -- it is still one physical liquid pool addressed by several
    channels at once, each at its own distinct sub-position, so per-channel readings must be
    pooled into ONE tracked reservoir, not N separate ones."""
    if definition is None:
        return False
    return (definition.labware_class or "").strip().lower() == "reservoir"


def container_max_volume_ul(definition: "LabwareDefinition | None") -> float | None:
    """Nominal capacity computed once from a labware's own volume model (the stacked segments
    describing container shape) -- fixed for the life of a run, unlike a depth-based estimate
    that would drift with each new LLD height reading, since this comes from static geometry.

    A labware whose own definition says ``labwareClass == "reservoir"`` is tracked as ONE pooled
    entry spanning every one of its addressable positions, so its capacity is the sum of every
    grid cell's volume, not just one. Anything else (a tube, a plate well) is tracked per well,
    so it gets just that one cell's own volume.

    Returns ``None`` when the definition is missing, or carries no usable volume model.
    """
    if definition is None:
        return None
    pooled = is_reservoir(definition)
    total = 0.0
    for grid in definition.container_grids.values():
        segments = grid.container_definition.volume_model.segments
        if not segments:
            continue
        cell_volume = sum(segment_volume_ul(seg) for seg in segments)
        if cell_volume <= 0:
            continue
        if pooled:
            total += cell_volume * max(1, grid.rows * grid.columns)
        else:
            return cell_volume
    return total if total > 0 else None


class LabwareGeometryCache:
    """Caches ``get_definition``/capacity/reservoir-classification lookups per labware id for
    the life of one run -- both the definition fetch and the capacity computation are pure
    functions of the (immutable, per-run) labware id, so there's never a reason to look either
    up twice. Thread-safe: the run's tracking wrappers can fire from more than one channel op
    concurrently."""

    def __init__(self, get_definition: DefinitionLookup) -> None:
        self._get_definition = get_definition
        self._lock = threading.Lock()
        self._definitions: dict[str, "LabwareDefinition | None"] = {}
        self._capacities: dict[str, float | None] = {}

    def definition(self, labware_id: str) -> "LabwareDefinition | None":
        with self._lock:
            if labware_id in self._definitions:
                return self._definitions[labware_id]
        try:
            found = self._get_definition(labware_id)
        except Exception:  # noqa: BLE001 - a lookup failure means "unknown", not fatal
            found = None
        with self._lock:
            self._definitions[labware_id] = found
        return found

    def is_reservoir(self, labware_id: str) -> bool:
        return is_reservoir(self.definition(labware_id))

    def max_volume_ul(self, labware_id: str) -> float | None:
        with self._lock:
            if labware_id in self._capacities:
                return self._capacities[labware_id]
        capacity = container_max_volume_ul(self.definition(labware_id))
        with self._lock:
            self._capacities[labware_id] = capacity
        return capacity
