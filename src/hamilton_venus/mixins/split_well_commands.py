"""Split wells: several channels pipetting side by side inside one large well.

``split_wells`` places a temporary rack of channel-pitch slots inside each chosen
well (see :mod:`hamilton_venus.split_well_geometry`) and registers it on the client.
From then on, aspirate / dispense / liquid level detection calls that send two or
more channels of the matching type to that well are routed to the slots: channel
``c`` goes to slot ``c - first_channel + 1``. Nothing else changes for the caller.

The registry lives on the client object, like ``tilt_labware``'s, keyed by
lower-cased labware id (VENUS stores ids lower-cased). The split racks are real
labware in the VENUS deck layout, so the SDK removes them when the parent is
removed, and removes and rebuilds them around anything that moves or reshapes the
parent: ``tilt_labware``, ``shift_labware``, ``move_carrier`` and the transport
commands. ``deck_load`` replaces the whole layout, so it only forgets them.

The lifecycle helpers below are module functions, not mixin methods, so the other
mixins can call them on any client; they do nothing while no well is split.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hamilton_venus.constants import MAX_CHANNELS
from hamilton_venus.exceptions import SplitWellCapacityError
from hamilton_venus.labware_builder import build_labware_definition, round_well
from hamilton_venus.models import (
    LabwareWellCoordinates,
    LayoutAddSplitWellSiteParameters,
    LayoutAddSplitWellSiteResponse,
    LayoutRemoveLabwareParameters,
    Position,
    SplitWellSlotInput,
)
from hamilton_venus.models.enums import SplitChannelType, SplitWellFit, TiltWellPosition
from hamilton_venus.models.position import normalize_positions
from hamilton_venus.split_well_geometry import (
    CHANNEL_PITCH_BY_TYPE,
    DEFAULT_TIP_PROFILES,
    SplitFit,
    SplitWellPlan,
    TipProfile,
    compute_split_well_plan,
    normalize_channel_type,
    normalize_fit,
)
from hamilton_venus.tilt_clearance import DEFAULT_HIGH_WALL_MARGIN_MM, DEFAULT_WALL_MARGIN_MM
from hamilton_venus.tilt_geometry import TiltSettings

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

logger = logging.getLogger(__name__)

_CHANNEL_TYPE_BY_PREFIX = {"channels.1mL": SplitChannelType.ONE_ML, "channels.5mL": SplitChannelType.FIVE_ML}

_SplitKey = tuple[str, str, SplitChannelType]  # (parent labware lower-cased, well upper-cased, channel type)


@dataclass(frozen=True)
class SplitWellRequest:
    """The ``split_wells`` options a split was made with, kept to rebuild it later."""

    channel_type: SplitChannelType
    max_channels: int | None = None
    fit: SplitFit = SplitWellFit.POSITION
    well_position: TiltWellPosition | None = None
    tip_profile: TipProfile | None = None
    tip_end_height_mm: float | None = None
    wall_margin_mm: float | None = None
    high_wall_margin_mm: float | None = None


@dataclass(frozen=True)
class SplitWellSite:
    """One split well: the temporary rack in it and where its slots are.

    ``split_labware`` is the rack's labware id; its positions (``slot_wells``: ``"1"``,
    ``"2"``, ... from the back) are the slots. ``coordinates`` holds their deck
    coordinates as VENUS placed them.
    """

    parent_labware: str
    parent_well: str
    channel_type: SplitChannelType
    split_labware: str
    plan: SplitWellPlan
    coordinates: tuple[LabwareWellCoordinates, ...] = ()
    request: SplitWellRequest = field(default_factory=lambda: SplitWellRequest(SplitChannelType.ONE_ML), repr=False)

    @property
    def slot_count(self) -> int:
        return self.plan.slot_count

    @property
    def slot_wells(self) -> list[str]:
        return [slot.well for slot in self.plan.slots]


def split_labware_id(parent_labware: str, well: str, channel_type: SplitChannelType | str, slot_count: int) -> str:
    """The id ``split_wells`` gives the *slot_count*-slot split rack in *parent_labware*'s *well*.

    The slot count is part of the id (``plate1_a1_split_1ml_4slots``), so racks with a
    different number of slots (after a tilt, or a new ``max_channels``) never share an id.
    """
    channel = normalize_channel_type(channel_type).value
    return f"{parent_labware}_{well}_split_{channel}_{slot_count}slots".lower()


def _split_state(client: object) -> dict[_SplitKey, SplitWellSite]:
    return vars(client).setdefault("_split_wells", {})


def _held_state(client: object) -> dict[str, list[SplitWellSite]]:
    return vars(client).setdefault("_split_wells_held", {})


def _send_remove(client: Any, labware_id: str) -> None:
    parameters = LayoutRemoveLabwareParameters(labware_name=labware_id)
    client._run(
        client._connected_instrument.venus.send_command(
            category="Deck Layout",
            action_name="labware.removeLabware",
            parameters=parameters.model_dump(by_alias=True),
        )
    )


def _consolidate_volume(client: Any, site: SplitWellSite) -> None:
    """Add the slots' tracked volumes back onto the parent well (STAR Tools' RemoveContainers)."""
    if not hasattr(client, "get_labware_details") or not hasattr(client, "set_labware_volume"):
        return
    details = client.get_labware_details([site.split_labware, f"{site.parent_labware}@{site.parent_well}"])
    total = 0.0
    for labware in details.return_parameters.labware:
        total += sum(well.volume or 0.0 for well in labware.wells)
    client.set_labware_volume(f"{site.parent_labware}@{site.parent_well}", max(total, 0.0))


def _remove_sites(client: Any, sites: Iterable[SplitWellSite], *, consolidate_volumes: bool = False) -> list[str]:
    """Take *sites* off the deck and out of the registry; return the removed rack ids."""
    state = _split_state(client)
    removed: list[str] = []
    for site in sites:
        if consolidate_volumes:
            _consolidate_volume(client, site)
        try:
            _send_remove(client, site.split_labware)
        finally:
            state.pop((site.parent_labware, site.parent_well, site.channel_type), None)
        removed.append(site.split_labware)
    return removed


def _reapply(client: Any, sites: Iterable[SplitWellSite]) -> None:
    """Rebuild *sites* from their stored requests, at the parents' current geometry."""
    split = getattr(client, "split_wells", None)
    if split is None:
        return
    groups: dict[tuple[str, SplitWellRequest], list[str]] = {}
    for site in sites:
        groups.setdefault((site.parent_labware, site.request), []).append(site.parent_well)
    for (parent, request), wells in groups.items():
        try:
            rebuilt = split(
                parent,
                wells,
                channel_type=request.channel_type,
                max_channels=request.max_channels,
                fit=request.fit,
                well_position=request.well_position,
                tip_profile=request.tip_profile,
                tip_end_height_mm=request.tip_end_height_mm,
                wall_margin_mm=request.wall_margin_mm,
                high_wall_margin_mm=request.high_wall_margin_mm,
            )
        except Exception:
            logger.warning(
                "Could not rebuild the split wells %s of %r; they stay removed", wells, parent, exc_info=True
            )
            continue
        made = {site.parent_well: site.slot_count for site in rebuilt}
        for well in wells:
            if well not in made:
                logger.warning("%r %s no longer holds 2+ channels; it is no longer split", parent, well)


