# Custom Labware

Guide for importing non-catalog labware — adding new definitions programmatically, importing from VENUS `.lay` files, and mounting rack files as sites on existing labware.

---

## Overview

This guide covers:
- Adding and managing labware definitions via the API
- Importing a full deck layout from a `.lay` file
- Querying racks inside a `.lay` file before importing
- Mounting a rack from a `.lay` file as a site on an existing labware

---

## Labware Definitions

### Add a New Definition

Register a custom labware definition with the instrument runtime. The definition can be supplied as a `LabwareDefinition` model or a raw dict. VENUS takes the labware category from the definition's own `labwareClass`:

```python
from hamilton_venus import StarClient
from hamilton_venus.models.labware_definition import LabwareDefinition

my_definition = LabwareDefinition(
	# populate with your labware geometry
)

with StarClient() as star:
	star.labware_definition_add_definition(
		labware_name="MyCustomPlate",
		labware_definition=my_definition,
	)
	print("Custom labware definition registered")
```

> To build the definition itself from dimensions (plates, reservoirs and tubes), see [`labware_builder.md`](./labware_builder.md).

> **Replacing a definition:** register a corrected or new definition under a **new name** (for example `MyCustomPlate_v2`), then use that name. A definition added under the name of one already loaded is not loaded, and the old one stays in use.

### List Available Definitions

```python
from hamilton_venus import StarClient

with StarClient() as star:
	# All definitions: a dict mapping labware type -> list of definition names
	all_defs = star.labware_definition_get_definitions()
	print(all_defs.return_parameters.labware)

	# Filtered by labware type
	filtered = star.labware_definition_get_definitions(filter=["plate", "carrier"])
	print(filtered.return_parameters.labware)
```

### Get a Single Definition

```python
from hamilton_venus import StarClient

with StarClient() as star:
	result = star.labware_definition_get_definition("MyCustomPlate")
	print(result.return_parameters.definition)
```

### Import a VENUS Labware File

Convert an existing VENUS labware file (`.rck`, ...) into an SDK definition. VENUS works out the labware type from the file, stores the definition under `Labware\User\<type>\`, and returns it:

```python
from hamilton_venus import StarClient

with StarClient() as star:
	result = star.labware_definition_import_definition(
		r"C:\Program Files (x86)\HAMILTON\Labware\Corning-Costar\Cos_96_Rd.rck",
		labware_name="Cos_96_Rd_Imported",  # optional: defaults to the file name
	)
	definition = result.return_parameters.definition
	print(result.return_parameters.models)
```

The 3D models VENUS uses (`.x` and `.hxx`) are converted to glTF (`.gltf` + `.bin`) in the registered SDK folder's `Labware\Models`, where the SDK's own definitions keep theirs, and the stored definition is updated to refer to them:

- **Where the models come from:** each model file is looked for next to the imported file, then anywhere under VENUS's Labware folder.
- **The converter:** the Labware Converter's model converter does the conversion (`LabwareConverter\ModelConverter\Hamilton.ModelConversion.Cli.exe`, installed with **Set up VENUS SDK**). Set `HAMILTON_MODEL_CONVERTER` to use another copy.
- **The report:** `result.return_parameters.models` lists the models it converted, found already converted, could not find, or could not convert. Pass `convert_models=False` to skip the step.

A definition that replaces another needs a new name (see [Replacing a definition](#add-a-new-definition)).

### Update an Existing Definition

```python
from hamilton_venus import StarClient
from hamilton_venus.models.labware_definition import LabwareDefinition

updated = LabwareDefinition(
	# updated geometry
)

with StarClient() as star:
	star.labware_definition_update_definition(
		labware_name="MyCustomPlate",
		labware_definition=updated,
	)
	print("Definition updated")
```

### Delete a Definition

```python
from hamilton_venus import StarClient

with StarClient() as star:
	star.labware_definition_delete_definition("MyCustomPlate")
	print("Definition removed")
