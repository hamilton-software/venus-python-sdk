"""Inheco ODTC: connect, build a small PCR cycle in Python, run it, release.

The ODTC driver is pure Python and does not use the VENUS runtime -- there is no
``StarClient``/``VantageClient`` involved at all. ``ODTCClient`` is a standalone
client just for the ``odtc_*`` methods. ``simulate=True`` selects the in-memory
transport, so this runs with no hardware and no vendor COM driver.
"""

from __future__ import annotations

import logging

from hamilton_venus import ODTCClient, ODTCError
from hamilton_venus.odtc_protocol import ODTCProtocolBuilder, ODTCStep

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("odtc_pcr")

DEVICE_IP = "192.168.1.50"


def build_protocol() -> ODTCProtocolBuilder:
    builder = ODTCProtocolBuilder("DemoPCR", description="Quick demo cycle")
    builder.add_hold(95, 30, slope=2)  # initial denature
    builder.add_cycle(
        [
            ODTCStep(temperature=95, hold_seconds=10),  # denature
            ODTCStep(temperature=60, hold_seconds=10),  # anneal
            ODTCStep(temperature=72, hold_seconds=15),  # extend
        ],
        repeats=5,
    )
    builder.add_hold(72, 30)  # final extend
    builder.add_hold(8, 0)  # hold
    return builder


def main() -> int:
    with ODTCClient(simulate=True) as odtc:
        try:
            connected = odtc.odtc_connect(DEVICE_IP)
        except ODTCError as exc:
            logger.error("connect failed: %s", exc)
            return 1

        unit = connected.return_parameters.unit
        logger.info(
            "device %d: sn=%s fw=%s state=%s", unit.device_id, unit.serial_number, unit.firmware_version, unit.state
        )
        device_id = unit.device_id

        protocol = build_protocol().build()
        logger.info("uploading and running %r ...", protocol.method_name)
        result = odtc.odtc_run_protocol(protocol, device_id=device_id, wait=True, timeout=600)
        logger.info(
            "run complete: method=%s request_id=%s",
            result.return_parameters.method_name,
            result.return_parameters.request_id,
        )

        status = odtc.odtc_get_status(device_id=device_id).return_parameters.device_ids[0]
        temps = odtc.odtc_get_temperature(device_id=device_id).return_parameters.device_ids[0]
        logger.info(
            "device %d: state=%s block=%.1f C lid=%.1f C",
            device_id,
            status.state,
            temps.block_temperature,
            temps.lid_temperature,
        )

        for row in odtc.odtc_get_run_data(device_id=device_id).return_parameters.rows:
            logger.info("run data: %s", row)

        result = odtc.odtc_terminate_device(device_id=device_id)
        logger.info("%s", result.return_parameters.message)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
