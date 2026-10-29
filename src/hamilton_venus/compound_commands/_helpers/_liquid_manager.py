"""Shared consumable-liquid-management helper for compound commands.

Implements *consumable liquid management* — the general capability for draining
consumable liquids (diluents, reagents, ...) from one or more source containers
in order.  Mirrors :mod:`hamilton_venus.compound_commands._helpers._tip_manager`
for the liquid domain.  The SDK does not maintain container fill levels, so
availability is tracked **reactively** from the measured per-channel liquid
volume reported after each aspiration
(:attr:`~hamilton_venus.models.command_types.AspirationChannelData.liquid_volume_ul`).

The core state lives on :class:`LiquidSourceTracker`, which owns an ordered list
of source positions consumed in order, a running remaining-volume *estimate* for
the active source, and the operator-reload prompt loop.  A running instance is
held by a command for the lifetime of a run (e.g. serial dilution's diluent
phase or add_reagent's source run), so the estimate persists across aspirations
and sources are drained in order.

Selector resolution is centralised in :func:`resolve_source_positions`, which
expands one or more selectors to the ordered list of source positions to drain,
so no command re-implements the position DSL.

:func:`ensure_liquid_available` is a thin, single-shot facade over the tracker
for callers that only need to resolve the active source for the next aspirate,
where no depletion estimate is carried between calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hamilton_venus._internal._operator_prompts import (
    LiquidReloadPromptContext,
    _invoke_callback,
)
from hamilton_venus.compound_commands._helpers._base import resolve_selector_positions
from hamilton_venus.exceptions import OperatorCancelledError

if TYPE_CHECKING:
    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.models.command_types import ChannelAspirationResponse
    from hamilton_venus.models.enums import CapacitiveLLD, PressureLLD
    from hamilton_venus.models.liquid_handling_settings import AspirateSettings
    from hamilton_venus.models.position import Position


_logger = logging.getLogger(__name__)


def lld_enabled(settings: AspirateSettings | None) -> bool:
    """Return whether an aspirate with *settings* detects the liquid surface.

    Only then is the ``liquid_volume_ul`` VENUS reports a measurement: without
    capacitive or pressure LLD it describes the fixed aspirate height (``0.0``
    for a reservoir aspirated near its bottom), not the liquid left.  Either
    detection mode on any channel counts; ``None`` settings mean the defaults,
    which have both off.
    """
    if settings is None:
        return False

    def _on(value: CapacitiveLLD | list[CapacitiveLLD] | PressureLLD | list[PressureLLD]) -> bool:
        values = value if isinstance(value, list) else [value]
        return any(int(v) != 0 for v in values)

    return _on(settings.capacitive_lld) or _on(settings.pressure_lld)


def measured_min_volume(response: ChannelAspirationResponse) -> float | None:
    """Return the minimum measured ``liquid_volume_ul`` across active channels.

    The estimate for a shared trough is the minimum across the channels that
    participated in the aspirate (Q-VOL1c).  Returns ``None`` when the response
    reports no per-channel data (nothing to seed the estimate from).
    """
    channels = response.return_parameters.channels
    if not channels:
        return None
    return min(ch.liquid_volume_ul for ch in channels)


def resolve_source_positions(client: InstrumentClient, source: str | list[str]) -> list[Position]:
    """Resolve *source* selector(s) to the ordered source positions to drain.

    The selector-resolution entry point for *consumable liquid management*: each
    selector is expanded to **all** the positions it addresses, and the results
    are concatenated in selector order.  A multi-well selector such as
    ``"Trough@1,2,3"`` therefore yields three ordered sources (drained in turn
    as each is exhausted), exactly as the equivalent list
    ``["Trough@1", "Trough@2", "Trough@3"]`` would.  A list of selectors is
    typically used to address distinct labware, whereas the comma form addresses
    multiple wells of the same labware; both expand to the same ordered list when
    they reference the same positions.

    Args:
        client: Connected instrument client for deck queries.
        source: A selector string or a list of selector strings.  Must resolve to
            at least one position overall.

    Returns:
        The ordered source positions, drained in list/selector order.

    Raises:
        ValueError: *source* is empty or a selector resolves to no positions.
    """
    selectors = [source] if isinstance(source, str) else list(source)
    if not selectors:
        raise ValueError("source must contain at least one entry.")
    sources: list[Position] = []
    for selector in selectors:
        resolved = resolve_selector_positions(client, selector)
        if not resolved:
            raise ValueError(f"source {selector!r} resolved to no positions.")
        sources.extend(resolved)
    return sources


def connected_source_labware(client: InstrumentClient, sources: list[Position]) -> set[str]:
    """Return the labware ids among *sources* that are connected containers.

    A *connected container* (``rack_layout.connected_container`` in the labware
    definition) is a single physical liquid whose several positions may be
    accessed by multiple channels at once.  Looks up each distinct labware via
    :meth:`~hamilton_venus.star_client.StarClient.get_labware_spec`; a labware
    whose spec cannot be resolved is treated as non-connected.
    """
    result: set[str] = set()
    seen: set[str] = set()
    for pos in sources:
        if pos.labware in seen:
            continue
        seen.add(pos.labware)
        try:
            spec = client.get_labware_spec(pos.labware)
        except Exception as e:  # unresolved geometry is treated as non-connected
            _logger.debug("Could not resolve labware spec for %r; treating as non-connected: %s", pos.labware, e)
            continue
        if getattr(spec, "connected_container", False):
            result.add(pos.labware)
    return result


def expand_connected_sources(
    client: InstrumentClient, sources: list[Position], connected_labware: set[str]
) -> list[Position]:
    """Replace each connected-container source with every section of its labware.

    A reservoir has no walls between its sections, so it is one liquid however
    it was addressed: ``"Trough@1"`` means the whole trough, and every channel
    gets a section of it.  Order is kept, each labware is expanded once where it
    first appears, and non-connected positions pass through unchanged.
    """
    expanded: list[Position] = []
    done: set[str] = set()
    for pos in sources:
        if pos.labware not in connected_labware:
            expanded.append(pos)
            continue
        if pos.labware in done:
            continue
        done.add(pos.labware)
        sections = resolve_selector_positions(client, pos.labware)
        expanded.extend(sections or [pos])
    return expanded


def connected_channel_cap(sources: list[Position], connected_labware: set[str], n_channels: int) -> int:
    """Return how many channels may aspirate *sources* simultaneously.

    A connected container can be addressed by at most as many channels as it has
    distinct positions (each channel takes one position of the shared liquid).
    The cap is the smallest such position count across the connected labware in
    *sources*, bounded by *n_channels*.  When no source labware is a connected
    container the full *n_channels* is returned (a non-connected source is
    drained one position at a time and the single active position is broadcast).
    """
    conn_counts = [
        sum(1 for p in sources if p.labware == lw)
        for lw in dict.fromkeys(p.labware for p in sources)
        if lw in connected_labware
    ]
    if not conn_counts:
        return n_channels
    return min(n_channels, min(conn_counts))



@dataclass(frozen=True)
class _SourceGroup:
    """One logical liquid source: its positions and whether channels spread across them.

    A non-spread group holds a single position broadcast to every channel (the
    classic drain-in-order behaviour).  A spread group -- every section of a
    connected container, or the positions of one ``add_reagent`` source selector
    such as ``"Tubes@1:4"`` -- gives each channel its own position, in passes
    when there are more channels than positions.
    """

    positions: tuple[Position, ...]
    spread: bool


def _build_source_groups(sources: list[Position], connected_labware: set[str]) -> list[_SourceGroup]:
    """Group *sources* into logical liquid sources.

    Consecutive positions on the same connected-container labware collapse into a
    single connected group; every other position becomes its own single-position
    group (drained in order).
    """
    groups: list[_SourceGroup] = []
    buffer: list[Position] = []

    def _flush_connected() -> None:
        if buffer:
            groups.append(_SourceGroup(positions=tuple(buffer), spread=True))
            buffer.clear()

    for pos in sources:
        if pos.labware in connected_labware:
            if buffer and buffer[-1].labware != pos.labware:
                _flush_connected()
            buffer.append(pos)
        else:
            _flush_connected()
            groups.append(_SourceGroup(positions=(pos,), spread=False))
    _flush_connected()
    return groups


class LiquidSourceTracker:
    """Track diluent depletion across an ordered list of source positions.

    Sources are consumed **in order** and shared/drained across the whole run.
    The remaining-volume estimate for the active source is seeded reactively from
    the first aspirate's measured volume and decremented by each subsequent
    aspirate; a measured value always overrides the running estimate
    (Q-VOL1f).  Source switching happens **only between whole aspirations**.

    Args:
        sources: Ordered source positions to drain.  Must be non-empty.
        connected_labware: Labware ids among *sources* that are connected
            containers (see :func:`connected_source_labware`).  Positions on
            these labware are accessed simultaneously by multiple channels rather
            than drained one at a time.

    Use :meth:`from_groups` instead to give the logical sources explicitly.

    Raises:
        ValueError: *sources* is empty.
    """

    def __init__(self, sources: list[Position], *, connected_labware: set[str] | None = None) -> None:
        if not sources:
            raise ValueError("LiquidSourceTracker requires at least one source position.")
        self._sources: list[Position] = list(sources)
        self._groups: list[_SourceGroup] = _build_source_groups(self._sources, connected_labware or set())
        self._index: int = 0
        # ``None`` until the first aspirate is measured (reactive seeding). While
        # ``None`` the active source is treated as able to satisfy the next
        # aspirate (the first stroke cannot be pre-validated).
        self._estimate: float | None = None

    @classmethod
    def from_groups(cls, groups: list[list[Position]]) -> LiquidSourceTracker:
        """Track explicit source groups, drained in order, each spread across its positions.

        Each group is one logical source whose positions the channels share, in
        passes when there are more channels than positions (see
        :meth:`aspirate_passes`): ``[Tube1]`` sends every channel to tube 1 in
        turn; ``[Tube1, ..., Tube4]`` sends channels 1-4 to tubes 1-4, then 5-8 to
        tubes 1-4.  The next group is used once the active one runs short.
        """
        groups = [list(g) for g in groups if g]
        if not groups:
            raise ValueError("LiquidSourceTracker requires at least one source position.")
        tracker = cls([pos for g in groups for pos in g])
        tracker._groups = [_SourceGroup(positions=tuple(g), spread=True) for g in groups]
        return tracker

    @property
    def sources(self) -> list[Position]:
        """The ordered source positions being drained (defensive copy)."""
        return list(self._sources)

    @property
    def active_source(self) -> Position:
        """The source position currently being consumed."""
        return self._groups[self._index].positions[0]

    def aspirate_passes(self, channels: list[int]) -> list[tuple[list[int], list[Position]]]:
        """Split an aspirate from the active source into ``(channels, positions)`` passes.

        A spread group gives each channel its own position.  When there are more
        channels than positions the channels go in passes that each start again
        at the first position: with 8 reservoir sections, channels 1-8 take
        sections 1-8, then channels 9-16 take sections 1-8; with a single tube,
        each channel takes its turn at that tube.  A non-spread source is a single
        pass with the active position broadcast to every channel.
        """
        group = self._groups[self._index]
        if not group.spread:
            return [(list(channels), [group.positions[0]] * len(channels))]
        size = len(group.positions)
        passes = []
        for i in range(0, len(channels), size):
            pass_channels = list(channels[i : i + size])
            passes.append((pass_channels, list(group.positions[: len(pass_channels)])))
        return passes

    def aspirate_plan(self, n_channels: int) -> list[Position]:
        """Return the positions to address for an *n_channels* aspirate.

        Always returns exactly *n_channels* positions.  For a connected container
        that has at least *n_channels* positions, the channels are spread across
        distinct positions of the shared liquid (``positions[:n_channels]``).
        Otherwise the single active position is broadcast across every channel
        (``[source] * n_channels``), matching the classic behaviour -- so the
        multi-channel path activates only when the channels actually fit the
        container.
        """
        group = self._groups[self._index]
        if group.spread and len(group.positions) >= n_channels:
            return list(group.positions[:n_channels])
        return [group.positions[0]] * n_channels

    @property
    def sources_used(self) -> list[Position]:
        """The source positions drained so far, in order of consumption.

        Every group up to and including the currently-active one has been
        started (the tracker only advances to the next group when the active one
        is exhausted; the active group is still in use), so this returns the flat
        positions of ``groups[: active_index + 1]``.  Before any aspirate this is
        the first group alone.
        """
        used: list[Position] = []
        for group in self._groups[: self._index + 1]:
            used.extend(group.positions)
        return used

    @property
    def budget(self) -> float | None:
        """Current remaining-volume estimate for the active source.

        ``None`` until the first aspirate is measured (reactive seeding).
        """
        return self._estimate

    def _advance(self) -> bool:
        """Move to the next source group, resetting the estimate.  Returns success."""
        if self._index + 1 >= len(self._groups):
            return False
        self._index += 1
        self._estimate = None
        return True

    def ensure_available(
        self,
        client: InstrumentClient,
        required: float,
        *,
        command_name: str,
    ) -> tuple[Position, float | None]:
        """Ensure the active source can satisfy *required*, switching if needed.

        Returns the ``(source, budget)`` to use for the next aspirate.  When the
        current estimate is insufficient the tracker advances to the next source;
        once all sources are exhausted the operator is prompted via
        ``client.on_liquid_reload_prompt``.  With no callback configured nobody
        can log a refill, so the shortage is traced (a warning plus a
        ``liquid_shortage`` run-log entry) and the run carries on: the estimate is
        only an estimate, and the next measured aspirate re-seeds it.

        The very first aspirate cannot be pre-validated (the estimate is unknown
        until it is measured), so while the estimate is ``None`` the active source
        is returned immediately.

        Args:
            client: Connected instrument client (for the reload prompt callback).
            required: Volume the caller needs from the active source.
            command_name: Name of the compound command issuing the prompt.

        Returns:
            ``(source, budget)`` where *budget* is the remaining estimate for the
            active source (``None`` before the first measurement).

        Raises:
            OperatorCancelledError: The operator cancelled the reload prompt.
        """
        # Reactive seeding: the first stroke cannot be pre-validated.
        if self._estimate is None:
            return self.active_source, self._estimate

        if self._estimate >= required:
            return self.active_source, self._estimate

        # Active source is short; try the remaining sources in order.
        while self._advance():
            if self._estimate is None or self._estimate >= required:
                return self.active_source, self._estimate

        # All sources exhausted: prompt the operator to reload/replace.
        self._prompt_reload(client, required, command_name=command_name)
        return self.active_source, self._estimate

    def record_aspirate(self, response: ChannelAspirationResponse, *, measured_level: bool = True) -> None:
        """Update the running estimate from a completed aspirate's measurement.

        The measured minimum across channels (Q-VOL1c) always overrides the
        running estimate (Q-VOL1f).  When the response carries no per-channel
        data, or the aspirate did not detect the liquid (*measured_level* false,
        see :func:`lld_enabled`), the estimate is left unchanged.
        """
        if not measured_level:
            return
        measured = measured_min_volume(response)
        if measured is not None:
            self._estimate = measured

    def consume(self, volume: float) -> None:
        """Decrement the running estimate by *volume* (a no-op before seeding)."""
        if self._estimate is not None:
            self._estimate = max(0.0, self._estimate - volume)

    def _prompt_reload(
        self,
        client: InstrumentClient,
        required: float,
        *,
        command_name: str,
    ) -> None:
        """Run the operator reload loop until enough liquid is available."""
        callback = client.on_liquid_reload_prompt
        available = self._estimate if self._estimate is not None else 0.0
        source_labels = tuple(f"{s.labware}@{s.well}" for s in self._sources)
        active_label = f"{self.active_source.labware}@{self.active_source.well}"
        if callback is None:
            _trace_shortage(
                client,
                command_name=command_name,
                sources=list(source_labels),
                active_source=active_label,
                available=available,
                required=required,
            )
            # Start over from the next measured aspirate rather than warning on
            # every stroke from the same stale estimate.
            self._estimate = None
            return

        attempt = 1
        while True:
            context = LiquidReloadPromptContext(
                sources=source_labels,
                active_source=active_label,
                required=required,
                available=available,
                command=command_name,
                attempt=attempt,
            )
            if not _invoke_callback(callback, context):
                raise OperatorCancelledError(
                    f"{command_name}: operator cancelled liquid reload for "
                    f"'{active_label}' (required={required}, available={available})."
                )
            # The operator refilled/replaced the trough; the level is re-read on
            # the next aspirate (reactive seeding), so clear the stale estimate
            # and treat the active source as replenished.
            self._estimate = None
            return


def _trace_shortage(
    client: InstrumentClient,
    *,
    command_name: str,
    sources: list[str],
    active_source: str,
    available: float,
    required: float,
) -> None:
    """Record that the liquid estimate ran short with no refill logged, without stopping."""
    message = (
        f"{command_name}: liquid sources {sources} estimated exhausted: {available} uL available "
        f"on '{active_source}', but {required} uL are required, and no refill was logged. Continuing."
    )
    _logger.warning(message)
    run_log = getattr(client, "_run_log", None)
    if run_log is None:
        return
    try:
        run_log.record(
            "SDK",
            "Out",
            "liquid_shortage",
            {
                "command": command_name,
                "sources": sources,
                "active_source": active_source,
                "available_ul": available,
                "required_ul": required,
                "message": message,
            },
        )
    except Exception as exc:
        _logger.debug("Could not record liquid shortage in the run log: %s", exc)


def ensure_liquid_available(
    client: InstrumentClient,
    sources: list[Position],
    required: float,
    *,
    command_name: str,
) -> tuple[Position, float | None]:
    """Resolve the source to use for a single aspirate of *required* volume.

    Single-shot facade over :class:`LiquidSourceTracker` for callers that do not
    carry a depletion estimate between aspirations.  Commands that aspirate
    repeatedly (``add_reagent``, ``serial_dilution``) instantiate a
    :class:`LiquidSourceTracker` directly so the estimate persists; this helper
    is provided for simpler callers that resolve one aspirate at a time.  With a
    single always-available source this simply returns ``(sources[0], None)``.

    Args:
        client: Connected instrument client (for the reload prompt callback).
        sources: Ordered source positions to drain.  Must be non-empty.
        required: Volume the caller needs from the active source.
        command_name: Name of the compound command issuing the prompt.

    Returns:
        ``(source, budget)`` for the next aspirate; *budget* is ``None`` when no
        measurement has seeded the estimate.
    """
    return LiquidSourceTracker(sources).ensure_available(client, required, command_name=command_name)
