from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LIQUID_CLASSES

SOURCE_LIQUID_CLASS = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_50UL.WATER.JET_EMPTY.TIP_50UL_WATER_DISPENSEJET_EMPTY
NEW_LIQUID_CLASS = f"{SOURCE_LIQUID_CLASS}_Copy"

try:
    with StarClient(auto_connect=False, simulate=True) as star:
        print("Connected — method is running")

        print(f"\n--- Pull Liquid Class: {SOURCE_LIQUID_CLASS} ---")
        pull_result = star.pull_liquid_classes(names=[SOURCE_LIQUID_CLASS])
        print(f"Pull response: {pull_result.model_dump(by_alias=True)}")
        if not pull_result.success:
            raise SystemExit(1)

        print(f"\n--- Get Liquid Class: {SOURCE_LIQUID_CLASS} ---")
        get_result = star.get_liquid_class(name=SOURCE_LIQUID_CLASS)
        print(f"Definition: {get_result.model_dump(by_alias=True)}")
        if not get_result.success:
            raise SystemExit(1)

        source_definition = get_result.return_parameters.definition

        print(f"\n--- Copy Liquid Class: {SOURCE_LIQUID_CLASS} -> {NEW_LIQUID_CLASS} ---")
        new_definition = source_definition.model_copy(deep=True)
        new_definition.id = NEW_LIQUID_CLASS
        new_definition.is_user_defined = True

        update_result = star.update_liquid_class(definition=new_definition)
        print(f"Update response: {update_result.model_dump(by_alias=True)}")
        if not update_result.success:
            raise SystemExit(1)

        print(f"\n--- Push Liquid Class: {NEW_LIQUID_CLASS} ---")
        push_result = star.push_liquid_classes(names=[NEW_LIQUID_CLASS])
        print(f"Push response: {push_result.model_dump(by_alias=True)}")
        if not push_result.success:
            raise SystemExit(1)

        print("\nCopy Liquid Class Smoke Test Complete - Disconnecting")
except VenusTimeoutError as e:
    print(f"Command timed out: {e}")
    raise SystemExit(1) from e
except VenusCommandFailedError as e:
    print(f"Command failed: {e}")
    print(f"  Return code: {e.response.return_code}")
    print(f"  Details: {e.response.return_parameters}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"Other SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
