"""Tests for exceptions defined in hamilton_venus.exceptions."""

from __future__ import annotations

import pytest

from hamilton_venus.exceptions import (
    MethodError,
    VenusApiContractError,
    VenusAuthenticationError,
    VenusCommandAbortedError,
    VenusCommandFailedError,
    VenusConnectionError,
    VenusError,
    VenusTimeoutError,
)
from hamilton_venus.models import CommandResponse


@pytest.mark.parametrize(
    "exc_class",
    [
        VenusConnectionError,
        VenusTimeoutError,
        VenusAuthenticationError,
        VenusApiContractError,
        VenusCommandAbortedError,
    ],
)
class TestSimpleVenusExceptions:
    """Common behaviour shared by all plain VenusError subclasses."""

    def test_is_subclass_of_venus_error(self, exc_class: type) -> None:
        assert issubclass(exc_class, VenusError)

    def test_accepts_message(self, exc_class: type) -> None:
        exc = exc_class("something went wrong")
        assert "something went wrong" in str(exc)

    def test_can_be_caught_as_venus_error(self, exc_class: type) -> None:
        with pytest.raises(VenusError):
            raise exc_class("error")


class TestVenusError:
    """Tests for the VenusError base class itself."""

    def test_is_subclass_of_exception(self) -> None:
        assert issubclass(VenusError, Exception)

    def test_accepts_message(self) -> None:
        exc = VenusError("base error")
        assert "base error" in str(exc)

    def test_accessible_from_top_level_package(self) -> None:
        from hamilton_venus import VenusError as TopLevelError

        assert TopLevelError is VenusError


class TestMethodError:
    """Tests for MethodError, which carries an optional cmd_result_message."""

    def test_is_subclass_of_venus_error(self) -> None:
        assert issubclass(MethodError, VenusError)

    def test_message_stored_as_str(self) -> None:
        exc = MethodError("operation failed")
        assert "operation failed" in str(exc)

    def test_cmd_result_message_defaults_to_empty_string(self) -> None:
        exc = MethodError("operation failed")
        assert exc.cmd_result_message == ""

    def test_cmd_result_message_stored_when_provided(self) -> None:
        exc = MethodError("operation failed", cmd_result_message="Venus returned code 5")
        assert exc.cmd_result_message == "Venus returned code 5"

    def test_cmd_result_message_not_in_str(self) -> None:
        exc = MethodError("operation failed", cmd_result_message="Venus returned code 5")
        assert "Venus returned code 5" not in str(exc)

    def test_can_be_caught_as_venus_error(self) -> None:
        with pytest.raises(VenusError):
            raise MethodError("error")


class TestVenusCommandFailedError:
    """Tests for the VenusCommandFailedError exception class."""

    def test_raises_with_response_attribute(self) -> None:
        response = CommandResponse(
            id="test-id",
            action_name="TestAction",
            return_status="Error",
            return_code=1,
        )
        exc = VenusCommandFailedError(response)
        assert exc.response is response

    def test_message_includes_action_name(self) -> None:
        response = CommandResponse(
            id="test-id",
            action_name="instrument.isConnected",
            return_status="Error",
            return_code=1,
        )
        exc = VenusCommandFailedError(response)
        assert "instrument.isConnected failed" in str(exc)

    def test_message_includes_return_status(self) -> None:
        response = CommandResponse(
            id="test-id",
            action_name="TestAction",
            return_status="Error",
            return_code=1,
        )
        exc = VenusCommandFailedError(response)
        assert "returnStatus='Error'" in str(exc)

    def test_message_includes_return_code(self) -> None:
        response = CommandResponse(
            id="test-id",
            action_name="TestAction",
            return_status="Error",
            return_code=42,
        )
        exc = VenusCommandFailedError(response)
        assert "returnCode=42" in str(exc)

    def test_message_includes_return_parameters(self) -> None:
        params = {"errorMessage": "device timeout", "retries": 3}
        response = CommandResponse(
            id="test-id",
            action_name="TestAction",
            return_status="Error",
            return_code=1,
            return_parameters=params,
        )
        exc = VenusCommandFailedError(response)
        assert "returnParameters=" in str(exc)
        assert "errorMessage" in str(exc)
        assert "device timeout" in str(exc)

    def test_falls_back_to_command_when_action_name_empty(self) -> None:
        response = CommandResponse(
            id="test-id",
            action_name="",
            return_status="Unknown",
            return_code=1,
        )
        exc = VenusCommandFailedError(response)
        assert "Command failed" in str(exc)

    def test_is_subclass_of_venus_error(self) -> None:
        from hamilton_venus.exceptions import VenusError

        response = CommandResponse(
            id="test-id",
            action_name="TestAction",
            return_status="Error",
            return_code=1,
        )
        exc = VenusCommandFailedError(response)
        assert isinstance(exc, VenusError)

    def test_non_zero_return_code_with_success_status_fails(self) -> None:
        response = CommandResponse(
            id="test-id",
            action_name="ConflictingStatus",
            return_status="Success",
            return_code=1,
        )
        assert not response.success
        exc = VenusCommandFailedError(response)
        assert "ConflictingStatus failed" in str(exc)

    def test_zero_return_code_with_error_status_fails(self) -> None:
        response = CommandResponse(
            id="test-id",
            action_name="ErrorStatus",
            return_status="Error",
            return_code=0,
        )
        assert not response.success
        exc = VenusCommandFailedError(response)
        assert "ErrorStatus failed" in str(exc)

    def test_accessible_from_top_level_package(self) -> None:
        from hamilton_venus import VenusCommandFailedError as TopLevelError

        assert TopLevelError is VenusCommandFailedError

    def test_can_be_caught_as_venus_error(self) -> None:
        from hamilton_venus.exceptions import VenusError

        response = CommandResponse(
            id="test-id",
            action_name="TestAction",
            return_status="Error",
            return_code=1,
        )
        with pytest.raises(VenusError):
            raise VenusCommandFailedError(response)

    def test_response_fields_accessible_via_exception(self) -> None:
        params = {"reason": "tip pickup failure"}
        response = CommandResponse(
            id="test-id",
            action_name="tip_pickup",
            return_status="Error",
            return_code=5,
            return_parameters=params,
        )
        exc = VenusCommandFailedError(response)
        assert exc.response.return_code == 5
        assert exc.response.return_status == "Error"
        assert exc.response.return_parameters == params
