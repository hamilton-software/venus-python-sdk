"""Unit tests for ODTCDeviceCommands / ODTCClient (pure-Python, no VENUS runtime)."""

from __future__ import annotations

from typing import ClassVar

import pytest

from hamilton_venus import odtc as odtc_module
from hamilton_venus.devices.odtc_commands import ODTCClient
from hamilton_venus.exceptions import ODTCError
from hamilton_venus.odtc_protocol import ODTCProtocolBuilder, ODTCStep


def _client() -> ODTCClient:
    return ODTCClient(simulate=True)


class TestODTCConnect:
    def test_connect_bundles_identification_and_status(self):
        client = _client()
        result = client.odtc_connect("192.168.1.50")

        assert result.return_status == "Success"
        unit = result.return_parameters.unit
        assert unit.device_id == 1
        assert unit.device_ip == "192.168.1.50"
        assert unit.serial_number == "ODTC-SIM-001"
        assert unit.firmware_version

    def test_connect_assigns_sequential_device_ids(self):
        client = _client()
        a = client.odtc_connect("192.168.1.50").return_parameters.unit.device_id
        b = client.odtc_connect("192.168.1.51").return_parameters.unit.device_id
        assert (a, b) == (1, 2)

    def test_get_device_ids(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        client.odtc_connect("192.168.1.51")
        ids = client.odtc_get_device_ids().return_parameters.device_ids
        assert ids == [1, 2]

    def test_commands_before_connect_raise(self):
        client = _client()
        with pytest.raises(ODTCError, match="no ODTC connected"):
            client.odtc_get_status()


class TestODTCStatusAndTemperature:
    def test_get_status_all_units(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        client.odtc_connect("192.168.1.51")
        rows = client.odtc_get_status().return_parameters.device_ids
        assert [r.device_id for r in rows] == [1, 2]
        assert all(r.state == "Idle" for r in rows)

    def test_get_temperature_single_device(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        client.odtc_connect("192.168.1.51")
        rows = client.odtc_get_temperature(device_id=2).return_parameters.device_ids
        assert [r.device_id for r in rows] == [2]

    def test_get_device_identification(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        result = client.odtc_get_device_identification(device_id=1)
        assert result.return_parameters.serial_number == "ODTC-SIM-001"


class TestODTCDoor:
    def test_open_close_door(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        client.odtc_open_door(device_id=1)
        assert client.odtc_get_status(device_id=1).return_parameters.device_ids[0].door_open is True
        client.odtc_close_door(device_id=1)
        assert client.odtc_get_status(device_id=1).return_parameters.device_ids[0].door_open is False


class TestODTCRunProtocol:
    def test_run_generated_protocol_and_wait(self):
        client = _client()
        client.odtc_connect("192.168.1.50")

        builder = ODTCProtocolBuilder("QuickCycle")
        builder.add_hold(95, 5, slope=2)
        builder.add_cycle(
            [ODTCStep(temperature=60, hold_seconds=5), ODTCStep(temperature=72, hold_seconds=5)], repeats=2
        )
        protocol = builder.build()

        result = client.odtc_run_protocol(protocol, device_id=1, wait=True)
        assert result.return_parameters.method_name == "QuickCycle"
        assert result.return_parameters.waited is True
        assert result.return_parameters.request_id

        status = client.odtc_get_status(device_id=1).return_parameters.device_ids[0]
        assert status.state == "Idle"

        run_data = client.odtc_get_run_data(device_id=1).return_parameters.rows
        assert len(run_data) > 0

    def test_run_without_wait_then_wait_for_protocol(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        builder = ODTCProtocolBuilder("Hold25")
        builder.add_hold(25, 1)
        client.odtc_run_protocol(builder.build(), device_id=1, wait=False)

        client.odtc_wait_for_protocol(device_id=1)
        status = client.odtc_get_status(device_id=1).return_parameters.device_ids[0]
        assert status.state == "Idle"

    def test_wait_for_protocol_without_a_run_raises(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        with pytest.raises(ODTCError, match="no in-progress request"):
            client.odtc_wait_for_protocol(device_id=1)

    def test_run_protocol_from_file(self, tmp_path):
        client = _client()
        client.odtc_connect("192.168.1.50")

        xml_path = tmp_path / "protocol.xml"
        xml_path.write_text(
            '<?xml version="1.0"?><MethodSet>'
            '<PreMethod methodName="Warm" dateTime="2026-01-01T00:00:00">'
            "<TargetBlockTemperature>37</TargetBlockTemperature>"
            "<TargetLidTemp>105</TargetLidTemp>"
            "</PreMethod></MethodSet>",
            encoding="utf-8",
        )
        result = client.odtc_run_protocol(xml_path, device_id=1, wait=True)
        assert result.return_parameters.method_name == "Warm"


class TestODTCRunControl:
    def test_stop_pause_resume_abort(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        builder = ODTCProtocolBuilder("Hold25")
        builder.add_hold(25, 1)
        client.odtc_run_protocol(builder.build(), device_id=1, wait=False)

        client.odtc_pause(device_id=1)
        assert client.odtc_get_status(device_id=1).return_parameters.device_ids[0].state == "Paused"
        client.odtc_resume(device_id=1)
        client.odtc_abort(device_id=1)
        assert client.odtc_get_status(device_id=1).return_parameters.device_ids[0].state == "Idle"

    def test_reset(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        result = client.odtc_reset(device_id=1)
        assert "reset" in result.return_parameters.message


class TestODTCAdmin:
    def test_parameters_roundtrip(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        params = client.odtc_get_parameters(device_id=1)
        assert params.return_parameters.xml

    def test_set_parameter_and_misc_admin_calls_do_not_raise(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        client.odtc_set_parameter("Foo", "int", "1", device_id=1)
        client.odtc_set_log_level("info", device_id=1)
        client.odtc_set_csv_separator(";", device_id=1)
        client.odtc_set_date_time("2026-01-01T00:00:00Z", device_id=1)
        client.odtc_add_allowed_return_code(42, device_id=1)

    def test_removed_commands_are_gone(self):
        # Removed deliberately: set_network_config can take a unit off the
        # network, and get_configuration needs an unknown password.
        client = _client()
        assert not hasattr(client, "odtc_set_network_config")
        assert not hasattr(client, "odtc_get_configuration")

    def test_log_level_is_validated(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        with pytest.raises(ODTCError, match="invalid log level"):
            client.odtc_set_log_level("LOUD", device_id=1)

    def test_csv_separator_must_be_one_character(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        with pytest.raises(ODTCError, match="single character"):
            client.odtc_set_csv_separator(";;", device_id=1)

    def test_date_time_datetime_is_sent_as_utc_z_string(self):
        import datetime

        sent = []
        client = _client()
        client.odtc_connect("192.168.1.50")
        transport = client._odtc().transport_for(1)
        transport.set_date_time = sent.append  # type: ignore[method-assign]
        client.odtc_set_date_time(datetime.datetime(2026, 9, 23, 12, 30, 5), device_id=1)
        aware = datetime.datetime(2026, 9, 23, 14, 30, 5, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
        client.odtc_set_date_time(aware, device_id=1)
        assert sent == ["2026-09-23T12:30:05Z", "2026-09-23T12:30:05Z"]


class TestODTCStoredMethods:
    def test_list_methods_shows_the_units_seeded_methods(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        methods = {m.name: m for m in client.odtc_list_methods(device_id=1).return_parameters.methods}
        assert {"PRE25", "PRE55"} <= set(methods)
        assert methods["PRE55"].kind == "PreMethod"
        assert methods["PRE55"].target_block_temperature == 55

    def test_uploaded_method_appears_in_the_list(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        builder = ODTCProtocolBuilder("MyPCR")
        builder.add_hold(95, 5)
        client.odtc_run_protocol(builder.build(), device_id=1)
        methods = {m.name: m for m in client.odtc_list_methods(device_id=1).return_parameters.methods}
        assert methods["MyPCR"].kind == "Method"
        assert methods["MyPCR"].step_count == 1

    def test_run_stored_method_by_name(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        result = client.odtc_run_stored_method("PRE55", device_id=1, wait=True)
        assert result.return_parameters.method_name == "PRE55"
        temps = client.odtc_get_temperature(device_id=1).return_parameters.device_ids[0]
        assert temps.block_temperature == pytest.approx(55, abs=0.5)

    def test_run_unknown_stored_method_raises(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        with pytest.raises(ODTCError, match="no method downloaded named"):
            client.odtc_run_stored_method("NOPE", device_id=1)


class TestParseStoredMethods:
    def test_real_device_payload_shape(self):
        from hamilton_venus.odtc import parse_stored_methods

        payload = (
            '<?xml version="1.0" encoding="utf-8"?><ResponseData><ParameterSet><Parameter name="MethodsXML"><String>'
            "&lt;?xml version=&quot;1.0&quot; encoding=&quot;utf-8&quot;?&gt;&lt;MethodSet&gt;"
            "&lt;DeleteAllMethods&gt;false&lt;/DeleteAllMethods&gt;"
            "&lt;PreMethod methodName=&quot;PRE25&quot; creator=&quot;HAN&quot;&gt;"
            "&lt;TargetBlockTemperature&gt;25&lt;/TargetBlockTemperature&gt;"
            "&lt;TargetLidTemp&gt;110&lt;/TargetLidTemp&gt;&lt;/PreMethod&gt;"
            "&lt;Method methodName=&quot;M1&quot; creator=&quot;X&quot;&gt;&lt;Step/&gt;&lt;Step/&gt;&lt;/Method&gt;"
            "&lt;/MethodSet&gt;</String></Parameter></ParameterSet></ResponseData>"
        )
        assert parse_stored_methods(payload) == [
            {
                "name": "PRE25",
                "kind": "PreMethod",
                "creator": "HAN",
                "targetBlockTemperature": 25.0,
                "targetLidTemperature": 110.0,
            },
            {"name": "M1", "kind": "Method", "creator": "X", "stepCount": 2},
        ]

    def test_payload_without_methods_is_empty(self):
        from hamilton_venus.odtc import parse_stored_methods

        assert parse_stored_methods("<ResponseData><ParameterSet/></ResponseData>") == []


class TestODTCTermination:
    def test_terminate_one_device(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        client.odtc_connect("192.168.1.51")
        client.odtc_terminate_device(device_id=1)
        assert client.odtc_get_device_ids().return_parameters.device_ids == [2]

    def test_terminate_all(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        client.odtc_connect("192.168.1.51")
        result = client.odtc_terminate()
        assert result.return_parameters.message == "ODTC disconnected"
        with pytest.raises(ODTCError):
            client.odtc_get_status()

    def test_close_on_unused_client_is_a_noop(self):
        client = ODTCClient(simulate=True)
        client.close()  # must not construct a manager, must not raise
        assert getattr(client, "_odtc_manager", None) is None

    def test_close_terminates_every_unit(self):
        client = _client()
        client.odtc_connect("192.168.1.50")
        client.odtc_connect("192.168.1.51")

        client.close()

        with pytest.raises(ODTCError):
            client.odtc_get_status()

    def test_context_manager_closes_on_exit(self):
        with ODTCClient(simulate=True) as client:
            client.odtc_connect("192.168.1.50")
            device_ids = client.odtc_get_device_ids().return_parameters.device_ids
            assert device_ids == [1]
        with pytest.raises(ODTCError):
            client.odtc_get_status()


class TestRealClientUsesSoapTransport:
    def test_unsimulated_client_selects_soap_transport(self):
        # The SOAP transport talks to the device's WSDL directly and needs
        # no local vendor COM driver, so simulate=False always selects it
        # regardless of odtc_available() -- constructing it does no I/O.
        client = ODTCClient()
        manager = client._odtc()
        assert isinstance(manager._make_transport(1), odtc_module._SoapODTCTransport)


_TWO_METHOD_FILE = (
    '<?xml version="1.0" encoding="utf-8"?>\r\n<MethodSet>\r\n'
    '  <PreMethod methodName="FilePre" creator="T"><TargetBlockTemperature>8</TargetBlockTemperature>'
    "<TargetLidTemp>60</TargetLidTemp></PreMethod>\r\n"
    '  <Method methodName="FileStepped" creator="T"><Variant>960000</Variant><PostHeating>true</PostHeating>'
    "<Step><Number>1</Number><Slope>2</Slope><PlateauTemperature>30</PlateauTemperature><PlateauTime>1</PlateauTime>"
    "<GotoNumber>0</GotoNumber><LoopNumber>0</LoopNumber><LidTemp>60</LidTemp></Step></Method>\r\n"
    "</MethodSet>\r\n"
)


def _write_bom_file(tmp_path, text=_TWO_METHOD_FILE):
    path = tmp_path / "methods.xml"
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))  # Hamilton's files start with a UTF-8 BOM
    return path


class TestODTCProtocolFiles:
    def test_import_methods_stores_them_without_running(self, tmp_path):
        client = _client()
        client.odtc_connect("192.168.1.50")
        imported = client.odtc_import_methods(_write_bom_file(tmp_path), device_id=1)
        assert [(m.name, m.kind) for m in imported.return_parameters.methods] == [
            ("FilePre", "PreMethod"),
            ("FileStepped", "Method"),
        ]
        stored = {m.name for m in client.odtc_list_methods(device_id=1).return_parameters.methods}
        assert {"FilePre", "FileStepped"} <= stored
        status = client.odtc_get_status(device_id=1).return_parameters.device_ids[0]
        assert status.state == "Idle"  # nothing was started

    def test_imported_method_runs_by_name(self, tmp_path):
        client = _client()
        client.odtc_connect("192.168.1.50")
        client.odtc_import_methods(_write_bom_file(tmp_path), device_id=1)
        result = client.odtc_run_stored_method("FilePre", device_id=1, wait=True)
        assert result.return_parameters.method_name == "FilePre"

    def test_run_protocol_file_needs_a_name_when_it_has_several_methods(self, tmp_path):
        client = _client()
        client.odtc_connect("192.168.1.50")
        with pytest.raises(ODTCError, match="pass method_name"):
            client.odtc_run_protocol(_write_bom_file(tmp_path), device_id=1)

    def test_run_protocol_file_with_a_name_uploads_and_runs(self, tmp_path):
        client = _client()
        client.odtc_connect("192.168.1.50")
        result = client.odtc_run_protocol(
            _write_bom_file(tmp_path), method_name="FilePre", device_id=1, wait=True
        )
        assert result.return_parameters.method_name == "FilePre"

    def test_unknown_method_name_is_caught_before_uploading(self, tmp_path):
        client = _client()
        client.odtc_connect("192.168.1.50")
        with pytest.raises(ODTCError, match="has no method named 'Nope'"):
            client.odtc_run_protocol(_write_bom_file(tmp_path), method_name="Nope", device_id=1)

    def test_file_that_deletes_all_methods_is_refused(self, tmp_path):
        bad = _TWO_METHOD_FILE.replace("<MethodSet>", "<MethodSet><DeleteAllMethods>true</DeleteAllMethods>")
        client = _client()
        client.odtc_connect("192.168.1.50")
        with pytest.raises(ODTCError, match="delete all"):
            client.odtc_import_methods(_write_bom_file(tmp_path, bad), device_id=1)

    def test_missing_file_raises_odtc_error(self, tmp_path):
        client = _client()
        client.odtc_connect("192.168.1.50")
        with pytest.raises(ODTCError, match="could not read"):
            client.odtc_import_methods(tmp_path / "nope.xml", device_id=1)


class TestODTCDownloadLogs:
    def test_downloads_into_the_destination(self, tmp_path):
        client = _client()
        client.odtc_connect("192.168.1.50")
        result = client.odtc_download_logs(1, tmp_path / "logs")
        files = result.return_parameters.files
        assert {f.remote for f in files} == {"/SiLA/Logs/InhecoSiLA.log", "/Odtc/Logs/Log_#1.csv"}
        assert all((tmp_path / "logs").resolve() in __import__("pathlib").Path(f.path).resolve().parents for f in files)
        assert all(f.size > 0 for f in files)

    def test_traces_are_opt_in(self, tmp_path):
        client = _client()
        client.odtc_connect("192.168.1.50")
        default = client.odtc_download_logs(1, tmp_path / "a").return_parameters.files
        with_traces = client.odtc_download_logs(1, tmp_path / "b", include_traces=True).return_parameters.files
        assert not any("Traces" in f.remote for f in default)
        assert any("Traces" in f.remote for f in with_traces)


class _FakeFtp:
    """Just enough of ftplib.FTP for _ftp_download_tree: a dict of path -> listing/bytes."""

    tree: ClassVar[dict] = {}

    def __init__(self, host, timeout=None):
        self.cwd_path = "/"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self):
        pass

    def cwd(self, path):
        import ftplib

        if path not in self.tree:
            raise ftplib.error_perm("550 no such folder")
        self.cwd_path = path

    def retrlines(self, cmd, callback):
        for line in self.tree[self.cwd_path]:
            callback(line)

    def retrbinary(self, cmd, callback):
        callback(self.tree["FILE:" + cmd.removeprefix("RETR ")])


class TestFtpLogHelpers:
    def test_parses_dos_and_unix_listings(self):
        from hamilton_venus.odtc import _parse_ftp_listing

        dos = ["01-01-06  13:02       <DIR>          CrashDumps", "09-23-26  09:29               139157 InhecoSiLA.log"]
        assert _parse_ftp_listing(dos) == [("CrashDumps", True, 0), ("InhecoSiLA.log", False, 139157)]
        unix = ["drwxr-xr-x 2 ftp ftp 0 Sep 23 09:29 sub", "-rw-r--r-- 1 ftp ftp 12 Sep 23 09:29 my log.txt"]
        assert _parse_ftp_listing(unix) == [("sub", True, 0), ("my log.txt", False, 12)]

    def test_download_tree_recurses_skips_missing_roots_and_hostile_names(self, tmp_path, monkeypatch):
        import ftplib

        from hamilton_venus.odtc import _ftp_download_tree

        _FakeFtp.tree = {
            "/Logs": ["09-23-26  09:29  <DIR>  Sub", "09-23-26  09:29  5  a.log", "09-23-26  09:29  5  ..\\evil.txt"],
            "/Logs/Sub": ["09-23-26  09:29  3  b.log"],
            "FILE:/Logs/a.log": b"AAAAA",
            "FILE:/Logs/Sub/b.log": b"BBB",
        }
        monkeypatch.setattr(ftplib, "FTP", _FakeFtp)
        files = _ftp_download_tree("host", ("Logs", "Missing"), tmp_path)
        assert sorted(f["remote"] for f in files) == ["/Logs/Sub/b.log", "/Logs/a.log"]
        assert (tmp_path / "Logs" / "Sub" / "b.log").read_bytes() == b"BBB"
        assert not (tmp_path.parent / "evil.txt").exists()


class TestODTCRunTrace:
    def _run(self, client, name):
        builder = ODTCProtocolBuilder(name)
        builder.add_hold(60, 2)
        client.odtc_run_protocol(builder.build(), device_id=1, wait=True)

    def test_downloads_and_parses_the_trace_of_the_named_run(self, tmp_path):
        client = _client()
        client.odtc_connect("192.168.1.50")
        self._run(client, "MyRun")
        result = client.odtc_download_run_trace(1, tmp_path, method_name="MyRun")
        params = result.return_parameters
        assert params.method_name == "MyRun"
        assert params.rows and params.rows[-1].target_temperature == pytest.approx(60, abs=0.01)
        assert (tmp_path / "sim" / "MyRun.csv").is_file()

    def test_a_trace_for_a_different_method_is_not_returned(self, tmp_path):
        client = _client()
        client.odtc_connect("192.168.1.50")
        self._run(client, "MyRun")
        with pytest.raises(ODTCError, match="no run trace for method 'Other'"):
            client.odtc_download_run_trace(1, tmp_path, method_name="Other")
