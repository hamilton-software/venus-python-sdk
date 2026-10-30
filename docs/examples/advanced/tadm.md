# TADM (Total Aspiration and Dispense Monitoring)

TADM records a pressure-vs-time curve for every aspiration and dispense. The curves can be used to detect clogs, empty wells, and out-of-specification liquid handling — either in real time (by flagging) or offline (by exporting the raw curve points for analysis).

---

## Overview

This guide covers:
- Reading TADM curves from aspirate and dispense results
- Detecting flagged (out-of-spec) curves
- Exporting raw curve points for offline analysis
- Using `CopyPlateResult.tadm_curves` for compound operations
- Practical patterns for process monitoring

---

## How TADM Data Is Returned

TADM data is optional. When the liquid class has TADM enabled, `aspirate()` returns a `ChannelAspirationResponse` whose `return_parameters.tadm` is a `ChannelTADM` object. When TADM is not enabled, `return_parameters.tadm` is `None`.

```
ChannelAspirationResponse
└── return_parameters: ChannelAspirationReturnParameters
	├── channels: list[AspirationChannelData]   # per-channel volumes / liquid level
	└── tadm: ChannelTADM | None
		└── tadm_curves: list[ChannelTADMCurve]
			├── channel_number: int
			├── volume: float
			├── step_type_name: str             # e.g. "Aspirate", "Dispense"
			├── liquid_class_name: str
			├── curve_flagged: int              # non-zero = out-of-spec
			├── error: int                      # non-zero = hardware error
			└── curve_points: list[ChannelTADMCurvePoint]
				├── time_ms: int | None
				└── pressure: int | None
```

The same structure applies to `dispense()` via `ChannelDispenseResponse`.

