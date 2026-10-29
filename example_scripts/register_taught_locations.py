"""Record operator-taught position corrections for a VENUS method to enforce.

Writes ``<SDK install>\\Active Layout\\TaughtLocations.json`` -- a store of teach
points that a VENUS method reads back and applies at run time. Two kinds of record
share the file:

* ``register_taught_offset`` -- a relative ``dx/dy/dz`` (+ angle) correction keyed
  by ``"<carrier>/<site>"``. Use this when every labware placed on that site needs
  the same nudge.
* ``register_taught_position`` -- absolute ``x/y/z`` (+ angle) coordinates keyed by
  labware name **then** by ``"<carrier>/<site>"`` (a plate can be taught at more
  than one site). Use this to pin one specific plate.

Each ``register_*`` call is *latest wins*: it adds a new key or replaces the record
already under that key. VENUS is expected to look a plate up in
``labwarePositions[<plate>]["<carrier>/<site>"]`` first and fall back to
``carrierSiteOffsets["<carrier>/<site>"]`` -- ``resolve_taught_location`` mirrors
that order. ``labware``, ``carrier`` and ``site`` are stored lower-cased (fields
and keys alike), so casing on the way in does not matter.

These commands are local file I/O only: no instrument connection is needed and
nothing is sent to the VENUS runtime, so ``auto_connect=False`` is fine. Pass the
numbers from wherever you actually measured them (arm jog + read-back, a probe
routine, a metrology report, ...).
"""

from __future__ import annotations

from hamilton_venus import StarClient

# The carrier the teach points belong to, the two sites, and the plate pinned by
# absolute coordinates -- change these to match your deck.
CARRIER = "PlateCarrier1"
SITE_A = "1"
SITE_B = "2"
PLATE = "Plate1"

with StarClient(auto_connect=False) as star:
    # 1. A per-site offset: everything landed on CARRIER/SITE_A is 0.42 mm too far
    #    in X and 0.18 mm short in Y; drop it 0.10 mm.
    offset = star.register_taught_offset(
        CARRIER,
        SITE_A,
        dx=0.42,
        dy=-0.18,
        dz=-0.10,
        note="teach 2026-09-01 (arm jog read-back)",
    )
    print(f"carrierSiteOffsets[{CARRIER}/{SITE_A}] = "
          f"dx={offset.dx}, dy={offset.dy}, dz={offset.dz}")

    # 2. Absolute coordinates taught for one plate on two different sites. A plate
    #    position wins over the carrier/site offset whenever VENUS places PLATE.
    star.register_taught_position(PLATE, CARRIER, SITE_A, x=123.45, y=210.90, z=95.20)
    star.register_taught_position(PLATE, CARRIER, SITE_B, x=123.45, y=304.10, z=95.20)

    # Re-teaching the same plate + site just overwrites it -- the store keeps the latest.
    star.register_taught_position(PLATE, CARRIER, SITE_A, x=123.50, y=210.85, z=95.20)

    # Direct keyed lookups (no iteration).
    print("plate @ site A ->", star.get_taught_position(PLATE, CARRIER, SITE_A))
    print("all plate sites->", list(star.get_taught_positions(PLATE)))
    print("site A offset  ->", star.get_taught_offset(CARRIER, SITE_A))

    # Resolve the way VENUS will: plate-at-site first, then the carrier/site offset.
    pinned = star.resolve_taught_location(PLATE, CARRIER, SITE_A)
    other = star.resolve_taught_location("SomeOtherPlate", CARRIER, SITE_A)
    print(f"resolve {PLATE!r} @ {SITE_A}       -> {type(pinned).__name__}")
    print(f"resolve 'SomeOtherPlate' @ {SITE_A} -> {type(other).__name__} (fell back to the site offset)")

    # Inspect the whole store.
    doc = star.get_taught_locations()
    print("labware positions   :", {k: list(v) for k, v in doc.labware_positions.items()})
    print("carrier/site offsets:", list(doc.carrier_site_offsets))

    # Prune when a teach point is no longer valid.
    # star.remove_taught_position(PLATE, CARRIER, SITE_B)  # one site
    # star.remove_taught_position(PLATE)                   # every site for the plate
    # star.clear_taught_locations()                        # wipe both maps
