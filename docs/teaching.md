# Automated Teaching

Teach a plate's true position on the deck with a **teaching needle** and the 1 mL
channel's **Z-stall sensor**. The needle is lowered until it stalls on a surface, so
the instrument can feel the top of a well wall or the bottom of a well. Python drives
the search and does the arithmetic; the instrument does single moves and searches.

This is a port of the plate flow of the VENUS *Deck Teaching Method*.

## What you need

- A rack of teaching needles on the deck (a tip rack whose definition marks it as a
  teaching-needle rack).
- The plate on the deck in your layout, and the well you want to teach.
- Optionally the teaching channel set with `teaching_set_channel(n)`. The default
  comes from the instrument configuration and is restored on every connect.

All coordinates are **needle-tip coordinates in mm**.

## Quick start

```python
from hamilton_venus import StarClient, TeachingError

# "MyTeachingDeck" is a saved deck containing the needle rack, carrier
# "PltCar_1" and plate "Plate_1" on site 1; use your own names.
with StarClient(deck_name="MyTeachingDeck") as star:
    star.instrument_init()
    star.teaching_pickup_needle()
    try:
        result = star.teach_well("Plate_1", "D6", register=True, carrier="PltCar_1", site=1)
    except TeachingError as error:
        print(f"teach failed: {error} (wall {error.wall}, status {error.status})")
    else:
        print("center", result.center, "bottom", result.bottom_z)
        print("offset from the definition", result.offset)
    finally:
        star.teaching_eject_needle()
```

`VantageClient` has the same methods.

## How `teach_well` works

1. **Look up the well.** `teaching_get_labware_dimensions` gives the definition's
   well center, well bottom Z and depth. The well entrance (top of the well) is
   `bottom Z + depth`.
2. **Move over the well** at its entrance height, coming in at `traverse_z` (245 mm).
   With `move_to_well=False` it starts wherever the needle already is. The needle
   must then be inside the well at the entrance height.
3. **Find the walls.** Each wall search (`teaching.1mL.measureXY`) steps toward one
   wall by `step_distance`. At every step it probes down from the **safe height**
   (`entrance + safe_clearance`, above the labware) to the **minimum search Z**
   (`entrance - search_depth`, 2-3 mm inside the well):

   - If the needle reaches the minimum search Z, it is still over the well, so the
     search keeps stepping.
   - If it stalls above it, it has landed on the wall top. The search then steps back
     until the needle drops into the well again.

   That last in-well position is the wall coordinate, and the stall height is the
   wall-top (entrance) height. The walls are found in this order:

   | Search | Starts from | Gives |
   |---|---|---|
   | +X | the start position | X1 |
   | -X | `X1 - 0.75 * well width`, start Y | X2; **center X = (X1 + X2) / 2** |
   | +Y | center X, start Y | Y1 |
   | -Y | center X, `Y1 - 0.75 * well width` | Y2; **center Y = (Y1 + Y2) / 2** |

   The measured entrance height is the mean of the four wall-top stall heights. The
   needle's own radius cancels out, because both walls of an axis are measured the
   same way.
4. **Find the bottom.** `teaching.1mL.measureZHeight` searches down from the measured
   entrance to `bottom_search_margin` below the expected bottom. The stall height,
   plus `z_offset`, is the taught bottom.
5. **Lift** the needle to `traverse_z`. This also happens when a search fails.
6. **Compare** with the definition: `offset = taught - expected` for the X/Y center and
   the bottom Z, rounded to 0.1 mm.
7. **Register** (optional). With `register=True` it records the plate's corrected
   first position (`first position + offset`, e.g. A1) for the plate at
   `carrier`/`site` in `TaughtLocations.json`, using `register_taught_position`.
   VENUS reads a taught position as the coordinates of the labware's first position,
   not its origin. It applies it as a labware shift the next time the plate is added
   to that carrier site (see *Taught Location Commands* in the command reference:
   [STAR](star_commands.md#taught-location-commands), [Vantage](vantage_commands.md#taught-location-commands));
   a plate already on the deck does not move until it is added again. The file is
   cleared when a new session connects, so to keep the taught position, `deck_save`
   the deck and start later sessions with `deck_name=...`.

`teach_well` needs the instrument: the searches rely on the channel's Z-stall
feedback, which the simulator does not provide.

`teach_z_only=True` skips the wall searches and only finds the bottom at the start X/Y.

### Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `well` | first position | Well to teach, e.g. `"D6"`. A well near the plate center averages out small rotations. |
| `well_width` | from the definition | Well opening in mm, one value or `(x, y)`. It is also the farthest a wall search travels. |
| `step_distance` | 0.6 | Wall search step, 0.3-2.4 mm. Smaller is more precise but slower. |
| `safe_clearance` | 5.0 | How far above the entrance the needle travels between probes. |
| `search_depth` | 3.0 | How deep into the well each wall probe goes. |
| `bottom_search_margin` | 5.0 | How far below the expected bottom the bottom search may go. |
| `z_offset` | 0.0 | Correction added to the measured bottom (e.g. needle/stall offset for your instrument). |
| `traverse_z` | 245.0 | Height for moving to and away from the well. |

### Search results

Each search returns `status.code` (`TeachingMeasureStatus`):

| Code | Name | Meaning | `teach_well` |
|---|---|---|---|
| 0 | `NOT_FOUND` | No stall inside the search range. | Raises `TeachingError` |
| 1 | `FOUND` | The wall or bottom was found. | Continues |
| 2 | `FOUND_EARLY` | The needle stalled before the search height: something is higher than expected (labware taller or offset, an obstacle). | Raises `TeachingError` |

`TeachingError.wall` names the wall being searched (`"+X"`, ...), or is `None` for
the bottom search. `TeachingError.status` holds the search result.

## The single commands

Build your own teaching flow (reservoirs, tube racks, a calibration routine) from the
single commands. They are listed in the command reference under *Teaching Commands*
([STAR](star_commands.md), [Vantage](vantage_commands.md)). Their request and response
JSON is in [JSON Schemas — System](json_schemas_system.md#teaching). The arithmetic
helpers `wall_center`, `wall_search_heights`, `bottom_search_window` and
`well_widths_from_definition` are in `hamilton_venus.teaching`.
