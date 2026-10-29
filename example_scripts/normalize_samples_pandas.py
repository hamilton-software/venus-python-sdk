"""Normalize sample concentrations with a pandas-built worklist.

A common prep step before library construction or qPCR is to bring every
sample to the same concentration. The script:

1. Loads a quantification table (sample well + measured ng/uL) into a pandas
   ``DataFrame``. By default it generates demo data. Point ``QUANT_CSV`` at a
   plate-reader export with ``well`` and ``conc_ng_ul`` columns to use real
   data instead.
2. Uses pandas to work out, for each sample, how much sample and how much
   diluent to add to reach ``TARGET_CONC_NG_UL`` in ``FINAL_VOLUME_UL``. Samples
   that are too dilute are flagged and skipped, and volumes are clipped to the
   pipettable range.
3. Writes two worklists from the DataFrame and runs them: the diluent with
   ``star.add_reagent``, then the samples with ``star.hit_picking``.
4. Saves a summary report CSV next to the worklists.

Needs pandas (``pip install pandas``).
"""

from __future__ import annotations

import pathlib
import tempfile

import numpy as np
import pandas as pd

from hamilton_venus import StarClient, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings, CapacitiveLLD, DispenseSettings

TIP_CARRIER = LABWARE.CARRIER.TIP_CAR_480BC
PLATE_CARRIER = LABWARE.CARRIER.PLT_CAR_L5_DWP
REAGENT_CARRIER = LABWARE.CARRIER.RGT_CAR_5R60
TIP_RACK = LABWARE.TIP_RACK.TIP_RACK_300UL
RESERVOIR = LABWARE.RESERVOIR.RGT_CONT_60ML
PLATE = LABWARE.PLATE.COS_96_DW_1ML

TIP_POOL = "300uLTips"
LIQUID_CLASS = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.SURFACE_EMPTY.STANDARDVOLUME_WATER_DISPENSESURFACE_EMPTY

# Aspirate from the detected liquid surface (capacitive LLD) and follow it down, for
# both the diluent and the samples. Detecting the surface also gives add_reagent a real
# reading of the diluent left in the reservoir.
ASPIRATE_SETTINGS = AspirateSettings(
    capacitive_lld=CapacitiveLLD.MID,
    liquid_following=True,
    submerge_depth=2.0,
)
# Dispense at a fixed height above the well bottom: the diluent goes into empty wells,
# where there is no surface to detect.
DISPENSE_SETTINGS = DispenseSettings(fixed_height=5.0)

SOURCE_PLATE_ID = "SamplePlate"
DEST_PLATE_ID = "NormPlate"
DILUENT_ID = "Diluent"

# Optional plate-reader export with columns: well, conc_ng_ul
QUANT_CSV: str | None = None

TARGET_CONC_NG_UL = 10.0
FINAL_VOLUME_UL = 100.0
MIN_PIPETTE_UL = 2.0


def load_quant_table() -> pd.DataFrame:
    """Return a DataFrame with ``well`` and ``conc_ng_ul`` columns."""
    if QUANT_CSV:
        return pd.read_csv(QUANT_CSV, usecols=["well", "conc_ng_ul"])

    # Demo data: 24 samples in column-major order (A1..H3) with random concentrations
    wells = [f"{row}{col}" for col in range(1, 4) for row in "ABCDEFGH"]
    rng = np.random.default_rng(seed=42)
    conc = rng.lognormal(mean=np.log(40), sigma=0.8, size=len(wells)).round(2)
    return pd.DataFrame({"well": wells, "conc_ng_ul": conc})


def build_normalization_plan(quant: pd.DataFrame) -> pd.DataFrame:
    """Add sample/diluent volumes and a status column to the quant table."""
    plan = quant.copy()
    plan["sample_ul"] = TARGET_CONC_NG_UL * FINAL_VOLUME_UL / plan["conc_ng_ul"]

    # Samples too dilute to reach the target: flag them and skip them.
    too_dilute = plan["sample_ul"] > FINAL_VOLUME_UL
    # Samples so concentrated that the sample volume is below the pipetting minimum:
    # pipette the minimum and let the final concentration end up a bit high.
    too_concentrated = plan["sample_ul"] < MIN_PIPETTE_UL

    plan["status"] = np.select(
        [too_dilute, too_concentrated],
        ["skipped: below target", "clamped: above target"],
        default="ok",
    )
    plan["sample_ul"] = plan["sample_ul"].clip(lower=MIN_PIPETTE_UL, upper=FINAL_VOLUME_UL).round(1)
    plan["diluent_ul"] = (FINAL_VOLUME_UL - plan["sample_ul"]).round(1)
    plan.loc[too_dilute, ["sample_ul", "diluent_ul"]] = 0.0
    plan["final_conc_ng_ul"] = (plan["conc_ng_ul"] * plan["sample_ul"] / FINAL_VOLUME_UL).round(2)
    return plan


