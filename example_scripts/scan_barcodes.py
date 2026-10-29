"""Scan barcodes off a loaded plate and a loaded tube rack.

Builds a deck with a plate carrier (plate at site 1) and a sample tube
carrier, then loads each one through the autoload. Before loading, each
carrier is checked by name with ``autoload_get_carrier_sensor_status()`` --
for plate carriers the sensor's reported track doesn't necessarily line up
with the track the carrier was added on, so the carrier identity is matched
directly via ``CarrierSensorStatusItem.carrier`` rather than by track number.
If the sensor reports that carrier as already pushed in, it's unloaded first
so the load doesn't collide with stale deck state. Only the positions that
actually hold labware are scanned: site 1 for the plate, and the first
``TUBES_TO_SCAN`` positions for the tube rack.
"""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

PLATE_CARRIER = LABWARE.CARRIER.PLT_CAR_L5MD
PLATE = LABWARE.PLATE.COS_96_DW_1ML
SAMPLE_CARRIER = LABWARE.TUBE_RACK.SMP_CAR_32_12X100

PLATE_CARRIER_TRACK = 1
SAMPLE_CARRIER_TRACK = 8
PLATE_SITE = "1"
TUBES_TO_SCAN = 8


def unload_if_pushed_in(star: StarClient, carrier_id: str) -> None:
    """Unload *carrier_id* if the sensor reports it's currently pushed in.

    Matched by carrier name rather than track: a plate carrier's
    ``sensor_track`` doesn't reliably match the track it was added on.
    """
    status = star.autoload_get_carrier_sensor_status()
    for item in status.return_parameters.carrier_sensor_status:
        if item.carrier == carrier_id and item.status:
            print(f"{carrier_id}: already pushed in -- unloading before reload")
            star.autoload_unload_carrier_by_id(carrier_id)
            break


with StarClient(simulate=True) as star:
    star.add_carrier(labware_definition=PLATE_CARRIER, left_track=PLATE_CARRIER_TRACK, labware_id="PlateCarrier")
    star.add_plate(labware_definition=PLATE, carrier_id="PlateCarrier", site=PLATE_SITE, plate_id="Plate1")

    star.add_tube_carrier(labware_definition=SAMPLE_CARRIER, left_track=SAMPLE_CARRIER_TRACK, labware_id="TubeRack1")

    star.instrument_init()

    unload_if_pushed_in(star, "PlateCarrier")
    plate_result = star.autoload_load_carrier_by_id(
        "PlateCarrier",
        scan_positions=[int(PLATE_SITE)],
    )

    unload_if_pushed_in(star, "TubeRack1")
    tube_result = star.autoload_load_carrier_by_id(
        "TubeRack1",
        scan_positions=list(range(1, TUBES_TO_SCAN + 1)),
    )

    print(f"Plate carrier barcode: {plate_result.return_parameters.carrier_barcode or '(no read)'}")
    for entry in plate_result.return_parameters.barcode_returns:
        print(f"  site {entry.position}: {entry.barcode or '(no read)'}")

    print(f"Tube rack carrier barcode: {tube_result.return_parameters.carrier_barcode or '(no read)'}")
    for entry in tube_result.return_parameters.barcode_returns:
        print(f"  tube {entry.position}: {entry.barcode or '(no read)'}")

print("Done")
