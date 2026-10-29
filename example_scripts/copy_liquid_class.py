"""Copy a liquid class definition and push the copy to the instrument database.

Fetches an existing liquid class definition, duplicates it under a new name,
forces ``isUserDefined`` to ``True`` on the copy (required since only
user-defined liquid classes can be created/edited), writes it back via
``update_liquid_class``, and then persists it to the instrument's liquid
class database via ``push_liquid_classes``.
"""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

# Example source/target names -- change these to the liquid class you want to copy.
SOURCE_LIQUID_CLASS = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_50UL.WATER.JET_EMPTY.TIP_50UL_WATER_DISPENSEJET_EMPTY
NEW_LIQUID_CLASS = f"{SOURCE_LIQUID_CLASS}_Copy"

with StarClient(auto_connect=False) as star:
    pull_result = star.pull_liquid_classes(names=[SOURCE_LIQUID_CLASS])
    if not pull_result.success:
        raise RuntimeError(f"Failed to pull liquid class {SOURCE_LIQUID_CLASS!r} from the database: {pull_result}")

    get_result = star.get_liquid_class(name=SOURCE_LIQUID_CLASS)
    if not get_result.success:
        raise RuntimeError(f"Failed to fetch liquid class {SOURCE_LIQUID_CLASS!r}: {get_result}")

    source_definition = get_result.return_parameters.definition

    new_definition = source_definition.model_copy(deep=True)
    new_definition.id = NEW_LIQUID_CLASS
    new_definition.is_user_defined = True

    update_result = star.update_liquid_class(definition=new_definition)
    if not update_result.success:
        raise RuntimeError(f"Failed to create liquid class {NEW_LIQUID_CLASS!r}: {update_result}")

    push_result = star.push_liquid_classes(names=[NEW_LIQUID_CLASS])
    if not push_result.success:
        raise RuntimeError(f"Failed to push liquid class {NEW_LIQUID_CLASS!r} to the database: {push_result}")

    print(f"Copied {SOURCE_LIQUID_CLASS!r} -> {NEW_LIQUID_CLASS!r} and pushed it to the database.")
