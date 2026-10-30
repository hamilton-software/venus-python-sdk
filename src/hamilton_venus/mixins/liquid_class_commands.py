"""Liquid Class command methods for StarClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hamilton_venus.liquid_class_library import (
    DEVICE_LABELS,
    LiquidClassSearchResult,
    TipTypeInfo,
    fitted_devices,
    normalize_device,
    normalize_dispense_mode,
    parse_tip_types,
    rank_candidates,
)
from hamilton_venus.models import (
    CommandResponse,
    GetLiquidClassParameters,
    GetLiquidClassResponse,
    LiquidClassDefinition,
    LiquidClassesParameters,
    LiquidClassesResponse,
    LiquidClassNamesParameters,
    LiquidDevicesResponse,
    LiquidNamesResponse,
    TipTypesResponse,
    UpdateLiquidClassParameters,
)
from hamilton_venus.tip_reach import TipReach, assess_tip_reach, container_depth

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient


class LiquidClassCommandsMixin:
    """Mixin providing Liquid Class commands."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    def pull_liquid_classes(self, names: list[str]) -> CommandResponse:
        """Pull liquid class definitions from the instrument database."""
        parameters = LiquidClassNamesParameters(names=names)
        return self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.pullLiquidClasses",
                parameters=parameters.model_dump(by_alias=True),
            )
        )

    def push_liquid_classes(self, names: list[str]) -> CommandResponse:
        """Push liquid class definitions to the instrument database.

        Not needed before pipetting: custom liquid classes a command uses are pushed
        automatically the first time a session uses them and whenever their JSON
        changes. Use this to load a set up front in one call.
        """
        parameters = LiquidClassNamesParameters(names=names)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.pushLiquidClasses",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        self._connected_instrument.liquid_class_sync.record_pushed(names)
        return response

    def get_liquid_devices(self) -> LiquidDevicesResponse:
        """Get the list of available liquid handling devices."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.getLiquidDevices",
            )
        )
        return LiquidDevicesResponse.model_validate(response.model_dump(by_alias=True))

    def get_liquid_names(self) -> LiquidNamesResponse:
        """Get the list of available liquid class names."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.getLiquidNames",
            )
        )
        return LiquidNamesResponse.model_validate(response.model_dump(by_alias=True))

    def get_liquid_classes(
        self,
        *,
        tip_type: int = -1,
        device: int = -1,
        dispense_mode: int = -1,
        is_original: int = -1,
        has_tadm_enabled: int = -1,
    ) -> LiquidClassesResponse:
        """Get liquid class names filtered by tip, device, dispense mode, and metadata flags."""
        parameters = LiquidClassesParameters(
            tip_type=tip_type,
            device=device,
            dispense_mode=dispense_mode,
            is_original=is_original,
            has_tadm_enabled=has_tadm_enabled,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.getLiquidClasses",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return LiquidClassesResponse.model_validate(response.model_dump(by_alias=True))

    def get_tip_types(self) -> TipTypesResponse:
        """Get the list of available tip types."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.getTipTypes",
            )
        )
        return TipTypesResponse.model_validate(response.model_dump(by_alias=True))

    def get_registered_tip_types(self) -> dict[int, TipTypeInfo]:
        """The tip types registered in VENUS, by tip type id: name, max liquid volume, max tip
        volume, tip length (whole tip) and length_below_channel (tip length minus the collar
        that sits on the channel up to its stop disk -- use this one for heights), filter,
        conductive, and the devices that can use each tip. A tip type that is not in this list
        cannot be used. Needs a started session, not a connected instrument."""
        return parse_tip_types(self.get_tip_types().return_parameters.tip_types)

    def find_liquid_classes(
        self,
        liquid: str,
        *,
        dispense_mode: Any = None,
        volume: float | None = None,
        tip_pool: str | None = None,
        tip_type: int | None = None,
        device: str | None = None,
        include_custom: bool = True,
        limit: int = 10,
    ) -> LiquidClassSearchResult:
        """Find the liquid classes that fit a transfer on this instrument, best first.

        Use this instead of picking a class by its name: a class is only right when its
        pipetting device is fitted on this instrument, its tip type is registered in VENUS and
        is the tip being used, its dispense mode fits the transfer, and the volume is in range.
        Raises ValueError, with the reason, for a device that is not fitted, a tip type that is
        not registered or cannot be used on the device, or a volume above the tip's maximum.

        Args:
            liquid: The liquid being transferred (e.g. "Water", "Ethanol 70%", "Serum"); the
                closest liquid wins when no class is made for it exactly.
            dispense_mode: JET_EMPTY ("jet_empty": no liquid contact, single dispense),
                JET_PART (no contact, multi-dispense), SURFACE_EMPTY (touching the liquid,
                single dispense), SURFACE_PART (touching, multi-dispense), or WHIPIP (MagPip
                sub-µL). A DispenseMode value or its name. None lists every mode.
            volume: Volume per channel in µL; checked against the tip's max liquid volume and
                each class's volume range.
            tip_pool: The tip pool the transfer picks up from; its loaded tip type is used.
            tip_type: A tip type id (see get_registered_tip_types) instead of tip_pool.
            device: "1mL", "5mL", "MagPip", "MPH96" or "MPH384" (or channels_1000ul, ...).
                Default: the fitted device the tip can be used on, 1 mL channels first.
            include_custom: Also list custom (User) liquid classes.
            limit: How many candidates to return.
        """
        notes: list[str] = []
        if tip_pool is not None:
            tip_type = self.tip_pool_get_tip_counter(tip_pool).return_parameters.tip_type  # type: ignore[attr-defined]
        if tip_type is None:
            raise ValueError("Pass tip_pool (the pool the transfer picks tips from) or tip_type.")

        registered = self.get_registered_tip_types()
        tip = registered.get(int(tip_type))
        if tip is None:
            raise ValueError(f"Tip type {tip_type} is not registered in VENUS, so it cannot be used. "
                             "get_registered_tip_types lists the registered ones.")

        try:
            fitted: set[str] | None = fitted_devices(self.instrument_get_configuration())  # type: ignore[attr-defined]
        except Exception:
            fitted = None
            notes.append("The instrument configuration could not be read (not connected?), so the device "
                         "was not checked against the fitted hardware.")

        if device is None:
            usable = [d for d in tip.devices() if fitted is None or d in fitted]
            if not usable:
                raise ValueError(f"No fitted device can use {tip.name} (tip type {tip.id}); it is for "
                                 f"{', '.join(tip.liquid_devices)}.")
            device = usable[0]
        device = normalize_device(device)
        if fitted is not None and device not in fitted:
            have = ", ".join(DEVICE_LABELS[d] for d in sorted(fitted)) or "no pipetting device"
            raise ValueError(f"This instrument has no {DEVICE_LABELS[device]}; it has {have}. "
                             "Choose a liquid class for a fitted device.")
        if not tip.usable_on(device):
            raise ValueError(f"{tip.name} (tip type {tip.id}) cannot be used on the {DEVICE_LABELS[device]}; "
                             f"it is for {', '.join(tip.liquid_devices)}.")
        if volume is not None and tip.max_liquid_volume and volume > tip.max_liquid_volume:
            raise ValueError(f"{volume:g} µL is more than {tip.name} holds ({tip.max_liquid_volume:g} µL max liquid "
                             "volume). Use a larger tip or split the transfer.")

        mode = normalize_dispense_mode(dispense_mode) if dispense_mode is not None else None
        library = self._connected_instrument.liquid_class_library
        if not library.available:
            notes.append(f"No local liquid class library at {library.root / library.instrument_folder}.")
        candidates, rank_notes = rank_candidates(
            library, liquid=liquid, device=device, tip_type_id=tip.id, dispense_mode=mode,
            volume=volume, include_custom=include_custom, limit=limit,
        )
        return LiquidClassSearchResult(
            instrument=library.instrument_folder, device=device, device_label=DEVICE_LABELS[device],
            tip_type_id=tip.id, tip=tip, dispense_mode=mode, liquid=liquid, volume=volume,
            candidates=candidates, notes=notes + rank_notes,
        )

    def check_tip_reach(
        self,
        labware_name: str,
        *,
        tip_pool: str | None = None,
        tip_type: int | None = None,
        device: str = "1mL",
        height_from_bottom: float = 0.0,
    ) -> TipReach:
        """Check that a tip is long enough for a labware's wells or tubes, before pipetting in them.

        A tip reaches only its length below the channel (full length minus the collar on the
        channel). Pipetting deeper into a container than that puts the channel itself inside the
        container, where it can touch the wall: a contamination
        risk (e.g. a 50 µL tip in a 100 mm tube). ``ok`` is False then, ``message`` says why, and
        ``longer_tips`` lists registered tips long enough on this device. Pipetting commands make
        the same check on their own and report it through ``pop_command_warnings``.

        Args:
            labware_name: Labware on the deck (its deepest container is used).
            tip_pool: The tip pool the transfer picks up from, or ``tip_type`` (a tip type id).
            device: "1mL", "5mL", "MagPip", "MPH96" or "MPH384".
            height_from_bottom: Lowest the tip end goes, in mm above the container bottom: the
                fixed height when pipetting at a fixed height without liquid level detection,
                0 with liquid level detection (it can follow the liquid to the bottom).
        """
        if tip_pool is not None:
            tip_type = self.tip_pool_get_tip_counter(tip_pool).return_parameters.tip_type  # type: ignore[attr-defined]
        if tip_type is None:
            raise ValueError("Pass tip_pool or tip_type.")
        registered = self.get_registered_tip_types()
        tip = registered.get(int(tip_type))
        if tip is None:
            raise ValueError(f"Tip type {tip_type} is not registered in VENUS.")
        definition = self.labware_get_params_from_id(labware_name).return_parameters.definition  # type: ignore[attr-defined]
        depth = container_depth(definition)
        if depth is None:
            raise ValueError(f"{labware_name} has no containers with a depth in its definition.")
        return assess_tip_reach(
            tip, labware=labware_name, depth=depth, lowest_tip_height=height_from_bottom,
            device=normalize_device(device), registered=registered, fixed_height=height_from_bottom > 0,
        )

    def get_liquid_class(self, name: str) -> GetLiquidClassResponse:
        """Get the full definition of a single liquid class by name."""
        parameters = GetLiquidClassParameters(name=name)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.getLiquidClass",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return GetLiquidClassResponse.model_validate(response.model_dump(by_alias=True))

    def update_liquid_class(self, definition: LiquidClassDefinition) -> CommandResponse:
        """Update an existing liquid class definition on the instrument."""
        parameters = UpdateLiquidClassParameters(definition=definition)
        return self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.updateLiquidClass",
                parameters=parameters.model_dump(by_alias=True),
            )
        )

