"""Hamilton Heater Cooler (HHC) command methods for the instrument clients.

Unlike the HHS / WXS device groups, these do **not** go through the VENUS
runtime -- the HHC is PC-connected and driven directly (see
:mod:`hamilton_venus.heater_cooler`). Methods work with no instrument connection
and regardless of ``auto_connect`` / ``instrument_init()``.

Addressing mirrors the HHS: :meth:`hhc_connect` assigns an integer ``device_id``
(``1..N``) to each unit on the daisy chain; control methods take
``device_id=None`` (all units) or a specific id.

Temperature is constrained to the device limits: **heat <= 110 degC, cool >= 0 degC**.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypeVar

from hamilton_venus.heater_cooler import HeaterCoolerManager, validate_band
from hamilton_venus.models import (
    CommandResponse,
    HHCConnectResponse,
    HHCDeviceIdsResponse,
    HHCSelfDiagnosticResponse,
    HHCStatusResponse,
    HHCTempControlResponse,
    MessageResponse,
)

if TYPE_CHECKING:
    from hamilton_venus.heater_cooler import _HeaterCoolerTransport

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)

# The HHC does not go through the VENUS runtime (see the module docstring), so
# it gets none of VENUS's own request/response trace logging for free -- these
# INFO-level logger calls are this device group's only record of what it did
# and when, which is why every command below traces its own steps explicitly
# rather than relying on a single before/after pair.
logger = logging.getLogger(__name__)


class HeaterCoolerDeviceCommands:
    """Device command group for the Hamilton Heater Cooler (HHC).

    Set :attr:`_heater_cooler_transport` on a client instance (or subclass) to
    inject a fake transport for tests; :attr:`_heater_cooler_sim_units` controls
    how many units the built-in simulation transport reports.
    """

    _heater_cooler_transport: _HeaterCoolerTransport | None = None
    _heater_cooler_sim_units: int = 1

    # -- manager plumbing ---------------------------------------------------

    def _hhc(self) -> HeaterCoolerManager:
        manager = getattr(self, "_heater_cooler_manager", None)
        if manager is None:
            manager = HeaterCoolerManager(
                simulate=bool(getattr(self, "_simulate", False)),
                transport=self._heater_cooler_transport,
                sim_units=self._heater_cooler_sim_units,
            )
            self._heater_cooler_manager = manager
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

    def hhc_connect(self, address: str, keep_alive: int = 5) -> HHCConnectResponse:
        """Open the HeaterCooler daisy chain at *address* and register its units.

        Bundles the vendor ``Connect`` with a per-unit read of firmware version,
        current temperature and verification date.

        Parameters
        ----------
        address:
            Vendor connection string (COM port / USB identifier).
        keep_alive:
            Keep-alive interval passed through to the vendor driver (seconds).
        """
        logger.info("HeaterCooler: connecting to chain at %r (keep_alive=%s)", address, keep_alive)
        manager = self._hhc()
        with manager.lock:
            manager.connect(address, keep_alive)
            transport = manager.transport
            units = []
            for device_id, serial in manager.devices():
                logger.info(
                    "HeaterCooler: device_id=%s (serial=%s) reading firmware version, "
                    "current temperature and verification date",
                    device_id,
                    serial,
                )
                units.append(
                    {
                        "deviceId": device_id,
                        "serialNumber": serial,
                        "firmwareVersion": transport.get_firmware(serial),
                        "temperature": transport.get_temperature(serial),
                        "verificationDate": transport.get_verification_date(serial),
                    }
                )
        logger.info(
            "HeaterCooler: connected chain_id=%s with %d unit(s): %s",
            manager.chain_id,
            len(units),
            [u["serialNumber"] for u in units],
        )
        return self._ok(
            HHCConnectResponse,
            {"chainId": manager.chain_id, "units": units},
        )

    def hhc_get_device_ids(self) -> HHCDeviceIdsResponse:
        """Return the registered HeaterCooler units and their firmware versions."""
        logger.info("HeaterCooler: reading device ids and firmware versions")
        manager = self._hhc()
        with manager.lock:
            transport = manager.transport
            device_ids = [
                {
                    "deviceId": device_id,
                    "serialNumber": serial,
                    "firmwareVersion": transport.get_firmware(serial),
                }
                for device_id, serial in manager.devices()
            ]
        logger.info("HeaterCooler: %d unit(s) registered", len(device_ids))
        return self._ok(HHCDeviceIdsResponse, {"deviceIds": device_ids})

    def hhc_get_status(self, device_id: int | None = None) -> HHCStatusResponse:
        """Return current temperature, time-remaining and control state per unit."""
        logger.info("HeaterCooler: reading status for device_id=%s", "all" if device_id is None else device_id)
        manager = self._hhc()
        with manager.lock:
            transport = manager.transport
            rows = [
                {
                    "deviceId": did,
                    "temperature": transport.get_temperature(serial),
                    "timeRemaining": transport.get_temp_time_remaining(serial),
                    "controlling": manager.is_controlling(serial),
                }
                for did, serial in manager.resolve(device_id)
            ]
        logger.info("HeaterCooler: status read for %d unit(s): %s", len(rows), rows)
        return self._ok(HHCStatusResponse, {"deviceIds": rows})

    # -- temperature control -------------------------------------------------

    def hhc_start_temp_control(
        self,
        target: float,
        *,
        tolerance: float = 0.5,
        wait: bool = False,
        timeout: int = 1800,
        device_id: int | None = None,
    ) -> HHCTempControlResponse:
        """Drive the unit(s) to *target* degC (+/- *tolerance*).

        *target* must be within ``[0, 110]`` degC. With ``wait=True`` the call
        blocks until each unit is within band or *timeout* seconds elapse.
        """
        low, high, tgt = validate_band(target, tolerance)
        logger.info(
            "HeaterCooler: starting temperature control target=%.2f degC (band %.2f-%.2f) "
            "wait=%s timeout=%ss device_id=%s",
            tgt,
            low,
            high,
            wait,
            timeout,
            "all" if device_id is None else device_id,
        )
        manager = self._hhc()
        with manager.lock:
            acted: list[int] = []
            for did, serial in manager.resolve(device_id):
                logger.info(
                    "HeaterCooler: device_id=%s (serial=%s) setting temperature target=%.2f degC "
                    "(band %.2f-%.2f)%s",
                    did,
                    serial,
                    tgt,
                    low,
                    high,
                    " and waiting for it to settle" if wait else "",
                )
                manager.transport.set_temperature(serial, low, high, tgt, wait, timeout)
                manager.mark_controlling(serial, True)
                acted.append(did)
        logger.info("HeaterCooler: temperature control started on %d unit(s): %s", len(acted), acted)
        return self._ok(
            HHCTempControlResponse,
            {"deviceIds": acted, "target": tgt, "waited": wait},
        )

    def hhc_hold_temp_for_time(
        self,
        target: float,
        minutes: float,
        *,
        tolerance: float = 0.5,
        device_id: int | None = None,
    ) -> HHCTempControlResponse:
        """Hold the unit(s) at *target* degC (+/- *tolerance*) for *minutes*."""
        low, high, tgt = validate_band(target, tolerance)
        logger.info(
            "HeaterCooler: holding temperature target=%.2f degC (band %.2f-%.2f) for %s minute(s) "
            "device_id=%s",
            tgt,
            low,
            high,
            minutes,
            "all" if device_id is None else device_id,
        )
        manager = self._hhc()
        with manager.lock:
            acted: list[int] = []
            for did, serial in manager.resolve(device_id):
                logger.info(
                    "HeaterCooler: device_id=%s (serial=%s) holding temperature target=%.2f degC "
                    "(band %.2f-%.2f) for %s minute(s)",
                    did,
                    serial,
                    tgt,
                    low,
                    high,
                    minutes,
                )
                manager.transport.set_temp_for_time(serial, low, high, tgt, minutes)
                manager.mark_controlling(serial, True)
                acted.append(did)
        logger.info("HeaterCooler: hold-for-time started on %d unit(s): %s", len(acted), acted)
        return self._ok(
            HHCTempControlResponse,
            {"deviceIds": acted, "target": tgt, "waited": False},
        )

    def hhc_wait_for_temp_control(
        self,
        *,
        timeout: int = 1800,
        device_id: int | None = None,
    ) -> HHCTempControlResponse:
        """Block until the unit(s) reach their temperature band or *timeout* elapses."""
        logger.info(
            "HeaterCooler: waiting for temperature control to settle timeout=%ss device_id=%s",
            timeout,
            "all" if device_id is None else device_id,
        )
        manager = self._hhc()
        with manager.lock:
            pairs = manager.resolve(device_id)
            for did, serial in pairs:
                logger.info(
                    "HeaterCooler: device_id=%s (serial=%s) waiting for temperature band (timeout=%ss)",
                    did,
                    serial,
                    timeout,
                )
                manager.transport.wait_for_temp(serial, float(timeout))
                logger.info("HeaterCooler: device_id=%s (serial=%s) reached its temperature band", did, serial)
        logger.info("HeaterCooler: %d unit(s) reached their temperature band", len(pairs))
        return self._ok(
            HHCTempControlResponse,
            {"deviceIds": [did for did, _ in pairs], "target": None, "waited": True},
        )

    def hhc_stop_temp_control(self, device_id: int | None = None) -> HHCTempControlResponse:
        """Stop temperature control on the unit(s)."""
        logger.info(
            "HeaterCooler: stopping temperature control device_id=%s",
            "all" if device_id is None else device_id,
        )
        manager = self._hhc()
        with manager.lock:
            acted: list[int] = []
            for did, serial in manager.resolve(device_id):
                logger.info("HeaterCooler: device_id=%s (serial=%s) stopping temperature control", did, serial)
                manager.transport.stop_temp_control(serial)
                manager.mark_controlling(serial, False)
                acted.append(did)
        logger.info("HeaterCooler: temperature control stopped on %d unit(s): %s", len(acted), acted)
        return self._ok(
            HHCTempControlResponse,
            {"deviceIds": acted, "target": None, "waited": False},
        )

    # -- misc ---------------------------------------------------------------

    def hhc_set_verification_date(
        self,
        date: str,
        device_id: int | None = None,
    ) -> MessageResponse:
        """Record the verification / calibration date (``YYYY-MM-DD``) on the unit(s)."""
        logger.info(
            "HeaterCooler: setting verification date=%s device_id=%s",
            date,
            "all" if device_id is None else device_id,
        )
        manager = self._hhc()
        with manager.lock:
            count = 0
            for did, serial in manager.resolve(device_id):
                logger.info("HeaterCooler: device_id=%s (serial=%s) verification date -> %s", did, serial, date)
                manager.transport.set_verification_date(serial, date)
                count += 1
        logger.info("HeaterCooler: verification date set on %d unit(s)", count)
        return self._ok(
            MessageResponse, {"message": f"verification date set on {count} unit(s)"}
        )

    def hhc_identify(self, device_id: int | None = None) -> MessageResponse:
        """Blink the display so an operator can locate the unit(s)."""
        logger.info("HeaterCooler: identify device_id=%s", "all" if device_id is None else device_id)
        manager = self._hhc()
        with manager.lock:
            count = 0
            for did, serial in manager.resolve(device_id):
                logger.info("HeaterCooler: device_id=%s (serial=%s) blinking display to identify", did, serial)
                manager.transport.identify(serial)
                count += 1
        logger.info("HeaterCooler: identified %d unit(s)", count)
        return self._ok(MessageResponse, {"message": f"identified {count} unit(s)"})

    def hhc_set_display(
        self,
        *,
        on: bool | None = None,
        brightness: int | None = None,
        device_id: int | None = None,
    ) -> MessageResponse:
        """Turn the display on/off and/or set its brightness (0-100%).

        Pass at least one of *on* / *brightness*.
        """
        if on is None and brightness is None:
            raise ValueError("pass on= and/or brightness=")
        if brightness is not None and not 0 <= brightness <= 100:
            raise ValueError(f"brightness must be 0-100, got {brightness}")
        logger.info(
            "HeaterCooler: updating display on=%s brightness=%s device_id=%s",
            on,
            brightness,
            "all" if device_id is None else device_id,
        )
        manager = self._hhc()
        with manager.lock:
            for did, serial in manager.resolve(device_id):
                if on is not None:
                    logger.info("HeaterCooler: device_id=%s (serial=%s) display on=%s", did, serial, on)
                    manager.transport.turn_on_off_display(serial, on)
                if brightness is not None:
                    logger.info(
                        "HeaterCooler: device_id=%s (serial=%s) display brightness=%s%%", did, serial, brightness
                    )
                    manager.transport.set_display_brightness(serial, brightness)
        logger.info("HeaterCooler: display updated")
        return self._ok(MessageResponse, {"message": "display updated"})

    def hhc_self_diagnostic(
        self,
        *,
        enable: bool | None = None,
        device_id: int | None = None,
    ) -> HHCSelfDiagnosticResponse:
        """Read the self-diagnostic toggle, or set it first when *enable* is given."""
        logger.info(
            "HeaterCooler: self-diagnostic enable=%s device_id=%s",
            enable,
            "all" if device_id is None else device_id,
        )
        manager = self._hhc()
        with manager.lock:
            rows = []
            for did, serial in manager.resolve(device_id):
                if enable is not None:
                    logger.info(
                        "HeaterCooler: device_id=%s (serial=%s) setting self-diagnostic=%s", did, serial, enable
                    )
                    manager.transport.set_self_diagnostic(serial, enable)
                state = manager.transport.get_self_diagnostic(serial)
                logger.info("HeaterCooler: device_id=%s (serial=%s) self-diagnostic=%s", did, serial, state)
                rows.append({"deviceId": did, "enabled": state})
        return self._ok(HHCSelfDiagnosticResponse, {"deviceIds": rows})

    def hhc_terminate(self) -> MessageResponse:
        """Disconnect every HeaterCooler unit and release the connection."""
        manager = self._hhc()
        logger.info("HeaterCooler: terminating connection (chain_id=%s)", manager.chain_id)
        manager.terminate()
        logger.info("HeaterCooler: disconnected")
        return self._ok(MessageResponse, {"message": "HeaterCooler disconnected"})


class HeaterCoolerClient(HeaterCoolerDeviceCommands):
    """Standalone client for the Hamilton Heater Cooler -- no ``StarClient``/
    ``VantageClient`` needed. Pure Python, no VENUS runtime (see
    :mod:`hamilton_venus.heater_cooler`)::

        with HeaterCoolerClient(simulate=True) as hhc:
            hhc.hhc_connect("COM4")
    """

    def __init__(
        self,
        *,
        simulate: bool = False,
        transport: _HeaterCoolerTransport | None = None,
        sim_units: int = 1,
    ) -> None:
        self._simulate = simulate
        self._heater_cooler_transport = transport
        self._heater_cooler_sim_units = sim_units

    def close(self) -> None:
        """Release the connection, if one was ever made. Safe to call even if
        :meth:`hhc_connect` was never called (never lazily creates a manager)."""
        manager = getattr(self, "_heater_cooler_manager", None)
        if manager is not None:
            manager.terminate()

    def __enter__(self) -> HeaterCoolerClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
