"""Browse to a VENUS ``.lay`` deck layout file and import it.

Shows a file-open dialog filtered to ``.lay`` files, then imports the chosen
layout with ``deck_import``. ``deck_import`` takes every carrier defined in
the ``.lay`` file, places it on the current (blank) deck, and registers each
one in the SDK's built-in carrier tracking -- so right after the import,
``get_added_carriers()`` lists them and later pipetting steps can address
them by name.

For every imported carrier the script then queries the live deck for its
coordinates (``get_labware_coordinates`` -> x/y/z/angle) and its carrier/site
location (``get_labware_location``) and traces them to the terminal.

Because it modifies the live deck and its tracking, ``deck_import`` is a
post-connect operation (lifecycle step 4): the instrument must already be
connected when you call it. That is the key difference from
``load_saved_layout.py``, which uses ``deck_load`` to load a layout saved
*by name* inside VENUS and can run *before* connecting.

Run through Script Manager, the file dialog renders as its built-in file
browser. Run directly (``python import_layout_file.py``), it's the native
OS open dialog. Either way, cancelling returns an empty string.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from hamilton_venus import StarClient

root = tk.Tk()
root.withdraw()

# askopenfilename returns "" (not None) when the dialog is cancelled -- see
# tkinter_dialog_example.py. The Script Manager relay narrows a multi-entry
# filetypes list to its first pattern, so keep ".lay" first.
lay_path = filedialog.askopenfilename(
    title="Select a VENUS deck layout to import",
    filetypes=[("VENUS layout files", "*.lay"), ("All files", "*.*")],
)

if not lay_path:
    print("No layout file selected. Exiting.")
    raise SystemExit(0)

if not Path(lay_path).is_file():
    messagebox.showerror("File Not Found", f"No such file:\n{lay_path}")
    root.destroy()
    raise SystemExit(1)

root.destroy()

with StarClient(auto_connect=False) as star:
    # deck_import adds carriers to the live deck AND to the built-in carrier
    # tracking, which the runtime only allows once the instrument is connected
    # (lifecycle step 4). Connect first -- unlike deck_load(), this cannot run
    # against a not-yet-connected client.
    star.instrument_connect(initialize=False)

    result = star.deck_import(path=lay_path)

    imported = result.return_parameters.carriers_added
    print(f"Imported {len(imported)} carrier(s) from {lay_path!r}:")

    for carrier in imported:
        name = carrier.labware_name

        # deck_import's own response echoes the placement it read from the
        # file; re-query the live deck for the authoritative coordinates and
        # the carrier/site location now that the carrier is actually on it.
        try:
            coords = star.get_labware_coordinates(name).return_parameters
            loc = star.get_labware_location(name).return_parameters
        except Exception as exc:  # keep tracing the remaining carriers
            print(f"  {name}: could not query position ({exc})")
            continue

        if loc.carrier or loc.site:
            location = f"carrier={loc.carrier!r} site={loc.site!r}"
        else:
            # A top-level carrier sits on deck tracks, not on another
            # carrier/site -- fall back to the track from the import response.
            location = f"deck track {carrier.left_track}"

        print(
            f"  {name}: x={coords.x:.1f} y={coords.y:.1f} z={coords.z:.1f} "
            f"angle={coords.angle:.1f}  ({location})"
        )

    # The imported carriers are now in the SDK's built-in tracking -- every
    # one is reported here, alongside anything already on the deck.
    tracked = star.get_added_carriers()
    print(f"Carriers now tracked on the deck: {tracked.return_parameters.carriers_added}")
