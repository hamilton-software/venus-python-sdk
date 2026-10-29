"""Split wells: several 1 mL channels pipetting side by side in one large well.

Runs against the simulator by default (``SIMULATE``). It checks, step by step:

1. ``split_wells`` on a 6-, 12- and 24-well Greiner plate makes 4 / 2 / 2 slots at 9 mm
   pitch, placed by VENUS (``labware.addSplitWellSite``) around the parent well: same X
   and Z, Y offsets of +-4.5 / +-13.5 mm, slot 1 at the back. Independently of the SDK's
   plan, every slot's tip (measured 1000 uL tip shape) must clear the well wall at the
   floor and at the opening, and sit on the well floor; this is checked again after the
   tilt and the move.
2. Aspirate / dispense with channels 1-4 on ``Plate6@A1`` are routed to the slots: the
   tracked volume lands in the split rack, not the parent well.
3. Five channels on a 4-slot well raise ``SplitWellCapacityError`` before anything is sent.
4. ``remove_split_wells(..., consolidate_volumes=True)`` adds the slot volumes back onto
   the parent well and removes the rack.
5. ``tilt_labware`` at 10 degrees aimed at the deepest point rebuilds the split with 2 slots
   at the deepest point; ``fit=SplitWellFit.MAX_CHANNELS`` keeps 4 slots by moving toward the centre.
6. Back to flat, a QCG move to another site rebuilds the split around the plate's new
   position.
7. ``remove_labware`` removes the plate's splits with it.

Exits non-zero if any check fails.
"""

from __future__ import annotations

import logging
import math
import sys

from hamilton_venus import SplitWellCapacityError, VantageClient, VenusCommandFailedError, VenusError
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import (
    AspirateSettings,
    DispenseSettings,
    QCGType,
    SplitChannelType,
    SplitWellFit,
    TiltWellPosition,
)
from hamilton_venus.models.enums import CapacitiveLLD, DispenseMode

SIMULATE = True

TIP_CARRIER_ID = "TipCarrier"
PLATE_CARRIER_ID = "PlateCarrier"
REAGENT_CARRIER_ID = "ReagentCarrier"
TIP_POOL = "Tips1000"
TROUGH_ID = "Trough"

PLATES = {  # plate id -> (definition, carrier site, expected 1 mL slots)
    "Plate6": (LABWARE.PLATE.GREINER_CULTURE_PLATE_6, "1", 4),
    "Plate12": (LABWARE.PLATE.GREINER_CULTURE_PLATE_12, "2", 2),
    "Plate24": (LABWARE.PLATE.GREINER_CULTURE_PLATE_24, "4", 2),
}
MOVE_SITE = "3"  # empty site the 6-well is moved to in step 6
GRIP_HEIGHT_MM = 8.0

CHANNELS = [1, 2, 3, 4]
VOLUME_UL = 100.0
LIQUID_CLASS = (
    LIQUID_CLASSES.VANTAGE.SYSTEM.CHANNELS_1000UL.TIP_1000UL.WATER.SURFACE_EMPTY.HIGHVOLUME_WATER_DISPENSESURFACE_EMPTY
)
ASPIRATE = AspirateSettings(capacitive_lld=CapacitiveLLD.OFF, fixed_height=2.0, liquid_following=False)
DISPENSE = DispenseSettings(dispense_mode=DispenseMode.FROM_LIQUID_CLASS, fixed_height=5.0, liquid_following=False)

TOLERANCE_MM = 0.05

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    print(f"   [{'PASS' if condition else 'FAIL'}] {message}")
    if not condition:
        failures.append(message)


def near(a: float | None, b: float | None, tolerance: float = TOLERANCE_MM) -> bool:
    return a is not None and b is not None and abs(a - b) <= tolerance


def well_xyz(client: VantageClient, labware: str, well: str) -> tuple[float, float, float]:
    coordinates = client.get_labware_coordinates(labware, well).return_parameters
    x, y, z = coordinates.x, coordinates.y, coordinates.z
    if x is None or y is None or z is None:
        raise RuntimeError(f"VENUS returned no coordinates for {labware} {well}")
    return x, y, z