```

---

## Importing from a VENUS `.lay` File

### Import a Full Deck Layout

`deck_import()` reads a `.lay` file and, for every carrier it defines, places that carrier on the current (blank) deck **and** registers it in the SDK's built-in carrier tracking. After the call, `get_added_carriers()` lists the imported carriers and later steps can address them by name. `deck_import()` returns the carriers it added:

```python
from hamilton_venus import StarClient

with StarClient(auto_connect=False) as star:
	# deck_import modifies the live deck and its tracking, so the instrument
	# must be connected and initialized first -- it is a lifecycle step 5
	# operation, unlike deck_load() (step 2), which loads a saved-by-name
	# layout before connect. (Steps are listed in getting_started.md, "Startup Flow".)
	star.instrument_connect(initialize=False)
	star.instrument_init()

	result = star.deck_import(path=r"C:\Venus\Methods\MyDeck.lay")

	for carrier in result.return_parameters.carriers_added:
		# Re-query the live deck for each imported carrier's coordinates and
		# its carrier/site location.
		# (no well given, so the coordinates are the carrier's origin)
		coords = star.get_labware_coordinates(carrier.labware_name).return_parameters.origin
		loc = star.get_labware_location(carrier.labware_name).return_parameters
		print(
			f"Added: {carrier.labware_name} "
			f"x={coords.x:.1f} y={coords.y:.1f} z={coords.z:.1f} angle={coords.angle:.1f} "
			f"(carrier={loc.carrier!r} site={loc.site!r})"
		)

	# The imported carriers are now in the built-in tracking:
	print(star.get_added_carriers().return_parameters.carriers_added)
```

> The lifecycle steps are described in [Startup Flow (7-Step Lifecycle)](../getting_started.md#startup-flow-7-step-lifecycle). With `with StarClient() as star:` (the default `auto_connect=True`) the client connects on context entry, so you only need to call `instrument_init()` before importing. The explicit `instrument_connect()` above just makes the ordering clear.

### Query Racks in a `.lay` File Before Importing

Inspect the racks inside a `.lay` file without modifying the current deck:

```python
from hamilton_venus import StarClient

with StarClient() as star:
	result = star.deck_get_rack_ids_from_deck(
		path=r"C:\Venus\Methods\MyDeck.lay",
		only_floating_racks=True,   # restrict to racks not mounted on a carrier
	)

	for rack_id, info in result.return_parameters.racks_found.items():
		print(f"Rack '{rack_id}': file={info.file}, x={info.x}, y={info.y}")
```

### Mount a Rack as a Site

`deck_import_rack_as_site()` reads a specific rack from a `.lay` file and registers it as a named site on an existing labware in the current layout. This is useful for non-standard plate positions. The target labware (`MyCarrier1` below) must already be on the deck, for example added with `add_carrier()` or `deck_import()`:

```python
from hamilton_venus import StarClient

with StarClient() as star:
	result = star.deck_import_rack_as_site(
		path=r"C:\Venus\Methods\CustomRack.lay",
		target_labware_name="MyCarrier1",
		site_name="CustomSite1",
	)
	print(f"Site added: {result.return_parameters.site_added}")
```

---

## Production Pattern: Register and Validate Custom Labware

Check whether a custom definition already exists before attempting to add it, and validate it is accessible afterward:

```python
import logging
from hamilton_venus import StarClient
from hamilton_venus.models.labware_definition import LabwareDefinition

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def ensure_labware_definition(
	star: StarClient,
	labware_name: str,
	definition: LabwareDefinition,
) -> bool:
	"""
	Register a labware definition if it is not already present.

	Returns True if the definition is available after this call.
	"""
	existing = star.labware_definition_get_definitions()
	already_registered = any(
		labware_name in names for names in existing.return_parameters.labware.values()
	)

	if already_registered:
		logger.info("Definition '%s' already registered — skipping", labware_name)
		return True

	try:
		star.labware_definition_add_definition(labware_name, definition)
		logger.info("Registered new definition: %s", labware_name)
		return True
	except Exception as e:
		logger.error("Failed to register '%s': %s", labware_name, e)
		return False


with StarClient() as star:
	my_def = LabwareDefinition()  # populate with actual geometry
	if not ensure_labware_definition(star, "MyCustomPlate", my_def):
		raise RuntimeError("Required labware definition unavailable")

	# Now safe to use MyCustomPlate in add_plate() calls
	print("Labware definition ready")
