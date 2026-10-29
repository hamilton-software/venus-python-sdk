"""Typed command parameter and response models for wire-level command handling."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeAlias

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from hamilton_venus.models.commands import CommandResponse
from hamilton_venus.models.enums import (
    AspirateMode,
    Axis,
    CapacitiveLLD,
    CMOrientation,
    CoordinateMode,
    CoreGripType,
    DispenseMode,
    EjectMode,
    GripInverse,
    InteriorLightState,
    LabwareType,
    LightColor,
    MPH96Pattern,
    MPH96PreAirAspirate,
    MphPickupMode,
    MphPickupSide,
    PipArmSpeed,
    PlaceRotation,
    PressureLLD,
    QCGType,
    ScanPositions,
    TeachingDirection,
    TeachingMeasureStatus,
    TiltPivotPoint,
    TiltWellPosition,
    TrackedLabwareType,
)
from hamilton_venus.models.liquid_handling_settings import TadmSettings
from hamilton_venus.models.position import Position

if TYPE_CHECKING:
    from hamilton_venus.models.labware_definition import LabwareDefinition
    from hamilton_venus.models.position import LabwareLayoutSpec

MPHSelection: TypeAlias = list[str] | list[int]


class _WireModel(BaseModel):
    """Base model for command payloads serialized onto the wire."""

    model_config = ConfigDict(populate_by_name=True, use_enum_values=True, extra="forbid")


class _ResponseModel(BaseModel):
    """Base model for typed ``returnParameters`` payloads."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class EmptyReturnParameters(_ResponseModel):
    pass


class InstrumentConnectParameters(_WireModel):
    initialize: bool = True


class PipArmMoveToParameters(_WireModel):
    value: float
    mode: CoordinateMode | None = None
    arm_id: int = Field(1, alias="armId")
    speed: PipArmSpeed | None = None
    safety_bypass_token: str | None = Field(None, alias="safetyBypassToken")


class AutoloadMoveParameters(_WireModel):
    track_id: int = Field(..., alias="trackId")


def _serialize_scan_positions(value: Any) -> Any:
    """VENUS's wire format for scanPositions is always a string -- ``"?"``/``"*"``/``""``
    for the ``ScanPositions`` enum cases (already strings via ``use_enum_values``), or a
    comma-joined list of 1-based position indices like ``"1,2,3"`` for explicit positions.
    A raw JSON array (``[1, 2, 3]``) is not a format VENUS accepts here -- it's silently
    ignored/misinterpreted rather than raising, so this must convert before the wire, not
    just rely on the Python-side type hint of ``list[int]`` looking reasonable.
    """
    if isinstance(value, list):
        return ",".join(str(p) for p in value)
    return value


class AutoloadLoadCarrierByIdParameters(_WireModel):
    carrier_id: str = Field(..., alias="carrierId")
    scan_positions: ScanPositions | list[int] | None = Field(None, alias="scanPositions")

    @field_serializer("scan_positions")
    def _serialize_scan_positions_field(self, value: Any) -> Any:
        return _serialize_scan_positions(value)


class AutoloadLoadCarrierByTrackParameters(_WireModel):
    track_id: int = Field(..., alias="trackId")
    scan_positions: ScanPositions | list[int] | None = Field(None, alias="scanPositions")

    @field_serializer("scan_positions")
    def _serialize_scan_positions_field(self, value: Any) -> Any:
        return _serialize_scan_positions(value)


class AutoloadUnloadCarrierByIdParameters(_WireModel):
    carrier_id: str = Field(..., alias="carrierId")


class AutoloadUnloadCarrierByTrackParameters(_WireModel):
    track_id: int = Field(..., alias="trackId")


class AutoloadBarcodeReturn(_ResponseModel):
    """One entry of an ``autoload.loadCarrierBy*`` call's ``barcodeReturns`` list.

    The list always holds one entry per barcode position registered to the
    carrier labware (its ``MlStarCarCountOfBCPos`` property), in position
    order -- e.g. 5 for a 5-site plate carrier, 32 for a 32-position tube
    carrier. ``position`` is the 1-based carrier position (the site of a site
    carrier; a tube rack's own well numbering for a sample tube rack), and
    is empty, like ``barcode``, for a position not included in
    ``scan_positions``. ``barcode`` is also empty when a scanned position had
    nothing to read or the read failed.
    """

    barcode: str = ""
    position: str = ""
    barcode_mask: str = Field("", alias="barcodeMask")


class AutoloadLoadCarrierReturnParameters(_ResponseModel):
    track: int = 0
    carrier_barcode: str = Field("", alias="carrierBarcode")
    carrier_labware_id: str = Field("", alias="carrierLabwareID")
    barcode_returns: list[AutoloadBarcodeReturn] = Field(default_factory=list, alias="barcodeReturns")


class AutoloadLoadCarrierResponse(CommandResponse):
    return_parameters: AutoloadLoadCarrierReturnParameters = Field(
        default_factory=AutoloadLoadCarrierReturnParameters,
        alias="returnParameters",
    )


class TrackIdParameters(_WireModel):
    track_id: int = Field(..., alias="trackId")


class ArmIdParameters(_WireModel):
    arm_id: int = Field(1, alias="armId")


class LayoutAddCarrierParameters(_WireModel):
    labware_name: str | None = Field(None, alias="labwareName")
    labware_definition: str = Field(..., alias="labwareDefinition")
    left_track: int = Field(..., alias="leftTrack")


class LayoutAddCarrierToSiteParameters(_WireModel):
    labware_name: str | None = Field(None, alias="labwareName")
    labware_definition: str = Field(..., alias="labwareDefinition")
    carrier: str
    site: str


class LayoutAddTipRackParameters(_WireModel):
    tip_pool: str | None = Field(None, alias="tipPool")
    labware_definition: str = Field(..., alias="labwareDefinition")
    carrier: str
    site: str
    labware_name: str | None = Field(None, alias="labwareName")


class LayoutAddPlateParameters(_WireModel):
    labware_name: str | None = Field(None, alias="labwareName")
    labware_definition: str = Field(..., alias="labwareDefinition")
    carrier: str
    site: str


class LayoutAddLiddedPlateParameters(_WireModel):
    labware_name: str | None = Field(None, alias="labwareName")
    labware_definition: str = Field(..., alias="labwareDefinition")
    lid_definition: str = Field(..., alias="lidDefinition")
    carrier: str
    site: str


class LayoutAddTipSupportParameters(_WireModel):
    carrier: str
    site: str


class LayoutAddLiquidWasteParameters(_WireModel):
    track: int | None = Field(None, alias="track")

class TipPoolParameters(_WireModel):
    tip_pool: str = Field(..., alias="tipPool")


class TipRackState(_WireModel):
    count: int
    positions: list[str]


class SetTipCounterParameters(_WireModel):
    tip_pool: str = Field(..., alias="tipPool")
    available_tips: list[dict[str, TipRackState]] = Field(..., alias="availableTips")


class ShowTipCountersParameters(_WireModel):
    tip_pools: list[str] | None = Field(None, alias="tipPools")


class LayoutCarrierSiteParameters(_WireModel):
    carrier: str
    site: str


class LayoutTopLabwareParameters(_WireModel):
    carrier_id: str = Field(..., alias="carrierId")
    site: str


class LayoutCarrierParameters(_WireModel):
    carrier: str


class LayoutRemoveLabwareParameters(_WireModel):
    labware_name: str = Field(..., alias="labwareName")


class LayoutMoveCarrierParameters(_WireModel):
    labware_name: str = Field(..., alias="labwareName")
    left_track: int = Field(..., alias="leftTrack")
    site: str = ""


class LayoutAddNTRParameters(_WireModel):
    tip_pool: str | None = Field(None, alias="tipPool")
    labware_definition: str = Field(..., alias="labwareDefinition")
    carrier: str
    site: str
    stack: int
    labware_name: str | None = Field(None, alias="labwareName")


class LayoutAddTransportSiteParameters(_WireModel):
    site_name: str = Field(..., alias="siteName")
    x_center: float = Field(..., alias="xCenter")
    y_center: float = Field(..., alias="yCenter")
    z_bottom: float = Field(..., alias="zBottom")
    angle_index: int = Field(..., alias="angleIndex")


class ChannelDispenseOnTheFlyParameters(_WireModel):
    channels: list[int]
    labware_name: str = Field(..., alias="labwareName")
    volumes: float | list[float]
    labware_surface_distance: float = Field(..., alias="labwareSurfaceDistance")
    start_x_offset: float = Field(0.0, alias="startXOffset")
    x_speed: float = Field(0.0, alias="xSpeed")
    x_acceleration_distance: float = Field(8.0, alias="xAccelerationDistance")
    dispense_direction: int = Field(0, alias="dispenseDirection")
    excluded_positions: list[str] = Field(default_factory=list, alias="excludedPositions")


class DeckImportParameters(_WireModel):
    path: str


class MPH96ClearTipSupportParameters(_WireModel):
    tip_pool: str = Field(..., alias="tipPool")


class StatusLightSetFrontLightParameters(_WireModel):
    color: LightColor
    blink: bool = False
    progress: int = 0


class InteriorLightColors(_WireModel):
    """Per-channel intensity values (0-100) for the interior light."""

    white: int = 0
    red: int = 0
    green: int = 0
    blue: int = 0


class StatusLightSetInteriorLightParameters(_WireModel):
    light_state: InteriorLightState = Field(..., alias="lightState")
    light_intensity: int | None = Field(None, alias="lightIntensity")
    blink_interval: int | None = Field(None, alias="blinkInterval")
    colors: InteriorLightColors | None = None


class FirmwareCommandParameters(_WireModel):
    command: str
    parameters: str = ""
    safety_bypass_token: str = Field(..., alias="safetyBypassToken")


class TransportHoldLidParameters(_WireModel):
    labware_name: str = Field(..., alias="labwareName")
    grip_height_from_top: float = Field(..., alias="gripHeightFromTop")
    grip_width: float | None = Field(None, alias="gripWidth")
    grip_open: float | None = Field(None, alias="gripOpen")
    tool_id: int | None = Field(None, alias="toolId")
    front_channel: int | None = Field(None, alias="frontChannel")
    grip_force: int | None = Field(None, alias="gripForce")
    check_presence: dict[str, bool] | None = Field(None, alias="checkPresence")
    grip_close_speed: float | None = Field(None, alias="gripCloseSpeed")
    grip_z_speed: float | None = Field(None, alias="gripZSpeed")
    x_acceleration: int | None = Field(None, alias="xAcceleration")


class IswapMoveLabwareParameters(_WireModel):
    labware_name: str = Field(..., alias="labwareName")
    carrier: str
    site: str
    grip_height_above_bottom: float = Field(..., alias="gripHeightAboveBottom")
    grip_width: float | None = Field(None, alias="gripWidth")
    grip_open: float | None = Field(None, alias="gripOpen")
    grip_force: int | None = Field(None, alias="gripForce")
    tolerance: float | None = None
    grip_inverse: GripInverse | None = Field(None, alias="gripInverse")
    place_rotation: PlaceRotation | None = Field(None, alias="placeRotation")
    offset_grip: float | None = Field(None, alias="offsetGrip")


class IswapMoveToWasteParameters(_WireModel):
    labware_name: str = Field(..., alias="labwareName")
    grip_height_above_bottom: float = Field(..., alias="gripHeightAboveBottom")
    grip_width: float | None = Field(None, alias="gripWidth")
    grip_open: float | None = Field(None, alias="gripOpen")
    grip_force: int | None = Field(None, alias="gripForce")
    tolerance: float | None = None
    grip_inverse: GripInverse | None = Field(None, alias="gripInverse")
    offset_grip: float | None = Field(None, alias="offsetGrip")


class IswapPresentAndScanParameters(_WireModel):
    labware_name: str = Field(..., alias="labwareName")
    carrier: str
    site: str
    track: int
    grip_height_above_bottom: float = Field(..., alias="gripHeightAboveBottom")
    grip_width: float | None = Field(None, alias="gripWidth")
    grip_open: float | None = Field(None, alias="gripOpen")
    z_minimal_position: float = Field(..., alias="zMinimalPosition")
    grip_force: int | None = Field(None, alias="gripForce")
    tolerance: float | None = None
    grip_inverse: GripInverse | None = Field(None, alias="gripInverse")
    place_rotation: PlaceRotation | None = Field(None, alias="placeRotation")


class IswapComplexMovement(_WireModel):
    """iSWAP complex movement (a hotel get or put). Its presence in a get or put
    request is what switches complex movement on."""

    retract_distance: float = Field(..., alias="retractDistance")
    lift_height: float = Field(..., alias="liftHeight")
    orientation: CMOrientation


class IswapGetLabwareParameters(_WireModel):
    labware_name: str = Field(..., alias="labwareName")
    grip_height_above_bottom: float = Field(..., alias="gripHeightAboveBottom")
    grip_force: int | None = Field(None, alias="gripForce")
    grip_width: float | None = Field(None, alias="gripWidth")
    grip_open: float | None = Field(None, alias="gripOpen")
    tolerance: float | None = None
    grip_inverse: GripInverse | None = Field(None, alias="gripInverse")
    offset_grip: float | None = Field(None, alias="offsetGrip")
    complex_movement: IswapComplexMovement | None = Field(None, alias="complexMovement")


class IswapPutLabwareParameters(_WireModel):
    carrier: str
    site: str
    place_rotation: PlaceRotation | None = Field(None, alias="placeRotation")
    complex_movement: IswapComplexMovement | None = Field(None, alias="complexMovement")


class DeckNameParameters(_WireModel):
    name: str


class DeckLoadParameters(_WireModel):
    deck: str | None = None
    previous: bool = False


class DeckSaveParameters(_WireModel):
    name: str
    overwrite: bool = False


class DeckGetRackIdsFromDeckParameters(_WireModel):
    path: str
    carrier_filter: list[str] | None = Field(None, alias="carrierFilter")
    only_floating_racks: bool | None = Field(None, alias="onlyFloatingRacks")


