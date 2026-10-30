# Star Commands Reference

All commands are available as methods on `StarClient`. They are organized into category mixins that are composed into the client automatically.

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES

with StarClient() as star:
    star.instrument_is_connected()
```

Enums used as defaults below come from two places: `WellOrder` and `OVERRIDE_SAFETY_CHECKS` are imported from `hamilton_venus`; the rest (`EjectMode`, `CapacitiveLLD`, `PressureLLD`, `CoordinateMode`, `CoreGripType`, `QCGType`, `GripInverse`, `PlaceRotation`, `CMOrientation`, `SplitChannelType`, `SplitWellFit`, `TiltPivotPoint`, `TiltWellPosition`, ...) are imported from `hamilton_venus.models`. A `...` in a signature means more optional parameters follow; see the linked guide or the method's docstring.

> For Hamilton Vantage instruments, see [Vantage Commands Reference](vantage_commands.md). Most commands are shared. STAR-only: 5 mL CO-RE gripper transport (`core_5ml_*`) and present-and-scan (`core_present_and_scan`, `iswap_present_and_scan`).

---

## Startup Behavior

`StarClient` defaults `auto_connect=True`. After calling `start()` (a `with StarClient() as star:` block calls it for you), the client waits for readiness and automatically connects (but does **not** initialize). You must call `instrument_init()` before running hardware commands. See [Getting Started Guide](examples/getting_started.md) for detailed startup patterns and manual control options.

---

## ⚠️ SAFETY_BYPASS_TOKEN CRITICAL WARNING

Several commands in this reference accept an optional `safety_bypass_token` parameter. 

> **⚠️ DANGER:** Passing `safety_bypass_token=OVERRIDE_SAFETY_CHECKS` **waives instrument safety checks** and risks hardware collisions that can **damage the instrument or cause injury**. 
>
> **Using this token waives vendor liability for any hardware damage or injuries resulting from collisions or misuse of this command.**
>
> Only use it when you fully understand the firmware command being issued.

Commands that accept this parameter: `firmware_command` (required), `move_axis`, `move_axis_relative`, `move_axis_5ml`, `mph96_move_axis`, `pip_arm_move`.

---

## Instrument Commands

Core instrument lifecycle and status queries.

| Method | Description |
|--------|-------------|
| `instrument_is_connected()` | Check if the instrument runtime is connected and responding. Returns `bool`. |
| `instrument_is_idle()` | Check if the instrument is idle. Returns `bool`. |
| `instrument_init(force_init=False)` | Manually initialize the instrument, or re-initialize it with `force_init=True`. Returns `StatusInitResponse`. |
| `instrument_connect(initialize=True)` | Connect the instrument runtime, optionally initializing it. Returns `StatusConnectResponse`. |
| `instrument_get_configuration()` | Return the hardware configuration reported by the instrument. Returns `ConfigurationResponse`. |
| `instrument_disable_cleanup()` | Disable end-of-run cleanup behavior. |
| `instrument_get_serial_number()` | Return the instrument serial number. Returns `ConfigurationSerialNumberResponse`. |
| `instrument_get_daily_maintenance_data()` | Return daily maintenance status and expiration metadata. Returns `MaintenanceDataResponse`. |
| `instrument_get_weekly_maintenance_data()` | Return weekly maintenance status and expiration metadata. Returns `MaintenanceDataResponse`. |
| `instrument_get_verification_data()` | Return verification status and expiration metadata. Returns `MaintenanceDataResponse`. |
| `instrument_get_deck_tracks()` | Return deck track counts. Returns `DeckTracksResponse`. |
| `instrument_get_deck_dimensions()` | Return deck dimension metadata in instrument coordinates. Returns `DeckDimensionsResponse`. |
| `instrument_get_waste_locations()` | Return waste-location metadata configured on the deck. Returns `WasteLocationsResponse`. |

---

## Front Cover Commands

Control the instrument front cover lock.

| Method | Description |
|--------|-------------|
| `front_cover_is_closed()` | Check if the front cover is closed. Returns `FrontCoverIsClosedResponse`. |
| `front_cover_lock()` | Lock the front cover. |
| `front_cover_unlock()` | Unlock the front cover. |

`front_cover_is_locked()` is Vantage only; on a STAR it raises `VenusCommandUnsupportedError` because the STAR hardware cannot report the lock state.

---

## Firmware Commands

Advanced, low-level access for sending raw firmware instructions directly to the
instrument. Prefer the typed command helpers whenever one exists.

| Method | Description |
|--------|-------------|
| `firmware_debug_mode(enable)` | Enable (`True`) or disable (`False`) firmware debug mode on the instrument. Returns `CommandResponse`. |
| `firmware_command(command, parameters="", *, safety_bypass_token)` | Send a raw firmware command (e.g. `command="C0AS"`) to the instrument. `command` is the whole upper-case module and command code (4 characters on a STAR, 6 to 8 on a Vantage); `parameters` are sent lower case. Unlike the other movement commands, VENUS requires this token for every firmware command. **Requires** `safety_bypass_token=OVERRIDE_SAFETY_CHECKS`. ⚠️ **Using this token waives vendor liability for hardware damage/injury.** Returns `FirmwareCommandResponse`. |

> **⚠️ Warning:** Passing `safety_bypass_token=OVERRIDE_SAFETY_CHECKS` waives instrument safety checks and risks hardware collisions that can damage the instrument or cause injury. **Using this token waives vendor liability for any hardware damage or injuries resulting from collisions or misuse of this command.** Only use it when you fully understand the firmware command being issued.
>
> `safety_bypass_token` is not an arbitrary flag — VENUS only accepts the exact literal `"OVERRIDE_SAFETY_CHECKS"`; any other string is rejected. Import the constant instead of retyping the literal: `from hamilton_venus import OVERRIDE_SAFETY_CHECKS`.

---

## Validation Against the Instrument Configuration

When the client connects (`start()` with `auto_connect=True`, or a later `instrument_connect()`), it reads `instrument_get_configuration()` once and uses it to reject commands the hardware cannot run. The check happens in the SDK, before anything is sent to VENUS. See [Instrument Configuration Guide](examples/advanced/instrument_configuration.md#connect-time-validation-from-the-instrument-configuration) for details and examples.

| Check | Rule | Raises |
|-------|------|--------|
| Channel count | `len(channels)` must not exceed the channel total reported for the module (1 mL, 5 mL or MagPip). If both arms have the module, the larger arm's total is used, since a command runs on a single arm. | `ValueError` |
| Channel numbers | Every entry of `channels` must be between 1 and the module's channel total. | `ValueError` |
| MPH96 commands | Some arm must report an MPH96 head. | `VenusCommandUnsupportedError` |
| Autoload commands | The configuration must report `Autoload`. | `VenusCommandUnsupportedError` |
| iSWAP / IPG commands | Some arm must report a gripper. | `VenusCommandUnsupportedError` |
| CO-RE `front_channel` | Must be between the gripper's channel span and the module's channel total. The span is 4 for the QCG (Vantage, or Fluid Motion channels) and 2 for the standard CO-RE gripper. | `ValueError` |
| `add_qcg()` / `add_1ml_core_grip()` (STAR only) | Fluid Motion channels take the QCG; Legacy channels take the CO-RE gripper. The two channel types cannot be mixed. | `VenusCommandUnsupportedError` |

If the configuration could not be read (or the client has not connected yet), channel checks fall back to the SDK ceiling of 16 channels and no command is rejected for missing hardware.

---

## Channel Commands (1 mL Pipetting)

Tip handling, aspiration, dispensing, and liquid detection using the independent 1 mL channels. All commands default to using all 8 channels (1–8) if `channels` is not specified. Systems can be configured with up to 16 channels; the accepted channel count and channel numbers come from the instrument configuration (see [Validation Against the Instrument Configuration](#validation-against-the-instrument-configuration)). See [Liquid Handling Guide](examples/liquid_handling.md) for detailed examples and settings reference.

| Method | Description |
|--------|-------------|
| `tip_pickup(channels=None, positions=None, well_order=WellOrder.COL_ASC, tip_pool=None, optimized_pickup=True)` | Pick up 1 mL tips from positions or managed pool. |
| `tip_eject(channels=None, eject_mode=EjectMode.WASTE, positions=None, well_order=WellOrder.COL_ASC, tip_pool=None)` | Eject 1 mL tips to waste, positions, or managed pool. |
| `aspirate(positions, *, channels=None, volumes, liquid_class, settings=None, well_order=WellOrder.COL_ASC, mad_enabled=None, mad_threshold=None, adc=None)` | Aspirate liquid with 1 mL channels. `mad_enabled` turns on Monitored Air Displacement; `adc` is Anti-Droplet Control. Returns `ChannelAspirationResponse`. See [Liquid Handling Guide](examples/liquid_handling.md#aspirate-settings-reference) for settings options. |
| `dispense(positions, *, channels=None, volumes, settings=None, well_order=WellOrder.COL_ASC, adc=None)` | Dispense liquid with 1 mL channels (uses the liquid class the tip aspirated with). Returns `ChannelDispenseResponse`. See [Liquid Handling Guide](examples/liquid_handling.md#dispense-settings-reference) for settings options. |
| `dispense_on_the_fly(channels, labware_name, volumes, labware_surface_distance, start_x_offset=0.0, x_speed=0.0, x_acceleration_distance=8.0, dispense_direction=0, excluded_positions=None)` | Dispense across wells while translating in X on a single pass. |
| `move_axis(channels, *, x=None, y=None, z=None, safety_bypass_token=None)` | Move 1 mL channels directly to absolute X/Y/Z coordinates. `x` is a single value (shared gantry axis); `y`/`z` are a single value or one per channel. `safety_bypass_token` is optional — VENUS runs its normal safety checks when omitted; pass `safety_bypass_token=OVERRIDE_SAFETY_CHECKS` (imported from `hamilton_venus`) to bypass them. ⚠️ **Using this token waives vendor liability for hardware damage/injury.** Returns `ChannelMoveAxisResponse`. |
| `get_status()` | Return the current X/Y/Z position and tip-loaded status for every 1 mL channel. Returns `ChannelGetStatusResponse`. |
| `move_axis_relative(channels, *, x=None, y=None, z=None, safety_bypass_token=None)` | Move 1 mL channels by a relative X/Y/Z offset. VENUS's `moveAxis` is absolute-only, so this calls `get_status()` first and adds the offset to each channel's current position. `safety_bypass_token` is optional, same as `move_axis()`. ⚠️ **Using this token waives vendor liability for hardware damage/injury.** Returns `ChannelMoveAxisResponse`. |
| `detect_liquid_level(positions, *, channels=None, capacitive_lld=CapacitiveLLD.MAX, pressure_lld=PressureLLD.OFF, well_order=WellOrder.COL_ASC)` | Detect liquid level with 1 mL channels. |
| `tip_check()` | Return current tip status for active 1 mL channels. Returns `ChannelTipCheckResponse`. |

> **Split wells:** after [`split_wells()`](examples/deck_and_layout.md#split-wells) (`SplitChannelType.ONE_ML`), `aspirate`, `dispense` and `detect_liquid_level` send two or more channels that target the same split well to its slots: channel `c` goes to slot `c - first channel + 1`. A single channel still goes to the well centre. More channels than slots raise `SplitWellCapacityError` before anything is sent.

## Channel Commands (5 mL Pipetting)

Tip handling, aspiration, dispensing, and liquid detection using the 5 mL channels. The 5 mL API mirrors the 1 mL API exactly — same parameters, same return types — but is dispatched to the `channels.5mL` action namespace. Available on both STAR and Vantage. See [Liquid Handling Guide → 5mL Channels](examples/liquid_handling.md#5ml-xl-channels) for examples.

| Method | Description |
|--------|-------------|
| `tip_pickup_5ml(channels=None, positions=None, well_order=WellOrder.COL_ASC, tip_pool=None, optimized_pickup=True)` | Pick up 5 mL tips from positions or managed pool. |
| `tip_eject_5ml(channels=None, eject_mode=EjectMode.WASTE, positions=None, well_order=WellOrder.COL_ASC, tip_pool=None)` | Eject 5 mL tips to waste, positions, or managed pool. |
| `aspirate_5ml(positions, *, channels=None, volumes, liquid_class, settings=None, well_order=WellOrder.COL_ASC, mad_enabled=None, mad_threshold=None, adc=None)` | Aspirate liquid with 5 mL channels. |
| `dispense_5ml(positions, *, channels=None, volumes, settings=None, well_order=WellOrder.COL_ASC, adc=None)` | Dispense liquid with 5 mL channels (uses the liquid class the tip aspirated with). |
| `dispense_on_the_fly_5ml(channels, labware_name, volumes, labware_surface_distance, start_x_offset=0.0, x_speed=0.0, x_acceleration_distance=8.0, dispense_direction=0, excluded_positions=None)` | Dispense across wells while translating in X with 5 mL channels. |
| `move_axis_5ml(channels, *, x=None, y=None, z=None, safety_bypass_token=None)` | Move 5 mL channels directly to absolute X/Y/Z coordinates. `x` is a single value (shared gantry axis); `y`/`z` are a single value or one per channel. `safety_bypass_token` is optional — VENUS runs its normal safety checks when omitted; pass `safety_bypass_token=OVERRIDE_SAFETY_CHECKS` (imported from `hamilton_venus`) to bypass them. ⚠️ **Using this token waives vendor liability for hardware damage/injury.** Returns `ChannelMoveAxisResponse`. |
| `get_status_5ml()` | Return the current X/Y/Z position and tip-loaded status for every 5 mL channel. Returns `ChannelGetStatusResponse`. |
| `detect_liquid_level_5ml(positions, *, channels=None, capacitive_lld=CapacitiveLLD.MAX, pressure_lld=PressureLLD.OFF, well_order=WellOrder.COL_ASC)` | Detect liquid level with 5 mL channels. |
| `tip_check_5ml()` | Return current tip status for active 5 mL channels. Returns `ChannelTipCheckResponse`. |

> **Split wells:** the same routing applies to `aspirate_5ml`, `dispense_5ml` and `detect_liquid_level_5ml` on wells split with `SplitChannelType.FIVE_ML` (18 mm slot pitch). A 1 mL split is never used by 5 mL channels, and a 5 mL split is never used by 1 mL channels.

---

## MPH96 Commands (96-Channel Head)

Full-plate operations using the 96-channel multi-probe head. See [96-Channel Guide](examples/mph96.md) for detailed examples and settings reference.

| Method | Description |
|--------|-------------|
| `tip_pick_up_mph96(labware_id=None, tip_pool=None, pre_air_aspirate=MPH96PreAirAspirate.DISABLED, pre_air_volume=None)` | Pick up a full set of 96 tips. |
| `tip_pick_up_mph96_partial(mode, count, labware_id=None, tip_pool=None, mph_pickup_side=MphPickupSide.LEFT, ...)` | Pick up a partial subset of tips (by row/column count). |
| `tip_eject_mph96(labware_id=None, mph_pattern=None, mph_selection=None, eject_mode=EjectMode.WASTE)` | Eject MPH96 tips. |
| `aspirate_mph96(labware_id, *, mph_pattern=None, volume, liquid_class, settings=None)` | Aspirate with the 96-channel head. See [96-Channel Guide](examples/mph96.md#mph96aspiratesettings-fields) for settings options. |
| `dispense_mph96(labware_id, *, mph_pattern=None, volume, settings=None)` | Dispense with the 96-channel head (uses the liquid class the head aspirated with). See [96-Channel Guide](examples/mph96.md#mph96dispensesettings-fields) for settings options. |
| `mph96_park_back()` | Park the MPH96 head at its rear position. |
| `mph96_park_front()` | Park the MPH96 head at its front position. |
| `mph96_move_axis(axis, value, mode=CoordinateMode.ABSOLUTE, *, safety_bypass_token=None)` | Move the MPH96 head along the selected axis. `safety_bypass_token` is optional — VENUS runs its normal safety checks when omitted; pass `safety_bypass_token=OVERRIDE_SAFETY_CHECKS` (imported from `hamilton_venus`) to bypass them. ⚠️ **Using this token waives vendor liability for hardware damage/injury.** |
| `mph96_detect_liquid_level(labware_id, mph_pattern=None, capacitive_lld=CapacitiveLLD.MAX)` | Detect liquid level with the 96-channel head. |
| `get_status_mph96()` | Return the MPH96 head's current X/Y/Z position and tip-loaded status. Returns `MPH96GetStatusResponse`. |
| `mph96_clear_tip_support(tip_pool)` | Clear a tip support and return remaining tip metadata. Returns `MPH96ClearTipSupportResponse`. |

---

## Pipetting Arm Commands

Control the physical position of pipetting arms on the deck.

| Method | Description |
|--------|-------------|
| `pip_arm_get_x_position(arm_id=1)` | Return the current X-axis position of the arm. |
| `pip_arm_park_left(arm_id=1)` | Park the arm at the left side of the deck. |
| `pip_arm_park_right(arm_id=1)` | Park the arm at the right side of the deck. |
| `pip_arm_move(value, coordinate_mode=None, arm_id=1, speed=None, *, safety_bypass_token=None)` | Move a pipetting arm using absolute or relative coordinates. `safety_bypass_token` is optional — VENUS runs its normal safety checks when omitted; pass `safety_bypass_token=OVERRIDE_SAFETY_CHECKS` (imported from `hamilton_venus`) to bypass them. ⚠️ **Using this token waives vendor liability for hardware damage/injury.** |

---

## Autoload Commands

Carrier loading and unloading via the autoload mechanism.

| Method | Description |
|--------|-------------|
| `autoload_move(track_id)` | Move the autoload shuttle to the specified deck track. |
| `autoload_park_left()` | Park the autoload shuttle at its left-most position. |
| `autoload_park_right()` | Park the autoload shuttle at its right-most position. |
| `autoload_load_carrier_by_id(carrier_id, scan_positions=None)` | Load a carrier by its identifier. |
| `autoload_load_carrier_by_track(track_id, scan_positions=None)` | Load a carrier from a specific track. |
| `autoload_unload_carrier_by_id(carrier_id)` | Unload a carrier by its identifier. |
| `autoload_unload_carrier_by_track(track_id)` | Unload a carrier from a specific track. |
| `autoload_is_track_occupied(track_id)` | Check if an autoload track holds a carrier. Returns `TrackOccupiedResponse`. |
| `autoload_get_carrier_sensor_status()` | Return carrier sensor availability and occupancy for every track. Returns `CarrierSensorStatusResponse`. |

> **Carrier already pushed in:** the STAR load step does not take back a carrier that is already pushed in. Check `autoload_get_carrier_sensor_status()` and unload the carrier before loading it -- see [Loading a Carrier That Is Already Pushed In](examples/autoload.md#loading-a-carrier-that-is-already-pushed-in-star-vs-vantage).

---

## Layout Commands

Build and modify the active deck layout at runtime. See [Deck and Layout Guide](examples/deck_and_layout.md) for detailed examples.

### Labware Placement

| Method | Description |
|--------|-------------|
| `add_carrier(labware_definition, left_track, labware_id=None)` | Add a carrier to the deck layout. |
| `add_carrier_to_site(labware_definition, carrier_id, site, labware_id=None)` | Add a carrier to a site on an existing carrier. |
| `add_tube_carrier(labware_definition, left_track, labware_id=None)` | Add a sample tube carrier to the deck layout. |
| `add_tubes_to_carrier(labware_name, positions)` | Add tubes to a sample tube carrier and return each tube's absolute coordinates. Returns `LayoutAddTubesToCarrierResponse`. |
| `add_tip_rack(labware_definition, carrier_id, site, tip_pool=None, labware_id=None)` | Add a tip rack to a carrier site. Returns `LayoutAddTipRackResponse`. |
| `add_tip_box(labware_definition, carrier_id, site, tip_pool=None, labware_id=None)` | Add a tip box to a carrier site. Returns `LayoutAddTipBoxResponse`. |
| `add_plate(labware_definition, carrier_id, site, plate_id=None)` | Add a plate to a carrier site. |
| `add_lidded_plate(labware_definition, carrier_id, site, plate_id=None, lid_definition=LABWARE.LID.NUNC_LID)` | Add a lidded plate to a carrier site and return plate and lid names. Returns `AddLiddedPlateResponse`. See [Deck and Layout Guide](examples/deck_and_layout.md#add_lidded_plate--add-lidded-plate-with-automated-lid) for details. |
| `add_lid(labware_definition, carrier_id, site, lid_id=None)` | Add a lid to a carrier site. |
| `add_reservoir(labware_definition, carrier_id, site, labware_id=None)` | Add a reservoir to a carrier site. |
| `add_tip_support(carrier_id, site)` | Add a tip support to a carrier site. |
| `add_ntr(labware_definition, carrier_id, site, stack, tip_pool=None, labware_id=None)` | Add a nested tip rack (NTR) to the active deck layout. Returns `LayoutAddNTRResponse`. |
| `add_transport_site(site_name, x_center, y_center, z_bottom, angle_index)` | Add a transport site definition to the active deck layout. Returns `LayoutAddTransportSiteResponse`. |
| `move_carrier(labware_name, left_track, site="")` | Move a loaded carrier to a new deck track/site location. Returns `LayoutMoveCarrierResponse`. |
| `remove_labware(labware_name)` | Remove the specified labware from the active deck layout. |
| `add_1ml_core_grip(grip_type=CoreGripType.STANDARD)` | Add a 1 mL CO-RE gripper tool to the layout. Rejected when the configuration reports Fluid Motion 1 mL channels (those use the QCG). |
| `add_5ml_core_grip()` | Add a 5 mL CO-RE gripper tool to the layout. |
| `add_qcg(qcg_type=QCGType.QCG, track=None)` | Add a Quad CO-RE Gripper (QCG) to the layout. Rejected when the configuration reports Legacy 1 mL channels (those use the CO-RE gripper). `track` is Vantage only (raises `ValueError` on STAR). |
| `add_channel_liquid_waste()` | Add a channel liquid waste container to the active deck layout. |
| `add_liquid_waste(track=None)` | Add a liquid waste container to the active deck layout (Vantage only; raises `ValueError` on STAR). |
| `get_transport_tool(is_1ml=None, is_qcg=None, tool_id=None)` | Get information about a transport tool (pass only one of the three). Returns `TransportToolResponse`. |
| `get_transport_tool_ids()` | Get the current transport tools. Returns `TransportToolIdsResponse`. |
| `remove_transport_tool(tool_id)` | Remove a transport tool from the layout. |
| `shift_labware(labware_name, relative_x=0.0, relative_y=0.0, relative_z=0.0, relative_angle=0.0)` | Apply relative X/Y/Z/angle offsets to a labware item's position in the deck layout. Returns `LayoutShiftLabwareResponse`. |
| `tilt_labware(labware_name, tilt_degrees, pivot_point=TiltPivotPoint.LEFT_EDGE, *, pivot_x_offset_mm=0.0, pivot_z_offset_mm=0.0, well_position=TiltWellPosition.CENTER, measured_tilt_degrees=None, tip_end_height_mm=0.0, wall_margin_mm=1.0, high_wall_margin_mm=2.0, tip_profile=None)` | Offset every well of a plate in the deck layout to match a tilt of 0-10 degrees (0 returns it to flat; fractions accepted). `DEEPEST_POINT` / `HIGHEST_POINT` aim one tip as close to the low / high wall as it fits with the tip end height and margins, and raise `ValueError` if no tip fits. `measured_tilt_degrees` is the plate's real angle, used for the offsets. Plates only. Calls do not add up, and sample tracking is kept. Transport commands raise `LabwareTiltedError` while the plate is tilted. Does not move the tilt hardware. Returns `LayoutTiltLabwareResponse`. See [Deck and Layout Guide](examples/deck_and_layout.md#tilt-labware). |
| `is_labware_tilted(labware_name)` | Whether `tilt_labware` has left the plate tilted (case-insensitive). |
| `get_tilted_labware()` | Every plate currently tilted: lower-cased name -> commanded degrees. |
| `get_tilt_settings(labware_name)` | How `tilt_labware` last tilted the plate (`TiltSettings`: commanded and measured angle, aim, tip and margins), or `None` if flat. |
| `split_wells(labware_name, wells=None, *, channel_type=SplitChannelType.ONE_ML, max_channels=None, fit=SplitWellFit.POSITION, well_position=None, tip_profile=None, tip_end_height_mm=None, wall_margin_mm=None, high_wall_margin_mm=None)` | Let several channels pipette side by side into large wells (6/12/24-well plates, 50 mL tubes). Places a temporary rack of slots at the channel pitch (9 mm for 1 mL, 18 mm for 5 mL) inside each well, sized from the well's shape, the tip shape and any tilt. Afterwards aspirate / dispense / liquid level detection with 2+ channels of that type on a split well go to its slots automatically (channel `c` -> slot `c - first + 1`); more channels than slots raise `SplitWellCapacityError`. `fit`: `SplitWellFit.POSITION` keeps the aim (aimed at a wall: as many channels as fit, as close to it as they fit), `SplitWellFit.MAX_CHANNELS` uses the most channels the well holds, an `int` asks for exactly that many. Tip end height and margins default to `tilt_labware`'s. The splits follow the plate through `tilt_labware`, `shift_labware`, `move_carrier` and transport, and `remove_labware` removes them. Returns `list[SplitWellSite]`. See [Deck and Layout Guide](examples/deck_and_layout.md#split-wells). |
| `remove_split_wells(labware_name=None, wells=None, *, channel_type=None, consolidate_volumes=False)` | Remove split wells; pipetting goes to the well centres again. `consolidate_volumes=True` adds the slots' tracked volumes back onto the parent well. Returns the removed rack ids. |
| `get_split_wells(labware_name=None)` | The wells currently split (`SplitWellSite`: parent, channel type, rack id, slots and their coordinates). |

> **Labware id casing:** VENUS stores every labware id (`labware_id`, `plate_id`,
> `lid_id`, `tip_pool`, and any name it auto-assigns when one is omitted) **lower-cased**,
> regardless of the case it was added with — `add_reservoir(..., labware_id="Trough1")` is
> later reported back, by every query below and by any tracking/event data, as `"trough1"`.
> A `Labware@expression` positions-selector string is matched against VENUS's storage
> server-side, so it does not need to be lower-cased by the caller — but code that compares
> a labware id it *typed* against one it *read back* (a query result below, a cache keyed by
> labware id, a script's own tracking) must normalize both sides first, the same caveat as
> the taught-location keys further down this document.

### Layout Queries

| Method | Description |
|--------|-------------|
| `get_added_carriers()` | Return the list of carriers currently added to the deck layout. Returns `AddedCarriersResponse`. |
| `get_available_tracks()` | Return the list of available (unoccupied) deck tracks. Returns `AvailableTracksResponse`. |
| `get_occupied_tracks()` | Return the list of currently occupied deck tracks. Returns `OccupiedTracksResponse`. |
| `get_available_carrier_sites(carrier)` | Return the available (empty) sites on the specified carrier. Returns `CarrierSitesResponse`. |
| `get_occupied_carrier_sites(carrier)` | Return the occupied sites on the specified carrier. Returns `CarrierSitesResponse`. |
| `get_labware_on_carrier(carrier)` | Return the labware items loaded on the specified carrier. Returns `LabwareOnCarrierResponse`. |
| `get_labware_positions(labware_name)` | Return the well positions occupied on the specified labware instance, keyed by labware name. Returns `LabwarePositionsResponse` (dynamic per-labware data via `.return_parameters.model_extra`). |
| `get_labware_location(labware_name)` | Return the carrier and site location of the specified labware. Returns `LabwareLocationResponse`. |
| `get_top_labware(carrier_id, site)` | Return the top labware at the specified carrier site. Returns `TopLabwareResponse`. |
| `get_labware_coordinates(labware_name, well=None)` | Return deck coordinates. With `well`: that well's `well`/`x`/`y`/`z`/`angle`. Without `well`: `origin` (the labware origin) plus `wells`, the coordinates of every position (rack-type labware only; a carrier returns `origin` alone) -- the top-level `x`/`y`/`z`/`angle` are `None`. Returns `LabwareCoordinatesResponse`. |
| `is_track_occupied(track_id)` | Return whether the specified deck track is occupied. Returns `TrackOccupiedResponse`. |
| `get_added_plates()` | Return the list of all plates currently in the deck layout. Returns `AddedPlatesResponse`. |
| `get_added_tip_racks()` | Return the list of all tip racks currently in the deck layout. Returns `AddedTipRacksResponse`. |
| `get_added_reservoirs()` | Return the list of all reservoirs currently in the deck layout. Returns `AddedReservoirsResponse`. |

### Sample Tracking

Category `Sample Tracking` (`tracking.*`). Each `labware` entry is a dict (wire keys) or the matching model from `hamilton_venus.models`.

| Method | Description |
|--------|-------------|
| `get_barcode_locations(barcodes)` | Look up where each barcode is tracked on the deck. Returns `TrackingBarcodeLocationsResponse` (`.return_parameters.barcodes` with `labware_id` / `well` / `labware_type`, plus `not_found` and `total_barcodes_found`). `.to_positions(labware_type=TrackedLabwareType.WELL, barcodes=None)` converts the result into position selectors (`"Plate_1@A1"`) that aspirate/dispense steps accept. `labware_type` filters on the reported type: a `TrackedLabwareType` (`TEMPLATE`, `RACK`, `WELL`, `TIP_RACK`, `RESERVOIR_RACK`), any other type string such as `"Reservoir Well"`, a list of those, or `None` for no filter. `barcodes` restricts and orders the output. |
| `get_labware_details(labware, well_order=WellOrder.COL_ASC)` | Return the tracked barcode, type and position of each labware and the barcode, volume, state and position of its wells. Accepts the same position inputs as pipetting steps (`"Plate_1@all"`, `"Plate_1@A1:C3"`, `Position`, a list of those) or `{"labwareId": ..., "wells": ["A1", ...]}` entries; a bare labware ID or `@all` reports every well loaded in the labware. Returns `TrackingLabwareDetailsResponse`; a labware that cannot be reported carries the reason in its `message`. Wells are sorted X ascending, then Y and Z descending. Well `volume` is `None` for `Reservoir Rack`, `Tip Rack` and `Template` labware, which VENUS does not track a volume for; reservoir wells also have no tracked state or barcode (`labware_state` and `barcode` are `None`). |
| `set_barcodes(labware, barcodes=None, well_order=WellOrder.COL_ASC)` | Assign barcodes. Either positions plus `barcodes` paired in order (`set_barcodes("Plate_1@A1,B1", ["bc1", "bc2"])`; a bare labware ID takes one barcode for the labware itself), or entries `{"labwareId": ..., "barcode": ..., "wells": [{"id": "A1", "barcode": ...}]}` where `barcode` and `wells` are both optional. Returns `TrackingSetBarcodesResponse` (`total_labware_barcodes_set`, `total_well_barcodes_set`). |
| `set_labware_volume(labware, volume=None, well_order=WellOrder.COL_ASC)` | Set tracked volumes (uL). Either positions plus one `volume` (`set_labware_volume("Plate_1@A1:H1", 50.0)`; a bare labware ID or `@all` sets every well), or entries `{"labwareId": ..., "volume": ..., "wells": [{"id": "A1", "volume": ...}]}` where `volume` and `wells` are both optional. Has no effect on reservoirs, tip racks or carriers (no tracked volume). Returns `CommandResponse`. |

---

## Transport Commands

Plate transport and handling using CO-RE grippers (gripper tools picked up by the pipetting channels) and the iSWAP (Hamilton's dedicated plate-handling robot arm). Available on both STAR and Vantage; `core_5ml_*` methods use STAR-only tools and will be rejected by Vantage hardware. See [Transport and Gripper Tools Guide](examples/transport.md) and [Advanced Transport Workflows](examples/advanced/transport_workflows.md) for detailed examples.

| Method | Description |
|--------|-------------|
| `core_transport(labware_name, carrier, site, grip_height_above_bottom, grip_width=None, grip_open=None, tool_id=None, front_channel=None, ...)` | Transport a plate to a carrier site using a CO-RE gripper. |
| `core_transport_is_holding_labware()` | Check whether the CO-RE gripper is currently holding labware. Returns `TransportIsHoldingLabwareResponse`. |
| `core_transport_tracking_clear()` | Clear the transport tracking state. |
| `core_eject_grips()` | Eject the CO-RE grips. |
| `core_present_and_scan(labware_name, carrier, site, grip_height_above_bottom, track, z_minimal_position, grip_width=None, grip_open=None, grip_force=None, ...)` | Transport labware to a scan position and return the barcode. See [Transport Guide](examples/transport.md) for details. Returns `TransportPresentAndScanResponse`. |
| `core_transport_return_plate(mode="return", carrier=None, site=None, ...)` | Return a plate to its original position or place it in a new location. |
| `core_transport_to_waste(labware_name, grip_height_above_bottom, grip_width=None, grip_open=None, ...)` | Transport the specified plate to waste. |
| `core_hold_lid(labware_name, grip_height_from_top, grip_width=None, grip_open=None, tool_id=None, front_channel=None, ...)` | Grip and hold a lid with the 1 mL transport tool. Returns `MessageResponse`. |
| `core_5ml_transport(labware_name, carrier, site, grip_height_above_bottom, grip_width=None, grip_open=None, tool_id=None, front_channel=None, ...)` | Transport a plate to a carrier site using the 5 mL CO-RE gripper. |
| `core_5ml_transport_is_holding_labware()` | Check whether the 5 mL CO-RE gripper is currently holding labware. Returns `TransportIsHoldingLabwareResponse`. |
| `core_5ml_transport_tracking_clear()` | Clear the 5 mL transport tracking state. |
| `core_5ml_eject_grips()` | Eject the 5 mL CO-RE grips. |
| `core_5ml_present_and_scan(labware_name, carrier, site, grip_height_above_bottom, track, z_minimal_position, grip_width=None, grip_open=None, grip_force=None, ...)` | Transport labware to a scan position and return the barcode using the 5 mL gripper. Returns `TransportPresentAndScanResponse`. |
| `core_5ml_transport_return_plate(mode="return", carrier=None, site=None, ...)` | Return a held plate to its original position or a new location using the 5 mL gripper. |
| `core_5ml_transport_to_waste(labware_name, grip_height_above_bottom, grip_width=None, grip_open=None, ...)` | Transport the specified plate to waste using the 5 mL gripper. |
| `core_5ml_hold_lid(labware_name, grip_height_from_top, grip_width=None, grip_open=None, tool_id=None, front_channel=None, ...)` | Grip and hold a lid with the 5 mL transport tool. Returns `MessageResponse`. |
| `iswap_transport(labware_name, carrier, site, grip_height_above_bottom, grip_width=None, grip_open=None, grip_force=None, grip_inverse=None, place_rotation=None, ...)` | Move labware using the iSWAP transport tool. `grip_inverse` accepts `GripInverse`, `place_rotation` accepts `PlaceRotation`. Returns `MessageResponse`. |
| `iswap_tracking_clear()` | Clear iSWAP transport tracking state. |
| `iswap_is_holding_labware()` | Return iSWAP held-labware status payload. Returns `IswapIsHoldingLabwareResponse`. |
| `iswap_transport_to_waste(labware_name, grip_height_above_bottom, grip_width=None, grip_open=None, grip_inverse=None, ...)` | Move labware to waste using the iSWAP transport tool. `grip_inverse` accepts `GripInverse`. Returns `MessageResponse`. |
| `iswap_park()` | Park the iSWAP transport tool. |
| `iswap_present_and_scan(labware_name, carrier, site, track, grip_height_above_bottom, z_minimal_position, grip_inverse=None, place_rotation=None, ...)` | Present labware for barcode scan using iSWAP. `grip_inverse` accepts `GripInverse`, `place_rotation` accepts `PlaceRotation`. Returns `TransportPresentAndScanResponse`. |
| `iswap_get_labware(labware_name, grip_height_above_bottom, grip_width=None, grip_open=None, grip_force=None, grip_inverse=None, ...)` | Pick up labware without placing it using the iSWAP transport tool. `grip_inverse` accepts `GripInverse`. Returns `MessageResponse`. |
| `iswap_put_labware(carrier, site, place_rotation=None)` | Place currently-held labware at a carrier site using the iSWAP transport tool. `place_rotation` accepts `PlaceRotation`. Returns `MessageResponse`. |
| `iswap_get_labware_complex_movement(labware_name, grip_height_above_bottom, retract_distance, lift_height, orientation, ...)` | Pick up labware from a hotel with complex movement. `orientation` accepts `CMOrientation`: the direction the iSWAP faces. Returns `MessageResponse`. |
| `iswap_put_labware_complex_movement(carrier, site, retract_distance, lift_height, orientation, place_rotation=None)` | Place currently-held labware into a hotel with complex movement. Without `place_rotation`, sends the rotation for the turn from the last get's grip to `orientation`. Returns `MessageResponse`. |

---

## Status Light Commands

Control the instrument status indicator light.

| Method | Description |
|--------|-------------|
| `status_light_set_front_light(color, blink=False, progress=0)` | Set color, blink, and discrete progress level (0-5, each step = 20%) in one command. |

---

## Deck Commands

Persistence and management of deck layouts.

| Method | Description |
|--------|-------------|
| `deck_get_previous()` | Check whether a previous deck layout is available to restore. Returns `DeckAvailableResponse`. |
| `deck_get_saved()` | Return the list of saved deck layout names. Returns `SavedDecksResponse`. |
| `deck_load(deck_name=None, *, previous=False)` | Load a previously saved deck layout by name. Set `previous=True` (and omit `deck_name`) to reload the last deck. |
| `deck_save(deck_name, *, overwrite=False)` | Save the current deck layout with the specified name. |
| `deck_delete_saved(deck_name)` | Delete a previously saved deck layout by name. |
| `deck_import(path)` | Import a deck layout from a .lay file path. Returns `DeckImportResponse`. |
| `deck_get_rack_ids_from_deck(path, carrier_filter=None, only_floating_racks=None)` | Get rack IDs from a deck layout file. Returns `DeckGetRackIdsFromDeckResponse`. |
| `deck_import_rack_as_site(path, target_labware_name, carrier_filter=None, only_floating_racks=None, site_name=None)` | Import a rack from a deck layout file as a site on the specified labware. Returns `DeckImportRackAsSiteResponse`. |

---

## Taught Location Commands

Record operator-taught position corrections to
`C:\Program Files (x86)\Hamilton\SDK\Active Layout\TaughtLocations.json`. These
methods are **local file I/O only** — they need no instrument connection and send
nothing to the VENUS runtime. A VENUS method reads the file back and enforces the
corrections at run time (configured separately).

The Active Layout folder, `TaughtLocations.json` included, is cleared each time a
new session connects. To keep taught locations, save the deck with `deck_save(...)`
and start the next session with `deck_name=...`, which restores the file.

The file holds two lookup maps. `carrierSiteOffsets` is keyed by
`"<carrier>/<site>"`. `labwarePositions` is nested — keyed by labware name, then by
`"<carrier>/<site>"` — so one plate can carry different coordinates on different
sites. Each `register_*` call is **latest-wins**: it adds a new key or replaces the
record under an existing one; no history is kept. VENUS is expected to resolve a
location by checking `labwarePositions[<plate>]["<carrier>/<site>"]` first, then
falling back to `carrierSiteOffsets["<carrier>/<site>"]`.

`labware`, `carrier` and `site` are stored **lower-cased** — in both the record
fields and the map keys — so `"Plate1"` and `"plate1"` address the same entry. The
VENUS side must lower-case them before building a lookup key.

| Method | Description |
|--------|-------------|
| `register_taught_offset(carrier, site, *, dx, dy, dz, d_angle=0.0, note=None)` | Record a relative X/Y/Z (+ angle) correction for a carrier/site. Returns `CarrierSiteOffset`. |
| `register_taught_position(labware, carrier, site, *, x, y, z, angle=0.0, note=None)` | Record absolute X/Y/Z (+ angle) coordinates for a labware item at a carrier/site. Returns `LabwarePosition`. |
| `get_taught_locations()` | Return the whole file. Returns `TaughtLocationsFile` (empty maps when the file does not exist). |
| `get_taught_offset(carrier, site)` | Direct lookup of the offset for a carrier/site. Returns `CarrierSiteOffset` or `None`. |
| `get_taught_positions(labware)` | Every taught position for a labware item, keyed by `"<carrier>/<site>"`. Returns `dict[str, LabwarePosition]` (`{}` if none). |
| `get_taught_position(labware, carrier, site)` | Direct lookup of a labware item's position at one carrier/site. Returns `LabwarePosition` or `None`. |
| `resolve_taught_location(labware, carrier, site)` | Resolve the way VENUS does: the labware position at that carrier/site first, then the carrier/site offset. Returns `LabwarePosition`, `CarrierSiteOffset`, or `None`. |
| `remove_taught_offset(carrier, site)` | Delete one carrier/site offset. Returns `bool` (`True` if it existed). |
| `remove_taught_position(labware, carrier=None, site=None)` | Delete one carrier/site combination for the labware, or (with `carrier`/`site` omitted) every taught position for it. Returns `bool`. |
| `clear_taught_locations()` | Empty both maps, leaving a canonical empty file in place. |

Set the client attribute `_taught_locations_path` to redirect the file (useful for
tests or non-default installs). The module functions in
`hamilton_venus.taught_locations` (same names, plus a `path=` argument and
`carrier_site_key(carrier, site)`) do the same work without a client.

**Enforcement (VENUS side).** The bundled VENUS method library reads this file at
run time via `sdk_method_structure/Library/TaughtLocation_Helper` — `LayoutController`
calls `ShiftLabwareForTaughtLocation(Device, labware, carrier, site)` after each
labware placement, which resolves the teach point (labware-at-site first, then the
carrier/site offset) and applies it as a labware shift. Nothing needs to be enabled
from Python; recording a teach point is enough for the next run to pick it up.

---

## Teaching Commands (Automated Teaching)

Teach labware positions automatically with a teaching needle on one 1 mL channel
(the *teaching channel*) and the channel's Z-stall sensor. The single commands
(category `Teaching`, actions `teaching.1mL.*`) do one move or one search on the
instrument; `teach_well` combines them into a full plate teach and does the
arithmetic in Python. A rack of teaching needles must be on the deck. All
coordinates are needle-tip coordinates in mm. See [teaching.md](teaching.md) for
the algorithm.

| Method | Description |
|--------|-------------|
| `teaching_set_channel(channel)` | Set the 1 mL channel used for teaching (1-based). Not allowed while a needle is held; reset to the instrument configuration on every connect. Returns `TeachingChannelResponse`. |
| `teaching_get_channel()` | Return the teaching channel (`.return_parameters.channel`). Returns `TeachingChannelResponse`. |
| `teaching_pickup_needle()` | Pick up a teaching needle with the teaching channel. Returns `TeachingChannelResponse`. |
| `teaching_eject_needle()` | Return the teaching needle to its pickup position. Returns `CommandResponse`. |
| `teaching_is_needle_picked_up()` | Whether the teaching channel holds a needle (`.return_parameters.is_needle_picked_up`). Returns `TeachingNeedleStatusResponse`. |
| `teaching_get_labware_dimensions(labware_name, well=None)` | Labware center / bottom Z / height and well center / bottom Z / depth (default: the first position). Returns `TeachingLabwareDimensionsResponse`. |
| `teaching_move_channel(x=None, y=None, z=None, z_traverse=None)` | Move the needle (Z and traverse 105-245 mm); omitted axes stay put, no arguments just reads the position. Returns `TeachingMoveResponse` (`x`/`y`/`z` after the move). |
| `teaching_measure_z(z_start, z_min, *, z_end=-1, slow=False)` | Search down from `z_start` to `z_min` (100-334 mm) until the needle stalls. Returns `TeachingMeasureZResponse` (`measured_z`, `status`). |
| `teaching_measure_wall(direction, *, safe_height, min_search_z, well_width, step_distance=None)` | Step toward one wall (`TeachingDirection.PLUS_X` / `MINUS_X` / `PLUS_Y` / `MINUS_Y`), probing Z at each step until the needle stalls on the wall top. Start inside the well at its entrance; `safe_height` above the labware, `min_search_z` 2-3 mm inside the well, `well_width` (2-100 mm) the farthest it travels, `step_distance` 0.3-2.4 mm (default 0.6). Returns `TeachingMeasureXYResponse` (`wall`, `status`, `measured.wall_coordinate` / `measured.entrance_z`). |
| `teach_well(labware_name, well=None, *, well_width=None, step_distance=0.6, safe_clearance=5.0, search_depth=3.0, bottom_search_margin=5.0, z_offset=0.0, teach_z_only=False, move_to_well=True, traverse_z=245.0, register=False, carrier=None, site=None)` | Teach one plate well: move over it, find the +X/-X/+Y/-Y walls, take the center of each axis, find the bottom, lift, and compare with the definition. `register=True` saves the corrected labware position with `register_taught_position` (needs `carrier`, `site`). Raises `TeachingError` if a wall or the bottom is not found (the needle is lifted first). Returns `TeachWellResult` (`walls`, `center`, `entrance_z`, `bottom_z`, `expected`, `offset`, `taught_position`). |

Search results carry `status.code` (`TeachingMeasureStatus`): `0` `NOT_FOUND`,
`1` `FOUND`, `2` `FOUND_EARLY` (the needle stalled before the search height —
something is higher than expected).

```python
with StarClient() as star:
    star.teaching_pickup_needle()
    try:
        result = star.teach_well("Plate_1", "D6", register=True, carrier="PltCar_1", site=1)
        print(result.offset)   # taught - definition, mm
    finally:
        star.teaching_eject_needle()
