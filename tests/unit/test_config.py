"""Unit tests for hamilton_venus.config."""

from __future__ import annotations

import textwrap

import pytest

from hamilton_venus.config import (
    AuthConfig,
    RunLogConfig,
    SdkConfig,
    StarClientConfig,
    load_config,
)


class TestSdkConfigDefaults:
    def test_defaults(self):
        cfg = SdkConfig()
        assert cfg.base_url == "http://localhost:42400"
        assert cfg.method.parent_window_handle == 0
        assert cfg.method.disable_status_communication is True
        assert cfg.method.disable_idle_communication is True
        assert cfg.network.max_retries == 3
        assert cfg.network.retry_backoff == 0.5
        assert cfg.timeouts.http == 30.0
        assert cfg.timeouts.startup == 300.0
        assert cfg.timeouts.disconnect == 30.0
        assert cfg.timeouts.command == 300.0
        assert cfg.auth.token_url == "https://localhost:42431/api/vector/v1/authorization/token"
        assert cfg.auth.username == ""
        assert cfg.auth.password == ""
        assert cfg.auth.client_id == "Venus"
        assert cfg.auth.client_secret == "venus_secret"
        assert cfg.auth.scope == "openid"
        assert cfg.auth.refresh_skew_seconds == 60
        assert cfg.tls.ca_bundle_path == ""
        assert cfg.run_log.include_cmd_comms is True
        assert cfg.star_client.auto_connect is True
        assert cfg.star_client.shutdown_timeout == 30.0
        assert cfg.star_client.logging_level is None
        assert cfg.star_client.venus_trace_logging is False
        assert cfg.star_client.error_profile_name == "standard"

    def test_rejects_invalid_scheme(self):
        with pytest.raises(ValueError, match="Invalid base_url scheme"):
            SdkConfig(base_url="ftp://localhost")

    def test_rejects_missing_hostname(self):
        with pytest.raises(ValueError, match="missing hostname"):
            SdkConfig(base_url="http://")

    def test_invalid_star_client_config_values(self):
        with pytest.raises(ValueError, match=r"star_client.shutdown_timeout"):
            StarClientConfig(shutdown_timeout=0)
        with pytest.raises(TypeError, match=r"star_client.shutdown_timeout"):
            StarClientConfig(shutdown_timeout="10")
        with pytest.raises(ValueError, match=r"star_client.logging_level"):
            StarClientConfig(logging_level=-1)
        with pytest.raises(TypeError, match=r"star_client.logging_level"):
            StarClientConfig(logging_level="DEBUG")
        with pytest.raises(ValueError, match=r"Unsupported star_client.error_profile_name"):
            StarClientConfig(error_profile_name="custom")


class TestAuthConfig:
    def test_configurable_token_url(self):
        auth = AuthConfig(
            token_url="https://custom-identity.example:5000/auth/token",
            username="user",
            password="pass",
        )
        assert auth.token_url == "https://custom-identity.example:5000/auth/token"

    def test_requires_username_and_password_when_validating_credentials(self):
        auth = AuthConfig()
        with pytest.raises(ValueError, match="Required authentication credentials are missing"):
            auth.validate_credentials()

    def test_rejects_negative_refresh_skew(self):
        with pytest.raises(ValueError, match="refresh_skew_seconds"):
            AuthConfig(refresh_skew_seconds=-1)


