"""Import the NGS STAR MOA deck layout and save it as a generic named deck.

Imports the Illumina DNA Prep "NGS STAR MOA" alternative deck layout
(``DNAPrep_MOA.lay``) with ``deck_import``, then persists the resulting deck
under the generic name ``NGS_STAR_MOA`` via ``deck_save`` so later scripts can
reload it with ``star.deck_load("NGS_STAR_MOA")`` -- no ``.lay`` path needed.

``deck_import`` modifies the live deck and the SDK's carrier tracking, so the
instrument must be connected first (lifecycle step 4). Set ``SIMULATE`` to
False to run against the real instrument.
"""

from __future__ import annotations

from pathlib import Path

from hamilton_venus import StarClient

LAY_PATH = Path(
    r"C:\Program Files (x86)\Hamilton\NGSStar\Illumina\DNAPrep\Methods"
    r"\Alternative deck layouts\NGS STAR MOA\DNAPrep_MOA.lay"
)
DECK_NAME = "NGS_STAR_MOA"
SIMULATE = True

if not LAY_PATH.is_file():
    raise SystemExit(f"Layout file not found: {LAY_PATH}")

with StarClient(simulate=SIMULATE, auto_connect=False) as star:
    star.instrument_connect(initialize=False)

    result = star.deck_import(path=str(LAY_PATH))

    imported = result.return_parameters.carriers_added
    print(f"Imported {len(imported)} carrier(s) from {LAY_PATH.name!r}:")
    for carrier in imported:
        print(f"  {carrier.labware_name} (track {carrier.left_track})")

    star.deck_save(deck_name=DECK_NAME, overwrite=True)
    print(f"Deck layout saved as {DECK_NAME!r}")