def to_worklist(plan: pd.DataFrame, volume_column: str, source_labware: str | None = None) -> pd.DataFrame:
    """Turn one volume column into a transfer worklist, dropping volumes too small to pipette.

    With *source_labware* (hit picking) each row takes its liquid from the same well of that
    plate; without it (add_reagent) the worklist is destinations and volumes only, since the
    reagent comes from add_reagent's own ``reagent_source``.
    """
    rows = plan[plan[volume_column] >= MIN_PIPETTE_UL]
    worklist = pd.DataFrame({"dest_labware": DEST_PLATE_ID, "dest_well": rows["well"], "volume": rows[volume_column]})
    if source_labware is not None:
        worklist.insert(0, "source_well", rows["well"])
        worklist.insert(0, "source_labware", source_labware)
    return worklist


quant = load_quant_table()
plan = build_normalization_plan(quant)

print("Normalization plan:")
print(plan.to_string(index=False))
print("\nSamples per status:")
print(plan["status"].value_counts().to_string())
print(f"\nTotal diluent needed: {plan['diluent_ul'].sum():.1f} uL")

diluent_worklist = to_worklist(plan, "diluent_ul")
sample_worklist = to_worklist(plan, "sample_ul", SOURCE_PLATE_ID)

out_dir = pathlib.Path(tempfile.mkdtemp(prefix="normalization_"))
diluent_csv = out_dir / "diluent_worklist.csv"
sample_csv = out_dir / "sample_worklist.csv"
report_csv = out_dir / "normalization_report.csv"
diluent_worklist.to_csv(diluent_csv, index=False)
sample_worklist.to_csv(sample_csv, index=False)
plan.to_csv(report_csv, index=False)
print(f"\nWorklists and report written to {out_dir}")

try:
    with StarClient(simulate=True) as star:
        star.add_carrier(labware_definition=TIP_CARRIER, left_track=1, labware_id="TipCarrier")
        for site in range(1, 6):
            star.add_tip_rack(
                labware_definition=TIP_RACK,
                carrier_id="TipCarrier",
                site=str(site),
                tip_pool=TIP_POOL,
            )

        star.add_carrier(labware_definition=REAGENT_CARRIER, left_track=7, labware_id="ReagentCarrier")
        star.add_reservoir(
            labware_definition=RESERVOIR,
            carrier_id="ReagentCarrier",
            site="1",
            labware_id=DILUENT_ID,
        )

        star.add_carrier(labware_definition=PLATE_CARRIER, left_track=12, labware_id="PlateCarrier")
        star.add_plate(labware_definition=PLATE, carrier_id="PlateCarrier", site="1", plate_id=SOURCE_PLATE_ID)
        star.add_plate(labware_definition=PLATE, carrier_id="PlateCarrier", site="2", plate_id=DEST_PLATE_ID)

        star.instrument_init()

        # Diluent first, from the reservoir with one set of tips for the whole worklist (the
        # plate is still empty). The worklist supplies each well's volume; `volume` is only the
        # fallback for a row without one. The reservoir counts as one well, so every channel
        # gets a section of it.
        print(f"\nDispensing diluent into {len(diluent_worklist)} well(s)...")
        diluent_result = star.add_reagent(
            reagent_source=DILUENT_ID,
            dest_plate=DEST_PLATE_ID,
            volume=FINAL_VOLUME_UL,
            transfer_csv=str(diluent_csv),
            liquid_class=LIQUID_CLASS,
            tip_pool=TIP_POOL,
            reuse_tips=True,
            aspirate_settings=ASPIRATE_SETTINGS,
            dispense_settings=DISPENSE_SETTINGS,
        )
        print(f"  wells filled: {diluent_result.wells_filled}")

        # Then the samples, with a fresh tip for each one.
        print(f"Transferring {len(sample_worklist)} sample(s)...")
        sample_result = star.hit_picking(
            transfer_csv=sample_csv,
            liquid_class=LIQUID_CLASS,
            tip_pool=TIP_POOL,
            change_tips=True,
            aspirate_settings=ASPIRATE_SETTINGS,
            dispense_settings=DISPENSE_SETTINGS,
        )
        print(f"  transfers: {sample_result.total_wells_processed}")

except VenusTimeoutError as e:
    print(f"Command timed out: {e}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
