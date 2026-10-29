"""Smoke test for the STAR front cover commands.

``front_cover_is_locked()`` is Vantage only: the STAR hardware cannot report the
lock state, so the SDK must reject the call before sending the command. This
test verifies that the call raises ``VenusCommandUnsupportedError`` and that the
other front cover commands still work.
"""

import logging

from hamilton_venus import (
    StarClient,
    VenusCommandFailedError,
    VenusCommandUnsupportedError,
    VenusError,
    VenusTimeoutError,
)

try:
    with StarClient(simulate=True, logging_level=logging.INFO) as star:
        print("Connected - method is running")

        is_closed = star.front_cover_is_closed()
        print(f"Front cover is closed: {is_closed.return_parameters.is_closed}")

        print("Calling front_cover_is_locked() (expected to be rejected on STAR)...")
        try:
            star.front_cover_is_locked()
        except VenusCommandUnsupportedError as e:
            print(f"Rejected before sending, as expected: {e}")
        else:
            print("front_cover_is_locked() unexpectedly succeeded on STAR")
            raise SystemExit(1)

        star.front_cover_lock()
        print("Front cover locked")
        star.front_cover_unlock()
        print("Front cover unlocked")

        print("\nSTAR Front Cover Smoke Test Complete - Disconnecting")
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
