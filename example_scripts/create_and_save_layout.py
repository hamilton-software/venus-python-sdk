"""Build a deck layout and save it for later reuse.

Adds a tip carrier (with a tip rack) and a plate carrier (with a plate),
then persists the layout under a name via ``deck_save`` so it can be
reloaded later with ``deck_load``.
"""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

DECK_NAME = "MyDeckLayout"

TIP_CARRIER = LABWARE.CARRIER.TIP_CAR_480BC
TIP_RACK = LABWARE.TIP_RACK.TIP_RACK_300UL
PLATE_CARRIER = LABWARE.CARRIER.PLT_CAR_L5MD
PLATE = LABWARE.PLATE.COS_96_DW_1ML
TIP_POOL = "300uLTips"

with StarClient(simulate=True) as star:
    star.add_carrier(labware_definition=TIP_CARRIER, left_track=1, labware_id="TipCarrier1")
    star.add_tip_rack(
        labware_definition=TIP_RACK,
        carrier_id="TipCarrier1",
        site="1",
        tip_pool=TIP_POOL,
    )

    star.add_carrier(labware_definition=PLATE_CARRIER, left_track=10, labware_id="PlateCarrier1")
    star.add_plate(
        labware_definition=PLATE,
        carrier_id="PlateCarrier1",
        site="1",
        plate_id="Plate1",
    )

    star.deck_save(deck_name=DECK_NAME, overwrite=True)
    print(f"Deck layout saved as {DECK_NAME!r}")
