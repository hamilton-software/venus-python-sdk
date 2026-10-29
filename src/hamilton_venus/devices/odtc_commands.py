"""Inheco ODTC (On-Deck Thermal Cycler) command methods for the instrument clients.

Like the HHC device group (see
:mod:`hamilton_venus.devices.heater_cooler_commands`), these do **not** go
through the VENUS runtime -- the ODTC is driven directly (see
:mod:`hamilton_venus.odtc`). Methods work with no instrument connection and
regardless of ``auto_connect`` / ``instrument_init()``.

Addressing is per-unit, not a daisy chain: :meth:`odtc_connect` registers one
physical unit per call and returns its ``device_id`` (``1..8``, the vendor
HSL's own cap). Status/temperature reads accept ``device_id=None`` (poll every
connected unit); every other method needs a specific ``device_id``.

Locking is fully internal -- :class:`~hamilton_venus.odtc.ODTCManager`
acquires one lock per connection at :meth:`odtc_connect` and holds it for the
connection's lifetime, so no method here ever takes a ``lock_id``.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import TypeVar

from hamilton_venus.exceptions import ODTCError
from hamilton_venus.models import (
    CommandResponse,
    MessageResponse,
    ODTCConfigurationResponse,
    ODTCConnectResponse,
    ODTCDeviceIdentificationResponse,
    ODTCDeviceIdsResponse,
    ODTCLogDownloadResponse,
    ODTCMethodListResponse,
    ODTCProtocolRunResponse,
    ODTCRunDataResponse,
    ODTCRunTraceResponse,
    ODTCStatusResponse,
    ODTCTemperatureResponse,
)
from hamilton_venus.odtc import ODTC_LOG_LEVELS, ODTCManager, parse_method_set, parse_stored_methods
from hamilton_venus.odtc_protocol import ODTCProtocol, render_protocol_xml

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)

# The ODTC does not go through the VENUS runtime (see the module docstring), so
# it gets none of VENUS's own request/response trace logging for free -- these
# INFO-level logger calls are this device group's only record of what it did
# and when, mirroring the HHC command group's logging style.
logger = logging.getLogger(__name__)


def _fmt_estimate(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s"


class ODTCDeviceCommands:
    """Device command group for the Inheco ODTC.

    Set :attr:`_odtc_transport_factory` on a client instance (or subclass) to
    inject a fake per-unit transport factory (``device_id -> transport``) for
    tests.
    """

    _odtc_transport_factory: object | None = None

    # -- manager plumbing ---------------------------------------------------

    def _odtc(self) -> ODTCManager:
        manager = getattr(self, "_odtc_manager", None)
        if manager is None:
            manager = ODTCManager(
                simulate=bool(getattr(self, "_simulate", False)),
                transport_factory=self._odtc_transport_factory,
            )
            self._odtc_manager = manager
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

    def odtc_connect(
        self,
        device_ip: str,
        device_port: str = "8080",
        *,
        local_ip: str = "",
        initialize: bool = True,
    ) -> ODTCConnectResponse:
        """Connect to the ODTC at *device_ip* and return its identity and state.

        Fetches the unit's SiLA description (``http://<device_ip>/odtc.wsdl``),
        starts a listener for its completion events, then issues a device
        ``Reset`` -- always, even from ``idle``, because that is how the unit
        learns where to send events. **The Reset aborts anything already running
        on the unit.** Unless *initialize* is False it is followed by
        ``Initialize``, leaving the unit ``idle``. No lock is taken (the ODTC has
        no lock command in use).

        Parameters
        ----------
        device_ip:
            IP address of the ODTC, e.g. ``"192.168.1.50"``. Must be reachable
            from this PC on the same network.
        device_port:
            Kept for compatibility with the vendor connect step; **not used** --
            the SiLA description is always fetched from ``device_ip`` on the
            default HTTP port. Leave at ``"8080"``.
        local_ip:
            This PC's address to give the unit as the target for its events
            (the ODTC connects back to it). Empty (default) picks the interface
            that routes to *device_ip*. Set it on a PC with several network
            cards. The listener uses TCP ports 18001-18008, which Windows
            Firewall must allow inbound.
        initialize:
            Run ``Initialize`` after the Reset (default). With ``False`` the unit
            stays in ``standby``, where it accepts almost nothing.

        Returns
        -------
        ODTCConnectResponse
            ``unit`` holds ``device_id`` (the handle every other command takes),
            firmware version, serial number and state.
        """
        logger.info("ODTC: connecting to %s:%s (initialize=%s)", device_ip, device_port, initialize)
        manager = self._odtc()
        with manager.lock:
            device_id = manager.connect(device_ip, device_port=device_port, local_ip=local_ip, initialize=initialize)
            transport = manager.transport_for(device_id)
            logger.info("ODTC: device_id=%s reading identification and status", device_id)
            ident = transport.get_device_identification()
            status = transport.get_status()
            unit = {
                "deviceId": device_id,
                "deviceIp": device_ip,
                "firmwareVersion": ident.get("firmwareVersion", ""),
                "serialNumber": ident.get("serialNumber", ""),
                "manufacturer": ident.get("manufacturer", ""),
                "state": status.get("state", ""),
            }
        logger.info("ODTC: connected device_id=%s serial=%s", device_id, unit["serialNumber"])
        return self._ok(ODTCConnectResponse, {"unit": unit})

    def odtc_get_device_ids(self) -> ODTCDeviceIdsResponse:
        """Return the ``device_id`` of every currently registered ODTC unit."""
        logger.info("ODTC: reading device ids")
        manager = self._odtc()
        with manager.lock:
            device_ids = manager.device_ids()
        logger.info("ODTC: %d unit(s) registered", len(device_ids))
        return self._ok(ODTCDeviceIdsResponse, {"deviceIds": device_ids})

    def odtc_get_status(self, device_id: int | None = None) -> ODTCStatusResponse:
        """Return state / locked / door-open per unit.

        Parameters
        ----------
        device_id:
            Unit to read, or ``None`` (default) for every connected unit.

        The ``state`` is one of ``startup``, ``standby``, ``idle``, ``busy``,
        ``paused``, ``inError`` (``busy`` includes a running method and door
        moves). ``locked`` is normally ``False``: this driver takes no lock.
        """
        logger.info("ODTC: reading status for device_id=%s", "all" if device_id is None else device_id)
        manager = self._odtc()
        with manager.lock:
            rows = []
            for did, transport in manager.resolve(device_id):
                status = transport.get_status()
                rows.append(
                    {
                        "deviceId": did,
                        "state": status.get("state", ""),
                        "locked": status.get("locked", False),
                        "doorOpen": status.get("doorOpen", False),
                    }
                )
        logger.info("ODTC: status read for %d unit(s): %s", len(rows), rows)
        return self._ok(ODTCStatusResponse, {"deviceIds": rows})

    def odtc_get_temperature(self, device_id: int | None = None) -> ODTCTemperatureResponse:
        """Return block + lid temperature per unit, in degrees C.

        Parameters
        ----------
        device_id:
            Unit to read, or ``None`` (default) for every connected unit.

        Can be refused for a moment while the unit is switching steps.
        """
        logger.info("ODTC: reading temperature for device_id=%s", "all" if device_id is None else device_id)
        manager = self._odtc()
        with manager.lock:
            rows = []
            for did, transport in manager.resolve(device_id):
                temps = transport.read_actual_temperature()
                rows.append(
                    {
                        "deviceId": did,
                        "blockTemperature": temps.get("blockTemperature", 0.0),
                        "lidTemperature": temps.get("lidTemperature", 0.0),
                    }
                )
        return self._ok(ODTCTemperatureResponse, {"deviceIds": rows})

    def odtc_get_device_identification(self, device_id: int) -> ODTCDeviceIdentificationResponse:
        """Return firmware version / serial number / manufacturer for one unit.

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        """
        manager = self._odtc()
        with manager.lock:
            transport = manager.transport_for(device_id)
            ident = transport.get_device_identification()
        return self._ok(
            ODTCDeviceIdentificationResponse,
            {
                "deviceId": device_id,
                "firmwareVersion": ident.get("firmwareVersion", ""),
                "serialNumber": ident.get("serialNumber", ""),
                "manufacturer": ident.get("manufacturer", ""),
            },
        )

    # -- door ------------------------------------------------------------------

    def odtc_open_door(self, device_id: int) -> MessageResponse:
        """Open the unit's plate door (done from ``idle``; takes a few seconds).

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        """
        logger.info("ODTC: device_id=%s opening door", device_id)
        manager = self._odtc()
        with manager.lock:
            manager.transport_for(device_id).open_door()
        return self._ok(MessageResponse, {"message": f"device_id {device_id} door opened"})

    def odtc_close_door(self, device_id: int) -> MessageResponse:
        """Close the unit's plate door (done from ``idle``; takes a few seconds).

        Close it before a run: the block gets hot. Parameters as
        :meth:`odtc_open_door`.
        """
        logger.info("ODTC: device_id=%s closing door", device_id)
        manager = self._odtc()
        with manager.lock:
            manager.transport_for(device_id).close_door()
        return self._ok(MessageResponse, {"message": f"device_id {device_id} door closed"})

    # -- protocol run ------------------------------------------------------------------

    def odtc_run_protocol(
        self,
        protocol: str | Path | ODTCProtocol,
        *,
        method_name: str | None = None,
        priority: int = 1,
        device_id: int,
        wait: bool = False,
        timeout: int = 3600,
    ) -> ODTCProtocolRunResponse:
        """Upload and run a PCR protocol on *device_id*.

        Bundles the vendor ``SetMethod`` with ``ExecuteMethod`` -- mirroring
        Hamilton's own ``InhecoODTCController.hsi`` ``ExecuteProtocol``, which
        combines the same two calls.

        Parameters
        ----------
        protocol:
            Either the path to an existing vendor-authored ``<MethodSet>`` XML
            file, or an :class:`~hamilton_venus.odtc_protocol.ODTCProtocol`
            built in Python (see :mod:`hamilton_venus.odtc_protocol`).
        method_name:
            Which ``<Method>``/``<PreMethod>`` in the file/protocol to run.
            Required when *protocol* is a file with more than one method;
            defaults to the protocol's own ``method_name`` when *protocol* is
            an :class:`ODTCProtocol`, or to a file's single method.
        priority:
            Execution priority sent with ``ExecuteMethod``, an integer of at least 1
            (0 is rejected by the unit; lower values are clamped up to 1). There is
            one method at a time, so leave it at the default ``1``.
        device_id:
            The handle returned by :meth:`odtc_connect` (keyword-only).
        wait:
            ``False`` (default): return as soon as the unit accepts the run --
            it then runs for minutes, so poll :meth:`odtc_get_status` or call
            :meth:`odtc_wait_for_protocol`. ``True``: block until it finishes.
        timeout:
            With ``wait=True``, the most seconds to wait for the run to finish
            (default 3600) before raising. Set it comfortably above the estimate.

        Returns
        -------
        ODTCProtocolRunResponse
            Includes ``estimated_duration_seconds``, the unit's own estimate of
            the run (``None`` if it gave none). A stepped ``Method`` only starts
            after a ``PreMethod`` has finished; a PreMethod has no natural end
            beyond reaching temperature. Build protocols with
            :class:`~hamilton_venus.odtc_protocol.ODTCProtocolBuilder`.
        """
        manager = self._odtc()
        with manager.lock:
            transport = manager.transport_for(device_id)
            if isinstance(protocol, ODTCProtocol):
                xml_text = render_protocol_xml(protocol)
                resolved_name = method_name or protocol.method_name
                logger.info(
                    "ODTC: device_id=%s uploading generated protocol %r", device_id, resolved_name
                )
                transport.set_method(xml_text)
            else:
                path = Path(protocol)
                xml_text = _read_protocol_file(path)
                resolved_name = method_name or _single_method_name(xml_text)
                _require_method_in_file(resolved_name, xml_text, path)
                logger.info(
                    "ODTC: device_id=%s uploading protocol file %s (method=%r)", device_id, path, resolved_name
                )
                transport.set_method(xml_text)

            logger.info("ODTC: device_id=%s executing method %r", device_id, resolved_name)
            request_id = transport.execute_method(resolved_name, priority)
            manager.note_request_id(device_id, request_id)
            estimate = getattr(transport, "last_estimated_seconds", None)
            logger.info(
                "ODTC: device_id=%s method %r accepted; estimated duration %s",
                device_id,
                resolved_name,
                _fmt_estimate(estimate),
            )

            if wait:
                logger.info(
                    "ODTC: device_id=%s waiting for method %r to complete (timeout=%ss)",
                    device_id,
                    resolved_name,
                    timeout,
                )
                transport.wait_for_end_of_execute_method(request_id, timeout)
                logger.info("ODTC: device_id=%s method %r complete", device_id, resolved_name)

        return self._ok(
            ODTCProtocolRunResponse,
            {
                "deviceId": device_id,
                "methodName": resolved_name,
                "requestId": request_id,
                "waited": wait,
                "estimatedDurationSeconds": estimate,
            },
        )

    def odtc_import_methods(self, protocol_file: str | Path, *, device_id: int) -> ODTCMethodListResponse:
        """Upload every method in a vendor ``<MethodSet>`` XML file to the unit
        *without running any of them*.

        The unit stores them (persistently, alongside its own), so afterwards
        they show up in :meth:`odtc_list_methods` and run by name with
        :meth:`odtc_run_stored_method`. Returns the methods that were in the file.
        A file holding ``<DeleteAllMethods>true</DeleteAllMethods>`` would make
        the unit discard its other methods; that is refused here.

        Parameters
        ----------
        protocol_file:
            Path of a vendor ``<MethodSet>`` XML file (e.g. Inheco's exported
            protocols); UTF-8, with or without a BOM. It must contain at least one
            ``<Method>`` or ``<PreMethod>``. Methods with a name already on the
            unit replace it.
        device_id:
            The handle returned by :meth:`odtc_connect` (keyword-only).
        """
        path = Path(protocol_file)
        xml_text = _read_protocol_file(path)
        methods = parse_method_set(xml_text)
        if not methods:
            raise ODTCError(f"{path} contains no <Method> or <PreMethod> entries")
        if "<DeleteAllMethods>true</DeleteAllMethods>" in xml_text.replace(" ", ""):
            raise ODTCError(f"{path} asks the unit to delete all its stored methods; refusing to upload it")
        logger.info("ODTC: device_id=%s importing %d method(s) from %s", device_id, len(methods), path)
        manager = self._odtc()
        with manager.lock:
            manager.transport_for(device_id).set_method(xml_text)
        return self._ok(ODTCMethodListResponse, {"deviceId": device_id, "methods": methods})

    def odtc_download_logs(
        self, device_id: int, dest_dir: str | Path = "odtc_logs", *, include_traces: bool = False
    ) -> ODTCLogDownloadResponse:
        """Copy the unit's log files to *dest_dir* (created if needed).

        Not a SiLA command: the unit serves its logs over anonymous FTP, and this
        copies everything under its ``Logs``, ``Odtc``, ``SiLA`` and ``Backup``
        folders, keeping the layout -- ``SiLA/Logs/InhecoSiLA.log`` is the SiLA
        stack's own log and the first place to look when the unit reports an
        error state. ``include_traces=True`` also copies ``Traces`` (one folder
        per day, which can be large). Not the same as :meth:`odtc_get_run_data`,
        which is the temperature trace of the last run.

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        dest_dir:
            Local folder to copy into (default ``"odtc_logs"`` in the current
            directory); created if missing, existing files are overwritten.
        include_traces:
            Also copy ``Traces`` (default ``False``): one CSV per run, so it can
            be many megabytes.
        """
        dest = Path(dest_dir)
        logger.info("ODTC: device_id=%s downloading logs to %s (traces=%s)", device_id, dest, include_traces)
        manager = self._odtc()
        with manager.lock:
            files = manager.transport_for(device_id).download_logs(str(dest), include_traces)
        logger.info("ODTC: device_id=%s downloaded %d file(s)", device_id, len(files))
        return self._ok(
            ODTCLogDownloadResponse, {"deviceId": device_id, "directory": str(dest.resolve()), "files": files}
        )

    def odtc_download_run_trace(
        self, device_id: int, dest_dir: str | Path = "odtc_traces", *, method_name: str | None = None
    ) -> ODTCRunTraceResponse:
        """Download and parse the unit's own temperature trace of its latest run.

        Every run leaves a trace on the unit (``Traces/<date>/<start time>.csv``,
        about 5 samples a second with many sensor columns). This fetches the
        newest one -- or the newest for *method_name*, which is how to be sure it
        is the run you just did -- saves the whole file under *dest_dir*, and
        returns the block target / block actual / lid temperatures per sample.
        Raises if no matching trace is found among the newest few. Prefer this to
        :meth:`odtc_get_run_data`, which was seen returning an older run's trace.

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        dest_dir:
            Local folder to save the trace CSV into (default ``"odtc_traces"``);
            created if missing.
        method_name:
            Only accept a trace of this method (the newest few are searched).
            ``None`` (default) takes the very latest run whatever it was. The
            file can take a few seconds to appear after a run ends, so retry.
        """
        manager = self._odtc()
        with manager.lock:
            found = manager.transport_for(device_id).download_run_trace(str(Path(dest_dir)), method_name)
        if found is None:
            what = f"for method {method_name!r} " if method_name else ""
            raise ODTCError(f"no run trace {what}found among the newest traces on the unit")
        logger.info(
            "ODTC: device_id=%s downloaded trace %s (%d samples)", device_id, found["remote"], len(found["rows"])
        )
        return self._ok(
            ODTCRunTraceResponse,
            {
                "deviceId": device_id,
                "methodName": found["methodName"],
                "startedAt": found["startedAt"],
                "remote": found["remote"],
                "path": found["path"],
                "rows": found["rows"],
            },
        )

    def odtc_run_stored_method(
        self,
        method_name: str,
        *,
        device_id: int,
        priority: int = 1,
        wait: bool = False,
        timeout: int = 3600,
    ) -> ODTCProtocolRunResponse:
        """Run a method that is *already stored on the unit*, by name.

        Nothing is uploaded -- use :meth:`odtc_list_methods` to see what the
        unit holds (it ships with ``PRE25``, ``PRE55`` and others), or
        :meth:`odtc_run_protocol` to upload and run your own.

        Parameters
        ----------
        method_name:
            Exact, case-sensitive name of a ``Method`` or ``PreMethod`` on the unit.
        device_id:
            The handle returned by :meth:`odtc_connect` (keyword-only).
        priority:
            Execution priority, at least 1 (default 1); see :meth:`odtc_run_protocol`.
        wait:
            ``False`` (default) returns once the run is accepted; ``True`` blocks
            until it finishes.
        timeout:
            With ``wait=True``, the most seconds to wait (default 3600).
        """
        manager = self._odtc()
        with manager.lock:
            transport = manager.transport_for(device_id)
            logger.info("ODTC: device_id=%s executing stored method %r", device_id, method_name)
            request_id = transport.execute_method(method_name, priority)
            manager.note_request_id(device_id, request_id)
            estimate = getattr(transport, "last_estimated_seconds", None)
            logger.info(
                "ODTC: device_id=%s method %r accepted; estimated duration %s",
                device_id,
                method_name,
                _fmt_estimate(estimate),
            )
            if wait:
                transport.wait_for_end_of_execute_method(request_id, timeout)
        return self._ok(
            ODTCProtocolRunResponse,
            {
                "deviceId": device_id,
                "methodName": method_name,
                "requestId": request_id,
                "waited": wait,
                "estimatedDurationSeconds": estimate,
            },
        )

    def odtc_wait_for_protocol(
        self, device_id: int, *, request_id: str | None = None, timeout: int = 3600
    ) -> MessageResponse:
        """Block until *device_id*'s in-progress protocol run completes.

        *request_id* defaults to the id returned by the most recent
        :meth:`odtc_run_protocol` call on this unit.

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        request_id:
            Which run to wait for; default the last one started on this unit.
        timeout:
            Most seconds to wait (default 3600) before raising; set it above the
            run's ``estimated_duration_seconds``.
        """
        manager = self._odtc()
        with manager.lock:
            resolved_id = request_id or manager.last_request_id(device_id)
            if not resolved_id:
                raise ODTCError(
                    f"no in-progress request for device_id {device_id}; call odtc_run_protocol first "
                    "or pass request_id explicitly"
                )
            logger.info("ODTC: device_id=%s waiting for request %r (timeout=%ss)", device_id, resolved_id, timeout)
            manager.transport_for(device_id).wait_for_end_of_execute_method(resolved_id, timeout)
        logger.info("ODTC: device_id=%s wait complete", device_id)
        return self._ok(MessageResponse, {"message": f"device_id {device_id} protocol complete"})

    def odtc_stop_method(self, device_id: int) -> MessageResponse:
        """Stop the in-progress method on *device_id*; harmless when the unit is idle.

        Call it before :meth:`odtc_terminate_device`. If the unit is still busy
        finishing another command (e.g. right after :meth:`odtc_abort`) the stop
        is retried for up to a minute.

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        """
        logger.info("ODTC: device_id=%s stopping method", device_id)
        manager = self._odtc()
        with manager.lock:
            manager.transport_for(device_id).stop_method()
        return self._ok(MessageResponse, {"message": f"device_id {device_id} method stopped"})

    def odtc_pause(self, device_id: int) -> MessageResponse:
        """Pause the in-progress method on *device_id*.

        **Unreliable on the unit this was tested on.** The request is accepted
        (state ``busy``, sub-state ``ExecuteMethod: pauseRequested``) but the
        unit never reaches ``paused`` -- not on a plain hold (``PreMethod``) and
        not on a stepped method with 30 s steps (watched for over a minute) --
        so this call raises a timeout. While the request is pending the unit
        refuses ``odtc_resume``, ``odtc_stop_method`` and temperature reads,
        and stays that way after the method would have finished;
        :meth:`odtc_reset` is the only recovery found.
        """
        logger.info("ODTC: device_id=%s pausing", device_id)
        manager = self._odtc()
        with manager.lock:
            manager.transport_for(device_id).pause()
        return self._ok(MessageResponse, {"message": f"device_id {device_id} paused"})

    def odtc_resume(self, device_id: int) -> MessageResponse:
        """Resume a paused method on *device_id* (see the caveats on :meth:`odtc_pause`).

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        """
        logger.info("ODTC: device_id=%s resuming", device_id)
        manager = self._odtc()
        with manager.lock:
            manager.transport_for(device_id).do_continue()
        return self._ok(MessageResponse, {"message": f"device_id {device_id} resumed"})

    def odtc_abort(self, device_id: int) -> MessageResponse:
        """Abort the in-progress method on *device_id*.

        Harsher than :meth:`odtc_stop_method`: it cancels the current command
        immediately and may leave the unit needing a :meth:`odtc_reset`; prefer
        stop.

        Parameters
        ----------
        device_id:
            The handle returned by :meth:`odtc_connect`.
        """
        logger.info("ODTC: device_id=%s aborting", device_id)
        manager = self._odtc()
        with manager.lock:
            manager.transport_for(device_id).abort()
        return self._ok(MessageResponse, {"message": f"device_id {device_id} aborted"})

    def odtc_reset(
        self,
        device_id: int,
        *,
        timeout: int = 60,
        simulate_on_device_base: bool = False,
        initialize: bool = True,
    ) -> MessageResponse:
        """Reset *device_id* (firmware-level reset) -- aborts any running method.

        This is the recovery path for a stuck unit (e.g. a pending pause, or
        ``inError``). A reset leaves the unit in ``standby``, where it accepts
        almost nothing, so by default it is followed by ``Initialize`` to bring
        it back to ``idle``; pass ``initialize=False`` to stay in ``standby``
        (the only state that accepts configuration changes).
        """
        logger.info("ODTC: device_id=%s resetting (timeout=%ss)", device_id, timeout)
        manager = self._odtc()
        with manager.lock:
            transport = manager.transport_for(device_id)
            transport.reset(timeout, simulate_on_device_base)
            if initialize:
                transport.initialize()
        return self._ok(MessageResponse, {"message": f"device_id {device_id} reset"})

    def odtc_get_run_data(self, device_id: int) -> ODTCRunDataResponse:
        """Return the unit's own temperature trace of its most recent run.

        One row per sample (about 1 per second): ``series`` (the run's start
        time), ``elapsedMs``, ``targetTemperature``, ``currentTemperature`` and
        ``lidTemperature`` in degrees C. **Not reliable as "the last run":** after
        two runs that completed normally it still returned the trace of an older,
        stopped one. Use :meth:`odtc_download_run_trace`, which reads the unit's
        per-run trace files and can match on the method name.
        """
        manager = self._odtc()
        with manager.lock:
            rows = manager.transport_for(device_id).get_last_data()
        return self._ok(ODTCRunDataResponse, {"deviceId": device_id, "rows": rows})

    # -- configuration / admin ------------------------------------------------------------------

    def odtc_get_parameters(self, device_id: int) -> ODTCConfigurationResponse:
        """Return the unit's raw device parameters XML (includes every method stored on it)."""
        manager = self._odtc()
        with manager.lock:
            xml_text = manager.transport_for(device_id).get_parameters()
        return self._ok(ODTCConfigurationResponse, {"deviceId": device_id, "xml": xml_text})

    def odtc_list_methods(self, device_id: int) -> ODTCMethodListResponse:
        """List the methods stored on the unit, by name.

        Each entry is a ``PreMethod`` (a plain block + lid temperature hold) or
        a ``Method`` (a stepped/cycling program). Run one already on the unit
        by name via :meth:`odtc_run_stored_method`.
        """
        manager = self._odtc()
        with manager.lock:
            xml_text = manager.transport_for(device_id).get_parameters()
        return self._ok(
            ODTCMethodListResponse, {"deviceId": device_id, "methods": parse_stored_methods(xml_text)}
        )

    def odtc_set_parameter(self, name: str, type_: str, value: str, device_id: int) -> MessageResponse:
        """Set one device parameter by name."""
        logger.info("ODTC: device_id=%s setting parameter %s=%s (type=%s)", device_id, name, value, type_)
        manager = self._odtc()
        with manager.lock:
            manager.transport_for(device_id).set_parameters(name, type_, value)
        return self._ok(MessageResponse, {"message": f"device_id {device_id} parameter {name} set"})

    def odtc_set_log_level(self, level: str, device_id: int) -> MessageResponse:
        """Set the *device's own* log level: ``"DEBUG"``, ``"INFO"``, ``"WARN"``, ``"ERROR"`` or ``"FATAL"``.

        Per the Hamilton help file this should only be changed when requested
        by Hamilton or Inheco personnel. The unit only accepts configuration
        changes in its ``standby`` state, so from ``idle`` this runs a
        Reset -> configure -> Initialize round trip (about a minute) and
        refuses while a method is running.
        """
        level = level.strip().upper()
        if level not in ODTC_LOG_LEVELS:
            raise ODTCError(f"invalid log level {level!r}; expected one of {', '.join(ODTC_LOG_LEVELS)}")
        manager = self._odtc()
        with manager.lock:
            manager.transport_for(device_id).set_log_level(level)
        return self._ok(MessageResponse, {"message": f"device_id {device_id} log level set to {level}"})

    def odtc_set_csv_separator(self, character: str, device_id: int) -> MessageResponse:
        """Set the separator character used in the data ``odtc_get_run_data`` reports.

        Use a single character such as ``";"`` or ``","`` -- per the Hamilton
        help file, separators like ``"."`` or ``":"`` may cripple the data.
        """
        if len(character) != 1:
            raise ODTCError(f"CSV separator must be a single character, got {character!r}")
        manager = self._odtc()
        with manager.lock:
            manager.transport_for(device_id).set_csv_separator(character)
        return self._ok(MessageResponse, {"message": f"device_id {device_id} CSV separator set to {character!r}"})

    def odtc_set_date_time(self, date_time: str | datetime.datetime, device_id: int) -> MessageResponse:
        """Set the unit's onboard clock.

        Pass a ``datetime`` (naive values are taken as UTC; aware ones are
        converted to UTC) or a string already in the device's
        ``YYYY-MM-DDTHH:MM:SSZ`` format. Like :meth:`odtc_set_log_level`, this
        needs the unit's ``standby`` state and so runs a Reset -> configure ->
        Initialize round trip (about a minute); it refuses while a method runs.
        """
        if isinstance(date_time, datetime.datetime):
            if date_time.tzinfo is not None:
                date_time = date_time.astimezone(datetime.UTC)
            date_time = date_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        manager = self._odtc()
        with manager.lock:
            manager.transport_for(device_id).set_date_time(date_time)
        return self._ok(MessageResponse, {"message": f"device_id {device_id} clock set to {date_time}"})

    def odtc_add_allowed_return_code(self, code: int, device_id: int) -> MessageResponse:
        """Whitelist a vendor return *code* as non-fatal for *device_id*."""
        manager = self._odtc()
        with manager.lock:
            manager.transport_for(device_id).add_allowed_return_code(code)
        return self._ok(MessageResponse, {"message": f"device_id {device_id} allowed return code {code} added"})

    # -- lifecycle ------------------------------------------------------------------

    def odtc_terminate_device(self, device_id: int) -> MessageResponse:
        """Disconnect one ODTC unit. Does **not** stop a running method.

        Don't disconnect while a method is still running: the unit reports its
        completion to this PC, and if nobody is listening any more it logs an
        event error and drops into ``inError`` (the next :meth:`odtc_connect`
        clears that with a Reset). Wait for the run to finish
        (:meth:`odtc_wait_for_protocol`) or call :meth:`odtc_stop_method` first.
        """
        logger.info("ODTC: device_id=%s terminating", device_id)
        manager = self._odtc()
        with manager.lock:
            manager.terminate_one(device_id)
        return self._ok(MessageResponse, {"message": f"device_id {device_id} disconnected"})

    def odtc_terminate(self) -> MessageResponse:
        """Disconnect every registered ODTC unit. Does **not** stop running methods --
        see :meth:`odtc_terminate_device` for why to wait for or stop them first."""
        manager = self._odtc()
        logger.info("ODTC: terminating all units (%s)", manager.device_ids())
        manager.terminate()
        logger.info("ODTC: all units disconnected")
        return self._ok(MessageResponse, {"message": "ODTC disconnected"})


