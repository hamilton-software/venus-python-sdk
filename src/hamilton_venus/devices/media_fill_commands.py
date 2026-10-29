"""Hamilton Media Fill Module command methods + standalone client.

Like the Heater Cooler / ODTC groups, these do **not** go through the VENUS
runtime -- the module is PC-connected and driven directly (see
:mod:`hamilton_venus.media_fill`). Use :class:`MediaFillClient` on its own; no
``StarClient``/``VantageClient`` is needed::

    with MediaFillClient(simulate=True) as mfm:
        mfm.media_fill_connect("COM5")
        mfm.media_fill_fill_trough(pump_id=1, speed=50, timeout=60)
        mfm.media_fill_wait_for_pump(pump_id=1)

One method per function of the vendor HSL libraries -- ``HxMediaFill`` (2.0) and
``HSLHamiltonMediaFillModule`` (1.1); the driver uses whichever is installed:

=========================================  ==========================================
HSL function (2.0 / 1.1)                   Python method
=========================================  ==========================================
``Initialize``                             :meth:`~MediaFillDeviceCommands.media_fill_connect`
``Disconnect``                             :meth:`~MediaFillDeviceCommands.media_fill_disconnect`
``GetPumpDirection``                       :meth:`~MediaFillDeviceCommands.media_fill_get_pump_direction`
``SetPumpDirection``                       :meth:`~MediaFillDeviceCommands.media_fill_set_pump_direction`
``GetLiquidLevelSensorState``              :meth:`~MediaFillDeviceCommands.media_fill_get_liquid_level_sensor_state`
``FillTrough``                             :meth:`~MediaFillDeviceCommands.media_fill_fill_trough`
``EmptyLineToSource`` / ``WastePumpNoSensor``  :meth:`~MediaFillDeviceCommands.media_fill_waste_pump_no_sensor`
``WaitForPump``                            :meth:`~MediaFillDeviceCommands.media_fill_wait_for_pump`
``StopPump`` (2.0 only)                    :meth:`~MediaFillDeviceCommands.media_fill_stop_pump`
``GetLastErrorMessage``                    :meth:`~MediaFillDeviceCommands.media_fill_get_last_error_message`
=========================================  ==========================================

plus the SDK's usual :meth:`~MediaFillDeviceCommands.media_fill_get_device_ids`
and :meth:`~MediaFillDeviceCommands.media_fill_terminate`, and
:meth:`~MediaFillDeviceCommands.media_fill_get_status` (every read-only query in one call). The HSL's
``InstrumentId`` becomes ``device_id`` (``1..N``, assigned by
:meth:`~MediaFillDeviceCommands.media_fill_connect`; default ``1``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypeVar

from hamilton_venus.exceptions import MediaFillError
from hamilton_venus.media_fill import (
    FIRMWARE_ID,
    PUMP_IDS,
    MediaFillManager,
    PumpDirection,
    direction_name,
    direction_value,
    is_media_fill_firmware,
    parse_com_port,
)
from hamilton_venus.models import (
    CommandResponse,
    MediaFillConnectResponse,
    MediaFillDeviceIdsResponse,
    MediaFillLastErrorMessageResponse,
    MediaFillLiquidLevelSensorStateResponse,
    MediaFillPumpDirectionResponse,
    MediaFillStatusResponse,
    MessageResponse,
)

if TYPE_CHECKING:
    from hamilton_venus.media_fill import _MediaFillTransport

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)

# The Media Fill Module does not go through the VENUS runtime, so it gets none
# of VENUS's own request/response trace logging -- these INFO-level logger calls
# are this device group's only record of what it did and when.
logger = logging.getLogger(__name__)


class MediaFillDeviceCommands:
    """Device command group for the Hamilton Media Fill Module.

    Set :attr:`_media_fill_transport` (or pass ``transport=`` to
    :class:`MediaFillClient`) to inject a fake transport for tests.
    """

    _media_fill_transport: _MediaFillTransport | None = None

    # -- manager plumbing ---------------------------------------------------

    def _mfm(self) -> MediaFillManager:
        manager = getattr(self, "_media_fill_manager", None)
        if manager is None:
            manager = MediaFillManager(
                simulate=bool(getattr(self, "_simulate", False)),
                transport=self._media_fill_transport,
            )
            self._media_fill_manager = manager
        return manager

    @staticmethod
    def _ok(model_type: type[_ResponseT], return_parameters: object) -> _ResponseT:
        return model_type.model_validate(
            {"returnStatus": "Success", "returnCode": 0, "returnParameters": return_parameters}
        )

    @staticmethod
    def _vendor_api(manager: MediaFillManager) -> str:
        """``"2.0"`` / ``"1.1"`` for the vendor library in use, ``"simulated"`` for the simulator."""
        return "simulated" if manager.simulated else str(getattr(manager.transport, "api", ""))

    # -- connection ------------------------------------------------------------

    def media_fill_connect(self, com_port: int | str) -> MediaFillConnectResponse:
        """Connect and initialize the module on *com_port* (``5`` or ``"COM5"``) and
        register it (HSL ``Initialize``). Like the HSL, also reads the firmware
        version -- and, on real hardware, refuses (disconnects and raises
        :class:`~hamilton_venus.MediaFillError`) a device whose firmware doesn't say
        ``Media Fill Module``: the module's USB id is shared with every Arduino Uno.
        Each module can only be controlled by one process, so close any VENUS method
        or script that has it open first.
        """
        port = parse_com_port(com_port)
        logger.info("MediaFill: connecting on COM%d", port)
        manager = self._mfm()
        with manager.lock:
            identify = getattr(manager.transport, "identify", None)
            already = any(p == port for _, p, _ in manager.devices())
            if identify is not None and not manager.simulated and not already:
                identify(port)  # firmware query only; raises if this port isn't a Media Fill Module
            device_id, instrument_id = manager.connect(port)
            try:
                firmware = manager.call(device_id, manager.transport.get_firmware_version)
                if not manager.simulated and not is_media_fill_firmware(firmware):
                    # The USB id is an Arduino Uno's: make sure this really is a Media Fill Module
                    # before anything can pump on it.
                    raise MediaFillError(
                        f"COM{port} answered, but its firmware {firmware!r} is not a Media Fill Module's "
                        f"(expected it to contain {FIRMWARE_ID!r}); not connected"
                    )
            except Exception:
                try:
                    manager.disconnect(device_id)
                except Exception:
                    logger.warning(
                        "MediaFill: device_id=%d could not be disconnected after a failed connect", device_id
                    )
                raise
        logger.info(
            "MediaFill: connected device_id=%d (COM%d, instrument_id=%d, firmware=%s)",
            device_id,
            port,
            instrument_id,
            firmware,
        )
        return self._ok(
            MediaFillConnectResponse,
            {
                "deviceId": device_id,
                "comPort": port,
                "instrumentId": instrument_id,
                "firmwareVersion": firmware,
                "simulated": manager.simulated,
                "vendorApi": self._vendor_api(manager),
            },
        )

    def media_fill_get_device_ids(self) -> MediaFillDeviceIdsResponse:
        """Return the registered modules: device id, COM port and firmware version."""
        logger.info("MediaFill: reading registered modules")
        manager = self._mfm()
        with manager.lock:
            rows = [
                {
                    "deviceId": did,
                    "comPort": port,
                    "instrumentId": inst,
                    "firmwareVersion": manager.call(did, manager.transport.get_firmware_version),
                }
                for did, port, inst in manager.devices()
            ]
        logger.info("MediaFill: %d module(s) registered", len(rows))
        return self._ok(MediaFillDeviceIdsResponse, {"deviceIds": rows})

    # -- pump direction --------------------------------------------------------

    def media_fill_get_pump_direction(self, pump_id: int, device_id: int = 1) -> MediaFillPumpDirectionResponse:
        """Read the motor direction set for pump *pump_id* (1-4): ``0`` counter-clockwise,
        ``1`` clockwise (HSL ``GetPumpDirection``)."""
        logger.info("MediaFill: device_id=%d pump_id=%d reading direction", device_id, pump_id)
        manager = self._mfm()
        with manager.lock:
            direction = manager.call(device_id, manager.transport.get_pump_direction, pump_id)
        name = direction_name(direction)
        logger.info("MediaFill: device_id=%d pump_id=%d direction=%s", device_id, pump_id, name)
        return self._ok(
            MediaFillPumpDirectionResponse,
            {"deviceId": device_id, "pumpId": pump_id, "direction": direction, "directionName": name},
        )

    def media_fill_set_pump_direction(
        self, pump_id: int, direction: PumpDirection | int | str, device_id: int = 1
    ) -> MessageResponse:
        """Set the motor direction of pump *pump_id* (1-4) (HSL ``SetPumpDirection``).

        *direction*: ``PumpDirection.COUNTER_CLOCKWISE`` (0) or ``PumpDirection.CLOCKWISE``
        (1); plain ints (passed to the vendor object unchanged -- it accepts only 0/1)
        and the names ``"ccw"``/``"cw"`` work too. Every pump starts each run counter-clockwise.
        """
        value = direction_value(direction)
        name = direction_name(value)
        logger.info("MediaFill: device_id=%d pump_id=%d setting direction=%s", device_id, pump_id, name)
        manager = self._mfm()
        with manager.lock:
            manager.call(device_id, manager.transport.set_pump_direction, pump_id, value)
        logger.info("MediaFill: device_id=%d pump_id=%d direction set", device_id, pump_id)
        return self._ok(MessageResponse, {"message": f"pump {pump_id} direction set to {name}"})

    # -- liquid level sensor ---------------------------------------------------

    def media_fill_get_liquid_level_sensor_state(
        self, pump_id: int, device_id: int = 1
    ) -> MediaFillLiquidLevelSensorStateResponse:
        """Read the liquid level sensor of pump *pump_id* (1-4) (HSL
        ``GetLiquidLevelSensorState``): ``0`` = liquid not detected; ``1`` = liquid
        detected, **or** the sensor is unplugged, **or** the controller is powered down."""
        logger.info("MediaFill: device_id=%d pump_id=%d reading liquid level sensor", device_id, pump_id)
        manager = self._mfm()
        with manager.lock:
            state = manager.call(device_id, manager.transport.get_liquid_level_sensor_state, pump_id)
        logger.info("MediaFill: device_id=%d pump_id=%d liquid level sensor state=%d", device_id, pump_id, state)
        return self._ok(
            MediaFillLiquidLevelSensorStateResponse,
            {"deviceId": device_id, "pumpId": pump_id, "liquidLevelSensorState": state},
        )

    # -- pumping ---------------------------------------------------------------

    def media_fill_fill_trough(self, pump_id: int, speed: int, timeout: int, device_id: int = 1) -> MessageResponse:
        """Start pump *pump_id* (1-4) filling its trough (HSL ``FillTrough``).

        Returns as soon as the pump has started; it runs until the trough's liquid
        level sensor triggers or *timeout* seconds elapse. *speed* is the relative
        rate, 30-100 (%). The pump turns counter-clockwise unless set otherwise with
        :meth:`media_fill_set_pump_direction`. Call :meth:`media_fill_wait_for_pump`
        to block until it stops.
        """
        logger.info(
            "MediaFill: device_id=%d pump_id=%d starting fill speed=%s%% timeout=%ss",
            device_id,
            pump_id,
            speed,
            timeout,
        )
        manager = self._mfm()
        with manager.lock:
            manager.call(device_id, manager.transport.fill_trough, pump_id, speed, timeout)
        logger.info("MediaFill: device_id=%d pump_id=%d fill started", device_id, pump_id)
        return self._ok(MessageResponse, {"message": f"pump {pump_id} filling"})

    def media_fill_waste_pump_no_sensor(
        self, pump_id: int, speed: int, timeout: int, device_id: int = 1
    ) -> MessageResponse:
        """Pump *out*: run pump *pump_id* (1-4) in **reverse**, without the liquid level
        sensor (vendor ``EmptyLineToSource`` in the 2.0 library, ``WastePumpNoSensor`` in 1.1;
        both behave the same).

        The pump turns the opposite way to the direction set with
        :meth:`media_fill_set_pump_direction` -- so leave the pump on its *fill*
        direction and this pulls liquid back from the trough toward the source
        bottle (verified on a real module). Setting the other direction first makes
        it pump **into** the trough with nothing to stop it at the sensor. The
        stored direction is not changed.

        Like :meth:`media_fill_fill_trough` it returns once the pump has started,
        with the same *speed* range (30-100 %), but it runs for the full *timeout*
        seconds (stop it early with :meth:`media_fill_stop_pump` on 2.0, or
        :meth:`media_fill_disconnect`). The 2.0 library allows at most 20 s
        (``MaxTimeoutForBackflow``); with 1.1, keep *timeout* within Hamilton's 720 s
        limit per pumping operation (that vendor object does not check it). Call
        :meth:`media_fill_wait_for_pump` to block until it stops.
        """
        logger.info(
            "MediaFill: device_id=%d pump_id=%d starting sensor-less run speed=%s%% timeout=%ss",
            device_id,
            pump_id,
            speed,
            timeout,
        )
        manager = self._mfm()
        with manager.lock:
            manager.call(device_id, manager.transport.waste_pump_no_sensor, pump_id, speed, timeout)
        logger.info("MediaFill: device_id=%d pump_id=%d sensor-less run started", device_id, pump_id)
        return self._ok(MessageResponse, {"message": f"pump {pump_id} running without sensor"})

    def media_fill_wait_for_pump(self, pump_id: int, device_id: int = 1) -> MessageResponse:
        """Block until pump *pump_id* (1-4) has finished pumping (HSL ``WaitForPump``).

        Other commands on this client wait until this returns. The 2.0 library raises
        an error once its default timeout of 1 minute passes; 1.1 waits until the pump stops.
        """
        logger.info("MediaFill: device_id=%d pump_id=%d waiting for pump", device_id, pump_id)
        manager = self._mfm()
        with manager.lock:
            manager.call(device_id, manager.transport.wait_for_pump, pump_id)
        logger.info("MediaFill: device_id=%d pump_id=%d finished", device_id, pump_id)
        return self._ok(MessageResponse, {"message": f"pump {pump_id} finished"})

    def media_fill_stop_pump(self, pump_id: int, device_id: int = 1) -> MessageResponse:
        """Stop pump *pump_id* (1-4), leaving the module connected (HSL ``StopPump``).

        Needs the 2.0 vendor library; with 1.1 this raises
        :class:`~hamilton_venus.MediaFillError` -- use :meth:`media_fill_disconnect`,
        which stops every pump on the module.
        """
        logger.info("MediaFill: device_id=%d pump_id=%d stopping pump", device_id, pump_id)
        manager = self._mfm()
        with manager.lock:
            manager.call(device_id, manager.transport.stop_pump, pump_id)
        logger.info("MediaFill: device_id=%d pump_id=%d stopped", device_id, pump_id)
        return self._ok(MessageResponse, {"message": f"pump {pump_id} stopped"})

    # -- diagnostics -----------------------------------------------------------

    def media_fill_get_last_error_message(self) -> MediaFillLastErrorMessageResponse:
        """Return the last error message from the vendor driver (HSL ``GetLastErrorMessage``).

        A failed command already raises :class:`~hamilton_venus.MediaFillError` with
        this text; this reads it again on demand.
        """
        logger.info("MediaFill: reading last error message")
        manager = self._mfm()
        with manager.lock:
            message = manager.transport.get_last_error_message()
        logger.info("MediaFill: last error message=%r", message)
        return self._ok(MediaFillLastErrorMessageResponse, {"errorMessage": message})

    def media_fill_get_status(self, device_id: int = 1) -> MediaFillStatusResponse:
        """Everything the module can report, in one call: COM port, firmware version,
        and for each pump 1-4 its direction and liquid level sensor state, plus the
        vendor's last error message. Reads only -- nothing moves. Safe while a pump runs.

        The vendor API has no "is the pump running" query, so there is none here:
        :meth:`media_fill_wait_for_pump` (which blocks) is the only way to learn a
        pump has stopped. Sensor ``1`` also means "unplugged" or "controller off"
        (see :meth:`media_fill_get_liquid_level_sensor_state`).
        """
        logger.info("MediaFill: device_id=%d reading status", device_id)
        manager = self._mfm()
        with manager.lock:
            row = next(((port, inst) for did, port, inst in manager.devices() if did == device_id), None)
            firmware = manager.call(device_id, manager.transport.get_firmware_version)
            pumps = []
            for pump_id in PUMP_IDS:
                direction = manager.call(device_id, manager.transport.get_pump_direction, pump_id)
                sensor = manager.call(device_id, manager.transport.get_liquid_level_sensor_state, pump_id)
                pumps.append({
                    "pumpId": pump_id,
                    "direction": direction,
                    "directionName": direction_name(direction),
                    "liquidLevelSensorState": sensor,
                })
            message = manager.transport.get_last_error_message()
        port, instrument_id = row if row else (0, 0)
        logger.info(
            "MediaFill: device_id=%d status firmware=%s sensors=%s last_error=%r",
            device_id,
            firmware,
            [p["liquidLevelSensorState"] for p in pumps],
            message,
        )
        return self._ok(
            MediaFillStatusResponse,
            {
                "deviceId": device_id,
                "comPort": port,
                "instrumentId": instrument_id,
                "firmwareVersion": firmware,
                "simulated": manager.simulated,
                "vendorApi": self._vendor_api(manager),
                "pumps": pumps,
                "lastErrorMessage": message,
            },
        )

    # -- teardown --------------------------------------------------------------

    def media_fill_disconnect(self, device_id: int = 1) -> MessageResponse:
        """Disconnect one module; the vendor driver stops all of its active pumps
        (HSL ``Disconnect``). If the vendor call fails, the module stays registered,
        and :meth:`media_fill_terminate` / ``close()`` retries it, then falls back to
        the vendor ``Abort`` (2.0) / ``AbortAll`` (1.1)."""
        logger.info("MediaFill: disconnecting device_id=%d", device_id)
        self._mfm().disconnect(device_id)
        logger.info("MediaFill: device_id=%d disconnected", device_id)
        return self._ok(MessageResponse, {"message": f"Media Fill device {device_id} disconnected"})

    def media_fill_terminate(self) -> MessageResponse:
        """Disconnect every module (stopping their pumps) and release the vendor COM object."""
        logger.info("MediaFill: terminating all connections")
        self._mfm().terminate()
        logger.info("MediaFill: disconnected")
        return self._ok(MessageResponse, {"message": "Media Fill disconnected"})


class MediaFillClient(MediaFillDeviceCommands):
    """Standalone client for the Hamilton Media Fill Module -- no ``StarClient``/
    ``VantageClient`` needed. Pure Python, no VENUS runtime (see
    :mod:`hamilton_venus.media_fill`)::

        with MediaFillClient(simulate=True) as mfm:
            mfm.media_fill_connect("COM5")
    """

    def __init__(self, *, simulate: bool = False, transport: _MediaFillTransport | None = None) -> None:
        self._simulate = simulate
        self._media_fill_transport = transport

    def close(self) -> None:
        """Disconnect every module (stopping their pumps) and release the vendor
        object, if a connection was ever made. Safe to call even if
        :meth:`media_fill_connect` was never called (never lazily creates a manager)."""
        manager = getattr(self, "_media_fill_manager", None)
        if manager is not None:
            manager.terminate()

    def __enter__(self) -> MediaFillClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


__all__ = ["MediaFillClient", "MediaFillDeviceCommands"]
