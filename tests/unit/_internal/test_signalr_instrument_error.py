"""Instrument error events must always reach the error resolver."""

from __future__ import annotations

import pytest

from hamilton_venus._internal._signalr_listener import _SignalRListener
from hamilton_venus.models.instrument_errors import ErrorData

# Vantage autoload "Load Carrier" barcode error (trimmed): the manual "Barcode"
# recovery has an input whose defaultValue VENUS sends as null.
BARCODE_ERROR = {
    "uuid": "d11f3180-6d58-4c2d-806f-abdc7d4e4e8e",
    "deviceId": 383869980,
    "code": "C0:05/00",
    "message": "C0:05/00",
    "title": "Load Carrier (Single Step) - Error",
    "timeout": -1,
    "actions": None,
    "detailedErrors": [
        {
            "uuid": "1da0bd3e-a8d4-437f-af67-8f96e6a4c3bb",
            "index": 0,
            "code": "0",
            "message": "Barcode error.",
            "recoveryActions": [
                {"id": 1030, "index": 0, "iterations": 0, "name": "Exclude", "inputs": None},
                {
                    "id": 211,
                    "index": 3,
                    "iterations": 0,
                    "name": "Barcode",
                    "inputs": [
                        {
                            "id": 1,
                            "name": "Barcode",
                            "pattern": None,
                            "defaultValue": None,
                            "valueType": "string",
                            "options": None,
                            "rules": None,
                            "index": 0,
                        }
                    ],
                },
            ],
            "actions": [{"id": 1208, "index": 0, "name": "Unload carrier", "inputs": None}],
        }
    ],
    "recoveryActions": [
        {"id": 1, "index": 0, "iterations": 0, "name": "Execute", "inputs": None},
        {"id": 1139, "index": 1, "iterations": 0, "name": "Abort", "inputs": None},
    ],
}


def test_null_input_default_value_parses_as_empty_string():
    error = ErrorData.model_validate(BARCODE_ERROR)
    barcode_input = error.detailed_errors[0].recovery_actions[1].inputs[0]
    assert barcode_input.default_value == ""


@pytest.mark.asyncio
async def test_barcode_error_event_is_dispatched_in_full():
    listener = _SignalRListener("http://localhost:42400")
    received: list[ErrorData] = []

    async def capture(event: ErrorData) -> None:
        received.append(event)

    listener.on_instrument_error(capture)
    await listener._on_instrument_error_event([BARCODE_ERROR])

    assert len(received) == 1
    assert received[0].detailed_errors[0].message == "Barcode error."


@pytest.mark.asyncio
async def test_unparseable_error_event_still_dispatched_with_identifying_fields():
    listener = _SignalRListener("http://localhost:42400")
    received: list[ErrorData] = []

    async def capture(event: ErrorData) -> None:
        received.append(event)

    listener.on_instrument_error(capture)
    broken = {**BARCODE_ERROR, "detailedErrors": [{"uuid": "x", "index": "not-an-int"}]}
    await listener._on_instrument_error_event([broken])

    assert len(received) == 1
    event = received[0]
    assert event.uuid == BARCODE_ERROR["uuid"]
    assert event.device_id == BARCODE_ERROR["deviceId"]
    assert event.code == "C0:05/00"
    assert event.detailed_errors is None
    assert event.recovery_actions == []