```

---

## Liquid Class Commands

Manage liquid class definitions for pipetting operations.

| Method | Description |
|--------|-------------|
| `pull_liquid_classes(names)` | Pull (download) the named liquid class definitions from the instrument. |
| `push_liquid_classes(names)` | Push (upload) the named liquid class definitions to the instrument. |
| `get_liquid_devices()` | Get the available liquid handling devices. Returns `LiquidDevicesResponse`. |
| `get_liquid_names()` | Get the available liquid names/types. Returns `LiquidNamesResponse`. |
| `get_liquid_classes(*, tip_type=-1, device=-1, dispense_mode=-1, is_original=-1, has_tadm_enabled=-1)` | Get liquid class names filtered by tip, device, dispense mode, and metadata flags. Returns `LiquidClassesResponse`. |
| `get_tip_types()` | Get the available tip type definitions. Returns `TipTypesResponse`. |
| `get_liquid_class(name)` | Get the full definition of a single liquid class by name. Returns `GetLiquidClassResponse`. |
| `update_liquid_class(definition)` | Update an existing liquid class definition on the instrument. Takes a `LiquidClassDefinition`. |

---

## System Commands

System-level operations including tip counter management and method termination.

| Method | Description |
|--------|-------------|
| `tip_pool_get_tip_counters()` | Return all tip counter states. Returns `TipPoolCountersResponse`. |
| `tip_pool_get_tip_counter(tip_pool)` | Return the tip counter state for the specified tip pool. Returns `TipPoolCounterResponse`. |
| `tip_pool_get_available_tips(tip_pool)` | Return structured available-tip data for the specified tip pool. Returns `TipPoolAvailableTipsResponse`. |
| `tip_pool_get_empty_tips(tip_pool)` | Return empty tip information for the specified tip pool. |
| `tip_pool_get_missing_racks(tip_pool)` | Return the names of the pool's racks marked missing (not present, e.g. transported away). Returns `TipPoolMissingRacksResponse`. |
| `tip_pool_initialize_tip_counter(tip_pool)` | Initialize the tip counter for the specified tip pool. |
| `tip_pool_reset_tip_counter(tip_pool)` | Reset the tip counter for the specified tip pool. |
| `tip_pool_set_tip_counter(tip_pool, available_tips)` | Set the tip counter state for the specified tip pool. `available_tips` uses the grouped rack structure expected by the backend. |
| `tip_pool_show_tip_counter(tip_pool)` | Show the tip counter dialog for the specified tip pool. |
| `tip_pool_show_tip_counters(tip_pools=None)` | Show the tip counter dialog for the specified tip pools, or every tip pool if omitted. Returns `ShowTipCountersResponse`. |
| `instrument_terminate()` | Terminate the current method execution. |

> **`tip_pool_show_tip_counter(s)` and remote/automated callers.** The dialog these two open is
> drawn by VENUS on the instrument PC's own console -- it is not visible over a network
> connection. A caller with no console
> session on that machine only sees the call block until someone at the instrument closes the
> dialog, then gets back whatever the return value is; it cannot read or drive the dialog itself.
> For automated tip counter updates, use `tip_pool_initialize_tip_counter`,
> `tip_pool_reset_tip_counter`, `tip_pool_set_tip_counter`, and
> `tip_pool_get_tip_counter`/`tip_pool_get_tip_counters` instead -- none of those open a dialog.

---

## Labware Commands

Query and manage labware definitions in the system.

| Method | Description |
|--------|-------------|
| `labware_get_types()` | Return the list of available labware type names. Returns `LabwareDefinitionTypesResponse`. |
| `labware_get_definitions(filter=None)` | Return labware definitions, optionally filtered by name. Returns `LabwareDefinitionDefinitionsResponse`. |
| `labware_get_definition(labware_name)` | Return the definition for the specified labware type. Returns `LabwareDefinitionSingleResponse`. |
| `labware_add_definition(labware_name, labware_definition)` | Add a new labware definition to the system. |
| `labware_update_definition(labware_name, labware_definition)` | Update an existing labware definition. |
| `labware_delete_definition(labware_name)` | Delete the specified labware definition from the system. |
| `labware_get_params_from_id(labware_name)` | Get the full labware definition for the specified labware instance by name/ID. Returns `LabwareDefinitionSingleResponse`. |

---

## Advanced Topics

### Raw Command Fallback

For commands not yet wrapped by the SDK, use `send_command` directly:

```python
response = star.send_command(
    category="Custom",
    action_name="backend.customCommand",
    parameters={"example": True},
)
print(response.return_code, response.return_parameters)
```

### Command Timeout Override

Use `set_command_timeout` to temporarily override the timeout for long-running operations:

```python
with star.set_command_timeout(600.0):
    star.instrument_init(force_init=True)