def check_site_around_parent(client: VantageClient, site, label: str) -> None:
    """Every slot sits at the parent well's current position plus its planned offset."""
    px, py, pz = well_xyz(client, site.parent_labware, site.parent_well)
    for slot, placed in zip(site.plan.slots, site.coordinates, strict=True):
        ok = (
            placed.well == slot.well
            and near(placed.x, px + slot.dx)
            and near(placed.y, py + slot.dy)
            and near(placed.z, pz + slot.dz)
        )
        check(
            ok,
            f"{label} slot {slot.well}: placed ({placed.x:.2f}, {placed.y:.2f}, {placed.z:.2f}), "
            f"expected ({px + slot.dx:.2f}, {py + slot.dy:.2f}, {pz + slot.dz:.2f})",
        )


# Measured 1000 uL tip: outside diameter at the end and 19.8 mm above it.
TIP_END_DIAMETER_MM = 1.2
TIP_UPPER_DIAMETER_MM = 5.4
TIP_MEASURED_HEIGHT_MM = 19.8


def tip_radius(height_above_end: float) -> float:
    taper = (TIP_UPPER_DIAMETER_MM - TIP_END_DIAMETER_MM) / TIP_MEASURED_HEIGHT_MM
    return (TIP_END_DIAMETER_MM + taper * height_above_end) / 2.0


def well_dimensions(client: VantageClient, plate: str) -> tuple[float, float, float]:
    """(floor radius, opening radius, depth) of the plate's wells, read from its labware definition."""
    definition = client.labware_get_params_from_id(plate).return_parameters.definition
    container = next(iter(definition["containerGrids"].values()))["containerDefinition"]
    segments = container["volumeModel"]["segments"]
    bottom, top = segments[0], segments[-1]
    floor = bottom.get("diameterBottom") or bottom.get("diameter")
    opening = container["openingDimensions"].get("diameter") or top.get("diameterTop") or top.get("diameter")
    return floor / 2.0, opening / 2.0, container["totalDepth"]


def check_inside_well(client: VantageClient, site, label: str, tilt_degrees: int = 0, deepest: bool = False) -> None:
    """Independent of the SDK's plan: every slot's tip fits inside the well, and its Z is on the floor.

    The well centre is worked out from the parent well's VENUS position (where
    ``tilt_labware`` aimed it, ``get_tilt_settings(...).aim_x_shift``, when ``deepest``).
    Each slot's offset from it is turned into the tilted well's own frame, then the
    tip is checked against the wall at the floor (tip end) and at the opening (tip at full depth;
    a tilted well leans, so the tip's offset across it changes with height).
    """
    floor_r, open_r, depth = well_dimensions(client, site.parent_labware)
    px, py, pz = well_xyz(client, site.parent_labware, site.parent_well)
    theta = math.radians(tilt_degrees)
    settings = client.get_tilt_settings(site.parent_labware)
    shift = settings.aim_x_shift if deepest and tilt_degrees and settings else 0.0
    centre_x = px + shift * math.cos(theta)  # the low wall is toward -X
    for placed in site.coordinates:
        u = (centre_x - placed.x) / math.cos(theta)  # across the well, toward the low wall
        y = placed.y - py
        floor_gap = floor_r - (math.hypot(u, y) + tip_radius(0.0))
        top_u = u - depth * math.tan(theta)
        top_gap = open_r - (math.hypot(top_u, y) + tip_radius(depth))
        floor_z = pz + (shift - u) * math.sin(theta)
        check(
            floor_gap >= 0 and top_gap >= 0 and near(placed.z, floor_z),
            f"{label} slot {placed.well} inside the well: {math.hypot(u, y):.2f} mm from centre, "
            f"tip-to-wall {floor_gap:.2f} mm at the floor / {top_gap:.2f} mm at the opening, "
            f"z {placed.z:.2f} vs floor {floor_z:.2f}",
        )


