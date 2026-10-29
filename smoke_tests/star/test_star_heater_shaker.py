from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError

try:
    with StarClient(simulate=True) as star:
        print("Connected — method is running")

        star.instrument_init()
        print("Initialization complete")

        print("\n--- HHS Device Registration ---")
        created = star.hhs_create_usb_device(node=1)
        device_id = created.return_parameters.device_id
        print(f"Created HHS device with id: {device_id}")

        device_ids = star.hhs_get_device_ids()
        print(f"Registered HHS devices: {device_ids.model_dump(by_alias=True)}")

        print("\n--- Plate Lock ---")
        star.hhs_set_plate_lock(lock=True, device_id=device_id)
        print("Plate locked")

        star.hhs_set_plate_lock(lock=False, device_id=device_id)
        print("Plate unlocked")

        print("\n--- Shaker ---")
        started = star.hhs_start_shaker(speed=1000, time=2, device_id=device_id)
        print(f"Shaker started: {started.return_parameters.shaking_started}")

        finished = star.hhs_wait_for_shaker(device_id=device_id)
        print(f"Shaker finished: {finished.return_parameters.shaking_stopped}")

        print("\n--- Temperature Control ---")
        temp_started = star.hhs_start_temp_control(temperature=25.0, device_id=device_id)
        print(f"Temp control started: {temp_started.return_parameters.temp_control_started}")

        temp_stopped = star.hhs_stop_temp_control(device_id=device_id)
        print(f"Temp control stop requested: {temp_stopped.return_parameters.temp_control_stopped}")

        temp_finished = star.hhs_wait_for_temp_control(device_id=device_id)
        print(f"Temp control finished: {temp_finished.return_parameters.temp_control_stopped}")

        star.hhs_set_plate_lock(lock=False, device_id=device_id)
        print("Plate unlocked")

        print("\n--- Status ---")
        status = star.hhs_get_status()
        print(f"HHS status: {status.model_dump(by_alias=True)}")

        print("\n--- Terminate ---")
        terminated = star.hhs_terminate()
        print(f"Terminate: {terminated.return_parameters.message}")

        print("\nHHS Smoke Test Complete - Disconnecting")
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