def _sites_of(client: object, labware_names: Iterable[str]) -> list[SplitWellSite]:
    state = vars(client).get("_split_wells")
    if not state:
        return []
    names = {name.lower() for name in labware_names if name}
    return [site for site in state.values() if site.parent_labware in names]


@contextmanager
def split_wells_suspended(client: Any, labware_names: Iterable[str] | None, *, reapply: bool = True) -> Iterator[None]:
    """Remove the split wells of *labware_names* (all if ``None``) around an operation.

    If the operation succeeds and *reapply* is set, they are rebuilt afterwards at the
    parents' new geometry; if it raises, they stay removed (and forgotten).
    """
    state = vars(client).get("_split_wells")
    sites = list(state.values()) if state and labware_names is None else _sites_of(client, labware_names or ())
    if not sites:
        yield
        return
    _remove_sites(client, sites)
    try:
        yield
    except Exception:
        parents = sorted({site.parent_labware for site in sites})
        logger.warning("Split wells of %s were removed and not rebuilt: the operation failed", parents)
        raise
    if reapply:
        _reapply(client, sites)


def hold_split_wells(client: Any, labware_name: str, gripper: str) -> None:
    """Remove the split wells of labware a gripper picks up; ``release_held_split_wells`` rebuilds them."""
    sites = _sites_of(client, [labware_name])
    if sites:
        _remove_sites(client, sites)
        _held_state(client).setdefault(gripper, []).extend(sites)


