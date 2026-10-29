"""Query saved deck layouts, let the user pick one, and load it.

Connects without auto-loading any deck, lists the saved layout names via
``deck_get_saved``, shows a tkinter dialog for the user to pick one, then
loads the selected layout via ``deck_load``. See ``create_and_save_layout.py``
for how a layout gets saved under a name.

Run through Script Manager, the picker renders as one of its formatted
modals (via the non-standard ``simpledialog.askchoice`` that its runner
injects). Run directly (``python load_saved_layout.py``), it falls back to a
plain Tk ``Listbox`` window -- ``askchoice`` isn't part of real tkinter.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog

from hamilton_venus import StarClient


def select_deck_layout(root: tk.Tk, options: list[str]) -> str | None:
    """Show a modal single-select dialog and return the chosen name, or None if cancelled."""
    # Script Manager's runner injects simpledialog.askchoice (a formatted
    # list-picker modal); plain tkinter has no such function, so feature-detect
    # and fall back to a hand-rolled Listbox window when running standalone.
    askchoice = getattr(simpledialog, "askchoice", None)
    if askchoice is not None:
        return askchoice(
            "Load Deck Layout",
            "Select a saved deck layout to load:",
            options,
            initialvalue=options[0] if options else None,
        )

    dialog = tk.Toplevel(root)
    dialog.title("Load Deck Layout")

    if root.winfo_viewable():
        dialog.transient(root)
    dialog.lift()
    dialog.focus_force()

    tk.Label(dialog, text="Select a saved deck layout to load:").pack(padx=10, pady=(10, 5))

    listbox = tk.Listbox(dialog, height=min(len(options), 10), exportselection=False)
    for name in options:
        listbox.insert(tk.END, name)
    listbox.selection_set(0)
    listbox.pack(padx=10, pady=5, fill="both", expand=True)

    selected: list[str | None] = [None]

    def on_ok() -> None:
        selection = listbox.curselection()
        if selection:
            selected[0] = listbox.get(selection[0])
        dialog.destroy()

    def on_cancel() -> None:
        dialog.destroy()

    listbox.bind("<Double-Button-1>", lambda _event: on_ok())
    dialog.protocol("WM_DELETE_WINDOW", on_cancel)

    button_frame = tk.Frame(dialog)
    button_frame.pack(padx=10, pady=(0, 10))
    tk.Button(button_frame, text="Load", command=on_ok, width=10).pack(side="left", padx=5)
    tk.Button(button_frame, text="Cancel", command=on_cancel, width=10).pack(side="left", padx=5)

    dialog.wait_visibility()
    dialog.grab_set()
    dialog.wait_window()
    return selected[0]


root = tk.Tk()
root.withdraw()

with StarClient(auto_connect=False) as star:
    saved = star.deck_get_saved()
    layout_names = saved.return_parameters.saved_decks

    if not layout_names:
        messagebox.showwarning("No Saved Layouts", "No saved deck layouts were found.")
        root.destroy()
        raise SystemExit(0)

    selected_layout = select_deck_layout(root, layout_names)
    root.destroy()

    if selected_layout is None:
        print("No layout selected. Exiting.")
        raise SystemExit(0)

    star.deck_load(deck_name=selected_layout)
    star.instrument_connect(initialize=False)
    print(f"Deck layout {selected_layout!r} loaded")

    carriers = star.get_added_carriers()
    print(f"Loaded carriers: {carriers.return_parameters.carriers_added}")