def tracked_volumes(client: VantageClient, labware: str) -> dict[str, float | None]:
    details = client.get_labware_details(labware).return_parameters.labware
    return {well.id: well.volume for entry in details for well in entry.wells}


try:
    with VantageClient(simulate=SIMULATE, logging_level=logging.INFO) as vantage:
        vantage.add_carrier(LABWARE.CARRIER.TIP_CAR_480BC, left_track=11, labware_id=TIP_CARRIER_ID)
        vantage.add_carrier(LABWARE.CARRIER.PLT_CAR_L5_MTP, left_track=46, labware_id=PLATE_CARRIER_ID)
        vantage.add_carrier(LABWARE.CARRIER.RGT_CAR_5R60, left_track=59, labware_id=REAGENT_CARRIER_ID)
        vantage.add_tip_rack(
            labware_definition=LABWARE.TIP_RACK.TIP_RACK_1000UL,
            carrier_id=TIP_CARRIER_ID,
            site="1",
            tip_pool=TIP_POOL,
        )
        for plate_id, (definition, site, _) in PLATES.items():
            vantage.add_plate(labware_definition=definition, carrier_id=PLATE_CARRIER_ID, site=site, plate_id=plate_id)
        vantage.add_reservoir(LABWARE.RESERVOIR.RGT_CONT_60ML, REAGENT_CARRIER_ID, "1", labware_id=TROUGH_ID)
        vantage.add_qcg(qcg_type=QCGType.QCG)
        vantage.instrument_init()
        vantage.tip_pool_reset_tip_counter(TIP_POOL)
        vantage.tip_pool_initialize_tip_counter(TIP_POOL)
        print("Layout built")

        print("\n1. Split A1 of each plate")
        for plate_id, (_, _, expected) in PLATES.items():
            sites = vantage.split_wells(plate_id, "A1", channel_type=SplitChannelType.ONE_ML)
            check(len(sites) == 1, f"{plate_id}: one split site")
            if not sites:
                continue
            site = sites[0]
            check(site.slot_count == expected, f"{plate_id} A1: {site.slot_count} slots (expected {expected})")
            check(site.slot_wells == [str(n) for n in range(1, expected + 1)], f"{plate_id}: slots named 1..{expected}")
            check_site_around_parent(vantage, site, plate_id)
            check_inside_well(vantage, site, plate_id)
            ys = [c.y for c in site.coordinates]
            check(all(a > b for a, b in zip(ys, ys[1:])), f"{plate_id}: slot 1 at the back, numbered toward the front")

        print("\n2. Pipette into Plate6 A1 with 4 channels")
        vantage.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)
        vantage.aspirate(f"{TROUGH_ID}@all", channels=CHANNELS, volumes=VOLUME_UL, liquid_class=LIQUID_CLASS, settings=ASPIRATE)
        vantage.dispense("Plate6@A1", channels=CHANNELS, volumes=VOLUME_UL, settings=DISPENSE)
        split_id = vantage.get_split_wells("Plate6")[0].split_labware
        slot_volumes = tracked_volumes(vantage, split_id)
        print(f"   tracked in {split_id}: {slot_volumes}")
        check(
            all(near(slot_volumes.get(str(n)), VOLUME_UL, 0.5) for n in range(1, 5)),
            f"each of the 4 slots received {VOLUME_UL:.0f} uL",
        )
        parent_before = tracked_volumes(vantage, "Plate6@A1").get("A1") or 0.0

        print("\n3. Five channels on a 4-slot well")
        try:
            vantage.dispense("Plate6@A1", channels=[1, 2, 3, 4, 5], volumes=0.0, settings=DISPENSE)
            check(False, "SplitWellCapacityError raised")
        except SplitWellCapacityError as exc:
            check(True, f"SplitWellCapacityError raised: {exc}")
        vantage.tip_eject(channels=CHANNELS)

        print("\n4. Remove the split, consolidating volumes")
        removed = vantage.remove_split_wells("Plate6", consolidate_volumes=True)
        check(removed == [split_id], f"removed {removed}")
        parent_after = tracked_volumes(vantage, "Plate6@A1").get("A1") or 0.0
        check(
            near(parent_after, parent_before + 4 * VOLUME_UL, 0.5),
            f"Plate6 A1 tracked volume {parent_before:.1f} -> {parent_after:.1f} uL",
        )
        check(vantage.get_split_wells("Plate6") == [], "no split left on Plate6")

        print("\n5. Tilt Plate6 10 degrees at the deepest point")
        vantage.split_wells("Plate6", "A1")
        vantage.split_wells("Plate6", "A2", fit=SplitWellFit.MAX_CHANNELS)
        vantage.tilt_labware("Plate6", 10, well_position=TiltWellPosition.DEEPEST_POINT)
        tilted = {site.parent_well: site for site in vantage.get_split_wells("Plate6")}
        deepest, most = tilted.get("A1"), tilted.get("A2")
        # Aimed at the wall, 'position' is as many tips as fit, as close to the wall as they fit.
        check(deepest is not None and deepest.slot_count == 3, "A1 rebuilt with 3 slots at the deepest point")
        check(most is not None and most.slot_count == 3, "A2 (fit='max_channels') rebuilt with 3 slots")
        if deepest:
            check_site_around_parent(vantage, deepest, "tilted A1")
            check_inside_well(vantage, deepest, "tilted A1", tilt_degrees=10, deepest=True)
        if most:
            check(most.plan.slots[0].dx > 0, f"A2 pulled back from the low wall by {most.plan.slots[0].dx:.2f} mm in X")
            check_site_around_parent(vantage, most, "tilted A2")
            check_inside_well(vantage, most, "tilted A2", tilt_degrees=10, deepest=True)

        print("\n6. Flat again, then move Plate6 with the QCG")
        vantage.tilt_labware("Plate6", 0)
        flat = {site.parent_well: site for site in vantage.get_split_wells("Plate6")}
        check(all(site.slot_count == 4 for site in flat.values()), "back to 4 slots per well when flat")
        before_y = flat["A1"].coordinates[0].y if "A1" in flat else None
        vantage.core_transport("Plate6", PLATE_CARRIER_ID, MOVE_SITE, GRIP_HEIGHT_MM, eject_grip=True)
        moved = {site.parent_well: site for site in vantage.get_split_wells("Plate6")}
        check(set(moved) == {"A1", "A2"}, f"splits rebuilt after the move: {sorted(moved)}")
        for well, site in moved.items():
            check_site_around_parent(vantage, site, f"moved {well}")
            check_inside_well(vantage, site, f"moved {well}")
        if "A1" in moved and before_y is not None:
            check(not near(moved["A1"].coordinates[0].y, before_y, 1.0), "split A1 followed the plate to its new site")

        print("\n7. Remove Plate6")
        gone = [site.split_labware for site in vantage.get_split_wells("Plate6")]
        vantage.remove_labware("Plate6")
        check(vantage.get_split_wells("Plate6") == [], "registry cleared")
        for split in gone:
            try:
                vantage.get_labware_coordinates(split)
                check(False, f"{split} removed from the deck")
            except VenusCommandFailedError:
                check(True, f"{split} removed from the deck")

        vantage.remove_split_wells()
        print("\nVantage Split Wells Smoke Test Complete - Disconnecting")
except VenusCommandFailedError as e:
    print(f"Command failed: {e}")
    print(f"  Return code: {e.response.return_code}")
    print(f"  Details: {e.response.return_parameters}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"SDK error: {e}")
    raise SystemExit(1) from e

if failures:
    print(f"\n{len(failures)} check(s) failed:")
    for failure in failures:
        print(f"  - {failure}")
    sys.exit(1)
print("\nAll checks passed")
