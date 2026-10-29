"""Clone an existing labware definition under a new name with a different height.

Reads the definition with ``labware_get_definition``, changes the overall labware
height (``dimensions.z``), and registers the result with ``labware_add_definition``.

Also calls ``labware_update_definition`` twice: on the read-only source (expected to
fail) and on the new user-defined clone (expected to succeed).

Finally sends invalid definitions (a required key removed, or nonsense JSON) to both
``labware_add_definition`` and ``labware_update_definition``; schema validation is
expected to reject every one.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from hamilton_venus import StarClient
from hamilton_venus.exceptions import VenusCommandFailedError

SOURCE_NAME = "Cos_96_DW_1mL"
NEW_NAME = "Cos_96_DW_1mL_Tall"
NEW_HEIGHT_MM = 45.0
UPDATED_HEIGHT_MM = 46.0
INVALID_NAME = "Cos_96_DW_1mL_Invalid"
REQUIRED_KEYS = ["labwareClass", "dimensions", "containerGrids"]
NONSENSE_DEFINITION = {"foo": "bar", "numbers": [1, 2, 3], "nested": {"not": "labware"}}


def expect_rejected(label: str, command: Callable[[], Any]) -> None:
    """Run *command*, which VENUS is expected to reject, and report the outcome."""
    try:
        command()
    except VenusCommandFailedError as error:
        print(f"{label} rejected as expected: {error}")
    else:
        print(f"WARNING: {label} succeeded")


with StarClient(simulate=True,auto_connect=False) as star:
    response = star.labware_get_definition(SOURCE_NAME)
    # The raw dict is edited (not the typed model) so every field VENUS sent is passed back unchanged.
    definition = copy.deepcopy(response.return_parameters.definition)
    print(f"Read {SOURCE_NAME}: height {definition['dimensions']['z']} mm")

    # The source is a system (read-only) definition, so updating it is expected to fail -- even
    # with the unchanged definition that was just read.
    expect_rejected(
        f"Update of read-only {SOURCE_NAME}",
        lambda: star.labware_update_definition(SOURCE_NAME, response.return_parameters.definition),
    )

    # Only the outer height changes; the wells (containerGrids) keep their depth and base offset.
    definition["dimensions"]["z"] = NEW_HEIGHT_MM
    definition["id"] = f"hamilton:{NEW_NAME.lower()}"
    definition["displayName"] = NEW_NAME

    # labware_name is sent as "labwareDefinition": the name of the new file, which must be unique
    # (add fails if it already exists -- delete it or use labware_update_definition to rerun).
    # labware_definition is sent as "definition": the full JSON object the new labware is created from.
    # VENUS marks the new definition as user defined and picks the writer from its labwareClass.
    result = star.labware_add_definition(
        labware_name=NEW_NAME,
        labware_definition=definition,
    )
    print(f"Add result: {result}")

    added = star.labware_get_definition(NEW_NAME).return_parameters.definition
    print(f"Read {NEW_NAME}: height {added['dimensions']['z']} mm")

    # The clone is user defined (not read-only), so updating it should succeed.
    updated_definition = copy.deepcopy(added)
    updated_definition["dimensions"]["z"] = UPDATED_HEIGHT_MM
    result = star.labware_update_definition(NEW_NAME, updated_definition)
    print(f"Update result: {result}")

    updated = star.labware_get_definition(NEW_NAME).return_parameters.definition
    print(f"Read {NEW_NAME}: height {updated['dimensions']['z']} mm")

    # Invalid definitions: the valid clone with one required key removed, plus nonsense JSON.
    invalid_definitions: dict[str, dict[str, Any]] = {}
    for key in REQUIRED_KEYS:
        invalid_definitions[f"missing {key}"] = {k: v for k, v in updated.items() if k != key}
    invalid_definitions["nonsense JSON"] = NONSENSE_DEFINITION

    for description, invalid in invalid_definitions.items():
        # INVALID_NAME is unused, so the add can only fail on validation.
        expect_rejected(
            f"Add with {description}",
            lambda invalid=invalid: star.labware_add_definition(
                labware_name=INVALID_NAME,
                labware_definition=invalid
            ),
        )
        # NEW_NAME exists and is not read-only, so the update can only fail on validation.
        expect_rejected(
            f"Update with {description}",
            lambda invalid=invalid: star.labware_update_definition(NEW_NAME, invalid),
        )

    final = star.labware_get_definition(NEW_NAME).return_parameters.definition
    print(f"{NEW_NAME} unchanged by rejected updates: {final == updated}")

print("Done")