class DeckImportRackAsSiteParameters(_WireModel):
    path: str
    carrier_filter: list[str] | None = Field(None, alias="carrierFilter")
    only_floating_racks: bool | None = Field(None, alias="onlyFloatingRacks")
    target_labware_name: str = Field(..., alias="targetLabwareName")
    site_name: str | None = Field(None, alias="siteName")


class LabwareDefinitionParameters(_WireModel):
    labware_definition: str = Field(..., alias="labwareDefinition")
    definition: dict[str, Any] = Field(..., alias="definition")


class LabwareDefinitionImportParameters(_WireModel):
    labware_definition: str | None = Field(None, alias="labwareDefinition")
    labware_path: str = Field(..., alias="labwarePath")
    labware_type: LabwareType = Field(..., alias="labwareType")


class LabwareNameParameters(_WireModel):
    labware_definition: str = Field(..., alias="labwareDefinition")


class LabwareParamsFromIdParameters(_WireModel):
    labware_name: str = Field(..., alias="labwareName")


class LabwareFilterParameters(_WireModel):
    filter: list[str] | None = None


class TipPickupParameters(_WireModel):
    channels: list[int]
    positions: list[Position] | None = None
    tip_pool: str | None = Field(None, alias="tipPool")
    optimized_pickup: bool | None = Field(None, alias="optimizedPickup")


class TipEjectParameters(_WireModel):
    channels: list[int] | None = None
    eject_mode: EjectMode = Field(EjectMode.WASTE, alias="ejectMode")
    positions: list[Position] | None = None
    tip_pool: str | None = Field(None, alias="tipPool")


class AspirateParameters(_WireModel):
    channels: list[int]
    positions: list[Position]
    volumes: float | list[float] = 100.0
    liquid_class: str | list[str] | None = Field(None, alias="liquidClass")
    aspirate_mode: AspirateMode | list[AspirateMode] = Field(AspirateMode.NORMAL, alias="aspirateMode")
    capacitive_lld: CapacitiveLLD | list[CapacitiveLLD] = Field(CapacitiveLLD.OFF, alias="capacitiveLLD")
    pressure_lld: PressureLLD | list[PressureLLD] = Field(PressureLLD.OFF, alias="pressureLLD")
    liquid_following: bool | list[bool] = Field(False, alias="liquidFollowing")
    tip_tracking_factor: float = Field(1.0, alias="tipTrackingFactor")
    submerge_depth: float | list[float] = Field(2.0, alias="submergeDepth")
    fixed_height: float | list[float] = Field(5.0, alias="fixedHeight")
    max_lld_difference: float | list[float] = Field(3.0, alias="maxLLdDifference")
    mix_cycles: int | list[int] = Field(0, alias="mixCycles")
    mix_position: float | list[float] = Field(0.0, alias="mixPosition")
    mix_volume: float | list[float] = Field(0.0, alias="mixVolume")
    air_transport_retract_dist: float | list[float] = Field(5.0, alias="airTransportRetractDist")
    touch_off: int | list[int] = Field(0, alias="touchOff")
    touch_off_height: float | list[float] = Field(1.0, alias="touchOffHeight")
    mad_enabled: bool | None = Field(None, alias="madEnabled")
    mad_threshold: int | None = Field(None, alias="madThreshold")
    adc: bool | None = Field(None, alias="ADC")


class DispenseChannelParameters(_WireModel):
    channel: int
    labware: str
    well: str
    volume: float = 100.0
    liquid_class: str | None = Field(None, alias="liquidClass")
    dispense_mode: DispenseMode = Field(DispenseMode.JET_EMPTY_TIP, alias="dispenseMode")
    liquid_following: bool = Field(False, alias="liquidFollowing")
    submerge_depth: float = Field(2.0, alias="submergeDepth")
    fixed_height: float = Field(5.0, alias="fixedHeight")
    mix_cycles: int = Field(0, alias="mixCycles")
    mix_position: float = Field(0.0, alias="mixPosition")
    mix_volume: float = Field(0.0, alias="mixVolume")
    air_transport_retract_dist: float = Field(5.0, alias="airTransportRetractDist")
    touch_off: int = Field(0, alias="touchOff")
    touch_off_height: float = Field(1.0, alias="touchOffHeight")


class DispenseParameters(_WireModel):
    channels: list[int]
    positions: list[Position]
    volumes: float | list[float] = 100.0
    dispense_mode: DispenseMode | list[DispenseMode] = Field(DispenseMode.JET_EMPTY_TIP, alias="dispenseMode")
    capacitive_lld: CapacitiveLLD | list[CapacitiveLLD] = Field(CapacitiveLLD.OFF, alias="capacitiveLLD")
    liquid_following: bool | list[bool] = Field(False, alias="liquidFollowing")
    tip_tracking_factor: float = Field(1.0, alias="tipTrackingFactor")
    submerge_depth: float | list[float] = Field(2.0, alias="submergeDepth")
    fixed_height: float | list[float] = Field(5.0, alias="fixedHeight")
    mix_cycles: int | list[int] = Field(0, alias="mixCycles")
    mix_position: float | list[float] = Field(0.0, alias="mixPosition")
    mix_volume: float | list[float] = Field(0.0, alias="mixVolume")
    air_transport_retract_dist: float | list[float] = Field(5.0, alias="airTransportRetractDist")
    touch_off: int | list[int] = Field(0, alias="touchOff")
    touch_off_height: float | list[float] = Field(1.0, alias="touchOffHeight")
    use_side_touch: bool = Field(False, alias="useSideTouch")
    adc: bool | None = Field(None, alias="ADC")


class ChannelMoveAxisParameters(_WireModel):
    channels: list[int] | int
    x: float | None = None
    y: float | list[float] | None = None
    z: float | list[float] | None = None
    safety_bypass_token: str | None = Field(None, alias="safetyBypassToken")


class DetectLiquidLevelParameters(_WireModel):
    channels: list[int]
    positions: list[Position]
    capacitive_lld: CapacitiveLLD | list[CapacitiveLLD] = Field(CapacitiveLLD.MAX, alias="capacitiveLLD")
    pressure_lld: PressureLLD | list[PressureLLD] = Field(PressureLLD.OFF, alias="pressureLLD")


class MagPipAspirateParameters(_WireModel):
    """Wire parameters for ``channels.MagPip.aspirate``.

    Identical to :class:`AspirateParameters` except the MagPip channels do not
    support ``tipTrackingFactor``, and an optional nested ``TADM`` object can be
    supplied.
    """

    channels: list[int]
    positions: list[Position]
    volumes: float | list[float] = 100.0
    liquid_class: str | list[str] | None = Field(None, alias="liquidClass")
    aspirate_mode: AspirateMode | list[AspirateMode] = Field(AspirateMode.NORMAL, alias="aspirateMode")
    capacitive_lld: CapacitiveLLD | list[CapacitiveLLD] = Field(CapacitiveLLD.OFF, alias="capacitiveLLD")
    pressure_lld: PressureLLD | list[PressureLLD] = Field(PressureLLD.OFF, alias="pressureLLD")
    liquid_following: bool | list[bool] = Field(False, alias="liquidFollowing")
    submerge_depth: float | list[float] = Field(2.0, alias="submergeDepth")
    fixed_height: float | list[float] = Field(5.0, alias="fixedHeight")
    max_lld_difference: float | list[float] = Field(3.0, alias="maxLLdDifference")
    mix_cycles: int | list[int] = Field(0, alias="mixCycles")
    mix_position: float | list[float] = Field(0.0, alias="mixPosition")
    mix_volume: float | list[float] = Field(0.0, alias="mixVolume")
    air_transport_retract_dist: float | list[float] = Field(5.0, alias="airTransportRetractDist")
    touch_off: int | list[int] = Field(0, alias="touchOff")
    touch_off_height: float | list[float] = Field(1.0, alias="touchOffHeight")
    mad_enabled: bool | None = Field(None, alias="madEnabled")
    mad_threshold: int | None = Field(None, alias="madThreshold")
    adc: bool | None = Field(None, alias="ADC")
    tadm: TadmSettings | None = Field(None, alias="TADM")


class MagPipDispenseParameters(_WireModel):
    """Wire parameters for ``channels.MagPip.dispense``.

    Identical to :class:`DispenseParameters` except the MagPip channels do not
    support ``tipTrackingFactor``, and an optional nested ``TADM`` object can be
    supplied.
    """

    channels: list[int]
    positions: list[Position]
    volumes: float | list[float] = 100.0
    dispense_mode: DispenseMode | list[DispenseMode] = Field(DispenseMode.JET_EMPTY_TIP, alias="dispenseMode")
    capacitive_lld: CapacitiveLLD | list[CapacitiveLLD] = Field(CapacitiveLLD.OFF, alias="capacitiveLLD")
    liquid_following: bool | list[bool] = Field(False, alias="liquidFollowing")
    submerge_depth: float | list[float] = Field(2.0, alias="submergeDepth")
    fixed_height: float | list[float] = Field(5.0, alias="fixedHeight")
    mix_cycles: int | list[int] = Field(0, alias="mixCycles")
    mix_position: float | list[float] = Field(0.0, alias="mixPosition")
    mix_volume: float | list[float] = Field(0.0, alias="mixVolume")
    air_transport_retract_dist: float | list[float] = Field(5.0, alias="airTransportRetractDist")
    touch_off: int | list[int] = Field(0, alias="touchOff")
    touch_off_height: float | list[float] = Field(1.0, alias="touchOffHeight")
    use_side_touch: bool = Field(False, alias="useSideTouch")
    adc: bool | None = Field(None, alias="ADC")
    tadm: TadmSettings | None = Field(None, alias="TADM")


class MagPipDispenseOnTheFlyParameters(_WireModel):
    """Wire parameters for ``channels.MagPip.dispenseOnTheFly``.

    Identical to :class:`ChannelDispenseOnTheFlyParameters` plus the optional
    ``ADC`` flag and a nested ``TADM`` object that the MagPip variant accepts.
    """

    channels: list[int]
    labware_name: str = Field(..., alias="labwareName")
    volumes: float | list[float]
    labware_surface_distance: float = Field(..., alias="labwareSurfaceDistance")
    start_x_offset: float = Field(0.0, alias="startXOffset")
    x_speed: float = Field(0.0, alias="xSpeed")
    x_acceleration_distance: float = Field(8.0, alias="xAccelerationDistance")
    dispense_direction: int = Field(0, alias="dispenseDirection")
    excluded_positions: list[str] = Field(default_factory=list, alias="excludedPositions")
    adc: bool | None = Field(None, alias="ADC")
    tadm: TadmSettings | None = Field(None, alias="TADM")


class MPH96TipPickupParameters(_WireModel):
    labware_id: str | None = Field(None, alias="labwareId")
    tip_pool: str | None = Field(None, alias="tipPool")
    pre_air_aspirate: MPH96PreAirAspirate = Field(MPH96PreAirAspirate.DISABLED, alias="preAirAspirate")
    pre_air_volume: float | None = Field(None, alias="preAirVolume")


class MPH96TipPickupPartialParameters(_WireModel):
    labware_id: str | None = Field(None, alias="labwareId")
    tip_pool: str | None = Field(None, alias="tipPool")
    mode: MphPickupMode
    count: int
    mph_pickup_side: MphPickupSide = Field(MphPickupSide.LEFT, alias="mphPickupSide")
    pre_air_aspirate: MPH96PreAirAspirate = Field(MPH96PreAirAspirate.DISABLED, alias="preAirAspirate")
    pre_air_volume: float | None = Field(None, alias="preAirVolume")


class MPH96LiquidHandlingParameters(_WireModel):
    labware_id: str = Field(..., alias="labwareName", validation_alias=AliasChoices("labwareName", "labwareId"))
    mph_pattern: MPHSelection | None = Field(
        None,
        alias="mphSelection",
        validation_alias=AliasChoices("mphSelection", "mphPattern"),
    )
    volume: float = 100.0
    liquid_class: str | None = Field(None, alias="liquidClass")
    aspirate_mode: AspirateMode | None = Field(None, alias="aspirateMode")
    dispense_mode: DispenseMode | None = Field(None, alias="dispenseMode")
    capacitive_lld: CapacitiveLLD = Field(CapacitiveLLD.OFF, alias="capacitiveLLD")
    liquid_following: bool = Field(False, alias="liquidFollowing")
    tip_tracking_factor: float = Field(1.0, alias="tipTrackingFactor")
    submerge_depth: float = Field(2.0, alias="submergeDepth")
    fixed_height: float = Field(5.0, alias="fixedHeight")
    mix_cycles: int = Field(0, alias="mixCycles")
    mix_position: float = Field(0.0, alias="mixPosition")
    mix_volume: float = Field(0.0, alias="mixVolume")
    air_transport_retract_dist: float = Field(5.0, alias="airTransportRetractDist")
    use_side_touch: bool | None = Field(None, alias="useSideTouch")
    minimize_z_move: bool | None = Field(None, alias="minimizeZMove")


class MPH96MoveAxisParameters(_WireModel):
    axis: Axis
    value: float
    mode: CoordinateMode = CoordinateMode.ABSOLUTE
    safety_bypass_token: str | None = Field(None, alias="safetyBypassToken")


class MPH96TipEjectParameters(_WireModel):
    labware_id: str | None = Field(None, alias="labwareName", validation_alias=AliasChoices("labwareName", "labwareId"))
    mph_pattern: MPH96Pattern | None = Field(None, alias="mphPattern")
    mph_selection: MPHSelection | None = Field(
        None,
        alias="mphSelection",
        validation_alias=AliasChoices("mphSelection", "mphPattern"),
    )
    eject_mode: EjectMode = Field(EjectMode.WASTE, alias="ejectMode")


