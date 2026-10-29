"""Smoke test: Inheco ODTC via ODTCClient, simulation only.

The ODTC driver is pure Python and does not use the VENUS runtime -- there is no
``StarClient``/``VantageClient`` involved at all. ``ODTCClient`` is a standalone
client just for the ``odtc_*`` methods, so -- unlike the instrument smoke tests
-- this one needs no running VENUS. It exercises the built-in simulation
transport end to end.

To try the real vendor COM transport, drop ``simulate=True`` on a machine with
the Inheco ODTC driver installed. On 64-bit Python the SDK bridges through a
32-bit Python (bundled at ``hamilton_venus/_com32_py32``, shared with the
Heater Cooler driver); check with ``hamilton-odtc --diagnose`` / ``--selftest``.
"""

from hamilton_venus import ODTCClient, ODTCError, VenusError
from hamilton_venus.odtc_protocol import ODTCProtocolBuilder, ODTCStep


def _write_sample_protocol_file() -> str:
    import os
    import tempfile

    fd, path = tempfile.mkstemp(prefix="odtc_smoke_", suffix=".xml")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(
            '<?xml version="1.0" encoding="utf-8"?><MethodSet>'
            '<PreMethod methodName="Warm25" creator="smoke" dateTime="2026-01-01T00:00:00">'
            "<TargetBlockTemperature>25</TargetBlockTemperature>"
            "<TargetLidTemp>105</TargetLidTemp>"
            "</PreMethod></MethodSet>"
        )
    return path


try:
    odtc = ODTCClient(simulate=True)

    print("--- ODTC Connect ---")
    connected = odtc.odtc_connect("192.168.1.50")
    unit = connected.return_parameters.unit
    print(
        f"  device {unit.device_id}: sn={unit.serial_number} fw={unit.firmware_version} "
        f"state={unit.state}"
    )
    device_id = unit.device_id

    print("\n--- Device IDs ---")
    print(odtc.odtc_get_device_ids().model_dump(by_alias=True))

    print("\n--- Device Identification ---")
    print(odtc.odtc_get_device_identification(device_id).model_dump(by_alias=True))

    print("\n--- Build + Run a Small PCR Cycle ---")
    builder = ODTCProtocolBuilder("SmokeTestPCR")
    builder.add_hold(95, 5, slope=2)
    builder.add_cycle(
        [ODTCStep(temperature=95, hold_seconds=2), ODTCStep(temperature=60, hold_seconds=2)],
        repeats=3,
    )
    result = odtc.odtc_run_protocol(builder.build(), device_id=device_id, wait=True, timeout=120)
    print(f"  ran {result.return_parameters.method_name!r}, request_id={result.return_parameters.request_id}")

    print("\n--- Status / Temperature ---")
    row = odtc.odtc_get_status(device_id=device_id).return_parameters.device_ids[0]
    print(f"  device {row.device_id}: state={row.state} locked={row.locked} door_open={row.door_open}")
    temps = odtc.odtc_get_temperature(device_id=device_id).return_parameters.device_ids[0]
    print(f"  block={temps.block_temperature} C lid={temps.lid_temperature} C")

    print("\n--- Run Data ---")
    rows = odtc.odtc_get_run_data(device_id=device_id).return_parameters.rows
    print(f"  {len(rows)} row(s), last={rows[-1] if rows else None}")

    print("\n--- Door / Admin ---")
    odtc.odtc_open_door(device_id=device_id)
    odtc.odtc_close_door(device_id=device_id)
    odtc.odtc_set_log_level("INFO", device_id=device_id)

    print("\n--- Run a Vendor-Authored Protocol File ---")
    result2 = odtc.odtc_run_protocol(
        _write_sample_protocol_file(),
        method_name="Warm25",
        device_id=device_id,
        wait=True,
    )
    print(f"  ran {result2.return_parameters.method_name!r}")

    print("\n--- Terminate ---")
    print(f"  {odtc.odtc_terminate_device(device_id=device_id).return_parameters.message}")
    print(f"  {odtc.odtc_terminate().return_parameters.message}")
    odtc.close()

    print("\nODTC Smoke Test Complete")
except ODTCError as e:
    print(f"ODTC error: {e}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"Other SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
