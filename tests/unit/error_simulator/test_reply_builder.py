"""Golden-value tests for the ``SetError`` reply-string assembly."""

from __future__ import annotations

from hamilton_venus.error_simulator.reply_builder import (
    build_channel_reply,
    build_single_reply,
    no_error_reply,
)


def test_star_single_channel() -> None:
    reply = build_channel_reply(
        "STAR", "P", is_magpip=False, channel_codes=[(1, "06/71")], firmware_command="C0AS"
    )
    assert reply.value == "er99/00 P106/71"
    assert reply.no_error == "er00/00"
    assert reply.firmware_command == "C0AS"


def test_star_multi_channel_with_letter_mapping() -> None:
    reply = build_channel_reply(
        "STAR",
        "P",
        is_magpip=False,
        channel_codes=[(1, "08/75"), (10, "08/75")],
        firmware_command="C0TP",
    )
    assert reply.value == "er99/00 P108/75 PA08/75"


def test_star_all_no_error_collapses() -> None:
    reply = build_channel_reply(
        "STAR", "P", is_magpip=False, channel_codes=[(1, "00/00")], firmware_command="C0AS"
    )
    assert reply.value == "er00/00"


def test_star_single_module_ipg() -> None:
    reply = build_single_reply("STAR", "R0", error_code="21/95", firmware_command="R0ZP")
    assert reply.value == "er99/00 R021/95"


def test_vantage_single_channel_gets_trailing_quote() -> None:
    reply = build_channel_reply(
        "VANTAGE", "P", is_magpip=False, channel_codes=[(1, "05")], firmware_command="A1PM"
    )
    assert reply.value == 'er99es"P105"'
    assert reply.no_error == "er0"


def test_vantage_magpip_uses_colon_and_er82() -> None:
    reply = build_channel_reply(
        "VANTAGE", "W", is_magpip=True, channel_codes=[(1, "03")], firmware_command="W1PM"
    )
    assert reply.value == 'er82es"W1:03"'


def test_vantage_idl_behaves_like_main_code() -> None:
    reply = build_single_reply("VANTAGE", "I1", error_code="1234", firmware_command="I1AMCL")
    assert reply.value == "er1234"  # no wrapper, no trailing quote


def test_special_no_error_payloads() -> None:
    autoload = no_error_reply("STAR", "I1AMCL")
    assert autoload.startswith('er00ciFFFFFFFFbc160bd"/0009')
    assert autoload.endswith('"')
    barcode = no_error_reply("STAR", "C0CL")
    assert barcode.startswith("er00/00ciFFFFFFFFvl0009 ")
    assert barcode.endswith("/09Barcode32")
    assert no_error_reply("STAR", "C0AS") == "er00/00"
    assert no_error_reply("VANTAGE", "A1PM") == "er0"
