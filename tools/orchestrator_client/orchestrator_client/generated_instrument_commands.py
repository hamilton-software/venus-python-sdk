"""GENERATED FILE -- do not hand-edit.

Produced by generate_instrument_commands.py from
hamilton_venus_mcp.catalog.CATALOG_BY_INSTRUMENT. Re-run that script (needs an
environment with hamilton-venus-sdk and hamilton-venus-mcp installed) after a
StarClient/VantageClient SDK command changes, and commit the diff.

Every method here is a thin, typed wrapper that calls self.call(name, **kwargs) --
see instrument.py's Instrument class, which mixes this module's _GeneratedCommands in.
Stdlib-only: no hamilton_venus or hamilton_venus_mcp import, so this file can run on a
thin orchestrator PC that has neither package installed.
"""

from __future__ import annotations

from typing import Any, Literal


class _GeneratedCommands:
    """One typed method per StarClient/VantageClient command -- see module docstring. Mixed into instrument.Instrument; every method below calls self.call(name, **kwargs)."""

    # ---- AddReagentCommand ----

    def add_reagent(self, *, reagent_source: Any, dest_plate: Any, volume: float, tip_pool: str, liquid_class: str | list[str], multi_dispense: bool = False, pre_aliquot_volume: float = 0.0, pre_aliquot_disposal: Literal['source', 'waste'] = 'source', post_aliquot_volume: float = 0.0, post_aliquot_height: float = 5.0, channels: list[int] | None = None, optimized_tip_pickup: bool = True, reuse_tips: bool = False, aspirate_settings: Any = None, dispense_settings: Any = None, error_profile: Any = None, transfer_csv: str | None = None, follow_csv_order: bool = False) -> Any:
        """Transfer reagent from a source location to multiple destination wells.

        See :func:`~hamilton_venus.compound_commands.add_reagent.execute_add_reagent`
        for full parameter documentation.

        reagent_source: real type is 'str | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("add_reagent") for its full schema.
        dest_plate: real type is 'str | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("add_reagent") for its full schema.
        aspirate_settings: real type is 'AspirateSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("add_reagent") for its full schema.
        dispense_settings: real type is 'DispenseSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("add_reagent") for its full schema.
        error_profile: real type is 'ErrorProfile | None' -- not representable as a plain type hint here; see describe_sdk_command("add_reagent") for its full schema.
        """
        return self.call("add_reagent", reagent_source=reagent_source, dest_plate=dest_plate, volume=volume, tip_pool=tip_pool, liquid_class=liquid_class, multi_dispense=multi_dispense, pre_aliquot_volume=pre_aliquot_volume, pre_aliquot_disposal=pre_aliquot_disposal, post_aliquot_volume=post_aliquot_volume, post_aliquot_height=post_aliquot_height, channels=channels, optimized_tip_pickup=optimized_tip_pickup, reuse_tips=reuse_tips, aspirate_settings=aspirate_settings, dispense_settings=dispense_settings, error_profile=error_profile, transfer_csv=transfer_csv, follow_csv_order=follow_csv_order)

    # ---- Autoload ----

    def autoload_get_carrier_sensor_status(self) -> Any:
        """Return carrier sensor availability and occupancy status across tracks."""
        return self.call("autoload_get_carrier_sensor_status")

    def autoload_is_track_occupied(self, *, track_id: int) -> Any:
        """Return whether the specified autoload track currently holds a carrier."""
        return self.call("autoload_is_track_occupied", track_id=track_id)

    def autoload_load_carrier_by_id(self, *, carrier_id: str, scan_positions: Literal['?', '*', ''] | list[int] | None = None) -> Any:
        """Load a carrier by carrier identifier, optionally scanning positions.

        When *scan_positions* is set, the response's ``barcode_returns``
        carries one entry per barcode position of the carrier (``MlStarCarCountOfBCPos``),
        empty for positions not scanned -- see
        :class:`~hamilton_venus.models.command_types.AutoloadLoadCarrierReturnParameters`.

        A carrier that is already pushed in: on the STAR, unload it first (check
        :meth:`autoload_get_carrier_sensor_status`); on the Vantage, the load step
        unloads it itself, and an unload before the load raises a load tray error.
        """
        return self.call("autoload_load_carrier_by_id", carrier_id=carrier_id, scan_positions=scan_positions)

    def autoload_load_carrier_by_track(self, *, track_id: int, scan_positions: Literal['?', '*', ''] | list[int] | None = None) -> Any:
        """Load a carrier from the specified track, optionally scanning positions.

        When *scan_positions* is set, the response's ``barcode_returns``
        carries one entry per barcode position of the carrier (``MlStarCarCountOfBCPos``),
        empty for positions not scanned -- see
        :class:`~hamilton_venus.models.command_types.AutoloadLoadCarrierReturnParameters`.

        A carrier that is already pushed in: on the STAR, unload it first (check
        :meth:`autoload_get_carrier_sensor_status`); on the Vantage, the load step
        unloads it itself, and an unload before the load raises a load tray error.
        """
        return self.call("autoload_load_carrier_by_track", track_id=track_id, scan_positions=scan_positions)

    def autoload_move(self, *, track_id: int) -> Any:
        """Move the autoload shuttle to the specified deck track."""
        return self.call("autoload_move", track_id=track_id)

    def autoload_park_left(self) -> Any:
        """Park the autoload shuttle at its left-most position."""
        return self.call("autoload_park_left")

    def autoload_park_right(self) -> Any:
        """Park the autoload shuttle at its right-most position."""
        return self.call("autoload_park_right")

    def autoload_unload_carrier_by_id(self, *, carrier_id: str) -> Any:
        """Unload a carrier using its configured carrier identifier."""
        return self.call("autoload_unload_carrier_by_id", carrier_id=carrier_id)

    def autoload_unload_carrier_by_track(self, *, track_id: int) -> Any:
        """Unload a carrier from the specified deck track."""
        return self.call("autoload_unload_carrier_by_track", track_id=track_id)

    # ---- BalanceDeviceCommands ----

    def wxs_get_weight(self, *, weigh_immediately: bool | None = None) -> Any:
        """Get a stable or dynamic weight value from the scale.

        Parameters
        ----------
        weigh_immediately:
            Immediately get the current weight value (optional).

        Returns
        -------
        WXSGetWeightResponse
            ``weight_gramm``: Measured weight value in grams.
            ``weight_stable``: Whether the measured value was stable.
            ``measured_weight``: Raw measured weight from the scale.
            ``measured_unit``: Measured unit from the scale.
        """
        return self.call("wxs_get_weight", weigh_immediately=weigh_immediately)

    def wxs_initialize_balance(self, *, port: int, time_out_seconds: int | None = None, trials: int | None = None) -> Any:
        """Establish a connection to the balance.

        Parameters
        ----------
        port:
            COM-Port number the device is connected to.
        time_out_seconds:
            Time after which a timeout occurs (optional, 0-60).
        trials:
            Number of trials to establish a connection (optional, 1-10).
        """
        return self.call("wxs_initialize_balance", port=port, time_out_seconds=time_out_seconds, trials=trials)

    def wxs_internal_calibration(self) -> Any:
        """Start an internal adjustment procedure of the scale."""
        return self.call("wxs_internal_calibration")

    def wxs_reset_scale(self) -> Any:
        """Reset the scale."""
        return self.call("wxs_reset_scale")

    def wxs_set_scale_parameters(self, *, weighing_mode: int | None = None, vibration: int | None = None, stability: int | None = None, weight_unit: int | None = None, auto_zero: bool | None = None) -> Any:
        """Set general scale parameters.

        Parameters
        ----------
        weighing_mode:
            Weighing mode (optional): 0 = Normal, 1 = Dosing.
        vibration:
            Weight value release filter (optional):
            0 = Very fast, 1 = Fast, 2 = Reliable and fast,
            3 = Reliable, 4 = Very reliable.
        stability:
            Ambient condition optimisation (optional):
            0 = Very stable, 1 = Stable, 2 = Standard,
            3 = Unstable, 4 = Very unstable, 5 = Automatic.
        weight_unit:
            Output weighing unit (optional):
            0 = g, 1 = kg, 2 = t, 3 = mg, 4 = µg, 5 = ct, 6 = N,
            7 = lb, 8 = oz, 9 = ozt, 10 = GN, 11 = dwt, 12 = mom,
            13 = msg, 14 = tlh, 15 = tls, 16 = tlt, 17 = tcl,
            18 = tola, 19 = baht, 20 = lb[oz], 21 = ton,
            25 = no unit, 26 = PCS, 27 = %, 28 = cu1, 29 = cu2,
            30 = Currency unit 1, 31 = Currency unit 2.
        auto_zero:
            Enable or disable the auto zero function (optional).
        """
        return self.call("wxs_set_scale_parameters", weighing_mode=weighing_mode, vibration=vibration, stability=stability, weight_unit=weight_unit, auto_zero=auto_zero)

    def wxs_set_zero(self, *, zero_immediately: bool | None = None) -> Any:
        """Set a new zero point on the scale.

        Clears the tare memory. All weight values (including tare weight) will be
        measured relative to this new zero.

        Parameters
        ----------
        zero_immediately:
            Set a new zero immediately, regardless of balance stability (optional).
        """
        return self.call("wxs_set_zero", zero_immediately=zero_immediately)

    def wxs_tare(self, *, tare_immediately: bool | None = None) -> Any:
        """Tare the scale.

        Note: Call ``wxs_set_zero`` before using this method.
        Having negative weight on the scale may lead to an error.

        Parameters
        ----------
        tare_immediately:
            Tare the balance immediately and independently of balance stability (optional).

        Returns
        -------
        WXSTareResponse
            ``tare_weight``: The tare weight value corresponding to the weight change on the balance.
        """
        return self.call("wxs_tare", tare_immediately=tare_immediately)

    def wxs_terminate_balance(self) -> Any:
        """Terminate the connection to the balance."""
        return self.call("wxs_terminate_balance")

    # ---- Channel ----

    def aspirate(self, *, positions: Any, channels: list[int] | None = None, volumes: float | list[float], liquid_class: str | list[str], settings: Any = None, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', mad_enabled: bool | None = None, mad_threshold: int | None = None, adc: bool | None = None) -> Any:
        """Aspirate liquid with channels (implementation method).

        The SDK accepts flexible ``positions`` input (selector DSL strings,
        ``Position`` objects, or wire-format dicts) and normalizes them into
        concrete ``LabwareWell[]`` entries required by the wire contract.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.
            positions: Target positions as selector DSL, explicit wells, or
                dicts.  Examples: ``"Plate1@col:1"``, ``"Plate1@A1,B1"``.
            volumes: Aspirate volume(s) in uL. Scalar applies uniformly;
                a list must match the number of channels.
            liquid_class: Liquid class name. Scalar or per-channel list.
            settings: Reusable :class:`AspirateSettings` object controlling
                LLD, mixing, submerge depth, touch-off, and other behaviors.
            well_order: Well expansion order for selector inputs.
            mad_enabled: Enable Monitored Air Displacement. Single value for
                all channels (not per-channel). ``None`` (default) omits the
                field from the wire call, so VENUS applies its own default
                (disabled).
            mad_threshold: MAD pressure threshold. Range 1-1023. Single value
                for all channels. ``None`` (default) omits the field, so
                VENUS applies its own default (``30``).
            adc: Enable Aspiration/Dispense Control (TADM-based). Single
                value for all channels. ``None`` (default) omits the field,
                so VENUS applies its own default (disabled).

        positions: real type is 'str | list | dict | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("aspirate") for its full schema.
        settings: real type is 'AspirateSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("aspirate") for its full schema.
        """
        return self.call("aspirate", positions=positions, channels=channels, volumes=volumes, liquid_class=liquid_class, settings=settings, well_order=well_order, mad_enabled=mad_enabled, mad_threshold=mad_threshold, adc=adc)

    def detect_liquid_level(self, *, positions: Any, channels: list[int] | None = None, capacitive_lld: Literal[0, 1, 2, 3, 4, 5] = 1, pressure_lld: Literal[0, 1, 2, 3, 4, 5] = 0, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc') -> Any:
        """Detect liquid level with channels (implementation method).

        Perform capacitive and/or pressure-based liquid-level detection at
        the specified positions.  ``positions`` may be passed as selector
        DSL input and is normalized to explicit wire-format positions.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.
            positions: Target positions as selector DSL, explicit wells, or
                dicts.
            capacitive_lld: Capacitive LLD sensitivity. Defaults to
                ``CapacitiveLLD.MAX``.
            pressure_lld: Pressure LLD sensitivity. Defaults to
                ``PressureLLD.OFF``.
            well_order: Well expansion order for selector inputs.

        positions: real type is 'str | list | dict | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("detect_liquid_level") for its full schema.
        """
        return self.call("detect_liquid_level", positions=positions, channels=channels, capacitive_lld=capacitive_lld, pressure_lld=pressure_lld, well_order=well_order)

    def dispense(self, *, positions: Any, channels: list[int] | None = None, volumes: float | list[float], settings: Any = None, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', adc: bool | None = None) -> Any:
        """Dispense liquid with channels (implementation method).

        The SDK accepts flexible ``positions`` input (selector DSL strings,
        ``Position`` objects, or wire-format dicts) and normalizes them into
        the vector-style payload compatible with the current VENUS helper path.

        Dispense has no liquid-class parameter of its own — the liquid class
        used is whichever one the tip aspirated with.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.
            positions: Target positions as selector DSL, explicit wells, or
                dicts.  Examples: ``"Plate1@col:1"``, ``"Plate1@A1,B1"``.
            volumes: Dispense volume(s) in uL. Scalar applies uniformly;
                a list must match the number of channels.
            adc: Enable Aspiration/Dispense Control (TADM-based). Single
                value for all channels (not per-channel). ``None`` (default)
                omits the field from the wire call, so VENUS applies its own
                default (disabled).
            settings: Reusable :class:`DispenseSettings` object controlling
                dispense mode, LLD, mixing, touch-off, and side-touch.
            well_order: Well expansion order for selector inputs.

        positions: real type is 'str | list | dict | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("dispense") for its full schema.
        settings: real type is 'DispenseSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("dispense") for its full schema.
        """
        return self.call("dispense", positions=positions, channels=channels, volumes=volumes, settings=settings, well_order=well_order, adc=adc)

    def dispense_on_the_fly(self, *, channels: list[int], labware_name: str, volumes: float | list[float], labware_surface_distance: float, start_x_offset: float = 0.0, x_speed: float = 0.0, x_acceleration_distance: float = 8.0, dispense_direction: int = 0, excluded_positions: list[str] | None = None) -> Any:
        """Dispense across wells while translating in X on a single pass (implementation method)."""
        return self.call("dispense_on_the_fly", channels=channels, labware_name=labware_name, volumes=volumes, labware_surface_distance=labware_surface_distance, start_x_offset=start_x_offset, x_speed=x_speed, x_acceleration_distance=x_acceleration_distance, dispense_direction=dispense_direction, excluded_positions=excluded_positions)

    def get_status(self) -> Any:
        """Return the current X/Y/Z position and tip-loaded status for every channel (implementation method)."""
        return self.call("get_status")

    def move_axis(self, *, channels: list[int] | int, x: float | None = None, y: float | list[float] | None = None, z: float | list[float] | None = None, safety_bypass_token: str | None = None) -> Any:
        """Move channels directly to absolute X/Y/Z coordinates (implementation method).

        Args:
            channels: Channel number(s) to move.
            x: Target absolute X position in mm. Shared by all channels
                (the gantry moves as one unit in X); a single value only.
            y: Target absolute Y position(s) in mm. A single value applies to
                every channel; a list must match the number of channels.
            z: Target absolute Z position(s) in mm. A single value applies to
                every channel; a list must match the number of channels.
            safety_bypass_token: Optional token to bypass safety checks. VENUS
                runs its normal safety validation when this is omitted; pass
                the exact literal :data:`hamilton_venus.OVERRIDE_SAFETY_CHECKS`
                to bypass it. It is not an arbitrary flag -- any other string
                is rejected.

                .. warning::

                   Bypassing safety checks risks collisions that can damage hardware
                   or cause injury. Using this token waives vendor liability for any
                   resulting damage.
        """
        return self.call("move_axis", channels=channels, x=x, y=y, z=z, safety_bypass_token=safety_bypass_token)

    def move_axis_relative(self, *, channels: list[int] | int, x: float | None = None, y: float | list[float] | None = None, z: float | list[float] | None = None, safety_bypass_token: str | None = None) -> Any:
        """Move 1 mL channels by a relative X/Y/Z offset.

        VENUS's ``channels.1mL.moveAxis`` only accepts absolute coordinates —
        there is no relative mode. This first calls :meth:`get_status` for
        each requested channel's current position, adds the requested offset
        to each coordinate, and issues :meth:`move_axis` with the resolved
        absolute values.

        Args:
            channels: Channel number(s) to move.
            x: Offset to apply to the shared X position in mm. A single
                value only (X is shared by all channels).
            y: Offset(s) to apply to each channel's Y position in mm. A
                single value applies to every channel; a list must match the
                number of channels.
            z: Offset(s) to apply to each channel's Z position in mm. A
                single value applies to every channel; a list must match the
                number of channels.
            safety_bypass_token: Optional token to bypass safety checks. VENUS
                runs its normal safety validation when this is omitted; pass
                the exact literal :data:`hamilton_venus.OVERRIDE_SAFETY_CHECKS`
                to bypass it. It is not an arbitrary flag -- any other string
                is rejected.

                .. warning::

                   Bypassing safety checks risks collisions that can damage hardware
                   or cause injury. Using this token waives vendor liability for any
                   resulting damage.
        """
        return self.call("move_axis_relative", channels=channels, x=x, y=y, z=z, safety_bypass_token=safety_bypass_token)

    def tip_check(self) -> Any:
        """Return current tip status for active channels (implementation method)."""
        return self.call("tip_check")

    def tip_eject(self, *, channels: list[int] | None = None, eject_mode: Literal['waste', 'return', 'positions', 'tipPool'] = 'waste', positions: Any = None, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', tip_pool: str | None = None) -> Any:
        """Eject tips (implementation method).

        Supports multiple ejection modes:

        1. **Waste mode** (default): Eject to default waste location.
           ``tip_eject(channels=[1,2,3])``

        2. **Return mode**: Return tips to pickup positions.
           ``tip_eject(channels=[1,2,3], eject_mode=EjectMode.RETURN)``

        3. **Explicit positions mode**: Eject to specific locations.
           ``tip_eject(channels=[1,2,3], eject_mode=EjectMode.POSITIONS, positions="TipRack@col:1")``

        4. **TipPool mode**: Return tips to an empty slot in a managed pool.
           ``tip_eject(channels=[1,2,3], eject_mode=EjectMode.TIP_POOL, tip_pool="TransferTips")``

        When positions are provided, the SDK accepts position selector DSL inputs
        and normalizes them into concrete wire-format positions.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.

        positions: real type is 'str | list | dict | list | Position | list | None' -- not representable as a plain type hint here; see describe_sdk_command("tip_eject") for its full schema.
        """
        return self.call("tip_eject", channels=channels, eject_mode=eject_mode, positions=positions, well_order=well_order, tip_pool=tip_pool)

    def tip_pickup(self, *, channels: list[int] | None = None, positions: Any = None, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', tip_pool: str | None = None, optimized_pickup: bool = True) -> Any:
        """Pick up tips (implementation method).

        Supports two picking modes:

        1. **Manual mode**: Pick tips from explicit positions.
           ``tip_pickup(channels=[1,2,3], positions="TipRack@col:1")``

        2. **TipPool mode**: Pick tips from a managed pool.
           ``tip_pickup(channels=[1,2,3], tip_pool="TransferTips", optimized_pickup=True)``

        When using manual mode, the SDK accepts position selector DSL inputs
        (e.g., "TipRack@col:1") and normalizes them into concrete ``labwareId``/``wellId``
        entries.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.

        positions: real type is 'str | list | dict | list | Position | list | None' -- not representable as a plain type hint here; see describe_sdk_command("tip_pickup") for its full schema.
        """
        return self.call("tip_pickup", channels=channels, positions=positions, well_order=well_order, tip_pool=tip_pool, optimized_pickup=optimized_pickup)

    # ---- Channels5mL ----

    def aspirate_5ml(self, *, positions: Any, channels: list[int] | None = None, volumes: float | list[float], liquid_class: str | list[str], settings: Any = None, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', mad_enabled: bool | None = None, mad_threshold: int | None = None, adc: bool | None = None) -> Any:
        """Aspirate liquid with channels (implementation method).

        The SDK accepts flexible ``positions`` input (selector DSL strings,
        ``Position`` objects, or wire-format dicts) and normalizes them into
        concrete ``LabwareWell[]`` entries required by the wire contract.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.
            positions: Target positions as selector DSL, explicit wells, or
                dicts.  Examples: ``"Plate1@col:1"``, ``"Plate1@A1,B1"``.
            volumes: Aspirate volume(s) in uL. Scalar applies uniformly;
                a list must match the number of channels.
            liquid_class: Liquid class name. Scalar or per-channel list.
            settings: Reusable :class:`AspirateSettings` object controlling
                LLD, mixing, submerge depth, touch-off, and other behaviors.
            well_order: Well expansion order for selector inputs.
            mad_enabled: Enable Monitored Air Displacement. Single value for
                all channels (not per-channel). ``None`` (default) omits the
                field from the wire call, so VENUS applies its own default
                (disabled).
            mad_threshold: MAD pressure threshold. Range 1-1023. Single value
                for all channels. ``None`` (default) omits the field, so
                VENUS applies its own default (``30``).
            adc: Enable Aspiration/Dispense Control (TADM-based). Single
                value for all channels. ``None`` (default) omits the field,
                so VENUS applies its own default (disabled).

        positions: real type is 'str | list | dict | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("aspirate_5ml") for its full schema.
        settings: real type is 'AspirateSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("aspirate_5ml") for its full schema.
        """
        return self.call("aspirate_5ml", positions=positions, channels=channels, volumes=volumes, liquid_class=liquid_class, settings=settings, well_order=well_order, mad_enabled=mad_enabled, mad_threshold=mad_threshold, adc=adc)

    def detect_liquid_level_5ml(self, *, positions: Any, channels: list[int] | None = None, capacitive_lld: Literal[0, 1, 2, 3, 4, 5] = 1, pressure_lld: Literal[0, 1, 2, 3, 4, 5] = 0, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc') -> Any:
        """Detect liquid level with channels (implementation method).

        Perform capacitive and/or pressure-based liquid-level detection at
        the specified positions.  ``positions`` may be passed as selector
        DSL input and is normalized to explicit wire-format positions.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.
            positions: Target positions as selector DSL, explicit wells, or
                dicts.
            capacitive_lld: Capacitive LLD sensitivity. Defaults to
                ``CapacitiveLLD.MAX``.
            pressure_lld: Pressure LLD sensitivity. Defaults to
                ``PressureLLD.OFF``.
            well_order: Well expansion order for selector inputs.

        positions: real type is 'str | list | dict | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("detect_liquid_level_5ml") for its full schema.
        """
        return self.call("detect_liquid_level_5ml", positions=positions, channels=channels, capacitive_lld=capacitive_lld, pressure_lld=pressure_lld, well_order=well_order)

    def dispense_5ml(self, *, positions: Any, channels: list[int] | None = None, volumes: float | list[float], settings: Any = None, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', adc: bool | None = None) -> Any:
        """Dispense liquid with channels (implementation method).

        The SDK accepts flexible ``positions`` input (selector DSL strings,
        ``Position`` objects, or wire-format dicts) and normalizes them into
        the vector-style payload compatible with the current VENUS helper path.

        Dispense has no liquid-class parameter of its own — the liquid class
        used is whichever one the tip aspirated with.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.
            positions: Target positions as selector DSL, explicit wells, or
                dicts.  Examples: ``"Plate1@col:1"``, ``"Plate1@A1,B1"``.
            volumes: Dispense volume(s) in uL. Scalar applies uniformly;
                a list must match the number of channels.
            adc: Enable Aspiration/Dispense Control (TADM-based). Single
                value for all channels (not per-channel). ``None`` (default)
                omits the field from the wire call, so VENUS applies its own
                default (disabled).
            settings: Reusable :class:`DispenseSettings` object controlling
                dispense mode, LLD, mixing, touch-off, and side-touch.
            well_order: Well expansion order for selector inputs.

        positions: real type is 'str | list | dict | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("dispense_5ml") for its full schema.
        settings: real type is 'DispenseSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("dispense_5ml") for its full schema.
        """
        return self.call("dispense_5ml", positions=positions, channels=channels, volumes=volumes, settings=settings, well_order=well_order, adc=adc)

    def dispense_on_the_fly_5ml(self, *, channels: list[int], labware_name: str, volumes: float | list[float], labware_surface_distance: float, start_x_offset: float = 0.0, x_speed: float = 0.0, x_acceleration_distance: float = 8.0, dispense_direction: int = 0, excluded_positions: list[str] | None = None) -> Any:
        """Dispense across wells while translating in X on a single pass (implementation method)."""
        return self.call("dispense_on_the_fly_5ml", channels=channels, labware_name=labware_name, volumes=volumes, labware_surface_distance=labware_surface_distance, start_x_offset=start_x_offset, x_speed=x_speed, x_acceleration_distance=x_acceleration_distance, dispense_direction=dispense_direction, excluded_positions=excluded_positions)

    def get_status_5ml(self) -> Any:
        """Return the current X/Y/Z position and tip-loaded status for every channel (implementation method)."""
        return self.call("get_status_5ml")

    def move_axis_5ml(self, *, channels: list[int] | int, x: float | None = None, y: float | list[float] | None = None, z: float | list[float] | None = None, safety_bypass_token: str | None = None) -> Any:
        """Move channels directly to absolute X/Y/Z coordinates (implementation method).

        Args:
            channels: Channel number(s) to move.
            x: Target absolute X position in mm. Shared by all channels
                (the gantry moves as one unit in X); a single value only.
            y: Target absolute Y position(s) in mm. A single value applies to
                every channel; a list must match the number of channels.
            z: Target absolute Z position(s) in mm. A single value applies to
                every channel; a list must match the number of channels.
            safety_bypass_token: Optional token to bypass safety checks. VENUS
                runs its normal safety validation when this is omitted; pass
                the exact literal :data:`hamilton_venus.OVERRIDE_SAFETY_CHECKS`
                to bypass it. It is not an arbitrary flag -- any other string
                is rejected.

                .. warning::

                   Bypassing safety checks risks collisions that can damage hardware
                   or cause injury. Using this token waives vendor liability for any
                   resulting damage.
        """
        return self.call("move_axis_5ml", channels=channels, x=x, y=y, z=z, safety_bypass_token=safety_bypass_token)

    def tip_check_5ml(self) -> Any:
        """Return current tip status for active channels (implementation method)."""
        return self.call("tip_check_5ml")

    def tip_eject_5ml(self, *, channels: list[int] | None = None, eject_mode: Literal['waste', 'return', 'positions', 'tipPool'] = 'waste', positions: Any = None, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', tip_pool: str | None = None) -> Any:
        """Eject tips (implementation method).

        Supports multiple ejection modes:

        1. **Waste mode** (default): Eject to default waste location.
           ``tip_eject(channels=[1,2,3])``

        2. **Return mode**: Return tips to pickup positions.
           ``tip_eject(channels=[1,2,3], eject_mode=EjectMode.RETURN)``

        3. **Explicit positions mode**: Eject to specific locations.
           ``tip_eject(channels=[1,2,3], eject_mode=EjectMode.POSITIONS, positions="TipRack@col:1")``

        4. **TipPool mode**: Return tips to an empty slot in a managed pool.
           ``tip_eject(channels=[1,2,3], eject_mode=EjectMode.TIP_POOL, tip_pool="TransferTips")``

        When positions are provided, the SDK accepts position selector DSL inputs
        and normalizes them into concrete wire-format positions.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.

        positions: real type is 'str | list | dict | list | Position | list | None' -- not representable as a plain type hint here; see describe_sdk_command("tip_eject_5ml") for its full schema.
        """
        return self.call("tip_eject_5ml", channels=channels, eject_mode=eject_mode, positions=positions, well_order=well_order, tip_pool=tip_pool)

    def tip_pickup_5ml(self, *, channels: list[int] | None = None, positions: Any = None, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', tip_pool: str | None = None, optimized_pickup: bool = True) -> Any:
        """Pick up tips (implementation method).

        Supports two picking modes:

        1. **Manual mode**: Pick tips from explicit positions.
           ``tip_pickup(channels=[1,2,3], positions="TipRack@col:1")``

        2. **TipPool mode**: Pick tips from a managed pool.
           ``tip_pickup(channels=[1,2,3], tip_pool="TransferTips", optimized_pickup=True)``

        When using manual mode, the SDK accepts position selector DSL inputs
        (e.g., "TipRack@col:1") and normalizes them into concrete ``labwareId``/``wellId``
        entries.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.

        positions: real type is 'str | list | dict | list | Position | list | None' -- not representable as a plain type hint here; see describe_sdk_command("tip_pickup_5ml") for its full schema.
        """
        return self.call("tip_pickup_5ml", channels=channels, positions=positions, well_order=well_order, tip_pool=tip_pool, optimized_pickup=optimized_pickup)

    # ---- ChannelsMagPip ----

    def aspirate_magpip(self, *, positions: Any, channels: list[int] | None = None, volumes: float | list[float], liquid_class: str | list[str], settings: Any = None, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', mad_enabled: bool | None = None, mad_threshold: int | None = None, adc: bool | None = None, tadm: Any = None) -> Any:
        """Aspirate liquid with the MagPip channels.

        Mirrors :meth:`ChannelCommandsMixin.aspirate
        <hamilton_venus.mixins.channel_commands.ChannelCommandsMixin.aspirate>`
        with one extra parameter:

        Args:
            tadm: Optional :class:`~hamilton_venus.models.TadmSettings`
                controlling Total Aspiration and Dispense Monitoring. ``None``
                (default) omits the ``TADM`` object, so VENUS applies its own
                defaults (``enabled=0``, ``recording=2``).

        ``settings.tip_tracking_factor`` is ignored -- the MagPip channels do
        not support it.

        Vantage only -- not available on STAR.

        positions: real type is 'str | list | dict | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("aspirate_magpip") for its full schema.
        settings: real type is 'AspirateSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("aspirate_magpip") for its full schema.
        tadm: real type is 'TadmSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("aspirate_magpip") for its full schema.
        """
        return self.call("aspirate_magpip", positions=positions, channels=channels, volumes=volumes, liquid_class=liquid_class, settings=settings, well_order=well_order, mad_enabled=mad_enabled, mad_threshold=mad_threshold, adc=adc, tadm=tadm)

    def detect_liquid_level_magpip(self, *, positions: Any, channels: list[int] | None = None, capacitive_lld: Literal[0, 1, 2, 3, 4, 5] = 1, pressure_lld: Literal[0, 1, 2, 3, 4, 5] = 0, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc') -> Any:
        """Detect liquid level with the MagPip channels. See
        :meth:`ChannelCommandsMixin.detect_liquid_level <hamilton_venus.mixins.channel_commands.ChannelCommandsMixin.detect_liquid_level>`.

        Vantage only -- not available on STAR.

        positions: real type is 'str | list | dict | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("detect_liquid_level_magpip") for its full schema.
        """
        return self.call("detect_liquid_level_magpip", positions=positions, channels=channels, capacitive_lld=capacitive_lld, pressure_lld=pressure_lld, well_order=well_order)

    def dispense_magpip(self, *, positions: Any, channels: list[int] | None = None, volumes: float | list[float], settings: Any = None, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', adc: bool | None = None, tadm: Any = None) -> Any:
        """Dispense liquid with the MagPip channels.

        Mirrors :meth:`ChannelCommandsMixin.dispense
        <hamilton_venus.mixins.channel_commands.ChannelCommandsMixin.dispense>`
        with one extra parameter:

        Args:
            tadm: Optional :class:`~hamilton_venus.models.TadmSettings`
                controlling Total Aspiration and Dispense Monitoring. ``None``
                (default) omits the ``TADM`` object, so VENUS applies its own
                defaults (``enabled=0``, ``recording=2``).

        ``settings.tip_tracking_factor`` is ignored -- the MagPip channels do
        not support it.

        Vantage only -- not available on STAR.

        positions: real type is 'str | list | dict | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("dispense_magpip") for its full schema.
        settings: real type is 'DispenseSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("dispense_magpip") for its full schema.
        tadm: real type is 'TadmSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("dispense_magpip") for its full schema.
        """
        return self.call("dispense_magpip", positions=positions, channels=channels, volumes=volumes, settings=settings, well_order=well_order, adc=adc, tadm=tadm)

    def dispense_on_the_fly_magpip(self, *, channels: list[int], labware_name: str, volumes: float | list[float], labware_surface_distance: float, start_x_offset: float = 0.0, x_speed: float = 0.0, x_acceleration_distance: float = 8.0, dispense_direction: int = 0, excluded_positions: list[str] | None = None, adc: bool | None = None, tadm: Any = None) -> Any:
        """Dispense across wells while translating in X on a single pass, MagPip channels.

        Mirrors :meth:`ChannelCommandsMixin.dispense_on_the_fly
        <hamilton_venus.mixins.channel_commands.ChannelCommandsMixin.dispense_on_the_fly>`
        with two extra parameters:

        Args:
            adc: Enable Aspiration/Dispense Control (TADM-based). ``None``
                (default) omits the field, so VENUS applies its own default
                (disabled).
            tadm: Optional :class:`~hamilton_venus.models.TadmSettings`. ``None``
                (default) omits the ``TADM`` object.

        Vantage only -- not available on STAR.

        tadm: real type is 'TadmSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("dispense_on_the_fly_magpip") for its full schema.
        """
        return self.call("dispense_on_the_fly_magpip", channels=channels, labware_name=labware_name, volumes=volumes, labware_surface_distance=labware_surface_distance, start_x_offset=start_x_offset, x_speed=x_speed, x_acceleration_distance=x_acceleration_distance, dispense_direction=dispense_direction, excluded_positions=excluded_positions, adc=adc, tadm=tadm)

    def get_status_magpip(self) -> Any:
        """Return the current X/Y/Z position and tip-loaded status for every MagPip channel.

        Vantage only -- not available on STAR.
        """
        return self.call("get_status_magpip")

    def move_axis_magpip(self, *, channels: list[int] | int, x: float | None = None, y: float | list[float] | None = None, z: float | list[float] | None = None, safety_bypass_token: str | None = None) -> Any:
        """Move MagPip channels directly to absolute X/Y/Z coordinates. See
        :meth:`ChannelCommandsMixin.move_axis <hamilton_venus.mixins.channel_commands._ChannelCommandsBase.move_axis>`.

        Vantage only -- not available on STAR.
        """
        return self.call("move_axis_magpip", channels=channels, x=x, y=y, z=z, safety_bypass_token=safety_bypass_token)

    def move_axis_relative_magpip(self, *, channels: list[int] | int, x: float | None = None, y: float | list[float] | None = None, z: float | list[float] | None = None, safety_bypass_token: str | None = None) -> Any:
        """Move MagPip channels by a relative X/Y/Z offset.

        Like :meth:`move_axis_relative
        <hamilton_venus.mixins.channel_commands._ChannelCommandsBase.move_axis_relative>`
        but for the MagPip channels: reads each channel's current position via
        :meth:`get_status_magpip`, adds the requested offset, and issues an
        absolute :meth:`move_axis_magpip`.

        Vantage only -- not available on STAR.
        """
        return self.call("move_axis_relative_magpip", channels=channels, x=x, y=y, z=z, safety_bypass_token=safety_bypass_token)

    def tip_check_magpip(self) -> Any:
        """Return current tip status for active MagPip channels.

        Vantage only -- not available on STAR.
        """
        return self.call("tip_check_magpip")

    def tip_eject_magpip(self, *, channels: list[int] | None = None, eject_mode: Literal['waste', 'return', 'positions', 'tipPool'] = 'waste', positions: Any = None, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', tip_pool: str | None = None) -> Any:
        """Eject tips from the MagPip channels. See
        :meth:`ChannelCommandsMixin.tip_eject <hamilton_venus.mixins.channel_commands.ChannelCommandsMixin.tip_eject>`.

        Vantage only -- not available on STAR.

        positions: real type is 'str | list | dict | list | Position | list | None' -- not representable as a plain type hint here; see describe_sdk_command("tip_eject_magpip") for its full schema.
        """
        return self.call("tip_eject_magpip", channels=channels, eject_mode=eject_mode, positions=positions, well_order=well_order, tip_pool=tip_pool)

    def tip_pickup_magpip(self, *, channels: list[int] | None = None, positions: Any = None, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', tip_pool: str | None = None, optimized_pickup: bool = True) -> Any:
        """Pick up tips on the MagPip channels. See
        :meth:`ChannelCommandsMixin.tip_pickup <hamilton_venus.mixins.channel_commands.ChannelCommandsMixin.tip_pickup>`.

        Vantage only -- not available on STAR.

        positions: real type is 'str | list | dict | list | Position | list | None' -- not representable as a plain type hint here; see describe_sdk_command("tip_pickup_magpip") for its full schema.
        """
        return self.call("tip_pickup_magpip", channels=channels, positions=positions, well_order=well_order, tip_pool=tip_pool, optimized_pickup=optimized_pickup)

    # ---- Configuration ----

    def instrument_disable_cleanup(self) -> Any:
        """Disable end-of-run cleanup behavior in the instrument runtime."""
        return self.call("instrument_disable_cleanup")

    def instrument_get_configuration(self) -> Any:
        """Return the typed hardware configuration reported by the instrument."""
        return self.call("instrument_get_configuration")

    def instrument_get_deck_dimensions(self) -> Any:
        """Return typed deck dimension metadata in instrument coordinates."""
        return self.call("instrument_get_deck_dimensions")

    def instrument_get_deck_tracks(self) -> Any:
        """Return typed deck track counts for the installed instrument."""
        return self.call("instrument_get_deck_tracks")

    def instrument_get_serial_number(self) -> Any:
        """Return the typed instrument serial number response."""
        return self.call("instrument_get_serial_number")

    def instrument_get_waste_locations(self) -> Any:
        """Return typed waste-location metadata configured on the deck."""
        return self.call("instrument_get_waste_locations")

    # ---- CopyPlateCommand ----

    def copy_plate(self, *, source_plate_id: str, dest_plate_id: str | list[str], volume: float, liquid_class: str | list[str], channels: list[int] | None = None, tip_pool: str, reuse_tips: bool = False, aspirate_settings: Any = None, dispense_settings: Any = None, error_profile: Any = None) -> Any:
        """Copy liquid from every well on a source plate to one or more destination plates.

        See :func:`~hamilton_venus.compound_commands.copy_plate.execute_copy_plate`
        for the full parameter and behaviour documentation.

        aspirate_settings: real type is 'AspirateSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("copy_plate") for its full schema.
        dispense_settings: real type is 'DispenseSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("copy_plate") for its full schema.
        error_profile: real type is 'ErrorProfile | None' -- not representable as a plain type hint here; see describe_sdk_command("copy_plate") for its full schema.
        """
        return self.call("copy_plate", source_plate_id=source_plate_id, dest_plate_id=dest_plate_id, volume=volume, liquid_class=liquid_class, channels=channels, tip_pool=tip_pool, reuse_tips=reuse_tips, aspirate_settings=aspirate_settings, dispense_settings=dispense_settings, error_profile=error_profile)

    # ---- Deck ----

    def deck_delete_saved(self, *, deck_name: str) -> Any:
        """Delete a previously saved deck layout by name."""
        return self.call("deck_delete_saved", deck_name=deck_name)

    def deck_get_previous(self) -> Any:
        """Check whether a previous deck layout is available to restore."""
        return self.call("deck_get_previous")

    def deck_get_rack_ids_from_deck(self, *, path: str, carrier_filter: list[str] | None = None, only_floating_racks: bool | None = None) -> Any:
        """Get rack IDs from a deck layout file."""
        return self.call("deck_get_rack_ids_from_deck", path=path, carrier_filter=carrier_filter, only_floating_racks=only_floating_racks)

    def deck_get_saved(self) -> Any:
        """Return the list of saved deck layout names."""
        return self.call("deck_get_saved")

    def deck_import(self, *, path: str) -> Any:
        """Import a deck layout from a ``.lay`` file path.

        Every carrier defined in the file is placed on the current deck and
        registered in the SDK's built-in carrier tracking (so it shows up in
        :meth:`get_added_carriers` afterwards). This modifies the live deck,
        so the instrument must already be connected -- it is a lifecycle
        step 4 operation, unlike :meth:`deck_load` (step 2), which loads a
        saved-by-name layout and can run before connecting.

        Returns the list of added carriers in ``return_parameters.carriers_added``.
        """
        return self.call("deck_import", path=path)

    def deck_import_rack_as_site(self, *, path: str, target_labware_name: str, carrier_filter: list[str] | None = None, only_floating_racks: bool | None = None, site_name: str | None = None) -> Any:
        """Import a rack from a deck layout file as a site on the specified labware."""
        return self.call("deck_import_rack_as_site", path=path, target_labware_name=target_labware_name, carrier_filter=carrier_filter, only_floating_racks=only_floating_racks, site_name=site_name)

    def deck_load(self, *, deck_name: str | None = None, previous: bool = False) -> Any:
        """Load a previously saved deck layout by name, or reload the last-used deck.

        Pass ``deck_name`` to load by name, or set ``previous=True`` to reload
        the last deck (omitting ``deck_name``).
        """
        return self.call("deck_load", deck_name=deck_name, previous=previous)

    def deck_save(self, *, deck_name: str, overwrite: bool = False) -> Any:
        """Save the current deck layout with the specified name."""
        return self.call("deck_save", deck_name=deck_name, overwrite=overwrite)

    # ---- DeckLabware ----

    def add_1ml_core_grip(self, *, grip_type: Literal[0, 1] = 0) -> Any:
        """Add a 1 mL CO-RE grip tool to the layout."""
        return self.call("add_1ml_core_grip", grip_type=grip_type)

    def add_5ml_core_grip(self) -> Any:
        """Add a 5 mL CO-RE grip tool to the layout."""
        return self.call("add_5ml_core_grip")

    def add_carrier(self, *, labware_definition: str, left_track: int, labware_id: str | None = None) -> Any:
        """Add a carrier definition to the active deck layout."""
        return self.call("add_carrier", labware_definition=labware_definition, left_track=left_track, labware_id=labware_id)

    def add_carrier_to_site(self, *, labware_definition: str, carrier_id: str, site: str, labware_id: str | None = None) -> Any:
        """Add a carrier definition to a specific site on an existing carrier."""
        return self.call("add_carrier_to_site", labware_definition=labware_definition, carrier_id=carrier_id, site=site, labware_id=labware_id)

    def add_channel_liquid_waste(self) -> Any:
        """Add a channel liquid waste container to the active deck layout."""
        return self.call("add_channel_liquid_waste")

    def add_lid(self, *, labware_definition: str, carrier_id: str, site: str, lid_id: str | None = None) -> Any:
        """Add a lid to a carrier site in the active layout."""
        return self.call("add_lid", labware_definition=labware_definition, carrier_id=carrier_id, site=site, lid_id=lid_id)

    def add_lidded_plate(self, *, labware_definition: str, carrier_id: str, site: str, plate_id: str | None = None, lid_definition: str = 'Nunc_Lid') -> Any:
        """Add a lidded plate to a carrier site and return plate and lid names.

        VENUS requires ``lidDefinition`` for ``labware.addLiddedPlate``. The
        default ``Nunc_Lid`` keeps existing call sites working for Nunc plates.
        """
        return self.call("add_lidded_plate", labware_definition=labware_definition, carrier_id=carrier_id, site=site, plate_id=plate_id, lid_definition=lid_definition)

    def add_liquid_waste(self, *, track: int | None = None) -> Any:
        """Add a liquid waste container to the active deck layout (Vantage only)."""
        return self.call("add_liquid_waste", track=track)

    def add_ntr(self, *, labware_definition: str, carrier_id: str, site: str, stack: int, tip_pool: str | None = None, labware_id: str | None = None) -> Any:
        """Add a nested tip rack (NTR) to the active deck layout.

        Adds ``stack`` racks, one on another, and returns their names bottom to
        top in ``labware_name``. With a ``labware_id`` they are named from it with
        a counter suffix (``"NamedNTR"`` -> ``namedntr_0001``, ``namedntr_0002``, ...).
        """
        return self.call("add_ntr", labware_definition=labware_definition, carrier_id=carrier_id, site=site, stack=stack, tip_pool=tip_pool, labware_id=labware_id)

    def add_plate(self, *, labware_definition: str, carrier_id: str, site: str, plate_id: str | None = None) -> Any:
        """Add a plate to a carrier site in the active layout."""
        return self.call("add_plate", labware_definition=labware_definition, carrier_id=carrier_id, site=site, plate_id=plate_id)

    def add_qcg(self, *, qcg_type: Literal[0, 1, 2] = 0, track: int | None = None) -> Any:
        """Add a QCG (Quad CO-RE Grip) tool to the layout.

        On a Vantage, *track* places the QCG (it occupies 2 tracks) somewhere other
        than its default location; omit it to load in the default location. *track*
        is not supported on a STAR.
        """
        return self.call("add_qcg", qcg_type=qcg_type, track=track)

    def add_reservoir(self, *, labware_definition: str, carrier_id: str, site: str, labware_id: str | None = None) -> Any:
        """Add a reservoir to a carrier site in the active deck layout."""
        return self.call("add_reservoir", labware_definition=labware_definition, carrier_id=carrier_id, site=site, labware_id=labware_id)

    def add_tip_box(self, *, labware_definition: str, carrier_id: str, site: str, tip_pool: str | None = None, labware_id: str | None = None) -> Any:
        """Add a tip box to a carrier site in the active layout.

        If ``tip_pool``/``labware_id`` are omitted, VENUS assigns names
        automatically; read them back from the response's return_parameters.
        """
        return self.call("add_tip_box", labware_definition=labware_definition, carrier_id=carrier_id, site=site, tip_pool=tip_pool, labware_id=labware_id)

    def add_tip_rack(self, *, labware_definition: str, carrier_id: str, site: str, tip_pool: str | None = None, labware_id: str | None = None) -> Any:
        """Add a tip rack to a carrier site in the active layout.

        If ``tip_pool``/``labware_id`` are omitted, VENUS assigns names
        automatically; read them back from the response's return_parameters.
        Either way, VENUS stores (and reports back) the name lower-cased -- see
        this module's docstring.
        """
        return self.call("add_tip_rack", labware_definition=labware_definition, carrier_id=carrier_id, site=site, tip_pool=tip_pool, labware_id=labware_id)

    def add_tip_support(self, *, carrier_id: str, site: str) -> Any:
        """Add a tip support to a carrier site in the active layout."""
        return self.call("add_tip_support", carrier_id=carrier_id, site=site)

    def add_transport_site(self, *, site_name: str, x_center: float, y_center: float, z_bottom: float, angle_index: int) -> Any:
        """Add a transport site definition to the active deck layout."""
        return self.call("add_transport_site", site_name=site_name, x_center=x_center, y_center=y_center, z_bottom=z_bottom, angle_index=angle_index)

    def add_tube_carrier(self, *, labware_definition: str, left_track: int, labware_id: str | None = None) -> Any:
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
        return self.call("add_tube_carrier", labware_definition=labware_definition, left_track=left_track, labware_id=labware_id)

    def add_tubes_to_carrier(self, *, labware_name: str, positions: Any) -> Any:
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

        positions: real type is 'list' -- not representable as a plain type hint here; see describe_sdk_command("add_tubes_to_carrier") for its full schema.
        """
        return self.call("add_tubes_to_carrier", labware_name=labware_name, positions=positions)

    def get_tilt_settings(self, *, labware_name: str) -> Any:
        """How ``tilt_labware`` last tilted *labware_name* (angle, aim, tip and margins), or ``None`` if flat."""
        return self.call("get_tilt_settings", labware_name=labware_name)

    def get_tilted_labware(self) -> Any:
        """Labware currently tilted by ``tilt_labware``: lower-cased name -> commanded degrees."""
        return self.call("get_tilted_labware")

    def is_labware_tilted(self, *, labware_name: str) -> Any:
        """Whether ``tilt_labware`` has left *labware_name* tilted (case-insensitive)."""
        return self.call("is_labware_tilted", labware_name=labware_name)

    def move_carrier(self, *, labware_name: str, left_track: int, site: str = '') -> Any:
        """Move a loaded carrier to a new deck track/site location."""
        return self.call("move_carrier", labware_name=labware_name, left_track=left_track, site=site)

    def remove_labware(self, *, labware_name: str) -> Any:
        """Remove the specified labware from the active deck layout.

        Split wells (``split_wells``) of the labware, or of labware on a removed
        carrier, are removed with it.
        """
        return self.call("remove_labware", labware_name=labware_name)

    def remove_transport_tool(self, *, tool_id: int) -> Any:
        """Remove a transport tool from the layout by ID."""
        return self.call("remove_transport_tool", tool_id=tool_id)

    def shift_labware(self, *, labware_name: str, relative_x: float = 0.0, relative_y: float = 0.0, relative_z: float = 0.0, relative_angle: float = 0.0) -> Any:
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
        return self.call("shift_labware", labware_name=labware_name, relative_x=relative_x, relative_y=relative_y, relative_z=relative_z, relative_angle=relative_angle)

    def tilt_labware(self, *, labware_name: str, tilt_degrees: float, pivot_point: Literal['LeftEdge', 'Center'] = 'LeftEdge', pivot_x_offset_mm: float = 0.0, pivot_z_offset_mm: float = 0.0, well_position: Literal['Center', 'DeepestPoint', 'HighestPoint'] = 'Center', measured_tilt_degrees: float | None = None, tip_end_height_mm: float = 0.0, wall_margin_mm: float = 1.0, high_wall_margin_mm: float = 2.0, tip_profile: Any = None) -> Any:
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

        tip_profile: real type is 'TipProfile | None' -- not representable as a plain type hint here; see describe_sdk_command("tilt_labware") for its full schema.
        """
        return self.call("tilt_labware", labware_name=labware_name, tilt_degrees=tilt_degrees, pivot_point=pivot_point, pivot_x_offset_mm=pivot_x_offset_mm, pivot_z_offset_mm=pivot_z_offset_mm, well_position=well_position, measured_tilt_degrees=measured_tilt_degrees, tip_end_height_mm=tip_end_height_mm, wall_margin_mm=wall_margin_mm, high_wall_margin_mm=high_wall_margin_mm, tip_profile=tip_profile)

    # ---- DeckStatus ----

    def get_added_carriers(self) -> Any:
        """Return the list of carriers currently added to the deck layout."""
        return self.call("get_added_carriers")

    def get_added_plates(self) -> Any:
        """Return the list of plates currently added to the deck layout."""
        return self.call("get_added_plates")

    def get_added_reservoirs(self) -> Any:
        """Return the list of reservoirs currently added to the deck layout."""
        return self.call("get_added_reservoirs")

    def get_added_tip_racks(self) -> Any:
        """Return the list of tip racks currently added to the deck layout."""
        return self.call("get_added_tip_racks")

    def get_available_carrier_sites(self, *, carrier: str) -> Any:
        """Return the available (empty) sites on the specified carrier.

        For carriers with sites (plate, reservoir, tip carriers). A sample tube carrier has no
        sites -- its tubes are part of the rack -- so this returns nothing for one; use
        ``get_labware_coordinates(carrier)`` (every tube position) or ``get_labware_spec(carrier)``.
        """
        return self.call("get_available_carrier_sites", carrier=carrier)

    def get_available_tracks(self) -> Any:
        """Return the list of available (unoccupied) deck tracks."""
        return self.call("get_available_tracks")

    def get_labware_coordinates(self, *, labware_name: str, well: str | None = None) -> Any:
        """Return the deck coordinates of a labware item, or of one of its wells.

        With ``well``: the response's ``well`` / ``x`` / ``y`` / ``z`` / ``angle``
        are that well's coordinates.

        Without ``well``: ``origin`` holds the labware's origin and, for a rack-type
        labware (plate, tip rack, tube rack, reservoir), ``wells`` holds the
        coordinates of every position, ordered by column. A carrier has no wells
        and returns ``origin`` only. The top-level ``x`` / ``y`` / ``z`` / ``angle``
        are ``None`` in this case -- read ``origin`` instead.
        """
        return self.call("get_labware_coordinates", labware_name=labware_name, well=well)

    def get_labware_location(self, *, labware_name: str) -> Any:
        """Return the carrier and site location of the specified labware instance by name."""
        return self.call("get_labware_location", labware_name=labware_name)

    def get_labware_on_carrier(self, *, carrier: str) -> Any:
        """Return the labware items loaded on the specified carrier.

        For carriers with sites (plate, reservoir, tip carriers). A sample tube carrier has no
        sites -- its tubes are part of the rack -- so this returns nothing for one; use
        ``get_labware_coordinates(carrier)`` (every tube position) or ``get_labware_spec(carrier)``.
        """
        return self.call("get_labware_on_carrier", carrier=carrier)

    def get_labware_positions(self, *, labware_name: str) -> Any:
        """Return the deck positions for the specified labware instance by name."""
        return self.call("get_labware_positions", labware_name=labware_name)

    def get_occupied_carrier_sites(self, *, carrier: str) -> Any:
        """Return the occupied sites on the specified carrier.

        For carriers with sites (plate, reservoir, tip carriers). A sample tube carrier has no
        sites -- its tubes are part of the rack -- so this returns nothing for one; use
        ``get_labware_coordinates(carrier)`` (every tube position) or ``get_labware_spec(carrier)``.
        """
        return self.call("get_occupied_carrier_sites", carrier=carrier)

    def get_occupied_tracks(self) -> Any:
        """Return the list of currently occupied deck tracks."""
        return self.call("get_occupied_tracks")

    def get_top_labware(self, *, carrier_id: str, site: str) -> Any:
        """Return the top labware at the specified carrier site.

        For carriers with sites (plate, reservoir, tip carriers). A sample tube carrier has no
        sites -- its tubes are part of the rack -- so this returns nothing for one; use
        ``get_labware_coordinates(carrier)`` (every tube position) or ``get_labware_spec(carrier)``.
        """
        return self.call("get_top_labware", carrier_id=carrier_id, site=site)

    def get_transport_tool(self, *, is_1ml: bool | None = None, is_qcg: bool | None = None, tool_id: int | None = None) -> Any:
        """Get a transport tool by type or ID (parameters are mutually exclusive)."""
        return self.call("get_transport_tool", is_1ml=is_1ml, is_qcg=is_qcg, tool_id=tool_id)

    def get_transport_tool_ids(self) -> Any:
        """Get all transport tool IDs currently in the layout."""
        return self.call("get_transport_tool_ids")

    def is_track_occupied(self, *, track_id: int) -> Any:
        """Return whether the specified deck track is occupied in the layout."""
        return self.call("is_track_occupied", track_id=track_id)

    # ---- ErrorSimulator ----

    def clear_simulated_errors(self) -> Any:
        """Reset every firmware command to its "no error" reply."""
        return self.call("clear_simulated_errors")

    def list_simulatable_errors(self, *, module: Literal['1mL', '5mL', 'X1', 'MPH96', 'MPH384', 'IPG', 'IDL', 'MagPip'] | str) -> Any:
        """Error descriptions known for *module* on this instrument."""
        return self.call("list_simulatable_errors", module=module)

    def list_simulatable_modules(self) -> Any:
        """Module names valid for :meth:`simulate_error` on this instrument."""
        return self.call("list_simulatable_modules")

    def list_simulatable_steps(self, *, module: Literal['1mL', '5mL', 'X1', 'MPH96', 'MPH384', 'IPG', 'IDL', 'MagPip'] | str) -> Any:
        """Firmware-step descriptions known for *module* on this instrument."""
        return self.call("list_simulatable_steps", module=module)

    def simulate_error(self, *, module: Literal['1mL', '5mL', 'X1', 'MPH96', 'MPH384', 'IPG', 'IDL', 'MagPip'] | str, step: Any, error: Any, channels: list[int] | None = None) -> Any:
        """Make the next *step* on *module* return *error*.

        Any previously injected simulated error is cleared first -- only one is
        ever active at a time (VENUS's firmware simulator misbehaves with
        several registered at once), so call this immediately before the step it
        targets.

        *step* / *error* accept a generated typed constant
        (``hamilton_venus.error_simulator`` ``*Step`` / ``*Error`` enums --
        exact match) or a plain string (fuzzy keyword match, as the HSL library
        does). For channel modules (1mL / 5mL / X1 / MagPip) *error* applies to
        every channel; pass ``channels=[...]`` for a subset, or the
        ``"1.<desc>;2.<desc>"`` micro-syntax in *error* for a per-channel error.

        step: real type is 'StrEnum | str' -- not representable as a plain type hint here; see describe_sdk_command("simulate_error") for its full schema.
        error: real type is 'StrEnum | str' -- not representable as a plain type hint here; see describe_sdk_command("simulate_error") for its full schema.
        """
        return self.call("simulate_error", module=module, step=step, error=error, channels=channels)

    def simulate_error_by_code(self, *, firmware_command: str, error_code: str, error_recovery: str = '') -> Any:
        """Write *error_code* as the raw simulated reply for *firmware_command*
        with no keyword matching. Clears any previously injected error first, as
        :meth:`simulate_error` does.
        """
        return self.call("simulate_error_by_code", firmware_command=firmware_command, error_code=error_code, error_recovery=error_recovery)

    # ---- Firmware ----

    def firmware_command(self, *, command: str, parameters: str = '', safety_bypass_token: str) -> Any:
        """Send a raw firmware command to the instrument.

        This is an advanced, low-level command that bypasses the typed SDK
        helpers. Prefer a dedicated command mixin whenever one exists.

        Parameters
        ----------
        command:
            Firmware command: the module and command code, sent upper case. On
            a STAR that is 4 characters, for example ``"C0AS"``; on a Vantage
            6 to 8, for example ``"A1PMRF"``.
        parameters:
            Firmware command parameters, for example ``"tm1 1 1 1 1 1 1 1"``.
            VENUS sends them lower case, so they cannot carry any part of the
            command code.
        safety_bypass_token:
            Security token required to override instrument safety checks. Pass
            the exact literal :data:`hamilton_venus.OVERRIDE_SAFETY_CHECKS` to
            bypass safety validation -- it is not an arbitrary flag, and any
            other string is rejected with a firmware error. Unlike the other
            movement commands, VENUS requires this token for every firmware
            command regardless of whether it actually needs to bypass anything.

            .. warning::

               Bypassing safety checks risks collisions that can damage hardware
               or cause injury. Using this token waives vendor liability for any
               resulting damage.

        Returns
        -------
        FirmwareCommandResponse
            Typed response exposing the raw firmware ``return`` value.
        """
        return self.call("firmware_command", command=command, parameters=parameters, safety_bypass_token=safety_bypass_token)

    def firmware_debug_mode(self, *, enable: bool) -> Any:
        """Enable or disable firmware debug mode on the instrument.

        Parameters
        ----------
        enable:
            ``True`` to enable debug mode, ``False`` to disable it.
        """
        return self.call("firmware_debug_mode", enable=enable)

    # ---- FrontCover ----

    def front_cover_is_closed(self) -> Any:
        """Return the typed front-cover closed-state response."""
        return self.call("front_cover_is_closed")

    def front_cover_is_locked(self) -> Any:
        """Return the typed front-cover lock-state response."""
        return self.call("front_cover_is_locked")

    def front_cover_lock(self) -> Any:
        """Lock the front cover through the system command channel."""
        return self.call("front_cover_lock")

    def front_cover_unlock(self) -> Any:
        """Unlock the front cover through the system command channel."""
        return self.call("front_cover_unlock")

    # ---- HeaterCoolerDeviceCommands ----

    def hhc_connect(self, *, address: str, keep_alive: int = 5) -> Any:
        """Open the HeaterCooler daisy chain at *address* and register its units.

        Bundles the vendor ``Connect`` with a per-unit read of firmware version,
        current temperature and verification date.

        Parameters
        ----------
        address:
            Vendor connection string (COM port / USB identifier).
        keep_alive:
            Keep-alive interval passed through to the vendor driver (seconds).
        """
        return self.call("hhc_connect", address=address, keep_alive=keep_alive)

    def hhc_get_device_ids(self) -> Any:
        """Return the registered HeaterCooler units and their firmware versions."""
        return self.call("hhc_get_device_ids")

    def hhc_get_status(self, *, device_id: int | None = None) -> Any:
        """Return current temperature, time-remaining and control state per unit."""
        return self.call("hhc_get_status", device_id=device_id)

    def hhc_hold_temp_for_time(self, *, target: float, minutes: float, tolerance: float = 0.5, device_id: int | None = None) -> Any:
        """Hold the unit(s) at *target* degC (+/- *tolerance*) for *minutes*."""
        return self.call("hhc_hold_temp_for_time", target=target, minutes=minutes, tolerance=tolerance, device_id=device_id)

    def hhc_identify(self, *, device_id: int | None = None) -> Any:
        """Blink the display so an operator can locate the unit(s)."""
        return self.call("hhc_identify", device_id=device_id)

    def hhc_self_diagnostic(self, *, enable: bool | None = None, device_id: int | None = None) -> Any:
        """Read the self-diagnostic toggle, or set it first when *enable* is given."""
        return self.call("hhc_self_diagnostic", enable=enable, device_id=device_id)

    def hhc_set_display(self, *, on: bool | None = None, brightness: int | None = None, device_id: int | None = None) -> Any:
        """Turn the display on/off and/or set its brightness (0-100%).

        Pass at least one of *on* / *brightness*.
        """
        return self.call("hhc_set_display", on=on, brightness=brightness, device_id=device_id)

    def hhc_set_verification_date(self, *, date: str, device_id: int | None = None) -> Any:
        """Record the verification / calibration date (``YYYY-MM-DD``) on the unit(s)."""
        return self.call("hhc_set_verification_date", date=date, device_id=device_id)

    def hhc_start_temp_control(self, *, target: float, tolerance: float = 0.5, wait: bool = False, timeout: int = 1800, device_id: int | None = None) -> Any:
        """Drive the unit(s) to *target* degC (+/- *tolerance*).

        *target* must be within ``[0, 110]`` degC. With ``wait=True`` the call
        blocks until each unit is within band or *timeout* seconds elapse.
        """
        return self.call("hhc_start_temp_control", target=target, tolerance=tolerance, wait=wait, timeout=timeout, device_id=device_id)

    def hhc_stop_temp_control(self, *, device_id: int | None = None) -> Any:
        """Stop temperature control on the unit(s)."""
        return self.call("hhc_stop_temp_control", device_id=device_id)

    def hhc_terminate(self) -> Any:
        """Disconnect every HeaterCooler unit and release the connection."""
        return self.call("hhc_terminate")

    def hhc_wait_for_temp_control(self, *, timeout: int = 1800, device_id: int | None = None) -> Any:
        """Block until the unit(s) reach their temperature band or *timeout* elapses."""
        return self.call("hhc_wait_for_temp_control", timeout=timeout, device_id=device_id)

    # ---- HeaterShakerDeviceCommands ----

    def hhs_create_star_device(self, *, node: int) -> Any:
        """Register an HHS connected through a STAR node and return its device id."""
        return self.call("hhs_create_star_device", node=node)

    def hhs_create_usb_device(self, *, node: int) -> Any:
        """Register an HHS connected through USB and return its device id."""
        return self.call("hhs_create_usb_device", node=node)

    def hhs_get_device_ids(self) -> Any:
        """Return the registered HHS devices and their connection metadata."""
        return self.call("hhs_get_device_ids")

    def hhs_get_status(self) -> Any:
        """Return the current shaking speed and temperature status of each HHS device."""
        return self.call("hhs_get_status")

    def hhs_set_plate_lock(self, *, lock: bool, device_id: int | None = None) -> Any:
        """Lock or unlock the plate on the HHS. Applies to all devices when *device_id* is None."""
        return self.call("hhs_set_plate_lock", lock=lock, device_id=device_id)

    def hhs_start_shaker(self, *, speed: int, time: int = 0, device_id: int | None = None) -> Any:
        """Start shaking at *speed* RPM for *time* seconds (0 = indefinite).

        Applies to all devices when *device_id* is None.
        """
        return self.call("hhs_start_shaker", speed=speed, time=time, device_id=device_id)

    def hhs_start_temp_control(self, *, temperature: float, device_id: int | None = None) -> Any:
        """Start temperature control targeting *temperature* deg C.

        Applies to all devices when *device_id* is None.
        """
        return self.call("hhs_start_temp_control", temperature=temperature, device_id=device_id)

    def hhs_stop_shaker(self, *, device_id: int | None = None) -> Any:
        """Stop shaking. Applies to all devices when *device_id* is None."""
        return self.call("hhs_stop_shaker", device_id=device_id)

    def hhs_stop_temp_control(self, *, device_id: int | None = None) -> Any:
        """Stop temperature control. Applies to all devices when *device_id* is None."""
        return self.call("hhs_stop_temp_control", device_id=device_id)

    def hhs_terminate(self) -> Any:
        """Disconnect all HHS devices and release the connection."""
        return self.call("hhs_terminate")

    def hhs_wait_for_shaker(self, *, device_id: int | None = None) -> Any:
        """Block until shaking has stopped. Waits for all devices when *device_id* is None."""
        return self.call("hhs_wait_for_shaker", device_id=device_id)

    def hhs_wait_for_temp_control(self, *, device_id: int | None = None) -> Any:
        """Block until temperature control has stopped. Waits for all devices when *device_id* is None."""
        return self.call("hhs_wait_for_temp_control", device_id=device_id)

    # ---- HitPickingCommand ----

    def hit_picking(self, *, transfer_csv: Any, liquid_class: str | list[str], tip_pool: str, channels: list[int] | None = None, optimized_tip_pickup: bool = True, change_tips: bool = True, minimize_tips: bool = False, follow_csv_order: bool = False, aspirate_settings: Any = None, dispense_settings: Any = None, error_profile: Any = None) -> Any:
        """Transfer samples between arbitrary source and destination wells from a CSV worklist.

        See :func:`~hamilton_venus.compound_commands.hit_picking.execute_hit_picking`
        for full parameter documentation.

        transfer_csv: real type is 'str | PathLike' -- not representable as a plain type hint here; see describe_sdk_command("hit_picking") for its full schema.
        aspirate_settings: real type is 'AspirateSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("hit_picking") for its full schema.
        dispense_settings: real type is 'DispenseSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("hit_picking") for its full schema.
        error_profile: real type is 'ErrorProfile | None' -- not representable as a plain type hint here; see describe_sdk_command("hit_picking") for its full schema.
        """
        return self.call("hit_picking", transfer_csv=transfer_csv, liquid_class=liquid_class, tip_pool=tip_pool, channels=channels, optimized_tip_pickup=optimized_tip_pickup, change_tips=change_tips, minimize_tips=minimize_tips, follow_csv_order=follow_csv_order, aspirate_settings=aspirate_settings, dispense_settings=dispense_settings, error_profile=error_profile)

    # ---- InhecoTECDeviceCommands ----

    def inheco_tec_connect(self, *, controller_id: int) -> Any:
        """Verify controller *controller_id* answers on the bus and register it.

        Bundles the vendor ``Initialize`` with a read of the controller's own
        type (STC/MTC) and a device-type scan of its slots, so the response
        tells you what's actually plugged in without a separate round trip.
        A Single TEC (STC) controller has exactly 1 slot; a Multi TEC (MTC)
        has up to 6 -- confirmed against real hardware -- so only an STC's
        one slot is scanned, not all 6 (see
        :data:`~hamilton_venus.inheco_tec.SLOT_COUNT_BY_CONTROLLER_TYPE`).
        """
        return self.call("inheco_tec_connect", controller_id=controller_id)

    def inheco_tec_get_firmware_version(self, *, controller_id: int, selector: int = 1) -> Any:
        """Read one firmware field for *controller_id* (see
        :data:`~hamilton_venus.inheco_tec.FIRMWARE_INFO_NAMES`; default is
        ``1`` = ``Application_Version``).
        """
        return self.call("inheco_tec_get_firmware_version", controller_id=controller_id, selector=selector)

    def inheco_tec_get_identification(self, *, controller_id: int, device_id: int = 0) -> Any:
        """Read device type, serial number, runtime and (for a real slot,
        ``device_id`` 1-6) calibration date for *device_id* on *controller_id*.

        ``device_id=0`` (the default) identifies the controller unit itself,
        which has no calibration date (``calibrationDate`` comes back
        ``null``).
        """
        return self.call("inheco_tec_get_identification", controller_id=controller_id, device_id=device_id)

    def inheco_tec_get_reservoir_status(self, *, controller_id: int, device_id: int) -> Any:
        """Read the reservoir/refill status for *device_id* on *controller_id*."""
        return self.call("inheco_tec_get_reservoir_status", controller_id=controller_id, device_id=device_id)

    def inheco_tec_get_sensor_values(self, *, controller_id: int, selector: int) -> Any:
        """Read one controller housing sensor (see
        :data:`~hamilton_venus.inheco_tec.SENSOR_INFO_NAMES`).

        Replicates an apparent, unfixed upstream bug: the vendor library's
        own ``GetSensorValues`` sends the *firmware*-version command instead
        of the sensor-value command (see
        :meth:`hamilton_venus.inheco_tec._ComInhecoTECTransport.get_sensor_values`)
        -- against real hardware this returns firmware data, not a sensor
        reading. Kept as-is for wire fidelity with the shipped vendor driver.
        """
        return self.call("inheco_tec_get_sensor_values", controller_id=controller_id, selector=selector)

    def inheco_tec_get_shaker_status(self, *, controller_id: int, device_id: int) -> Any:
        """Read shaker run status, revolutions and shape for *device_id* on
        *controller_id* in one call.
        """
        return self.call("inheco_tec_get_shaker_status", controller_id=controller_id, device_id=device_id)

    def inheco_tec_get_temperature_status(self, *, controller_id: int, device_id: int, temperature_selector: int = 3) -> Any:
        """Read actual/target temperature, the device's limits and heater
        status for *device_id* on *controller_id* in one call.

        *temperature_selector* picks the actual-temperature compensation mode
        (see :data:`~hamilton_venus.inheco_tec.TEMPERATURE_INFO_NAMES`;
        default ``3`` = ``Fully_Compensated``, the vendor's own recommended
        reading).
        """
        return self.call("inheco_tec_get_temperature_status", controller_id=controller_id, device_id=device_id, temperature_selector=temperature_selector)

    def inheco_tec_send_command(self, *, controller_id: int, command: str) -> Any:
        """Send a raw ASCII command string to *controller_id* and return the
        raw response, unparsed -- an escape hatch mirroring the vendor's own
        ``SendCommandString``, for commands this device group does not
        otherwise expose.
        """
        return self.call("inheco_tec_send_command", controller_id=controller_id, command=command)

    def inheco_tec_set_shaker_revolutions(self, *, controller_id: int, device_id: int, rpm: int) -> Any:
        """Set shaker speed in RPM (60-3000, or 0 to clamp without shaking)
        for *device_id* on *controller_id*.
        """
        return self.call("inheco_tec_set_shaker_revolutions", controller_id=controller_id, device_id=device_id, rpm=rpm)

    def inheco_tec_set_shaker_shape(self, *, controller_id: int, device_id: int, shape: int) -> Any:
        """Set shaker motion shape (see
        :data:`~hamilton_venus.inheco_tec.SHAKE_SHAPE_NAMES`) for *device_id*
        on *controller_id*.
        """
        return self.call("inheco_tec_set_shaker_shape", controller_id=controller_id, device_id=device_id, shape=shape)

    def inheco_tec_set_target_temperature(self, *, controller_id: int, device_id: int, target_c: float) -> Any:
        """Set the target temperature (degC) for *device_id* on *controller_id*."""
        return self.call("inheco_tec_set_target_temperature", controller_id=controller_id, device_id=device_id, target_c=target_c)

    def inheco_tec_set_touchscreen(self, *, controller_id: int, enabled: bool) -> Any:
        """Turn the controller's own touchscreen on/off."""
        return self.call("inheco_tec_set_touchscreen", controller_id=controller_id, enabled=enabled)

    def inheco_tec_start_shaker(self, *, controller_id: int, device_id: int) -> Any:
        """Start shaking for *device_id* on *controller_id*."""
        return self.call("inheco_tec_start_shaker", controller_id=controller_id, device_id=device_id)

    def inheco_tec_start_temperature_control(self, *, controller_id: int, device_id: int) -> Any:
        """Start temperature control (heating/cooling toward the target) for
        *device_id* on *controller_id*.
        """
        return self.call("inheco_tec_start_temperature_control", controller_id=controller_id, device_id=device_id)

    def inheco_tec_stop_shaker(self, *, controller_id: int, device_id: int) -> Any:
        """Stop shaking for *device_id* on *controller_id*."""
        return self.call("inheco_tec_stop_shaker", controller_id=controller_id, device_id=device_id)

    def inheco_tec_stop_temperature_control(self, *, controller_id: int, device_id: int) -> Any:
        """Stop temperature control for *device_id* on *controller_id*."""
        return self.call("inheco_tec_stop_temperature_control", controller_id=controller_id, device_id=device_id)

    def inheco_tec_terminate(self, *, stop_all_devices: bool = True) -> Any:
        """Disconnect every InhecoTEC controller and release the COM connection.

        With *stop_all_devices* (the default), stops the shaker and
        temperature control on every connected controller's slots 1-6 first,
        best-effort, mirroring the vendor's own ``Terminate(stopAllDevices)``.
        """
        return self.call("inheco_tec_terminate", stop_all_devices=stop_all_devices)

    # ---- InstrumentSyncClient ----

    def pop_command_warnings(self) -> Any:
        """Warnings the SDK's checks raised before commands since the last call -- for example a
        tip too short for the labware it pipetted in, so the channel itself went inside the
        container (contamination risk). They are also logged and written to the run log.
        Returns them oldest first and clears the list.
        """
        return self.call("pop_command_warnings")

    # ---- Labware ----

    def labware_add_definition(self, *, labware_name: str, labware_definition: Any) -> Any:
        """Add a new labware definition to the system.

        VENUS takes the labware category from the definition's own ``labwareClass``.

        labware_definition: real type is 'LabwareDefinition | dict' -- not representable as a plain type hint here; see describe_sdk_command("labware_add_definition") for its full schema.
        """
        return self.call("labware_add_definition", labware_name=labware_name, labware_definition=labware_definition)

    def labware_delete_definition(self, *, labware_name: str) -> Any:
        """Delete the specified labware definition from the system."""
        return self.call("labware_delete_definition", labware_name=labware_name)

    def labware_get_definition(self, *, labware_name: str) -> Any:
        """Return the definition for the specified labware type."""
        return self.call("labware_get_definition", labware_name=labware_name)

    def labware_get_definitions(self, *, filter: list[str] | None = None) -> Any:
        """Return labware definitions, optionally filtered by name."""
        return self.call("labware_get_definitions", filter=filter)

    def labware_get_params_from_id(self, *, labware_name: str) -> Any:
        """Return the full labware definition for a labware instance by its name/ID."""
        return self.call("labware_get_params_from_id", labware_name=labware_name)

    def labware_get_types(self) -> Any:
        """Return the list of available labware type names."""
        return self.call("labware_get_types")

    def labware_update_definition(self, *, labware_name: str, labware_definition: Any) -> Any:
        """Update an existing labware definition.

        labware_definition: real type is 'LabwareDefinition | dict' -- not representable as a plain type hint here; see describe_sdk_command("labware_update_definition") for its full schema.
        """
        return self.call("labware_update_definition", labware_name=labware_name, labware_definition=labware_definition)

    # ---- LabwareDefinition ----

    def labware_definition_add_definition(self, *, labware_name: str, labware_definition: Any) -> Any:
        """Add a new labware definition to the system.

        VENUS takes the labware category from the definition's own ``labwareClass``.

        labware_definition: real type is 'LabwareDefinition | dict' -- not representable as a plain type hint here; see describe_sdk_command("labware_definition_add_definition") for its full schema.
        """
        return self.call("labware_definition_add_definition", labware_name=labware_name, labware_definition=labware_definition)

    def labware_definition_delete_definition(self, *, labware_name: str) -> Any:
        """Delete the specified labware definition from the system."""
        return self.call("labware_definition_delete_definition", labware_name=labware_name)

    def labware_definition_get_definition(self, *, labware_name: str) -> Any:
        """Return the definition for the specified labware type."""
        return self.call("labware_definition_get_definition", labware_name=labware_name)

    def labware_definition_get_definitions(self, *, filter: list[str] | None = None) -> Any:
        """Return labware definitions, optionally filtered by name."""
        return self.call("labware_definition_get_definitions", filter=filter)

    def labware_definition_get_params_from_id(self, *, labware_name: str) -> Any:
        """Return the full labware definition for a labware instance by its name/ID."""
        return self.call("labware_definition_get_params_from_id", labware_name=labware_name)

    def labware_definition_get_types(self) -> Any:
        """Return the list of available labware type names."""
        return self.call("labware_definition_get_types")

    def labware_definition_import_definition(self, *, labware_path: str, labware_name: str | None = None, convert_models: bool = True) -> Any:
        """Import a labware definition from a VENUS labware file (``.rck``, ``.tml``, ...).

        VENUS works out the labware type from the file, converts it to the SDK's JSON format,
        stores it under ``Labware\\User\\<type>`` and returns it as
        ``return_parameters.definition``.

        With *convert_models* (the default), the 3D models it refers to as VENUS ``.x`` /
        ``.hxx`` files are converted to glTF (``.gltf`` + ``.bin``) in the registered SDK
        folder's ``Labware\\Models``, and the stored definition is updated to refer to them;
        ``return_parameters.models`` says what was converted, found already, missing or failed.

        Args:
            labware_path: The labware file to import.
            labware_name: Name for the new definition; defaults to the file name. A
                definition replacing another needs a new name.
            convert_models: Convert the definition's ``.x`` / ``.hxx`` models to glTF.
        """
        return self.call("labware_definition_import_definition", labware_path=labware_path, labware_name=labware_name, convert_models=convert_models)

    def labware_definition_update_definition(self, *, labware_name: str, labware_definition: Any) -> Any:
        """Update an existing labware definition.

        labware_definition: real type is 'LabwareDefinition | dict' -- not representable as a plain type hint here; see describe_sdk_command("labware_definition_update_definition") for its full schema.
        """
        return self.call("labware_definition_update_definition", labware_name=labware_name, labware_definition=labware_definition)

    # ---- LiquidClass ----

    def check_tip_reach(self, *, labware_name: str, tip_pool: str | None = None, tip_type: int | None = None, device: str = '1mL', height_from_bottom: float = 0.0) -> Any:
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
        return self.call("check_tip_reach", labware_name=labware_name, tip_pool=tip_pool, tip_type=tip_type, device=device, height_from_bottom=height_from_bottom)

    def find_liquid_classes(self, *, liquid: str, dispense_mode: Any = None, volume: float | None = None, tip_pool: str | None = None, tip_type: int | None = None, device: str | None = None, include_custom: bool = True, limit: int = 10) -> Any:
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
        return self.call("find_liquid_classes", liquid=liquid, dispense_mode=dispense_mode, volume=volume, tip_pool=tip_pool, tip_type=tip_type, device=device, include_custom=include_custom, limit=limit)

    def get_liquid_class(self, *, name: str) -> Any:
        """Get the full definition of a single liquid class by name."""
        return self.call("get_liquid_class", name=name)

    def get_liquid_classes(self, *, tip_type: int = -1, device: int = -1, dispense_mode: int = -1, is_original: int = -1, has_tadm_enabled: int = -1) -> Any:
        """Get liquid class names filtered by tip, device, dispense mode, and metadata flags."""
        return self.call("get_liquid_classes", tip_type=tip_type, device=device, dispense_mode=dispense_mode, is_original=is_original, has_tadm_enabled=has_tadm_enabled)

    def get_liquid_devices(self) -> Any:
        """Get the list of available liquid handling devices."""
        return self.call("get_liquid_devices")

    def get_liquid_names(self) -> Any:
        """Get the list of available liquid class names."""
        return self.call("get_liquid_names")

    def get_registered_tip_types(self) -> Any:
        """The tip types registered in VENUS, by tip type id: name, max liquid volume, max tip
        volume, tip length (whole tip) and length_below_channel (tip length minus the collar
        that sits on the channel up to its stop disk -- use this one for heights), filter,
        conductive, and the devices that can use each tip. A tip type that is not in this list
        cannot be used. Needs a started session, not a connected instrument.
        """
        return self.call("get_registered_tip_types")

    def get_tip_types(self) -> Any:
        """Get the list of available tip types."""
        return self.call("get_tip_types")

    def pull_liquid_classes(self, *, names: list[str]) -> Any:
        """Pull liquid class definitions from the instrument database."""
        return self.call("pull_liquid_classes", names=names)

    def push_liquid_classes(self, *, names: list[str]) -> Any:
        """Push liquid class definitions to the instrument database.

        Not needed before pipetting: custom liquid classes a command uses are pushed
        automatically the first time a session uses them and whenever their JSON
        changes. Use this to load a set up front in one call.
        """
        return self.call("push_liquid_classes", names=names)

    def update_liquid_class(self, *, definition: Any) -> Any:
        """Update an existing liquid class definition on the instrument.

        definition: real type is 'LiquidClassDefinition' -- not representable as a plain type hint here; see describe_sdk_command("update_liquid_class") for its full schema.
        """
        return self.call("update_liquid_class", definition=definition)

    # ---- LoadTray ----

    def load_tray_lower(self) -> Any:
        """Lower the Vantage load tray to the loading position.

        Vantage only -- not available on STAR.
        """
        return self.call("load_tray_lower")

    def load_tray_raise(self) -> Any:
        """Raise the Vantage load tray to the operational position.

        Vantage only -- not available on STAR.
        """
        return self.call("load_tray_raise")

    # ---- MPH96 ----

    def aspirate_mph96(self, *, labware_id: str, mph_pattern: list[str] | list[int] | None = None, volume: float, liquid_class: str, settings: Any = None) -> Any:
        """Aspirate liquid with the MPH96 head from the specified labware.

        settings: real type is 'MPH96AspirateSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("aspirate_mph96") for its full schema.
        """
        return self.call("aspirate_mph96", labware_id=labware_id, mph_pattern=mph_pattern, volume=volume, liquid_class=liquid_class, settings=settings)

    def dispense_mph96(self, *, labware_id: str, mph_pattern: list[str] | list[int] | None = None, volume: float, settings: Any = None) -> Any:
        """Dispense liquid with the MPH96 head into the specified labware.

        Dispense has no liquid-class parameter of its own — the liquid class
        used is whichever one the head aspirated with.

        settings: real type is 'MPH96DispenseSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("dispense_mph96") for its full schema.
        """
        return self.call("dispense_mph96", labware_id=labware_id, mph_pattern=mph_pattern, volume=volume, settings=settings)

    def get_status_mph96(self) -> Any:
        """Return the MPH96 head's current X/Y/Z position and tip-loaded status."""
        return self.call("get_status_mph96")

    def mph96_clear_tip_support(self, *, tip_pool: str) -> Any:
        """Clear a tip support and return remaining tip metadata."""
        return self.call("mph96_clear_tip_support", tip_pool=tip_pool)

    def mph96_detect_liquid_level(self, *, labware_id: str, mph_pattern: list[str] | list[int] | None = None, capacitive_lld: Literal[0, 1, 2, 3, 4, 5] = 1) -> Any:
        """Detect liquid level with the MPH96 head for the selected wells."""
        return self.call("mph96_detect_liquid_level", labware_id=labware_id, mph_pattern=mph_pattern, capacitive_lld=capacitive_lld)

    def mph96_move_axis(self, *, axis: Literal[0, 1, 2], value: float, mode: Literal[0, 1] = 0, safety_bypass_token: str | None = None) -> Any:
        """Move the MPH96 head along the selected axis.

        Args:
            axis: The mechanical axis to move (X, Y, or Z).
            value: Target position or distance in mm.
            safety_bypass_token: Optional token to bypass safety checks.
                VENUS runs its normal safety validation when this is
                omitted; pass the exact literal :data:`hamilton_venus.OVERRIDE_SAFETY_CHECKS`
                to bypass it. It is not an arbitrary flag -- any other string
                is rejected.

                .. warning::

                   Bypassing safety checks risks collisions that can damage hardware
                   or cause injury. Using this token waives vendor liability for any
                   resulting damage.
            mode: Absolute or relative coordinate mode.
        """
        return self.call("mph96_move_axis", axis=axis, value=value, mode=mode, safety_bypass_token=safety_bypass_token)

    def mph96_park_back(self) -> Any:
        """Park the MPH96 head at its rear parking position."""
        return self.call("mph96_park_back")

    def mph96_park_front(self) -> Any:
        """Park the MPH96 head at its front parking position."""
        return self.call("mph96_park_front")

    def tip_eject_mph96(self, *, labware_id: str | None = None, mph_pattern: Literal[0, 1, 2, 3, 4, 5] | None = None, mph_selection: list[str] | list[int] | None = None, eject_mode: Literal['waste', 'return', 'positions', 'tipPool'] = 'waste') -> Any:
        """Eject MPH96 tips, optionally targeting a subset selection pattern.

        `mph_selection` is currently retained as an advanced SDK-only extension
        pending product catalog alignment.
        """
        return self.call("tip_eject_mph96", labware_id=labware_id, mph_pattern=mph_pattern, mph_selection=mph_selection, eject_mode=eject_mode)

    def tip_pick_up_mph96(self, *, labware_id: str | None = None, tip_pool: str | None = None, pre_air_aspirate: Literal[0, 1, 2, 3] = 0, pre_air_volume: float | None = None) -> Any:
        """Pick up a full set of tips with the MPH96 head."""
        return self.call("tip_pick_up_mph96", labware_id=labware_id, tip_pool=tip_pool, pre_air_aspirate=pre_air_aspirate, pre_air_volume=pre_air_volume)

    def tip_pick_up_mph96_partial(self, *, mode: Literal['cols', 'rows'], count: int, labware_id: str | None = None, tip_pool: str | None = None, mph_pickup_side: Literal[0, 1, 2, 3] = 0, pre_air_aspirate: Literal[0, 1, 2, 3] = 0, pre_air_volume: float | None = None) -> Any:
        """Pick up a partial subset of tips with the MPH96 head."""
        return self.call("tip_pick_up_mph96_partial", mode=mode, count=count, labware_id=labware_id, tip_pool=tip_pool, mph_pickup_side=mph_pickup_side, pre_air_aspirate=pre_air_aspirate, pre_air_volume=pre_air_volume)

    # ---- Maintenance ----

    def instrument_get_daily_maintenance_data(self) -> Any:
        """Return the typed daily maintenance status and expiration metadata."""
        return self.call("instrument_get_daily_maintenance_data")

    def instrument_get_verification_data(self) -> Any:
        """Return the typed verification status and expiration metadata."""
        return self.call("instrument_get_verification_data")

    def instrument_get_weekly_maintenance_data(self) -> Any:
        """Return the typed weekly maintenance status and expiration metadata."""
        return self.call("instrument_get_weekly_maintenance_data")

    # ---- MediaFillDeviceCommands ----

    def media_fill_connect(self, *, com_port: int | str) -> Any:
        """Connect and initialize the module on *com_port* (``5`` or ``"COM5"``) and
        register it (HSL ``Initialize``). Like the HSL, also reads the firmware
        version -- and, on real hardware, refuses (disconnects and raises
        :class:`~hamilton_venus.MediaFillError`) a device whose firmware doesn't say
        ``Media Fill Module``: the module's USB id is shared with every Arduino Uno.
        Each module can only be controlled by one process, so close any VENUS method
        or script that has it open first.
        """
        return self.call("media_fill_connect", com_port=com_port)

    def media_fill_disconnect(self, *, device_id: int = 1) -> Any:
        """Disconnect one module; the vendor driver stops all of its active pumps
        (HSL ``Disconnect``). If the vendor call fails, the module stays registered,
        and :meth:`media_fill_terminate` / ``close()`` retries it, then falls back to
        the vendor ``Abort`` (2.0) / ``AbortAll`` (1.1).
        """
        return self.call("media_fill_disconnect", device_id=device_id)

    def media_fill_fill_trough(self, *, pump_id: int, speed: int, timeout: int, device_id: int = 1) -> Any:
        """Start pump *pump_id* (1-4) filling its trough (HSL ``FillTrough``).

        Returns as soon as the pump has started; it runs until the trough's liquid
        level sensor triggers or *timeout* seconds elapse. *speed* is the relative
        rate, 30-100 (%). The pump turns counter-clockwise unless set otherwise with
        :meth:`media_fill_set_pump_direction`. Call :meth:`media_fill_wait_for_pump`
        to block until it stops.
        """
        return self.call("media_fill_fill_trough", pump_id=pump_id, speed=speed, timeout=timeout, device_id=device_id)

    def media_fill_get_device_ids(self) -> Any:
        """Return the registered modules: device id, COM port and firmware version."""
        return self.call("media_fill_get_device_ids")

    def media_fill_get_last_error_message(self) -> Any:
        """Return the last error message from the vendor driver (HSL ``GetLastErrorMessage``).

        A failed command already raises :class:`~hamilton_venus.MediaFillError` with
        this text; this reads it again on demand.
        """
        return self.call("media_fill_get_last_error_message")

    def media_fill_get_liquid_level_sensor_state(self, *, pump_id: int, device_id: int = 1) -> Any:
        """Read the liquid level sensor of pump *pump_id* (1-4) (HSL
        ``GetLiquidLevelSensorState``): ``0`` = liquid not detected; ``1`` = liquid
        detected, **or** the sensor is unplugged, **or** the controller is powered down.
        """
        return self.call("media_fill_get_liquid_level_sensor_state", pump_id=pump_id, device_id=device_id)

    def media_fill_get_pump_direction(self, *, pump_id: int, device_id: int = 1) -> Any:
        """Read the motor direction set for pump *pump_id* (1-4): ``0`` counter-clockwise,
        ``1`` clockwise (HSL ``GetPumpDirection``).
        """
        return self.call("media_fill_get_pump_direction", pump_id=pump_id, device_id=device_id)

    def media_fill_get_status(self, *, device_id: int = 1) -> Any:
        """Everything the module can report, in one call: COM port, firmware version,
        and for each pump 1-4 its direction and liquid level sensor state, plus the
        vendor's last error message. Reads only -- nothing moves. Safe while a pump runs.

        The vendor API has no "is the pump running" query, so there is none here:
        :meth:`media_fill_wait_for_pump` (which blocks) is the only way to learn a
        pump has stopped. Sensor ``1`` also means "unplugged" or "controller off"
        (see :meth:`media_fill_get_liquid_level_sensor_state`).
        """
        return self.call("media_fill_get_status", device_id=device_id)

    def media_fill_set_pump_direction(self, *, pump_id: int, direction: Literal[0, 1] | int | str, device_id: int = 1) -> Any:
        """Set the motor direction of pump *pump_id* (1-4) (HSL ``SetPumpDirection``).

        *direction*: ``PumpDirection.COUNTER_CLOCKWISE`` (0) or ``PumpDirection.CLOCKWISE``
        (1); plain ints (passed to the vendor object unchanged -- it accepts only 0/1)
        and the names ``"ccw"``/``"cw"`` work too. Every pump starts each run counter-clockwise.
        """
        return self.call("media_fill_set_pump_direction", pump_id=pump_id, direction=direction, device_id=device_id)

    def media_fill_stop_pump(self, *, pump_id: int, device_id: int = 1) -> Any:
        """Stop pump *pump_id* (1-4), leaving the module connected (HSL ``StopPump``).

        Needs the 2.0 vendor library; with 1.1 this raises
        :class:`~hamilton_venus.MediaFillError` -- use :meth:`media_fill_disconnect`,
        which stops every pump on the module.
        """
        return self.call("media_fill_stop_pump", pump_id=pump_id, device_id=device_id)

    def media_fill_terminate(self) -> Any:
        """Disconnect every module (stopping their pumps) and release the vendor COM object."""
        return self.call("media_fill_terminate")

    def media_fill_wait_for_pump(self, *, pump_id: int, device_id: int = 1) -> Any:
        """Block until pump *pump_id* (1-4) has finished pumping (HSL ``WaitForPump``).

        Other commands on this client wait until this returns. The 2.0 library raises
        an error once its default timeout of 1 minute passes; 1.1 waits until the pump stops.
        """
        return self.call("media_fill_wait_for_pump", pump_id=pump_id, device_id=device_id)

    def media_fill_waste_pump_no_sensor(self, *, pump_id: int, speed: int, timeout: int, device_id: int = 1) -> Any:
        """Pump *out*: run pump *pump_id* (1-4) in **reverse**, without the liquid level
        sensor (vendor ``EmptyLineToSource`` in the 2.0 library, ``WastePumpNoSensor`` in 1.1;
        both behave the same).

        The pump turns the opposite way to the direction set with
        :meth:`media_fill_set_pump_direction` -- so leave the pump on its *fill*
        direction and this pulls liquid back from the trough toward the source
        bottle (verified on a real module). Setting the other direction first makes
        it pump **into** the trough with nothing to stop it at the sensor. The
        stored direction is not changed.

        Like :meth:`media_fill_fill_trough` it returns once the pump has started,
        with the same *speed* range (30-100 %), but it runs for the full *timeout*
        seconds (stop it early with :meth:`media_fill_stop_pump` on 2.0, or
        :meth:`media_fill_disconnect`). The 2.0 library allows at most 20 s
        (``MaxTimeoutForBackflow``); with 1.1, keep *timeout* within Hamilton's 720 s
        limit per pumping operation (that vendor object does not check it). Call
        :meth:`media_fill_wait_for_pump` to block until it stops.
        """
        return self.call("media_fill_waste_pump_no_sensor", pump_id=pump_id, speed=speed, timeout=timeout, device_id=device_id)

    # ---- ODTCDeviceCommands ----

    def odtc_abort(self, *, device_id: int) -> Any:
        """Abort the in-progress method on *device_id*.

        Harsher than :meth:`odtc_stop_method`: it cancels the current command
        immediately and may leave the unit needing a :meth:`odtc_reset`; prefer
        stop.

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        """
        return self.call("odtc_abort", device_id=device_id)

    def odtc_add_allowed_return_code(self, *, code: int, device_id: int) -> Any:
        """Whitelist a vendor return *code* as non-fatal for *device_id*."""
        return self.call("odtc_add_allowed_return_code", code=code, device_id=device_id)

    def odtc_close_door(self, *, device_id: int) -> Any:
        """Close the unit's plate door (done from ``idle``; takes a few seconds).

        Close it before a run: the block gets hot. Parameters as
        :meth:`odtc_open_door`.
        """
        return self.call("odtc_close_door", device_id=device_id)

    def odtc_connect(self, *, device_ip: str, device_port: str = '8080', local_ip: str = '', initialize: bool = True) -> Any:
        """Connect to the ODTC at *device_ip* and return its identity and state.

        Fetches the unit's SiLA description (``http://<device_ip>/odtc.wsdl``),
        starts a listener for its completion events, then issues a device
        ``Reset`` -- always, even from ``idle``, because that is how the unit
        learns where to send events. **The Reset aborts anything already running
        on the unit.** Unless *initialize* is False it is followed by
        ``Initialize``, leaving the unit ``idle``. No lock is taken (the ODTC has
        no lock command in use).

        Parameters
        ----------
        device_ip:
            IP address of the ODTC, e.g. ``"192.168.1.50"``. Must be reachable
            from this PC on the same network.
        device_port:
            Kept for compatibility with the vendor connect step; **not used** --
            the SiLA description is always fetched from ``device_ip`` on the
            default HTTP port. Leave at ``"8080"``.
        local_ip:
            This PC's address to give the unit as the target for its events
            (the ODTC connects back to it). Empty (default) picks the interface
            that routes to *device_ip*. Set it on a PC with several network
            cards. The listener uses TCP ports 18001-18008, which Windows
            Firewall must allow inbound.
        initialize:
            Run ``Initialize`` after the Reset (default). With ``False`` the unit
            stays in ``standby``, where it accepts almost nothing.

        Returns
        -------
        ODTCConnectResponse
            ``unit`` holds ``device_id`` (the handle every other command takes),
            firmware version, serial number and state.
        """
        return self.call("odtc_connect", device_ip=device_ip, device_port=device_port, local_ip=local_ip, initialize=initialize)

    def odtc_download_logs(self, *, device_id: int, dest_dir: Any = 'odtc_logs', include_traces: bool = False) -> Any:
        """Copy the unit's log files to *dest_dir* (created if needed).

        Not a SiLA command: the unit serves its logs over anonymous FTP, and this
        copies everything under its ``Logs``, ``Odtc``, ``SiLA`` and ``Backup``
        folders, keeping the layout -- ``SiLA/Logs/InhecoSiLA.log`` is the SiLA
        stack's own log and the first place to look when the unit reports an
        error state. ``include_traces=True`` also copies ``Traces`` (one folder
        per day, which can be large). Not the same as :meth:`odtc_get_run_data`,
        which is the temperature trace of the last run.

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        dest_dir:
            Local folder to copy into (default ``"odtc_logs"`` in the current
            directory); created if missing, existing files are overwritten.
        include_traces:
            Also copy ``Traces`` (default ``False``): one CSV per run, so it can
            be many megabytes.

        dest_dir: real type is 'str | Path' -- not representable as a plain type hint here; see describe_sdk_command("odtc_download_logs") for its full schema.
        """
        return self.call("odtc_download_logs", device_id=device_id, dest_dir=dest_dir, include_traces=include_traces)

    def odtc_download_run_trace(self, *, device_id: int, dest_dir: Any = 'odtc_traces', method_name: str | None = None) -> Any:
        """Download and parse the unit's own temperature trace of its latest run.

        Every run leaves a trace on the unit (``Traces/<date>/<start time>.csv``,
        about 5 samples a second with many sensor columns). This fetches the
        newest one -- or the newest for *method_name*, which is how to be sure it
        is the run you just did -- saves the whole file under *dest_dir*, and
        returns the block target / block actual / lid temperatures per sample.
        Raises if no matching trace is found among the newest few. Prefer this to
        :meth:`odtc_get_run_data`, which was seen returning an older run's trace.

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        dest_dir:
            Local folder to save the trace CSV into (default ``"odtc_traces"``);
            created if missing.
        method_name:
            Only accept a trace of this method (the newest few are searched).
            ``None`` (default) takes the very latest run whatever it was. The
            file can take a few seconds to appear after a run ends, so retry.

        dest_dir: real type is 'str | Path' -- not representable as a plain type hint here; see describe_sdk_command("odtc_download_run_trace") for its full schema.
        """
        return self.call("odtc_download_run_trace", device_id=device_id, dest_dir=dest_dir, method_name=method_name)

    def odtc_get_device_identification(self, *, device_id: int) -> Any:
        """Return firmware version / serial number / manufacturer for one unit.

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        """
        return self.call("odtc_get_device_identification", device_id=device_id)

    def odtc_get_device_ids(self) -> Any:
        """Return the ``device_id`` of every currently registered ODTC unit."""
        return self.call("odtc_get_device_ids")

    def odtc_get_parameters(self, *, device_id: int) -> Any:
        """Return the unit's raw device parameters XML (includes every method stored on it)."""
        return self.call("odtc_get_parameters", device_id=device_id)

    def odtc_get_run_data(self, *, device_id: int) -> Any:
        """Return the unit's own temperature trace of its most recent run.

        One row per sample (about 1 per second): ``series`` (the run's start
        time), ``elapsedMs``, ``targetTemperature``, ``currentTemperature`` and
        ``lidTemperature`` in degrees C. **Not reliable as "the last run":** after
        two runs that completed normally it still returned the trace of an older,
        stopped one. Use :meth:`odtc_download_run_trace`, which reads the unit's
        per-run trace files and can match on the method name.
        """
        return self.call("odtc_get_run_data", device_id=device_id)

    def odtc_get_status(self, *, device_id: int | None = None) -> Any:
        """Return state / locked / door-open per unit.

        Parameters
        ----------
        device_id:
            Unit to read, or ``None`` (default) for every connected unit.

        The ``state`` is one of ``startup``, ``standby``, ``idle``, ``busy``,
        ``paused``, ``inError`` (``busy`` includes a running method and door
        moves). ``locked`` is normally ``False``: this driver takes no lock.
        """
        return self.call("odtc_get_status", device_id=device_id)

    def odtc_get_temperature(self, *, device_id: int | None = None) -> Any:
        """Return block + lid temperature per unit, in degrees C.

        Parameters
        ----------
        device_id:
            Unit to read, or ``None`` (default) for every connected unit.

        Can be refused for a moment while the unit is switching steps.
        """
        return self.call("odtc_get_temperature", device_id=device_id)

    def odtc_import_methods(self, *, protocol_file: Any, device_id: int) -> Any:
        """Upload every method in a vendor ``<MethodSet>`` XML file to the unit
        *without running any of them*.

        The unit stores them (persistently, alongside its own), so afterwards
        they show up in :meth:`odtc_list_methods` and run by name with
        :meth:`odtc_run_stored_method`. Returns the methods that were in the file.
        A file holding ``<DeleteAllMethods>true</DeleteAllMethods>`` would make
        the unit discard its other methods; that is refused here.

        Parameters
        ----------
        protocol_file:
            Path of a vendor ``<MethodSet>`` XML file (e.g. Inheco's exported
            protocols); UTF-8, with or without a BOM. It must contain at least one
            ``<Method>`` or ``<PreMethod>``. Methods with a name already on the
            unit replace it.
        device_id:
            The handle returned by :meth:`odtc_connect` (keyword-only).

        protocol_file: real type is 'str | Path' -- not representable as a plain type hint here; see describe_sdk_command("odtc_import_methods") for its full schema.
        """
        return self.call("odtc_import_methods", protocol_file=protocol_file, device_id=device_id)

    def odtc_list_methods(self, *, device_id: int) -> Any:
        """List the methods stored on the unit, by name.

        Each entry is a ``PreMethod`` (a plain block + lid temperature hold) or
        a ``Method`` (a stepped/cycling program). Run one already on the unit
        by name via :meth:`odtc_run_stored_method`.
        """
        return self.call("odtc_list_methods", device_id=device_id)

    def odtc_open_door(self, *, device_id: int) -> Any:
        """Open the unit's plate door (done from ``idle``; takes a few seconds).

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        """
        return self.call("odtc_open_door", device_id=device_id)

    def odtc_pause(self, *, device_id: int) -> Any:
        """Pause the in-progress method on *device_id*.

        **Unreliable on the unit this was tested on.** The request is accepted
        (state ``busy``, sub-state ``ExecuteMethod: pauseRequested``) but the
        unit never reaches ``paused`` -- not on a plain hold (``PreMethod``) and
        not on a stepped method with 30 s steps (watched for over a minute) --
        so this call raises a timeout. While the request is pending the unit
        refuses ``odtc_resume``, ``odtc_stop_method`` and temperature reads,
        and stays that way after the method would have finished;
        :meth:`odtc_reset` is the only recovery found.
        """
        return self.call("odtc_pause", device_id=device_id)

    def odtc_reset(self, *, device_id: int, timeout: int = 60, simulate_on_device_base: bool = False, initialize: bool = True) -> Any:
        """Reset *device_id* (firmware-level reset) -- aborts any running method.

        This is the recovery path for a stuck unit (e.g. a pending pause, or
        ``inError``). A reset leaves the unit in ``standby``, where it accepts
        almost nothing, so by default it is followed by ``Initialize`` to bring
        it back to ``idle``; pass ``initialize=False`` to stay in ``standby``
        (the only state that accepts configuration changes).
        """
        return self.call("odtc_reset", device_id=device_id, timeout=timeout, simulate_on_device_base=simulate_on_device_base, initialize=initialize)

    def odtc_resume(self, *, device_id: int) -> Any:
        """Resume a paused method on *device_id* (see the caveats on :meth:`odtc_pause`).

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        """
        return self.call("odtc_resume", device_id=device_id)

    def odtc_run_protocol(self, *, protocol: Any, method_name: str | None = None, priority: int = 1, device_id: int, wait: bool = False, timeout: int = 3600) -> Any:
        """Upload and run a PCR protocol on *device_id*.

        Bundles the vendor ``SetMethod`` with ``ExecuteMethod`` -- mirroring
        Hamilton's own ``InhecoODTCController.hsi`` ``ExecuteProtocol``, which
        combines the same two calls.

        Parameters
        ----------
        protocol:
            Either the path to an existing vendor-authored ``<MethodSet>`` XML
            file, or an :class:`~hamilton_venus.odtc_protocol.ODTCProtocol`
            built in Python (see :mod:`hamilton_venus.odtc_protocol`).
        method_name:
            Which ``<Method>``/``<PreMethod>`` in the file/protocol to run.
            Required when *protocol* is a file with more than one method;
            defaults to the protocol's own ``method_name`` when *protocol* is
            an :class:`ODTCProtocol`, or to a file's single method.
        priority:
            Execution priority sent with ``ExecuteMethod``, an integer of at least 1
            (0 is rejected by the unit; lower values are clamped up to 1). There is
            one method at a time, so leave it at the default ``1``.
        device_id:
            The handle returned by :meth:`odtc_connect` (keyword-only).
        wait:
            ``False`` (default): return as soon as the unit accepts the run --
            it then runs for minutes, so poll :meth:`odtc_get_status` or call
            :meth:`odtc_wait_for_protocol`. ``True``: block until it finishes.
        timeout:
            With ``wait=True``, the most seconds to wait for the run to finish
            (default 3600) before raising. Set it comfortably above the estimate.

        Returns
        -------
        ODTCProtocolRunResponse
            Includes ``estimated_duration_seconds``, the unit's own estimate of
            the run (``None`` if it gave none). A stepped ``Method`` only starts
            after a ``PreMethod`` has finished; a PreMethod has no natural end
            beyond reaching temperature. Build protocols with
            :class:`~hamilton_venus.odtc_protocol.ODTCProtocolBuilder`.

        protocol: real type is 'str | Path | ODTCProtocol' -- not representable as a plain type hint here; see describe_sdk_command("odtc_run_protocol") for its full schema.
        """
        return self.call("odtc_run_protocol", protocol=protocol, method_name=method_name, priority=priority, device_id=device_id, wait=wait, timeout=timeout)

    def odtc_run_stored_method(self, *, method_name: str, device_id: int, priority: int = 1, wait: bool = False, timeout: int = 3600) -> Any:
        """Run a method that is *already stored on the unit*, by name.

        Nothing is uploaded -- use :meth:`odtc_list_methods` to see what the
        unit holds (it ships with ``PRE25``, ``PRE55`` and others), or
        :meth:`odtc_run_protocol` to upload and run your own.

        Parameters
        ----------
        method_name:
            Exact, case-sensitive name of a ``Method`` or ``PreMethod`` on the unit.
        device_id:
            The handle returned by :meth:`odtc_connect` (keyword-only).
        priority:
            Execution priority, at least 1 (default 1); see :meth:`odtc_run_protocol`.
        wait:
            ``False`` (default) returns once the run is accepted; ``True`` blocks
            until it finishes.
        timeout:
            With ``wait=True``, the most seconds to wait (default 3600).
        """
        return self.call("odtc_run_stored_method", method_name=method_name, device_id=device_id, priority=priority, wait=wait, timeout=timeout)

    def odtc_set_csv_separator(self, *, character: str, device_id: int) -> Any:
        """Set the separator character used in the data ``odtc_get_run_data`` reports.

        Use a single character such as ``";"`` or ``","`` -- per the Hamilton
        help file, separators like ``"."`` or ``":"`` may cripple the data.
        """
        return self.call("odtc_set_csv_separator", character=character, device_id=device_id)

    def odtc_set_date_time(self, *, date_time: Any, device_id: int) -> Any:
        """Set the unit's onboard clock.

        Pass a ``datetime`` (naive values are taken as UTC; aware ones are
        converted to UTC) or a string already in the device's
        ``YYYY-MM-DDTHH:MM:SSZ`` format. Like :meth:`odtc_set_log_level`, this
        needs the unit's ``standby`` state and so runs a Reset -> configure ->
        Initialize round trip (about a minute); it refuses while a method runs.

        date_time: real type is 'str | datetime' -- not representable as a plain type hint here; see describe_sdk_command("odtc_set_date_time") for its full schema.
        """
        return self.call("odtc_set_date_time", date_time=date_time, device_id=device_id)

    def odtc_set_log_level(self, *, level: str, device_id: int) -> Any:
        """Set the *device's own* log level: ``"DEBUG"``, ``"INFO"``, ``"WARN"``, ``"ERROR"`` or ``"FATAL"``.

        Per the Hamilton help file this should only be changed when requested
        by Hamilton or Inheco personnel. The unit only accepts configuration
        changes in its ``standby`` state, so from ``idle`` this runs a
        Reset -> configure -> Initialize round trip (about a minute) and
        refuses while a method is running.
        """
        return self.call("odtc_set_log_level", level=level, device_id=device_id)

    def odtc_set_parameter(self, *, name: str, type_: str, value: str, device_id: int) -> Any:
        """Set one device parameter by name."""
        return self.call("odtc_set_parameter", name=name, type_=type_, value=value, device_id=device_id)

    def odtc_stop_method(self, *, device_id: int) -> Any:
        """Stop the in-progress method on *device_id*; harmless when the unit is idle.

        Call it before :meth:`odtc_terminate_device`. If the unit is still busy
        finishing another command (e.g. right after :meth:`odtc_abort`) the stop
        is retried for up to a minute.

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        """
        return self.call("odtc_stop_method", device_id=device_id)

    def odtc_terminate(self) -> Any:
        """Disconnect every registered ODTC unit. Does **not** stop running methods --
        see :meth:`odtc_terminate_device` for why to wait for or stop them first.
        """
        return self.call("odtc_terminate")

    def odtc_terminate_device(self, *, device_id: int) -> Any:
        """Disconnect one ODTC unit. Does **not** stop a running method.

        Don't disconnect while a method is still running: the unit reports its
        completion to this PC, and if nobody is listening any more it logs an
        event error and drops into ``inError`` (the next :meth:`odtc_connect`
        clears that with a Reset). Wait for the run to finish
        (:meth:`odtc_wait_for_protocol`) or call :meth:`odtc_stop_method` first.
        """
        return self.call("odtc_terminate_device", device_id=device_id)

    def odtc_wait_for_protocol(self, *, device_id: int, request_id: str | None = None, timeout: int = 3600) -> Any:
        """Block until *device_id*'s in-progress protocol run completes.

        *request_id* defaults to the id returned by the most recent
        :meth:`odtc_run_protocol` call on this unit.

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        request_id:
            Which run to wait for; default the last one started on this unit.
        timeout:
            Most seconds to wait (default 3600) before raising; set it above the
            run's ``estimated_duration_seconds``.
        """
        return self.call("odtc_wait_for_protocol", device_id=device_id, request_id=request_id, timeout=timeout)

    # ---- PipettingArm ----

    def pip_arm_get_x_position(self, *, arm_id: int = 1) -> Any:
        """Return the raw X-axis position response for the selected pipetting arm."""
        return self.call("pip_arm_get_x_position", arm_id=arm_id)

    def pip_arm_move(self, *, value: float, coordinate_mode: Literal[0, 1] | None = None, arm_id: int = 1, speed: Literal['Slow', 'Reduced', 'Standard'] | None = None, safety_bypass_token: str | None = None) -> Any:
        """Move a pipetting arm using absolute or relative coordinates.

        Args:
            value: Target position or distance in mm.
            safety_bypass_token: Optional token to bypass safety checks.
                VENUS runs its normal safety validation when this is
                omitted; pass the exact literal :data:`hamilton_venus.OVERRIDE_SAFETY_CHECKS`
                to bypass it. It is not an arbitrary flag -- any other string
                is rejected.

                .. warning::

                   Bypassing safety checks risks collisions that can damage hardware
                   or cause injury. Using this token waives vendor liability for any
                   resulting damage.
            coordinate_mode: Absolute or relative coordinate mode.
            arm_id: Arm identifier (default 1).
            speed: Movement speed setting.
        """
        return self.call("pip_arm_move", value=value, coordinate_mode=coordinate_mode, arm_id=arm_id, speed=speed, safety_bypass_token=safety_bypass_token)

    def pip_arm_park_left(self, *, arm_id: int = 1) -> Any:
        """Park the selected pipetting arm at the left side of the deck."""
        return self.call("pip_arm_park_left", arm_id=arm_id)

    def pip_arm_park_right(self, *, arm_id: int = 1) -> Any:
        """Park the selected pipetting arm at the right side of the deck."""
        return self.call("pip_arm_park_right", arm_id=arm_id)

    # ---- PoolSamplesCommand ----

    def pool_samples(self, *, source_plate: Any, dest_plate: Any, pool_size: int, volume_per_source: float, liquid_class: str | list[str], tip_pool: str, channels: list[int] | None = None, source_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', dest_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', mix_after_pool: bool = True, reuse_tips_within_pool: bool = False, optimized_tip_pickup: bool = True, aspirate_settings: Any = None, dispense_settings: Any = None, error_profile: Any = None) -> Any:
        """Combine ``N`` source wells into one destination well, one pool at a time.

        See :func:`hamilton_venus.compound_commands.pool_samples.execute_pool_samples`
        for the full parameter reference.

        source_plate: real type is 'str | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("pool_samples") for its full schema.
        dest_plate: real type is 'str | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("pool_samples") for its full schema.
        aspirate_settings: real type is 'AspirateSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("pool_samples") for its full schema.
        dispense_settings: real type is 'DispenseSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("pool_samples") for its full schema.
        error_profile: real type is 'ErrorProfile | None' -- not representable as a plain type hint here; see describe_sdk_command("pool_samples") for its full schema.
        """
        return self.call("pool_samples", source_plate=source_plate, dest_plate=dest_plate, pool_size=pool_size, volume_per_source=volume_per_source, liquid_class=liquid_class, tip_pool=tip_pool, channels=channels, source_order=source_order, dest_order=dest_order, mix_after_pool=mix_after_pool, reuse_tips_within_pool=reuse_tips_within_pool, optimized_tip_pickup=optimized_tip_pickup, aspirate_settings=aspirate_settings, dispense_settings=dispense_settings, error_profile=error_profile)

    # ---- ReplicateSamplesCommand ----

    def replicate_samples(self, *, source_plate: Any, dest_plate: Any, replicates_per_source: int, volume_per_replicate: float, liquid_class: str | list[str], tip_pool: str, channels: list[int] | None = None, source_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', dest_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc', multi_dispense: bool = True, pre_aliquot_volume: float = 0.0, pre_aliquot_disposal: Literal['source', 'waste'] = 'source', post_aliquot_volume: float = 0.0, post_aliquot_height: float = 5.0, optimized_tip_pickup: bool = True, aspirate_settings: Any = None, dispense_settings: Any = None, error_profile: Any = None) -> Any:
        """Replicate every source well into ``replicates_per_source`` destination wells.

        See :func:`hamilton_venus.compound_commands.replicate_samples.execute_replicate_samples`
        for the full parameter reference.

        source_plate: real type is 'str | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("replicate_samples") for its full schema.
        dest_plate: real type is 'str | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("replicate_samples") for its full schema.
        aspirate_settings: real type is 'AspirateSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("replicate_samples") for its full schema.
        dispense_settings: real type is 'DispenseSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("replicate_samples") for its full schema.
        error_profile: real type is 'ErrorProfile | None' -- not representable as a plain type hint here; see describe_sdk_command("replicate_samples") for its full schema.
        """
        return self.call("replicate_samples", source_plate=source_plate, dest_plate=dest_plate, replicates_per_source=replicates_per_source, volume_per_replicate=volume_per_replicate, liquid_class=liquid_class, tip_pool=tip_pool, channels=channels, source_order=source_order, dest_order=dest_order, multi_dispense=multi_dispense, pre_aliquot_volume=pre_aliquot_volume, pre_aliquot_disposal=pre_aliquot_disposal, post_aliquot_volume=post_aliquot_volume, post_aliquot_height=post_aliquot_height, optimized_tip_pickup=optimized_tip_pickup, aspirate_settings=aspirate_settings, dispense_settings=dispense_settings, error_profile=error_profile)

    # ---- SampleTracking ----

    def get_barcode_locations(self, *, barcodes: list[str]) -> Any:
        """Return where each barcode is currently tracked on the deck.

        Found barcodes are listed in ``.return_parameters.barcodes`` with their
        ``labware_id``, ``well`` (empty for a labware-level barcode) and
        ``labware_type``; the rest are listed in ``.return_parameters.not_found``.

        Call ``.to_positions()`` on the response to turn the found barcodes into
        position selectors (``"Plate_1@A1"``) that aspirate/dispense steps accept.
        """
        return self.call("get_barcode_locations", barcodes=barcodes)

    def get_labware_details(self, *, labware: Any, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc') -> Any:
        """Return the current sample tracking details (barcode, volume, state, position) for labware.

        Args:
            labware: What to report on, as one entry or a list. Each entry may be:

                - a position selector as used by pipetting steps: ``"Plate_1"`` or
                  ``"Plate_1@all"`` (every well loaded in the labware),
                  ``"Plate_1@A1,B1"``, ``"Plate_1@A1:C3"``, ``"Plate_1@col:1"``, ...
                - a ``Position`` or a ``{"labwareId": ..., "wellId": ...}`` dict
                - a TrackingLabwareQuery, or a dict with ``labwareId`` and optional
                  ``wells`` (well IDs or ``{"id": "A1"}`` objects)
            well_order: Order in which selector ranges are expanded.

        A labware item that cannot be reported (not on the layout, nothing tracked
        on it yet) carries the reason in its ``message`` instead of failing the command.

        Wells are returned sorted by deck position: X ascending, then Y descending,
        then Z descending.

        Limitation: VENUS sample tracking keeps no volume for reservoirs (connected
        containers), tip racks or carriers, so well ``volume`` is ``None`` for labware
        of type ``Reservoir Rack``, ``Tip Rack`` and ``Template``. Reservoirs also
        track no well state and no well barcode, so ``labware_state`` and ``barcode``
        are ``None`` for their wells too.

        labware: real type is 'str | Position | dict | TrackingLabwareQuery | list | list | list | list' -- not representable as a plain type hint here; see describe_sdk_command("get_labware_details") for its full schema.
        """
        return self.call("get_labware_details", labware=labware, well_order=well_order)

    def set_barcodes(self, *, labware: Any, barcodes: str | list[str] | None = None, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc') -> Any:
        """Assign barcodes to labware and/or to individual wells.

        Two call forms:

        - ``set_barcodes("Plate_1@A1,B1,C1", ["bc1", "bc2", "bc3"])`` -- positions as
          used by pipetting steps (selector, ``Position``, ``labwareId``/``wellId``
          dict, or a list of those) paired in order with ``barcodes``. A bare labware
          ID (``"Plate_1"``) takes one barcode, assigned to the labware itself.
        - ``set_barcodes([{...}])`` -- TrackingLabwareBarcodes entries, or dicts with
          ``labwareId`` (required), optional ``barcode`` (the labware itself) and
          optional ``wells`` (``{"id": "A1", "barcode": "..."}`` objects).

        Args:
            labware: Positions (with ``barcodes``) or explicit barcode entries.
            barcodes: Barcodes for the positions in ``labware``, in expansion order.
            well_order: Order in which selector ranges are expanded.

        labware: real type is 'str | Position | dict | TrackingLabwareBarcodes | list | list | list | list' -- not representable as a plain type hint here; see describe_sdk_command("set_barcodes") for its full schema.
        """
        return self.call("set_barcodes", labware=labware, barcodes=barcodes, well_order=well_order)

    def set_labware_volume(self, *, labware: Any, volume: float | None = None, well_order: Literal['col-asc', 'col-desc', 'row-asc', 'row-desc', 'custom'] = 'col-asc') -> Any:
        """Set the tracked liquid volume of labware and/or of individual wells.

        Two call forms:

        - ``set_labware_volume("Plate_1@A1:H1", 50.0)`` -- positions as used by
          pipetting steps (selector, ``Position``, ``labwareId``/``wellId`` dict, or a
          list of those), each set to ``volume``. A bare labware ID or ``@all`` sets
          every well of the labware.
        - ``set_labware_volume([{...}])`` -- TrackingLabwareVolume entries, or dicts
          with ``labwareId`` (required), optional ``volume`` (every well) and optional
          ``wells`` (``{"id": "A1", "volume": 50.0}`` objects, applied after ``volume``).

        Limitation: VENUS sample tracking keeps no volume for reservoirs (connected
        containers), tip racks or carriers; setting one succeeds but has no effect.

        Args:
            labware: Positions (with ``volume``) or explicit volume entries.
            volume: Volume in uL for the positions in ``labware``.
            well_order: Order in which selector ranges are expanded.

        labware: real type is 'str | Position | dict | TrackingLabwareVolume | list | list | list | list' -- not representable as a plain type hint here; see describe_sdk_command("set_labware_volume") for its full schema.
        """
        return self.call("set_labware_volume", labware=labware, volume=volume, well_order=well_order)

    # ---- SerialDilutionCommand ----

    def serial_dilution_by_dilution_factor(self, *, plate_id: Any, start_column: int, num_dilutions: int, transfer_volume: float, dilution_factor: float, diluent_source: str | list[str], diluent_liquid_class: str | list[str] = 'HighVolume_Water_DispenseJet_Empty', diluent_tip_pool: str = '', transfer_liquid_class: str | list[str] = 'HighVolume_Water_DispenseJet_Empty', transfer_tip_pool: str, channels: list[int] | None = None, exclude_columns: list[int] | None = None, exclude_rows: list[int | str] | None = None, mix_after_dispense: bool = True, diluent_multi_dispense: bool = True, reuse_tips: bool = False, discard_last_excess: Literal['none', 'to_waste', 'with_tip_eject'] = 'none', waste_location: str | None = None, optimized_tip_pickup: bool = True, diluent_asp_settings: Any = None, diluent_disp_settings: Any = None, transfer_asp_settings: Any = None, transfer_disp_settings: Any = None, diluent_error_profile: Any = None, transfer_error_profile: Any = None) -> Any:
        """Serial-dilute across plate columns using a target fold ``dilution_factor``.

        See
        :func:`hamilton_venus.compound_commands.serial_dilution.execute_serial_dilution_by_dilution_factor`
        for the full parameter reference.

        plate_id: real type is 'str | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("serial_dilution_by_dilution_factor") for its full schema.
        diluent_asp_settings: real type is 'AspirateSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("serial_dilution_by_dilution_factor") for its full schema.
        diluent_disp_settings: real type is 'DispenseSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("serial_dilution_by_dilution_factor") for its full schema.
        transfer_asp_settings: real type is 'AspirateSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("serial_dilution_by_dilution_factor") for its full schema.
        transfer_disp_settings: real type is 'DispenseSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("serial_dilution_by_dilution_factor") for its full schema.
        diluent_error_profile: real type is 'ErrorProfile | None' -- not representable as a plain type hint here; see describe_sdk_command("serial_dilution_by_dilution_factor") for its full schema.
        transfer_error_profile: real type is 'ErrorProfile | None' -- not representable as a plain type hint here; see describe_sdk_command("serial_dilution_by_dilution_factor") for its full schema.
        """
        return self.call("serial_dilution_by_dilution_factor", plate_id=plate_id, start_column=start_column, num_dilutions=num_dilutions, transfer_volume=transfer_volume, dilution_factor=dilution_factor, diluent_source=diluent_source, diluent_liquid_class=diluent_liquid_class, diluent_tip_pool=diluent_tip_pool, transfer_liquid_class=transfer_liquid_class, transfer_tip_pool=transfer_tip_pool, channels=channels, exclude_columns=exclude_columns, exclude_rows=exclude_rows, mix_after_dispense=mix_after_dispense, diluent_multi_dispense=diluent_multi_dispense, reuse_tips=reuse_tips, discard_last_excess=discard_last_excess, waste_location=waste_location, optimized_tip_pickup=optimized_tip_pickup, diluent_asp_settings=diluent_asp_settings, diluent_disp_settings=diluent_disp_settings, transfer_asp_settings=transfer_asp_settings, transfer_disp_settings=transfer_disp_settings, diluent_error_profile=diluent_error_profile, transfer_error_profile=transfer_error_profile)

    def serial_dilution_by_volume(self, *, plate_id: Any, start_column: int, num_dilutions: int, transfer_volume: float, diluent_volume: float, diluent_source: str | list[str], diluent_liquid_class: str | list[str] = 'HighVolume_Water_DispenseJet_Empty', diluent_tip_pool: str = '', transfer_liquid_class: str | list[str] = 'HighVolume_Water_DispenseJet_Empty', transfer_tip_pool: str, channels: list[int] | None = None, exclude_columns: list[int] | None = None, exclude_rows: list[int | str] | None = None, mix_after_dispense: bool = True, diluent_multi_dispense: bool = True, reuse_tips: bool = False, discard_last_excess: Literal['none', 'to_waste', 'with_tip_eject'] = 'none', waste_location: str | None = None, optimized_tip_pickup: bool = True, diluent_asp_settings: Any = None, diluent_disp_settings: Any = None, transfer_asp_settings: Any = None, transfer_disp_settings: Any = None, diluent_error_profile: Any = None, transfer_error_profile: Any = None) -> Any:
        """Serial-dilute across plate columns using an explicit per-well diluent volume.

        See
        :func:`hamilton_venus.compound_commands.serial_dilution.execute_serial_dilution_by_volume`
        for the full parameter reference.

        plate_id: real type is 'str | list | Position | list' -- not representable as a plain type hint here; see describe_sdk_command("serial_dilution_by_volume") for its full schema.
        diluent_asp_settings: real type is 'AspirateSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("serial_dilution_by_volume") for its full schema.
        diluent_disp_settings: real type is 'DispenseSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("serial_dilution_by_volume") for its full schema.
        transfer_asp_settings: real type is 'AspirateSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("serial_dilution_by_volume") for its full schema.
        transfer_disp_settings: real type is 'DispenseSettings | None' -- not representable as a plain type hint here; see describe_sdk_command("serial_dilution_by_volume") for its full schema.
        diluent_error_profile: real type is 'ErrorProfile | None' -- not representable as a plain type hint here; see describe_sdk_command("serial_dilution_by_volume") for its full schema.
        transfer_error_profile: real type is 'ErrorProfile | None' -- not representable as a plain type hint here; see describe_sdk_command("serial_dilution_by_volume") for its full schema.
        """
        return self.call("serial_dilution_by_volume", plate_id=plate_id, start_column=start_column, num_dilutions=num_dilutions, transfer_volume=transfer_volume, diluent_volume=diluent_volume, diluent_source=diluent_source, diluent_liquid_class=diluent_liquid_class, diluent_tip_pool=diluent_tip_pool, transfer_liquid_class=transfer_liquid_class, transfer_tip_pool=transfer_tip_pool, channels=channels, exclude_columns=exclude_columns, exclude_rows=exclude_rows, mix_after_dispense=mix_after_dispense, diluent_multi_dispense=diluent_multi_dispense, reuse_tips=reuse_tips, discard_last_excess=discard_last_excess, waste_location=waste_location, optimized_tip_pickup=optimized_tip_pickup, diluent_asp_settings=diluent_asp_settings, diluent_disp_settings=diluent_disp_settings, transfer_asp_settings=transfer_asp_settings, transfer_disp_settings=transfer_disp_settings, diluent_error_profile=diluent_error_profile, transfer_error_profile=transfer_error_profile)

    # ---- SplitWell ----

    def get_split_wells(self, *, labware_name: str | None = None) -> Any:
        """The wells currently split, optionally only those of *labware_name*."""
        return self.call("get_split_wells", labware_name=labware_name)

    def remove_split_wells(self, *, labware_name: str | None = None, wells: str | list[str] | None = None, channel_type: Literal['1mL', '5mL'] | None = None, consolidate_volumes: bool = False) -> Any:
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
        return self.call("remove_split_wells", labware_name=labware_name, wells=wells, channel_type=channel_type, consolidate_volumes=consolidate_volumes)

    def split_wells(self, *, labware_name: str, wells: str | list[str] | None = None, channel_type: Literal['1mL', '5mL'] = '1mL', max_channels: int | None = None, fit: Literal['position', 'max_channels'] | int = 'position', well_position: Literal['Center', 'DeepestPoint', 'HighestPoint'] | None = None, tip_profile: Any = None, tip_end_height_mm: float | None = None, wall_margin_mm: float | None = None, high_wall_margin_mm: float | None = None) -> Any:
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

        tip_profile: real type is 'TipProfile | None' -- not representable as a plain type hint here; see describe_sdk_command("split_wells") for its full schema.
        """
        return self.call("split_wells", labware_name=labware_name, wells=wells, channel_type=channel_type, max_channels=max_channels, fit=fit, well_position=well_position, tip_profile=tip_profile, tip_end_height_mm=tip_end_height_mm, wall_margin_mm=wall_margin_mm, high_wall_margin_mm=high_wall_margin_mm)

    # ---- Status ----

    def instrument_connect(self, *, initialize: bool = True) -> Any:
        """Connect the instrument runtime, optionally initializing the instrument."""
        return self.call("instrument_connect", initialize=initialize)

    def instrument_init(self, *, force_init: bool = False) -> Any:
        """Initialize the instrument, optionally forcing re-initialization.

        Args:
            force_init: If True, force re-initialization even if already initialized.

        Returns:
            StatusInitResponse with success status and any error details.
        """
        return self.call("instrument_init", force_init=force_init)

    def instrument_is_connected(self) -> Any:
        """Return whether the instrument runtime is connected and responding."""
        return self.call("instrument_is_connected")

    def instrument_is_idle(self) -> Any:
        """Return whether the instrument runtime is idle (no commands running)."""
        return self.call("instrument_is_idle")

    def instrument_terminate(self) -> Any:
        """Terminate the current method execution."""
        return self.call("instrument_terminate")

    # ---- StatusLight ----

    def status_light_set_front_light(self, *, color: Literal[0, 1, 2, 3], blink: bool = False, progress: int = 0) -> Any:
        """Set color, blink, and discrete progress level in one command."""
        return self.call("status_light_set_front_light", color=color, blink=blink, progress=progress)

    def status_light_set_interior_light(self, *, light_state: Literal[0, 1, 2, 3], light_intensity: int | None = None, blink_interval: int | None = None, white: int = 0, red: int = 0, green: int = 0, blue: int = 0) -> Any:
        """Set the Vantage interior light state, intensity, blink interval, and color mix.

        ``light_intensity`` (0-100) and ``colors`` are only used when ``light_state`` is
        ``ON`` or ``BLINK``. ``blink_interval`` (1-10000 ms) is only used when
        ``light_state`` is ``BLINK`` or ``RAINBOW_DASH``. Omit optional parameters to
        let the instrument use its own defaults.

        Vantage only -- not available on STAR.
        """
        return self.call("status_light_set_interior_light", light_state=light_state, light_intensity=light_intensity, blink_interval=blink_interval, white=white, red=red, green=green, blue=blue)

    # ---- TaughtLocation ----

    def clear_taught_locations(self) -> Any:
        """Empty both maps, leaving a canonical empty file in place."""
        return self.call("clear_taught_locations")

    def get_taught_locations(self) -> Any:
        """Return the whole taught-locations file (an empty model when it does not exist)."""
        return self.call("get_taught_locations")

    def get_taught_offset(self, *, carrier: str, site: str | int) -> Any:
        """Return the offset recorded for a carrier/site, or ``None``."""
        return self.call("get_taught_offset", carrier=carrier, site=site)

    def get_taught_position(self, *, labware: str, carrier: str, site: str | int) -> Any:
        """Return the position recorded for a labware item at a carrier/site, or ``None``."""
        return self.call("get_taught_position", labware=labware, carrier=carrier, site=site)

    def get_taught_positions(self, *, labware: str) -> Any:
        """Return every taught position for a labware item, keyed by ``"<carrier>/<site>"`` (``{}`` if none)."""
        return self.call("get_taught_positions", labware=labware)

    def register_taught_offset(self, *, carrier: str, site: str | int, dx: float, dy: float, dz: float, d_angle: float = 0.0, note: str | None = None) -> Any:
        """Record an X/Y/Z (+ angle) offset for a carrier/site, replacing any prior one."""
        return self.call("register_taught_offset", carrier=carrier, site=site, dx=dx, dy=dy, dz=dz, d_angle=d_angle, note=note)

    def register_taught_position(self, *, labware: str, carrier: str, site: str | int, x: float, y: float, z: float, angle: float = 0.0, note: str | None = None) -> Any:
        """Record absolute coordinates for a labware item at a carrier/site, replacing any prior one."""
        return self.call("register_taught_position", labware=labware, carrier=carrier, site=site, x=x, y=y, z=z, angle=angle, note=note)

    def remove_taught_offset(self, *, carrier: str, site: str | int) -> Any:
        """Delete the offset for a carrier/site. Returns ``True`` if one was present."""
        return self.call("remove_taught_offset", carrier=carrier, site=site)

    def remove_taught_position(self, *, labware: str, carrier: str | None = None, site: str | int | None = None) -> Any:
        """Delete taught positions for a labware item.

        Pass ``carrier`` and ``site`` together to delete just that combination;
        omit both to delete every taught position for the labware. Returns
        ``True`` if anything was removed.
        """
        return self.call("remove_taught_position", labware=labware, carrier=carrier, site=site)

    def resolve_taught_location(self, *, labware: str, carrier: str, site: str | int) -> Any:
        """Resolve a teach point the way VENUS is expected to: labware at
        carrier/site first, then the carrier/site offset.
        """
        return self.call("resolve_taught_location", labware=labware, carrier=carrier, site=site)

    # ---- Teaching ----

    def teach_well(self, *, labware_name: str, well: str | None = None, well_width: Any = None, step_distance: float = 0.6, safe_clearance: float = 5.0, search_depth: float = 3.0, bottom_search_margin: float = 5.0, z_offset: float = 0.0, teach_z_only: bool = False, move_to_well: bool = True, traverse_z: float = 245.0, register: bool = False, carrier: str | None = None, site: str | int | None = None) -> Any:
        """Teach one well of a plate: find its four walls and its bottom with the teaching needle.

        Pick up a teaching needle first (:meth:`teaching_pickup_needle`). Steps:

        1. Move over the definition's well center at its entrance height
           (``move_to_well=False`` starts wherever the needle is instead; it must be
           inside the well at the entrance height).
        2. Find the +X, -X, +Y and -Y walls; the center of each axis is the mean of its
           two walls, the measured entrance height the mean of the four wall-top stalls.
        3. Search down from the measured entrance for the well bottom.
        4. Lift to ``traverse_z`` and compare with the definition.

        Args:
            labware_name: Labware ID of the plate.
            well: Well to teach (e.g. ``"A1"``); default the labware's first position.
            well_width: Well opening in mm, one value or ``(x, y)``; also the farthest a
                wall search travels. Default: from the labware definition.
            step_distance: Wall search step, 0.3-2.4 mm.
            safe_clearance: Travel height above the entrance between probes, mm.
            search_depth: How far into the well each wall probe goes, mm (2-3 mm).
            bottom_search_margin: How far below the expected bottom the Z search may go, mm.
            z_offset: Added to the measured bottom (needle/stall correction), mm.
            teach_z_only: Skip the wall searches and only find the bottom at the start X/Y.
            move_to_well: Move over the expected well first.
            traverse_z: Height for the moves to and away from the well (105-245 mm).
            register: Save the taught labware position to TaughtLocations.json
                (:meth:`register_taught_position`); needs ``carrier`` and ``site``.
            carrier, site: Where the plate sits, for ``register``.

        Raises:
            TeachingError: A wall or the bottom was not found, or the needle stalled
                early. The needle is lifted to ``traverse_z`` first.

        well_width: real type is 'float | tuple | None' -- not representable as a plain type hint here; see describe_sdk_command("teach_well") for its full schema.
        """
        return self.call("teach_well", labware_name=labware_name, well=well, well_width=well_width, step_distance=step_distance, safe_clearance=safe_clearance, search_depth=search_depth, bottom_search_margin=bottom_search_margin, z_offset=z_offset, teach_z_only=teach_z_only, move_to_well=move_to_well, traverse_z=traverse_z, register=register, carrier=carrier, site=site)

    def teaching_eject_needle(self) -> Any:
        """Return the teaching needle to its pickup position."""
        return self.call("teaching_eject_needle")

    def teaching_get_channel(self) -> Any:
        """Return the 1 mL channel used for teaching (``.return_parameters.channel``)."""
        return self.call("teaching_get_channel")

    def teaching_get_labware_dimensions(self, *, labware_name: str, well: str | None = None) -> Any:
        """Return a labware's center, bottom and height, and a well's center, bottom and depth.

        Without ``well`` the labware's first position is reported in ``.well``.
        """
        return self.call("teaching_get_labware_dimensions", labware_name=labware_name, well=well)

    def teaching_is_needle_picked_up(self) -> Any:
        """Return whether the teaching channel holds a teaching needle (``.return_parameters.is_needle_picked_up``)."""
        return self.call("teaching_is_needle_picked_up")

    def teaching_measure_wall(self, *, direction: Literal[1, 2, 3, 4], safe_height: float, min_search_z: float, well_width: float, step_distance: float | None = None) -> Any:
        """Step toward one wall, probing Z at each step, until the needle stalls on the wall top.

        Start with the needle inside the well at its entrance height. ``safe_height`` is
        above the labware, ``min_search_z`` 2-3 mm inside the well, ``well_width`` the
        maximum travel and ``step_distance`` (0.3-2.4 mm, default 0.6) the probe step.
        ``.return_parameters.measured.wall_coordinate`` is the last X or Y where the needle
        still dropped into the well. Needs a teaching needle.
        """
        return self.call("teaching_measure_wall", direction=direction, safe_height=safe_height, min_search_z=min_search_z, well_width=well_width, step_distance=step_distance)

    def teaching_measure_z(self, *, z_start: float, z_min: float, z_end: float = -1.0, slow: bool = False) -> Any:
        """Search down from ``z_start`` to ``z_min`` until the needle stalls.

        ``.return_parameters.measured_z`` is the stall height and ``.status`` the result
        (``NOT_FOUND`` / ``FOUND`` / ``FOUND_EARLY``). With ``z_end`` -1 the needle returns
        to its start height after a find. Needs a teaching needle.
        """
        return self.call("teaching_measure_z", z_start=z_start, z_min=z_min, z_end=z_end, slow=slow)

    def teaching_move_channel(self, *, x: float | None = None, y: float | None = None, z: float | None = None, z_traverse: float | None = None) -> Any:
        """Move the teaching channel to a needle-tip position and return where it ended up.

        Omitted axes keep their current value; ``z_traverse`` (105-245 mm) defaults to the
        current Z. With no arguments nothing moves and the current position is returned.
        Needs a teaching needle.
        """
        return self.call("teaching_move_channel", x=x, y=y, z=z, z_traverse=z_traverse)

    def teaching_pickup_needle(self) -> Any:
        """Pick up a teaching needle with the teaching channel.

        Needs a teaching-needle rack on the deck. Returns the channel that holds the needle.
        """
        return self.call("teaching_pickup_needle")

    def teaching_set_channel(self, *, channel: int) -> Any:
        """Set the 1 mL channel (1-based) used for teaching. Not allowed while a needle is held.

        The channel is reset to the instrument configuration's teaching channel on every connect.
        """
        return self.call("teaching_set_channel", channel=channel)

    # ---- TiltModuleDeviceCommands ----

    def tilt_module_connect(self, *, system_id: int, com_port: int | str) -> Any:
        """Open the RS-232 port for a system (HSL ``InitializeCommunication``).

        One system (``system_id`` 1..4) is one COM port; the modules on its daisy chain
        share it. Call once per system, before :meth:`tilt_module_initialize`.

        Parameters
        ----------
        system_id:
            System identifier, 1..4.
        com_port:
            COM port number 1..255 (``3`` or ``"COM3"``).
        """
        return self.call("tilt_module_connect", system_id=system_id, com_port=com_port)

    def tilt_module_error_message(self, *, error_code: int) -> Any:
        """Text for a return code (HSL ``EvaluateErrorMessage``): firmware codes 0..7, library codes -1..-11."""
        return self.call("tilt_module_error_message", error_code=error_code)

    def tilt_module_get_status(self, *, system_id: int, module_name: str) -> Any:
        """Module state: tracked angle plus a live busy/error query (not in the HSL).

        ``angle`` is the last angle *commanded* -- the module has no position read-back.
        ``busy`` / ``error_code`` come from the firmware's ``RS`` / ``RE`` commands; if that
        query fails they are ``None`` and ``query_error`` explains why (the tracked fields are
        always returned).
        """
        return self.call("tilt_module_get_status", system_id=system_id, module_name=module_name)

    def tilt_module_initialize(self, *, system_id: int, module_name: str) -> Any:
        """Bring a module up (HSL ``InitializeTiltModuleAmbient``).

        Sends the HSL's command list ``EI,SI,RF``: reset the error state, home the drive to
        horizontal, read the firmware version. Afterwards the module is at 0 degrees.

        Parameters
        ----------
        system_id:
            System identifier, 1..4 (must already be connected).
        module_name:
            The module's two-character name on the chain (e.g. ``"TM"``).
        """
        return self.call("tilt_module_initialize", system_id=system_id, module_name=module_name)

    def tilt_module_move_to_position(self, *, system_id: int, module_name: str, angle: int) -> Any:
        """Tilt a module to *angle* degrees (HSL ``MoveToPosition``) and wait until it is idle.

        Do not pipette to or from the module while it is moving; this call returns only once
        the module has acknowledged the move (and, when it answers status queries, reports idle).
        If the move fails the tracked angle becomes unknown until the next successful move.

        Parameters
        ----------
        angle:
            Target angle in whole degrees, ``0..10`` (0 = horizontal).
        """
        return self.call("tilt_module_move_to_position", system_id=system_id, module_name=module_name, angle=angle)

    def tilt_module_terminate_communication(self, *, system_id: int) -> Any:
        """Close a system's COM port (HSL ``TerminateCommunication``).

        Every module on the system must be terminated first (``tilt_module_terminate_module``).
        """
        return self.call("tilt_module_terminate_communication", system_id=system_id)

    def tilt_module_terminate_module(self, *, system_id: int, module_name: str) -> Any:
        """Return a module to horizontal and power it off (HSL ``TerminateTiltModuleAmbient``: ``GP0,PO``).

        If the module cannot return to horizontal it is *not* powered off, and the error is raised.
        """
        return self.call("tilt_module_terminate_module", system_id=system_id, module_name=module_name)

    # ---- TipPool ----

    def tip_pool_get_available_tips(self, *, tip_pool: str) -> Any:
        """Return the number of available tips in the specified tip pool."""
        return self.call("tip_pool_get_available_tips", tip_pool=tip_pool)

    def tip_pool_get_empty_tips(self, *, tip_pool: str) -> Any:
        """Return empty tip information for the specified tip pool."""
        return self.call("tip_pool_get_empty_tips", tip_pool=tip_pool)

    def tip_pool_get_missing_racks(self, *, tip_pool: str) -> Any:
        """Return the missing rack indices for the specified tip pool."""
        return self.call("tip_pool_get_missing_racks", tip_pool=tip_pool)

    def tip_pool_get_tip_counter(self, *, tip_pool: str) -> Any:
        """Return the tip counter state for the specified tip pool."""
        return self.call("tip_pool_get_tip_counter", tip_pool=tip_pool)

    def tip_pool_get_tip_counters(self) -> Any:
        """Return all tip counter states."""
        return self.call("tip_pool_get_tip_counters")

    def tip_pool_initialize_tip_counter(self, *, tip_pool: str) -> Any:
        """Initialize the tip counter for the specified tip pool."""
        return self.call("tip_pool_initialize_tip_counter", tip_pool=tip_pool)

    def tip_pool_reset_tip_counter(self, *, tip_pool: str) -> Any:
        """Reset the tip counter for the specified tip pool."""
        return self.call("tip_pool_reset_tip_counter", tip_pool=tip_pool)

    def tip_pool_set_tip_counter(self, *, tip_pool: str, available_tips: Any) -> Any:
        """Set the tip counter state for the specified tip pool.

        Replaces the pool's whole state. Each entry names a rack (its labware id)
        and lists the positions that hold a tip; a listed rack holds exactly those
        tips, and one listed with no positions is on the deck but empty (an empty
        top NTR rack is moved to the NTR waste at the next pickup). A rack left out
        is marked missing (not on the deck) and reported by ``missing_racks``.
        ``count`` is not used.

        available_tips: real type is 'list' -- not representable as a plain type hint here; see describe_sdk_command("tip_pool_set_tip_counter") for its full schema.
        """
        return self.call("tip_pool_set_tip_counter", tip_pool=tip_pool, available_tips=available_tips)

    def tip_pool_show_tip_counter(self, *, tip_pool: str) -> Any:
        """Show the tip counter dialog for the specified tip pool.

        This blocks on user interaction with the dialog, so like every tip pool
        command it runs with the command timeout disabled.

        The dialog is drawn by VENUS on the instrument PC's own console -- it is
        **not** visible over a network connection. A caller with no console
        session on that machine
        only ever sees this call block until *someone at the instrument* closes
        the dialog, then receives whatever the return value is; it has no way to
        read or drive the dialog's contents itself. For remote/automated tip
        counter updates, use ``tip_pool_initialize_tip_counter``,
        ``tip_pool_reset_tip_counter``, ``tip_pool_set_tip_counter``, and
        ``tip_pool_get_tip_counter``/``tip_pool_get_tip_counters`` instead --
        none of those open a dialog.
        """
        return self.call("tip_pool_show_tip_counter", tip_pool=tip_pool)

    def tip_pool_show_tip_counters(self, *, tip_pools: list[str] | None = None) -> Any:
        """Show the tip counter dialog for the specified tip pools, or every tip
        pool if *tip_pools* is omitted.

        This blocks on user interaction with the dialog, so like every tip pool
        command it runs with the command timeout disabled.

        Same caveat as ``tip_pool_show_tip_counter``: the dialog is local to the
        instrument PC's own console and is invisible to a remote/network caller
        -- only the eventual return value is seen.
        Use ``tip_pool_initialize_tip_counter``/``tip_pool_reset_tip_counter``/
        ``tip_pool_set_tip_counter``/``tip_pool_get_tip_counter(s)`` for
        automated, dialog-free tip counter updates.
        """
        return self.call("tip_pool_show_tip_counters", tip_pools=tip_pools)

    # ---- Transport ----

    def core_5ml_eject_grips(self) -> Any:
        """Eject the 5 mL CO-RE grips.

        STAR only -- not available on Vantage.
        """
        return self.call("core_5ml_eject_grips")

    def core_5ml_hold_lid(self, *, labware_name: str, grip_height_from_top: float, grip_width: float | None = None, grip_open: float | None = None, tool_id: int | None = None, front_channel: int | None = None, grip_force: int | None = None, check_presence: dict[str, bool] | None = None, grip_close_speed: float | None = None, grip_z_speed: float | None = None, x_acceleration: int | None = None) -> Any:
        """Grip and hold a lid with the 5 mL transport tool.

        STAR only -- not available on Vantage.
        """
        return self.call("core_5ml_hold_lid", labware_name=labware_name, grip_height_from_top=grip_height_from_top, grip_width=grip_width, grip_open=grip_open, tool_id=tool_id, front_channel=front_channel, grip_force=grip_force, check_presence=check_presence, grip_close_speed=grip_close_speed, grip_z_speed=grip_z_speed, x_acceleration=x_acceleration)

    def core_5ml_present_and_scan(self, *, labware_name: str, carrier: str, site: str, grip_height_above_bottom: float, track: int, z_minimal_position: float, grip_width: float | None = None, grip_open: float | None = None, grip_force: int | None = None, x_acceleration: int | None = None, grip_close_speed: float | None = None, grip_z_speed: float | None = None, eject_grip: bool | None = None, check_presence: dict[str, bool] | None = None) -> Any:
        """Transport labware to a scan position and return barcode using the 5 mL gripper.

        STAR only -- not available on Vantage.
        """
        return self.call("core_5ml_present_and_scan", labware_name=labware_name, carrier=carrier, site=site, grip_height_above_bottom=grip_height_above_bottom, track=track, z_minimal_position=z_minimal_position, grip_width=grip_width, grip_open=grip_open, grip_force=grip_force, x_acceleration=x_acceleration, grip_close_speed=grip_close_speed, grip_z_speed=grip_z_speed, eject_grip=eject_grip, check_presence=check_presence)

    def core_5ml_transport(self, *, labware_name: str, carrier: str, site: str, grip_height_above_bottom: float, grip_width: float | None = None, grip_open: float | None = None, tool_id: int | None = None, front_channel: int | None = None, grip_force: int | None = None, press_distance: float | None = None, x_acceleration: int | None = None, grip_close_speed: float | None = None, grip_z_speed: float | None = None, offset_grip: float | None = None, check_presence: dict[str, bool] | None = None, eject_grip: bool | None = None) -> Any:
        """Transport a plate to a carrier site using the 5 mL CO-RE gripper.

        STAR only -- not available on Vantage.
        """
        return self.call("core_5ml_transport", labware_name=labware_name, carrier=carrier, site=site, grip_height_above_bottom=grip_height_above_bottom, grip_width=grip_width, grip_open=grip_open, tool_id=tool_id, front_channel=front_channel, grip_force=grip_force, press_distance=press_distance, x_acceleration=x_acceleration, grip_close_speed=grip_close_speed, grip_z_speed=grip_z_speed, offset_grip=offset_grip, check_presence=check_presence, eject_grip=eject_grip)

    def core_5ml_transport_is_holding_labware(self) -> Any:
        """Check whether the 5 mL CO-RE gripper is currently holding labware.

        STAR only -- not available on Vantage.
        """
        return self.call("core_5ml_transport_is_holding_labware")

    def core_5ml_transport_return_plate(self, *, mode: str = 'return', carrier: str | None = None, site: str | None = None, check_presence: dict[str, bool] | None = None, grip_z_speed: float | None = None, x_acceleration: int | None = None, press_distance: float | None = None, eject_grip: bool | None = None) -> Any:
        """Return a held plate to its original position or a new carrier site using the 5 mL gripper.

        STAR only -- not available on Vantage.
        """
        return self.call("core_5ml_transport_return_plate", mode=mode, carrier=carrier, site=site, check_presence=check_presence, grip_z_speed=grip_z_speed, x_acceleration=x_acceleration, press_distance=press_distance, eject_grip=eject_grip)

    def core_5ml_transport_to_waste(self, *, labware_name: str, grip_height_above_bottom: float, grip_width: float | None = None, grip_open: float | None = None, tool_id: int | None = None, front_channel: int | None = None, grip_force: int | None = None, x_acceleration: int | None = None, grip_close_speed: float | None = None, grip_z_speed: float | None = None, offset_grip: float | None = None, check_presence: dict[str, bool] | None = None, eject_grip: bool | None = None) -> Any:
        """Transport a plate to the waste position using the 5 mL gripper.

        STAR only -- not available on Vantage.
        """
        return self.call("core_5ml_transport_to_waste", labware_name=labware_name, grip_height_above_bottom=grip_height_above_bottom, grip_width=grip_width, grip_open=grip_open, tool_id=tool_id, front_channel=front_channel, grip_force=grip_force, x_acceleration=x_acceleration, grip_close_speed=grip_close_speed, grip_z_speed=grip_z_speed, offset_grip=offset_grip, check_presence=check_presence, eject_grip=eject_grip)

    def core_5ml_transport_tracking_clear(self) -> Any:
        """Clear the 5 mL transport tracking state.

        STAR only -- not available on Vantage.
        """
        return self.call("core_5ml_transport_tracking_clear")

    def core_eject_grips(self) -> Any:
        """Eject the CO-RE grips."""
        return self.call("core_eject_grips")

    def core_hold_lid(self, *, labware_name: str, grip_height_from_top: float, grip_width: float | None = None, grip_open: float | None = None, tool_id: int | None = None, front_channel: int | None = None, grip_force: int | None = None, check_presence: dict[str, bool] | None = None, grip_close_speed: float | None = None, grip_z_speed: float | None = None, x_acceleration: int | None = None) -> Any:
        """Grip and hold a lid with the 1 mL transport tool."""
        return self.call("core_hold_lid", labware_name=labware_name, grip_height_from_top=grip_height_from_top, grip_width=grip_width, grip_open=grip_open, tool_id=tool_id, front_channel=front_channel, grip_force=grip_force, check_presence=check_presence, grip_close_speed=grip_close_speed, grip_z_speed=grip_z_speed, x_acceleration=x_acceleration)

    def core_present_and_scan(self, *, labware_name: str, carrier: str, site: str, grip_height_above_bottom: float, track: int, z_minimal_position: float, grip_width: float | None = None, grip_open: float | None = None, grip_force: int | None = None, x_acceleration: int | None = None, grip_close_speed: float | None = None, grip_z_speed: float | None = None, eject_grip: bool | None = None, check_presence: dict[str, bool] | None = None) -> Any:
        """Transport labware to a scan position and return barcode (STAR only).

        STAR only -- not available on Vantage.
        """
        return self.call("core_present_and_scan", labware_name=labware_name, carrier=carrier, site=site, grip_height_above_bottom=grip_height_above_bottom, track=track, z_minimal_position=z_minimal_position, grip_width=grip_width, grip_open=grip_open, grip_force=grip_force, x_acceleration=x_acceleration, grip_close_speed=grip_close_speed, grip_z_speed=grip_z_speed, eject_grip=eject_grip, check_presence=check_presence)

    def core_transport(self, *, labware_name: str, carrier: str, site: str, grip_height_above_bottom: float, grip_width: float | None = None, grip_open: float | None = None, tool_id: int | None = None, front_channel: int | None = None, grip_force: int | None = None, press_distance: float | None = None, x_acceleration: int | None = None, grip_close_speed: float | None = None, grip_z_speed: float | None = None, offset_grip: float | None = None, check_presence: dict[str, bool] | None = None, eject_grip: bool | None = None) -> Any:
        """Transport a plate to a carrier site using the CO-RE gripper."""
        return self.call("core_transport", labware_name=labware_name, carrier=carrier, site=site, grip_height_above_bottom=grip_height_above_bottom, grip_width=grip_width, grip_open=grip_open, tool_id=tool_id, front_channel=front_channel, grip_force=grip_force, press_distance=press_distance, x_acceleration=x_acceleration, grip_close_speed=grip_close_speed, grip_z_speed=grip_z_speed, offset_grip=offset_grip, check_presence=check_presence, eject_grip=eject_grip)

    def core_transport_is_holding_labware(self) -> Any:
        """Check whether the CO-RE gripper is currently holding labware."""
        return self.call("core_transport_is_holding_labware")

    def core_transport_return_plate(self, *, mode: str = 'return', carrier: str | None = None, site: str | None = None, check_presence: dict[str, bool] | None = None, grip_z_speed: float | None = None, x_acceleration: int | None = None, press_distance: float | None = None, eject_grip: bool | None = None) -> Any:
        """Return a held plate to its original position or a new carrier site."""
        return self.call("core_transport_return_plate", mode=mode, carrier=carrier, site=site, check_presence=check_presence, grip_z_speed=grip_z_speed, x_acceleration=x_acceleration, press_distance=press_distance, eject_grip=eject_grip)

    def core_transport_to_waste(self, *, labware_name: str, grip_height_above_bottom: float, grip_width: float | None = None, grip_open: float | None = None, tool_id: int | None = None, front_channel: int | None = None, grip_force: int | None = None, x_acceleration: int | None = None, grip_close_speed: float | None = None, grip_z_speed: float | None = None, offset_grip: float | None = None, check_presence: dict[str, bool] | None = None, eject_grip: bool | None = None) -> Any:
        """Transport a plate to the waste position."""
        return self.call("core_transport_to_waste", labware_name=labware_name, grip_height_above_bottom=grip_height_above_bottom, grip_width=grip_width, grip_open=grip_open, tool_id=tool_id, front_channel=front_channel, grip_force=grip_force, x_acceleration=x_acceleration, grip_close_speed=grip_close_speed, grip_z_speed=grip_z_speed, offset_grip=offset_grip, check_presence=check_presence, eject_grip=eject_grip)

    def core_transport_tracking_clear(self) -> Any:
        """Clear the transport tracking state."""
        return self.call("core_transport_tracking_clear")

    def iswap_get_labware(self, *, labware_name: str, grip_height_above_bottom: float, grip_width: float | None = None, grip_open: float | None = None, grip_force: int | None = None, tolerance: float | None = None, grip_inverse: Literal[True, False] | None = None, offset_grip: float | None = None) -> Any:
        """Pick up labware without placing it using iSWAP.

        A plain get from a carrier site. A *grip_width* of 100 mm or more is a
        wide grip, with the iSWAP facing the back of the instrument (the front
        with ``GRIP_FROM_LEFT``); below that, a narrow grip facing left (right
        with ``GRIP_FROM_LEFT``), for labware at rotation 0. To get from a hotel
        with complex movement, use
        :meth:`iswap_get_labware_complex_movement`.

        With *grip_width* set, the client remembers the grip, so a following
        :meth:`iswap_put_labware_complex_movement` can work out its place rotation.
        """
        return self.call("iswap_get_labware", labware_name=labware_name, grip_height_above_bottom=grip_height_above_bottom, grip_width=grip_width, grip_open=grip_open, grip_force=grip_force, tolerance=tolerance, grip_inverse=grip_inverse, offset_grip=offset_grip)

    def iswap_get_labware_complex_movement(self, *, labware_name: str, grip_height_above_bottom: float, retract_distance: float, lift_height: float, orientation: Literal[1, 2, 3, 4], grip_width: float | None = None, grip_open: float | None = None, grip_force: int | None = None, tolerance: float | None = None, offset_grip: float | None = None) -> Any:
        """Pick up labware from a hotel with iSWAP complex movement.

        The iSWAP faces *orientation* (front, right, rear or left), toward the
        hotel, reaches *retract_distance* mm into it, and lifts the labware
        *lift_height* mm before retracting. *grip_width* still picks a narrow or
        wide grip (100 mm or more); ``grip_inverse`` has no effect here. Sends the same
        ``transport.iswap.getLabware`` command as :meth:`iswap_get_labware`,
        with a ``complexMovement`` object.
        """
        return self.call("iswap_get_labware_complex_movement", labware_name=labware_name, grip_height_above_bottom=grip_height_above_bottom, retract_distance=retract_distance, lift_height=lift_height, orientation=orientation, grip_width=grip_width, grip_open=grip_open, grip_force=grip_force, tolerance=tolerance, offset_grip=offset_grip)

    def iswap_is_holding_labware(self) -> Any:
        """Return iSWAP held-labware status payload."""
        return self.call("iswap_is_holding_labware")

    def iswap_park(self) -> Any:
        """Park the iSWAP transport tool."""
        return self.call("iswap_park")

    def iswap_present_and_scan(self, *, labware_name: str, carrier: str, site: str, track: int, grip_height_above_bottom: float, z_minimal_position: float, grip_width: float | None = None, grip_open: float | None = None, grip_force: int | None = None, tolerance: float | None = None, grip_inverse: Literal[True, False] | None = None, place_rotation: Literal[1, 2, 3, 4] | None = None) -> Any:
        """Present labware for barcode scan using iSWAP (STAR only).

        STAR only -- not available on Vantage.
        """
        return self.call("iswap_present_and_scan", labware_name=labware_name, carrier=carrier, site=site, track=track, grip_height_above_bottom=grip_height_above_bottom, z_minimal_position=z_minimal_position, grip_width=grip_width, grip_open=grip_open, grip_force=grip_force, tolerance=tolerance, grip_inverse=grip_inverse, place_rotation=place_rotation)

    def iswap_put_labware(self, *, carrier: str, site: str, place_rotation: Literal[1, 2, 3, 4] | None = None) -> Any:
        """Place currently-held labware at a carrier site using iSWAP.

        A plain put to a carrier site. To put into a hotel with complex
        movement, use :meth:`iswap_put_labware_complex_movement`.
        """
        return self.call("iswap_put_labware", carrier=carrier, site=site, place_rotation=place_rotation)

    def iswap_put_labware_complex_movement(self, *, carrier: str, site: str, retract_distance: float, lift_height: float, orientation: Literal[1, 2, 3, 4], place_rotation: Literal[1, 2, 3, 4] | None = None) -> Any:
        """Place currently-held labware into a hotel with iSWAP complex movement.

        The iSWAP faces *orientation* (front, right, rear or left), toward the
        hotel, reaches *retract_distance* mm into it at *lift_height* mm above
        the site, then lowers the labware. Sends the same
        ``transport.iswap.putLabware`` command as :meth:`iswap_put_labware`,
        with a ``complexMovement`` object.

        The held labware turns with the iSWAP, so when *orientation* differs
        from the way the iSWAP faced when it gripped (see
        :meth:`iswap_get_labware`, or the complex get's orientation),
        VENUS needs the matching place rotation: 180° for the opposite side,
        90° or 270° for a quarter turn. Left as ``None``, *place_rotation* is
        worked out from the last get by this client, when that get set
        *grip_width* or used complex movement; otherwise it is not sent.
        """
        return self.call("iswap_put_labware_complex_movement", carrier=carrier, site=site, retract_distance=retract_distance, lift_height=lift_height, orientation=orientation, place_rotation=place_rotation)

    def iswap_tracking_clear(self) -> Any:
        """Clear iSWAP transport tracking state."""
        return self.call("iswap_tracking_clear")

    def iswap_transport(self, *, labware_name: str, carrier: str, site: str, grip_height_above_bottom: float, grip_width: float | None = None, grip_open: float | None = None, grip_force: int | None = None, tolerance: float | None = None, grip_inverse: Literal[True, False] | None = None, place_rotation: Literal[1, 2, 3, 4] | None = None, offset_grip: float | None = None) -> Any:
        """Move labware using the iSWAP transport tool.

        A *grip_width* of 100 mm or more is a wide grip, with the iSWAP facing
        the back of the instrument (the front with ``GRIP_FROM_LEFT``); below
        that, a narrow grip facing left (right with ``GRIP_FROM_LEFT``), for
        labware at rotation 0.
        """
        return self.call("iswap_transport", labware_name=labware_name, carrier=carrier, site=site, grip_height_above_bottom=grip_height_above_bottom, grip_width=grip_width, grip_open=grip_open, grip_force=grip_force, tolerance=tolerance, grip_inverse=grip_inverse, place_rotation=place_rotation, offset_grip=offset_grip)

    def iswap_transport_to_waste(self, *, labware_name: str, grip_height_above_bottom: float, grip_width: float | None = None, grip_open: float | None = None, grip_force: int | None = None, tolerance: float | None = None, grip_inverse: Literal[True, False] | None = None, offset_grip: float | None = None) -> Any:
        """Move labware to waste using the iSWAP transport tool."""
        return self.call("iswap_transport_to_waste", labware_name=labware_name, grip_height_above_bottom=grip_height_above_bottom, grip_width=grip_width, grip_open=grip_open, grip_force=grip_force, tolerance=tolerance, grip_inverse=grip_inverse, offset_grip=offset_grip)
