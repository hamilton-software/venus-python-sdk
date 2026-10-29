"""Matching tests against the shipped knowledge base (converted ErrorSimulator.mdb)."""

from __future__ import annotations

import pytest

from hamilton_venus.error_simulator._generated_errors import StarChannels1MlError
from hamilton_venus.error_simulator._generated_steps import StarStep, VantageStep
from hamilton_venus.error_simulator.exceptions import NoMatchError
from hamilton_venus.error_simulator.knowledge_base import KnowledgeBase
from hamilton_venus.error_simulator.matching import match_error, match_firmware


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return KnowledgeBase.load()


def test_module_resolution(kb: KnowledgeBase) -> None:
    assert kb.resolve_module("1mL Channels").table == "1mL"
    assert kb.resolve_module("IPG/iSWAP").table == "IPG"
    assert kb.resolve_module("1mL").table == "1mL"  # canonical suffix


def test_firmware_match_star_and_vantage(kb: KnowledgeBase) -> None:
    star_1ml = kb.firmware_rows("STAR", kb.resolve_module("1mL"))
    assert match_firmware("Aspirate", star_1ml) == "C0AS"
    assert match_firmware("Tip Pick Up", star_1ml) == "C0TP"
    assert match_firmware(StarStep.ASPIRATE, star_1ml, exact=True) == "C0AS"

    vantage_1ml = kb.firmware_rows("VANTAGE", kb.resolve_module("1mL"))
    assert match_firmware(VantageStep.ASPIRATE, vantage_1ml, exact=True)


def test_star_error_has_main_prefix(kb: KnowledgeBase) -> None:
    rows = kb.error_rows("STAR", kb.resolve_module("1mL"))
    code = match_error(
        StarChannels1MlError.TIP_HANDLING_NO_TIP_PICKED_UP, rows, instrument="STAR", exact=True
    )
    assert "/" in code  # "<MAIN>/<CODE>"
    main, _, tail = code.partition("/")
    assert main.isdigit() and tail.isdigit()


def test_vantage_error_is_bare_code(kb: KnowledgeBase) -> None:
    rows = kb.error_rows("VANTAGE", kb.resolve_module("1mL"))
    match = next(r for r in rows if r.description.lower().startswith("main: tip not loaded"))
    code = match_error(match.description, rows, instrument="VANTAGE", exact=True)
    assert code == match.code
    assert "/" not in code


def test_exact_no_match_raises(kb: KnowledgeBase) -> None:
    rows = kb.error_rows("STAR", kb.resolve_module("1mL"))
    with pytest.raises(NoMatchError):
        match_error("this description does not exist anywhere", rows, instrument="STAR", exact=True)


def test_fuzzy_falls_through_to_nomatch_for_gibberish(kb: KnowledgeBase) -> None:
    rows = kb.error_rows("STAR", kb.resolve_module("1mL"))
    with pytest.raises(NoMatchError):
        match_error("zzzqqq nonsense tokens", rows, instrument="STAR")


def test_generated_constants_cover_every_row(kb: KnowledgeBase) -> None:
    """Every FW / ERROR description in the JSON is reachable as a constant."""
    from hamilton_venus.error_simulator import _generated_errors as errors_mod
    from hamilton_venus.error_simulator import _generated_steps as steps_mod

    step_values = {v for cls in _enums(steps_mod) for v in cls}
    error_values = {v for cls in _enums(errors_mod) for v in cls}

    for table_key in ("STAR-1mL", "VANTAGE-1mL", "STAR-IPG", "VANTAGE-MagPip"):
        instrument, _, _ = table_key.partition("-")
        module = kb.resolve_module(table_key.split("-", 1)[1])
        for row in kb.firmware_rows(instrument, module):
            assert row.description in step_values
        for row in kb.error_rows(instrument, module):
            assert row.description in error_values


def _enums(module: object) -> list[type]:
    from enum import EnumMeta

    return [obj for obj in vars(module).values() if isinstance(obj, EnumMeta)]