def release_held_split_wells(client: Any, gripper: str) -> None:
    """Rebuild the split wells of the labware *gripper* just put down."""
    held = vars(client).get("_split_wells_held")
    sites = held.pop(gripper, []) if held else []
    if sites:
        _reapply(client, sites)


def forget_split_wells(client: Any, labware_names: Iterable[str]) -> None:
    """Remove the split wells of labware that is leaving the deck (or of a removed split rack)."""
    state = vars(client).get("_split_wells")
    if not state:
        return
    names = {name.lower() for name in labware_names if name}
    for key, site in list(state.items()):
        if site.split_labware in names:
            state.pop(key, None)  # the rack itself is being removed by the caller
    sites = _sites_of(client, names)
    if sites:
        _remove_sites(client, sites)


def clear_split_wells(client: object) -> None:
    """Forget every split well without touching VENUS (the deck layout was replaced)."""
    vars(client).pop("_split_wells", None)
    vars(client).pop("_split_wells_held", None)


def route_split_wells(
    client: object, positions: list[Position], channels: list[int], action_prefix: str
) -> list[Position]:
    """Send channels that share a split well to its slots: channel ``c`` -> slot ``c - first + 1``.

    Only for the channel type the split was made for, and only when two or more of
    the channels target the same well; a single channel keeps the well centre.
    """
    state = vars(client).get("_split_wells")
    channel_type = _CHANNEL_TYPE_BY_PREFIX.get(action_prefix)
    if not state or channel_type is None or len(positions) != len(channels):
        return positions
    groups: dict[_SplitKey, list[int]] = {}
    for index, position in enumerate(positions):
        key = (position.labware.lower(), position.well.upper(), channel_type)
        if key in state:
            groups.setdefault(key, []).append(index)
    routed = list(positions)
    for key, indexes in groups.items():
        if len(indexes) < 2:
            continue
        site = state[key]
        group_channels = [channels[index] for index in indexes]
        first = min(group_channels)
        needed = max(group_channels) - first + 1
        if needed > site.slot_count:
            raise SplitWellCapacityError(
                f"{site.parent_labware} {site.parent_well} is split into {site.slot_count} slots for "
                f"{channel_type.value} channels (limited by {site.plan.limited_by}), but channels "
                f"{sorted(group_channels)} span {needed}"
            )
        for index in indexes:
            slot = site.plan.slots[channels[index] - first]
            routed[index] = Position(labware=site.split_labware, well=slot.well)
    return routed