class TestLoadConfig:
    @pytest.fixture(autouse=True)
    def _run_log_env_unset(self, monkeypatch):
        # tests/unit/conftest.py turns the run log off for every test; these test the real defaults.
        monkeypatch.delenv("HAMILTON_VENUS_RUN_LOG_ENABLED", raising=False)
        monkeypatch.delenv("HAMILTON_VENUS_RUN_LOG_INCLUDE_COM_TRACE", raising=False)

    def test_returns_defaults_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("HAMILTON_VENUS_CONFIG", raising=False)
        monkeypatch.chdir(tmp_path)
        cfg = load_config()
        assert cfg.base_url == "http://localhost:42400"
        assert cfg.timeouts.command == 300.0

    def test_loads_from_explicit_path(self, tmp_path, monkeypatch):
        # Clear auth environment variables to ensure config file values are used
        monkeypatch.delenv("HAMILTON_VENUS_AUTH_USERNAME", raising=False)
        monkeypatch.delenv("HAMILTON_VENUS_AUTH_PASSWORD", raising=False)
        monkeypatch.delenv("HAMILTON_VENUS_AUTH_TOKEN_URL", raising=False)
        monkeypatch.delenv("HAMILTON_VENUS_AUTH_CLIENT_ID", raising=False)
        monkeypatch.delenv("HAMILTON_VENUS_AUTH_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("HAMILTON_VENUS_AUTH_SCOPE", raising=False)
        monkeypatch.delenv("HAMILTON_VENUS_AUTH_REFRESH_SKEW_SECONDS", raising=False)
        monkeypatch.delenv("HAMILTON_VENUS_TLS_CA_BUNDLE", raising=False)

        ca_file = tmp_path / "venus-ca.pem"
        ca_file.write_text("fake CA bundle")

        toml = tmp_path / "test.toml"
        toml.write_text(
            textwrap.dedent(f"""\
            [venus]
            base_url = "http://myhost:9999"

            [venus.method]
            method_display_name = "TestMethod"

            [venus.network]
            max_retries = 5
            retry_backoff = 1.5

            [venus.timeouts]
            http = 10.0
            startup = 20.0
            disconnect = 15.0
            command = 25.0

            [venus.auth]
            token_url = "http://myhost:42431/api/vector/v1/authorization/token"
            username = "venus-user"
            password = "venus-pass"
            client_id = "Venus"
            client_secret = "venus_secret"
            scope = "openid"
            refresh_skew_seconds = 90

            [venus.tls]
            ca_bundle_path = "{ca_file.as_posix()}"
        """)
        )
        cfg = load_config(toml)
        assert cfg.base_url == "http://myhost:9999"
        assert cfg.method.method_display_name == "TestMethod"
        assert cfg.network.max_retries == 5
        assert cfg.network.retry_backoff == 1.5
        assert cfg.timeouts.http == 10.0
        assert cfg.timeouts.startup == 20.0
        assert cfg.timeouts.disconnect == 15.0
        assert cfg.timeouts.command == 25.0
        assert cfg.auth.token_url == "http://myhost:42431/api/vector/v1/authorization/token"
        assert cfg.auth.username == "venus-user"
        assert cfg.auth.password == "venus-pass"
        assert cfg.auth.refresh_skew_seconds == 90
        assert cfg.tls.ca_bundle_path == ca_file.as_posix()

    def test_partial_toml_uses_defaults(self, tmp_path):
        toml = tmp_path / "partial.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://partial:1234"
        """)
        )
        cfg = load_config(toml)
        assert cfg.base_url == "http://partial:1234"
        assert cfg.network.max_retries == 3
        assert cfg.network.retry_backoff == 0.5
        assert cfg.timeouts.http == 30.0
        assert cfg.timeouts.command == 300.0

    def test_env_var_config_path(self, tmp_path, monkeypatch):
        toml = tmp_path / "env.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://envhost:8888"
        """)
        )
        monkeypatch.setenv("HAMILTON_VENUS_CONFIG", str(toml))
        cfg = load_config()
        assert cfg.base_url == "http://envhost:8888"
        assert cfg.timeouts.command == 300.0

    def test_auth_env_vars_override_toml(self, tmp_path, monkeypatch):
        toml = tmp_path / "auth.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://envhost:8888"

            [venus.auth]
            token_url = "http://envhost:42431/api/vector/v1/authorization/token"
            username = "toml-user"
            password = "toml-pass"
            client_id = "Venus"
            client_secret = "venus_secret"
            scope = "openid"
            refresh_skew_seconds = 90
        """)
        )
        monkeypatch.setenv(
            "HAMILTON_VENUS_AUTH_TOKEN_URL", "http://override.example:42431/api/vector/v1/authorization/token"
        )
        monkeypatch.setenv("HAMILTON_VENUS_AUTH_USERNAME", "env-user")
        monkeypatch.setenv("HAMILTON_VENUS_AUTH_PASSWORD", "env-pass")
        monkeypatch.setenv("HAMILTON_VENUS_AUTH_CLIENT_ID", "EnvClient")
        monkeypatch.setenv("HAMILTON_VENUS_AUTH_CLIENT_SECRET", "env-secret")
        monkeypatch.setenv("HAMILTON_VENUS_AUTH_SCOPE", "openid api")
        monkeypatch.setenv("HAMILTON_VENUS_AUTH_REFRESH_SKEW_SECONDS", "0")

        cfg = load_config(toml)

        assert cfg.auth.token_url == "http://override.example:42431/api/vector/v1/authorization/token"
        assert cfg.auth.username == "env-user"
        assert cfg.auth.password == "env-pass"
        assert cfg.auth.client_id == "EnvClient"
        assert cfg.auth.client_secret == "env-secret"
        assert cfg.auth.scope == "openid api"
        assert cfg.auth.refresh_skew_seconds == 0

    def test_auth_settings_can_be_supplied_without_explicit_enabled_override(self, tmp_path, monkeypatch):
        toml = tmp_path / "auth.toml"
        toml.write_text('[venus]\nbase_url = "http://envhost:8888"\n')
        monkeypatch.setenv("HAMILTON_VENUS_AUTH_TOKEN_URL", "http://envhost:42431/api/vector/v1/authorization/token")
        monkeypatch.setenv("HAMILTON_VENUS_AUTH_USERNAME", "env-user")
        monkeypatch.setenv("HAMILTON_VENUS_AUTH_PASSWORD", "env-pass")

        cfg = load_config(toml)

        assert cfg.auth.token_url == "http://envhost:42431/api/vector/v1/authorization/token"
        assert cfg.auth.username == "env-user"
        assert cfg.auth.password == "env-pass"

    def test_tls_env_var_overrides_toml(self, tmp_path, monkeypatch):
        toml_ca = tmp_path / "toml-ca.pem"
        toml_ca.write_text("fake CA bundle")
        env_ca = tmp_path / "env-ca.pem"
        env_ca.write_text("fake CA bundle")

        toml = tmp_path / "tls.toml"
        toml.write_text(
            textwrap.dedent(f"""\
            [venus]

            [venus.tls]
            ca_bundle_path = "{toml_ca.as_posix()}"
            """)
        )
        monkeypatch.setenv("HAMILTON_VENUS_TLS_CA_BUNDLE", env_ca.as_posix())

        cfg = load_config(toml)

        assert cfg.tls.ca_bundle_path == env_ca.as_posix()

    def test_missing_explicit_config_file_raises(self, tmp_path, monkeypatch):
        missing = tmp_path / "missing.toml"
        monkeypatch.setenv("HAMILTON_VENUS_CONFIG", str(missing))

        with pytest.raises(FileNotFoundError, match="VENUS SDK config file not found"):
            load_config()

    def test_run_log_config_invalid_bool_raises(self, tmp_path):
        """Invalid boolean values in run_log config should raise ValueError."""
        toml = tmp_path / "run_log_invalid.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.run_log]
            enabled = "yes"
        """)
        )
        with pytest.raises(ValueError, match="Invalid boolean value for key 'enabled'"):
            load_config(toml)

    def test_run_log_config_valid_bool_loads(self, tmp_path):
        """Valid boolean values in run_log config should load correctly."""
        toml = tmp_path / "run_log_valid.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.run_log]
            enabled = true
            console_capture = false
            include_http = true
            include_signalr = false
            include_cmd_comms = false
            redact_auth = true
        """)
        )
        cfg = load_config(toml)
        assert cfg.run_log.enabled is True
        assert cfg.run_log.console_capture is False
        assert cfg.run_log.include_http is True
        assert cfg.run_log.include_signalr is False
        assert cfg.run_log.include_cmd_comms is False
        assert cfg.run_log.redact_auth is True

    def test_run_log_on_by_default(self, tmp_path):
        toml = tmp_path / "no_run_log.toml"
        toml.write_text('[venus]\nbase_url = "http://localhost:42400"\n')
        cfg = load_config(toml)
        assert cfg.run_log.enabled is True
        assert cfg.run_log.include_com_trace is True
        assert cfg.run_log.output_dir == ""

    def test_run_log_config_env_vars_override_toml(self, tmp_path, monkeypatch):
        """Environment variables should override TOML settings for run_log config."""
        toml = tmp_path / "run_log_env_override.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.run_log]
            enabled = true
            console_capture = false
            include_http = false
            include_signalr = false
            include_cmd_comms = false
            redact_auth = false
        """)
        )
        # Override all boolean settings via environment variables
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_ENABLED", "false")
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_CONSOLE_CAPTURE", "true")
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_INCLUDE_HTTP", "yes")
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_INCLUDE_SIGNALR", "on")
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_INCLUDE_CMD_COMMS", "true")
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_REDACT_AUTH", "1")

        cfg = load_config(toml)
        assert cfg.run_log.enabled is False
        assert cfg.run_log.console_capture is True
        assert cfg.run_log.include_http is True
        assert cfg.run_log.include_signalr is True
        assert cfg.run_log.include_cmd_comms is True
        assert cfg.run_log.redact_auth is True

    def test_run_log_config_invalid_bool_env_var_raises(self, tmp_path, monkeypatch):
        """Invalid environment variable boolean values should raise ValueError with helpful message."""
        toml = tmp_path / "run_log_env_invalid.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.run_log]
            enabled = true
        """)
        )
        # Set an invalid boolean value in environment variable
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_ENABLED", "maybe")

        with pytest.raises(ValueError) as exc_info:
            load_config(toml)

        error_message = str(exc_info.value)
        # Verify error message mentions the environment variable name
        assert "HAMILTON_VENUS_RUN_LOG_ENABLED" in error_message
        # Verify error message mentions the invalid value
        assert "maybe" in error_message
        # Verify error message lists allowed truthy values
        assert "1" in error_message or "true" in error_message
        # Verify error message lists allowed falsy values
        assert "0" in error_message or "false" in error_message

    def test_run_log_config_include_cmd_comms_defaults_true(self, tmp_path):
        """include_cmd_comms should default to True when not specified in config."""
        toml = tmp_path / "run_log_include_cmd_comms_default.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.run_log]
            enabled = true
        """)
        )

        cfg = load_config(toml)

        assert cfg.run_log.include_cmd_comms is True

    def test_method_disable_status_communication_from_toml_and_env(self, tmp_path, monkeypatch):
        toml = tmp_path / "method_status_communication.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.method]
            disable_status_communication = false
        """)
        )
        monkeypatch.delenv("HAMILTON_VENUS_METHOD_DISABLE_STATUS_COMMUNICATION", raising=False)
        assert load_config(toml).method.disable_status_communication is False

        monkeypatch.setenv("HAMILTON_VENUS_METHOD_DISABLE_STATUS_COMMUNICATION", "true")
        assert load_config(toml).method.disable_status_communication is True

    def test_method_disable_idle_communication_from_toml_and_env(self, tmp_path, monkeypatch):
        toml = tmp_path / "method_idle_communication.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.method]
            disable_idle_communication = false
        """)
        )
        monkeypatch.delenv("HAMILTON_VENUS_METHOD_DISABLE_IDLE_COMMUNICATION", raising=False)
        assert load_config(toml).method.disable_idle_communication is False

        monkeypatch.setenv("HAMILTON_VENUS_METHOD_DISABLE_IDLE_COMMUNICATION", "true")
        assert load_config(toml).method.disable_idle_communication is True

    def test_run_log_com_trace_defaults(self, tmp_path):
        toml = tmp_path / "run_log_com_trace_default.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.run_log]
            enabled = true
        """)
        )
        cfg = load_config(toml)
        assert cfg.run_log.include_com_trace is True
        assert cfg.run_log.com_trace_logfiles_dir == ""
        assert cfg.run_log.com_trace_max_bytes == 5_242_880

    def test_run_log_com_trace_from_toml(self, tmp_path):
        toml = tmp_path / "run_log_com_trace.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.run_log]
            enabled = true
            include_com_trace = true
            com_trace_logfiles_dir = "D:/traces"
            com_trace_max_bytes = 1024
        """)
        )
        cfg = load_config(toml)
        assert cfg.run_log.include_com_trace is True
        assert cfg.run_log.com_trace_logfiles_dir == "D:/traces"
        assert cfg.run_log.com_trace_max_bytes == 1024

    def test_run_log_com_trace_env_vars_override_toml(self, tmp_path, monkeypatch):
        toml = tmp_path / "run_log_com_trace_env.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.run_log]
            enabled = true
            include_com_trace = false
        """)
        )
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_INCLUDE_COM_TRACE", "true")
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_COM_TRACE_DIR", r"C:\tmp\traces")
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_COM_TRACE_MAX_BYTES", "2048")
        cfg = load_config(toml)
        assert cfg.run_log.include_com_trace is True
        assert cfg.run_log.com_trace_logfiles_dir == r"C:\tmp\traces"
        assert cfg.run_log.com_trace_max_bytes == 2048

    def test_run_log_com_trace_max_bytes_negative_raises(self):
        with pytest.raises(ValueError, match="com_trace_max_bytes"):
            RunLogConfig(com_trace_max_bytes=-1)

    def test_base_url_env_var_overrides_toml(self, tmp_path, monkeypatch):
        toml = tmp_path / "base_url_override.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://toml-host:42400"
        """)
        )
        monkeypatch.setenv("HAMILTON_VENUS_BASE_URL", "http://env-host:52525")

        cfg = load_config(toml)

        assert cfg.base_url == "http://env-host:52525"

    def test_timeouts_env_vars_override_toml(self, tmp_path, monkeypatch):
        toml = tmp_path / "timeouts_env_override.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.timeouts]
            http = 10.0
            startup = 20.0
            disconnect = 30.0
            command = 40.0
        """)
        )
        monkeypatch.setenv("HAMILTON_VENUS_TIMEOUT_HTTP", "11.5")
        monkeypatch.setenv("HAMILTON_VENUS_TIMEOUT_STARTUP", "21.5")
        monkeypatch.setenv("HAMILTON_VENUS_TIMEOUT_DISCONNECT", "31.5")
        monkeypatch.setenv("HAMILTON_VENUS_TIMEOUT_COMMAND", "41.5")

        cfg = load_config(toml)

        assert cfg.timeouts.http == 11.5
        assert cfg.timeouts.startup == 21.5
        assert cfg.timeouts.disconnect == 31.5
        assert cfg.timeouts.command == 41.5

    def test_network_env_vars_override_toml(self, tmp_path, monkeypatch):
        toml = tmp_path / "network_env_override.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.network]
            max_retries = 3
            retry_backoff = 0.5
        """)
        )
        monkeypatch.setenv("HAMILTON_VENUS_NETWORK_MAX_RETRIES", "7")
        monkeypatch.setenv("HAMILTON_VENUS_NETWORK_RETRY_BACKOFF", "1.25")

        cfg = load_config(toml)

        assert cfg.network.max_retries == 7
        assert cfg.network.retry_backoff == 1.25

    def test_star_client_env_vars_override_toml(self, tmp_path, monkeypatch):
        toml = tmp_path / "star_client_env_override.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.star_client]
            auto_connect = true
            shutdown_timeout = 15.0
            logging_level = "WARNING"
            venus_trace_logging = false
            error_profile_name = "standard"
        """)
        )
        monkeypatch.setenv("HAMILTON_VENUS_AUTO_CONNECT", "false")
        monkeypatch.setenv("HAMILTON_VENUS_SHUTDOWN_TIMEOUT", "45")
        monkeypatch.setenv("HAMILTON_VENUS_LOGGING_LEVEL", "DEBUG")
        monkeypatch.setenv("HAMILTON_VENUS_TRACE_LOGGING", "true")
        monkeypatch.setenv("HAMILTON_VENUS_ERROR_PROFILE", "standard")

        cfg = load_config(toml)

        assert cfg.star_client.auto_connect is False
        assert cfg.star_client.shutdown_timeout == 45.0
        assert cfg.star_client.logging_level == 10
        assert cfg.star_client.venus_trace_logging is True
        assert cfg.star_client.error_profile_name == "standard"

    def test_star_client_toml_values_are_loaded(self, tmp_path):
        toml = tmp_path / "star_client_toml_values.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.star_client]
            auto_connect = false
            shutdown_timeout = 12.5
            logging_level = "ERROR"
            venus_trace_logging = true
            error_profile_name = "STANDARD"
        """)
        )

        cfg = load_config(toml)

        assert cfg.star_client.auto_connect is False
        assert cfg.star_client.shutdown_timeout == 12.5
        assert cfg.star_client.logging_level == 40
        assert cfg.star_client.venus_trace_logging is True
        assert cfg.star_client.error_profile_name == "standard"

    def test_star_client_relative_error_profile_path_is_resolved_against_config_dir(self, tmp_path):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        profile_file = profiles_dir / "custom_profile.json"
        profile_file.write_text("{}")

        toml = tmp_path / "relative_error_profile_path.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.star_client]
            error_profile_path = "profiles/custom_profile.json"
        """)
        )

        cfg = load_config(toml)

        assert cfg.star_client.error_profile_path == str(profile_file.resolve())

    def test_invalid_logging_level_env_value_raises(self, tmp_path, monkeypatch):
        toml = tmp_path / "invalid_logging_level_env.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"
        """)
        )
        monkeypatch.setenv("HAMILTON_VENUS_LOGGING_LEVEL", "VERBOSE")

        with pytest.raises(ValueError, match="HAMILTON_VENUS_LOGGING_LEVEL"):
            load_config(toml)

    def test_star_client_error_profile_path_env_override_is_not_rebased(self, tmp_path, monkeypatch):
        env_profile = tmp_path / "env_profile.json"
        env_profile.write_text("{}")

        toml = tmp_path / "env_error_profile_path.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.star_client]
            error_profile_path = "profiles/custom_profile.json"
        """)
        )

        monkeypatch.setenv("HAMILTON_VENUS_ERROR_PROFILE_PATH", str(env_profile))

        cfg = load_config(toml)

        assert cfg.star_client.error_profile_path == str(env_profile)

    def test_invalid_star_client_error_profile_env_value_raises(self, tmp_path, monkeypatch):
        toml = tmp_path / "invalid_error_profile_env.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"
        """)
        )
        monkeypatch.setenv("HAMILTON_VENUS_ERROR_PROFILE", "custom")

        with pytest.raises(ValueError, match=r"star_client.error_profile_name"):
            load_config(toml)

    def test_command_timeout_toml_none_disables_timeout(self, tmp_path):
        toml = tmp_path / "command_timeout_none.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.timeouts]
            command = "none"
        """)
        )

        cfg = load_config(toml)

        assert cfg.timeouts.command is None

    def test_command_timeout_env_none_disables_timeout(self, tmp_path, monkeypatch):
        toml = tmp_path / "command_timeout_env_none.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.timeouts]
            command = 12.0
        """)
        )
        monkeypatch.setenv("HAMILTON_VENUS_TIMEOUT_COMMAND", "none")

        cfg = load_config(toml)

        assert cfg.timeouts.command is None

    def test_run_log_signalr_filter_env_var_overrides_toml(self, tmp_path, monkeypatch):
        toml = tmp_path / "run_log_filter_env_override.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.run_log]
            enabled = true
            signalr_event_filter = ["runtime_status"]
        """)
        )
        monkeypatch.setenv(
            "HAMILTON_VENUS_RUN_LOG_SIGNALR_EVENT_FILTER",
            "runtime_status, progress, ,instrument_error",
        )

        cfg = load_config(toml)

        assert cfg.run_log.signalr_event_filter == ["runtime_status", "progress", "instrument_error"]

    def test_run_log_signalr_filter_toml_string_parsed_as_single_item(self, tmp_path):
        toml = tmp_path / "run_log_filter_toml_string.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.run_log]
            enabled = true
            signalr_event_filter = "runtime_status"
        """)
        )

        cfg = load_config(toml)

        assert cfg.run_log.signalr_event_filter == ["runtime_status"]

    def test_run_log_signalr_filter_toml_comma_separated_string_parsed(self, tmp_path):
        toml = tmp_path / "run_log_filter_toml_csv_string.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.run_log]
            enabled = true
            signalr_event_filter = "runtime_status, progress, ,instrument_error"
        """)
        )

        cfg = load_config(toml)

        assert cfg.run_log.signalr_event_filter == ["runtime_status", "progress", "instrument_error"]

    def test_run_log_signalr_filter_toml_invalid_non_string_list_item_raises(self, tmp_path):
        toml = tmp_path / "run_log_filter_toml_invalid_list_item.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.run_log]
            enabled = true
            signalr_event_filter = ["runtime_status", 1]
        """)
        )

        with pytest.raises(ValueError, match=r"signalr_event_filter"):
            load_config(toml)

    def test_run_log_signalr_filter_toml_invalid_type_raises(self, tmp_path):
        toml = tmp_path / "run_log_filter_toml_invalid_type.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.run_log]
            enabled = true
            signalr_event_filter = 123
        """)
        )

        with pytest.raises(ValueError, match=r"signalr_event_filter"):
            load_config(toml)

    def test_run_log_max_payload_bytes_env_var_overrides_toml(self, tmp_path, monkeypatch):
        toml = tmp_path / "run_log_payload_env_override.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.run_log]
            enabled = true
            max_payload_bytes = 2048
        """)
        )
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_MAX_PAYLOAD_BYTES", "4096")

        cfg = load_config(toml)

        assert cfg.run_log.max_payload_bytes == 4096

    @pytest.mark.parametrize(
        ("env_name", "env_value"),
        [
            ("HAMILTON_VENUS_TIMEOUT_HTTP", "abc"),
            ("HAMILTON_VENUS_TIMEOUT_HTTP", ""),
            ("HAMILTON_VENUS_NETWORK_MAX_RETRIES", ""),
            ("HAMILTON_VENUS_RUN_LOG_MAX_PAYLOAD_BYTES", "not-a-number"),
        ],
    )
    def test_invalid_numeric_env_parse_errors_include_env_name(self, tmp_path, monkeypatch, env_name, env_value):
        toml = tmp_path / "invalid_numeric_parse_env.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"
        """)
        )
        monkeypatch.setenv(env_name, env_value)

        with pytest.raises(ValueError) as exc_info:
            load_config(toml)

        assert env_name in str(exc_info.value)

    def test_shutdown_timeout_toml_bool_rejected(self, tmp_path):
        toml = tmp_path / "shutdown_timeout_bool.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.star_client]
            shutdown_timeout = true
        """)
        )

        with pytest.raises(ValueError, match=r"key 'shutdown_timeout'"):
            load_config(toml)

    def test_network_max_retries_toml_bool_rejected(self, tmp_path):
        toml = tmp_path / "network_max_retries_bool.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"

            [venus.network]
            max_retries = true
        """)
        )

        with pytest.raises(ValueError, match=r"key 'max_retries'"):
            load_config(toml)

    @pytest.mark.parametrize(
        ("env_name", "env_value", "expected_message"),
        [
            ("HAMILTON_VENUS_TIMEOUT_HTTP", "0", "timeouts.http"),
            ("HAMILTON_VENUS_TIMEOUT_COMMAND", "-1", "timeouts.command"),
            ("HAMILTON_VENUS_NETWORK_MAX_RETRIES", "-1", "network.max_retries"),
            ("HAMILTON_VENUS_NETWORK_RETRY_BACKOFF", "-0.1", "network.retry_backoff"),
            ("HAMILTON_VENUS_RUN_LOG_MAX_PAYLOAD_BYTES", "-1", "run_log.max_payload_bytes"),
            ("HAMILTON_VENUS_SHUTDOWN_TIMEOUT", "0", "star_client.shutdown_timeout"),
        ],
    )
    def test_invalid_numeric_env_values_raise(self, tmp_path, monkeypatch, env_name, env_value, expected_message):
        toml = tmp_path / "invalid_numeric_env.toml"
        toml.write_text(
            textwrap.dedent("""\
            [venus]
            base_url = "http://localhost:42400"
        """)
        )
        monkeypatch.setenv(env_name, env_value)

        with pytest.raises(ValueError, match=expected_message):
            load_config(toml)
