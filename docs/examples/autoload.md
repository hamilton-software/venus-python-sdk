# Autoload

Guide for loading, unloading, and querying carrier state using the autoload shuttle.

Autoload commands are rejected with `VenusCommandUnsupportedError` when the instrument configuration does not report an autoload. See [Connect-Time Validation](advanced/instrument_configuration.md#connect-time-validation-from-the-instrument-configuration).

---

## Overview

This guide covers:
- Loading and unloading carriers by ID or track
- Loading a carrier that is already pushed in (STAR: unload first; Vantage: load directly)
- Checking individual track occupancy
- Reading carrier sensor status across the full deck
- Moving and parking the shuttle
- Production patterns for safe autoload workflows

---

## Fundamental Concepts

The autoload shuttle slides carriers on and off the deck. Each carrier is identified either by its `carrier_id` (the name given when it was added with `add_carrier()`) or by its deck `track_id` (1-based track number).

When loading, you can optionally pass `scan_positions` to control how tip rack positions are scanned:

| `scan_positions` value | Behaviour |
|------------------------|-----------|
| `ScanPositions.DETECTED` (`"?"`) | Scan only positions where tips were detected |
| `ScanPositions.ALL` (`"*"`) | Scan all positions unconditionally |
| `ScanPositions.SKIP` (`""`) | Skip scanning entirely |
| `list[int]` | Scan the explicitly listed position indices |

---

## Basic Operations

### Load a Carrier by ID

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

with StarClient() as star:
	star.add_carrier(
		labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
		left_track=1,
		labware_id="PlateCarrier1",
	)
	star.instrument_init()

	star.autoload_load_carrier_by_id("PlateCarrier1")
	print("PlateCarrier1 loaded")
```

### Load a Carrier by Track

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE
from hamilton_venus.models.enums import ScanPositions

with StarClient() as star:
	star.add_carrier(
		labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
		left_track=10,
		labware_id="TipCarrier1",
	)
	star.instrument_init()

	# Load and scan only detected positions
	star.autoload_load_carrier_by_track(
		track_id=10,
		scan_positions=ScanPositions.DETECTED,
	)
	print("Carrier at track 10 loaded")
```

### Loading a Carrier That Is Already Pushed In (STAR vs Vantage)

A carrier can already be pushed in when the load step runs: left in from a previous run, or pushed in by hand. The two instruments handle this differently.

**STAR: unload first.** The STAR load step does not take back a carrier that is already pushed in, so check the carrier sensor status and unload the carrier before loading it. This is the pattern used in `example_scripts/load_unload_dwp_carrier.py`:

```python
from hamilton_venus import StarClient


def load_by_id(star: StarClient, carrier_id: str) -> None:
	"""Load *carrier_id*, unloading first if already pushed in."""
	status = star.autoload_get_carrier_sensor_status()
	print(f"Sensor status: {status.return_parameters.carrier_sensor_status}")
	for item in status.return_parameters.carrier_sensor_status:
		if item.carrier.lower() == carrier_id.lower() and item.status:
			print(f"{carrier_id!r}: already pushed in -- unloading before load")
			star.autoload_unload_carrier_by_id(carrier_id)
			break

	result = star.autoload_load_carrier_by_id(carrier_id)
	print(f"Loaded {carrier_id!r} (barcode: {result.return_parameters.carrier_barcode or '(no read)'})")
```

Match the carrier by name (`item.carrier`) rather than by track: the sensor reports a carrier at its own sensor track, which is not necessarily the track the carrier was added on. Carrier names come back lower-cased, hence the case-insensitive comparison.

**Vantage: just load.** The Vantage load step unloads a carrier that is already pushed in as part of the load, so call `autoload_load_carrier_by_id()` / `autoload_load_carrier_by_track()` directly. Do **not** unload before loading on the Vantage: the unload step then raises a load tray error (`C0:13/83`, "Load tray full."), which stops the run for error handling.

```python
from hamilton_venus import VantageClient

with VantageClient() as vantage:
	vantage.instrument_init()

	# No sensor check or unload needed -- the load step handles a carrier that is already in.
	vantage.autoload_load_carrier_by_id("PlateCarrier1")
```

> **Note:** `autoload_get_carrier_sensor_status()` fails (code `101`, "Track 'N' is unknown to the layout!") when any carrier on the deck sits on a track the active layout does not define, so the STAR pattern above needs every pushed-in carrier to be part of the layout.

### Reading Scanned Barcodes

When `scan_positions` is set, the response's `return_parameters.barcode_returns` carries the scanned barcodes, alongside the loaded carrier's own identity:

```python
from hamilton_venus import StarClient

with StarClient() as star:
	star.instrument_init()

	result = star.autoload_load_carrier_by_id(
		"TubeRack1",
		scan_positions=[1, 2, 3],
	)

	print("Carrier labware:", result.return_parameters.carrier_labware_id)
	print("Carrier barcode:", result.return_parameters.carrier_barcode)
	for entry in result.return_parameters.barcode_returns:
		if entry.position:  # skip positions that were not scanned
			print(f"  position {entry.position}: {entry.barcode or '(no read)'}")
```

`carrier_labware_id` matches the labware ID the carrier was added under (e.g. via `add_tube_carrier`/`add_carrier`), and each `barcode_returns` entry's `position` is the 1-based position on that carrier: the site on a plate or tip carrier, and for a sample tube rack the tube's own well number (e.g. `"31"` for well `31`).

`barcode_returns` always holds one entry per barcode position registered to the carrier labware (its `MlStarCarCountOfBCPos` property; `countOfBcPositions` in the SDK's carrier JSON definitions), in position order, whatever `scan_positions` selected. A position that was not scanned comes back with an empty `position` and `barcode`; a scanned position with nothing to read keeps its `position` with an empty `barcode`. For example, scanning only site 2 of a 5-site plate carrier returns:

```
[('', ''), ('2', 'PLT00002'), ('', ''), ('', ''), ('', '')]   # (position, barcode)
```

### Unload a Carrier

```python
from hamilton_venus import StarClient

with StarClient() as star:
	star.instrument_init()

	# By carrier ID
	star.autoload_unload_carrier_by_id("PlateCarrier1")

	# Or by track number
	star.autoload_unload_carrier_by_track(track_id=1)
```

---

## Checking Occupancy

### Check a Single Track

```python
from hamilton_venus import StarClient

with StarClient() as star:
	star.instrument_init()

	result = star.autoload_is_track_occupied(track_id=5)
	if result.return_parameters.is_occupied:
		print("Track 5 is occupied")
	else:
		print("Track 5 is empty")
```

### Read Full Sensor Status

`autoload_get_carrier_sensor_status()` returns the occupancy and sensor availability for every track at once:

```python
from hamilton_venus import StarClient

with StarClient() as star:
	star.instrument_init()

	status = star.autoload_get_carrier_sensor_status()
	for item in status.return_parameters.carrier_sensor_status:
		state = "occupied" if item.status else "empty"
		avail = "sensor OK" if item.sensor_available else "no sensor"
		print(f"Track {item.sensor_track} ({item.carrier}): {state}, {avail}")
```

---

## Shuttle Positioning

### Move Shuttle to a Track

```python
from hamilton_venus import StarClient

with StarClient() as star:
	star.instrument_init()
	star.autoload_move(track_id=5)
	print("Shuttle moved to track 5")
```

### Park the Shuttle

```python
from hamilton_venus import StarClient

with StarClient() as star:
	star.instrument_init()

	star.autoload_park_left()   # park at left-most position
	star.autoload_park_right()  # or park at right-most position
```

---

## Production Pattern: Safe Load with Occupancy Check

Load a carrier only if the target track is clear, then verify the load succeeded:

```python
import logging
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE
from hamilton_venus.models.enums import ScanPositions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def safe_load_carrier(star: StarClient, carrier_id: str, track_id: int) -> bool:
	"""
	Load a carrier at the given track only if the track is unoccupied.

	Returns True if the carrier was loaded successfully.
	"""
	occupancy = star.autoload_is_track_occupied(track_id=track_id)
	if occupancy.return_parameters.is_occupied:
		logger.warning(
			"Track %d already occupied — cannot load %s", track_id, carrier_id
		)
		return False

	logger.info("Loading %s onto track %d...", carrier_id, track_id)
	star.autoload_load_carrier_by_id(
		carrier_id,
		scan_positions=ScanPositions.DETECTED,
	)
	logger.info("%s loaded successfully", carrier_id)
	return True


with StarClient() as star:
	star.add_carrier(
		labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
		left_track=1,
		labware_id="PlateCarrier1",
	)
	star.instrument_init()

	if safe_load_carrier(star, "PlateCarrier1", track_id=1):
		print("Ready to proceed with workflow")
	else:
		raise RuntimeError("Could not load carrier — check deck state")
```

---

## Production Pattern: Pre-Run Deck Audit

Before starting a run, verify that every expected carrier is present and every unexpected track is clear:

```python
import logging
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)


def audit_deck(star: StarClient, expected_occupied: list[int]) -> bool:
	"""
	Verify deck occupancy matches expectations.

	Args:
		expected_occupied: Track numbers that should be occupied before the run.

	Returns:
		True if deck state matches expectations.
	"""
	status = star.autoload_get_carrier_sensor_status()
	items = status.return_parameters.carrier_sensor_status

	issues = []
	for item in items:
		track = item.sensor_track
		is_occupied = item.status
		should_be_occupied = track in expected_occupied

		if not item.sensor_available:
			logger.debug("Track %d: no sensor", track)
			continue

		if should_be_occupied and not is_occupied:
			issues.append(f"Track {track}: expected carrier but track is empty")
		elif not should_be_occupied and is_occupied:
			issues.append(f"Track {track}: unexpected carrier present")

	if issues:
		for issue in issues:
			logger.error(issue)
		return False

	logger.info("Deck audit passed — %d carriers in place", len(expected_occupied))
	return True


with StarClient() as star:
	star.instrument_init()

	# Expect carriers on tracks 1, 10, and 20
	if not audit_deck(star, expected_occupied=[1, 10, 20]):
		raise RuntimeError("Deck audit failed — correct carrier positions before starting")

	print("Deck verified — starting workflow")
```

---

## Autoload API Reference

| Method | Returns | Description |
|--------|---------|-------------|
| `autoload_load_carrier_by_id(carrier_id, scan_positions=None)` | `AutoloadLoadCarrierResponse` | Load carrier by its configured ID |
| `autoload_load_carrier_by_track(track_id, scan_positions=None)` | `AutoloadLoadCarrierResponse` | Load carrier at the specified track |
| `autoload_unload_carrier_by_id(carrier_id)` | `CommandResponse` | Unload carrier by ID |
| `autoload_unload_carrier_by_track(track_id)` | `CommandResponse` | Unload carrier at the specified track |
| `autoload_is_track_occupied(track_id)` | `TrackOccupiedResponse` | Check if a single track is occupied |
| `autoload_get_carrier_sensor_status()` | `CarrierSensorStatusResponse` | Read occupancy/sensor status for all tracks |
| `autoload_move(track_id)` | `CommandResponse` | Move shuttle to the specified track |
| `autoload_park_left()` | `CommandResponse` | Park shuttle at left-most position |
| `autoload_park_right()` | `CommandResponse` | Park shuttle at right-most position |

**`CarrierSensorStatusItem` fields** (each element of `.return_parameters.carrier_sensor_status`):

| Field | Type | Description |
|-------|------|-------------|
| `carrier` | `str` | Carrier name at this track |
| `sensor_track` | `int` | Track number |
| `sensor_available` | `bool` | Whether occupancy sensor is present for this track |
| `status` | `bool` | `True` if carrier is detected as present |

---

## See Also

- [`deck-and-layout.md`](./deck-and-layout.md) — Adding carriers to the layout
- [`deck_persistence.md`](./advanced/deck_persistence.md) — Saving and reloading deck layouts
- [`../star-commands.md`](../star-commands.md) — Full API reference
