"""Heater Cooler (HHC): connect, chill to 8 C, confirm, hold, and release.

The HHC driver is pure Python and does not use the VENUS runtime -- there is no
``StarClient``/``VantageClient`` involved at all. ``HeaterCoolerClient`` is a
standalone client just for the ``hhc_*`` methods. ``simulate=True`` selects the
in-memory transport, so this runs with no hardware and no vendor COM driver.
"""

from __future__ import annotations

import logging

from hamilton_venus import HeaterCoolerClient, HeaterCoolerError

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("hhc_incubate")

ADDRESS = "COM4"  # COM port / USB identifier of the HHC chain
TARGET_C = 8.0
HOLD_MINUTES = 5.0


def main() -> int:
    with HeaterCoolerClient(simulate=True) as hhc:
        try:
            connected = hhc.hhc_connect(ADDRESS)
        except HeaterCoolerError as exc:
            logger.error("connect failed: %s", exc)
            return 1

        for unit in connected.return_parameters.units:
            logger.info(
                "device %d: sn=%s fw=%s temp=%.1f C verified=%s",
                unit.device_id,
                unit.serial_number,
                unit.firmware_version,
                unit.temperature,
                unit.verification_date,
            )

        logger.info("ramping all units to %.1f C ...", TARGET_C)
        hhc.hhc_start_temp_control(target=TARGET_C, wait=True, timeout=1800)

        for row in hhc.hhc_get_status().return_parameters.device_ids:
            logger.info(
                "device %d now %.1f C (controlling=%s)",
                row.device_id,
                row.temperature,
                row.controlling,
            )

        logger.info("holding %.1f C for %.0f min ...", TARGET_C, HOLD_MINUTES)
        hhc.hhc_hold_temp_for_time(target=TARGET_C, minutes=HOLD_MINUTES)
        hhc.hhc_wait_for_temp_control()

        hhc.hhc_stop_temp_control()
        result = hhc.hhc_terminate()
        logger.info("%s", result.return_parameters.message)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