```

---

## Production Pattern: Import and Verify a `.lay` File

```python
import logging
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)


def import_and_verify_deck(star: StarClient, lay_path: str, expected_carriers: list[str]) -> bool:
	"""
	Import a deck layout file and verify all expected carriers were added.

	Call this only after the instrument is connected and initialized --
	deck_import() adds the carriers to the live deck and its built-in
	tracking (lifecycle step 5).

	Args:
		lay_path: Path to the VENUS .lay file.
		expected_carriers: List of labware names that must be present after import.

	Returns:
		True if all expected carriers were imported.
	"""
	result = star.deck_import(path=lay_path)
	added_names = [c.labware_name for c in result.return_parameters.carriers_added]

	logger.info("Imported %d carriers from %s", len(added_names), lay_path)

	missing = [name for name in expected_carriers if name not in added_names]
	if missing:
		logger.error("Expected carriers not found in import: %s", missing)
		return False

	logger.info("All expected carriers imported successfully")
	return True


with StarClient() as star:
	star.instrument_init()

	if not import_and_verify_deck(
		star,
		lay_path=r"C:\Venus\Methods\ProductionDeck.lay",
		expected_carriers=["PlateCarrier1", "TipCarrier1"],
	):
		raise RuntimeError("Deck import incomplete — check .lay file")

	print("Deck ready")
```

---

## API Reference

### Labware Definition Management

| Method | Returns | Description |
|--------|---------|-------------|
| `labware_definition_add_definition(labware_name, labware_definition)` | `CommandResponse` | Register a new definition |
| `labware_definition_update_definition(labware_name, labware_definition)` | `CommandResponse` | Update an existing definition |
| `labware_definition_delete_definition(labware_name)` | `CommandResponse` | Remove a definition |
| `labware_definition_get_definitions(filter=None)` | `LabwareDefinitionDefinitionsResponse` | List definition names grouped by labware type (`.return_parameters.labware`), optionally filtered by type |
| `labware_definition_get_definition(labware_name)` | `LabwareDefinitionSingleResponse` | Get a single definition by name |
| `labware_definition_get_params_from_id(labware_name)` | `LabwareDefinitionSingleResponse` | Get definition for a labware instance by ID |

### Deck File Import

| Method | Returns | Key response field | Description |
|--------|---------|-------------------|-------------|
| `deck_import(path)` | `DeckImportResponse` | `.return_parameters.carriers_added` | Import every carrier from a `.lay` file onto the current deck and into built-in tracking. **Requires the instrument to be connected and initialized** ([lifecycle](../getting_started.md#startup-flow-7-step-lifecycle) step 5). |
| `deck_get_rack_ids_from_deck(path, carrier_filter=None, only_floating_racks=None)` | `DeckGetRackIdsFromDeckResponse` | `.return_parameters.racks_found` | Query racks in a `.lay` file without importing |
| `deck_import_rack_as_site(path, target_labware_name, carrier_filter=None, only_floating_racks=None, site_name=None)` | `DeckImportRackAsSiteResponse` | `.return_parameters.site_added` | Mount a rack from a `.lay` file as a site |

**`DeckImportCarrier` fields** (each element of `carriers_added`):

| Field | Type | Description |
|-------|------|-------------|
| `labware_name` | `str` | Name of the added carrier |
| `left_track` | `int \| None` | Leftmost deck track the carrier occupies |
| `x`, `y`, `z` | `float \| None` | Absolute position on the deck |
| `angle` | `float \| None` | Rotation angle |

---

## See Also

- [`labware_builder.md`](./labware_builder.md) — Building plate, reservoir, and tube definitions from scratch
- [`position_and_well_selection.md`](../position_and_well_selection.md) — `LabwareDefinition` parsing and `from_definition()`
- [`deck_and_layout.md`](../deck_and_layout.md) — `add_carrier()`, `add_plate()` with catalog labware
- [`deck_persistence.md`](./deck_persistence.md) — Saving and reloading complete deck configurations
