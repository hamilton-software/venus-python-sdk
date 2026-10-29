"""End-to-end demo of the daisy-chained ambient Tilt Module driver.

Runs entirely against the simulation transport, so it needs no hardware and no
serial port. Mirrors the HSL library's own example method (InitializeComm ->
Initialize module -> move to 10 deg -> step down to 0 -> terminate).

Run:  python "example_scripts/tilt_module_demo.py"
"""

from __future__ import annotations

import logging

from hamilton_venus import TiltModuleClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

SYSTEM_ID = 1
COM_PORT = 4  # -> "COM4" on real hardware
MODULE = "A1"


def main() -> None:
    with TiltModuleClient(simulate=True) as tilt:
        tilt.tilt_module_connect(SYSTEM_ID, COM_PORT)
        tilt.tilt_module_initialize(SYSTEM_ID, MODULE)

        # Tilt fully up, then step back down to horizontal (1 deg per step).
        tilt.tilt_module_move_to_position(SYSTEM_ID, MODULE, 10)
        for angle in range(9, -1, -1):
            tilt.tilt_module_move_to_position(SYSTEM_ID, MODULE, angle)
            status = tilt.tilt_module_get_status(SYSTEM_ID, MODULE)
            print(f"  module {MODULE} now at {status.return_parameters.angle} deg")

        tilt.tilt_module_terminate_module(SYSTEM_ID, MODULE)
        tilt.tilt_module_terminate_communication(SYSTEM_ID)

    print("Demo complete.")


if __name__ == "__main__":
    main()