```

Pass `None` to disable the timeout entirely for commands requiring user input:

```python
with star.set_command_timeout(None):
    star.instrument_init()
```

---

## Compound Commands

High-level commands that orchestrate multiple low-level SDK calls into a single operation. Available on both `StarClient` and `VantageClient`. Tip management, batching, and result aggregation are handled automatically. See [Compound Commands](examples/compound_commands/README.md) for detailed guides.

| Command | Description |
|---------|-------------|
| `add_reagent(*, reagent_source, dest_plate, volume, tip_pool, liquid_class, ...)` | Dispense a reagent from one or more source locations into destination wells, with single-dispense and multi-dispense modes and an optional worklist CSV of per-well destinations and volumes. Returns `AddReagentResult`. See [Add Reagent](examples/compound_commands/add_reagent.md). |
| `copy_plate(source_plate_id, dest_plate_id, *, volume, liquid_class, tip_pool, ...)` | Transfer the contents of one plate to another with automatic tip management and multi-iteration batching. Returns `CopyPlateResult`. See [Copy Plate](examples/compound_commands/copy_plate.md). |
| `hit_picking(*, transfer_csv, liquid_class, tip_pool, ...)` | Transfer samples between arbitrary source and destination wells from a CSV worklist ("cherry pick"), with fresh-tips, reuse-tips, and minimize-tips (one tip per source well) strategies. Returns `HitPickingResult`. See [Hit Picking](examples/compound_commands/hit_picking.md). |
| `pool_samples(*, source_plate, dest_plate, pool_size, volume_per_source, liquid_class, tip_pool, ...)` | Combine ``pool_size`` source wells into a single destination well, one pool at a time, with optional in-pool tip reuse and final mix. Returns `PoolSamplesResult`. See [Pool Samples](examples/compound_commands/pool_samples.md). |
| `replicate_samples(*, source_plate, dest_plate, replicates_per_source, volume_per_replicate, liquid_class, tip_pool, ...)` | Aliquot every source well into ``replicates_per_source`` destination wells, with single-dispense and multi-dispense modes, multi-dispense auto-split, and pre/post-aliquot handling. Returns `ReplicateSamplesResult`. See [Replicate Samples](examples/compound_commands/replicate_samples.md). |
| `serial_dilution_by_volume(*, plate_id, start_column, num_dilutions, transfer_volume, diluent_volume, diluent_source, transfer_tip_pool, diluent_tip_pool="", ...)` | Dilute a sample across a plate's columns, one series per row (rows in parallel), using a global diluent pre-charge phase then transfer chains, with an explicit per-well diluent volume. Returns `SerialDilutionResult`. See [Serial Dilution](examples/compound_commands/serial_dilution.md). |
| `serial_dilution_by_dilution_factor(*, plate_id, start_column, num_dilutions, transfer_volume, dilution_factor, diluent_source, transfer_tip_pool, diluent_tip_pool="", ...)` | Serial dilution where the per-well diluent volume is derived from the fold `dilution_factor` (`transfer_volume * (dilution_factor - 1)`). Returns `SerialDilutionResult`. See [Serial Dilution](examples/compound_commands/serial_dilution.md). |

---

## Heater Shaker Commands (HHS)

Control Hamilton Heater Shaker (HHS) devices for plate shaking and temperature control. A device must be registered first; `device_id` is optional on control commands and, when omitted, applies to all registered devices. See [Heater Shaker](examples/heater_shaker.md).

| Method | Description |
|--------|-------------|
| `hhs_create_star_device(node)` | Register an HHS connected through a STAR node (1-2). Returns `HHSCreateDeviceResponse`. |
| `hhs_create_usb_device(node)` | Register an HHS connected through USB (node 1-8). Returns `HHSCreateDeviceResponse`. |
| `hhs_get_device_ids()` | List registered HHS devices and their connection metadata. Returns `HHSDeviceIdsResponse`. |
| `hhs_get_status()` | Get the current shaking speed and temperature status of each device. Returns `HHSStatusResponse`. |
| `hhs_set_plate_lock(lock, device_id=None)` | Lock (`True`) or unlock (`False`) the plate. Returns `HHSPlateLockResponse`. |
| `hhs_start_shaker(speed, time=0, device_id=None)` | Start shaking at `speed` RPM (30-2500) for `time` seconds (0 = indefinite). Returns `HHSShakingStartedResponse`. |
| `hhs_stop_shaker(device_id=None)` | Stop shaking. Returns `HHSShakingStoppedResponse`. |
| `hhs_wait_for_shaker(device_id=None)` | Block until shaking has stopped. Returns `HHSShakingStoppedResponse`. |
| `hhs_start_temp_control(temperature, device_id=None)` | Start temperature control targeting `temperature` °C. Returns `HHSTempControlStartedResponse`. |
| `hhs_stop_temp_control(device_id=None)` | Stop temperature control. Returns `HHSTempControlStoppedResponse`. |
| `hhs_wait_for_temp_control(device_id=None)` | Block until temperature control has stopped. Returns `HHSTempControlStoppedResponse`. |
| `hhs_terminate()` | Disconnect all HHS devices. Returns `MessageResponse`. |

---

## Heater Cooler (HHC), Inheco ODTC, Inheco TEC Controller, and Tilt Module

All of these are **pure Python and do not go through the VENUS runtime** -- none is on
`StarClient`/`VantageClient` at all. Each has its own standalone client instead:

- **Heater Cooler (HHC)** — `HeaterCoolerClient`, `hhc_*` methods. See
  [Heater Cooler](examples/heater_cooler.md) for the full guide and method table.
- **Inheco ODTC** — `ODTCClient`, `odtc_*` methods. See
  [Inheco ODTC](examples/odtc.md) for the full guide and method table.
- **Inheco TEC Controller (STC/MTC)** — `InhecoTECClient`, `inheco_tec_*` methods. See
  [Inheco TEC Controller](examples/inheco_tec.md) for the full guide and method table.
- **MFX Tilt Module** — `TiltModuleClient`, `tilt_module_*` methods (RS-232, no COM object). It only
  moves the hardware; pair it with `tilt_labware()` so VENUS pipettes into the tilted wells. See
  [Tilt Module](examples/tilt_module.md) for the full guide and method table.
- **Hamilton Media Fill Module** — `MediaFillClient`, `media_fill_*` methods (also pure Python). See
  [Hamilton Media Fill Module](examples/media_fill.md) for the full guide and method table.

---

## Need Detailed Info?

This quick reference shows what commands exist and what they return. For in-depth guides, examples, and detailed parameter documentation, see:

| Topic | Guide |
|-------|-------|
| **Getting Started** | Connection, initialization, startup patterns → [Getting Started](examples/getting_started.md) |
| **Liquid Handling** | Aspirate, dispense, liquid level detection, mixing; settings reference → [Liquid Handling](examples/liquid_handling.md) |
| **96-Channel Head** | Full-plate operations, partial pickups, settings reference → [96-Channel Guide](examples/mph96.md) |
| **Deck Layout** | Building layouts, adding labware, lidded plates, layout queries → [Deck and Layout](examples/deck_and_layout.md) |
| **Autoload** | Loading/unloading carriers, occupancy sensing, deck audit → [Autoload](examples/autoload.md) |
| **Transport** | Plate transport, gripper control, barcode scanning → [Transport](examples/transport.md) |
| **Tip Pool Management** | Tip counter queries and updates → [Tip Pool Management](examples/advanced/tip_pool_management.md) |
| **Status & Diagnostics** | Front cover, status light, maintenance data → [Status and Diagnostics](examples/advanced/status_and_diagnostics.md) |
| **TADM** | Pressure curves, flagged channels, raw export → [TADM](examples/advanced/tadm.md) |
| **Custom Labware** | Add definitions, import `.lay` files, mount rack sites → [Custom Labware](examples/advanced/custom_labware.md) |
| **Liquid Classes** | Filter, query, pull/push definitions → [Liquid Class Management](examples/advanced/liquid_class_management.md) |
| **Common Patterns** | Practical workflows and best practices → [Common Patterns](examples/common_patterns.md) |
