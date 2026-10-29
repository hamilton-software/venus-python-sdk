"""Aspirate from a reagent trough and report the detected liquid level.

Builds a minimal deck (tip carrier + reagent carrier with a trough), picks up
a tip, and aspirates with capacitive LLD enabled. Capacitive/pressure LLD
must be turned on for the aspirate to return a real measured liquid level --
with LLD off, ``liquid_level_mm``/``liquid_volume_ul`` in the response just
echo back the static ``fixed_height`` fallback instead of an actual reading.
"""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings
from hamilton_venus.models.enums import CapacitiveLLD

TIP_CARRIER = LABWARE.CARRIER.TIP_CAR_480BC
REAGENT_CARRIER = LABWARE.CARRIER.RGT_CAR_5R60
TIP_RACK = LABWARE.TIP_RACK.TIP_RACK_300UL
TROUGH = LABWARE.RESERVOIR.RGT_CONT_60ML
TIP_POOL = "300uLTips"

CHANNELS = [1, 2, 3, 4]
ASPIRATE_VOLUME = 100.0
LIQUID_CLASS = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.SURFACE_EMPTY.STANDARDVOLUME_WATER_DISPENSESURFACE_EMPTY

aspirate_settings = AspirateSettings(
    capacitive_lld=CapacitiveLLD.MAX,
    submerge_depth=2.0,
    liquid_following=True,
)

with StarClient(simulate=True) as star:
    star.add_carrier(labware_definition=TIP_CARRIER, left_track=1, labware_id="TipCarrier")
    star.add_carrier(labware_definition=REAGENT_CARRIER, left_track=7, labware_id="ReagentCarrier")
    star.add_tip_rack(
        labware_definition=TIP_RACK,
        carrier_id="TipCarrier",
        site="1",
        tip_pool=TIP_POOL,
    )
    star.add_reservoir(
        labware_definition=TROUGH,
        carrier_id="ReagentCarrier",
        site="1",
        labware_id="Trough",
    )
    star.instrument_init()

    star.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)

    result = star.aspirate(
        "Trough@1",
        channels=CHANNELS,
        volumes=ASPIRATE_VOLUME,
        liquid_class=LIQUID_CLASS,
        settings=aspirate_settings,
    )

    print("Liquid level after aspirating from the trough:")
    for channel in result.return_parameters.channels:
        print(
            f"  channel {channel.channel}: "
            f"level={channel.liquid_level_mm:.2f} mm, "
            f"volume aspirated={channel.aspirated_volume:.1f} uL, "
            f"volume remaining={channel.liquid_volume_ul:.1f} uL"
        )

    star.tip_eject(channels=CHANNELS, tip_pool=TIP_POOL)

print("Done")
