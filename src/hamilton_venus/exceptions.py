"""Exceptions raised by the Hamilton VENUS Python SDK."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hamilton_venus.models import CommandResponse


class VenusError(Exception):
    """Base exception for all Hamilton VENUS SDK errors."""


class VenusConnectionError(VenusError):
    """Raised when a connection to the VENUS WebAPI cannot be established
    or is lost unexpectedly."""


class VenusTimeoutError(VenusError):
    """Raised when a VENUS operation does not complete within the allotted time."""


class VenusAuthenticationError(VenusError):
    """Raised when VENUS authentication configuration or token acquisition fails."""


class VenusApiContractError(VenusError):
    """Raised when the VENUS API returns malformed or inconsistent contract data."""


class VenusCommandAbortedError(VenusError):
    """Raised when an in-flight command is interrupted by method abort events."""


class VenusCommandUnsupportedError(VenusError):
    """Raised before sending a command that needs hardware the instrument's
    configuration does not report (e.g. an MPH96 head, autoload, or iSWAP/IPG gripper)."""


class LiquidClassPushError(VenusError):
    """Raised when VENUS fails to import a custom liquid class the SDK pushed before a
    command (its JSON in the SDK ``Liquid Class`` folder changed, or it was first used
    this session). Fix the liquid class JSON; the command was not sent."""


class LabwareTiltedError(VenusError):
    """Raised before sending a transport command for labware that ``tilt_labware``
    has tilted. Tilt it back with ``tilt_labware(labware_name, 0)`` first."""


class SplitWellCapacityError(VenusError):
    """Raised before pipetting when more channels target a split well than it has slots.

    ``split_wells`` sized the well for the channels that fit; target fewer channels,
    or adjacent ones, or split it again with a different ``fit``."""


class VenusCommandFailedError(VenusError):
    """Raised when a command response indicates failure (``success`` is ``False``).

    The original :class:`~hamilton_venus.models.CommandResponse` is available on
    the ``response`` attribute for inspection of ``return_code``,
    ``return_status``, and ``return_parameters``.
    """

    def __init__(self, response: CommandResponse) -> None:
        op_name = response.action_name or "Command"
        super().__init__(
            f"{op_name} failed: returnStatus={response.return_status!r}, "
            f"returnCode={response.return_code}, "
            f"returnParameters={response.return_parameters!r}"
        )
        self.response = response


class MethodError(VenusError):
    """Raised when a VENUS method operation fails."""

    def __init__(self, message: str, *, cmd_result_message: str = "") -> None:
        super().__init__(message)
        self.cmd_result_message = cmd_result_message


class HeaterCoolerError(VenusError):
    """Raised when a Hamilton Heater Cooler (HHC) operation fails.

    Covers a missing vendor driver, a COM ``HRESULT`` / non-zero vendor return
    code, an unknown ``device_id``, or (native transport) a serial timeout. The
    HHC driver talks to the device directly and does not go through the VENUS
    runtime, but this subclasses :class:`VenusError` so existing
    ``except VenusError`` handlers keep working.
    """


class ODTCError(VenusError):
    """Raised when an Inheco ODTC (On-Deck Thermal Cycler) operation fails.

    Covers a missing vendor driver, a COM ``HRESULT`` / non-zero SiLA return
    code, an unknown ``device_id``, or a lock-acquisition failure. The ODTC
    driver talks to the device directly and does not go through the VENUS
    runtime, but this subclasses :class:`VenusError` so existing
    ``except VenusError`` handlers keep working.
    """


class InhecoTECError(VenusError):
    """Raised when an Inheco Single/Multi TEC Controller (STC/MTC) operation fails.

    Covers a missing vendor driver, a COM ``HRESULT``, an unreachable
    ``controller_id``, or repeated garbled/mismatched wire responses after
    the vendor's own retry budget is exhausted. The InhecoTEC driver talks to
    the device directly and does not go through the VENUS runtime, but this
    subclasses :class:`VenusError` so existing ``except VenusError`` handlers
    keep working.
    """


class TiltModuleError(VenusError):
    """Raised when a Hamilton MFX Tilt Module (daisy chain, ambient) operation fails.

    ``error_code`` carries the HSL return code: a firmware ``er<NN>`` code (0..7) when the
    failure came from a module reply, a communication-library code (-1..-11, e.g. -8 for a
    read timeout) for a port or protocol failure, or ``None``.
    ``tilt_module_error_message(code)`` turns a code into its text. The Tilt Module driver
    talks to the module over RS-232 and does not go through the VENUS runtime, but this
    subclasses :class:`VenusError` so existing ``except VenusError`` handlers keep working.
    """

    def __init__(self, message: str, *, error_code: int | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class MediaFillError(VenusError):
    """Raised when a Hamilton Media Fill Module operation fails.

    Covers a missing vendor driver, a COM ``HRESULT`` / non-zero vendor return
    code (the message includes the vendor's ``GetLastErrorMessage`` text) or an
    unknown ``device_id``. The Media Fill driver talks to the device directly
    and does not go through the VENUS runtime, but this subclasses
    :class:`VenusError` so existing ``except VenusError`` handlers keep working.

    ``error_code`` is the vendor call's return code (``1`` = failed) when the
    vendor object reported the failure, else ``None``.
    """

    def __init__(self, message: str = "", *, error_code: int | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class OperatorCancelledError(VenusError):
    """Raised when an operator declines a compound-command prompt.

    Currently emitted by ``_tip_manager.ensure_tips_available`` when the
    operator cancels a tip-reload request via ``StarClient.on_tip_reload_prompt``.
    """
