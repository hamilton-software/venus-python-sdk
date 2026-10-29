"""Smoke test: Inheco TEC controller via InhecoTECClient, simulation only.

The InhecoTEC driver is pure Python and does not use the VENUS runtime -- there
is no ``StarClient``/``VantageClient`` involved at all. ``InhecoTECClient`` is
a standalone client just for the ``inheco_tec_*`` methods, so -- unlike the
instrument smoke tests -- this one needs no running VENUS. It exercises the
built-in simulation transport end to end.

To try the real vendor COM transport, drop ``simulate=True`` on a machine with
the Inheco TEC driver installed. On 64-bit Python the SDK bridges through a
32-bit Python (bundled at ``hamilton_venus/_com32_py32``); check with
``hamilton-inheco-tec --diagnose`` / ``--selftest``.
"""

from hamilton_venus import InhecoTECClient, InhecoTECError, VenusError
from hamilton_venus.inheco_tec import SHAKER_CAPABLE_DEVICE_TYPES

try:
    tec = InhecoTECClient(simulate=True)
    controller_id = 0

    print("--- Connect ---")
    connected = tec.inheco_tec_connect(controller_id)
    params = connected.return_parameters
    print(f"controller_id={params.controller_id} type={params.controller_type_name}")
    for slot in params.devices:
        print(f"  slot {slot.device_id}: {slot.device_type_name}")
    # A CPAC (or similar) is temperature-only -- no shaker motor -- so the
    # shaker section below targets a separate, shaker-capable slot.
    device_id = next((s.device_id for s in params.devices if s.device_type not in (64, 128)), 1)
    shaker_device_id = next((s.device_id for s in params.devices if s.device_type in SHAKER_CAPABLE_DEVICE_TYPES), None)

    print("\n--- Identification ---")
    ident = tec.inheco_tec_get_identification(controller_id, device_id).return_parameters
    print(
        f"  device {device_id}: type={ident.device_type_name} sn={ident.serial_number} "
        f"runtime={ident.runtime_minutes} min calibrated={ident.calibration_date}"
    )

    print("\n--- Firmware / sensors ---")
    fw = tec.inheco_tec_get_firmware_version(controller_id).return_parameters
    print(f"  firmware[{fw.selector_name}]={fw.value}")
    sensor = tec.inheco_tec_get_sensor_values(controller_id, selector=2).return_parameters
    print(f"  sensor[{sensor.selector_name}]={sensor.value}")

    print("\n--- Reservoir ---")
    reservoir = tec.inheco_tec_get_reservoir_status(controller_id, device_id).return_parameters
    print(f"  reservoir={reservoir.status_name}")

    print("\n--- Chill to 8 C ---")
    tec.inheco_tec_set_target_temperature(controller_id, device_id, 8.0)
    tec.inheco_tec_start_temperature_control(controller_id, device_id)
    for _ in range(20):
        status = tec.inheco_tec_get_temperature_status(controller_id, device_id).return_parameters
        if abs(status.actual_temperature - status.target_temperature) < 0.5:
            break
    print(f"  actual={status.actual_temperature} C target={status.target_temperature} C heater={status.heater_status_name}")
    tec.inheco_tec_stop_temperature_control(controller_id, device_id)

    print("\n--- Shaker ---")
    if shaker_device_id is not None:
        tec.inheco_tec_set_shaker_shape(controller_id, shaker_device_id, 0)
        tec.inheco_tec_set_shaker_revolutions(controller_id, shaker_device_id, 600)
        tec.inheco_tec_start_shaker(controller_id, shaker_device_id)
        shaker = tec.inheco_tec_get_shaker_status(controller_id, shaker_device_id).return_parameters
        print(f"  slot {shaker_device_id}: status={shaker.status} revolutions={shaker.revolutions} shape={shaker.shape_name}")
        tec.inheco_tec_stop_shaker(controller_id, shaker_device_id)
    else:
        print("  no shaker-capable device in any slot -- skipped")

    print("\n--- Touchscreen / raw command ---")
    tec.inheco_tec_set_touchscreen(controller_id, False)
    raw = tec.inheco_tec_send_command(controller_id, "1RAT3").return_parameters
    print(f"  sent={raw.command!r} response={raw.response!r}")

    print("\n--- Terminate ---")
    print(f"  {tec.inheco_tec_terminate().return_parameters.message}")
    tec.close()

    print("\nInhecoTEC Smoke Test Complete")
except InhecoTECError as e:
    print(f"InhecoTEC error: {e}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"Other SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
