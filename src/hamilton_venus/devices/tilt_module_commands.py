"""Hamilton MFX Tilt Module command methods (standalone client).

Converted from the VENUS library ``HSLMultiDaisyChainedTiltModuleAmbient``. Like the
Heater Cooler, the Tilt Module does **not** go through the VENUS runtime: it is
PC-connected over RS-232 and driven directly (see :mod:`hamilton_venus.tilt_module`).
:class:`TiltModuleClient` works with no instrument connection and no
``StarClient`` / ``VantageClient``.

The methods follow the HSL one-to-one::

    InitializeCommunication       tilt_module_connect(system_id, com_port)
    InitializeTiltModuleAmbient   tilt_module_initialize(system_id, module_name)
    MoveToPosition                tilt_module_move_to_position(system_id, module_name, angle)
    TerminateTiltModuleAmbient    tilt_module_terminate_module(system_id, module_name)
    TerminateCommunication        tilt_module_terminate_communication(system_id)
    EvaluateErrorMessage          tilt_module_error_message(error_code)
    (not in the HSL)              tilt_module_get_status(system_id, module_name)

A *system* (``system_id`` 1..4) is one COM port; up to eight modules, each with a
two-character ``module_name``, share it. Angles are whole degrees ``0..10`` (``0`` =
horizontal; the **right** side of the plate lifts).

Failures raise :class:`~hamilton_venus.TiltModuleError` (the HSL returns codes instead);
``error_code`` carries the HSL return code, and :meth:`tilt_module_error_message` turns a
code into its text.

This module only moves the hardware: it does **not** change where VENUS thinks the wells
are. See ``docs/examples/tilt-module.md``.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from hamilton_venus.models import (
    CommandResponse,
    MessageResponse,
    TiltModuleConnectResponse,
    TiltModuleStatusResponse,
)
from hamilton_venus.tilt_module import (
    BAUD_RATE,
    DEFAULT_PARITY,
    TiltModuleManager,
    TransportFactory,
    evaluate_error_message,
)

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)

# The Tilt Module does not go through the VENUS runtime, so it gets none of VENUS's
# own request/response trace logging for free -- these INFO-level logger calls are
# this command group's only record of what it did and when.
logger = logging.getLogger(__name__)


class TiltModuleDeviceCommands:
    """Device command group for the Hamilton MFX Tilt Module.

    Set :attr:`_tilt_module_transport_factory` on a client instance (or subclass) to inject
    fake transports for tests (a callable ``system_id -> TiltModuleTransport``);
    :attr:`_tilt_module_sim_modules` fixes the module names the simulator knows (default:
    any two-character name is accepted).
    """

    _tilt_module_transport_factory: TransportFactory | None = None
    _tilt_module_sim_modules: tuple[str, ...] | None = None
    _tilt_module_return_to_flat_on_close: bool = True
    _tilt_module_baudrate: int = BAUD_RATE
    _tilt_module_parity: str = DEFAULT_PARITY

    # -- manager plumbing ---------------------------------------------------

    def _tilt(self) -> TiltModuleManager:
        manager = getattr(self, "_tilt_module_manager", None)
        if manager is None:
            manager = TiltModuleManager(
                simulate=bool(getattr(self, "_simulate", False)),
                transport_factory=self._tilt_module_transport_factory,
                sim_modules=self._tilt_module_sim_modules,
                return_to_flat_on_close=self._tilt_module_return_to_flat_on_close,
                baudrate=self._tilt_module_baudrate,
                parity=self._tilt_module_parity,
            )
            self._tilt_module_manager = manager
        return manager

    @staticmethod
    def _ok(model_type: type[_ResponseT], return_parameters: object) -> _ResponseT:
        return model_type.model_validate(
            {
                "returnStatus": "Success",
                "returnCode": 0,
                "returnParameters": return_parameters,
            }
        )

    # -- InitializeCommunication / TerminateCommunication ------------------------

    def tilt_module_connect(self, system_id: int, com_port: int | str) -> TiltModuleConnectResponse:
        """Open the RS-232 port for a system (HSL ``InitializeCommunication``).

        One system (``system_id`` 1..4) is one COM port; the modules on its daisy chain
        share it. Call once per system, before :meth:`tilt_module_initialize`.

        Parameters
        ----------
        system_id:
            System identifier, 1..4.
        com_port:
            COM port number 1..255 (``3`` or ``"COM3"``).
        """
        logger.info("tilt_module_connect(system_id=%s, com_port=%s) starting", system_id, com_port)
        port = self._tilt().connect(system_id, com_port)
        logger.info("tilt_module_connect(system_id=%s) complete on %s", system_id, port)
        return self._ok(TiltModuleConnectResponse, {"systemId": system_id, "comPort": port})

    def tilt_module_terminate_communication(self, system_id: int) -> MessageResponse:
        """Close a system's COM port (HSL ``TerminateCommunication``).

        Every module on the system must be terminated first (``tilt_module_terminate_module``).
        """
        logger.info("tilt_module_terminate_communication(system_id=%s) starting", system_id)
        self._tilt().terminate_communication(system_id)
        logger.info("tilt_module_terminate_communication(system_id=%s) complete", system_id)
        return self._ok(MessageResponse, {"message": f"System {system_id} communication closed"})

    # -- InitializeTiltModuleAmbient / MoveToPosition / TerminateTiltModuleAmbient ---------

    def tilt_module_initialize(self, system_id: int, module_name: str) -> MessageResponse:
        """Bring a module up (HSL ``InitializeTiltModuleAmbient``).

        Sends the HSL's command list ``EI,SI,RF``: reset the error state, home the drive to
        horizontal, read the firmware version. Afterwards the module is at 0 degrees.

        Parameters
        ----------
        system_id:
            System identifier, 1..4 (must already be connected).
        module_name:
            The module's two-character name on the chain (e.g. ``"TM"``).
        """
        logger.info("tilt_module_initialize(system_id=%s, module_name=%r) starting", system_id, module_name)
        firmware = self._tilt().initialize_module(system_id, module_name)
        logger.info(
            "tilt_module_initialize(system_id=%s, module_name=%r) complete, firmware=%r",
            system_id,
            module_name,
            firmware,
        )
        return self._ok(
            MessageResponse,
            {"message": f"Module {module_name} initialized on system {system_id} (firmware: {firmware})"},
        )

    def tilt_module_move_to_position(self, system_id: int, module_name: str, angle: int) -> MessageResponse:
        """Tilt a module to *angle* degrees (HSL ``MoveToPosition``) and wait until it is idle.

        Do not pipette to or from the module while it is moving; this call returns only once
        the module has acknowledged the move (and, when it answers status queries, reports idle).
        If the move fails the tracked angle becomes unknown until the next successful move.

        Parameters
        ----------
        angle:
            Target angle in whole degrees, ``0..10`` (0 = horizontal).
        """
        logger.info(
            "tilt_module_move_to_position(system_id=%s, module_name=%r, angle=%s) starting",
            system_id,
            module_name,
            angle,
        )
        target = self._tilt().move_to_position(system_id, module_name, angle)
        logger.info("tilt_module_move_to_position(system_id=%s, module_name=%r) complete", system_id, module_name)
        return self._ok(MessageResponse, {"message": f"Module {module_name} moved to {target} deg"})

    def tilt_module_terminate_module(self, system_id: int, module_name: str) -> MessageResponse:
        """Return a module to horizontal and power it off (HSL ``TerminateTiltModuleAmbient``: ``GP0,PO``).

        If the module cannot return to horizontal it is *not* powered off, and the error is raised.
        """
        logger.info("tilt_module_terminate_module(system_id=%s, module_name=%r) starting", system_id, module_name)
        self._tilt().terminate_module(system_id, module_name)
        logger.info("tilt_module_terminate_module(system_id=%s, module_name=%r) complete", system_id, module_name)
        return self._ok(MessageResponse, {"message": f"Module {module_name} terminated on system {system_id}"})

    # -- queries ----------------------------------------------------------------

    def tilt_module_get_status(self, system_id: int, module_name: str) -> TiltModuleStatusResponse:
        """Module state: tracked angle plus a live busy/error query (not in the HSL).

        ``angle`` is the last angle *commanded* -- the module has no position read-back.
        ``busy`` / ``error_code`` come from the firmware's ``RS`` / ``RE`` commands; if that
        query fails they are ``None`` and ``query_error`` explains why (the tracked fields are
        always returned).
        """
        logger.info("tilt_module_get_status(system_id=%s, module_name=%r) starting", system_id, module_name)
        status = self._tilt().status(system_id, module_name)
        logger.info("tilt_module_get_status(system_id=%s, module_name=%r) complete", system_id, module_name)
        return self._ok(
            TiltModuleStatusResponse,
            {
                "systemId": status.system_id,
                "moduleName": status.module_name,
                "initialized": status.initialized,
                "angle": status.angle,
                "powered": status.powered,
                "firmwareVersion": status.firmware,
                "busy": status.busy,
                "errorCode": status.error_code,
                "errorMessage": status.error_message,
                "queryError": status.query_error,
            },
        )

    def tilt_module_error_message(self, error_code: int) -> MessageResponse:
        """Text for a return code (HSL ``EvaluateErrorMessage``): firmware codes 0..7, library codes -1..-11."""
        return self._ok(MessageResponse, {"message": evaluate_error_message(error_code)})


class TiltModuleClient(TiltModuleDeviceCommands):
    """Standalone client -- no StarClient/VantageClient needed.

    ``close()`` (and leaving a ``with`` block) shuts down anything still up: each initialised
    module is returned to horizontal and powered off, then every COM port is closed. Pass
    ``return_to_flat_on_close=False`` to leave a tilted plate where it is instead.

    ``baudrate`` / ``parity`` default to Hamilton's documented 1200 baud, 8 data bits, even
    parity, 1 stop bit; override them only to diagnose a unit that does not answer (see
    ``hamilton-tilt-module --scan PORT``).
    """

    def __init__(
        self,
        *,
        simulate: bool = False,
        transport_factory: TransportFactory | None = None,
        sim_modules: tuple[str, ...] | None = None,
        return_to_flat_on_close: bool = True,
        baudrate: int = BAUD_RATE,
        parity: str = DEFAULT_PARITY,
    ) -> None:
        self._simulate = simulate
        self._tilt_module_transport_factory = transport_factory
        self._tilt_module_sim_modules = sim_modules
        self._tilt_module_return_to_flat_on_close = return_to_flat_on_close
        self._tilt_module_baudrate = baudrate
        self._tilt_module_parity = parity

    def close(self) -> None:
        manager = getattr(self, "_tilt_module_manager", None)
        if manager is not None:
            manager.terminate()

    def __enter__(self) -> TiltModuleClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
