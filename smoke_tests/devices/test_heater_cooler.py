"""Smoke test: Heater Cooler (HHC) via HeaterCoolerClient, simulation only.

The HHC driver is pure Python and does not use the VENUS runtime -- there is no
``StarClient``/``VantageClient`` involved at all. ``HeaterCoolerClient`` is a
standalone client just for the ``hhc_*`` methods, so -- unlike the instrument
smoke tests -- this one needs no running VENUS. It exercises the built-in
simulation transport end to end.

To try the real vendor COM transport, drop ``simulate=True`` on a machine with
the Hamilton HeaterCooler driver installed. On 64-bit Python the SDK bridges
through a 32-bit Python (bundled at ``hamilton_venus/_com32_py32``); check with
``hamilton-hhc --diagnose`` / ``--selftest``.
"""

from hamilton_venus import HeaterCoolerClient, HeaterCoolerError, VenusError

try:
    hhc = HeaterCoolerClient(simulate=True)

    print("--- HHC Connect ---")
    connected = hhc.hhc_connect("COM4")
    units = connected.return_parameters.units
    print(f"Chain {connected.return_parameters.chain_id}, {len(units)} unit(s)")
    for unit in units:
        print(
            f"  device {unit.device_id}: sn={unit.serial_number} "
            f"fw={unit.firmware_version} temp={unit.temperature} C "
            f"verified={unit.verification_date}"
        )
    device_id = units[0].device_id

    print("\n--- Device IDs ---")
    print(hhc.hhc_get_device_ids().model_dump(by_alias=True))

    print("\n--- Chill to 8 C ---")
    hhc.hhc_start_temp_control(target=8.0, wait=True, device_id=device_id)
    row = hhc.hhc_get_status(device_id=device_id).return_parameters.device_ids[0]
    print(f"  device {row.device_id}: {row.temperature} C, controlling={row.controlling}")

    print("\n--- Heat to 40 C ---")
    hhc.hhc_start_temp_control(target=40.0, device_id=device_id)
    hhc.hhc_wait_for_temp_control(device_id=device_id)
    row = hhc.hhc_get_status(device_id=device_id).return_parameters.device_ids[0]
    print(f"  device {row.device_id}: {row.temperature} C")

    print("\n--- Hold 40 C for 1 min ---")
    hhc.hhc_hold_temp_for_time(target=40.0, minutes=1.0, device_id=device_id)
    hhc.hhc_wait_for_temp_control(device_id=device_id)

    print("\n--- Display / identify / diagnostic ---")
    hhc.hhc_identify(device_id=device_id)
    hhc.hhc_set_display(on=True, brightness=50, device_id=device_id)
    diag = hhc.hhc_self_diagnostic(enable=True, device_id=device_id)
    print(f"  self-diagnostic: {diag.return_parameters.device_ids[0].enabled}")

    print("\n--- Stop + Terminate ---")
    hhc.hhc_stop_temp_control(device_id=device_id)
    print(f"  {hhc.hhc_terminate().return_parameters.message}")
    hhc.close()

    print("\nHHC Smoke Test Complete")
except HeaterCoolerError as e:
    print(f"HeaterCooler error: {e}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"Other SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
