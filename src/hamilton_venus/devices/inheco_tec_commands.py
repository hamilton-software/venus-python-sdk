"""Inheco Single/Multi TEC Controller (STC/MTC) command methods for the instrument clients.

Unlike the HHS / WXS device groups, these do **not** go through the VENUS
runtime -- the InhecoTEC controller is PC-connected and driven directly (see
:mod:`hamilton_venus.inheco_tec`). Methods work with no instrument connection
and regardless of ``auto_connect`` / ``instrument_init()``.

Addressing is two-level, matching the vendor's own ``HSLInhecoTECLib.hsl``:
``controller_id`` (0-7) selects which physical controller box a command
targets on the shared bus, and ``device_id`` (1-6, or 0 for the controller
unit itself) selects a slot on that box. :meth:`InhecoTECDeviceCommands.inheco_tec_connect`
must be called for a given ``controller_id`` before any other command
targeting it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypeVar

from hamilton_venus.inheco_tec import (
    CONTROLLER_TYPE_NAMES,
    DEVICE_MAX,
    DEVICE_MIN,
    DEVICE_TYPE_NAMES,
    FIRMWARE_INFO_NAMES,
    HEATER_STATUS_NAMES,
    RESERVOIR_STATUS_NAMES,
    SENSOR_INFO_NAMES,
    SHAKE_SHAPE_NAMES,
    SLOT_COUNT_BY_CONTROLLER_TYPE,
    TEMPERATURE_INFO_NAMES,
    InhecoTECManager,
    check_controller_id,
    check_device_id,
    check_shaker_revolutions,
    validate_target_temperature,
)
from hamilton_venus.models import (
    CommandResponse,
    InhecoTECConnectResponse,
    InhecoTECFirmwareResponse,
    InhecoTECIdentificationResponse,
    InhecoTECRawResponse,
    InhecoTECReservoirStatusResponse,
    InhecoTECSensorValueResponse,
    InhecoTECShakerStatusResponse,
    InhecoTECTemperatureStatusResponse,
    MessageResponse,
)

if TYPE_CHECKING:
    from hamilton_venus.inheco_tec import _InhecoTECTransport

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)

# The InhecoTEC controller does not go through the VENUS runtime (see the
# module docstring), so it gets none of VENUS's own request/response trace
# logging for free -- these INFO-level logger calls are this device group's
# only record of what it did and when.
logger = logging.getLogger(__name__)


class InhecoTECDeviceCommands:
    """Device command group for the Inheco Single/Multi TEC Controller.

    Set :attr:`_inheco_tec_transport` on a client instance (or subclass) to
    inject a fake transport for tests.
    """

    _inheco_tec_transport: _InhecoTECTransport | None = None

    # -- manager plumbing ---------------------------------------------------

    def _inheco_tec(self) -> InhecoTECManager:
        manager = getattr(self, "_inheco_tec_manager", None)
        if manager is None:
            manager = InhecoTECManager(
                simulate=bool(getattr(self, "_simulate", False)),
                transport=self._inheco_tec_transport,
            )
            self._inheco_tec_manager = manager
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

    # -- connection / discovery ------------------------------------------------

    def inheco_tec_connect(self, controller_id: int) -> InhecoTECConnectResponse:
        """Verify controller *controller_id* answers on the bus and register it.

        Bundles the vendor ``Initialize`` with a read of the controller's own
        type (STC/MTC) and a device-type scan of its slots, so the response
        tells you what's actually plugged in without a separate round trip.
        A Single TEC (STC) controller has exactly 1 slot; a Multi TEC (MTC)
        has up to 6 -- confirmed against real hardware -- so only an STC's
        one slot is scanned, not all 6 (see
        :data:`~hamilton_venus.inheco_tec.SLOT_COUNT_BY_CONTROLLER_TYPE`).
        """
        check_controller_id(controller_id)
        logger.info("InhecoTEC: connecting to controller_id=%s", controller_id)
        manager = self._inheco_tec()
        with manager.lock:
            manager.connect(controller_id)
            transport = manager.transport
            controller_type = transport.get_device_type(controller_id, 0)
            slot_count = SLOT_COUNT_BY_CONTROLLER_TYPE.get(controller_type, DEVICE_MAX)
            devices = []
            for device_id in range(DEVICE_MIN, DEVICE_MIN + slot_count):
                device_type = transport.get_device_type(controller_id, device_id)
                devices.append(
                    {
                        "deviceId": device_id,
                        "deviceType": device_type,
                        "deviceTypeName": DEVICE_TYPE_NAMES.get(device_type, "Unknown"),
                    }
                )
        logger.info(
            "InhecoTEC: controller_id=%s connected (%s), %d slot(s) scanned",
            controller_id,
            CONTROLLER_TYPE_NAMES.get(controller_type, "Unknown"),
            len(devices),
        )
        return self._ok(
            InhecoTECConnectResponse,
            {
                "controllerId": controller_id,
                "controllerType": controller_type,
                "controllerTypeName": CONTROLLER_TYPE_NAMES.get(controller_type, "Unknown"),
                "devices": devices,
            },
        )

    def inheco_tec_terminate(self, *, stop_all_devices: bool = True) -> MessageResponse:
        """Disconnect every InhecoTEC controller and release the COM connection.

        With *stop_all_devices* (the default), stops the shaker and
        temperature control on every connected controller's slots 1-6 first,
        best-effort, mirroring the vendor's own ``Terminate(stopAllDevices)``.
        """
        manager = self._inheco_tec()
        controllers = manager.connected_controllers()
        logger.info("InhecoTEC: terminating connection (controllers=%s)", controllers)
        manager.terminate(stop_all_devices=stop_all_devices)
        logger.info("InhecoTEC: disconnected")
        return self._ok(MessageResponse, {"message": "InhecoTEC disconnected"})

    # -- identification / firmware / sensors ---------------------------------

    def inheco_tec_get_identification(self, controller_id: int, device_id: int = 0) -> InhecoTECIdentificationResponse:
        """Read device type, serial number, runtime and (for a real slot,
        ``device_id`` 1-6) calibration date for *device_id* on *controller_id*.

        ``device_id=0`` (the default) identifies the controller unit itself,
        which has no calibration date (``calibrationDate`` comes back
        ``null``).
        """
        check_controller_id(controller_id)
        check_device_id(device_id, allow_controller=True)
        logger.info("InhecoTEC: reading identification controller_id=%s device_id=%s", controller_id, device_id)
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            transport = manager.transport
            device_type = transport.get_device_type(controller_id, device_id)
            serial_number = transport.get_device_serial_number(controller_id, device_id)
            runtime_minutes = transport.get_device_runtime(controller_id, device_id)
            calibration_date = (
                transport.get_calibration_date(controller_id, device_id) if device_id != 0 else None
            )
        logger.info(
            "InhecoTEC: controller_id=%s device_id=%s type=%s serial=%s runtime=%s calibration=%s",
            controller_id,
            device_id,
            DEVICE_TYPE_NAMES.get(device_type, "Unknown"),
            serial_number,
            runtime_minutes,
            calibration_date,
        )
        return self._ok(
            InhecoTECIdentificationResponse,
            {
                "controllerId": controller_id,
                "deviceId": device_id,
                "deviceType": device_type,
                "deviceTypeName": DEVICE_TYPE_NAMES.get(device_type, "Unknown"),
                "serialNumber": serial_number,
                "runtimeMinutes": runtime_minutes,
                "calibrationDate": calibration_date,
            },
        )

    def inheco_tec_get_firmware_version(self, controller_id: int, selector: int = 1) -> InhecoTECFirmwareResponse:
        """Read one firmware field for *controller_id* (see
        :data:`~hamilton_venus.inheco_tec.FIRMWARE_INFO_NAMES`; default is
        ``1`` = ``Application_Version``)."""
        check_controller_id(controller_id)
        if selector not in FIRMWARE_INFO_NAMES:
            raise ValueError(f"selector must be one of {sorted(FIRMWARE_INFO_NAMES)}, got {selector}")
        logger.info("InhecoTEC: reading firmware version controller_id=%s selector=%s", controller_id, selector)
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            value = manager.transport.get_firmware_version(controller_id, selector)
        logger.info("InhecoTEC: controller_id=%s firmware[%s]=%s", controller_id, FIRMWARE_INFO_NAMES[selector], value)
        return self._ok(
            InhecoTECFirmwareResponse,
            {
                "controllerId": controller_id,
                "selector": selector,
                "selectorName": FIRMWARE_INFO_NAMES[selector],
                "value": value,
            },
        )

    def inheco_tec_get_sensor_values(self, controller_id: int, selector: int) -> InhecoTECSensorValueResponse:
        """Read one controller housing sensor (see
        :data:`~hamilton_venus.inheco_tec.SENSOR_INFO_NAMES`).

        Replicates an apparent, unfixed upstream bug: the vendor library's
        own ``GetSensorValues`` sends the *firmware*-version command instead
        of the sensor-value command (see
        :meth:`hamilton_venus.inheco_tec._ComInhecoTECTransport.get_sensor_values`)
        -- against real hardware this returns firmware data, not a sensor
        reading. Kept as-is for wire fidelity with the shipped vendor driver.
        """
        check_controller_id(controller_id)
        if selector not in SENSOR_INFO_NAMES:
            raise ValueError(f"selector must be one of {sorted(SENSOR_INFO_NAMES)}, got {selector}")
        logger.info("InhecoTEC: reading sensor value controller_id=%s selector=%s", controller_id, selector)
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            value = manager.transport.get_sensor_values(controller_id, selector)
        logger.info("InhecoTEC: controller_id=%s sensor[%s]=%s", controller_id, SENSOR_INFO_NAMES[selector], value)
        return self._ok(
            InhecoTECSensorValueResponse,
            {
                "controllerId": controller_id,
                "selector": selector,
                "selectorName": SENSOR_INFO_NAMES[selector],
                "value": value,
            },
        )

    def inheco_tec_get_reservoir_status(self, controller_id: int, device_id: int) -> InhecoTECReservoirStatusResponse:
        """Read the reservoir/refill status for *device_id* on *controller_id*."""
        check_controller_id(controller_id)
        check_device_id(device_id)
        logger.info("InhecoTEC: reading reservoir status controller_id=%s device_id=%s", controller_id, device_id)
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            status = manager.transport.get_reservoir_status(controller_id, device_id)
        logger.info(
            "InhecoTEC: controller_id=%s device_id=%s reservoir=%s",
            controller_id,
            device_id,
            RESERVOIR_STATUS_NAMES.get(status, "Unknown"),
        )
        return self._ok(
            InhecoTECReservoirStatusResponse,
            {
                "controllerId": controller_id,
                "deviceId": device_id,
                "status": status,
                "statusName": RESERVOIR_STATUS_NAMES.get(status, "Unknown"),
            },
        )

    # -- temperature control -------------------------------------------------

    def inheco_tec_get_temperature_status(
        self, controller_id: int, device_id: int, *, temperature_selector: int = 3
    ) -> InhecoTECTemperatureStatusResponse:
        """Read actual/target temperature, the device's limits and heater
        status for *device_id* on *controller_id* in one call.

        *temperature_selector* picks the actual-temperature compensation mode
        (see :data:`~hamilton_venus.inheco_tec.TEMPERATURE_INFO_NAMES`;
        default ``3`` = ``Fully_Compensated``, the vendor's own recommended
        reading).
        """
        check_controller_id(controller_id)
        check_device_id(device_id)
        if temperature_selector not in TEMPERATURE_INFO_NAMES:
            raise ValueError(
                f"temperature_selector must be one of {sorted(TEMPERATURE_INFO_NAMES)}, got {temperature_selector}"
            )
        logger.info("InhecoTEC: reading temperature status controller_id=%s device_id=%s", controller_id, device_id)
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            transport = manager.transport
            actual = transport.get_actual_temperature(controller_id, device_id, temperature_selector)
            target = transport.get_target_temperature(controller_id, device_id)
            low, high = transport.get_temperature_limits(controller_id, device_id)
            heater_status = transport.get_heater_status(controller_id, device_id, 0)
        logger.info(
            "InhecoTEC: controller_id=%s device_id=%s actual=%.1f target=%.1f limits=(%.1f,%.1f) heater=%s",
            controller_id,
            device_id,
            actual,
            target,
            low,
            high,
            HEATER_STATUS_NAMES.get(heater_status, "Unknown"),
        )
        return self._ok(
            InhecoTECTemperatureStatusResponse,
            {
                "controllerId": controller_id,
                "deviceId": device_id,
                "actualTemperature": actual,
                "targetTemperature": target,
                "temperatureMin": low,
                "temperatureMax": high,
                "heaterStatus": heater_status,
                "heaterStatusName": HEATER_STATUS_NAMES.get(heater_status, "Unknown"),
            },
        )

    def inheco_tec_set_target_temperature(
        self, controller_id: int, device_id: int, target_c: float
    ) -> MessageResponse:
        """Set the target temperature (degC) for *device_id* on *controller_id*."""
        check_controller_id(controller_id)
        check_device_id(device_id)
        validate_target_temperature(target_c)
        logger.info(
            "InhecoTEC: setting target temperature controller_id=%s device_id=%s target=%.1f degC",
            controller_id,
            device_id,
            target_c,
        )
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            manager.transport.set_target_temperature(controller_id, device_id, target_c)
        logger.info("InhecoTEC: controller_id=%s device_id=%s target temperature set", controller_id, device_id)
        return self._ok(MessageResponse, {"message": f"target temperature set to {target_c:.1f} degC"})

    def inheco_tec_start_temperature_control(self, controller_id: int, device_id: int) -> MessageResponse:
        """Start temperature control (heating/cooling toward the target) for
        *device_id* on *controller_id*."""
        check_controller_id(controller_id)
        check_device_id(device_id)
        logger.info("InhecoTEC: starting temperature control controller_id=%s device_id=%s", controller_id, device_id)
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            manager.transport.start_temperature_control(controller_id, device_id)
        logger.info("InhecoTEC: controller_id=%s device_id=%s temperature control started", controller_id, device_id)
        return self._ok(MessageResponse, {"message": "temperature control started"})

    def inheco_tec_stop_temperature_control(self, controller_id: int, device_id: int) -> MessageResponse:
        """Stop temperature control for *device_id* on *controller_id*."""
        check_controller_id(controller_id)
        check_device_id(device_id)
        logger.info("InhecoTEC: stopping temperature control controller_id=%s device_id=%s", controller_id, device_id)
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            manager.transport.stop_temperature_control(controller_id, device_id)
        logger.info("InhecoTEC: controller_id=%s device_id=%s temperature control stopped", controller_id, device_id)
        return self._ok(MessageResponse, {"message": "temperature control stopped"})

    # -- shaker ---------------------------------------------------------------

    def inheco_tec_get_shaker_status(self, controller_id: int, device_id: int) -> InhecoTECShakerStatusResponse:
        """Read shaker run status, revolutions and shape for *device_id* on
        *controller_id* in one call."""
        check_controller_id(controller_id)
        check_device_id(device_id)
        logger.info("InhecoTEC: reading shaker status controller_id=%s device_id=%s", controller_id, device_id)
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            transport = manager.transport
            status = transport.get_shaker_status(controller_id, device_id)
            revolutions = transport.get_shaker_revolutions(controller_id, device_id)
            shape = transport.get_shaker_shape(controller_id, device_id)
        logger.info(
            "InhecoTEC: controller_id=%s device_id=%s shaker status=%s revolutions=%s shape=%s",
            controller_id,
            device_id,
            status,
            revolutions,
            SHAKE_SHAPE_NAMES.get(shape, "Unknown"),
        )
        # The vendor HSL does not document a named enum for GetShakerStatus's
        # o_intStatus (unlike GetHeaterEnableStatus's HEATER_STATUS) -- no
        # name mapping is invented here, just the raw vendor code.
        return self._ok(
            InhecoTECShakerStatusResponse,
            {
                "controllerId": controller_id,
                "deviceId": device_id,
                "status": status,
                "statusName": str(status),
                "revolutions": revolutions,
                "shape": shape,
                "shapeName": SHAKE_SHAPE_NAMES.get(shape, "Unknown"),
            },
        )

    def inheco_tec_set_shaker_revolutions(self, controller_id: int, device_id: int, rpm: int) -> MessageResponse:
        """Set shaker speed in RPM (60-3000, or 0 to clamp without shaking)
        for *device_id* on *controller_id*."""
        check_controller_id(controller_id)
        check_device_id(device_id)
        check_shaker_revolutions(rpm)
        logger.info(
            "InhecoTEC: setting shaker revolutions controller_id=%s device_id=%s rpm=%s",
            controller_id,
            device_id,
            rpm,
        )
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            manager.transport.set_shaker_revolutions(controller_id, device_id, rpm)
        logger.info(
            "InhecoTEC: controller_id=%s device_id=%s shaker revolutions set to %s",
            controller_id,
            device_id,
            rpm,
        )
        return self._ok(MessageResponse, {"message": f"shaker revolutions set to {rpm}"})

    def inheco_tec_set_shaker_shape(self, controller_id: int, device_id: int, shape: int) -> MessageResponse:
        """Set shaker motion shape (see
        :data:`~hamilton_venus.inheco_tec.SHAKE_SHAPE_NAMES`) for *device_id*
        on *controller_id*."""
        check_controller_id(controller_id)
        check_device_id(device_id)
        if shape not in SHAKE_SHAPE_NAMES:
            raise ValueError(f"shape must be one of {sorted(SHAKE_SHAPE_NAMES)}, got {shape}")
        logger.info(
            "InhecoTEC: setting shaker shape controller_id=%s device_id=%s shape=%s (%s)",
            controller_id,
            device_id,
            shape,
            SHAKE_SHAPE_NAMES[shape],
        )
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            manager.transport.set_shaker_shape(controller_id, device_id, shape)
        logger.info("InhecoTEC: controller_id=%s device_id=%s shaker shape set", controller_id, device_id)
        return self._ok(MessageResponse, {"message": f"shaker shape set to {SHAKE_SHAPE_NAMES[shape]}"})

    def inheco_tec_start_shaker(self, controller_id: int, device_id: int) -> MessageResponse:
        """Start shaking for *device_id* on *controller_id*."""
        check_controller_id(controller_id)
        check_device_id(device_id)
        logger.info("InhecoTEC: starting shaker controller_id=%s device_id=%s", controller_id, device_id)
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            manager.transport.start_shaker(controller_id, device_id)
        logger.info("InhecoTEC: controller_id=%s device_id=%s shaker started", controller_id, device_id)
        return self._ok(MessageResponse, {"message": "shaker started"})

    def inheco_tec_stop_shaker(self, controller_id: int, device_id: int) -> MessageResponse:
        """Stop shaking for *device_id* on *controller_id*."""
        check_controller_id(controller_id)
        check_device_id(device_id)
        logger.info("InhecoTEC: stopping shaker controller_id=%s device_id=%s", controller_id, device_id)
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            manager.transport.stop_shaker(controller_id, device_id)
        logger.info("InhecoTEC: controller_id=%s device_id=%s shaker stopped", controller_id, device_id)
        return self._ok(MessageResponse, {"message": "shaker stopped"})

    # -- misc ---------------------------------------------------------------

    def inheco_tec_set_touchscreen(self, controller_id: int, enabled: bool) -> MessageResponse:
        """Turn the controller's own touchscreen on/off."""
        check_controller_id(controller_id)
        logger.info("InhecoTEC: setting touchscreen controller_id=%s enabled=%s", controller_id, enabled)
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            manager.transport.set_touchscreen(controller_id, enabled)
        logger.info("InhecoTEC: controller_id=%s touchscreen enabled=%s", controller_id, enabled)
        return self._ok(MessageResponse, {"message": f"touchscreen {'enabled' if enabled else 'disabled'}"})

    def inheco_tec_send_command(self, controller_id: int, command: str) -> InhecoTECRawResponse:
        """Send a raw ASCII command string to *controller_id* and return the
        raw response, unparsed -- an escape hatch mirroring the vendor's own
        ``SendCommandString``, for commands this device group does not
        otherwise expose."""
        check_controller_id(controller_id)
        if not command:
            raise ValueError("command must not be empty")
        logger.info("InhecoTEC: sending raw command controller_id=%s command=%r", controller_id, command)
        manager = self._inheco_tec()
        with manager.lock:
            manager.require_connected(controller_id)
            response = manager.transport.send_command_string(controller_id, command)
        logger.info("InhecoTEC: controller_id=%s raw response=%r", controller_id, response)
        return self._ok(
            InhecoTECRawResponse,
            {"controllerId": controller_id, "command": command, "response": response},
        )


class InhecoTECClient(InhecoTECDeviceCommands):
    """Standalone client for the Inheco Single/Multi TEC Controller -- no
    ``StarClient``/``VantageClient`` needed. Pure Python, no VENUS runtime
    (see :mod:`hamilton_venus.inheco_tec`)::

        with InhecoTECClient(simulate=True) as tec:
            tec.inheco_tec_connect(0)
    """

    def __init__(
        self,
        *,
        simulate: bool = False,
        transport: _InhecoTECTransport | None = None,
    ) -> None:
        self._simulate = simulate
        self._inheco_tec_transport = transport

    def close(self) -> None:
        """Release the connection, if one was ever made. Safe to call even if
        :meth:`inheco_tec_connect` was never called (never lazily creates a manager)."""
        manager = getattr(self, "_inheco_tec_manager", None)
        if manager is not None:
            manager.terminate()

    def __enter__(self) -> InhecoTECClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
