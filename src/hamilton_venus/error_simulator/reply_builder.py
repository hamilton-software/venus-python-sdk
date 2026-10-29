"""Port of the reply-string assembly in the ``ErrorSimulator`` HSL ``SetError``.

Turns resolved error code(s) into the exact simulated-firmware reply string the
HSL wrote as the value for a firmware command in ``<instrument>_Simulator.cfg``,
including every STAR / VANTAGE / MagPip / IDL special case:

* base wrapper ``er99/00 `` (STAR) or ``er99es"`` (VANTAGE)
* per-channel ``<prefix><channel><code> `` segments, ``:``-separated and
  ``er82`` for MagPip, channels 10-16 mapped to letters ``A``-``G``
* VANTAGE trailing ``"`` (except IDL / ``I1``)
* the long ``I1AMCL`` (autoload) and ``C0CL`` (barcode) "no error" payloads
"""

from __future__ import annotations

from dataclasses import dataclass

_CHANNEL_LETTERS = ["A", "B", "C", "D", "E", "F", "G"]  # channels 10..16

#: "No error" reply per instrument (the generic case).
_NO_ERROR = {"STAR": "er00/00", "VANTAGE": "er0"}

#: Firmware commands whose "no error" reply is a long structured payload.
_SPECIAL_NO_ERROR = {
    "I1AMCL": 'er00ciFFFFFFFFbc160bd"' + "/0009" * 32 + '"',
    "C0CL": (
        "er00/00ciFFFFFFFFvl"
        + " ".join(["0009"] * 32)
        + "bb"
        + "".join(f"/09Barcode{i:02d}" for i in range(1, 33))
    ),
}


@dataclass(frozen=True)
class Reply:
    """The three values ``SetError`` writes for one firmware command."""

    firmware_command: str
    value: str  # the simulated reply string
    no_error: str  # written to `updateParamValue`


def no_error_reply(instrument: str, firmware_command: str) -> str:
    """The "no error" reply for *firmware_command* (used to reset / as
    ``updateParamValue``)."""
    if firmware_command in _SPECIAL_NO_ERROR:
        return _SPECIAL_NO_ERROR[firmware_command]
    return _NO_ERROR[instrument]


def _channel_token(channel: int) -> str:
    if channel > 9:
        return _CHANNEL_LETTERS[channel - 10]
    return str(channel)


def build_channel_reply(
    instrument: str,
    module_prefix: str,
    *,
    is_magpip: bool,
    channel_codes: list[tuple[int, str]],
    firmware_command: str,
) -> Reply:
    """Assemble the reply for a per-channel (1mL / 5mL / X1 / MagPip) error."""
    no_error = no_error_reply(instrument, firmware_command)
    generic_no_error = _NO_ERROR[instrument]
    base = 'er99es"' if instrument == "VANTAGE" else "er99/00 "
    value = base
    for channel, code in channel_codes:
        if f"er{code}" == generic_no_error:
            continue
        sep = ":" if is_magpip else ""
        value += f"{module_prefix}{_channel_token(channel)}{sep}{code} "
    value = value.rstrip(" ")

    set_no_error = value in ("er99/00", 'er99es"')
    if is_magpip:
        value = value.replace("er99", "er82")
    if instrument == "VANTAGE" and module_prefix != "I1":
        value += '"'
    if set_no_error:
        value = no_error
    return Reply(firmware_command, value, no_error)


def build_single_reply(
    instrument: str,
    module_prefix: str,
    *,
    error_code: str,
    firmware_command: str,
) -> Reply:
    """Assemble the reply for a single (IPG / MPH96 / MPH384 / IDL) error."""
    no_error = no_error_reply(instrument, firmware_command)
    generic_no_error = _NO_ERROR[instrument]
    base = 'er99es"' if instrument == "VANTAGE" else "er99/00 "

    if f"er{error_code}" == generic_no_error:
        value = no_error
        return Reply(firmware_command, value, no_error)
    value = f"er{error_code}" if module_prefix == "I1" else f"{base}{module_prefix}{error_code}"

    if instrument == "VANTAGE" and module_prefix != "I1":
        value += '"'
    return Reply(firmware_command, value, no_error)
