from hamilton_venus import StarClient

with StarClient(auto_connect=False) as star:
    star.deck_load(previous=True)
    star.instrument_connect(initialize=False)
    print("Last-used deck layout loaded")

    carriers = star.get_added_carriers()
    print(f"Loaded carriers: {carriers}")
