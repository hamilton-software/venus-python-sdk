"""Load a DWP carrier on track 20, unload it, then load it again.

Builds a deck with a plate carrier on track 20 holding a deep-well plate
(DWP), then exercises the autoload sequence by carrier id: load, unload,
load. Before each load, ``autoload_get_carrier_sensor_status()`` is checked
so a stale "already pushed in" carrier doesn't collide with the load.
"""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

DWP_CARRIER = LABWARE.CARRIER.PLT_CAR_L5_DWP
DWP_PLATE = LABWARE.PLATE.COS_96_DW_1ML

CARRIER_TRACK = 20
CARRIER_ID = "DwpCarrier"
PLATE_SITE = "1"


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


with StarClient(simulate=False) as star:
    star.add_carrier(labware_definition=DWP_CARRIER, left_track=CARRIER_TRACK, labware_id=CARRIER_ID)
    star.add_plate(labware_definition=DWP_PLATE, carrier_id=CARRIER_ID, site=PLATE_SITE, plate_id="DwpPlate1")

    star.instrument_init()

    # Load
    load_by_id(star, CARRIER_ID)

    # Unload
    star.autoload_unload_carrier_by_id(CARRIER_ID)
    print(f"Unloaded {CARRIER_ID!r}")
    post_unload_status = star.autoload_get_carrier_sensor_status()
    print(f"Sensor status after unload: {post_unload_status.return_parameters.carrier_sensor_status}")

    # Load again
    load_by_id(star, CARRIER_ID)

print("Done")