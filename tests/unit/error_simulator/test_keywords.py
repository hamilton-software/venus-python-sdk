"""Unit tests for the ``_GenerateKeywords`` port."""

from __future__ import annotations

import pytest

from hamilton_venus.error_simulator.keywords import generate_keywords, keyword_sql_list


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Insufficient liquid level", ["INSUFFICIENT", "LIQUID", "LEVEL"]),
        ("Tip Pick Up", ["TIP", "PICK", "UP"]),
        ("No tip picked up", ["NO", "TIP", "PICKED", "UP"]),
        # "-" is stripped (not split on); " DRIVE"/"DRIVE" then removed
        ("Z-drive step lost", ["Z", "STEP", "LOST"]),
        ("Z drive step lost", ["Z", "STEP", "LOST"]),
        # stop-words (" IS ", " NOT ") dropped
        ("Object is not found", ["OBJECT", "FOUND"]),
        # synonym rewrites
        ("Aspiration failed", ["ASPIRATE", "FAILED"]),
        ("initialization error", ["INITIALIZE", "ERROR"]),
        ("MAXIMUM voltage", ["MAX", "VOLTAGE"]),
        ("2nd phase", ["SECOND", "PHASE"]),
    ],
)
def test_generate_keywords(text: str, expected: list[str]) -> None:
    assert generate_keywords(text) == expected


def test_drive_is_removed() -> None:
    assert "DRIVE" not in generate_keywords("Y drive not initialized")


def test_empty_and_none() -> None:
    assert generate_keywords("") == []
    assert generate_keywords(None) == []  # type: ignore[arg-type]


def test_sql_list_render() -> None:
    assert keyword_sql_list("Tip Pick Up") == "'TIP','PICK','UP'"
