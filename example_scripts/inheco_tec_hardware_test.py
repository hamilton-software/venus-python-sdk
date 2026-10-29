"""Inheco TEC hardware test: verify communication with a Single TEC (STC) box
driving a CPAC -- get device type, temperature get/set, shaker speed set.

Runs against **real hardware** (``InhecoTECClient()``, ``simulate=False`` is the
default). Edit ``CONTROLLER_ID`` / ``DEVICE_ID`` below if yours differ.

The temperature step actually drives the block: it sets a target, starts
temperature control, polls until reached (or a timeout), then stops control
-- with a ``finally`` so control is stopped even if something goes wrong
partway through. The shaker step, by contrast, only *writes a setpoint and
reads it back* -- it never calls ``inheco_tec_start_shaker``, so nothing
physically shakes.

- ``SetShakerRevolutions`` only writes a setpoint; a CPAC has no shaker motor
  at all (see ``hamilton_venus.inheco_tec.SHAKER_CAPABLE_DEVICE_TYPES``), so
  the real device may reject this outright -- that's still a useful
  communication check, so failure here is logged, not fatal.

Once you're ready to actually drive the block further, see
``example_scripts/inheco_tec_incubate.py`` (``simulate=True``) for the pattern.
"""

from __future__ import annotations

import logging
import time

from hamilton_venus import InhecoTECClient, InhecoTECError

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("inheco_tec_hardware_test")

CONTROLLER_ID = 0
DEVICE_ID = 1  # the CPAC's slot on the controller
TEST_SHAKER_RPM = 500

TEMP_TARGET_C = 10.0
TEMP_TOLERANCE_C = 0.5
TEMP_POLL_SECONDS = 5
TEMP_TIMEOUT_S = 600  # give up waiting after 10 min either way


def main() -> int:
    with InhecoTECClient() as tec:  # simulate=False (default) -- talks to real hardware
        try:
            connected = tec.inheco_tec_connect(CONTROLLER_ID)
        except InhecoTECError as exc:
            logger.error("connect failed: %s", exc)
            return 1

        params = connected.return_parameters
        logger.info("controller_id=%d is a %s", params.controller_id, params.controller_type_name)
        for slot in params.devices:
            logger.info("  slot %d: %s", slot.device_id, slot.device_type_name)

        logger.info("--- Get device type (slot %d) ---", DEVICE_ID)
        try:
            ident = tec.inheco_tec_get_identification(CONTROLLER_ID, DEVICE_ID).return_parameters
            logger.info(
                "slot %d: type=%s sn=%s runtime=%d min calibrated=%s",
                DEVICE_ID,
                ident.device_type_name,
                ident.serial_number,
                ident.runtime_minutes,
                ident.calibration_date,
            )
        except InhecoTECError as exc:
            logger.error("get identification failed: %s", exc)

        logger.info("--- Temperature get/set (slot %d) ---", DEVICE_ID)
        try:
            before = tec.inheco_tec_get_temperature_status(CONTROLLER_ID, DEVICE_ID).return_parameters
            logger.info(
                "actual=%.1f C target=%.1f C limits=(%.1f, %.1f) heater=%s",
                before.actual_temperature,
                before.target_temperature,
                before.temperature_min,
                before.temperature_max,
                before.heater_status_name,
            )

            logger.info("setting target temperature to %.1f C and starting temperature control ...", TEMP_TARGET_C)
            tec.inheco_tec_set_target_temperature(CONTROLLER_ID, DEVICE_ID, TEMP_TARGET_C)
            tec.inheco_tec_start_temperature_control(CONTROLLER_ID, DEVICE_ID)

            try:
                reached = False
                elapsed = 0
                while elapsed < TEMP_TIMEOUT_S:
                    time.sleep(TEMP_POLL_SECONDS)
                    elapsed += TEMP_POLL_SECONDS
                    status = tec.inheco_tec_get_temperature_status(CONTROLLER_ID, DEVICE_ID).return_parameters
                    logger.info(
                        "  t+%ds: actual=%.1f C target=%.1f C heater=%s",
                        elapsed,
                        status.actual_temperature,
                        status.target_temperature,
                        status.heater_status_name,
                    )
                    if abs(status.actual_temperature - TEMP_TARGET_C) <= TEMP_TOLERANCE_C:
                        reached = True
                        break

                if reached:
                    logger.info("target reached after %ds", elapsed)
                else:
                    logger.warning("target not reached within %ds timeout", TEMP_TIMEOUT_S)
            finally:
                # Always stop control, whether or not the target was reached
                # (or an exception interrupted the wait) -- never leave the
                # CPAC actively driving toward a setpoint unattended.
                logger.info("stopping temperature control")
                tec.inheco_tec_stop_temperature_control(CONTROLLER_ID, DEVICE_ID)
        except InhecoTECError as exc:
            logger.error("temperature get/set failed: %s", exc)

        logger.info("--- Shaker speed set (slot %d, NOT starting the shaker) ---", DEVICE_ID)
        try:
            tec.inheco_tec_set_shaker_revolutions(CONTROLLER_ID, DEVICE_ID, TEST_SHAKER_RPM)
            shaker = tec.inheco_tec_get_shaker_status(CONTROLLER_ID, DEVICE_ID).return_parameters
            logger.info(
                "read back revolutions=%d shape=%s (status=%s; inheco_tec_start_shaker was NOT called)",
                shaker.revolutions,
                shaker.shape_name,
                shaker.status,
            )
        except InhecoTECError as exc:
            logger.warning("shaker revolutions set/read failed (expected on a non-shaker CPAC): %s", exc)

        logger.info("--- Terminate ---")
        # Temperature control was already stopped above (in its own finally
        # block); stop_all_devices=True here is just defense in depth in case
        # that call itself failed.
        result = tec.inheco_tec_terminate(stop_all_devices=True)
        logger.info("%s", result.return_parameters.message)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