class MPH96DetectLiquidLevelParameters(_WireModel):
    labware_id: str = Field(..., alias="labwareName", validation_alias=AliasChoices("labwareName", "labwareId"))
    mph_pattern: MPHSelection | None = Field(
        None,
        alias="mphSelection",
        validation_alias=AliasChoices("mphSelection", "mphPattern"),
    )
    capacitive_lld: CapacitiveLLD = Field(CapacitiveLLD.MAX, alias="capacitiveLLD")


class TransportParameters(_WireModel):
    labware_name: str | None = Field(None, alias="labwareName")
    carrier: str | None = None
    site: str | None = None
    grip_height_above_bottom: float | None = Field(None, alias="gripHeightAboveBottom")
    grip_width: float | None = Field(None, alias="gripWidth")
    grip_open: float | None = Field(None, alias="gripOpen")
    tool_id: int | None = Field(None, alias="toolId")
    front_channel: int | None = Field(None, alias="frontChannel")
    grip_force: int | None = Field(None, alias="gripForce")
    press_distance: float | None = Field(None, alias="pressDistance")
    x_acceleration: int | None = Field(None, alias="xAcceleration")
    grip_close_speed: float | None = Field(None, alias="gripCloseSpeed")
    grip_z_speed: float | None = Field(None, alias="gripZSpeed")
    offset_grip: float | None = Field(None, alias="offsetGrip")
    check_presence: dict[str, bool] | None = Field(None, alias="checkPresence")
    eject_grip: bool | None = Field(None, alias="ejectGrip")


TransportPlateParameters = TransportParameters


class TransportReturnPlateParameters(_WireModel):
    mode: str = "return"
    carrier: str | None = None
    site: str | None = None
    check_presence: dict[str, bool] | None = Field(None, alias="checkPresence")
    grip_z_speed: float | None = Field(None, alias="gripZSpeed")
    x_acceleration: int | None = Field(None, alias="xAcceleration")
    press_distance: float | None = Field(None, alias="pressDistance")
    eject_grip: bool | None = Field(None, alias="ejectGrip")


class TransportToWasteParameters(_WireModel):
    labware_name: str | None = Field(None, alias="labwareName")
    grip_height_above_bottom: float | None = Field(None, alias="gripHeightAboveBottom")
    grip_width: float | None = Field(None, alias="gripWidth")
    grip_open: float | None = Field(None, alias="gripOpen")
    tool_id: int | None = Field(None, alias="toolId")
    front_channel: int | None = Field(None, alias="frontChannel")
    grip_force: int | None = Field(None, alias="gripForce")
    x_acceleration: int | None = Field(None, alias="xAcceleration")
    grip_close_speed: float | None = Field(None, alias="gripCloseSpeed")
    grip_z_speed: float | None = Field(None, alias="gripZSpeed")
    offset_grip: float | None = Field(None, alias="offsetGrip")
    check_presence: dict[str, bool] | None = Field(None, alias="checkPresence")
    eject_grip: bool | None = Field(None, alias="ejectGrip")


class TransportPresentAndScanParameters(_WireModel):
    labware_name: str = Field(..., alias="labwareName")
    carrier: str = ""
    site: str = ""
    grip_height_above_bottom: float = Field(..., alias="gripHeightAboveBottom")
    grip_width: float | None = Field(None, alias="gripWidth")
    grip_open: float | None = Field(None, alias="gripOpen")
    track: int = Field(..., alias="track")
    z_minimal_position: float = Field(..., alias="zMinimalPosition")
    grip_force: int | None = Field(None, alias="gripForce")
    x_acceleration: int | None = Field(None, alias="xAcceleration")
    grip_close_speed: float | None = Field(None, alias="gripCloseSpeed")
    grip_z_speed: float | None = Field(None, alias="gripZSpeed")
    eject_grip: bool | None = Field(None, alias="ejectGrip")
    check_presence: dict[str, bool] | None = Field(None, alias="checkPresence")


class FrontCoverIsClosedReturnParameters(_ResponseModel):
    is_closed: bool = Field(False, alias="isClosed")


class FrontCoverIsLockedReturnParameters(_ResponseModel):
    is_locked: bool = Field(False, alias="isLocked")


class TrackOccupiedReturnParameters(_ResponseModel):
    is_occupied: bool = Field(False, alias="isOccupied", validation_alias=AliasChoices("isOccupied", "trackOccupied"))


class StatusInitReturnParameters(_ResponseModel):
    instrument_name: str = Field("", alias="instrumentName")
    autoload_current_track: int | None = Field(None, alias="autoloadCurrentTrack")


class StatusConnectReturnParameters(_ResponseModel):
    instrument_name: str = Field("", alias="instrumentName")
    autoload_current_track: int | None = Field(None, alias="autoloadCurrentTrack")
    message: str = ""


class StatusIsConnectedReturnParameters(_ResponseModel):
    is_connected: bool = Field(False, alias="isConnected")


class StatusIsIdleReturnParameters(_ResponseModel):
    is_idle: bool = Field(False, alias="isIdle")


class Gripper(_ResponseModel):
    type: str | None = Field(None)


class ChannelInfo(_ResponseModel):
    total: int | None = None
    raster: int | None = None
    type: str | None = None
    capacity: int | None = None
    max_y: list[float] | None = Field(None, alias="maxY")
    min_y: list[float] | None = Field(None, alias="minY")


class MPH96ConfigurationInfo(_ResponseModel):
    """MPH96 head details reported by ``configuration.getConfiguration``.

    VENUS reports this nested object when an MPH96 head is installed, or
    ``null`` (-> ``None`` here) when it isn't. Older VENUS builds report a
    plain boolean presence flag instead, which ``ConfigurationArm.mph96``
    still accepts.
    """

    total: int | None = None
    raster: float | None = None
    type: str | None = None
    capacity: float | None = None
    x_min: float | None = Field(None, alias="xMin")
    x_max: float | None = Field(None, alias="xMax")
    y_min: float | None = Field(None, alias="yMin")
    y_max: float | None = Field(None, alias="yMax")


class ConfigurationArm(_ResponseModel):
    arm_id: int | None = Field(None, alias="armId")
    # Whether the arm's transport tool is an iSWAP or IPG gripper is reported
    # via gripper.type ("iSWAP" / "IPG"), not a standalone boolean -- VENUS
    # never sends an "iSWAP" key on the arm itself.
    gripper: Gripper | None = None
    mph96: MPH96ConfigurationInfo | bool | None = Field(None, alias="MPH96")
    mph384: bool | None = Field(None, alias="MPH384")
    channels_1_ml: ChannelInfo | None = Field(None, alias="channels1mL")
    channels_5_ml: ChannelInfo | None = Field(None, alias="channels5mL")
    channels_mag_pip: ChannelInfo | None = Field(None, alias="channelsMagPip")
    x_min: float | None = Field(None, alias="xMin")
    x_max: float | None = Field(None, alias="xMax")


class ConfigurationReturnParameters(_ResponseModel):
    left_arm: ConfigurationArm | None = Field(None, alias="LeftArm")
    right_arm: ConfigurationArm | None = Field(None, alias="RightArm")
    type: str | None = None
    autoload: bool | None = Field(None, alias="Autoload")
    tracks: int | None = None
    max_autoload_track: int | None = Field(None, alias="MaxAutoloadTrack")


class ConfigurationSerialNumberReturnParameters(_ResponseModel):
    serial_number: str = Field("", alias="serialNumber")


class MaintenanceDataReturnParameters(_ResponseModel):
    status: str = ""
    expiration_date: str | None = Field(None, alias="expirationDate")
    processed_date: str | None = Field(None, alias="processedDate")
    processed_status: str | None = Field(None, alias="processedStatus")
    processed_code: int | None = Field(None, alias="processedCode")
    is_mandatory: bool | None = Field(None, alias="isMandatory")


class DeckTracksReturnParameters(_ResponseModel):
    total_tracks: int = Field(0, alias="totalTracks")
    autoloadable_tracks: int = Field(0, alias="autoloadableTracks")
    active_tracks: list[int] = Field(default_factory=list, alias="activeTracks")


class DeckDimensionsReturnParameters(_ResponseModel):
    x: float = 0.0
    y: float = 0.0


