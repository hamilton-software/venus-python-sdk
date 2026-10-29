"""Smoke test: Hamilton Media Fill Module via MediaFillClient.

The Media Fill driver is pure Python and does not use the VENUS runtime -- there
is no ``StarClient``/``VantageClient`` involved at all. ``MediaFillClient`` is a
standalone client just for the ``media_fill_*`` methods, so this needs no running
VENUS. By default it exercises the built-in simulation transport end to end.

To drive the real module, run with ``--real --port COM5`` on a PC with the
Hamilton Media Fill Module library installed (check first with
``hamilton-media-fill --diagnose`` / ``--selftest``). A real run **fills the
pump's trough**, so only use it with the module plumbed and a trough in place.
"""

import argparse

from hamilton_venus import MediaFillClient, MediaFillError, VenusError
from hamilton_venus.media_fill import media_fill_com_diagnosis
from hamilton_venus.models import PumpDirection

parser = argparse.ArgumentParser()
parser.add_argument("--real", action="store_true", help="use the vendor COM driver instead of simulation")
parser.add_argument("--port", default="COM5", help="COM port of the module (real runs)")
parser.add_argument("--pump", type=int, default=1, help="pump 1-4")
parser.add_argument("--speed", type=int, default=50, help="relative speed, 30-100 %%")
parser.add_argument("--timeout", type=int, default=60, help="fill timeout in seconds")
args = parser.parse_args()

try:
    with MediaFillClient(simulate=not args.real) as mfm:
        print("--- Connect ---")
        rp = mfm.media_fill_connect(args.port).return_parameters
        print(f"  device {rp.device_id}: COM{rp.com_port} instrument={rp.instrument_id} "
              f"fw={rp.firmware_version} simulated={rp.simulated}")
        if args.real and rp.simulated:
            raise MediaFillError(
                "--real was requested but the vendor driver is not reachable, so the simulator "
                f"was used instead. {media_fill_com_diagnosis()}"
            )

        print("\n--- Device IDs ---")
        print(mfm.media_fill_get_device_ids().model_dump(by_alias=True))

        print("\n--- Pump direction ---")
        print(f"  pump {args.pump}: {mfm.media_fill_get_pump_direction(args.pump).return_parameters.direction_name}")
        mfm.media_fill_set_pump_direction(args.pump, PumpDirection.COUNTER_CLOCKWISE)

        print("\n--- Liquid level sensor ---")
        state = mfm.media_fill_get_liquid_level_sensor_state(args.pump).return_parameters.liquid_level_sensor_state
        print(f"  pump {args.pump}: state={state} (0 = no liquid; 1 = liquid, or sensor unplugged / controller off)")

        print("\n--- Fill trough, then wait for the pump ---")
        mfm.media_fill_fill_trough(args.pump, args.speed, args.timeout)
        mfm.media_fill_wait_for_pump(args.pump)
        state = mfm.media_fill_get_liquid_level_sensor_state(args.pump).return_parameters.liquid_level_sensor_state
        print(f"  pump {args.pump}: finished, sensor state={state}")

        print("\n--- Last error message ---")
        print(f"  {mfm.media_fill_get_last_error_message().return_parameters.error_message!r}")

        print("\n--- Terminate ---")
        print(f"  {mfm.media_fill_terminate().return_parameters.message}")

    print("\nMedia Fill Smoke Test Complete")
except MediaFillError as e:
    print(f"Media Fill error: {e}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"Other SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
