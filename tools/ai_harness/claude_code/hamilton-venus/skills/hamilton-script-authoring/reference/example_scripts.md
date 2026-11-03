# Example scripts

The SDK's `example_scripts/` folder (next to `.venv` in the install, or `example_scripts/` in the SDK repo). Read the closest one before writing something new. Through the MCP spoke, `import_script(source_path=...)` copies one into the scripts store.

**Dialogs** marks scripts that use `tkinter` or `input()`. They are for the Script Manager or a console, and the spoke's `run_script` refuses them (V012).

## Pipetting

| Script | Shows |
|---|---|
| `aspirate_liquid_level.py` | Aspirate from a trough with capacitive LLD and read the detected liquid level |
| `tube_to_plate_example.py` | Tubes to a deep well plate with `add_reagent` and `replicate_samples`, two tip pools, autoload with barcode scan. **Dialogs** |
| `tube_carriers_to_deep_well_plate.py` | Tubes to a deep well plate with low-level `tip_pickup` / `aspirate` / `dispense` / `tip_eject` in batches of 8; simulated error injection. **Dialogs** |
| `mastermix_tubes_to_384_plate.py` | 4 tubes to every well of a 384 plate, tips reused, custom dispense order around the 9 mm channel pitch |
| `normalize_samples_pandas.py` | Worklist built with pandas: per-well sample and diluent volumes to a target concentration |
| `magnet_elution_transfer.py` | Move a plate onto an Alpaqua magnet, then transfer the cleared eluent to a clean plate |
| `magpip_whipip_dispense_on_the_fly.py` | Vantage MagPip: aspirate with TADM, then dispense on the fly at 2 µL per well |
| `tilt_labware_example.py` | Cell wash on a tilted plate: remove media from the low side, add buffer down the high side (Vantage) |
| `tilt_module_split_wells_example.py` | 6-well plate on the MFX Tilt Module, four channels per well with `split_wells` |
| `dynamic_labware_example.py` | Build a plate and a tube definition in Python (`labware_builder`), use them, delete them |

## Deck layouts

| Script | Shows |
|---|---|
| `create_and_save_layout.py` | Build a deck and save it with `deck_save` |
| `load_saved_layout.py` | List saved layouts and load the one picked. **Dialogs** |
| `load_previous_deck.py`, `load_previous_layout_and_query.py` | Reload the last-used layout and list what's on it |
| `import_layout_file.py` | Import a VENUS `.lay` file with `deck_import`. **Dialogs** |
| `import_ngs_star_moa_layout.py` | Import an NGS `.lay` and save it under a generic name |
| `clone_labware_definition_height.py` | Clone a labware definition with a new height; schema validation of bad definitions |

## Tips, tracking, autoload

| Script | Shows |
|---|---|
| `show_tip_counters.py` | `tip_pool_show_tip_counters` for all or some pools (blocks until the operator closes VENUS's dialog) |
| `sample_tracking.py` | Volumes, barcodes and tracked details around a pipetting step |
| `sample_tracking_tubes_to_plate.py` | Barcoded tubes into a plate, then where each sample ended up |
| `load_unload_dwp_carrier.py` | Autoload load / unload / load by carrier id, with the sensor checked first |
| `scan_barcodes.py` | Barcode scan of a plate and a tube rack while loading |

## Liquid classes, errors, logs, teaching

| Script | Shows |
|---|---|
| `copy_liquid_class.py` | Copy a liquid class under a new name and push it to the database |
| `simulate_firmware_error.py` | Inject a simulated firmware error and watch the error profile recover it |
| `run_log_com_trace.py` | Run log with the firmware COM trace embedded |
| `teach_plate_well.py` | Teach a plate's position with the teaching needle and save it |
| `register_taught_locations.py` | Write taught offsets and positions for VENUS to apply |

## Standalone devices (no VENUS, no StarClient)

| Script | Shows |
|---|---|
| `heater_cooler_incubate.py` | Hamilton Heater Cooler: chill, hold, release (simulated) |
| `inheco_tec_incubate.py`, `inheco_tec_hardware_test.py` | Inheco TEC: CPAC temperature and Thermoshake slots; hardware check |
| `odtc_run_pcr_protocol.py`, `odtc_pcr_temperature_trace.py`, `odtc_import_protocol_file.py`, `odtc_hardware_test.py` | Inheco ODTC: build and run PCR methods, plot temperatures, import vendor XML, hardware check |
| `media_fill_fill_trough.py`, `media_fill_hardware_test.py` | Media Fill Module: fill a trough to its sensor; full field test. The test has **Dialogs** |
| `tilt_module_demo.py`, `tilt_module_fit_hinge.py`, `tilt_module_hardware_test.py` | MFX Tilt Module: driver demo, hinge calibration from probe readings, hardware check |