class WasteLocation(_ResponseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    carrier: str = ""
    labware_name: str = Field("", alias="labwareName")
    is_default: bool = Field(False, alias="isDefault")
    is_mph96_waste: bool = Field(False, alias="isMPH96Waste")
    is_mph384_waste: bool = Field(False, alias="isMPH384Waste")
    is_mag_pip_waste: bool = Field(False, alias="isMagPipWaste")


class WasteLocationsReturnParameters(_ResponseModel):
    waste_locations: list[dict[str, WasteLocation]] = Field(default_factory=list, alias="wasteLocations")


class FirmwareCommandReturnParameters(_ResponseModel):
    return_value: str = Field("", alias="return")


class EmptyCommandResponse(CommandResponse):
    return_parameters: EmptyReturnParameters = Field(default_factory=EmptyReturnParameters, alias="returnParameters")


class FrontCoverIsClosedResponse(CommandResponse):
    return_parameters: FrontCoverIsClosedReturnParameters = Field(
        default_factory=FrontCoverIsClosedReturnParameters,
        alias="returnParameters",
    )


class FrontCoverIsLockedResponse(CommandResponse):
    return_parameters: FrontCoverIsLockedReturnParameters = Field(
        default_factory=FrontCoverIsLockedReturnParameters,
        alias="returnParameters",
    )


class TrackOccupiedResponse(CommandResponse):
    return_parameters: TrackOccupiedReturnParameters = Field(
        default_factory=TrackOccupiedReturnParameters,
        alias="returnParameters",
    )


class StatusInitResponse(CommandResponse):
    return_parameters: StatusInitReturnParameters = Field(
        default_factory=StatusInitReturnParameters,
        alias="returnParameters",
    )


class StatusConnectResponse(CommandResponse):
    return_parameters: StatusConnectReturnParameters = Field(
        default_factory=StatusConnectReturnParameters,
        alias="returnParameters",
    )


class StatusIsConnectedResponse(CommandResponse):
    return_parameters: StatusIsConnectedReturnParameters = Field(
        default_factory=StatusIsConnectedReturnParameters,
        alias="returnParameters",
    )


class StatusIsIdleResponse(CommandResponse):
    return_parameters: StatusIsIdleReturnParameters = Field(
        default_factory=StatusIsIdleReturnParameters,
        alias="returnParameters",
    )


class ConfigurationResponse(CommandResponse):
    return_parameters: ConfigurationReturnParameters = Field(
        default_factory=ConfigurationReturnParameters,
        alias="returnParameters",
    )


class ConfigurationSerialNumberResponse(CommandResponse):
    return_parameters: ConfigurationSerialNumberReturnParameters = Field(
        default_factory=ConfigurationSerialNumberReturnParameters,
        alias="returnParameters",
    )


class MaintenanceDataResponse(CommandResponse):
    return_parameters: MaintenanceDataReturnParameters = Field(
        default_factory=MaintenanceDataReturnParameters,
        alias="returnParameters",
    )


class FirmwareCommandResponse(CommandResponse):
    return_parameters: FirmwareCommandReturnParameters = Field(
        default_factory=FirmwareCommandReturnParameters,
        alias="returnParameters",
    )


class DeckTracksResponse(CommandResponse):
    return_parameters: DeckTracksReturnParameters = Field(
        default_factory=DeckTracksReturnParameters,
        alias="returnParameters",
    )


class DeckDimensionsResponse(CommandResponse):
    return_parameters: DeckDimensionsReturnParameters = Field(
        default_factory=DeckDimensionsReturnParameters,
        alias="returnParameters",
    )


class WasteLocationsResponse(CommandResponse):
    return_parameters: WasteLocationsReturnParameters = Field(
        default_factory=WasteLocationsReturnParameters,
        alias="returnParameters",
    )


class DeckAvailableReturnParameters(_ResponseModel):
    deck_available: bool = Field(False, alias="deckAvailable")


class SavedDecksReturnParameters(_ResponseModel):
    saved_decks: list[str] = Field(default_factory=list, alias="savedDecks")


class AvailableTracksReturnParameters(_ResponseModel):
    tracks_available: list[int] = Field(default_factory=list, alias="tracksAvailable")


class OccupiedTracksReturnParameters(_ResponseModel):
    tracks_occupied: list[int] = Field(default_factory=list, alias="tracksOccupied")


class AddedCarriersReturnParameters(_ResponseModel):
    total_carriers: int = Field(0, alias="totalCarriers")
    carriers_added: list[str] = Field(default_factory=list, alias="carriersAdded")


class DeckImportCarrier(_ResponseModel):
    labware_name: str = Field("", alias="labwareName")
    left_track: int | None = Field(None, alias="leftTrack")
    x: float | None = None
    y: float | None = None
    z: float | None = None
    angle: float | None = None


class DeckImportReturnParameters(_ResponseModel):
    carriers_added: list[DeckImportCarrier] = Field(default_factory=list, alias="carriersAdded")


class DeckRackInfo(_ResponseModel):
    file: str = ""
    x: float | None = None
    y: float | None = None
    z: float | None = None
    angle: float | None = None


class DeckGetRackIdsFromDeckReturnParameters(_ResponseModel):
    racks_found: dict[str, DeckRackInfo] = Field(default_factory=dict, alias="racksFound")


class DeckImportRackAsSiteReturnParameters(_ResponseModel):
    site_added: str = Field("", alias="siteAdded")


class ChannelTADMCurvePoint(_ResponseModel):
    time_ms: int | None = Field(None, alias="timeMs")
    pressure: int | None = None


class ChannelTADMCurve(_ResponseModel):
    curve_id: int = Field(0, alias="curveId")
    liquid_class_name: str = Field("", alias="liquidClassName")
    step_type: int = Field(0, alias="stepType")
    step_type_name: str = Field("", alias="stepTypeName")
    volume: float = 0.0
    time_stamp: str = Field("", alias="timeStamp")
    step_guid: str = Field("", alias="stepGuid")
    tolerance_band_guid: str = Field("", alias="toleranceBandGuid")
    step_number: int = Field(0, alias="stepNumber")
    curve_points: list[ChannelTADMCurvePoint] = Field(default_factory=list, alias="curvePoints")
    error: int = 0
    channel_number: int = Field(0, alias="channelNumber")
    tadm_mode: int = Field(0, alias="tadmMode")
    curve_flagged: int = Field(0, alias="curveFlagged")
    check_sum: int = Field(0, alias="checkSum")


class ChannelTADM(_ResponseModel):
    tadm_curves: list[ChannelTADMCurve] = Field(default_factory=list, alias="tadmCurves")


class AspirationChannelData(_ResponseModel):
    """Per-channel result of a 1mL-channel aspirate.

    FORMERLY-KNOWN VENUS-SIDE BUG, now patched by Hamilton (see CHANGELOG.md's
    2026-08-12 entry): when capacitive/pressure LLD was enabled,
    ``liquid_level_mm``/``liquid_volume_ul`` used to come back as the
    fixed-height placeholder (whatever ``fixedHeight`` was) and ``0.0`` instead
    of the real measured values, even though VENUS's own runtime trace showed
    it genuinely measured real per-channel height/volume via a "Get Last
    Liquid Level" step right after the aspirate. Root cause was an inverted
    condition in ``sdk_method_structure/Library/Controllers/STARController.hsi``
    (~line 5654) guarding the real-vs-fixed fallback -- it discarded the real
    reading exactly when LLD was *on*, the opposite of correct. Hamilton has
    since patched this on their end; this repo's ``sdk_method_structure`` copy
    hasn't been re-synced to pick it up yet as of 2026-08-12, so it may still
    show the old (buggy) logic until the next "Sync sdk (N)" pull.
    """

    channel: int = 0
    aspirated_volume: float = Field(0.0, alias="aspiratedVolume")
    liquid_level_mm: float = Field(0.0, alias="liquidLevel_mm")
    liquid_volume_ul: float = Field(0.0, alias="liquidVolume_uL")


class DispenseChannelData(_ResponseModel):
    channel: int = 0
    dispensed_volume: float = Field(0.0, alias="dispensedVolume")


class ChannelAspirationReturnParameters(_ResponseModel):
    channels: list[AspirationChannelData] = Field(default_factory=list)
    tadm: ChannelTADM | None = Field(None, alias="TADM")


class ChannelDispenseReturnParameters(_ResponseModel):
    channels: list[DispenseChannelData] = Field(default_factory=list)
    tadm: ChannelTADM | None = Field(None, alias="TADM")


class ChannelTipCheckActiveChannel(_ResponseModel):
    channel: int = 0
    tip_type: int = Field(0, alias="tipType")
    tip_name: str = Field("", alias="tipName")


class ChannelTipCheckReturnParameters(_ResponseModel):
    active_channels: list[ChannelTipCheckActiveChannel] = Field(default_factory=list, alias="activeChannels")


class ChannelAxisPosition(_ResponseModel):
    channel: int = 0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class ChannelMoveAxisReturnParameters(_ResponseModel):
    channel_status: list[ChannelAxisPosition] = Field(default_factory=list, alias="channelStatus")


class ChannelStatus(_ResponseModel):
    channel: int = 0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    tip_loaded: int = Field(0, alias="tipLoaded")


class ChannelGetStatusReturnParameters(_ResponseModel):
    channel_status: list[ChannelStatus] = Field(default_factory=list, alias="channelStatus")


class MPH96Status(_ResponseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    tip_loaded: int = Field(0, alias="tipLoaded")


class MPH96GetStatusReturnParameters(_ResponseModel):
    mph96_status: MPH96Status = Field(default_factory=MPH96Status, alias="mph96Status")


class CarrierSensorStatusItem(_ResponseModel):
    carrier: str = ""
    sensor_track: int = Field(0, alias="sensorTrack")
    sensor_available: bool = Field(False, alias="sensorAvailable")
    status: bool = False


class CarrierSensorStatusReturnParameters(_ResponseModel):
    carrier_sensor_status: list[CarrierSensorStatusItem] = Field(default_factory=list, alias="carrierSensorStatus")


class MPH96ClearTipSupportReturnParameters(_ResponseModel):
    remaining_tips: int = Field(0, alias="remainingTips")


class MessageReturnParameters(_ResponseModel):
    message: str = ""


class IswapIsHoldingLabwareReturnParameters(_ResponseModel):
    # VENUS's controllers emit ``isHoldingPlate``; ``isHoldingLabware`` is kept
    # for older executor builds that used the method's literal name.
    is_holding_labware: bool = Field(
        False,
        validation_alias=AliasChoices("isHoldingPlate", "isHoldingLabware"),
    )


class LayoutMoveCarrierReturnParameters(_ResponseModel):
    message: str = ""


class LayoutAddNTRReturnParameters(_ResponseModel):
    total_tips: int = Field(0, alias="totalTips")
    tip_pool_name: str = Field("", alias="tipPoolName")
    labware_name: str | list[str] = Field("", alias="labwareName")
    tip_type: int = Field(0, alias="tipType")

class LayoutAddTipBoxReturnParameters(_ResponseModel):
    total_tips: int = Field(0, alias="totalTips")
    tip_pool_name: str = Field("", alias="tipPoolName")
    labware_name: str = Field("", alias="labwareName")
    tip_type: int = Field(0, alias="tipType")


class LayoutAddTipRackReturnParameters(_ResponseModel):
    total_tips: int = Field(0, alias="totalTips")
    tip_pool_name: str = Field("", alias="tipPoolName")
    labware_name: str = Field("", alias="labwareName")
    tip_type: int = Field(0, alias="tipType")


class LayoutAddTransportSiteReturnParameters(_ResponseModel):
    site_added: str = Field("", alias="siteAdded")


class OccupiedCarrierSite(_ResponseModel):
    site: str = ""
    labware_count: int = Field(0, alias="labwareCount")


class CarrierSitesReturnParameters(_ResponseModel):
    available_sites: list[str] = Field(default_factory=list, alias="availableSites")
    used_sites: list[OccupiedCarrierSite] = Field(default_factory=list, alias="usedSites")


class LabwareOnCarrierItem(_ResponseModel):
    labware_name: str = Field("", alias="labwareName")
    labware_type: str = Field("", alias="labwareType")


class LabwareOnCarrierReturnParameters(_ResponseModel):
    labware: list[LabwareOnCarrierItem] = Field(default_factory=list)


class LabwarePositionsReturnParameters(_ResponseModel):
    """VENUS returns a flat {labwareName: {count, positions}} map with no fixed
    fields of its own; extra="allow" on _ResponseModel captures those dynamic
    keys, reachable via .model_extra."""


class TopLabwareReturnParameters(_ResponseModel):
    labware_id: str = Field("", alias="labwareId")
    type: str = ""


class TipPoolCounterReturnParameters(_ResponseModel):
    total_available_tips: int = Field(0, alias="totalAvailableTips")
    total_empty_tips: int = Field(0, alias="totalEmptyTips")
    total_consumed_tips: int = Field(0, alias="totalConsumedTips")
    available_tips: list[dict[str, TipRackState]] = Field(default_factory=list, alias="availableTips")
    empty_tips: list[dict[str, TipRackState]] = Field(default_factory=list, alias="emptyTips")
    missing_racks: list[str] = Field(default_factory=list, alias="missingRacks")
    tip_type: int = Field(-1, alias="tipType")
    tip_type_id: str = Field("", alias="tipTypeId")


class TipPoolCountersReturnParameters(_ResponseModel):
    tip_counter_names: list[str] = Field(default_factory=list, alias="tipCounterNames")


class TipPoolAvailableTipsReturnParameters(_ResponseModel):
    total_available_tips: int = Field(0, alias="totalAvailableTips")
    available_tips: list[dict[str, TipRackState]] = Field(default_factory=list, alias="availableTips")


class TipPoolEmptyTipsReturnParameters(_ResponseModel):
    total_empty_tips: int = Field(0, alias="totalEmptyTips")
    empty_tips: list[dict[str, TipRackState]] = Field(default_factory=list, alias="emptyTips")


class TipPoolMissingRacksReturnParameters(_ResponseModel):
    missing_racks: list[str] = Field(default_factory=list, alias="missingRacks")


class TipCounterSummary(_ResponseModel):
    tip_counter: str = Field("", alias="tipCounter")
    total_available_tips: int = Field(0, alias="totalAvailableTips")
    available_tips: dict[str, TipRackState] = Field(default_factory=dict, alias="availableTips")
    missing_racks: list[str] = Field(default_factory=list, alias="missingRacks")


class ShowTipCountersReturnParameters(_ResponseModel):
    tip_counters: list[TipCounterSummary] = Field(default_factory=list, alias="tipCounters")


class LabwareDefinitionSingleReturnParameters(_ResponseModel):
    labware_name: str = Field("", alias="labwareName")
    definition: dict[str, Any] = Field(default_factory=dict)

    def to_labware_definition(self) -> LabwareDefinition:
        """Parse :attr:`definition` into a typed :class:`LabwareDefinition`."""
        from hamilton_venus.models.labware_definition import LabwareDefinition as _LabwareDefinition

        return _LabwareDefinition.model_validate(self.definition)

    def to_labware_layout_spec(self) -> LabwareLayoutSpec:
        """Parse :attr:`definition` into a :class:`LabwareLayoutSpec`."""
        from hamilton_venus.models.position import LabwareLayoutSpec as _LabwareLayoutSpec

        return _LabwareLayoutSpec.from_definition(self.definition)


class LabwareDefinitionDefinitionsReturnParameters(_ResponseModel):
    labware: dict[str, list[Any]] = Field(default_factory=dict, alias="labware")


class LabwareDefinitionTypesReturnParameters(_ResponseModel):
    labware_types: list[str] = Field(default_factory=list, alias="labwareTypes")


class DeckAvailableResponse(CommandResponse):
    return_parameters: DeckAvailableReturnParameters = Field(
        default_factory=DeckAvailableReturnParameters,
        alias="returnParameters",
    )


class SavedDecksResponse(CommandResponse):
    return_parameters: SavedDecksReturnParameters = Field(
        default_factory=SavedDecksReturnParameters,
        alias="returnParameters",
    )


class AvailableTracksResponse(CommandResponse):
    return_parameters: AvailableTracksReturnParameters = Field(
        default_factory=AvailableTracksReturnParameters,
        alias="returnParameters",
    )


class OccupiedTracksResponse(CommandResponse):
    return_parameters: OccupiedTracksReturnParameters = Field(
        default_factory=OccupiedTracksReturnParameters,
        alias="returnParameters",
    )


class AddedCarriersResponse(CommandResponse):
    return_parameters: AddedCarriersReturnParameters = Field(
        default_factory=AddedCarriersReturnParameters,
        alias="returnParameters",
    )


class DeckImportResponse(CommandResponse):
    return_parameters: DeckImportReturnParameters = Field(
        default_factory=DeckImportReturnParameters,
        alias="returnParameters",
    )


class DeckGetRackIdsFromDeckResponse(CommandResponse):
    return_parameters: DeckGetRackIdsFromDeckReturnParameters = Field(
        default_factory=DeckGetRackIdsFromDeckReturnParameters,
        alias="returnParameters",
    )


class DeckImportRackAsSiteResponse(CommandResponse):
    return_parameters: DeckImportRackAsSiteReturnParameters = Field(
        default_factory=DeckImportRackAsSiteReturnParameters,
        alias="returnParameters",
    )


class ChannelAspirationResponse(CommandResponse):
    return_parameters: ChannelAspirationReturnParameters = Field(
        default_factory=ChannelAspirationReturnParameters,
        alias="returnParameters",
    )


class ChannelDispenseResponse(CommandResponse):
    return_parameters: ChannelDispenseReturnParameters = Field(
        default_factory=ChannelDispenseReturnParameters,
        alias="returnParameters",
    )


class ChannelTipCheckResponse(CommandResponse):
    return_parameters: ChannelTipCheckReturnParameters = Field(
        default_factory=ChannelTipCheckReturnParameters,
        alias="returnParameters",
    )


class ChannelMoveAxisResponse(CommandResponse):
    return_parameters: ChannelMoveAxisReturnParameters = Field(
        default_factory=ChannelMoveAxisReturnParameters,
        alias="returnParameters",
    )


class ChannelGetStatusResponse(CommandResponse):
    return_parameters: ChannelGetStatusReturnParameters = Field(
        default_factory=ChannelGetStatusReturnParameters,
        alias="returnParameters",
    )


class MPH96GetStatusResponse(CommandResponse):
    return_parameters: MPH96GetStatusReturnParameters = Field(
        default_factory=MPH96GetStatusReturnParameters,
        alias="returnParameters",
    )


class CarrierSensorStatusResponse(CommandResponse):
    return_parameters: CarrierSensorStatusReturnParameters = Field(
        default_factory=CarrierSensorStatusReturnParameters,
        alias="returnParameters",
    )


class MPH96ClearTipSupportResponse(CommandResponse):
    return_parameters: MPH96ClearTipSupportReturnParameters = Field(
        default_factory=MPH96ClearTipSupportReturnParameters,
        alias="returnParameters",
    )


class MessageResponse(CommandResponse):
    return_parameters: MessageReturnParameters = Field(
        default_factory=MessageReturnParameters,
        alias="returnParameters",
    )


class IswapIsHoldingLabwareResponse(CommandResponse):
    return_parameters: IswapIsHoldingLabwareReturnParameters = Field(
        default_factory=IswapIsHoldingLabwareReturnParameters,
        alias="returnParameters",
    )


class LayoutMoveCarrierResponse(CommandResponse):
    return_parameters: LayoutMoveCarrierReturnParameters = Field(
        default_factory=LayoutMoveCarrierReturnParameters,
        alias="returnParameters",
    )


class LayoutAddNTRResponse(CommandResponse):
    return_parameters: LayoutAddNTRReturnParameters = Field(
        default_factory=LayoutAddNTRReturnParameters,
        alias="returnParameters",
    )

class LayoutAddTipBoxResponse(CommandResponse):
    return_parameters: LayoutAddTipBoxReturnParameters = Field(
        default_factory=LayoutAddTipBoxReturnParameters,
        alias="returnParameters",
    )


class LayoutAddTipRackResponse(CommandResponse):
    return_parameters: LayoutAddTipRackReturnParameters = Field(
        default_factory=LayoutAddTipRackReturnParameters,
        alias="returnParameters",
    )


class LayoutAddTransportSiteResponse(CommandResponse):
    return_parameters: LayoutAddTransportSiteReturnParameters = Field(
        default_factory=LayoutAddTransportSiteReturnParameters,
        alias="returnParameters",
    )


class CarrierSitesResponse(CommandResponse):
    return_parameters: CarrierSitesReturnParameters = Field(
        default_factory=CarrierSitesReturnParameters,
        alias="returnParameters",
    )


class LabwareOnCarrierResponse(CommandResponse):
    return_parameters: LabwareOnCarrierReturnParameters = Field(
        default_factory=LabwareOnCarrierReturnParameters,
        alias="returnParameters",
    )


class LabwarePositionsResponse(CommandResponse):
    return_parameters: LabwarePositionsReturnParameters = Field(
        default_factory=LabwarePositionsReturnParameters,
        alias="returnParameters",
    )


class TopLabwareResponse(CommandResponse):
    return_parameters: TopLabwareReturnParameters = Field(
        default_factory=TopLabwareReturnParameters,
        alias="returnParameters",
    )


class TipPoolCounterResponse(CommandResponse):
    return_parameters: TipPoolCounterReturnParameters = Field(
        default_factory=TipPoolCounterReturnParameters,
        alias="returnParameters",
    )


class TipPoolCountersResponse(CommandResponse):
    return_parameters: TipPoolCountersReturnParameters = Field(
        default_factory=TipPoolCountersReturnParameters,
        alias="returnParameters",
    )


class TipPoolAvailableTipsResponse(CommandResponse):
    return_parameters: TipPoolAvailableTipsReturnParameters = Field(
        default_factory=TipPoolAvailableTipsReturnParameters,
        alias="returnParameters",
    )


class TipPoolEmptyTipsResponse(CommandResponse):
    return_parameters: TipPoolEmptyTipsReturnParameters = Field(
        default_factory=TipPoolEmptyTipsReturnParameters,
        alias="returnParameters",
    )


class TipPoolMissingRacksResponse(CommandResponse):
    return_parameters: TipPoolMissingRacksReturnParameters = Field(
        default_factory=TipPoolMissingRacksReturnParameters,
        alias="returnParameters",
    )


class ShowTipCountersResponse(CommandResponse):
    return_parameters: ShowTipCountersReturnParameters = Field(
        default_factory=ShowTipCountersReturnParameters,
        alias="returnParameters",
    )


class LabwareDefinitionSingleResponse(CommandResponse):
    return_parameters: LabwareDefinitionSingleReturnParameters = Field(
        default_factory=LabwareDefinitionSingleReturnParameters,
        alias="returnParameters",
    )


class LabwareDefinitionDefinitionsResponse(CommandResponse):
    return_parameters: LabwareDefinitionDefinitionsReturnParameters = Field(
        default_factory=LabwareDefinitionDefinitionsReturnParameters,
        alias="returnParameters",
    )


class LabwareDefinitionTypesResponse(CommandResponse):
    return_parameters: LabwareDefinitionTypesReturnParameters = Field(
        default_factory=LabwareDefinitionTypesReturnParameters,
        alias="returnParameters",
    )


class TransportIsHoldingLabwareReturnParameters(_ResponseModel):
    # Channel controllers also emit ``isHoldingPlate`` (see IswapIsHoldingLabwareReturnParameters).
    is_holding_labware: bool = Field(
        False,
        validation_alias=AliasChoices("isHoldingPlate", "isHoldingLabware"),
    )
    labware_name: str = Field("", alias="labwareName")
    carrier: str = ""
    site: str = ""
    offset_grip: float = Field(0.0, alias="offsetGrip")


class TransportIsHoldingLabwareResponse(CommandResponse):
    return_parameters: TransportIsHoldingLabwareReturnParameters = Field(
        default_factory=TransportIsHoldingLabwareReturnParameters,
        alias="returnParameters",
    )


class Add1mLCoreGripParameters(_WireModel):
    type: CoreGripType = Field(CoreGripType.STANDARD, alias="type")


class Add5mLCoreGripParameters(_WireModel):
    pass


class AddQCGParameters(_WireModel):
    type: QCGType = Field(QCGType.QCG, alias="type")
    track: int | None = Field(None, alias="track")


class GetTransportToolParameters(_WireModel):
    is_1ml: bool | None = Field(None, alias="is1mL")
    is_qcg: bool | None = Field(None, alias="isQCG")
    tool_id: int | None = Field(None, alias="toolId")


class RemoveTransportToolParameters(_WireModel):
    tool_id: int = Field(..., alias="toolId")


class TransportToolPosition(_ResponseModel):
    carrier: str = ""
    site: str = ""


class TransportToolReturnParameters(_ResponseModel):
    transport_tool_id: int = Field(0, alias="transportToolID")
    labware_name: str = Field("", alias="labwareName")
    transport_tool_positions: list[TransportToolPosition] = Field(default_factory=list, alias="transportToolPositions")


class TransportToolResponse(CommandResponse):
    return_parameters: TransportToolReturnParameters = Field(
        default_factory=TransportToolReturnParameters,
        alias="returnParameters",
    )


class TransportToolIdItem(_ResponseModel):
    transport_tool_id: int = Field(0, alias="transportToolID")
    labware_name: str = Field("", alias="labwareName")


class TransportToolIdsReturnParameters(_ResponseModel):
    transport_tools: list[TransportToolIdItem] = Field(default_factory=list, alias="transportTools")


class TransportToolIdsResponse(CommandResponse):
    return_parameters: TransportToolIdsReturnParameters = Field(
        default_factory=TransportToolIdsReturnParameters,
        alias="returnParameters",
    )


class LiquidClassNamesParameters(_WireModel):
    names: list[str]


class LiquidClassesParameters(_WireModel):
    tip_type: int = Field(-1, alias="tipType")
    device: int = -1
    dispense_mode: int = Field(-1, alias="dispenseMode")
    is_original: int = Field(-1, alias="isOriginal")
    has_tadm_enabled: int = Field(-1, alias="hasTadmEnabled")


class LiquidDevice(_ResponseModel):
    device_name: str = Field("", alias="deviceName")
    device_id: int = Field(0, alias="deviceId")


class LiquidDevicesReturnParameters(_ResponseModel):
    devices: list[LiquidDevice] = Field(default_factory=list, alias="devices")


class LiquidDevicesResponse(CommandResponse):
    return_parameters: LiquidDevicesReturnParameters = Field(
        default_factory=LiquidDevicesReturnParameters,
        alias="returnParameters",
    )


class LiquidNamesReturnParameters(_ResponseModel):
    liquid_names: list[str] = Field(default_factory=list, alias="liquidNames")


class LiquidNamesResponse(CommandResponse):
    return_parameters: LiquidNamesReturnParameters = Field(
        default_factory=LiquidNamesReturnParameters,
        alias="returnParameters",
    )


class LiquidClassesReturnParameters(_ResponseModel):
    count: int = 0
    liquid_class_names: list[str] = Field(default_factory=list, alias="liquidClassNames")


class LiquidClassesResponse(CommandResponse):
    return_parameters: LiquidClassesReturnParameters = Field(
        default_factory=LiquidClassesReturnParameters,
        alias="returnParameters",
    )


class TipTypesReturnParameters(_ResponseModel):
    tip_types: dict[str, Any] = Field(default_factory=dict, alias="tipTypes")


class TipTypesResponse(CommandResponse):
    return_parameters: TipTypesReturnParameters = Field(
        default_factory=TipTypesReturnParameters,
        alias="returnParameters",
    )


class LiquidCorrectionPoint(_ResponseModel):
    targeted_volume: float = Field(0.0, alias="targetedVolume")
    corrected_volume: float = Field(0.0, alias="correctedVolume")


class LiquidClassVolumeRange(_ResponseModel):
    min: float = 0.0
    max: float = 0.0


class LiquidClassAppliesTo(_ResponseModel):
    instrument: str = ""
    liquid: str = ""
    volume_range: LiquidClassVolumeRange = Field(default_factory=LiquidClassVolumeRange, alias="volumeRange")
    tip_type: str = Field("", alias="tipType")
    dispense_mode: str = Field("", alias="dispenseMode")
    pipetting_device: str = Field("", alias="pipettingDevice")


class LiquidClassAspirate(_ResponseModel):
    flow_rate: float = Field(0.0, alias="flowRate")
    mix_flow_rate: float = Field(0.0, alias="mixFlowRate")
    air_transport_volume: float = Field(0.0, alias="airTransportVolume")
    blow_out_volume: float = Field(0.0, alias="blowOutVolume")
    swap_speed: float = Field(0.0, alias="swapSpeed")
    settling_time: float = Field(0.0, alias="settlingTime")
    over_aspirate_volume: float = Field(0.0, alias="overAspirateVolume")
    clot_retract_height: float = Field(0.0, alias="clotRetractHeight")


class LiquidClassDispense(_ResponseModel):
    flow_rate: float = Field(0.0, alias="flowRate")
    mix_flow_rate: float = Field(0.0, alias="mixFlowRate")
    air_transport_volume: float = Field(0.0, alias="airTransportVolume")
    blow_out_volume: float = Field(0.0, alias="blowOutVolume")
    swap_speed: float = Field(0.0, alias="swapSpeed")
    settling_time: float = Field(0.0, alias="settlingTime")
    stop_flow_rate: float = Field(0.0, alias="stopFlowRate")
    stop_back_volume: float = Field(0.0, alias="stopBackVolume")


class LiquidClassDetectionLLD(_ResponseModel):
    pressure_sensitivity: int = Field(0, alias="pressureSensitivity")
    lld_max_height_difference: float = Field(0.0, alias="lldMaxHeightDifference")


class LiquidClassDetection(_ResponseModel):
    lld: LiquidClassDetectionLLD = Field(default_factory=LiquidClassDetectionLLD)


class LiquidClassPipettingProperties(_ResponseModel):
    aspirate: LiquidClassAspirate = Field(default_factory=LiquidClassAspirate)
    dispense: LiquidClassDispense = Field(default_factory=LiquidClassDispense)
    detection: LiquidClassDetection = Field(default_factory=LiquidClassDetection)
    correction: list[LiquidCorrectionPoint] = Field(default_factory=list)
    tadm_bands: list[Any] = Field(default_factory=list, alias="tadmBands")


class LiquidClassInternal(_ResponseModel):
    model_config = ConfigDict(populate_by_name=True)

    design_history: str = Field("", alias="designHistory")
    tip_type_id: int = Field(0, alias="tipTypeId")
    dispense_mode: int = Field(0, alias="dispenseMode")
    liquid_device_ids: list[int] = Field(default_factory=list, alias="liquidDeviceIds")


class LiquidClassDefinition(_ResponseModel):
    id: str = ""
    is_user_defined: bool = Field(False, alias="isUserDefined")
    version: str = ""
    tadm_enabled: bool = Field(False, alias="tadmEnabled")
    validated: bool = False
    notes: str = ""
    applies_to: LiquidClassAppliesTo = Field(default_factory=LiquidClassAppliesTo, alias="appliesTo")
    pipetting_properties: LiquidClassPipettingProperties = Field(
        default_factory=LiquidClassPipettingProperties, alias="pipettingProperties"
    )
    internal: LiquidClassInternal = Field(default_factory=LiquidClassInternal, alias="_internal")


class GetLiquidClassParameters(_WireModel):
    name: str


class GetLiquidClassReturnParameters(_ResponseModel):
    definition: LiquidClassDefinition = Field(default_factory=LiquidClassDefinition)


class GetLiquidClassResponse(CommandResponse):
    return_parameters: GetLiquidClassReturnParameters = Field(
        default_factory=GetLiquidClassReturnParameters,
        alias="returnParameters",
    )


class UpdateLiquidClassParameters(_WireModel):
    definition: LiquidClassDefinition


class AddedPlatesReturnParameters(_ResponseModel):
    total_plates: int = Field(0, alias="totalPlates")
    plates_added: list[str] = Field(default_factory=list, alias="platesAdded")


class AddedPlatesResponse(CommandResponse):
    return_parameters: AddedPlatesReturnParameters = Field(
        default_factory=AddedPlatesReturnParameters,
        alias="returnParameters",
    )


class AddedTipRacksReturnParameters(_ResponseModel):
    total_tip_racks: int = Field(0, alias="totalTipRacks")
    tip_racks_added: list[str] = Field(default_factory=list, alias="tipRacksAdded")


class AddedTipRacksResponse(CommandResponse):
    return_parameters: AddedTipRacksReturnParameters = Field(
        default_factory=AddedTipRacksReturnParameters,
        alias="returnParameters",
    )


class AddedReservoirsReturnParameters(_ResponseModel):
    total_reservoirs: int = Field(0, alias="totalReservoirs")
    reservoirs_added: list[str] = Field(default_factory=list, alias="reservoirsAdded")


class AddedReservoirsResponse(CommandResponse):
    return_parameters: AddedReservoirsReturnParameters = Field(
        default_factory=AddedReservoirsReturnParameters,
        alias="returnParameters",
    )


class LabwareLocationReturnParameters(_ResponseModel):
    carrier: str = ""
    site: str = ""


class LabwareLocationResponse(CommandResponse):
    return_parameters: LabwareLocationReturnParameters = Field(
        default_factory=LabwareLocationReturnParameters,
        alias="returnParameters",
    )


class TransportPresentAndScanReturnParameters(_ResponseModel):
    message: str = ""
    barcode: str = ""


class TransportPresentAndScanResponse(CommandResponse):
    return_parameters: TransportPresentAndScanReturnParameters = Field(
        default_factory=TransportPresentAndScanReturnParameters,
        alias="returnParameters",
    )


class AddLiddedPlateReturnParameters(_ResponseModel):
    labware_name: str = Field("", alias="labwareName")
    lid_name: str = Field("", alias="lidName")


class AddLiddedPlateResponse(CommandResponse):
    return_parameters: AddLiddedPlateReturnParameters = Field(
        default_factory=AddLiddedPlateReturnParameters,
        alias="returnParameters",
    )


class LabwareCoordinatesParameters(_WireModel):
    labware_name: str = Field(..., alias="labwareName")
    well: str | None = None


class LabwareCoordinates(_ResponseModel):
    """One x/y/z position on the deck (mm) with its rotation angle (degrees)."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    angle: float = 0.0


class LabwareWellCoordinates(LabwareCoordinates):
    """The coordinates of one well (position) of a labware."""

    well: str = ""


class LabwareCoordinatesReturnParameters(_ResponseModel):
    """What ``status.getLabwareCoordinates`` returns, in one of two shapes.

    With a ``well``: that well's coordinates in ``well`` / ``x`` / ``y`` / ``z`` /
    ``angle``; ``origin`` and ``wells`` are ``None``.

    Without a ``well``: ``origin`` (the labware's origin) and, for a rack-type
    labware (``.rck``: plate, tip rack, tube rack, reservoir), ``wells`` with the
    coordinates of every position, ordered by column (A1, B1, ..., A2, ...).
    A carrier has no wells and returns ``origin`` only (``wells`` is ``None``).
    ``well`` / ``x`` / ``y`` / ``z`` / ``angle`` are ``None`` in this shape.
    """

    well: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    angle: float | None = None
    origin: LabwareCoordinates | None = None
    wells: list[LabwareWellCoordinates] | None = None


class LabwareCoordinatesResponse(CommandResponse):
    return_parameters: LabwareCoordinatesReturnParameters = Field(
        default_factory=LabwareCoordinatesReturnParameters,
        alias="returnParameters",
    )


class LayoutShiftLabwareParameters(_WireModel):
    labware_name: str = Field(..., alias="labwareName")
    relative_x: float = Field(..., alias="relativeX")
    relative_y: float = Field(..., alias="relativeY")
    relative_z: float = Field(..., alias="relativeZ")
    relative_angle: float = Field(..., alias="relativeAngle")


class LayoutShiftLabwareResponse(CommandResponse):
    return_parameters: LabwareCoordinates = Field(
        default_factory=LabwareCoordinates,
        alias="returnParameters",
    )


# --- Teaching (category "Teaching", actions teaching.1mL.*) -------------------------
# All coordinates are needle-tip coordinates in mm.


class TeachingSetChannelParameters(_WireModel):
    channel: int = Field(..., ge=1)


class TeachingChannelReturnParameters(_ResponseModel):
    channel: int = 0


class TeachingChannelResponse(CommandResponse):
    return_parameters: TeachingChannelReturnParameters = Field(
        default_factory=TeachingChannelReturnParameters,
        alias="returnParameters",
    )


class TeachingNeedleStatusReturnParameters(_ResponseModel):
    is_needle_picked_up: bool = Field(False, alias="isNeedlePickedUp")


class TeachingNeedleStatusResponse(CommandResponse):
    return_parameters: TeachingNeedleStatusReturnParameters = Field(
        default_factory=TeachingNeedleStatusReturnParameters,
        alias="returnParameters",
    )


class TeachingLabwareDimensionsParameters(_WireModel):
    labware_name: str = Field(..., alias="labwareName")
    well: str | None = None


class TeachingPoint2D(_ResponseModel):
    x: float = 0.0
    y: float = 0.0


class TeachingLabwareDimensions(_ResponseModel):
    """The labware as a whole: bounding-box ``center``, ``bottom_z`` (skirt bottom) and ``height``."""

    labware_id: str = Field("", alias="labwareId")
    center: TeachingPoint2D = Field(default_factory=TeachingPoint2D)
    bottom_z: float = Field(0.0, alias="bottomZ")
    height: float = 0.0


class TeachingWellDimensions(_ResponseModel):
    """One well: its ``center``, ``bottom_z`` (well bottom) and ``depth`` (bottom to entrance)."""

    position_id: str = Field("", alias="positionId")
    center: TeachingPoint2D = Field(default_factory=TeachingPoint2D)
    bottom_z: float = Field(0.0, alias="bottomZ")
    depth: float = 0.0

    @property
    def entrance_z(self) -> float:
        """Z of the well entrance (``bottom_z + depth``)."""
        return self.bottom_z + self.depth


class TeachingLabwareDimensionsReturnParameters(_ResponseModel):
    labware: TeachingLabwareDimensions = Field(default_factory=TeachingLabwareDimensions)
    well: TeachingWellDimensions = Field(default_factory=TeachingWellDimensions)


class TeachingLabwareDimensionsResponse(CommandResponse):
    return_parameters: TeachingLabwareDimensionsReturnParameters = Field(
        default_factory=TeachingLabwareDimensionsReturnParameters,
        alias="returnParameters",
    )


class TeachingMoveParameters(_WireModel):
    """Omitted axes stay where they are; ``z_traverse`` defaults to the current Z."""

    x: float | None = None
    y: float | None = None
    z: float | None = Field(None, ge=105.0, le=245.0)
    z_traverse: float | None = Field(None, alias="zTraverse", ge=105.0, le=245.0)


class TeachingPosition(_ResponseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class TeachingMoveResponse(CommandResponse):
    return_parameters: TeachingPosition = Field(
        default_factory=TeachingPosition,
        alias="returnParameters",
    )


class TeachingStatus(_ResponseModel):
    """Search result as ``code`` (0/1/2) and ``name`` (``WALL_NOT_FOUND``/``WALL_FOUND``/``FOUND_EARLY``)."""

    code: int = 0
    name: str = ""

    @property
    def measure_status(self) -> TeachingMeasureStatus:
        return TeachingMeasureStatus(self.code)


class TeachingMeasureZParameters(_WireModel):
    """``z_end`` -1 returns the needle to its start height after a find."""

    z_start: float = Field(..., alias="zStart", ge=100.0, le=334.0)
    z_min: float = Field(..., alias="zMin", ge=100.0, le=334.0)
    z_end: float = Field(-1.0, alias="zEnd", ge=-1.0, le=100.0)
    use_slow_speed: bool | None = Field(None, alias="useSlowSpeed")


class TeachingMeasureZReturnParameters(_ResponseModel):
    measured_z: float = Field(0.0, alias="measuredZ")
    status: TeachingStatus = Field(default_factory=TeachingStatus)


class TeachingMeasureZResponse(CommandResponse):
    return_parameters: TeachingMeasureZReturnParameters = Field(
        default_factory=TeachingMeasureZReturnParameters,
        alias="returnParameters",
    )


class TeachingMeasureXYParameters(_WireModel):
    safe_height: float = Field(..., alias="safeHeight", ge=100.0, le=334.0)
    min_search_z: float = Field(..., alias="minSearchZ", ge=100.0, le=334.0)
    well_width: float = Field(..., alias="wellWidth", ge=2.0, le=100.0)
    direction: TeachingDirection
    step_distance: float | None = Field(None, alias="stepDistance", ge=0.3, le=2.4)


class TeachingWallMeasurement(_ResponseModel):
    """``wall_coordinate`` is on ``axis`` (``"x"``/``"y"``); ``entrance_z`` is the wall-top stall height."""

    axis: str = ""
    wall_coordinate: float = Field(0.0, alias="wallCoordinate")
    entrance_z: float = Field(0.0, alias="entranceZ")


class TeachingMeasureXYReturnParameters(_ResponseModel):
    wall: str = ""
    status: TeachingStatus = Field(default_factory=TeachingStatus)
    measured: TeachingWallMeasurement | None = None


class TeachingMeasureXYResponse(CommandResponse):
    return_parameters: TeachingMeasureXYReturnParameters = Field(
        default_factory=TeachingMeasureXYReturnParameters,
        alias="returnParameters",
    )


class TiltWellDeltaInput(_WireModel):
    """One well of a ``labware.tiltLabware`` request.

    ``delta_x`` / ``delta_y`` are added to the well's nominal X / Y; ``delta_z`` is the
    well's container base offset above the rack base (the definition's value at 0 degrees).
    """

    well: str
    delta_x: float = Field(..., alias="deltaX")
    delta_y: float = Field(0.0, alias="deltaY")
    delta_z: float = Field(..., alias="deltaZ")


class LayoutTiltLabwareParameters(_WireModel):
    labware_name: str = Field(..., alias="labwareName")
    tilt_degrees: float = Field(..., alias="tiltDegrees")
    pivot_point: TiltPivotPoint = Field(TiltPivotPoint.LEFT_EDGE, alias="pivotPoint")
    pivot_x_offset: float = Field(0.0, alias="pivotXOffset")
    pivot_z_offset: float = Field(0.0, alias="pivotZOffset")
    well_position: TiltWellPosition = Field(TiltWellPosition.CENTER, alias="wellPosition")
    wells: list[TiltWellDeltaInput]


class LayoutTiltLabwareReturnParameters(_ResponseModel):
    """What ``labware.tiltLabware`` returns: each updated well's deck coordinates after the tilt."""

    labware_name: str = Field("", alias="labwareName")
    tilt_degrees: float = Field(0.0, alias="tiltDegrees")
    wells: list[LabwareWellCoordinates] = Field(default_factory=list)


class LayoutTiltLabwareResponse(CommandResponse):
    return_parameters: LayoutTiltLabwareReturnParameters = Field(
        default_factory=LayoutTiltLabwareReturnParameters,
        alias="returnParameters",
    )


class SplitWellSlotInput(_WireModel):
    """One slot of a ``labware.addSplitWellSite`` request.

    ``well`` is the slot's position in the split rack (``"1"``, ``"2"``, ... from the back). The deltas
    are deck-frame millimetres from the parent well's current position; ``delta_z``
    raises the slot's container base above the parent's.
    """

    well: str
    delta_x: float = Field(0.0, alias="deltaX")
    delta_y: float = Field(0.0, alias="deltaY")
    delta_z: float = Field(0.0, alias="deltaZ")


class LayoutAddSplitWellSiteParameters(_WireModel):
    split_labware_name: str = Field(..., alias="splitLabwareName")
    parent_labware_name: str = Field(..., alias="parentLabwareName")
    parent_well: str = Field(..., alias="parentWell")
    definition: dict[str, Any]
    slots: list[SplitWellSlotInput]
    # Where the split rack's origin goes relative to the parent well. X / Y only centre
    # the rack on the well (each slot is placed on its own); Z must be slot 1's deltaZ,
    # because VENUS ignores a container Z offset on rack position 1.
    rack_delta_x: float = Field(0.0, alias="rackDeltaX")
    rack_delta_y: float = Field(0.0, alias="rackDeltaY")
    rack_delta_z: float = Field(0.0, alias="rackDeltaZ")


class LayoutAddSplitWellSiteReturnParameters(_ResponseModel):
    """What ``labware.addSplitWellSite`` returns: the deck coordinates of each slot of the one split rack."""

    split_labware_name: str = Field("", alias="splitLabwareName")
    parent_labware_name: str = Field("", alias="parentLabwareName")
    parent_well: str = Field("", alias="parentWell")
    slots: list[LabwareWellCoordinates] = Field(default_factory=list)


class LayoutAddSplitWellSiteResponse(CommandResponse):
    return_parameters: LayoutAddSplitWellSiteReturnParameters = Field(
        default_factory=LayoutAddSplitWellSiteReturnParameters,
        alias="returnParameters",
    )


class TubePositionInput(_WireModel):
    position: str
    tube: str
    x_offset: float = Field(0.0, alias="xOffset")
    y_offset: float = Field(0.0, alias="yOffset")
    z_offset: float = Field(0.0, alias="zOffset")


class LayoutAddTubesToCarrierParameters(_WireModel):
    labware_name: str = Field(..., alias="labwareName")
    positions: list[TubePositionInput]


class TubePositionResult(_ResponseModel):
    position: str = ""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class LayoutAddTubesToCarrierReturnParameters(_ResponseModel):
    positions: list[TubePositionResult] = Field(default_factory=list)


class LayoutAddTubesToCarrierResponse(CommandResponse):
    return_parameters: LayoutAddTubesToCarrierReturnParameters = Field(
        default_factory=LayoutAddTubesToCarrierReturnParameters,
        alias="returnParameters",
    )


class HHSCreateDeviceReturnParameters(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")


class HHSDeviceInfo(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    node: int = 0
    connect_usb: bool = Field(False, alias="connectUsb")
    serial_number: str = Field("", alias="serialNumber")
    firmware_version: str = Field("", alias="firmwareVersion")


class HHSDeviceIdsReturnParameters(_ResponseModel):
    device_ids: list[HHSDeviceInfo] = Field(default_factory=list, alias="deviceIds")


class HHSDeviceStatus(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    shaking_speed: int = Field(0, alias="shakingSpeed")
    temperature: float = 0.0
    temp_control_status: str = Field("", alias="tempControlStatus")


class HHSStatusReturnParameters(_ResponseModel):
    device_ids: list[HHSDeviceStatus] = Field(default_factory=list, alias="deviceIds")


class HHSPlateLockReturnParameters(_ResponseModel):
    plate_lock_status: bool = Field(False, alias="plateLockStatus")


class HHSShakingStartedReturnParameters(_ResponseModel):
    shaking_started: str = Field("", alias="shakingStarted")


class HHSShakingStoppedReturnParameters(_ResponseModel):
    shaking_stopped: str = Field("", alias="shakingStopped")


class HHSTempControlStartedReturnParameters(_ResponseModel):
    temp_control_started: str = Field("", alias="tempControlStarted")


class HHSTempControlStoppedReturnParameters(_ResponseModel):
    temp_control_stopped: str = Field("", alias="tempControlStopped")


class HHSCreateDeviceResponse(CommandResponse):
    return_parameters: HHSCreateDeviceReturnParameters = Field(
        default_factory=HHSCreateDeviceReturnParameters,
        alias="returnParameters",
    )


class HHSDeviceIdsResponse(CommandResponse):
    return_parameters: HHSDeviceIdsReturnParameters = Field(
        default_factory=HHSDeviceIdsReturnParameters,
        alias="returnParameters",
    )


class HHSStatusResponse(CommandResponse):
    return_parameters: HHSStatusReturnParameters = Field(
        default_factory=HHSStatusReturnParameters,
        alias="returnParameters",
    )


class HHSPlateLockResponse(CommandResponse):
    return_parameters: HHSPlateLockReturnParameters = Field(
        default_factory=HHSPlateLockReturnParameters,
        alias="returnParameters",
    )


class HHSShakingStartedResponse(CommandResponse):
    return_parameters: HHSShakingStartedReturnParameters = Field(
        default_factory=HHSShakingStartedReturnParameters,
        alias="returnParameters",
    )


class HHSShakingStoppedResponse(CommandResponse):
    return_parameters: HHSShakingStoppedReturnParameters = Field(
        default_factory=HHSShakingStoppedReturnParameters,
        alias="returnParameters",
    )


class HHSTempControlStartedResponse(CommandResponse):
    return_parameters: HHSTempControlStartedReturnParameters = Field(
        default_factory=HHSTempControlStartedReturnParameters,
        alias="returnParameters",
    )


class HHSTempControlStoppedResponse(CommandResponse):
    return_parameters: HHSTempControlStoppedReturnParameters = Field(
        default_factory=HHSTempControlStoppedReturnParameters,
        alias="returnParameters",
    )


class HHCUnitInfo(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    serial_number: str = Field("", alias="serialNumber")
    firmware_version: str = Field("", alias="firmwareVersion")
    temperature: float = 0.0
    verification_date: str = Field("", alias="verificationDate")


class HHCConnectReturnParameters(_ResponseModel):
    chain_id: int = Field(0, alias="chainId")
    units: list[HHCUnitInfo] = Field(default_factory=list)


class HHCDeviceInfo(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    serial_number: str = Field("", alias="serialNumber")
    firmware_version: str = Field("", alias="firmwareVersion")


class HHCDeviceIdsReturnParameters(_ResponseModel):
    device_ids: list[HHCDeviceInfo] = Field(default_factory=list, alias="deviceIds")


class HHCUnitStatus(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    temperature: float = 0.0
    time_remaining: str = Field("", alias="timeRemaining")
    controlling: bool = False


class HHCStatusReturnParameters(_ResponseModel):
    device_ids: list[HHCUnitStatus] = Field(default_factory=list, alias="deviceIds")


class HHCTempControlReturnParameters(_ResponseModel):
    device_ids: list[int] = Field(default_factory=list, alias="deviceIds")
    target: float | None = None
    waited: bool = False


class HHCSelfDiagnosticEntry(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    enabled: bool = False


class HHCSelfDiagnosticReturnParameters(_ResponseModel):
    device_ids: list[HHCSelfDiagnosticEntry] = Field(default_factory=list, alias="deviceIds")


class HHCConnectResponse(CommandResponse):
    return_parameters: HHCConnectReturnParameters = Field(
        default_factory=HHCConnectReturnParameters,
        alias="returnParameters",
    )


class HHCDeviceIdsResponse(CommandResponse):
    return_parameters: HHCDeviceIdsReturnParameters = Field(
        default_factory=HHCDeviceIdsReturnParameters,
        alias="returnParameters",
    )


class HHCStatusResponse(CommandResponse):
    return_parameters: HHCStatusReturnParameters = Field(
        default_factory=HHCStatusReturnParameters,
        alias="returnParameters",
    )


class HHCTempControlResponse(CommandResponse):
    return_parameters: HHCTempControlReturnParameters = Field(
        default_factory=HHCTempControlReturnParameters,
        alias="returnParameters",
    )


class HHCSelfDiagnosticResponse(CommandResponse):
    return_parameters: HHCSelfDiagnosticReturnParameters = Field(
        default_factory=HHCSelfDiagnosticReturnParameters,
        alias="returnParameters",
    )


class ODTCUnitInfo(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    device_ip: str = Field("", alias="deviceIp")
    firmware_version: str = Field("", alias="firmwareVersion")
    serial_number: str = Field("", alias="serialNumber")
    manufacturer: str = ""
    state: str = ""


class ODTCConnectReturnParameters(_ResponseModel):
    unit: ODTCUnitInfo = Field(default_factory=ODTCUnitInfo)


class ODTCDeviceIdsReturnParameters(_ResponseModel):
    device_ids: list[int] = Field(default_factory=list, alias="deviceIds")


class ODTCUnitStatus(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    state: str = ""
    locked: bool = False
    door_open: bool = Field(False, alias="doorOpen")


class ODTCStatusReturnParameters(_ResponseModel):
    device_ids: list[ODTCUnitStatus] = Field(default_factory=list, alias="deviceIds")


class ODTCTemperatureReading(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    block_temperature: float = Field(0.0, alias="blockTemperature")
    lid_temperature: float = Field(0.0, alias="lidTemperature")


class ODTCTemperatureReturnParameters(_ResponseModel):
    device_ids: list[ODTCTemperatureReading] = Field(default_factory=list, alias="deviceIds")


class ODTCDeviceIdentificationReturnParameters(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    firmware_version: str = Field("", alias="firmwareVersion")
    serial_number: str = Field("", alias="serialNumber")
    manufacturer: str = ""


class ODTCProtocolRunReturnParameters(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    method_name: str = Field("", alias="methodName")
    request_id: str = Field("", alias="requestId")
    waited: bool = False
    #: The unit's own estimate of how long the run will take (None if it gave none).
    estimated_duration_seconds: float | None = Field(None, alias="estimatedDurationSeconds")


class ODTCRunDataReturnParameters(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    rows: list[dict[str, Any]] = Field(default_factory=list)


class ODTCConfigurationReturnParameters(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    xml: str = ""


class ODTCMethodInfo(_ResponseModel):
    name: str = ""
    kind: str = ""  # "PreMethod" (block + lid hold) or "Method" (stepped program)
    creator: str = ""
    target_block_temperature: float | None = Field(None, alias="targetBlockTemperature")
    target_lid_temperature: float | None = Field(None, alias="targetLidTemperature")
    step_count: int | None = Field(None, alias="stepCount")


class ODTCLogFile(_ResponseModel):
    remote: str = ""  # path on the unit's FTP server
    path: str = ""  # where it was saved locally
    size: int = 0  # bytes


class ODTCLogDownloadReturnParameters(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    directory: str = ""
    files: list[ODTCLogFile] = Field(default_factory=list)


class ODTCTraceSample(_ResponseModel):
    elapsed_ms: float = Field(0.0, alias="elapsedMs")
    target_temperature: float = Field(0.0, alias="targetTemperature")  # block target, degrees C
    current_temperature: float = Field(0.0, alias="currentTemperature")  # block actual, degrees C
    lid_temperature: float = Field(0.0, alias="lidTemperature")


class ODTCRunTraceReturnParameters(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    method_name: str = Field("", alias="methodName")
    started_at: str = Field("", alias="startedAt")  # the unit's clock, UTC
    remote: str = ""  # path on the unit's FTP server
    path: str = ""  # where the full trace file was saved locally
    rows: list[ODTCTraceSample] = Field(default_factory=list)


class ODTCMethodListReturnParameters(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    methods: list[ODTCMethodInfo] = Field(default_factory=list)


class ODTCConnectResponse(CommandResponse):
    return_parameters: ODTCConnectReturnParameters = Field(
        default_factory=ODTCConnectReturnParameters,
        alias="returnParameters",
    )


class ODTCDeviceIdsResponse(CommandResponse):
    return_parameters: ODTCDeviceIdsReturnParameters = Field(
        default_factory=ODTCDeviceIdsReturnParameters,
        alias="returnParameters",
    )


class ODTCStatusResponse(CommandResponse):
    return_parameters: ODTCStatusReturnParameters = Field(
        default_factory=ODTCStatusReturnParameters,
        alias="returnParameters",
    )


class ODTCTemperatureResponse(CommandResponse):
    return_parameters: ODTCTemperatureReturnParameters = Field(
        default_factory=ODTCTemperatureReturnParameters,
        alias="returnParameters",
    )


class ODTCDeviceIdentificationResponse(CommandResponse):
    return_parameters: ODTCDeviceIdentificationReturnParameters = Field(
        default_factory=ODTCDeviceIdentificationReturnParameters,
        alias="returnParameters",
    )


class ODTCProtocolRunResponse(CommandResponse):
    return_parameters: ODTCProtocolRunReturnParameters = Field(
        default_factory=ODTCProtocolRunReturnParameters,
        alias="returnParameters",
    )


class ODTCRunDataResponse(CommandResponse):
    return_parameters: ODTCRunDataReturnParameters = Field(
        default_factory=ODTCRunDataReturnParameters,
        alias="returnParameters",
    )


class ODTCConfigurationResponse(CommandResponse):
    return_parameters: ODTCConfigurationReturnParameters = Field(
        default_factory=ODTCConfigurationReturnParameters,
        alias="returnParameters",
    )


class ODTCLogDownloadResponse(CommandResponse):
    return_parameters: ODTCLogDownloadReturnParameters = Field(
        default_factory=ODTCLogDownloadReturnParameters,
        alias="returnParameters",
    )


class ODTCRunTraceResponse(CommandResponse):
    return_parameters: ODTCRunTraceReturnParameters = Field(
        default_factory=ODTCRunTraceReturnParameters,
        alias="returnParameters",
    )


class ODTCMethodListResponse(CommandResponse):
    return_parameters: ODTCMethodListReturnParameters = Field(
        default_factory=ODTCMethodListReturnParameters,
        alias="returnParameters",
    )


class InhecoTECDeviceSlot(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    device_type: int = Field(0, alias="deviceType")
    device_type_name: str = Field("", alias="deviceTypeName")


class InhecoTECConnectReturnParameters(_ResponseModel):
    controller_id: int = Field(0, alias="controllerId")
    controller_type: int = Field(0, alias="controllerType")
    controller_type_name: str = Field("", alias="controllerTypeName")
    devices: list[InhecoTECDeviceSlot] = Field(default_factory=list)


class InhecoTECIdentificationReturnParameters(_ResponseModel):
    controller_id: int = Field(0, alias="controllerId")
    device_id: int = Field(0, alias="deviceId")
    device_type: int = Field(0, alias="deviceType")
    device_type_name: str = Field("", alias="deviceTypeName")
    serial_number: str = Field("", alias="serialNumber")
    runtime_minutes: int = Field(0, alias="runtimeMinutes")
    calibration_date: str | None = Field(None, alias="calibrationDate")


class InhecoTECFirmwareReturnParameters(_ResponseModel):
    controller_id: int = Field(0, alias="controllerId")
    selector: int = 0
    selector_name: str = Field("", alias="selectorName")
    value: str = ""


class InhecoTECSensorValueReturnParameters(_ResponseModel):
    controller_id: int = Field(0, alias="controllerId")
    selector: int = 0
    selector_name: str = Field("", alias="selectorName")
    value: str = ""


class InhecoTECReservoirStatusReturnParameters(_ResponseModel):
    controller_id: int = Field(0, alias="controllerId")
    device_id: int = Field(0, alias="deviceId")
    status: int = 0
    status_name: str = Field("", alias="statusName")


class InhecoTECTemperatureStatusReturnParameters(_ResponseModel):
    controller_id: int = Field(0, alias="controllerId")
    device_id: int = Field(0, alias="deviceId")
    actual_temperature: float = Field(0.0, alias="actualTemperature")
    target_temperature: float = Field(0.0, alias="targetTemperature")
    temperature_min: float = Field(0.0, alias="temperatureMin")
    temperature_max: float = Field(0.0, alias="temperatureMax")
    heater_status: int = Field(0, alias="heaterStatus")
    heater_status_name: str = Field("", alias="heaterStatusName")


class InhecoTECShakerStatusReturnParameters(_ResponseModel):
    controller_id: int = Field(0, alias="controllerId")
    device_id: int = Field(0, alias="deviceId")
    status: int = 0
    status_name: str = Field("", alias="statusName")
    revolutions: int = 0
    shape: int = 0
    shape_name: str = Field("", alias="shapeName")


class InhecoTECRawReturnParameters(_ResponseModel):
    controller_id: int = Field(0, alias="controllerId")
    command: str = ""
    response: str = ""


class InhecoTECConnectResponse(CommandResponse):
    return_parameters: InhecoTECConnectReturnParameters = Field(
        default_factory=InhecoTECConnectReturnParameters,
        alias="returnParameters",
    )


class InhecoTECIdentificationResponse(CommandResponse):
    return_parameters: InhecoTECIdentificationReturnParameters = Field(
        default_factory=InhecoTECIdentificationReturnParameters,
        alias="returnParameters",
    )


class InhecoTECFirmwareResponse(CommandResponse):
    return_parameters: InhecoTECFirmwareReturnParameters = Field(
        default_factory=InhecoTECFirmwareReturnParameters,
        alias="returnParameters",
    )


class InhecoTECSensorValueResponse(CommandResponse):
    return_parameters: InhecoTECSensorValueReturnParameters = Field(
        default_factory=InhecoTECSensorValueReturnParameters,
        alias="returnParameters",
    )


class InhecoTECReservoirStatusResponse(CommandResponse):
    return_parameters: InhecoTECReservoirStatusReturnParameters = Field(
        default_factory=InhecoTECReservoirStatusReturnParameters,
        alias="returnParameters",
    )


class InhecoTECTemperatureStatusResponse(CommandResponse):
    return_parameters: InhecoTECTemperatureStatusReturnParameters = Field(
        default_factory=InhecoTECTemperatureStatusReturnParameters,
        alias="returnParameters",
    )


class InhecoTECShakerStatusResponse(CommandResponse):
    return_parameters: InhecoTECShakerStatusReturnParameters = Field(
        default_factory=InhecoTECShakerStatusReturnParameters,
        alias="returnParameters",
    )


class InhecoTECRawResponse(CommandResponse):
    return_parameters: InhecoTECRawReturnParameters = Field(
        default_factory=InhecoTECRawReturnParameters,
        alias="returnParameters",
    )


class TiltModuleConnectReturnParameters(_ResponseModel):
    system_id: int = Field(0, alias="systemId")
    com_port: str = Field("", alias="comPort")


class TiltModuleStatusReturnParameters(_ResponseModel):
    """``angle`` is the last *commanded* angle: the module has no position read-back."""

    system_id: int = Field(0, alias="systemId")
    module_name: str = Field("", alias="moduleName")
    initialized: bool = False
    angle: int | None = None
    powered: bool = False
    firmware_version: str = Field("", alias="firmwareVersion")
    busy: bool | None = None
    error_code: int | None = Field(None, alias="errorCode")
    error_message: str | None = Field(None, alias="errorMessage")
    query_error: str | None = Field(None, alias="queryError")


class TiltModuleConnectResponse(CommandResponse):
    return_parameters: TiltModuleConnectReturnParameters = Field(
        default_factory=TiltModuleConnectReturnParameters,
        alias="returnParameters",
    )


class TiltModuleStatusResponse(CommandResponse):
    return_parameters: TiltModuleStatusReturnParameters = Field(
        default_factory=TiltModuleStatusReturnParameters,
        alias="returnParameters",
    )


class MediaFillUnitInfo(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    com_port: int = Field(0, alias="comPort")
    instrument_id: int = Field(0, alias="instrumentId")
    firmware_version: str = Field("", alias="firmwareVersion")


class MediaFillConnectReturnParameters(MediaFillUnitInfo):
    simulated: bool = False
    #: ``"2.0"`` / ``"1.1"``: the vendor library in use; ``"simulated"`` for the SDK's simulator.
    vendor_api: str = Field("", alias="vendorApi")


class MediaFillDeviceIdsReturnParameters(_ResponseModel):
    device_ids: list[MediaFillUnitInfo] = Field(default_factory=list, alias="deviceIds")


class MediaFillPumpDirectionReturnParameters(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    pump_id: int = Field(0, alias="pumpId")
    direction: int = 0
    direction_name: str = Field("", alias="directionName")


class MediaFillLiquidLevelSensorStateReturnParameters(_ResponseModel):
    device_id: int = Field(0, alias="deviceId")
    pump_id: int = Field(0, alias="pumpId")
    liquid_level_sensor_state: int = Field(0, alias="liquidLevelSensorState")


class MediaFillLastErrorMessageReturnParameters(_ResponseModel):
    error_message: str = Field("", alias="errorMessage")


class MediaFillPumpStatus(_ResponseModel):
    pump_id: int = Field(0, alias="pumpId")
    direction: int = 0
    direction_name: str = Field("", alias="directionName")
    liquid_level_sensor_state: int = Field(0, alias="liquidLevelSensorState")


class MediaFillStatusReturnParameters(MediaFillUnitInfo):
    simulated: bool = False
    vendor_api: str = Field("", alias="vendorApi")
    pumps: list[MediaFillPumpStatus] = Field(default_factory=list)
    last_error_message: str = Field("", alias="lastErrorMessage")


class MediaFillConnectResponse(CommandResponse):
    return_parameters: MediaFillConnectReturnParameters = Field(
        default_factory=MediaFillConnectReturnParameters,
        alias="returnParameters",
    )


class MediaFillDeviceIdsResponse(CommandResponse):
    return_parameters: MediaFillDeviceIdsReturnParameters = Field(
        default_factory=MediaFillDeviceIdsReturnParameters,
        alias="returnParameters",
    )


class MediaFillPumpDirectionResponse(CommandResponse):
    return_parameters: MediaFillPumpDirectionReturnParameters = Field(
        default_factory=MediaFillPumpDirectionReturnParameters,
        alias="returnParameters",
    )


class MediaFillLiquidLevelSensorStateResponse(CommandResponse):
    return_parameters: MediaFillLiquidLevelSensorStateReturnParameters = Field(
        default_factory=MediaFillLiquidLevelSensorStateReturnParameters,
        alias="returnParameters",
    )


class MediaFillLastErrorMessageResponse(CommandResponse):
    return_parameters: MediaFillLastErrorMessageReturnParameters = Field(
        default_factory=MediaFillLastErrorMessageReturnParameters,
        alias="returnParameters",
    )


class MediaFillStatusResponse(CommandResponse):
    return_parameters: MediaFillStatusReturnParameters = Field(
        default_factory=MediaFillStatusReturnParameters,
        alias="returnParameters",
    )


class WXSTareReturnParameters(_ResponseModel):
    tare_weight: float = Field(0.0, alias="tareWeight")


class WXSGetWeightReturnParameters(_ResponseModel):
    weight_gramm: float = Field(0.0, alias="weightGramm")
    weight_stable: bool = Field(False, alias="weightStable")
    measured_weight: str = Field("", alias="measuredWeight")
    measured_unit: str = Field("", alias="measuredUnit")


class WXSTareResponse(CommandResponse):
    return_parameters: WXSTareReturnParameters = Field(
        default_factory=WXSTareReturnParameters,
        alias="returnParameters",
    )


class WXSGetWeightResponse(CommandResponse):
    return_parameters: WXSGetWeightReturnParameters = Field(
        default_factory=WXSGetWeightReturnParameters,
        alias="returnParameters",
    )


class _TrackingLabwareEntry(_WireModel):
    labware_id: str = Field(
        ...,
        validation_alias=AliasChoices("labwareId", "labware", "labware_id"),
        serialization_alias="labwareId",
    )

    # VENUS stores deck labware IDs lower-cased, and the tracking controller reads
    # this value from the case-preserved parameters (so barcodes keep their case),
    # so a mixed-case ID would be reported as "not on the current layout".
    @field_validator("labware_id")
    @classmethod
    def _lower_labware_id(cls, value: str) -> str:
        return value.lower()


class TrackingWellId(_WireModel):
    id: str


class TrackingLabwareQuery(_TrackingLabwareEntry):
    wells: list[TrackingWellId] | None = None

    @field_validator("wells", mode="before")
    @classmethod
    def _wrap_well_ids(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [{"id": well} if isinstance(well, str) else well for well in value]
        return value


class TrackingWellBarcode(_WireModel):
    id: str
    barcode: str


class TrackingLabwareBarcodes(_TrackingLabwareEntry):
    barcode: str | None = None
    wells: list[TrackingWellBarcode] | None = None


class TrackingWellVolume(_WireModel):
    id: str
    volume: float


class TrackingLabwareVolume(_TrackingLabwareEntry):
    volume: float | None = None
    wells: list[TrackingWellVolume] | None = None


class TrackingGetBarcodeLocationsParameters(_WireModel):
    barcodes: list[str]


class TrackingGetLabwareDetailsParameters(_WireModel):
    labware: list[TrackingLabwareQuery]


class TrackingSetBarcodesParameters(_WireModel):
    labware: list[TrackingLabwareBarcodes]


class TrackingSetLabwareVolumeParameters(_WireModel):
    labware: list[TrackingLabwareVolume]


class TrackingBarcodeLocation(_ResponseModel):
    barcode: str = ""
    labware_type: str = Field("", alias="labwareType")
    labware_id: str = Field("", alias="labwareId")
    well: str = ""

    @property
    def selector(self) -> str:
        """Position selector for this barcode: ``"<labware>@<well>"``, or the bare labware ID."""
        return f"{self.labware_id}@{self.well}" if self.well else self.labware_id


TrackedLabwareTypeFilter: TypeAlias = (
    TrackedLabwareType | str | list[TrackedLabwareType | str] | None
)


class TrackingBarcodeLocationsReturnParameters(_ResponseModel):
    barcodes: list[TrackingBarcodeLocation] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list, alias="notFound")
    total_barcodes_found: int = Field(0, alias="totalBarcodesFound")

    def to_positions(
        self,
        labware_type: TrackedLabwareTypeFilter = TrackedLabwareType.WELL,
        barcodes: list[str] | None = None,
    ) -> list[str]:
        """Convert the found barcodes into position selectors for pipetting and other steps.

        A barcode found on a well becomes ``"<labware>@<well>"``; one found on a rack
        (plate, tip rack, reservoir, ...) or a carrier becomes the bare labware ID --
        for a rack that selects all of its wells.

        Args:
            labware_type: Keep only barcodes whose ``labware_type`` matches: a
                TrackedLabwareType (``TEMPLATE`` = carrier, ``RACK``, ``WELL``,
                ``TIP_RACK``, ``RESERVOIR_RACK``), any ``labwareType`` string as
                reported by VENUS (e.g. ``"Reservoir Well"``), or a list of those.
                ``None`` keeps every barcode. Defaults to ``WELL``.
            barcodes: Keep only these barcodes and return them in this order (e.g.
                worklist order). Barcodes that were not found, or are of another
                type, are skipped. Defaults to every found barcode, as returned.
        """
        entries = self.barcodes
        if labware_type is not None:
            wanted = {
                item.value if isinstance(item, TrackedLabwareType) else item
                for item in (labware_type if isinstance(labware_type, list) else [labware_type])
            }
            entries = [entry for entry in entries if entry.labware_type in wanted]
        if barcodes is not None:
            by_barcode = {entry.barcode: entry for entry in entries}
            entries = [by_barcode[barcode] for barcode in barcodes if barcode in by_barcode]
        return [entry.selector for entry in entries]


class TrackingBarcodeLocationsResponse(CommandResponse):
    return_parameters: TrackingBarcodeLocationsReturnParameters = Field(
        default_factory=TrackingBarcodeLocationsReturnParameters,
        alias="returnParameters",
    )

    def to_positions(
        self,
        labware_type: TrackedLabwareTypeFilter = TrackedLabwareType.WELL,
        barcodes: list[str] | None = None,
    ) -> list[str]:
        """Shorthand for ``.return_parameters.to_positions(...)``."""
        return self.return_parameters.to_positions(labware_type=labware_type, barcodes=barcodes)


# VENUS sample tracking keeps no volume for these labware types or their wells:
# reservoirs are connected containers, tip racks and carriers hold no liquid.
_UNTRACKED_VOLUME_RACK_TYPES = frozenset(
    {
        TrackedLabwareType.RESERVOIR_RACK.value,
        TrackedLabwareType.TIP_RACK.value,
        TrackedLabwareType.TEMPLATE.value,
    }
)
_UNTRACKED_VOLUME_WELL_TYPES = _UNTRACKED_VOLUME_RACK_TYPES | {"Reservoir Well", "Tip Well"}
# Reservoir wells additionally carry no state and no well barcode.
_RESERVOIR_WELL_TYPES = frozenset({TrackedLabwareType.RESERVOIR_RACK.value, "Reservoir Well"})


class TrackedWellDetail(_ResponseModel):
    """Tracked state of one well.

    Fields VENUS does not track for the labware type are ``None``: ``volume`` for
    reservoirs (connected containers), tip racks and carriers; ``barcode`` and
    ``labware_state`` as well for reservoirs.
    """

    id: str = ""
    barcode: str | None = ""
    volume: float | None = 0.0
    labware_type: str = Field("", alias="labwareType")
    labware_state: str | None = Field("", alias="labwareState")
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    message: str = ""

    def _drop_untracked(self, labware_type: str) -> None:
        if labware_type in _UNTRACKED_VOLUME_WELL_TYPES:
            self.volume = None
        if labware_type in _RESERVOIR_WELL_TYPES:
            self.barcode = None
            self.labware_state = None

    @model_validator(mode="after")
    def _drop_untracked_fields(self) -> TrackedWellDetail:
        self._drop_untracked(self.labware_type)
        return self


class TrackedLabwareDetail(_ResponseModel):
    """Tracked state of one labware item; ``wells`` are sorted X ascending, then Y and Z descending."""

    labware_id: str = Field("", alias="labwareId")
    barcode: str = ""
    type: str = ""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    wells: list[TrackedWellDetail] = Field(default_factory=list)
    message: str = ""

    @model_validator(mode="after")
    def _normalize_wells(self) -> TrackedLabwareDetail:
        for well in self.wells:
            well._drop_untracked(self.type)
        self.wells.sort(key=lambda well: (well.x, -well.y, -well.z))
        return self


class TrackingLabwareDetailsReturnParameters(_ResponseModel):
    labware: list[TrackedLabwareDetail] = Field(default_factory=list)


class TrackingLabwareDetailsResponse(CommandResponse):
    return_parameters: TrackingLabwareDetailsReturnParameters = Field(
        default_factory=TrackingLabwareDetailsReturnParameters,
        alias="returnParameters",
    )


class TrackingSetBarcodesReturnParameters(_ResponseModel):
    total_labware_barcodes_set: int = Field(0, alias="totalLabwareBarcodesSet")
    total_well_barcodes_set: int = Field(0, alias="totalWellBarcodesSet")


class TrackingSetBarcodesResponse(CommandResponse):
    return_parameters: TrackingSetBarcodesReturnParameters = Field(
        default_factory=TrackingSetBarcodesReturnParameters,
        alias="returnParameters",
    )