TADM is enabled per liquid class. To list classes that have it enabled, filter with `get_liquid_classes(has_tadm_enabled=...)` (see [Liquid Class Management](./liquid_class_management.md#filter-liquid-classes)). The examples below use a catalog liquid class; substitute one with TADM enabled, otherwise `tadm` is `None`.

**Prerequisites:** except for the `copy_plate()` example, which builds its own deck, the examples assume a deck that already has a tip pool `"TransferTips"` and plates `"SourcePlate"` and `"DestPlate"`, set up as in [TADM with `copy_plate()`](#tadm-with-copy_plate).

---

## Basic: Check for Flagged Curves

Inspect the TADM result after each aspirate to detect out-of-spec channels:

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

with StarClient() as star:
	star.instrument_init()
	star.tip_pickup(channels=[1, 2, 3, 4], tip_pool="TransferTips")

	result = star.aspirate(
		channels=[1, 2, 3, 4],
		positions="SourcePlate@col:1",
		volumes=100.0,
		liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	)

	tadm = result.return_parameters.tadm
	if tadm is not None:
		for curve in tadm.tadm_curves:
			if curve.curve_flagged:
				print(
					f"Channel {curve.channel_number}: FLAGGED "
					f"(step={curve.step_type_name}, volume={curve.volume}µL)"
				)
			else:
				print(f"Channel {curve.channel_number}: OK")
```

---

## Detect Errors and Flags Together

`curve_flagged` indicates a tolerance-band violation; `error` indicates a hardware-level problem. Check both:

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

def check_tadm(tadm, label=""):
	"""Log any flagged or errored TADM curves. Returns True if all OK."""
	if tadm is None:
		return True  # TADM not enabled for this liquid class

	all_ok = True
	for curve in tadm.tadm_curves:
		ch = curve.channel_number
		if curve.error:
			print(f"[{label}] Channel {ch}: ERROR code {curve.error}")
			all_ok = False
		elif curve.curve_flagged:
			print(f"[{label}] Channel {ch}: flagged (out of tolerance)")
			all_ok = False
	return all_ok


with StarClient() as star:
	star.instrument_init()
	star.tip_pickup(channels=[1, 2, 3, 4], tip_pool="TransferTips")

	asp = star.aspirate(
		channels=[1, 2, 3, 4],
		positions="SourcePlate@col:1",
		volumes=100.0,
		liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	)
	disp = star.dispense(
		channels=[1, 2, 3, 4],
		positions="DestPlate@col:1",
		volumes=100.0,
	)
	star.tip_eject(channels=[1, 2, 3, 4])

	asp_ok = check_tadm(asp.return_parameters.tadm, label="Aspirate")
	disp_ok = check_tadm(disp.return_parameters.tadm, label="Dispense")

	if asp_ok and disp_ok:
		print("All TADM checks passed")
	else:
		raise RuntimeError("TADM failure detected — review results before proceeding")
```

---

## Export Raw Curve Points

Access the raw pressure-vs-time points for offline analysis or custom visualization:

```python
import csv
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

with StarClient() as star:
	star.instrument_init()
	star.tip_pickup(channels=[1], tip_pool="TransferTips")

	result = star.aspirate(
		channels=[1],
		positions="SourcePlate@A1",
		volumes=50.0,
		liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	)
	star.tip_eject(channels=[1])

	tadm = result.return_parameters.tadm
	if tadm is not None:
		with open("tadm_curves.csv", "w", newline="") as f:
			writer = csv.writer(f)
			writer.writerow(["channel", "step_type", "time_ms", "pressure"])
			for curve in tadm.tadm_curves:
				for point in curve.curve_points:
					writer.writerow([
						curve.channel_number,
						curve.step_type_name,
						point.time_ms,
						point.pressure,
					])
		print(f"Exported {sum(len(c.curve_points) for c in tadm.tadm_curves)} points")
```

---

## TADM with `copy_plate()`

`CopyPlateResult` aggregates all TADM curves across every iteration via the `.tadm_curves` property:

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES

with StarClient() as star:
	star.instrument_init()
	star.add_carrier(
		labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
		left_track=1,
		labware_id="PlateCarrier1",
	)
	star.add_plate(
		labware_definition=LABWARE.PLATE.COS_96_RD,
		carrier_id="PlateCarrier1",
		site="1",
		plate_id="SourcePlate",
	)
	star.add_plate(
		labware_definition=LABWARE.PLATE.COS_96_RD,
		carrier_id="PlateCarrier1",
		site="2",
		plate_id="DestPlate",
	)
	star.add_carrier(
		labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
		left_track=10,
		labware_id="TipCarrier1",
	)
	star.add_tip_rack(
		tip_pool="TransferTips",
		labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL_FILTER,
		carrier_id="TipCarrier1",
		site="1",
	)

	result = star.copy_plate(
		source_plate_id="SourcePlate",
		dest_plate_id="DestPlate",
		tip_pool="TransferTips",
		liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
		volume=50.0,
	)

	all_curves = result.tadm_curves  # flat list across all iterations
	flagged = [c for c in all_curves if c.curve_flagged]

	print(f"Total curves: {len(all_curves)}, Flagged: {len(flagged)}")
	for curve in flagged:
		print(f"  Channel {curve.channel_number}: {curve.step_type_name} flagged")
```

---

## Production Pattern: TADM Monitoring Class

```python
import logging
from dataclasses import dataclass, field
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models.command_types import ChannelTADM

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TADMSummary:
	total_curves: int = 0
	flagged_curves: int = 0
	error_curves: int = 0
	flagged_channels: list[int] = field(default_factory=list)

	@property
	def all_ok(self) -> bool:
		return self.flagged_curves == 0 and self.error_curves == 0


class TADMMonitor:
	"""Accumulate and evaluate TADM results across multiple liquid handling steps."""

	def __init__(self, fail_on_flag: bool = True):
		self.fail_on_flag = fail_on_flag
		self.summary = TADMSummary()

	def record(self, tadm: ChannelTADM | None, label: str = "") -> bool:
		"""
		Record TADM curves from one aspirate or dispense result.

		Returns True if all curves passed, False if any were flagged or errored.
		"""
		if tadm is None:
			return True

		step_ok = True
		for curve in tadm.tadm_curves:
			self.summary.total_curves += 1
			if curve.error:
				self.summary.error_curves += 1
				logger.error(
					"[%s] Channel %d: TADM error code %d",
					label, curve.channel_number, curve.error,
				)
				step_ok = False
			elif curve.curve_flagged:
				self.summary.flagged_curves += 1
				self.summary.flagged_channels.append(curve.channel_number)
				logger.warning(
					"[%s] Channel %d: out-of-tolerance (volume=%.1fµL)",
					label, curve.channel_number, curve.volume,
				)
				step_ok = False

		if not step_ok and self.fail_on_flag:
			raise RuntimeError(
				f"TADM failure in step '{label}' — "
				f"{self.summary.flagged_curves} flagged, "
				f"{self.summary.error_curves} errors"
			)
		return step_ok

	def log_summary(self):
		logger.info(
			"TADM summary: %d total, %d flagged, %d errors",
			self.summary.total_curves,
			self.summary.flagged_curves,
			self.summary.error_curves,
		)


with StarClient() as star:
	star.instrument_init()
	monitor = TADMMonitor(fail_on_flag=True)

	channels = [1, 2, 3, 4, 5, 6, 7, 8]
	star.tip_pickup(channels=channels, tip_pool="TransferTips")

	asp = star.aspirate(
		channels=channels,
		positions="SourcePlate@col:1",
		volumes=100.0,
		liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	)
	monitor.record(asp.return_parameters.tadm, label="Aspirate col:1")

	disp = star.dispense(
		channels=channels,
		positions="DestPlate@col:1",
		volumes=100.0,
	)
	monitor.record(disp.return_parameters.tadm, label="Dispense col:1")

	star.tip_eject(channels=channels)
	monitor.log_summary()
```

---

## TADM Data Reference

| Field | Type | Description |
|-------|------|-------------|
| `tadm_curves` | `list[ChannelTADMCurve]` | One curve per channel that performed the step |
| `curve.channel_number` | `int` | 1-based channel index |
| `curve.step_type_name` | `str` | `"Aspirate"` or `"Dispense"` |
| `curve.liquid_class_name` | `str` | Liquid class used for this step |
| `curve.volume` | `float` | Commanded volume in µL |
| `curve.curve_flagged` | `int` | Non-zero if curve fell outside tolerance band |
| `curve.error` | `int` | Non-zero if a hardware error occurred |
| `curve.curve_points` | `list[ChannelTADMCurvePoint]` | Raw pressure-vs-time samples |
| `point.time_ms` | `int \| None` | Time offset from step start in milliseconds |
| `point.pressure` | `int \| None` | Pressure reading (instrument units) |

---

## See Also

- [`liquid_handling.md`](../liquid_handling.md) — Aspirate and dispense parameters
- [`compound_commands/copy_plate.md`](../compound_commands/copy_plate.md) — `copy_plate()` and `CopyPlateResult.tadm_curves`
- [`common_patterns.md`](../common_patterns.md) — Pattern 9: per-well TADM inspection
