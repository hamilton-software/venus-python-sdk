"""Hamilton Media Fill Module: connect, set the pump direction, fill a trough,
wait for it, check the liquid level sensor, release.

The Media Fill driver is pure Python and does not use the VENUS runtime -- there
is no ``StarClient``/``VantageClient`` involved at all. ``MediaFillClient`` is a
standalone client just for the ``media_fill_*`` methods. ``simulate=True``
selects the in-memory transport, so this runs with no hardware and no vendor
driver; set SIMULATE = False and COM_PORT to drive a real module.
"""

from __future__ import annotations

import logging

from hamilton_venus import MediaFillClient, MediaFillError
from hamilton_venus.models import PumpDirection

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("media_fill_fill_trough")

SIMULATE = True
COM_PORT = "COM5"  # the module's virtual COM port (Device Manager > Ports)
PUMP_ID = 1  # 1-4
SPEED = 50  # relative speed, 30-100 %
TIMEOUT_S = 60  # the pump stops after this many seconds if the sensor hasn't triggered


def main() -> int:
    with MediaFillClient(simulate=SIMULATE) as mfm:
        try:
            info = mfm.media_fill_connect(COM_PORT).return_parameters
        except MediaFillError as exc:
            logger.error("connect failed: %s", exc)
            return 1
        logger.info("module %d on COM%d, firmware %s", info.device_id, info.com_port, info.firmware_version)

        mfm.media_fill_set_pump_direction(PUMP_ID, PumpDirection.COUNTER_CLOCKWISE)
        mfm.media_fill_fill_trough(PUMP_ID, SPEED, TIMEOUT_S)  # returns once the pump has started
        mfm.media_fill_wait_for_pump(PUMP_ID)  # blocks until the sensor triggers or the timeout elapses

        state = mfm.media_fill_get_liquid_level_sensor_state(PUMP_ID).return_parameters.liquid_level_sensor_state
        if state != 1:
            logger.error("pump %d stopped (timeout?) but its liquid level sensor reads %d", PUMP_ID, state)
            return 1
        logger.info("trough on pump %d is full", PUMP_ID)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
