"""Unit tests for the shared 32-bit-COM bridge (hamilton_venus._com32)."""

from __future__ import annotations

import sys

from hamilton_venus import _com32


class TestFindPython32:
    def test_no_env_vars_given_skips_override(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_com32, "_BUNDLED_PY32", str(tmp_path / "does-not-exist" / "python.exe"))
        monkeypatch.setattr(_com32, "_IS_64BIT", False)
        monkeypatch.setattr(sys, "platform", "win32")
        assert _com32.find_python32() == sys.executable

    def test_first_set_env_var_wins(self, monkeypatch):
        monkeypatch.delenv("FIRST_VAR", raising=False)
        monkeypatch.setenv("SECOND_VAR", r"C:\py32\python.exe")
        monkeypatch.setattr(_com32, "_is_python_32bit", lambda exe: exe == r"C:\py32\python.exe")
        monkeypatch.setattr(sys, "platform", "win32")
        assert _com32.find_python32("FIRST_VAR", "SECOND_VAR") == r"C:\py32\python.exe"

    def test_env_override_rejected_when_not_32bit(self, monkeypatch):
        monkeypatch.setenv("HAMILTON_ODTC_PYTHON32", sys.executable)
        monkeypatch.setattr(_com32, "_IS_64BIT", True)
        monkeypatch.setattr(_com32, "_is_python_32bit", lambda exe: False)
        assert _com32.find_python32("HAMILTON_ODTC_PYTHON32") is None

    def test_bundled_path_used_when_present(self, monkeypatch, tmp_path):
        monkeypatch.delenv("HAMILTON_ODTC_PYTHON32", raising=False)
        fake = tmp_path / "python.exe"
        fake.write_text("")
        monkeypatch.setattr(_com32, "_BUNDLED_PY32", str(fake))
        monkeypatch.setattr(sys, "platform", "win32")
        assert _com32.find_python32("HAMILTON_ODTC_PYTHON32") == str(fake)

    def test_shared_runtime_used_when_present(self, monkeypatch, tmp_path):
        monkeypatch.delenv("HAMILTON_ODTC_PYTHON32", raising=False)
        monkeypatch.setattr(_com32, "_BUNDLED_PY32", str(tmp_path / "does-not-exist" / "python.exe"))
        monkeypatch.setattr(sys, "platform", "win32")
        programdata = tmp_path / "programdata"
        exe = programdata / "Hamilton" / "VenusSDK" / "py32" / "python.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        monkeypatch.setenv("PROGRAMDATA", str(programdata))
        assert _com32.find_python32("HAMILTON_ODTC_PYTHON32") == str(exe)
        assert _com32.find_python32("HAMILTON_ODTC_PYTHON32") == _com32.shared_python32_exe()

    def test_bundled_wins_over_shared_runtime(self, monkeypatch, tmp_path):
        monkeypatch.delenv("HAMILTON_ODTC_PYTHON32", raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        bundled = tmp_path / "bundled" / "python.exe"
        bundled.parent.mkdir(parents=True)
        bundled.write_text("")
        monkeypatch.setattr(_com32, "_BUNDLED_PY32", str(bundled))
        programdata = tmp_path / "programdata"
        exe = programdata / "Hamilton" / "VenusSDK" / "py32" / "python.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        monkeypatch.setenv("PROGRAMDATA", str(programdata))
        assert _com32.find_python32("HAMILTON_ODTC_PYTHON32") == str(bundled)

    def test_non_windows_returns_none(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert _com32.find_python32() is None


class TestCandidateBackends:
    def test_32bit_python_gets_inproc_backend(self, monkeypatch):
        monkeypatch.setattr(_com32, "_IS_64BIT", False)
        backends = _com32.candidate_backends(progid="Some.ProgId")
        assert len(backends) == 1
        assert isinstance(backends[0], _com32.InProcBackend32)

    def test_64bit_with_py32_gets_bridge_backend(self, monkeypatch):
        monkeypatch.setattr(_com32, "_IS_64BIT", True)
        monkeypatch.setattr(_com32, "find_python32", lambda *env: r"C:\py32\python.exe")
        backends = _com32.candidate_backends(progid="Some.ProgId")
        assert len(backends) == 1
        assert isinstance(backends[0], _com32.Bridge32Backend)

    def test_64bit_without_py32_falls_back_to_inproc(self, monkeypatch):
        monkeypatch.setattr(_com32, "_IS_64BIT", True)
        monkeypatch.setattr(_com32, "find_python32", lambda *env: None)
        backends = _com32.candidate_backends(progid="Some.ProgId")
        assert len(backends) == 1
        assert isinstance(backends[0], _com32.InProcBackend32)


class TestMergeBindingRedirectsAdditiveAcrossDrivers:
    def test_two_drivers_writing_same_config_do_not_clobber(self, tmp_path):
        cfg = tmp_path / "python.exe.config"
        hhc_redirects = {"Hamilton.Components.TransportLayer.ComLink": "7.0.1.561"}
        odtc_redirects = {"Hamilton.Components.TransportLayer.ComLib": "7.0.2.100"}

        assert _com32.merge_binding_redirects(str(cfg), hhc_redirects) is True
        assert _com32.merge_binding_redirects(str(cfg), odtc_redirects) is True

        text = cfg.read_text()
        assert "Hamilton.Components.TransportLayer.ComLink" in text
        assert '"7.0.1.561"' in text
        assert "Hamilton.Components.TransportLayer.ComLib" in text
        assert '"7.0.2.100"' in text

        # Re-running either is a no-op.
        assert _com32.merge_binding_redirects(str(cfg), hhc_redirects) is False
        assert _com32.merge_binding_redirects(str(cfg), odtc_redirects) is False

    def test_order_independent(self, tmp_path):
        cfg_a = tmp_path / "a" / "python.exe.config"
        cfg_b = tmp_path / "b" / "python.exe.config"
        hhc_redirects = {"Hamilton.Components.TransportLayer.ComLink": "7.0.1.561"}
        odtc_redirects = {"Hamilton.Components.TransportLayer.ComLib": "7.0.2.100"}

        _com32.merge_binding_redirects(str(cfg_a), hhc_redirects)
        _com32.merge_binding_redirects(str(cfg_a), odtc_redirects)

        _com32.merge_binding_redirects(str(cfg_b), odtc_redirects)
        _com32.merge_binding_redirects(str(cfg_b), hhc_redirects)

        text_a, text_b = cfg_a.read_text(), cfg_b.read_text()
        for text in (text_a, text_b):
            assert "Hamilton.Components.TransportLayer.ComLink" in text
            assert "Hamilton.Components.TransportLayer.ComLib" in text

    def test_preserves_existing_config(self, tmp_path):
        cfg = tmp_path / "python.exe.config"
        cfg.write_text(
            '<?xml version="1.0"?><configuration><appSettings>'
            '<add key="x" value="1"/></appSettings></configuration>'
        )
        _com32.merge_binding_redirects(str(cfg), {"Hamilton.Components.TransportLayer.ComLib": "7.0.1.561"})
        text = cfg.read_text()
        assert 'key="x"' in text
        assert "Hamilton.Components.TransportLayer.ComLib" in text

    def test_no_redirects_is_noop(self, tmp_path):
        cfg = tmp_path / "python.exe.config"
        assert _com32.merge_binding_redirects(str(cfg), {}) is False
        assert not cfg.exists()


class TestMergeBindingRedirectsFixtureParity:
    """Fixture-parity with hamilton_venus._com32_worker._ensure_binding_config's
    necessarily-duplicated inline logic (it cannot import _com32 -- the bundled
    interpreter has no hamilton_venus installed). Same input must yield the same
    set of assembly names written, so the two implementations cannot silently
    drift apart."""

    def test_same_redirects_same_resulting_names(self, tmp_path, monkeypatch):
        from hamilton_venus import _com32_worker

        redirects = {
            "Hamilton.Components.TransportLayer.ComLink": "7.0.1.561",
            "Hamilton.Components.TransportLayer.ComLib": "7.0.2.100",
        }

        cfg_a = tmp_path / "a.exe.config"
        _com32.merge_binding_redirects(str(cfg_a), redirects)

        tl_dir = tmp_path / "tl_bin"
        tl_dir.mkdir()
        monkeypatch.setattr(_com32_worker, "_wanted_redirects", lambda _tl_dir: redirects)
        monkeypatch.setattr(sys, "maxsize", 2**31 - 1)  # pretend 32-bit
        monkeypatch.delenv(_com32_worker._REEXEC_FLAG, raising=False)
        cfg_b = tmp_path / "b.exe.config"
        monkeypatch.setattr(sys, "executable", str(cfg_b)[: -len(".config")])
        _com32_worker._ensure_binding_config(str(tl_dir))

        names_a = _com32._existing_redirect_names(cfg_a.read_text())
        names_b = _com32_worker._existing_redirect_names(cfg_b.read_text())
        assert names_a == names_b == set(redirects)


class TestGrantDataAccess:
    def test_non_windows_returns_false(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        ok, msg = _com32.grant_data_access("C:\\nowhere")
        assert ok is False
        assert msg == "not Windows"


class TestWritePy32BindingConfig:
    def test_missing_interpreter_reported(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "win32")
        ok, msg = _com32.write_py32_binding_config(str(tmp_path / "nope.exe"), str(tmp_path))
        assert ok is False
        assert "no such interpreter" in msg

    def test_no_transport_layer_dlls_reported(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "win32")
        exe = tmp_path / "python.exe"
        exe.write_text("")
        ok, msg = _com32.write_py32_binding_config(str(exe), str(tmp_path))
        assert ok is False
        assert "no TransportLayer DLLs found" in msg