def _split_rack_definition(split_id: str, plan: SplitWellPlan) -> dict[str, Any]:
    """A 1-column rack of ``plan.slot_count`` numbered positions at channel pitch, flush with the well top.

    Its wells only stand in until VENUS puts the parent well's own container in each
    slot, so their size does not matter beyond fitting the pitch.
    """
    pitch = plan.pitch_mm
    depth = max(plan.well_depth, 1.0)
    definition = build_labware_definition(
        split_id,
        height=depth,
        rows=plan.slot_count,
        columns=1,
        first_well_center=(pitch / 2.0, pitch / 2.0),
        well=round_well(diameter=pitch * 0.8, depth=depth, bottom_wall_thickness=0.0),
        width=pitch,
        depth=plan.slot_count * pitch,
        row_pitch=pitch,
        column_pitch=pitch,
        well_floor_height=0.0,
        description=f"Temporary split-well rack ({plan.slot_count} x {pitch:g} mm)",
    )
    # Positions "1".."N" from the back, like a sample carrier, so slot n is position "n".
    definition["containerGrids"]["default"]["namingConvention"]["rowStyle"] = "numeric"
    return definition


class SplitWellCommandsMixin:
    """Mixin providing ``split_wells`` and its registry."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

        def get_labware_spec(self, labware_id: str) -> Any: ...

        def labware_get_params_from_id(self, labware_name: str) -> Any: ...

    def split_wells(
        self,
        labware_name: str,
        wells: str | list[str] | None = None,
        *,
        channel_type: SplitChannelType = SplitChannelType.ONE_ML,
        max_channels: int | None = None,
        fit: SplitFit = SplitWellFit.POSITION,
        well_position: TiltWellPosition | None = None,
        tip_profile: TipProfile | None = None,
        tip_end_height_mm: float | None = None,
        wall_margin_mm: float | None = None,
        high_wall_margin_mm: float | None = None,
    ) -> list[SplitWellSite]:
        """Let several channels pipette side by side into each of *wells*.

        Places a temporary rack of slots inside each well, spaced by the channel pitch
        (9 mm for 1 mL channels, 18 mm for 5 mL), each with the well's own container
        so its depth, Z bottom and LLD are unchanged. Afterwards, aspirate / dispense /
        liquid level detection with two or more channels of *channel_type* on one of
        these wells go to its slots automatically: channel ``c`` to slot
        ``c - first_channel + 1``, so adjacent channels use adjacent slots. A single
        channel still goes to the well centre.

        The number of slots is how many tips fit in the well, using the shape in its
        labware definition and, on a tilted plate (``tilt_labware``), the tilt and the
        point in the well being aimed at. Wells that cannot take two channels are
        skipped (with a warning). Splitting a well again replaces its split.

        The splits follow the plate: ``tilt_labware``, ``shift_labware``,
        ``move_carrier`` and the transport commands remove and rebuild them,
        ``remove_labware`` removes them, and ``deck_load`` forgets them.

        Args:
            labware_name: The plate (or other labware) holding the wells.
            wells: Wells to split: a selector as used by pipetting steps without the
                labware part (``"A1"``, ``"A1:B3"``, ``"row:A"``), a list of well
                names, or ``None`` for every well.
            channel_type: :class:`~hamilton_venus.models.enums.SplitChannelType`: which
                channels will use the split (``ONE_ML`` / ``FIVE_ML``), which also sets the
                slot pitch.
            max_channels: Most slots per well. Defaults to the channels installed.
            fit: What to give up when the well is narrow where the tips go:
                :attr:`~hamilton_venus.models.enums.SplitWellFit.POSITION` keeps the aim.
                Aimed at the centre, it uses as many channels as fit there; aimed at a
                wall (``DEEPEST_POINT`` / ``HIGHEST_POINT``), it uses as many channels
                as the well holds, placed as close to that wall as they fit.
                :attr:`~hamilton_venus.models.enums.SplitWellFit.MAX_CHANNELS` uses the
                most channels the well can take and moves toward the aim only as far
                as they fit; an ``int`` asks for exactly that many channels (an error
                if they can't fit), as close to the aim as they fit.
            well_position: Where to aim the slots across a tilted well. Defaults to
                where ``tilt_labware`` aimed the plate. Ignored on a flat plate.
            tip_profile: Tip shape used to decide what fits. Defaults to the profile
                passed to ``tilt_labware`` (1 mL splits only), else the 1000 uL / 5 mL
                CO-RE tip for the channel type
                (:data:`~hamilton_venus.tilt_clearance.DEFAULT_TIP_PROFILES`).
                Pass the real tip's profile for smaller tips (e.g. 300 uL).
            tip_end_height_mm: How far above the floor the tip ends will be (the
                aspirate / dispense fixed height). Defaults to ``tilt_labware``'s, else 0.
            wall_margin_mm: Gap kept between the tips and the low wall (and the walls
                along the hinge). Defaults to ``tilt_labware``'s, else 1.0.
            high_wall_margin_mm: Gap kept between the tips and the high wall, which
                leans in over them. Defaults to ``tilt_labware``'s, else 2.0.

        Returns:
            One :class:`SplitWellSite` per well that was split.

        Raises:
            ValueError: For an unknown channel type, a bad ``max_channels`` or
                ``fit``, labware without a single container grid, or an ``int``
                ``fit`` a well can't hold.
        """
        channel_type = normalize_channel_type(channel_type)
        installed = getattr(self, "_channel_limits", {}).get(f"channels.{channel_type.value}", MAX_CHANNELS)
        if max_channels is not None and not 1 <= max_channels <= installed:
            raise ValueError(f"max_channels must be between 1 and {installed}, got {max_channels}")
        fit = normalize_fit(fit, max_channels or installed)
        request = SplitWellRequest(
            channel_type,
            max_channels,
            fit,
            well_position,
            tip_profile,
            tip_end_height_mm,
            wall_margin_mm,
            high_wall_margin_mm,
        )
        parent = labware_name.lower()
        well_names = self._split_well_names(labware_name, wells)
        definition = self.labware_get_params_from_id(labware_name).return_parameters.definition
        tilt: TiltSettings | None = vars(self).get("_tilt_settings", {}).get(parent)
        angle = tilt.angle_degrees if tilt else 0.0
        parent_position = tilt.well_position if tilt else TiltWellPosition.CENTER
        # tilt_labware aims 1 mL-channel tips, so its tip profile only stands in for a 1 mL split.
        plate_tip = tilt.tip_profile if tilt and channel_type is SplitChannelType.ONE_ML else None
        tip = tip_profile or plate_tip or DEFAULT_TIP_PROFILES[channel_type]

        def setting(value: float | None, name: str, default: float) -> float:
            if value is not None:
                return value
            return getattr(tilt.clearance, name) if tilt else default

        plans = [
            compute_split_well_plan(
                definition,
                well,
                pitch_mm=CHANNEL_PITCH_BY_TYPE[channel_type],
                max_channels=max_channels or installed,
                tilt_degrees=angle,
                well_position=well_position or parent_position,
                parent_well_position=parent_position,
                parent_x_shift=tilt.aim_x_shift if tilt else 0.0,
                fit=fit,
                tip=tip,
                tip_end_height_mm=setting(tip_end_height_mm, "tip_end_height_mm", 0.0),
                wall_margin_mm=setting(wall_margin_mm, "wall_margin_mm", DEFAULT_WALL_MARGIN_MM),
                high_wall_margin_mm=setting(high_wall_margin_mm, "high_wall_margin_mm", DEFAULT_HIGH_WALL_MARGIN_MM),
            )
            for well in well_names
        ]
        state = _split_state(self)
        sites: list[SplitWellSite] = []
        for plan in plans:
            key = (parent, plan.well, channel_type)
            if key in state:
                _remove_sites(self, [state[key]])
            if plan.slot_count < 2:
                logger.warning(
                    "%r %s holds only one %s channel (limited by %s); not split",
                    labware_name, plan.well, channel_type.value, plan.limited_by,
                )
                continue
            split_id = split_labware_id(parent, plan.well, channel_type, plan.slot_count)
            parameters = LayoutAddSplitWellSiteParameters(
                split_labware_name=split_id,
                parent_labware_name=labware_name,
                parent_well=plan.well,
                definition=_split_rack_definition(split_id, plan),
                slots=[SplitWellSlotInput(well=s.well, delta_x=s.dx, delta_y=s.dy, delta_z=s.dz) for s in plan.slots],
                rack_delta_x=plan.slots[0].dx - plan.pitch_mm / 2.0,
                rack_delta_y=-plan.slot_count * plan.pitch_mm / 2.0,
                # VENUS ignores a Z offset on rack position 1, so raise the whole rack to slot 1's
                # height instead; the other slots are then placed relative to it (seen in simulation).
                rack_delta_z=plan.slots[0].dz,
            )
            response = self._run(
                self._connected_instrument.venus.send_command(
                    category="Deck Layout",
                    action_name="labware.addSplitWellSite",
                    parameters=parameters.model_dump(by_alias=True),
                )
            )
            placed = LayoutAddSplitWellSiteResponse.model_validate(response.model_dump(by_alias=True))
            site = SplitWellSite(
                parent_labware=parent,
                parent_well=plan.well,
                channel_type=channel_type,
                split_labware=split_id,
                plan=plan,
                coordinates=tuple(placed.return_parameters.slots),
                request=request,
            )
            state[key] = site
            sites.append(site)
        return sites

    def remove_split_wells(
        self,
        labware_name: str | None = None,
        wells: str | list[str] | None = None,
        *,
        channel_type: SplitChannelType | None = None,
        consolidate_volumes: bool = False,
    ) -> list[str]:
        """Remove split wells made by ``split_wells``; pipetting goes to the well centres again.

        Args:
            labware_name: Only this labware's splits; ``None`` for every split well.
            wells: Only these wells (as for ``split_wells``); ``None`` for all of them.
            channel_type: Only splits for this :class:`~hamilton_venus.models.enums.SplitChannelType`.
            consolidate_volumes: Add the volume sample tracking recorded in the slots
                back onto the parent well before removing them.

        Returns:
            The ids of the split racks removed.
        """
        state = vars(self).get("_split_wells")
        if not state:
            return []
        selected = list(state.values())
        if labware_name:
            selected = [s for s in selected if s.parent_labware == labware_name.lower()]
            if wells is not None:
                names = set(self._split_well_names(labware_name, wells))
                selected = [s for s in selected if s.parent_well in names]
        if channel_type is not None:
            channel_type = normalize_channel_type(channel_type)
            selected = [s for s in selected if s.channel_type == channel_type]
        return _remove_sites(self, selected, consolidate_volumes=consolidate_volumes)

    def get_split_wells(self, labware_name: str | None = None) -> list[SplitWellSite]:
        """The wells currently split, optionally only those of *labware_name*."""
        sites = list(vars(self).get("_split_wells", {}).values())
        if labware_name:
            sites = [s for s in sites if s.parent_labware == labware_name.lower()]
        return sites

    def _split_well_names(self, labware_name: str, wells: str | list[str] | None) -> list[str]:
        if wells is None:
            selector = labware_name
        elif isinstance(wells, str):
            selector = f"{labware_name}@{wells}"
        else:
            selector = f"{labware_name}@{','.join(wells)}"
        names: list[str] = []
        for position in normalize_positions(selector, get_spec=self.get_labware_spec):
            well = position.well.upper()
            if well not in names:
                names.append(well)
        return names


__all__ = [
    "SplitWellCommandsMixin",
    "SplitWellRequest",
    "SplitWellSite",
    "clear_split_wells",
    "forget_split_wells",
    "hold_split_wells",
    "release_held_split_wells",
    "route_split_wells",
    "split_labware_id",
    "split_wells_suspended",
]
