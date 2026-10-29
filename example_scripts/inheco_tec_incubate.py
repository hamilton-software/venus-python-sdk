"""Inheco TEC controller: connect, chill a CPAC slot, shake a Thermoshake slot, release.

The InhecoTEC driver is pure Python and does not use the VENUS runtime -- there
is no ``StarClient``/``VantageClient`` involved at all. ``InhecoTECClient`` is a
standalone client just for the ``inheco_tec_*`` methods. ``simulate=True``
selects the in-memory transport, so this runs with no hardware and no vendor
COM driver.

Addressing is two-level: ``controller_id`` (0-7) picks the physical controller
box, ``device_id`` (1-6) picks a slot on it (0 addresses the controller unit
itself). Not every slot can do everything -- a CPAC, Heat_PAC, Heated_Lid, ...
is a temperature-only block with no shaker motor; only a Thermoshake/Teleshake
(and their AC variants) actually shake. The vendor library itself never checks
this before sending a shaker command (the physical device rejects an
inapplicable one), so this script picks the right slot for each operation
itself, the way a real setup would -- see
``hamilton_venus.inheco_tec.SHAKER_CAPABLE_DEVICE_TYPES``.
"""

from __future__ import annotations

import logging

from hamilton_venus import InhecoTECClient, InhecoTECError
from hamilton_venus.inheco_tec import SHAKER_CAPABLE_DEVICE_TYPES

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("inheco_tec_incubate")

CONTROLLER_ID = 0
TARGET_C = 8.0
SHAKER_RPM = 500


def main() -> int:
    with InhecoTECClient(simulate=True) as tec:
        try:
            connected = tec.inheco_tec_connect(CONTROLLER_ID)
        except InhecoTECError as exc:
            logger.error("connect failed: %s", exc)
            return 1
        
        params = connected.return_parameters
        logger.info("controller_id=%d is a %s", params.controller_id, params.controller_type_name)
        for slot in params.devices:
            logger.info("  slot %d: %s", slot.device_id, slot.device_type_name)

        # Pick a temperature-only slot for the chill demo and a separate,
        # shaker-capable slot for the shake demo -- never the same slot
        # unless it happens to be both (e.g. a Thermoshake_AC).
        temp_slot = next((s.device_id for s in params.devices if s.device_type not in (64, 128)), None)
        shaker_slot = next((s.device_id for s in params.devices if s.device_type in SHAKER_CAPABLE_DEVICE_TYPES), None)

        if temp_slot is not None:
            ident = tec.inheco_tec_get_identification(CONTROLLER_ID, temp_slot).return_parameters
            logger.info(
                "slot %d: %s sn=%s runtime=%d min calibrated=%s",
                temp_slot,
                ident.device_type_name,
                ident.serial_number,
                ident.runtime_minutes,
                ident.calibration_date,
            )

            logger.info("setting target temperature to %.1f C on slot %d ...", TARGET_C, temp_slot)
            tec.inheco_tec_set_target_temperature(CONTROLLER_ID, temp_slot, TARGET_C)
            tec.inheco_tec_start_temperature_control(CONTROLLER_ID, temp_slot)

            status = tec.inheco_tec_get_temperature_status(CONTROLLER_ID, temp_slot).return_parameters
            logger.info(
                "actual=%.1f C target=%.1f C heater=%s",
                status.actual_temperature,
                status.target_temperature,
                status.heater_status_name,
            )

            tec.inheco_tec_stop_temperature_control(CONTROLLER_ID, temp_slot)
        else:
            logger.info("no device in a slot -- skipping the temperature demo")

        if shaker_slot is not None:
            logger.info("shaking at %d rpm on slot %d ...", SHAKER_RPM, shaker_slot)
            tec.inheco_tec_set_shaker_revolutions(CONTROLLER_ID, shaker_slot, SHAKER_RPM)
            tec.inheco_tec_start_shaker(CONTROLLER_ID, shaker_slot)
            shaker = tec.inheco_tec_get_shaker_status(CONTROLLER_ID, shaker_slot).return_parameters
            logger.info(
                "shaker status=%s revolutions=%d shape=%s", shaker.status, shaker.revolutions, shaker.shape_name
            )
            tec.inheco_tec_stop_shaker(CONTROLLER_ID, shaker_slot)
        else:
            logger.info("no shaker-capable device in any slot -- skipping the shaker demo")

        result = tec.inheco_tec_terminate()
        logger.info("%s", result.return_parameters.message)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