class ODTCClient(ODTCDeviceCommands):
    """Standalone client for the Inheco ODTC -- no ``StarClient``/``VantageClient``
    needed. Pure Python, no VENUS runtime (see :mod:`hamilton_venus.odtc`)::

        with ODTCClient(simulate=True) as odtc:
            odtc.odtc_connect("192.168.1.50")
    """

    def __init__(self, *, simulate: bool = False, transport_factory: object | None = None) -> None:
        self._simulate = simulate
        self._odtc_transport_factory = transport_factory

    def close(self) -> None:
        """Disconnect every registered unit, if any were ever connected. Safe
        to call even if :meth:`odtc_connect` was never called (never lazily
        creates a manager)."""
        manager = getattr(self, "_odtc_manager", None)
        if manager is not None:
            manager.terminate()

    def __enter__(self) -> ODTCClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _read_protocol_file(path: Path) -> str:
    """Read a vendor protocol file. Hamilton's own files start with a UTF-8 BOM,
    which is not valid at the start of an XML *string*, so decode with ``utf-8-sig``."""
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ODTCError(f"could not read protocol file {path}: {exc}") from exc


def _require_method_in_file(name: str, xml_text: str, path: Path) -> None:
    names = [m["name"] for m in parse_method_set(xml_text)]
    if name not in names:
        raise ODTCError(f"{path} has no method named {name!r}; it contains {names!r}")


def _single_method_name(xml_text: str) -> str:
    """Resolve the implicit method name from a vendor file with exactly one
    ``<Method>``/``<PreMethod>`` entry; raises :class:`ODTCError` otherwise."""
    names: list[str] = [m["name"] for m in parse_method_set(xml_text)]
    if len(names) == 1:
        return names[0]
    raise ODTCError(
        f"protocol file has {len(names)} methods ({names!r}); pass method_name= to pick one"
    )


__all__ = ["ODTCClient", "ODTCDeviceCommands"]
