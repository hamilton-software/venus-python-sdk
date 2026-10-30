"""MFX Tilt Module hardware check -- runs against a REAL module.

Run this when setting up a module. It walks up from "can we talk to it" to "does it
move and report sanely", stopping at the first failure, and writes a full serial
trace to ``tilt_module_hardware_test.log`` (include it when contacting support; see
``docs/tilt_module_hardware_notes.md``).

    python "example_scripts/tilt_module_hardware_test.py" COM3 [MODULE ...] [--baud N] [--parity E|N|O]

With no module names it first asks the single module on the bus for its name using the
``99`` broadcast (valid only when exactly one module is connected). If nothing answers,
run ``hamilton-tilt-module --scan COM3`` (read-only) to look for working serial settings.

SAFETY: remove liquid and any lidded/loose labware first. The script tilts the module
through 0 -> 3 -> 10 -> 0 degrees; keep hands clear of the hinge and the lifted edge.
Nothing here pipettes. Press Ctrl+C to abort -- the ``with`` block returns the module to
horizontal and powers the motor off.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from hamilton_venus import TiltModuleClient, TiltModuleError
from hamilton_venus.tilt_module import (
    BAUD_RATE,
    BROADCAST_ID,
    DEFAULT_PARITY,
    TiltModuleTransport,
    _Win32SerialLink,
    normalize_port,
)

logger = logging.getLogger("tilt_module_hardware_test")

SYSTEM_ID = 1
ANGLES = (3, 10, 0)
LOG_FILE = "tilt_module_hardware_test.log"


def _configure_logging() -> None:
    """Full DEBUG trace (every serial line) to LOG_FILE; INFO progress to the console."""
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(message)s", filename=LOG_FILE)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)


def _discover_module(port: str, baud: int, parity: str) -> str:
    """Name of the single module on the bus (``99RF``)."""
    transport = TiltModuleTransport(_Win32SerialLink(baudrate=baud, parity=parity))
    try:
        transport.open(normalize_port(port))
        return transport.discover()
    finally:
        transport.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="MFX Tilt Module hardware check (moves the real module)")
    parser.add_argument("port", nargs="?", help="COM port, e.g. COM3 or 3")
    parser.add_argument("modules", nargs="*", help=f"module name(s); default: discover via {BROADCAST_ID}")
    parser.add_argument("--baud", type=int, default=BAUD_RATE)
    parser.add_argument("--parity", default=DEFAULT_PARITY, choices=["E", "N", "O"])
    args = parser.parse_args(argv)
    if not args.port:
        print(__doc__)
        return 2
    _configure_logging()

    try:
        modules = args.modules or [_discover_module(args.port, args.baud, args.parity)]
    except TiltModuleError as exc:
        logger.error("could not find a module on %s at %d 8%s1: %s", args.port, args.baud, args.parity, exc)
        logger.error("try:  hamilton-tilt-module --scan %s", args.port)
        return 1

    with TiltModuleClient(baudrate=args.baud, parity=args.parity) as tilt:  # simulate=False: REAL hardware
        try:
            logger.info("1/5 connect system %d on %s (%d baud, 8%s1)", SYSTEM_ID, args.port, args.baud, args.parity)
            tilt.tilt_module_connect(SYSTEM_ID, args.port)

            logger.info("2/5 initialize %s (EI, SI, RF)", modules)
            for name in modules:
                logger.info("    %s", tilt.tilt_module_initialize(SYSTEM_ID, name).return_parameters.message)

            logger.info("3/5 status after homing")
            for name in modules:
                p = tilt.tilt_module_get_status(SYSTEM_ID, name).return_parameters
                logger.info(
                    "    %s: angle=%s busy=%s error=%s (%s) query_error=%s",
                    name,
                    p.angle,
                    p.busy,
                    p.error_code,
                    p.error_message,
                    p.query_error,
                )

            logger.info("4/5 move through %s degrees (time each move; watch and listen)", ANGLES)
            for angle in ANGLES:
                for name in modules:
                    started = time.monotonic()
                    tilt.tilt_module_move_to_position(SYSTEM_ID, name, angle)
                    logger.info("    %s -> %2d deg done in %.1f s", name, angle, time.monotonic() - started)

            logger.info("5/5 terminate (GP0, PO) and close")
            for name in modules:
                tilt.tilt_module_terminate_module(SYSTEM_ID, name)
            tilt.tilt_module_terminate_communication(SYSTEM_ID)
        except TiltModuleError as exc:
            logger.error(
                "FAILED: %s (error_code=%s: %s)",
                exc,
                exc.error_code,
                tilt.tilt_module_error_message(exc.error_code or 0).return_parameters.message,
            )
            return 1
    logger.info("PASSED. Full serial trace: %s", LOG_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
