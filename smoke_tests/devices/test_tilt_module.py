"""Tilt Module smoke test (simulation): exercises the whole public surface and prints results.

Run:  python smoke_tests/devices/test_tilt_module.py
No hardware, no VENUS. Exits non-zero on the first failed check.
"""

from __future__ import annotations

from hamilton_venus import TiltModuleClient, TiltModuleError


def check(label: str, condition: bool) -> None:
    print(("PASS  " if condition else "FAIL  ") + label)
    if not condition:
        raise SystemExit(1)


def expect_error(label: str, call, code: int) -> None:
    try:
        call()
    except TiltModuleError as exc:
        print(f"      {label}: code {exc.error_code} -> {exc}")
        check(f"{label} raises code {code}", exc.error_code == code)
    else:
        check(f"{label} raises", False)


def main() -> None:
    with TiltModuleClient(simulate=True) as tilt:
        connected = tilt.tilt_module_connect(1, 3).return_parameters
        check("connect system 1 on COM3", (connected.system_id, connected.com_port) == (1, "COM3"))
        tilt.tilt_module_connect(2, 4)
        check("a second system on another port", True)

        tilt.tilt_module_initialize(1, "TM")
        tilt.tilt_module_initialize(2, "TM")  # same module name on a different system is fine
        check("initialize two modules", True)

        tilt.tilt_module_move_to_position(1, "TM", 10)
        tilt.tilt_module_move_to_position(2, "TM", 5)
        a = tilt.tilt_module_get_status(1, "TM").return_parameters
        b = tilt.tilt_module_get_status(2, "TM").return_parameters
        check("status tracks each module's angle", (a.angle, b.angle) == (10, 5))
        check(
            "status reports idle with no firmware error",
            (a.busy, a.error_code, a.error_message) == (False, 0, "No error."),
        )

        expect_error("angle 11", lambda: tilt.tilt_module_move_to_position(1, "TM", 11), 6)
        expect_error("system 5", lambda: tilt.tilt_module_connect(5, 3), 6)
        expect_error("move unknown module", lambda: tilt.tilt_module_move_to_position(1, "ZZ", 3), -4)
        expect_error("close with module up", lambda: tilt.tilt_module_terminate_communication(1), -6)

        for code in (0, 3, 6, -4, -8):
            print(f"      error {code:>3}: {tilt.tilt_module_error_message(code).return_parameters.message}")

        for system_id in (1, 2):
            tilt.tilt_module_terminate_module(system_id, "TM")
            tilt.tilt_module_terminate_communication(system_id)
        check("terminate both systems", True)

    print("tilt module smoke test OK")


if __name__ == "__main__":
    main()
