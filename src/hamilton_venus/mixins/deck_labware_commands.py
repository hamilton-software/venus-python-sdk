"""Deck labware placement methods for StarClient (Deck Layout category).

IMPORTANT -- labware id casing: every ``labware_id``/``plate_id``/``lid_id``/
``tip_pool`` accepted below is stored by VENUS lower-cased, regardless of the case
it was supplied in (``add_reservoir(..., labware_id="Trough1")`` is echoed back by
VENUS, and by every later SDK event/response that names it, as ``"trough1"``).
Code that compares an id it typed here against one read back later (a tracking
event, ``get_labware_spec``/``get_added_plates``/``get_added_carriers``/
``get_added_tip_racks``/``get_added_reservoirs``, a dict cache keyed by labware
id) must account for that -- normalize both sides before comparing rather than
assuming the original casing survives the round trip. See
``hamilton_venus.models.position``'s module docstring for the same note as it
applies to the ``Labware@expression`` positions selector DSL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from hamilton_venus.mixins.split_well_commands import forget_split_wells, split_wells_suspended
from hamilton_venus.models import (
    Add1mLCoreGripParameters,
    AddLiddedPlateResponse,
    AddQCGParameters,
    CommandResponse,
    LayoutAddCarrierParameters,
    LayoutAddCarrierToSiteParameters,
    LayoutAddLabwareResponse,
    LayoutAddLiddedPlateParameters,
    LayoutAddLiquidWasteParameters,
    LayoutAddNTRParameters,
    LayoutAddNTRResponse,
    LayoutAddPlateParameters,
    LayoutAddTipBoxResponse,
    LayoutAddTipRackParameters,
    LayoutAddTipRackResponse,
    LayoutAddTipSupportParameters,
    LayoutAddTransportSiteParameters,
    LayoutAddTransportSiteResponse,
    LayoutAddTransportToolResponse,
    LayoutAddTubesToCarrierParameters,
    LayoutAddTubesToCarrierResponse,
    LayoutMoveCarrierParameters,
    LayoutMoveCarrierResponse,
    LayoutRemoveLabwareParameters,
    LayoutRemoveLabwareResponse,
    LayoutRemoveTransportToolResponse,
    LayoutShiftLabwareParameters,
    LayoutShiftLabwareResponse,
    LayoutTiltLabwareParameters,
    LayoutTiltLabwareResponse,
    RemoveTransportToolParameters,
    TiltWellDeltaInput,
    TubePositionInput,
)
from hamilton_venus.models.enums import CoreGripType, InstrumentType, QCGType, TiltPivotPoint, TiltWellPosition
from hamilton_venus.tilt_clearance import (
    DEFAULT_HIGH_WALL_MARGIN_MM,
    DEFAULT_WALL_MARGIN_MM,
    TipClearance,
    TipProfile,
)
from hamilton_venus.tilt_geometry import (
    MAX_MEASURED_TILT_DEG,
    TiltSettings,
    compute_tilt_well_deltas,
    validate_tilt_degrees,
    well_aim_x_shift,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)


def tube_carrier_z_offset(definition: dict[str, Any]) -> float:
    """Where a sample tube carrier's own tubes sit: the height of their bottom above the
    carrier base (the definition's firstContainerCenter.z, typically 10 mm). 0 when the
    definition has none."""
    for grid in (definition.get("containerGrids") or {}).values():
        z = ((grid or {}).get("firstContainerCenter") or {}).get("z")
        if isinstance(z, (int, float)):
            return float(z)
    return 0.0



_R = TypeVar("_R", bound=CommandResponse)


def _typed(model: type[_R], response: CommandResponse) -> _R:
    """The same response with its returnParameters as the typed model (the wire payload is unchanged)."""
    return model.model_validate(response.model_dump(by_alias=True))


class DeckLabwareCommandsMixin:
    """Mixin providing deck labware placement and management commands."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    def add_carrier(
        self,
        labware_definition: str,
        left_track: int,
        labware_id: str | None = None,
    ) -> LayoutAddLabwareResponse:
        """Add a carrier definition to the active deck layout."""
        parameters = LayoutAddCarrierParameters(
            labware_name=labware_id,
            labware_definition=labware_definition,
            left_track=left_track,
        )
        return _typed(LayoutAddLabwareResponse, self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addCarrier",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        ))

    def add_carrier_to_site(
        self,
        labware_definition: str,
        carrier_id: str,
        site: str,
        labware_id: str | None = None,
    ) -> LayoutAddLabwareResponse:
        """Add a carrier definition to a specific site on an existing carrier."""
        parameters = LayoutAddCarrierToSiteParameters(
            labware_name=labware_id,
            labware_definition=labware_definition,
            carrier=carrier_id,
            site=site,
        )
        return _typed(LayoutAddLabwareResponse, self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addCarrierToSite",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        ))

    def add_tube_carrier(
        self,
        labware_definition: str,
        left_track: int,
        labware_id: str | None = None,
    ) -> LayoutAddLabwareResponse:
        """Add a sample tube carrier definition to the active deck layout.

        The carrier comes with its tubes already loaded (its definition is a rack of tube
        positions, e.g. "Sample carrier with 24 positions with preloaded 15x100 tubes"); nothing
        else has to be added before pipetting. Address a tube as ``"<carrier>@<position>"``
        (``"Tubes@1"`` .. ``"Tubes@24"``). ``get_labware_coordinates(carrier)`` lists every
        position and ``get_labware_spec(carrier)`` its layout. The site queries
        (get_labware_on_carrier, get_occupied_carrier_sites, get_top_labware) are for carriers
        with sites and return nothing for a tube carrier. Use ``add_tubes_to_carrier`` only to put
        a different tube type in some positions.
        """
        parameters = LayoutAddCarrierParameters(
            labware_name=labware_id,
            labware_definition=labware_definition,
            left_track=left_track,
        )
        return _typed(LayoutAddLabwareResponse, self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addSampleTubeCarrier",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        ))

    def add_tubes_to_carrier(
        self,
        labware_name: str,
        positions: list[dict[str, Any] | TubePositionInput],
    ) -> LayoutAddTubesToCarrierResponse:
        """Replace the tubes in some positions of a sample tube carrier with another tube type,
        and return their absolute coordinates. Not needed for the carrier's own tubes: a tube
        carrier comes with them loaded (see ``add_tube_carrier``).

        Args:
            labware_name: Name of the sample tube carrier on the deck.
            positions: List of tube placements. Each entry may be a TubePositionInput
                or a dict with keys ``position`` (carrier slot, e.g. ``"1"``),
                ``tube`` (tube labware definition filename from the SDK's
                ``Labware/Tubes/`` directory, e.g. ``"Tub_17x75_FlipTop_A00"``),
                and optional ``xOffset``/``yOffset``/``zOffset`` in mm.
                ``zOffset`` -- the height of the tube's bottom above the carrier base, the
                offset that matters most -- defaults to where the carrier's own tubes sit
                (its definition's first container height, typically 10 mm, which accounts
                for the carrier's base). Pass it only to put tubes higher or lower than that,
                as the full height (e.g. 15 to raise them 5 mm on a 10 mm carrier); 0 would
                put them on the carrier base.

        Returns:
            LayoutAddTubesToCarrierResponse with each tube's resulting x, y, z.
        """
        normalized = [
            p if isinstance(p, TubePositionInput) else TubePositionInput.model_validate(p)
            for p in positions
        ]
        if any(p.z_offset is None for p in normalized):
            definition = self.labware_get_params_from_id(labware_name).return_parameters.definition  # type: ignore[attr-defined]
            carrier_z = tube_carrier_z_offset(definition)
            normalized = [
                p if p.z_offset is not None else p.model_copy(update={"z_offset": carrier_z})
                for p in normalized
            ]
        parameters = LayoutAddTubesToCarrierParameters(
            labware_name=labware_name,
            positions=normalized,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addTubesToCarrier",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return LayoutAddTubesToCarrierResponse.model_validate(response.model_dump(by_alias=True))


    def add_tip_rack(
        self,
        labware_definition: str,
        carrier_id: str,
        site: str,
        tip_pool: str | None = None,
        labware_id: str | None = None,
    ) -> LayoutAddTipRackResponse:
        """Add a tip rack to a carrier site in the active layout.

        If ``tip_pool``/``labware_id`` are omitted, VENUS assigns names
        automatically; read them back from the response's return_parameters.
        Either way, VENUS stores (and reports back) the name lower-cased -- see
        this module's docstring.
        """
        parameters = LayoutAddTipRackParameters(
            tip_pool=tip_pool,
            labware_definition=labware_definition,
            carrier=carrier_id,
            site=site,
            labware_name=labware_id,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addTipRack",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return LayoutAddTipRackResponse.model_validate(response.model_dump(by_alias=True))

    def add_tip_box(
        self,
        labware_definition: str,
        carrier_id: str,
        site: str,
        tip_pool: str | None = None,
        labware_id: str | None = None,
    ) -> LayoutAddTipBoxResponse:
        """Add a tip box to a carrier site in the active layout.

        If ``tip_pool``/``labware_id`` are omitted, VENUS assigns names
        automatically; read them back from the response's return_parameters.
        """
        parameters = LayoutAddTipRackParameters(
            tip_pool=tip_pool,
            labware_definition=labware_definition,
            carrier=carrier_id,
            site=site,
            labware_name=labware_id,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addTipBox",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return LayoutAddTipBoxResponse.model_validate(response.model_dump(by_alias=True))

    def move_carrier(
        self, labware_name: str, left_track: int, site: str = ""
    ) -> LayoutMoveCarrierResponse:
        """Move a loaded carrier to a new deck track/site location."""
        parameters = LayoutMoveCarrierParameters(
            labware_name=labware_name,
            left_track=left_track,
            site=site,
        )
        # Split racks sit on the deck, not the carrier: rebuild them all after the move.
        with split_wells_suspended(self, None):
            response = self._run(
                self._connected_instrument.venus.send_command(
                    category="Deck Layout",
                    action_name="labware.moveCarrier",
                    parameters=parameters.model_dump(by_alias=True),
                )
            )
        return LayoutMoveCarrierResponse.model_validate(response.model_dump(by_alias=True))

    def add_ntr(
        self,
        labware_definition: str,
        carrier_id: str,
        site: str,
        stack: int,
        tip_pool: str | None = None,
        labware_id: str | None = None,
    ) -> LayoutAddNTRResponse:
        """Add a nested tip rack (NTR) to the active deck layout.

        Adds ``stack`` racks, one on another, and returns their names bottom to
        top in ``labware_name``. With a ``labware_id`` they are named from it with
        a counter suffix (``"NamedNTR"`` -> ``namedntr_0001``, ``namedntr_0002``, ...).
        """
        parameters = LayoutAddNTRParameters(
            tip_pool=tip_pool,
            labware_definition=labware_definition,
            carrier=carrier_id,
            site=site,
            stack=stack,
            labware_name=labware_id,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addNTR",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return LayoutAddNTRResponse.model_validate(response.model_dump(by_alias=True))

    def add_transport_site(
        self,
        site_name: str,
        x_center: float,
        y_center: float,
        z_bottom: float,
        angle_index: int,
    ) -> LayoutAddTransportSiteResponse:
        """Add a transport site definition to the active deck layout."""
        parameters = LayoutAddTransportSiteParameters(
            site_name=site_name,
            x_center=x_center,
            y_center=y_center,
            z_bottom=z_bottom,
            angle_index=angle_index,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addTransportSite",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return LayoutAddTransportSiteResponse.model_validate(response.model_dump(by_alias=True))


    def add_plate(
        self,
        labware_definition: str,
        carrier_id: str,
        site: str,
        plate_id: str | None = None,
    ) -> LayoutAddLabwareResponse:
        """Add a plate to a carrier site in the active layout."""
        parameters = LayoutAddPlateParameters(
            labware_name=plate_id,
            labware_definition=labware_definition,
            carrier=carrier_id,
            site=site,
        )
        return _typed(LayoutAddLabwareResponse, self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addPlate",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        ))

    def add_lidded_plate(
        self,
        labware_definition: str,
        carrier_id: str,
        site: str,
        plate_id: str | None = None,
        lid_definition: str = "Nunc_Lid",
    ) -> AddLiddedPlateResponse:
        """Add a lidded plate to a carrier site and return plate and lid names.

        VENUS requires ``lidDefinition`` for ``labware.addLiddedPlate``. The
        default ``Nunc_Lid`` keeps existing call sites working for Nunc plates.
        """
        parameters = LayoutAddLiddedPlateParameters(
            labware_name=plate_id,
            labware_definition=labware_definition,
            lid_definition=lid_definition,
            carrier=carrier_id,
            site=site,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addLiddedPlate",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return AddLiddedPlateResponse.model_validate(response.model_dump(by_alias=True))

    def add_lid(
        self,
        labware_definition: str,
        carrier_id: str,
        site: str,
        lid_id: str | None = None,
    ) -> LayoutAddLabwareResponse:
        """Add a lid to a carrier site in the active layout."""
        parameters = LayoutAddPlateParameters(
            labware_name=lid_id,
            labware_definition=labware_definition,
            carrier=carrier_id,
            site=site,
        )
        return _typed(LayoutAddLabwareResponse, self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addLid",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        ))


    def add_reservoir(
        self,
        labware_definition: str,
        carrier_id: str,
        site: str,
        labware_id: str | None = None,
    ) -> LayoutAddLabwareResponse:
        """Add a reservoir to a carrier site in the active deck layout."""
        parameters = LayoutAddPlateParameters(
            labware_name=labware_id,
            labware_definition=labware_definition,
            carrier=carrier_id,
            site=site,
        )
        return _typed(LayoutAddLabwareResponse, self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addReservoir",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        ))

    def add_tip_support(
        self,
        carrier_id: str,
        site: str,
    ) -> LayoutAddLabwareResponse:
        """Add a tip support to a carrier site in the active layout."""
        parameters = LayoutAddTipSupportParameters(
            carrier=carrier_id,
            site=site,
        )
        return _typed(LayoutAddLabwareResponse, self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addTipSupport",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        ))

    def remove_labware(self, labware_name: str) -> LayoutRemoveLabwareResponse:
        """Remove the specified labware from the active deck layout.

        Split wells (``split_wells``) of the labware, or of labware on a removed
        carrier, are removed with it.
        """
        forget_split_wells(self, [labware_name, *self._labware_on_removed_carrier(labware_name)])
        parameters = LayoutRemoveLabwareParameters(labware_name=labware_name)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.removeLabware",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        self._tilted_labware_state().pop(labware_name.lower(), None)
        vars(self).get("_tilt_settings", {}).pop(labware_name.lower(), None)
        return _typed(LayoutRemoveLabwareResponse, response)

    def _labware_on_removed_carrier(self, labware_name: str) -> list[str]:
        """Split-well parents on *labware_name* if it is a carrier (only asked while any are split)."""
        state = vars(self).get("_split_wells")
        if not state or labware_name.lower() in {site.parent_labware for site in state.values()}:
            return []
        get_labware_on_carrier = getattr(self, "get_labware_on_carrier", None)
        if get_labware_on_carrier is None:
            return []
        try:
            on_carrier = get_labware_on_carrier(labware_name).return_parameters.labware
        except Exception:  # not a carrier, or the query is unavailable
            return []
        return [item.labware_name for item in on_carrier]

    def add_1ml_core_grip(
        self,
        grip_type: CoreGripType = CoreGripType.STANDARD,
    ) -> LayoutAddTransportToolResponse:
        """Add a 1 mL CO-RE grip tool to the layout."""
        parameters = Add1mLCoreGripParameters(type=grip_type)
        return _typed(LayoutAddTransportToolResponse, self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.add1mLCoreGrip",
                parameters=parameters.model_dump(by_alias=True),
            )
        ))

    def add_5ml_core_grip(self) -> LayoutAddTransportToolResponse:
        """Add a 5 mL CO-RE grip tool to the layout."""
        return _typed(LayoutAddTransportToolResponse, self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.add5mLCoreGrip",
            )
        ))

    def add_qcg(
        self,
        qcg_type: QCGType = QCGType.QCG,
        track: int | None = None,
    ) -> LayoutAddTransportToolResponse:
        """Add a QCG (Quad CO-RE Grip) tool to the layout.

        On a Vantage, *track* places the QCG (it occupies 2 tracks) somewhere other
        than its default location; omit it to load in the default location. *track*
        is not supported on a STAR.
        """
        if track is not None and getattr(self, "_instrument_type", InstrumentType.STAR) == InstrumentType.STAR:
            raise ValueError("add_qcg track is only supported for Vantage instrument type")

        parameters = AddQCGParameters(type=qcg_type, track=track)
        return _typed(LayoutAddTransportToolResponse, self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addQCG",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        ))

    def remove_transport_tool(self, tool_id: int) -> LayoutRemoveTransportToolResponse:
        """Remove a transport tool from the layout by ID."""
        parameters = RemoveTransportToolParameters(tool_id=tool_id)
        return _typed(LayoutRemoveTransportToolResponse, self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.removeTransportTool",
                parameters=parameters.model_dump(by_alias=True),
            )
        ))

    def add_channel_liquid_waste(self) -> LayoutAddLabwareResponse:
        """Add a channel liquid waste container to the active deck layout."""
        return _typed(LayoutAddLabwareResponse, self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addChannelLiquidWaste",
            )
        ))

    def add_liquid_waste(self, track: int | None = None) -> CommandResponse:
        """Add a liquid waste container to the active deck layout (Vantage only)."""
        if getattr(self, "_instrument_type", InstrumentType.STAR) == InstrumentType.STAR:
            raise ValueError("add_liquid_waste is only supported for Vantage instrument type")

        parameters = LayoutAddLiquidWasteParameters(track=track)
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.addLiquidWaste",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    def shift_labware(
        self,
        labware_name: str,
        relative_x: float = 0.0,
        relative_y: float = 0.0,
        relative_z: float = 0.0,
        relative_angle: float = 0.0,
    ) -> LayoutShiftLabwareResponse:
        """Shift labware position by relative offsets in the deck layout.

        Applies relative X/Y/Z/angle offsets to a labware item's current position
        without physically moving it via a gripper. Returns the resulting absolute
        coordinates after the shift.

        Args:
            labware_name: Name of the labware to shift.
            relative_x: Offset in the X direction (mm).
            relative_y: Offset in the Y direction (mm).
            relative_z: Offset in the Z direction (mm).
            relative_angle: Rotational offset (degrees).

        Returns:
            LayoutShiftLabwareResponse with the resulting absolute x, y, z, and angle.
        """
        parameters = LayoutShiftLabwareParameters(
            labware_name=labware_name,
            relative_x=relative_x,
            relative_y=relative_y,
            relative_z=relative_z,
            relative_angle=relative_angle,
        )
        with split_wells_suspended(self, [labware_name]):
            response = self._run(
                self._connected_instrument.venus.send_command(
                    category="Deck Layout",
                    action_name="labware.shiftLabware",
                    parameters=parameters.model_dump(by_alias=True),
                )
            )
        return LayoutShiftLabwareResponse.model_validate(response.model_dump(by_alias=True))

    def tilt_labware(
        self,
        labware_name: str,
        tilt_degrees: float,
        pivot_point: TiltPivotPoint = TiltPivotPoint.LEFT_EDGE,
        *,
        pivot_x_offset_mm: float = 0.0,
        pivot_z_offset_mm: float = 0.0,
        well_position: TiltWellPosition = TiltWellPosition.CENTER,
        measured_tilt_degrees: float | None = None,
        tip_end_height_mm: float = 0.0,
        wall_margin_mm: float = DEFAULT_WALL_MARGIN_MM,
        high_wall_margin_mm: float = DEFAULT_HIGH_WALL_MARGIN_MM,
        tip_profile: TipProfile | None = None,
    ) -> LayoutTiltLabwareResponse:
        """Offset every well of a plate in the deck layout to match a tilt.

        Computes each well's X / Z offset from the plate's labware definition (see
        :mod:`hamilton_venus.tilt_geometry`) and sends them to VENUS, which applies
        them to the existing labware item, so sample tracking is kept. Offsets are
        always computed from the nominal well positions: calls do not compound, and
        ``tilt_degrees=0`` returns the plate to normal.

        While a plate is tilted (``tilt_degrees > 0``) the transport commands refuse
        to move it (:class:`~hamilton_venus.exceptions.LabwareTiltedError`). Split wells
        (``split_wells``) of the plate are rebuilt for the new angle, aim and margins.

        This only changes the deck layout; it does not move the tilt hardware.

        Args:
            labware_name: Name of the plate on the deck. Only ``plate`` labware can be tilted.
            tilt_degrees: The angle the tilt module is commanded to, 0 (flat) to 10.
                Fractions are accepted. Positive raises the right side.
            pivot_point: Hinge line: the plate's left edge or the middle of its footprint.
            pivot_x_offset_mm: Measured hinge X offset from the pivot point; positive toward -X.
            pivot_z_offset_mm: Measured hinge Z offset below the labware base; positive toward -Z.
            well_position: Where in each well to aim one tip: the centre, or as close
                to the low wall (``DEEPEST_POINT``) or the high wall (``HIGHEST_POINT``)
                as the tip fits with the margins below. Ignored at 0 degrees.
            measured_tilt_degrees: The angle the plate really sits at, if it differs
                from the commanded one (e.g. 10.8 for a module commanded to 10; up to
                15). The offsets are computed for it; VENUS still gets ``tilt_degrees``.
                See :func:`hamilton_venus.tilt_calibration.fit_tilt_hinge`.
            tip_end_height_mm: How far above the well floor the tip end will be (the
                aspirate / dispense fixed height). 0 is the most conservative; a raised
                tip end lets the aim come a little closer to the wall. Re-tilt if it
                changes.
            wall_margin_mm: Gap kept between the tip and the low wall.
            high_wall_margin_mm: Gap kept between the tip and the high wall, which
                leans in over the tip, so errors reach it first.
            tip_profile: The tip's shape. Defaults to a 1000 uL CO-RE tip; pass the
                real tip's profile for smaller tips (e.g. 300 uL) or narrow wells.
                ``split_wells`` reuses it unless it is given its own.

        Raises:
            ValueError: If an angle or margin is out of range, the labware is not a
                single-grid plate, or a ``DEEPEST_POINT`` / ``HIGHEST_POINT`` aim has no
                room for a single tip (the message gives the largest angle that fits).
        """
        tilt_degrees = validate_tilt_degrees(tilt_degrees)
        if measured_tilt_degrees is None:
            angle = tilt_degrees
        elif tilt_degrees == 0:
            raise ValueError("measured_tilt_degrees needs tilt_degrees > 0; tilt_degrees=0 returns the plate to flat")
        else:
            angle = validate_tilt_degrees(
                measured_tilt_degrees, maximum=MAX_MEASURED_TILT_DEG, name="measured_tilt_degrees"
            )
        if tilt_degrees == 0:
            well_position = TiltWellPosition.CENTER
        clearance = TipClearance(
            tip_profile or TipClearance().tip, tip_end_height_mm, wall_margin_mm, high_wall_margin_mm
        )
        definition =self.labware_get_params_from_id(labware_name).return_parameters.definition  # type: ignore[attr-defined]
        deltas = compute_tilt_well_deltas(
            definition,
            angle,
            pivot_point,
            pivot_x_offset_mm=pivot_x_offset_mm,
            pivot_z_offset_mm=pivot_z_offset_mm,
            well_position=well_position,
            clearance=clearance,
        )
        settings = TiltSettings(
            tilt_degrees=tilt_degrees,
            angle_degrees=angle,
            well_position=TiltWellPosition(well_position),
            aim_x_shift=well_aim_x_shift(definition, angle, well_position, clearance),
            clearance=clearance,
            tip_profile=tip_profile,
        )
        parameters = LayoutTiltLabwareParameters(
            labware_name=labware_name,
            tilt_degrees=tilt_degrees,
            pivot_point=pivot_point,
            pivot_x_offset=pivot_x_offset_mm,
            pivot_z_offset=pivot_z_offset_mm,
            well_position=well_position,
            wells=[TiltWellDeltaInput(well=d.well, delta_x=d.dx, delta_y=d.dy, delta_z=d.dz) for d in deltas],
        )
        with split_wells_suspended(self, [labware_name]):
            response = self._run(
                self._connected_instrument.venus.send_command(
                    category="Deck Layout",
                    action_name="labware.tiltLabware",
                    parameters=parameters.model_dump(by_alias=True),
                )
            )
            # Recorded before the split wells are rebuilt, which size themselves from it.
            tilted = self._tilted_labware_state()
            all_settings = vars(self).setdefault("_tilt_settings", {})
            if tilt_degrees:
                tilted[labware_name.lower()] = tilt_degrees
                all_settings[labware_name.lower()] = settings
            else:
                tilted.pop(labware_name.lower(), None)
                all_settings.pop(labware_name.lower(), None)
        return LayoutTiltLabwareResponse.model_validate(response.model_dump(by_alias=True))

    def get_tilt_settings(self, labware_name: str) -> TiltSettings | None:
        """How ``tilt_labware`` last tilted *labware_name* (angle, aim, tip and margins), or ``None`` if flat."""
        return vars(self).get("_tilt_settings", {}).get(labware_name.lower())

    def is_labware_tilted(self, labware_name: str) -> bool:
        """Whether ``tilt_labware`` has left *labware_name* tilted (case-insensitive)."""
        return labware_name.lower() in self._tilted_labware_state()

    def get_tilted_labware(self) -> dict[str, float]:
        """Labware currently tilted by ``tilt_labware``: lower-cased name -> commanded degrees."""
        return dict(self._tilted_labware_state())

    def _tilted_labware_state(self) -> dict[str, float]:
        # Lower-cased keys: VENUS stores labware ids lower-cased (see module docstring).
        return vars(self).setdefault("_tilted_labware", {})

