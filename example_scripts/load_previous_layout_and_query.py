"""Load the last-used deck layout and query its carriers and plates.

Reloads whatever layout was active last (``deck_load(previous=True)``),
connects to the instrument runtime, then reports what's on the deck via
``get_added_carriers``/``get_added_plates``.
"""

from hamilton_venus import StarClient

with StarClient(auto_connect=False) as star:
    star.deck_load(previous=True)
    star.instrument_connect(initialize=False)
    print("Last-used deck layout loaded")

    carriers = star.get_added_carriers()
    plates = star.get_added_plates()

    print(f"Carriers ({carriers.return_parameters.total_carriers}): {carriers.return_parameters.carriers_added}")
    print(f"Plates ({plates.return_parameters.total_plates}): {plates.return_parameters.plates_added}")
