"""FastMCP server exposing hamilton_venus.StarClient/VantageClient to AI agents.

Session lifecycle (client start/stop, deck loading, instrument connect) and the
tricky operator-escalation handling are delegated to
``hamilton_workflow_framework.WorkflowSession`` unmodified -- the same code every
Hamilton workflow UI uses -- instead of reimplementing them here. What's new in
this module is purely the MCP-facing surface: reflection-driven command discovery
(``catalog``) and dispatch (``coercion``) in place of a per-app curated command
registry + WebSocket UI.

Both Hamilton STAR and Hamilton Vantage instruments are supported: start_session's
instrument_type parameter picks which client WorkflowSession constructs, and every
discovery/dispatch tool below reads from whichever of CATALOG_BY_INSTRUMENT's two
catalogs matches the active session, so a Vantage session never sees (or can call)
a command the active client class has no method for (e.g. StarClient's CO-RE 5mL
transport, or VantageClient's load tray / interior status light).
"""

from __future__ import annotations

import asyncio
import json
import re
import logging
import os
import socket
import threading
import time
import urllib.request
from typing import Any

from mcp import types as mcp_types
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from hamilton_venus.error_handling import ErrorEntry, ErrorProfile
from hamilton_venus.error_handling.presets import BUILTIN_ERROR_PROFILES
from hamilton_venus.error_handling.profile_loaders import profile_from_json
from hamilton_venus.exceptions import VenusCommandFailedError, VenusError
from hamilton_venus.models import InstrumentType
from hamilton_venus.models.enums import LightColor
from hamilton_venus.models.error_types import RecoveryAction
from hamilton_venus.standalone_devices import find_standalone_device
from hamilton_venus.tools.generate_catalog import regenerate_catalog as _regenerate_local_catalog
from hamilton_workflow_framework import WorkflowBackendConfig, WorkflowSession
from hamilton_workflow_framework.session import BUSY_RUN_STATES

from hamilton_venus_mcp import deck_tracks, venus_api
from hamilton_venus_mcp.auth import configured_token
from hamilton_venus_mcp.catalog import CATALOG_BY_INSTRUMENT, CommandSpec, describe_command
from hamilton_venus_mcp.command_kinds import is_query_command
from hamilton_venus_mcp.coercion import coerce_kwargs, serialize_result
from hamilton_venus_mcp.docs_catalog import DOCS_BY_PATH, DOCS_CATALOG, read_doc_text
from hamilton_venus_mcp.labware_catalog import LABWARE_CATALOG
from hamilton_venus_mcp.run_control import RunControl, RunControlError
from hamilton_venus_mcp.script_runs.manager import RunManager
from hamilton_venus_mcp.script_runs.operator_gate import OperatorGate
from hamilton_venus_mcp.script_runs.operator_http import OperatorServer, start_operator_server
from hamilton_venus_mcp import instrument_guard
from hamilton_venus_mcp.script_validator import validate_bytes
from hamilton_venus_mcp.scripts_store import ScriptStore

_logger = logging.getLogger("hamilton_venus_mcp.server")

# The full usage guide, served by the get_usage_guide tool (see _INSTRUCTIONS below).
_GUIDE = (
    "Controls a Hamilton STAR or Hamilton Vantage liquid-handling instrument through "
    "the VENUS Python SDK.\n\n"
    "Typical flow:\n"
    "1. start_session() to boot a client for the installed instrument (get_session_status shows "
    "installed_instrument_type; the other family is refused). The USER always "
    "chooses simulation vs live and the deck layout -- never pick either for them; pass only "
    "what the user said. When the app can show forms, start_session always asks them itself "
    "(simulation or live first; then, with the client up but the instrument not connected, a "
    "blank layout, the last layout used with a summary, or a saved layout), and anything you "
    "pass is only pre-selected. Some apps (Claude Desktop's Code tab) cancel these forms without "
    "showing them, so still ask the user simulation or live in the chat before calling "
    "start_session. If the result has deck_choice_required=True (the app couldn't show the form "
    "or the user dismissed it), show the user deck_options -- blank, last_layout_summary and "
    "saved_layouts -- always offering all three kinds, even when the last layout is empty -- "
    "ask which they want, and call select_deck_layout(deck_name=... | load_previous_deck=True | "
    "blank_deck=True), which loads it and connects the instrument (never call start_session "
    "again for this). connect_instrument refuses until a layout is chosen. If start_session "
    "errors asking for simulate, ask the user simulation or live and call it again with their "
    "answer. When the user named the layout up front, pass deck_name, "
    "load_previous_deck=True or blank_deck=True directly. After connect_instrument(), verify what's "
    "actually on the deck with call_sdk_command(\"get_added_plates\") / "
    "\"get_added_carriers\" / \"get_added_tip_racks\" / \"get_added_reservoirs\" rather than "
    "assuming -- there is no single \"get whole deck layout\" command; these are queried "
    "separately per labware category.\n"
    "2. connect_instrument() to bring the instrument runtime online. Always follow it with "
    "two more calls before running any protocol, real hardware or simulated: "
    "call_sdk_command(\"instrument_get_configuration\") to learn the actual arm/tool "
    "configuration (per-arm channels_1_ml/channels_5_ml/channels_mag_pip/mph96/mph384/"
    "gripper, and each arm's x_min/x_max physical reach range) rather than assuming which "
    "tools exist or how far they reach; and call_sdk_command(\"autoload_get_carrier_sensor_"
    "status\") to verify every carrier the deck layout expects is actually physically "
    "loaded -- each entry's `status` is True if that carrier is physically pushed in, "
    "False if the sensor doesn't see it (only meaningful where `sensorAvailable` is also "
    "True for that track). IMPORTANT: confirmed directly against real hardware -- in a "
    "simulate=True session `status` comes back False for every single carrier, "
    "unconditionally, regardless of what the deck layout actually specifies. Do NOT "
    "interpret that as \"no carriers are loaded\" or fail/warn on it when simulate=True; "
    "there is no physical sensor to read in simulation, so this check is only "
    "authoritative against real hardware and should be skipped entirely otherwise.\n"
    "3. list_sdk_commands / list_sdk_categories to discover what's available for the "
    "active session's instrument type, describe_sdk_command(name) to see a command's "
    "full parameter schema.\n"
    "4. call_sdk_command(name, kwargs) to run it. send_raw_command is a fallback for "
    "anything without a dedicated typed method.\n"
    "5. get_recent_events() after a call to see SDK trace output; if an instrument error "
    "raises an operator_prompt event, resolve it with resolve_operator_prompt before "
    "retrying.\n"
    "6. close_session() when done.\n\n"
    "Need a labware type name/id for a deck layout or an SDK call (e.g. a carrier or "
    "plate name)? Use search_labware/list_labware_categories rather than reading "
    "hamilton_venus/catalog/labware.py directly -- it's the same static catalog, just "
    "searchable. Not the same lookup as get_labware_spec, which is for an instance "
    "already on the active deck, not a type name.\n\n"
    "This SDK's own docs/*.md files (authentication, configuration, error handling, JSON "
    "schemas, worked examples for autoload/deck-and-layout/liquid-handling/position-and-"
    "well-selection/etc., labware schema conventions) are available two ways: as tools -- "
    "list_sdk_docs(search=...) then read_sdk_doc(relative_path) -- or as MCP resources "
    "under docs://hamilton-venus/... (see this server's own resources/list). Prefer these "
    "over guessing at file contents or assuming a doc doesn't exist.\n\n"
    "Example call_sdk_command shape: call_sdk_command(name=\"aspirate\", kwargs={\"positions\": "
    "\"Plate1@A1\", \"volumes\": 100.0, \"liquid_class\": \"...\"}) -- kwargs is always a single "
    "flat dict of that command's own parameter names, never nested further.\n\n"
    "Any command with a `positions`-style parameter (aspirate, dispense, tip_pickup, "
    "tip_eject, detect_liquid_level, add_reagent's reagent_source/dest_plate, pool_samples/"
    "replicate_samples' source_plate/dest_plate, serial_dilution's plate_id, ...) accepts a "
    "compact selector DSL string instead of building explicit position objects by hand -- "
    "prefer it: `\"Plate1\"` (every well, equivalent to `\"Plate1@all\"`), `\"Plate1@A1\"` "
    "(one well), `\"Plate1@A1,B1,C1\"` (explicit wells, any number, comma-separated), "
    "`\"Plate1@A1:C3\"` (rectangular range), `\"Plate1@row:A,C:E\"` (whole rows), "
    "`\"Plate1@col:1,3:5\"` (whole columns). The colon after `row`/`col` is required, not "
    "optional -- `row2`/`col1` are NOT valid syntax and will be rejected or misparsed as a "
    "literal (nonsense) well name, not silently corrected. A single-well selector is "
    "automatically repeated across every channel when more than one channel is used (e.g. "
    "every tip pooling into one shared destination well on a plate) -- it is not a "
    "channel-count mismatch. Not every command uses `positions` as the parameter name for "
    "this DSL (e.g. core_transport uses `site` instead) -- check describe_sdk_command(name) "
    "rather than assuming a parameter named `positions` exists; it also shows the full "
    "accepted shape (the selector string, a wire-format dict, or an explicit "
    "{\"labwareId\":..., \"wellId\":...} object) for whichever parameter takes positions.\n\n"
    "IMPORTANT -- reservoirs specifically: always address a reservoir with the \"@all\" "
    "selector (e.g. \"Trough1@all\"), never a single well like \"Trough1@A1\" alone. A "
    "reservoir is a connected-container labware (LabwareLayoutSpec.connected_container) "
    "whose several row/column positions are meant to be distributed one per channel via "
    "\"@all\" -- addressing only the first well undersupplies or misdirects every channel "
    "past the first instead of spreading them across the reservoir's actual usable "
    "positions. This is also a real performance cost, confirmed directly: pipetting "
    "channels are rigidly spaced on the arm and physically cannot occupy the same point at "
    "once, so a single well repeated across channels forces the instrument to aspirate them "
    "one at a time (repositioning between each) instead of one simultaneous multi-channel "
    "aspirate -- \"@all\" lets the SDK's own spacing-aware interleaving engine "
    "(well_sequencing.py) assign each channel a distinct, physically-reachable position so "
    "the whole group aspirates together.\n\n"
    "IMPORTANT -- labware id casing: VENUS stores every labware id lower-cased on the deck "
    "layout, regardless of the case it was added with -- add_carrier/add_reservoir/etc.'s "
    "call_sdk_command(\"add_reservoir\", {..., \"labware_id\": \"Trough1\"}) is later reported "
    "back by VENUS, and by every tracking event or query result that names it (labware "
    "events, get_added_plates/get_added_reservoirs/get_added_tip_racks, get_run's tracking), "
    "as \"trough1\". A positions selector string (e.g. \"Trough1@all\") is matched against "
    "VENUS's storage server-side, so it does not need to be lower-cased -- but if you compare "
    "a labware id you typed against one read back from a tool result (or use it as a dict "
    "key, e.g. register_reagent's labware argument), normalize both to the same case first "
    "rather than assuming the original casing survives the round trip.\n\n"
    "Before pipetting with a specific tool (1mL/5mL/MagPip channels, MPH96, gripper, ...), "
    "verify every labware you're about to target is actually reachable by that tool: cross-"
    "check call_sdk_command(\"get_labware_coordinates\", {\"labware_name\": ...})'s "
    "origin x coordinate (returned under \"origin\" when no well is given, next to a "
    "\"wells\" list with every well's coordinates; pass \"well\" to get one well's x/y/z "
    "at the top level instead) against instrument_get_configuration()'s matching arm's x_min/x_max range "
    "(from step 2 above) rather than assuming every labware on the deck is reachable by "
    "every tool -- this matters most on a dual-arm Vantage, or any deck with labware placed "
    "on a far track.\n\n"
    "Moving labware: use the CO-RE grips (add_1ml_core_grip on Legacy STAR channels, add_qcg on "
    "Fluid Motion channels or a Vantage) for on-deck moves whenever the instrument has them -- "
    "they come straight down and need no side clearance. The CO-RE grips are a separate tool, "
    "not an arm device: instrument_get_configuration never lists them (an arm's gripper.type is "
    "only its iSWAP / IPG), which is why add_1ml_core_grip / add_qcg exist. Systems may or may "
    "not have them, so a configuration showing only an iSWAP says nothing about CO-RE grips: "
    "if the deck doesn't already have them (get_transport_tool_ids), ask the user. When the "
    "user says the system has CO-RE grips, that means they are physically fitted, NOT that they "
    "are in the layout: a layout (blank, or one being built) has no grip tool until it is "
    "added. So check get_transport_tool_ids and, if it is empty, add them as part of building "
    "the layout -- add_1ml_core_grip for Legacy 1 mL channels, add_qcg for Fluid Motion "
    "channels or a Vantage (instrument_get_configuration's channels1mL type) -- and confirm it "
    "from the result; never report them as set up without that check. "
    "Use the iSWAP / IPG only for off-deck "
    "or extended-reach moves, rotations, when there are no CO-RE grips, or when the user asks: "
    "it grips from the sides (left/right for a narrow grip, front/back for a wide one) and can "
    "hit adjacent labware taller than the target. Eject tips before the CO-RE grips, keep the "
    "grips on for a series of moves (core_transport eject_grip=False) and eject them after the "
    "last; iswap_park() after a series of iSWAP moves. A lid held by the CO-RE grips or the "
    "iSWAP allows MPH pipetting only, not channels (except an iSWAP on a Vantage second arm).\n\n"
    "Tilted plates: call_sdk_command(\"tilt_labware\", {\"labware_name\": ..., \"tilt_degrees\": "
    "0-10, \"pivot_point\": \"LeftEdge\"|\"Center\", \"well_position\": \"Center\"|\"DeepestPoint\"|"
    "\"HighestPoint\"}) offsets every well of a plate (plates only) in the deck layout to match a "
    "tilt; it does NOT move the tilt hardware. DeepestPoint / HighestPoint aim one tip as close to "
    "the low / high wall as it fits: pass \"tip_end_height_mm\" (the fixed height you will pipette "
    "at), and optionally \"wall_margin_mm\" (default 1.0) / \"high_wall_margin_mm\" (default 2.0) and "
    "\"measured_tilt_degrees\" (the plate's real angle, e.g. 10.8). It raises ValueError, naming the "
    "largest angle that fits, when no tip fits (e.g. 96-well plates at 10 degrees). Calls do not add up -- each is computed from the "
    "flat plate, so re-calling at the same angle with another well_position just re-aims (e.g. "
    "remove media at DeepestPoint, then add buffer at HighestPoint) -- and tilt_degrees=0 "
    "returns the plate to flat. While a plate is tilted every transport command for it is "
    "refused (LabwareTiltedError) until it is tilted back to 0; is_labware_tilted / "
    "get_tilted_labware report the state. On a tilted plate use fixed heights with "
    "capacitive_lld OFF and liquid_following False -- LLD and liquid following assume vertical "
    "wells. See docs examples/deck_and_layout.md (Tilt Labware).\n\n"
    "Carrier widths: never assume a carrier's width -- not 5, not 10. search_labware gives each "
    "carrier's real width as \"width_tracks\" (from its definition: "
    "customAttributes[\"hamilton:star\"].widthAsTracks); look up EVERY carrier type you will "
    "place before choosing any left_track. Most plate and tip carriers are 6 or 7 tracks, "
    "reagent and sample/tube carriers 1 or 2, TIP_CAR_288 is 4. A carrier at left_track t takes "
    "tracks t .. t + width - 1, so the next one goes at t + width or later. add_carrier / "
    "add_tube_carrier / move_carrier refuse a placement that overlaps another carrier or runs "
    "off the deck, naming the free tracks and where it fits, and a successful one reports the "
    "tracks it took (\"deck_tracks\"). Don't retry a refused placement one track over: re-plan "
    "from the widths.\n\n"
    "Tip carriers: the carrier depends on the channels and how many racks are needed, NOT on the "
    "tip size -- any standard tip rack (10/50/300/1000 uL, filter or not) fits any of these. "
    "TIP_CAR_480BC: 5 landscape sites, the default; use it unless there is a reason below. "
    "TIP_CAR_384BC: 4 sites grouped toward the center of the carrier, for random access by "
    "16-channel systems (the \"384\" has nothing to do with 384 formats or 50 uL tips). "
    "TIP_CAR_288: 3 portrait sites, for 12-channel systems, so all 12 channels pick up a full row "
    "of tips in one go. TIP_CAR_NTR: nested tip racks (NTR) only. Don't pick a different tip "
    "carrier per tip size; ask the user if the channel count or rack count suggests otherwise.\n\n"
    "MPH96 tips: the 96 head picks up a full set from fixed tip racks (add_tip_rack), nested tip "
    "racks (add_ntr) and tip boxes (add_tip_box) -- NTRs are fine for it. Partial (column / row) "
    "pickups from any of them need a tip support on the carrier site first: "
    "add_tip_support(carrier_id, site), before tip_pick_up_mph96_partial; mph96_clear_tip_support "
    "clears it.\n\n"
    "Replacing a labware definition (e.g. a corrected custom one): register it under a NEW name "
    "-- a definition added with the name of one already loaded is not loaded -- and use that "
    "new name from then on.\n\n"
    "Sample tube carriers (SMP_CAR_*): add_tube_carrier loads the carrier WITH its tubes -- its "
    "definition is a rack of tube positions (\"Sample carrier with 24 positions with preloaded "
    "15x100 tubes\"); nothing else has to be added before pipetting. Address a tube as "
    "\"<carrier>@<position>\" (e.g. \"smp_car_24_15x100_0001@1\" .. \"@24\"). To confirm the tubes, use "
    "get_labware_coordinates(<carrier>) with no well (it lists every position) or "
    "get_labware_spec(<carrier>). Do NOT use get_labware_on_carrier, get_occupied_carrier_sites, "
    "get_available_carrier_sites, get_top_labware or get_labware_location for tube carriers: "
    "they are for carriers with sites and return nothing for one, which does not mean the tubes "
    "are missing. Sample tracking (get_labware_details) only knows a tube once something was "
    "done to it. Use add_tubes_to_carrier only to put a different tube type in some positions; "
    "leave zOffset out so the tubes sit where the carrier's own tubes do (the carrier "
    "definition's height, typically 10 mm -- 0 would put them on the carrier base), and pass it "
    "only when the user asks to raise or lower them, as the full height above the carrier base "
    "(e.g. 15 to raise them 5 mm).\n\n"
    "Several channels in one large well (6/12/24-well plates, 50 mL tubes): call_sdk_command("
    "\"split_wells\", {\"labware_name\": ..., \"wells\": \"A1:B3\", \"channel_type\": \"1mL\"|\"5mL\", "
    "\"fit\": \"position\"|\"max_channels\"|<int>}) places channel-pitch slots (9 mm / 18 mm) "
    "inside each well, sized from the labware definition and any tilt. Afterwards aspirate / "
    "dispense / detect_liquid_level with 2+ channels of that type on one split well are routed "
    "to its slots automatically (channel c -> slot c - first_channel + 1); more channels than "
    "slots raises SplitWellCapacityError. On a plate tilted to DeepestPoint, fit=\"position\" and "
    "fit=\"max_channels\" both use as many channels as the well holds, as close to the wall as they "
    "fit; an int asks for exactly that many (fewer channels sit closer to the wall). split_wells "
    "reuses tilt_labware's tip end height and margins. The splits follow the plate through "
    "tilt_labware, shift_labware, move_carrier and transports, and are removed by "
    "remove_labware / remove_split_wells; get_split_wells lists them.\n\n"
    "Choosing a liquid class for a transfer -- never pick one by its name, and never one for a "
    "pipetting device this instrument does not have (e.g. a MagPip class without MagPip channels):\n"
    "a. call_sdk_command(\"get_registered_tip_types\") (works once start_session has run, even "
    "before connect_instrument) lists the tip types registered in VENUS by id: name, max liquid "
    "volume (the most a tip can transfer), tip_length (the whole tip) and length_below_channel "
    "(tip_length minus the collar depth up to the channel's stop disk, e.g. 59.9 - 8 = 51.9 mm for a "
    "300 uL tip -- the length that matters for heights and clearances), filter, conductive, and the "
    "devices that can use it. A tip type not in this list cannot be used.\n"
    "b. call_sdk_command(\"find_liquid_classes\", {\"liquid\": ..., \"dispense_mode\": ..., "
    "\"volume\": ..., \"tip_pool\": ...}) -- it takes the tip type loaded in that pool, the "
    "pipetting device from instrument_get_configuration (pass device=\"1mL\"|\"5mL\"|\"MagPip\"|"
    "\"MPH96\"|\"MPH384\" to choose one), and returns the matching classes best first: same "
    "device, same tip type, same dispense mode, volume in range, closest liquid, Hamilton's "
    "validated originals before custom ones. It refuses (with the reason) a device that is not "
    "fitted, a tip that is not registered or not usable on the device, or a volume over the tip's "
    "max liquid volume -- tell the user rather than working around it. Use the first candidate "
    "unless the user wants another; when its liquid_match is not \"exact\", say which liquid it "
    "was made for.\n"
    "c. Dispense mode: no liquid contact + single dispense (empty well, or dispensing above the "
    "liquid) -> \"jet_empty\", fixed-height only (jet modes do not support cLLD: "
    "DispenseSettings.capacitive_lld must be CapacitiveLLD.OFF). No contact + multi-dispense -> "
    "\"jet_part\", also fixed-height only. Touching the liquid + single dispense -> "
    "\"surface_empty\" (cLLD or fixed height). Touching + multi-dispense -> \"surface_part\".\n"
    "d. A pipetting command whose liquid class is for another device or the other instrument "
    "fails before it is sent (LiquidClassMismatchError); run find_liquid_classes again rather than "
    "guessing another name.\n"
    "e. Tip length vs labware depth: a tip reaches only its length_below_channel below the "
    "channel. Pipetting deeper into a well or tube than that puts the channel itself "
    "inside the container, where it can touch the wall -- a contamination risk (e.g. "
    "a 50 uL tip in a 100 mm tube). When choosing tips for deep labware (tubes, deep-well plates), "
    "call_sdk_command(\"check_tip_reach\", {\"labware_name\": ..., \"tip_pool\": ...}) and prefer a tip "
    "it reports ok. Pipetting commands check this themselves: a call_sdk_command result with "
    "\"warnings\" must be shown to the user before you continue -- say what the risk is and offer "
    "the longer tips it names.\n\n"
    "To exercise error-recovery in a simulated session: set_simulated_error(module, "
    "step, error) before a step to make it fail, then clear_simulated_errors() to "
    "restore normal replies. list_simulatable_errors(module) shows valid values.\n\n"
    "IMPORTANT -- tip_pool_show_tip_counter/tip_pool_show_tip_counters: these open a dialog "
    "on VENUS's own screen, on the instrument PC. Called through this server (locally or "
    "through a hub), there is no way to see or interact with that dialog -- the call simply "
    "blocks until a human at the instrument closes it, then returns whatever the dialog's "
    "result was. Do not call either of these expecting to read or drive the dialog "
    "yourself, and do not treat a long-blocked call as stuck -- it is normal for it to wait "
    "on a person at the instrument, or forever if nobody is there. For any tip-counter "
    "change you need to make programmatically (initializing, resetting, or setting counts, "
    "or just reading the current state), use tip_pool_initialize_tip_counter / "
    "tip_pool_reset_tip_counter / tip_pool_set_tip_counter / tip_pool_get_tip_counter / "
    "tip_pool_get_tip_counters instead -- none of those open a dialog.\n\n"
    "IMPORTANT -- tip counters after adding tip racks: a tip pool name used before with "
    "different labware makes the first tip_pickup fail with \"Rack transport is not "
    "possible\". After the last add_tip_rack (or a loaded deck with tip pools) and before the "
    "first tip_pickup: in a simulated session, always call tip_pool_reset_tip_counter for every "
    "pool the session will use. On the live instrument, ask the user whether the racks are "
    "full -- if so reset each pool; otherwise call tip_pool_show_tip_counters for the pools "
    "and tell the user to complete the dialog at the instrument PC (or use "
    "tip_pool_set_tip_counter with the tips they tell you are present). Do the same if that "
    "error ever appears.\n\n"
    "Some commands (hhc_*, e.g. hhc_connect; odtc_*, e.g. odtc_connect) drive a benchtop "
    "device (Hamilton Heater Cooler / Inheco ODTC) directly over its own vendor COM object -- "
    "they are pure Python and do NOT touch the STAR/Vantage instrument or VENUS runtime at "
    "all. They still go through list_sdk_commands/call_sdk_command exactly like every other "
    "command -- call them the same way. start_session()/connect_instrument() are NOT required "
    "first for these specifically (though calling them anyway, e.g. for other steps in the "
    "same session, is harmless) -- do not assume an hhc_*/odtc_* command needs a separate "
    "script or a different client just because it isn't instrument-related; try "
    "call_sdk_command first.\n\n"
    "The MFX Tilt Module works the same way: tilt_module_* commands (tilt_module_connect(system_id, "
    "com_port), tilt_module_initialize(system_id, module_name), tilt_module_move_to_position("
    "system_id, module_name, angle 0-10), tilt_module_terminate_module, "
    "tilt_module_terminate_communication, tilt_module_get_status) drive the module over its own "
    "RS-232 port, with no session needed. They only move the hardware: VENUS still thinks the "
    "plate is flat until tilt_labware is called for the plate on it at the same angle, so pair "
    "them -- tilt_module_move_to_position then tilt_labware to tilt, and tilt_labware(..., 0) "
    "then tilt_module_move_to_position(..., 0) before transporting the plate. The module "
    "reports no position; tilt_module_get_status gives the last commanded angle.\n\n"
    "media_fill_* (Hamilton Media Fill Module, e.g. media_fill_connect) works the same way: "
    "pure Python, no session needed.\n\n"
    "Running a whole script instead of one command at a time (for anything with a loop or a "
    "sequence of steps, this is usually better than many call_sdk_command calls):\n"
    "a. import_script(name, content=\"...\") stores a Python script in this spoke's scripts "
    "folder and checks it against the SDK: every client command must exist, take the keyword "
    "arguments it is given, and pass pydantic validation; catalog names (LABWARE/LIQUID_CLASSES/"
    "enums) must resolve; there must be no GUI dialogs, input(), or unsafe calls (scripts run "
    "headless). Read the report's errors (each has a rule id, a line, and often a suggestion), "
    "fix them, and import again with overwrite=True. Only a script whose validation is clean "
    "can be run; list_scripts/get_script/validate_script inspect what is stored. Write scripts "
    "in the same style as the SDK's example scripts (docs/ via list_sdk_docs).\n"
    "b. run_script(script, simulate=True) starts it and returns a run_id immediately. simulate "
    "is forced into every StarClient/VantageClient the script builds, whatever the script says. "
    "Only pass simulate=False when the user explicitly asked for real hardware, and only if the "
    "spoke's operator has enabled that.\n"
    "c. Follow the run with get_run_events(run_id, since_seq=<the last next_since_seq>, "
    "wait_s=20) -- a long poll -- and get_run(run_id) for its state, current line, labware, "
    "tip consumption, and liquid seen at each aspirate. pause_run / resume_run / abort_run "
    "control it.\n"
    "d. If an instrument error the SDK cannot recover from happens (or tips/liquid need "
    "reloading), what happens next depends on whether this spoke has an operator token "
    "configured (HAMILTON_MCP_OPERATOR_TOKEN, set on the spoke's own machine, never visible to "
    "you). With one: the script stops and WAITS FOR A HUMAN. The prompt and the options VENUS "
    "offers appear in get_run_events, get_run, and get_spoke_state (state \"error\"). Tell the "
    "user, and have them answer it on the operator page (get_spoke_state's operator_ui.url) or "
    "the hub dashboard. You cannot answer it and must not try: the answer needs an operator "
    "token you do not have. Without one: the run does NOT stop and wait for a remote answer -- "
    "nobody but a person physically at the instrument could ever give one -- it hands the error "
    "straight to VENUS's own local operator dialog instead (an operator_error_deferred event, "
    "informational only) and keeps waiting on whatever that person does locally. Either way, "
    "you are only ever informed, never asked to decide.\n"
    "e. get_spoke_state() says idle / running / error at any moment. After a failed run, call "
    "acknowledge_run_error(run_id) once the user has seen it.\n"
    "f. get_venus_run_state, get_venus_current_run_data, list_venus_run_history, "
    "get_venus_run_detail, get_venus_run_trace and venus_pause / venus_resume / venus_abort "
    "look at and control VENUS itself, whoever started the run.\n"
    "g. Once a run finishes, get_run_summary(run_id) gives the result/duration/error counts, "
    "failed steps with their script line, tips/plates/lids used by type, and reservoir volumes "
    "drawn.\n"
    "h. Consumables (tips, reagents, plates, lids) tracked across every run over time: "
    "get_consumables_usage(...) for totals over a period (group by item/day/run/script), "
    "get_consumables_levels()/list_low_consumables() for current stock, get_consumables_config()"
    "/set_tip_threshold/register_reagent to configure what is tracked and its low threshold. "
    "record_consumable_event (a manual reload/correction) is HUMAN OPERATORS ONLY, gated by the "
    "operator token exactly like resolving a prompt -- do not attempt it yourself.\n\n"
    "Stop / Resume / Resume From for commands sent one at a time (call_sdk_command): every "
    "normal STAR/Vantage command gets a step number (returned as \"step\"). With "
    "start_session(hold_on_error=True) (or set_hold_on_error), a command that fails with an "
    "error answered as Cancel (VENUS keeps running) is HELD instead of reported: the call "
    "returns status \"held\" and its caller waits with await_command_step(step). "
    "stop_commands() holds the next normal command before it runs. While held, only commands "
    "sent with call_sdk_command(..., recovery=True) run (door unlock/lock, tip eject, tip "
    "pickup, ...); they are journaled but never replayed. Then resume_commands() re-runs the "
    "held step and hands its result to the waiting caller, resume_commands_from(step) first "
    "replays the earlier successful steps from that step on, and release_command_hold() fails "
    "the held step instead. get_command_hold / get_command_journal show the state. An ABORT "
    "ends the VENUS method and is never held. To be told about a hold the moment it "
    "happens instead of polling: keep wait_for_command_event(since_seq=..., wait_s=20) "
    "running in a loop, or subscribe_command_events(url) for an HTTP POST per event; the "
    "instrument's front status light also shows it (VENUS colors: white idle, green "
    "running, red held on an error, blue stopped; off when the session closes). Only a Cancel "
    "is held -- start_session(error_profile=\"cancel_all\") (or set_error_profile) makes "
    "every error end in Cancel instead of a retry or operator prompt.\n\n"
    "IMPORTANT: simulate=True never touches real hardware. start_session has no default: the "
    "user chooses. Never pass simulate=False -- which drives an actual instrument -- unless the "
    "user explicitly chose the live instrument."
)

def _installed_instrument() -> InstrumentType | None:
    """The instrument family this PC's VENUS is installed for (see instrument_guard)."""
    return instrument_guard.installed_instrument()


def _installed_value() -> str | None:
    installed = _installed_instrument()
    return installed.value if installed else None


_OPENING = (
    f"This PC's VENUS is a Hamilton {_installed_instrument().value}: start_session uses it and "
    "refuses the other family. Essentials follow. "
    if _installed_instrument()
    else "Drives a Hamilton STAR or Vantage through the VENUS Python SDK. These are the essentials. "
)


# What the AI is told up front. MCP clients pass a server's instructions to the model cut to
# its first 4,096 characters (Claude Code does), so this is only the essentials and must stay
# under that; the full guide (_GUIDE) is the get_usage_guide tool.
_INSTRUCTIONS = (
    _OPENING
    + "The full guide is the get_usage_guide tool: call get_usage_guide(search=...) for the "
    "details before doing something new in this conversation -- e.g. \"positions\", "
    "\"reservoir\", \"reach\", \"transport\", \"tilt\", \"tube carriers\", \"split_wells\", "
    "\"liquid class\", \"tip counter\", \"hhc\", \"run_script\", \"stop_commands\".\n\n"
    "Session: the USER chooses simulation vs live and the deck layout; never choose for them. "
    "start_session asks them with forms when the app can; otherwise ask in the chat and pass "
    "simulate. If its result has deck_choice_required, show deck_options (blank, last layout, "
    "saved layouts), ask, and call select_deck_layout with the answer (not start_session again). "
    "Never pass simulate=False unless the user chose live.\n\n"
    "After connect_instrument: call_sdk_command(\"instrument_get_configuration\") for the arms, "
    "1 mL channels (type Legacy / Fluid Motion), MPH heads, iSWAP / IPG (gripper.type) and reach. "
    "autoload_get_carrier_sensor_status always reads False in simulation; ignore it there.\n\n"
    "Commands: list_sdk_commands / describe_sdk_command, then call_sdk_command(name, kwargs). "
    "Positions are selector strings (\"Plate1@A1:H1\", \"Plate1@col:1\"); a reservoir is "
    "always \"Trough1@all\". VENUS lower-cases labware ids.\n\n"
    "Building a deck:\n"
    "- Carrier widths: never assume them. search_labware gives each carrier type's width_tracks; "
    "look up every type before choosing any left_track. A carrier at track t takes tracks "
    "t .. t+width-1. add_carrier / move_carrier refuse overlaps and say where it fits -- re-plan, "
    "don't retry one track over.\n"
    "- CO-RE grips are a separate TOOL, not an arm device: instrument_get_configuration NEVER "
    "reports them (gripper.type is only the iSWAP / IPG), so it never shows there are none. "
    "\"The system has CO-RE grips\" means physically fitted, not in the layout: check "
    "get_transport_tool_ids and, if empty, add them (add_1ml_core_grip for Legacy 1 mL channels, "
    "add_qcg for Fluid Motion channels or a Vantage). Not sure it has them? Ask the user.\n"
    "- Tip carriers: TIP_CAR_480BC (5 sites) is the default for any standard tip rack, whatever "
    "the tip size; TIP_CAR_384BC (4 sites) is for 16-channel systems, TIP_CAR_288 (3, portrait) "
    "for 12-channel ones, TIP_CAR_NTR only for nested tip racks (add_ntr with stack=N; ask the "
    "user whether they have single racks or stacks, and how many). The 96 head picks up from "
    "tip racks, NTRs and tip boxes; partial pickups need add_tip_support first.\n"
    "- 96 / 384 head reservoirs are the SBS troughs named for the head (HAM_DW_RGT_96, "
    "NUN_*_96C_RGT, ...) on a plate carrier (PLT_CAR_L5_DWP); RGT_CONT / RGT_VESSEL troughs are "
    "for the channels only. Labware that fits the same carrier shares it, one per site.\n"
    "- Replacing a labware definition: register it under a new name.\n"
    "- After adding tip racks, reset the tip counters (simulation) or ask the user (live) before "
    "the first tip pickup. A script does it itself: if star.simulate reset, else show them.\n\n"
    "Moving labware: CO-RE grips for on-deck moves when the system has them; the iSWAP / IPG "
    "only for off-deck or extended-reach moves, rotations, no CO-RE grips, or when asked (it "
    "grips from the sides and can hit taller labware next to the target). Keep the grips on for "
    "a series of moves and eject them after the last; park the iSWAP after its series.\n\n"
    "Liquid classes: ask what the liquid is if the user hasn't said, then pick with "
    "find_liquid_classes (device, tip, dispense mode, volume), never by name; judge a class by its "
    "summary and numbers, not its name (\"1000ul\" in a 96 head class is the head). Every aspirate and "
    "dispense gets settings chosen for the liquid and labware (LLD or fixed height, dispense "
    "mode and height, mixing), never the defaults; tell the user what you chose. From a trough or "
    "a container with an unknown level use cLLD with submerge depth and liquid following; liquid "
    "following without LLD runs into the bottom (insufficient liquid level).\n\n"
    "Script-run error prompts are for a person (the operator page), never for you."
)

# CO-RE grips are easy to misread from the configuration: say so where it is read.
CORE_GRIP_CONFIG_NOTE = (
    "This configuration lists arm devices only. CO-RE grips are a separate tool and never appear "
    "here (gripper is the iSWAP / IPG), so it says nothing about whether the system has them: "
    "get_transport_tool_ids shows whether the layout has them, and the user knows whether the "
    "system does."
)


mcp = FastMCP("hamilton-venus", instructions=_INSTRUCTIONS)


@mcp.tool()
def get_usage_guide(search: str | None = None) -> dict[str, Any]:
    """This server's full usage guide; the instructions you were given only summarise it.

    With search: every section that mentions all of its words (case-insensitive), e.g.
    "tube carriers", "reservoir", "split_wells", "liquid class", "tip counter", "run_script",
    "stop_commands", "transport", "tilt". search="all" returns the whole guide. Without
    search: a one-line summary of each section, to choose from.
    """
    sections = [part.strip() for part in _GUIDE.split("\n\n") if part.strip()]
    if not search:
        return {"sections": [section.split(". ")[0][:160] for section in sections],
                "hint": "Call again with search=<words> for the full text of the sections you need."}
    if search.strip().lower() == "all":
        return {"guide": _GUIDE}
    words = search.lower().split()
    hits = [section for section in sections if all(word in section.lower() for word in words)]
    if not hits:
        return {"search": search, "sections": [], "note": "No section mentions all of those words; try fewer."}
    return {"search": search, "sections": hits}

SPOKE_NAME_ENV = "HAMILTON_MCP_SPOKE_NAME"


def _spoke_name() -> str:
    """This spoke's human-facing display name -- for hub discovery/get_spoke_state only,
    distinct from the fixed "hamilton-venus" MCP protocol server name above (that one is
    surfaced in every client's initialize handshake, e.g. Claude Code/Desktop; changing it
    per-install would be a visible behavior change for direct/stdio users for a benefit
    only the hub's network discovery needs). Read fresh, not cached, so a changed env var
    takes effect on the next /ping or get_spoke_state call without a restart."""
    return os.environ.get(SPOKE_NAME_ENV, "").strip() or socket.gethostname()


@mcp.custom_route("/ping", methods=["GET"])
async def ping(_request: Request) -> JSONResponse:
    """Cheap, unauthenticated, no-MCP-handshake identity probe for hub-side network
    discovery (see hamilton_venus_mcp_hub.discovery) -- a real tool call needs a full
    initialize+call round trip per target, too slow to fire speculatively at hundreds of
    candidate host:port pairs during a scan. Only reachable when this spoke runs over
    streamable-http/sse, same as every other custom_route in this codebase."""
    return JSONResponse(
        {"service": "hamilton-venus-mcp", "name": _spoke_name(), "auth_required": configured_token() is not None}
    )


@mcp.resource(
    "docs://hamilton-venus/getting-started",
    name="hamilton-venus-mcp getting started guide",
    description=(
        "Full reference for this server's session lifecycle, deck layout options, command/"
        "labware discovery, and the positions selector DSL. The full guide that this server's "
        "MCP `instructions` summarise (also the get_usage_guide tool), as a pull-able resource."
    ),
    mime_type="text/plain",
)
def getting_started_doc() -> str:
    return _GUIDE


def _register_doc_resource(entry: Any) -> None:
    """One @mcp.resource per docs/*.md file, registered in a loop off DOCS_CATALOG rather
    than hand-written one at a time -- same reflection-over-a-generated-list philosophy as
    list_sdk_commands/search_labware, so a new file under docs/ is picked up automatically
    on the next server start with no code change here. A def inside a loop would close over
    the loop variable by reference, not value, silently making every resource return the
    *last* file's content -- routed through this function's own parameter instead.
    """

    def _read() -> str:
        return read_doc_text(entry.path)

    _read.__name__ = "doc_" + entry.relative_path.replace("/", "_").replace(".", "_").replace("-", "_").replace(
        " ", "_"
    )
    mcp.resource(entry.uri, name=entry.relative_path, description=entry.title, mime_type="text/markdown")(_read)


for _entry in DOCS_CATALOG:
    _register_doc_resource(_entry)
del _entry


@mcp.tool()
def list_sdk_docs(search: str | None = None) -> list[dict[str, str]]:
    """List this SDK's own docs/*.md files (authentication, configuration, error handling,
    JSON schemas, worked examples for autoload/deck-and-layout/liquid-handling/position-and-
    well-selection/etc., labware schema conventions) -- so an agent can pull the SDK's own
    reference documentation through MCP instead of needing local filesystem access. Call
    read_sdk_doc(relative_path) with a result's relative_path to get the full text.

    Args:
        search: Case-insensitive substring match over each doc's relative_path and title.
    """
    results = []
    for entry in DOCS_CATALOG:
        if search is not None and search.lower() not in f"{entry.relative_path} {entry.title}".lower():
            continue
        results.append({"relative_path": entry.relative_path, "title": entry.title})
    return results


@mcp.tool()
def read_sdk_doc(relative_path: str) -> str:
    """Return the full markdown text of one docs/*.md file, by the relative_path from
    list_sdk_docs (e.g. "examples/position_and_well_selection.md")."""
    entry = DOCS_BY_PATH.get(relative_path)
    if entry is None:
        raise ValueError(f"Unknown doc {relative_path!r}. Use list_sdk_docs to discover valid paths.")
    return read_doc_text(entry.path)


# HAMILTON_MCP_COM_TRACE=1 embeds VENUS's firmware COM trace (.trc) into each
# session's *_SdkRunLog.json. Off by default -- see WorkflowBackendConfig.
_com_trace_enabled = os.getenv("HAMILTON_MCP_COM_TRACE", "").strip().lower() in ("1", "true", "yes", "on")
_backend_config = WorkflowBackendConfig(
    com_trace_enabled=_com_trace_enabled,
    # Before any session, list_sdk_commands and friends describe the installed family.
    default_instrument_type=_installed_instrument() or InstrumentType.STAR,
)
_session = WorkflowSession(_backend_config)
_lock = asyncio.Lock()


# -- hold notifications -------------------------------------------------------------------
#
# Everyone who needs to know a step is held, without polling for it: webhook subscribers get
# a POST per event, wait_for_command_event long-polls the same events for an agent, the
# front status light shows the state (see _StatusLight), and get_spoke_state carries the hold
# for the hub.

COMMAND_EVENT_WEBHOOKS_ENV = "HAMILTON_MCP_HOLD_WEBHOOKS"  # comma-separated URLs, all events
STATUS_LIGHT_ENV = "HAMILTON_MCP_STATUS_LIGHT"  # "0" leaves the front status light alone
IDLE_LIGHT_ENV = "HAMILTON_MCP_IDLE_LIGHT_S"  # seconds without a command before "idle" (white)

# url -> the event kinds it wants (None = every kind). Lives as long as the spoke process.
_command_event_webhooks: dict[str, frozenset[str] | None] = {
    url.strip(): None for url in os.environ.get(COMMAND_EVENT_WEBHOOKS_ENV, "").split(",") if url.strip()
}
_background_tasks: set[asyncio.Task[Any]] = set()

COMMAND_EVENT_KINDS = (
    "held",
    "stop_requested",
    "resuming",
    "resumed",
    "released",
    "replay_failed",
    "status",
    "error",
    "operator_prompt",
    "operator_prompt_resolved",
)
# Event "type" -> published kind, for the types that aren't run-control "event" names.
_EVENT_TYPE_KINDS = {
    "run_hold": "held",
    "status": "status",
    "command_error": "error",
    "operator_prompt": "operator_prompt",
    "operator_prompt_resolved": "operator_prompt_resolved",
}
SPOKE_STATUSES = ("idle", "running", "error", "hold", "paused", "terminated")


def _event_kind(event: dict[str, Any]) -> str:
    kind = _EVENT_TYPE_KINDS.get(str(event.get("type")))
    return kind if kind is not None else str(event.get("event"))


def _spawn(coro: Any) -> None:
    """Fire and forget on the running loop -- notifications must never slow the command path."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return
    task = loop.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _post_webhook(url: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, default=str).encode()

    def _send() -> None:
        request = urllib.request.Request(url, body, {"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()

    try:
        await asyncio.to_thread(_send)
    except Exception as exc:
        _logger.warning("Command-event webhook %s failed: %s", url, exc)


# The front light's progress range is 0-5: 5 lights it fully, 0 turns it off.
FULL_PROGRESS = 5


class _StatusLight:
    """The instrument's front status light, in VENUS's own colors: white idle, green running,
    red held on an error, blue stopped for a person -- always solid at full progress (5, the
    light's top level; its range is 0-5) -- and off (progress 0) once the session closes.

    A burst of commands keeps it green; it only drops back to white after idle_after_s with no
    normal command, so a card workflow's short gaps between commands don't flicker it. Every
    change is one instrument command, sent only when the color actually changes.
    """

    def __init__(self) -> None:
        self.enabled = os.environ.get(STATUS_LIGHT_ENV, "1").strip().lower() not in ("0", "false", "no", "off")
        try:
            self.idle_after_s = max(0.0, float(os.environ.get(IDLE_LIGHT_ENV, "5")))
        except ValueError:
            self.idle_after_s = 5.0
        self._current: tuple[LightColor, int] | None = None
        self._idle_generation = 0
        self._request_seq = 0
        # What the interactive session is doing (see _overall_status): idle | running | error |
        # hold | terminated. Moves with the light, but also when the light is turned off.
        self.session_status = "terminated"

    def status(self, status: str) -> None:
        self.session_status = status
        _publish_status()

    def reset(self) -> None:
        self._current = None
        self._idle_generation += 1

    @property
    def current(self) -> str | None:
        if self._current is None:
            return None
        color, progress = self._current
        return "off" if progress == 0 else color.name.lower()

    async def set(self, color: LightColor, progress: int = FULL_PROGRESS) -> None:
        await self.request(color, progress)

    def request(self, color: LightColor, progress: int = FULL_PROGRESS) -> Any:
        """Claim the light now (synchronously) and return the coroutine that sets it. Latest
        claim wins: one still waiting for _lock when a newer claim is made (e.g. a hold's color
        spawned just before a resume turned it green) is dropped. Claiming here, not when the
        coroutine first runs, is what makes a spawned request lose to a later inline one."""
        self._request_seq += 1
        return self._apply(color, progress, self._request_seq)

    async def _apply(self, color: LightColor, progress: int, request: int) -> None:
        if not self.enabled:
            return
        # The light is the instrument's: VENUS refuses it ("Instrument must be connected") while
        # a session runs without one -- before connect_instrument, or when a session that never
        # connected is closed. Nothing is remembered, so the first change once connected is sent.
        if not _session.is_connected():
            return
        try:
            star = _active_star()
            async with _lock:
                if request != self._request_seq or self._current == (color, progress):
                    return
                # Remembered before sending, so a light command that fails is not re-sent before
                # every following command -- each attempt is a full instrument round trip.
                self._current = (color, progress)
                await asyncio.to_thread(star.status_light_set_front_light, color=color, blink=False, progress=progress)
        except Exception as exc:
            _logger.warning("Could not set the front status light: %s", exc)

    async def running(self) -> None:
        """A normal command or a resume is about to run: green, and no idle timer."""
        self._idle_generation += 1
        self.status("running")
        await self.set(LightColor.GREEN)

    def interrupted(self) -> None:
        """A hold or stop owns the light now: cancel any pending switch back to idle."""
        self._idle_generation += 1

    def schedule_idle(self) -> None:
        """White once nothing else runs for idle_after_s (a later command or hold cancels it)."""
        self._idle_generation += 1
        generation = self._idle_generation

        async def _idle_later() -> None:
            await asyncio.sleep(self.idle_after_s)
            if generation == self._idle_generation and _run_control.state == "running":
                self.status("idle")
                await self.request(LightColor.WHITE)

        _spawn(_idle_later())

    async def off(self) -> None:
        await self.set(LightColor.WHITE, progress=0)
        self.reset()
        self.status("terminated")


_status_light = _StatusLight()


def _on_run_control_event(event: dict[str, Any]) -> None:
    # The session already queued the operator_prompt itself (get_recent_events); a second copy
    # would show an agent the same prompt twice.
    if event.get("type") != "operator_prompt":
        _session.log_queue.put_nowait(event)
    kind = _event_kind(event)
    payload = {"spoke": _spoke_name(), "connection_id": _session.connection_id, "kind": kind, **event}
    for url, kinds in list(_command_event_webhooks.items()):
        if kinds is None or kind in kinds:
            _spawn(_post_webhook(url, payload))
    if kind == "held":
        _status_light.interrupted()
        on_error = event.get("reason") == "error"
        _status_light.status("error" if on_error else "hold")
        _spawn(_status_light.request(LightColor.RED if on_error else LightColor.BLUE))
    elif kind == "stop_requested":
        _status_light.interrupted()
        _status_light.status("hold")
        _spawn(_status_light.request(LightColor.BLUE))
    elif kind in ("released", "replay_failed") and event.get("state") == "running":
        _status_light.status("running")
        _status_light.schedule_idle()


# -- spoke status --------------------------------------------------------------------------
#
# One word for what this spoke is doing, whoever drives it: a whole-script run (run_script) or
# an interactive session driven one command at a time. Every change is a "status" event --
# webhooks, wait_for_command_event and get_spoke_state all carry it -- so a hub dashboard or
# orchestrator sees it the moment it happens. Script-run changes happen in the run manager's
# own threads, so a short watcher loop notices those; session changes publish immediately.

_venus_paused = False
_status_lock = threading.Lock()
_status_watcher: asyncio.Task[Any] | None = None
_STATUS_WATCH_INTERVAL_S = 0.5
_last_status: dict[str, Any] = {"status": "terminated", "detail": None, "source": "session", "since": time.time()}


def _overall_status() -> tuple[str, str | None, str]:
    """(status, detail, source). A script run wins (it owns the instrument), then a VENUS-level
    pause, then the interactive session, then an unacknowledged failed run."""
    run_state = _run_manager.state(session_active=_session_active())
    if run_state.get("run") is not None:
        if run_state.get("pending_prompts"):
            return "error", run_state.get("detail"), "script"
        if run_state.get("paused"):
            return "paused", run_state.get("detail"), "script"
        return "running", run_state.get("detail"), "script"
    if _venus_paused:
        return "paused", "The VENUS method is paused (venus_pause).", "venus"
    if _session_active():
        status = _status_light.session_status
        if status == "terminated":
            status = "idle"
        hold = _run_control.hold_brief
        detail = None
        prompts = _session.pending_operator_prompts
        if prompts:
            # The command is blocked until resolve_operator_prompt answers it.
            first = prompts[0]
            more = f" (+{len(prompts) - 1} more)" if len(prompts) > 1 else ""
            return "error", f"Operator prompt waiting ({first.get('code')}): {first.get('title')}{more}", "session"
        if hold and status in ("error", "hold"):
            detail = f"Step {hold['step']} ({hold['command']}) held" + (f": {hold['message']}" if hold.get("message") else "")
        return status, detail, "session"
    if run_state.get("state") == "error":
        return "error", run_state.get("detail"), "script"
    return "terminated", None, "session"


def _publish_status() -> None:
    """Emit a "status" event if the overall status changed. Safe to call from anywhere on the
    event loop; cheap enough to call on every transition."""
    try:
        status, detail, source = _overall_status()
    except Exception:  # noqa: BLE001 - status reporting must never break a command
        _logger.exception("Could not work out the spoke status")
        return
    with _status_lock:
        previous = _last_status["status"]
        if status == previous and detail == _last_status["detail"]:
            return
        since = time.time() if status != previous else _last_status["since"]
        _last_status.update(status=status, detail=detail, source=source, since=since)
    if status != previous:
        _run_control.emit(
            {"type": "status", "status": status, "previous": previous, "detail": detail, "source": source}
        )


def _ensure_status_watcher() -> None:
    """Start (once per event loop) the loop that notices script-run and pause changes."""
    global _status_watcher
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _status_watcher is not None and not _status_watcher.done() and _status_watcher.get_loop() is loop:
        return

    async def _watch() -> None:
        while True:
            _publish_status()
            await asyncio.sleep(_STATUS_WATCH_INTERVAL_S)

    _status_watcher = loop.create_task(_watch(), name="spoke-status-watcher")


def _status_view() -> dict[str, Any]:
    with _status_lock:
        return dict(_last_status)


# Step journal and hold for call_sdk_command (see run_control.py). Reset on every
# start_session / close_session.
_run_control = RunControl(on_event=_on_run_control_event)


def _on_operator_prompt(message: dict[str, Any]) -> None:
    """Publish a session operator prompt (or its answer) like any other command event."""
    event = {k: v for k, v in message.items() if k != "channel_errors"}
    if message.get("type") == "operator_prompt":
        event["channel_error_count"] = len(message.get("channel_errors") or [])
    _run_control.emit(event)
    _publish_status()


_session.add_operator_prompt_listener(_on_operator_prompt)

# Every error ends in Cancel straight away: no retries, no operator prompt. The VENUS method
# stays alive, so with hold_on_error the failed step is held for recovery and resume.
CANCEL_ALL_PROFILE = ErrorProfile(
    name="cancel_all",
    default=ErrorEntry(actions=(RecoveryAction.CANCEL,), max_retries=0, allow_operator=False),
)
_NAMED_ERROR_PROFILES: dict[str, ErrorProfile] = {**BUILTIN_ERROR_PROFILES, "cancel_all": CANCEL_ALL_PROFILE}


def _apply_error_profile(profile: str) -> str:
    """Make *profile* (a name from _NAMED_ERROR_PROFILES, or an ErrorProfile as JSON) the
    active session's error profile until the session ends or this is called again."""
    text = profile.strip()
    if text.startswith("{"):
        resolved = profile_from_json(text)
    else:
        resolved = _NAMED_ERROR_PROFILES.get(text.lower())
        if resolved is None:
            names = ", ".join(sorted(_NAMED_ERROR_PROFILES))
            raise ValueError(f"Unknown error profile {profile!r}. Use one of: {names}, or a profile as JSON.")
    _active_star()._connected_instrument.error_resolver.set_active_profile(resolved)
    return resolved.name

# Whole-script runs (see the "script runs" section at the end of this module). The store is the
# only place a script can run from; the manager owns the one active run; the gate is the
# token-protected, human-only path for answering a run's prompts.
_store = ScriptStore()
_run_manager = RunManager(_store)
_operator_gate = OperatorGate(_run_manager)
_operator_server: OperatorServer | None = None


def _active_star():
    try:
        return _session.star
    except RuntimeError as exc:
        raise RuntimeError("No active session. Call start_session first.") from exc


def _resolve_target(name: str):
    """The object *name* should be called on: a standalone device client (e.g.
    hhc_*/odtc_*, no session required) or the active StarClient/VantageClient.
    Same "no active session" wrapping as _active_star() -- only actually
    triggered when *name* isn't a standalone-device command and no session has
    been started.
    """
    try:
        return _session.resolve_command_target(name)
    except RuntimeError as exc:
        raise RuntimeError("No active session. Call start_session first.") from exc


def _active_catalog() -> dict[str, CommandSpec]:
    """The command catalog matching whichever instrument type the session is (or will
    be) using -- readable even before a session is started, since instrument_type
    reflects the pending/last-used selection, not connection state.
    """
    return CATALOG_BY_INSTRUMENT[_session.instrument_type]


def _parse_instrument_type(value: str) -> InstrumentType:
    try:
        return InstrumentType(value)
    except ValueError:
        for member in InstrumentType:
            if member.value.lower() == value.lower():
                return member
        supported = ", ".join(m.value for m in (InstrumentType.STAR, InstrumentType.Vantage))
        raise ValueError(f"Unsupported instrument_type {value!r}. Supported values: {supported}.") from None


def _resolve_instrument_type(requested: str | None) -> InstrumentType:
    """The client family start_session should build: the installed one when none is asked for,
    and a refusal (with the exact fix) when the other family is asked for -- by anyone calling
    over the network. Only the spoke's owner can allow it (HAMILTON_MCP_ALLOW_INSTRUMENT_MISMATCH)."""
    installed = _installed_instrument()
    if requested is None:
        return installed or InstrumentType.STAR
    parsed = _parse_instrument_type(requested)
    if installed is not None and parsed != installed and not instrument_guard.mismatch_allowed():
        raise ValueError(instrument_guard.refusal_for_type(installed, parsed))
    return parsed


def _describe_venus_error(exc: VenusError) -> dict[str, Any]:
    payload: dict[str, Any] = {"error_type": type(exc).__name__, "message": str(exc)}
    if isinstance(exc, VenusCommandFailedError):
        payload["response"] = serialize_result(exc.response)
    if "must be connected" in str(exc):
        payload["hint"] = (
            "Call connect_instrument first (after start_session and the deck choice); instrument_get_configuration "
            "and the pipetting and deck commands need the connected instrument. Commands that need no connection: "
            "get_registered_tip_types, find_liquid_classes, search_labware, list_sdk_commands."
        )
    return payload


# -- session lifecycle --------------------------------------------------------------


# Set while a session is open with no deck layout chosen yet (start_session got no deck
# choice and the client couldn't show the prompt, or the user dismissed it).
# connect_instrument refuses until select_deck_layout settles it.
_deck_choice_pending = False
# Whether this session has loaded a layout; a session starts blank, but there's no way to
# go back to blank after a load other than a new session.
_deck_loaded = False

_BLANK_DECK = "blank"
_PREVIOUS_DECK = "previous"
_SAVED_DECK_PREFIX = "saved:"


def _can_elicit(ctx: Context | None) -> bool:
    """True when the MCP client can show the user a form (elicitation): Claude Code / Desktop
    can; the hub relaying for an AI, and orchestrator scripts, cannot."""
    if ctx is None:
        return False
    try:
        return ctx.session.check_client_capability(
            mcp_types.ClientCapabilities(elicitation=mcp_types.ElicitationCapability())
        )
    except Exception:  # no request context (called directly) or an old client
        return False


def _deck_choice_count(deck_name: str | None, load_previous_deck: bool, blank_deck: bool) -> int:
    count = sum([deck_name is not None, load_previous_deck, blank_deck])
    if count > 1:
        raise ValueError("Pass only one of deck_name, load_previous_deck and blank_deck.")
    return count


async def _deck_options() -> dict[str, Any]:
    """The deck layouts the user can choose from: the last layout used (with whatever details
    VENUS's deck.getPreviousDeck reports) and the saved layouts. Needs a started session, not
    a connected instrument."""
    options: dict[str, Any] = {"blank": "An empty deck with no labware."}
    try:
        previous = await asyncio.to_thread(_session.star.deck_get_previous)
        options["last_layout"] = previous.return_parameters.model_dump(by_alias=True)
        options["last_layout_summary"] = (
            _describe_last_layout(options["last_layout"])
            if options["last_layout"].get("deckAvailable")
            else "No last layout is available."
        )
    except Exception as exc:
        options["last_layout"] = {"deckAvailable": None, "error": f"Could not check the last layout: {exc}"}
    try:
        saved = await asyncio.to_thread(_session.star.deck_get_saved)
        options["saved_layouts"] = list(saved.return_parameters.saved_decks)
    except Exception as exc:
        options["saved_layouts"] = []
        options["saved_layouts_error"] = f"Could not list saved layouts: {exc}"
    return options


def _describe_last_layout(last: dict[str, Any], max_labware: int = 6) -> str:
    """A short summary of the last layout for the prompt, from deck.getPreviousDeck's
    carrierTracking (carrier id -> track and per-site labware) and tipCountingTracking
    (tip pool -> its racks). layoutTracking (every track) is too long to show."""
    carriers = last.get("carrierTracking") if isinstance(last.get("carrierTracking"), dict) else {}
    pools = last.get("tipCountingTracking") if isinstance(last.get("tipCountingTracking"), dict) else {}
    carrier_parts = []
    for carrier_id, info in sorted(
        ((k, v) for k, v in carriers.items() if isinstance(v, dict)), key=lambda kv: kv[1].get("track", 0)
    ):
        labware = [
            str(item["ID"])
            for site in info.values()
            if isinstance(site, dict)
            for item in site.get("labware", [])
            if isinstance(item, dict) and item.get("ID")
        ]
        text = f"{carrier_id} on track {info.get('track', '?')}"
        if labware:
            shown = ", ".join(labware[:max_labware])
            more = f", +{len(labware) - max_labware} more" if len(labware) > max_labware else ""
            text += f" ({shown}{more})"
        carrier_parts.append(text)
    pool_parts = [
        f"{name} ({len(pool.get('tipRacks') or [])} rack(s), {pool.get('totalTips', '?')} tips)"
        for name, pool in pools.items()
        if isinstance(pool, dict)
    ]
    if not carrier_parts and not pool_parts:
        return "It has no carriers on it." if "carrierTracking" in last else "No further details are available for it."
    summary = "Carriers: " + ("; ".join(carrier_parts) if carrier_parts else "none") + "."
    if pool_parts:
        summary += " Tip pools: " + "; ".join(pool_parts) + "."
    return summary


async def _elicit_simulate(
    ctx: Context, suggested: bool | None = None, suggested_name: str | None = None
) -> tuple[bool, str | None] | None:
    """Ask simulation or live, and the session's name in VENUS. *suggested* / *suggested_name*
    (what the AI or app passed, if anything) are only pre-filled -- the user still decides.
    Returns (simulate, session name or None for the default). None when the form wasn't answered: the
    user dismissed it, or the app cancelled it without showing it (Claude Desktop's Code tab
    does this for every form), so the caller falls back to the AI asking in the chat."""
    default = {True: "simulation", False: "live"}.get(suggested) if suggested is not None else None

    class _ModeChoice(BaseModel):
        mode: str = Field(
            default if default is not None else ...,
            title="Run mode",
            description="Simulation never moves hardware. Live gives the assistant control of the real "
            "instrument until the session is closed.",
            json_schema_extra={"enum": ["simulation", "live"], "enumNames": ["Simulation", "Live instrument"]},
        )
        session_name: str = Field(
            suggested_name or "",
            title="Session name",
            description=f"How this session appears in VENUS run control and run history. Leave empty for "
            f"\"{DEFAULT_SESSION_NAME}\".",
            max_length=SESSION_NAME_MAX,
        )

    result = await ctx.elicit("Start the Hamilton session in simulation or on the live instrument?", schema=_ModeChoice)
    if result.action != "accept" or result.data.mode not in ("simulation", "live"):
        return None
    return result.data.mode != "live", _clean_session_name(result.data.session_name)


async def _elicit_deck(
    ctx: Context, options: dict[str, Any], suggested: str | None = None
) -> tuple[str | None, bool] | None:
    """Ask which deck layout to load. *suggested* (blank / previous / saved:<name>, from what
    the AI passed) is only pre-selected. Returns (deck_name, previous) for deck_load, with
    (None, False) meaning blank; None when the user dismissed the prompt."""
    last = options["last_layout"]
    values = [_BLANK_DECK]
    labels = ["Blank layout (empty deck)"]
    lines = ["Which deck layout should this session use?", "", "- Blank layout: an empty deck with no labware."]
    if last.get("deckAvailable"):
        values.append(_PREVIOUS_DECK)
        labels.append("Last layout used")
        lines.append(f"- Last layout used. {_describe_last_layout(last)}")
    else:
        lines.append("- Last layout used: none is available." + (f" ({last['error']})" if last.get("error") else ""))
    for name in options["saved_layouts"]:
        values.append(_SAVED_DECK_PREFIX + name)
        labels.append(f"Saved layout: {name}")
    if options["saved_layouts"]:
        lines.append(f"- Saved layouts: {', '.join(options['saved_layouts'])}.")
    else:
        lines.append("- Saved layouts: none.")

    default = suggested if suggested in values else None

    class _DeckChoice(BaseModel):
        layout: str = Field(
            default if default is not None else ...,
            title="Deck layout",
            json_schema_extra={"enum": values, "enumNames": labels},
        )

    result = await ctx.elicit("\n".join(lines), schema=_DeckChoice)
    if result.action != "accept" or result.data.layout not in values:
        return None
    choice = result.data.layout
    if choice == _PREVIOUS_DECK:
        return None, True
    if choice.startswith(_SAVED_DECK_PREFIX):
        return choice[len(_SAVED_DECK_PREFIX) :], False
    return None, False


def _deck_label(deck_name: str | None, previous: bool) -> str:
    return "last layout used" if previous else (f"saved layout {deck_name!r}" if deck_name else "blank")


# What a session runs under in VENUS when start_session gets no session_name: the SDK names a
# run after the running program, and this server runs as hamilton-venus-mcp.
DEFAULT_SESSION_NAME = "hamilton-venus-mcp"
SESSION_NAME_MAX = 64
_SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9_\- ]+$")
# The SDK's own method files; a session named like one would collide with it.
_RESERVED_SESSION_NAMES = {"venus_sdk_executor"}


def _check_session_name(name: str | None) -> str | None:
    """None/blank for the default, else the name -- refused (rather than silently changed)
    when VENUS couldn't use it as a method file name."""
    if name is None or not name.strip():
        return None
    name = name.strip()
    if len(name) > SESSION_NAME_MAX or not _SESSION_NAME_RE.match(name):
        raise ValueError(
            f"session_name {name!r} can't be used: use letters, digits, spaces, '-' and '_' only, "
            f"up to {SESSION_NAME_MAX} characters. start_session was not called."
        )
    if name.lower() in _RESERVED_SESSION_NAMES:
        raise ValueError(f"session_name {name!r} is reserved for the SDK's own method. start_session was not called.")
    return name


def _clean_session_name(text: str | None) -> str | None:
    """A name typed in the form, made usable rather than refused: characters VENUS can't take
    become spaces; None for empty (the default name) or the SDK's reserved name."""
    name = " ".join(re.sub(r"[^A-Za-z0-9_\- ]+", " ", text or "").split())[:SESSION_NAME_MAX].strip()
    return name if name and name.lower() not in _RESERVED_SESSION_NAMES else None


def _session_run_name() -> str:
    return _session.session_name or DEFAULT_SESSION_NAME


@mcp.tool()
async def start_session(
    simulate: bool | None = None,
    deck_name: str | None = None,
    load_previous_deck: bool = False,
    blank_deck: bool = False,
    instrument_type: str | None = None,
    hold_on_error: bool = False,
    error_profile: str | None = None,
    session_name: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Start (or restart) a session against a StarClient or VantageClient. Tears down
    any existing session first. Does not connect to the instrument yet -- call
    connect_instrument afterwards.

    The user always chooses simulation vs live and the deck layout. When the app can show
    forms (Claude Code, Claude Desktop), this tool ALWAYS asks them itself: simulation or
    live first, then (once the client is up, without connecting the instrument) a blank
    layout, the last layout used (with a summary) or one of the saved layouts. Anything you
    pass for simulate or the deck is only pre-selected in those forms, so pass what the
    user said and nothing more. If the app can't show forms, or a form comes back
    unanswered (Claude Desktop's Code tab cancels them without showing them), it falls back
    to the chat: simulate is then required (ask the user first), and with no deck choice
    the result has deck_choice_required=True with the options (blank, last_layout_summary,
    saved_layouts): show them to the user, ask, and call select_deck_layout with their
    answer before connect_instrument. The same happens if the user dismisses the layout
    form.

    Raises if VENUS Run Control is currently executing a method that wasn't started
    from this session -- entering a fresh StarClient/VantageClient silently aborts
    whatever is running otherwise (see hamilton_venus's stale-method cleanup), and
    there's no UI here to warn a human first the way the web apps do, so this refuses
    instead. If that happens, tell the user VENUS is busy (and with what run-state)
    and let them decide -- don't just retry.

    Args:
        simulate: True for the VENUS simulator, False for the real instrument. Leave unset
            to have the user asked; never pass False unless the user chose live.
        deck_name: Load this saved deck layout by name. One deck choice at most.
        load_previous_deck: Load the last layout used.
        blank_deck: Start with an empty deck. Scripts and orchestrators with no person to
            ask pass one of deck_name / load_previous_deck / blank_deck.
        instrument_type: "STAR" or "Vantage" (case-insensitive). Leave it out: the spoke uses
            the instrument this PC's VENUS is installed for (see installed_instrument_type in
            get_session_status). It determines which client class is used and which commands
            list_sdk_commands/call_sdk_command expose for the rest of this session. Asking for
            the other family is refused, whatever the calling computer has installed.
        hold_on_error: Hold a call_sdk_command step that fails with a Cancel-answered error
            instead of reporting the error, so it can be resumed after recovery (see
            stop_commands / resume_commands). Off by default; set_hold_on_error changes it
            later.
        error_profile: Error recovery for this session -- see set_error_profile. None keeps
            the spoke's configured profile ("standard" unless configured otherwise).
        session_name: The name this session runs under in VENUS (run control, run history and
            the run log's file name), so sessions can be told apart -- e.g. "PCR setup plate 3".
            Letters, digits, spaces, "-" and "_", up to 64 characters. Only pass one the user
            (or the calling workflow) asked for; omitted, the run is "hamilton-venus-mcp".
    """
    global _deck_choice_pending, _deck_loaded
    parsed_instrument_type = _resolve_instrument_type(instrument_type)
    session_name = _check_session_name(session_name)
    explicit_deck = _deck_choice_count(deck_name, load_previous_deck, blank_deck) == 1
    if _run_manager.has_active_run():
        raise RuntimeError(
            "A script run is active on this spoke. Wait for it to finish, or abort_run it, before "
            "starting an interactive session. start_session was not called."
        )
    # A person is at the app whenever it can show forms: they answer both questions, whatever
    # the AI passed. Without forms (hub, scripts, orchestrators) the explicit arguments rule.
    interactive = _can_elicit(ctx)
    if interactive:
        answered = await _elicit_simulate(ctx, suggested=simulate, suggested_name=session_name)
        if answered is None:
            interactive = False  # no form answer: the chat path below, as for an app without forms
        else:
            simulate, session_name = answered
    if simulate is None:
        raise RuntimeError(
            "Ask the user whether to run in simulation or on the live instrument, then call "
            "start_session(simulate=True) or start_session(simulate=False). start_session was not called."
        )
    deck_chosen = explicit_deck and not interactive
    if (
        explicit_deck
        and _deck_choice_pending
        and _session_active()
        and not _session.is_connected()
        and _session.simulate == simulate
        and _session.instrument_type == parsed_instrument_type
        and (session_name is None or session_name == _session.session_name)
    ):
        # The AI called start_session again with the user's layout instead of
        # select_deck_layout: the open session is the one wanted, so just load it and connect.
        selected = await select_deck_layout(
            deck_name=deck_name, load_previous_deck=load_previous_deck, blank_deck=blank_deck
        )
        return {
            "session_id": _session.session_id,
            "simulate": _session.simulate,
            "instrument_type": _session.instrument_type.value,
            "session_name": _session_run_name(),
            "reused_open_session": True,
            **selected,
        }
    async with _lock:
        run_state = await _session.check_run_state()
        own_run = _session_active() and await _session.owns_current_run()
        if run_state is not None and run_state in BUSY_RUN_STATES and not own_run:
            raise RuntimeError(
                f"VENUS Run Control is currently {run_state.name} -- a method is running that "
                "wasn't started from this session. Starting a new session here would silently "
                "abort it. Ask the user to confirm before proceeding (e.g. that they know it's a "
                "stale leftover run safe to clear), or check the instrument/Method Editor directly. "
                "start_session was not called."
            )
        _ensure_status_watcher()
        _run_control.reset(hold_on_error=hold_on_error)
        _status_light.reset()
        await _session.start_session(
            simulate=simulate, instrument_type=parsed_instrument_type, session_name=session_name
        )
        _run_control.session_id = _session.session_id
        _deck_choice_pending = not deck_chosen
        _deck_loaded = False
        if deck_chosen:
            await _session.load_deck(deck_name, previous=load_previous_deck)
            _deck_loaded = not blank_deck
        active_profile = _apply_error_profile(error_profile) if error_profile else None
    _status_light.status("idle")
    result: dict[str, Any] = {
        "session_id": _session.session_id,
        "connection_id": _session.connection_id,
        "simulate": _session.simulate,
        "instrument_type": _session.instrument_type.value,
        "session_name": _session_run_name(),
        "hold_on_error": _run_control.hold_on_error,
        "error_profile": active_profile,
        # Whether the user answered in the app's own forms (False: the app can't show them).
        "asked_in_app": interactive,
    }
    if deck_chosen:
        result["deck_layout"] = _deck_label(deck_name, load_previous_deck)
        return result

    # Ask now. The client is up, so VENUS can report the last and saved layouts; the
    # instrument stays unconnected until a layout is chosen.
    options = await _deck_options()
    suggested = (
        _PREVIOUS_DECK
        if load_previous_deck
        else _SAVED_DECK_PREFIX + deck_name
        if deck_name
        else _BLANK_DECK
        if blank_deck
        else None
    )
    choice = await _elicit_deck(ctx, options, suggested=suggested) if interactive else None
    if choice is not None:
        chosen_name, previous = choice
        async with _lock:
            await _session.load_deck(chosen_name, previous=previous)
        _deck_choice_pending = False
        _deck_loaded = chosen_name is not None or previous
        result["deck_layout"] = _deck_label(chosen_name, previous)
        return result
    result.update(
        deck_choice_required=True,
        deck_options=options,
        next_step=(
            "Ask the user which deck layout to use, always offering all three kinds even if the last "
            "layout is empty: a blank layout, the last layout used (describe it with "
            "deck_options.last_layout_summary) and each saved layout in deck_options.saved_layouts. Then "
            "call select_deck_layout with their answer -- it loads the layout and connects the "
            "instrument. Do not call start_session again."
        ),
    )
    return result


@mcp.tool()
async def select_deck_layout(
    deck_name: str | None = None,
    load_previous_deck: bool = False,
    blank_deck: bool = False,
    connect: bool = True,
    expected_connection_id: str | None = None,
) -> dict[str, Any]:
    """Load the deck layout the user chose for the open session -- a saved layout by name, the
    last layout used, or a blank deck (exactly one) -- and connect the instrument. This is the
    next call after start_session returned deck_choice_required=True: do NOT call
    start_session again (that restarts the session). Can also switch layouts later.

    Args:
        deck_name: A saved layout's exact name (from start_session's deck_options).
        load_previous_deck: The last layout used.
        blank_deck: An empty deck.
        connect: Connect the instrument right after loading (default). False only loads it;
            call connect_instrument yourself (e.g. with initialize=True).
        expected_connection_id: Optional safety check -- see connect_instrument.
    """
    global _deck_choice_pending, _deck_loaded
    if _deck_choice_count(deck_name, load_previous_deck, blank_deck) != 1:
        raise ValueError("Pass exactly one of deck_name, load_previous_deck and blank_deck.")
    _check_connection(expected_connection_id)
    async with _lock:
        if blank_deck:
            # A started session's deck is blank until something loads or adds labware.
            if _deck_loaded or _session.is_connected():
                raise RuntimeError(
                    "This session already has a layout loaded or is connected, so it can't go back to a "
                    "blank deck. Start a new session with blank_deck=True instead."
                )
        else:
            await _session.load_deck(deck_name, previous=load_previous_deck)
            _deck_loaded = True
    _deck_choice_pending = False
    result: dict[str, Any] = {
        "deck_layout": _deck_label(deck_name, load_previous_deck),
        "connection_id": _session.connection_id,
    }
    if connect and not _session.is_connected():
        result.update(await connect_instrument(expected_connection_id=expected_connection_id))
    else:
        result["connected"] = _session.is_connected()
    return result


def _check_connection(expected_connection_id: str | None) -> None:
    """Guard for connect_instrument/close_session/call_sdk_command: if the caller says
    which connection it expects (from start_session's own return value, or a fresh
    get_session_status call), refuse up front when a *different* connection is active
    now -- e.g. a later, unrelated start_session call silently replaced this one, which
    start_session itself never warns about. Every existing caller that doesn't pass
    expected_connection_id is unaffected (it's opt-in, default None)."""
    if expected_connection_id is None:
        return
    current = _session.connection_id
    if expected_connection_id != current:
        raise RuntimeError(
            f"Expected connection {expected_connection_id!r} but {current!r} is active now -- "
            "it was likely replaced by a later start_session call (possibly from a different "
            "workflow). Confirm the intended session before retrying."
        )


@mcp.tool()
async def connect_instrument(initialize: bool = False, expected_connection_id: str | None = None) -> dict[str, Any]:
    """Connect the instrument runtime for the active session (must run after start_session).

    Args:
        initialize: Also run instrument initialization as part of connecting.
        expected_connection_id: Optional safety check -- pass the connection_id
            start_session returned; refuses with a clear error if a different session is
            active now instead of silently connecting the wrong one. See
            get_session_status to look the current value up if it wasn't captured
            earlier.
    """
    _check_connection(expected_connection_id)
    if _deck_choice_pending:
        raise RuntimeError(
            "No deck layout has been chosen for this session yet. Ask the user whether they want a blank "
            "layout, the last layout used or a saved layout (start_session's deck_options lists them), "
            "then call select_deck_layout before connect_instrument."
        )
    async with _lock:
        await _session.connect_instrument(initialize=initialize)
    _status_light.reset()
    _status_light.status("idle")
    await _status_light.set(LightColor.WHITE)
    return {"connected": _session.is_connected(), "connection_id": _session.connection_id}


@mcp.tool()
async def close_session(expected_connection_id: str | None = None) -> dict[str, Any]:
    """Tear down the active StarClient session, disconnecting the instrument.

    Args:
        expected_connection_id: Optional safety check -- see connect_instrument. Refuses
            (without closing anything) if a different session is active now than the one
            being closed -- important here especially, since closing the wrong workflow's
            session mid-use would otherwise happen silently.
    """
    global _deck_choice_pending, _deck_loaded
    _check_connection(expected_connection_id)
    await _status_light.off()
    async with _lock:
        await _session.close()
    _deck_choice_pending = _deck_loaded = False
    _run_control.reset()
    return {"closed": True}



async def close_session_on_exit() -> None:
    """The stdio client closed its pipe (its conversation or app ended): close an open session,
    so VENUS's method doesn't keep running with nobody to drive or stop it."""
    global _deck_choice_pending, _deck_loaded
    if not _session_active():
        return
    _logger.info("Client disconnected with a session open: closing it")
    try:
        await _status_light.off()
        async with _lock:
            await _session.close()
    except Exception:  # noqa: BLE001 - best effort on the way out
        _logger.warning("Could not close the session on exit", exc_info=True)
    _deck_choice_pending = _deck_loaded = False
    _run_control.reset()

@mcp.tool()
def get_session_status() -> dict[str, Any]:
    """Report whether a session is active, whether the instrument is connected,
    whether it's running in simulate mode, and which instrument type it's using.

    connection_id (None when no session is active) identifies the specific currently-open
    connection -- pass it as expected_connection_id to connect_instrument/call_sdk_command/
    close_session to guard against those silently acting on a different, later session that
    replaced this one (see start_session)."""
    try:
        _session.star
        session_active = True
    except RuntimeError:
        session_active = False
    return {
        "session_active": session_active,
        "instrument_connected": _session.is_connected(),
        "simulate": _session.simulate,
        "session_id": _session.session_id,
        "connection_id": _session.connection_id,
        "instrument_type": _session.instrument_type.value,
        # What this PC's VENUS is installed for (None if unreadable); start_session refuses the other.
        "installed_instrument_type": _installed_value(),
        "session_name": _session_run_name() if session_active else None,
    }


# -- command discovery ---------------------------------------------------------------


@mcp.tool()
def list_sdk_categories() -> list[str]:
    """List the distinct command categories (SDK mixin groupings) available via
    list_sdk_commands for the active session's instrument type, e.g. "Channel",
    "Deck", "TipPool", "LiquidClass"."""
    return sorted({spec.category for spec in _active_catalog().values()})


@mcp.tool()
def list_sdk_commands(category: str | None = None, search: str | None = None) -> list[dict[str, str]]:
    """List SDK commands available for the active session's instrument type (STAR and
    Vantage share almost every command; STAR alone has CO-RE 5mL transport, Vantage
    alone has load tray and interior status light). Call describe_sdk_command(name)
    for full parameter details before calling call_sdk_command.

    Args:
        category: Restrict to one category from list_sdk_categories (case-insensitive).
        search: Case-insensitive substring match over each command's name and summary.
    """
    results = []
    for spec in _active_catalog().values():
        if category is not None and spec.category.lower() != category.lower():
            continue
        if search is not None and search.lower() not in f"{spec.name} {spec.summary}".lower():
            continue
        results.append({"name": spec.name, "category": spec.category, "summary": spec.summary})
    return sorted(results, key=lambda r: r["name"])


@mcp.tool()
def describe_sdk_command(name: str) -> dict[str, Any]:
    """Return the full docstring, parameter schema, and return type for one SDK command,
    scoped to the active session's instrument type."""
    spec = _active_catalog().get(name)
    if spec is None:
        raise ValueError(f"Unknown SDK command: {name!r}. Use list_sdk_commands to discover valid names.")
    return describe_command(spec)


@mcp.tool()
def list_labware_categories() -> list[str]:
    """List the labware catalog's categories (e.g. "CARRIER", "PLATE", "TIP_RACK") --
    pass one to search_labware's category filter."""
    return sorted({entry.category for entry in LABWARE_CATALOG})


@mcp.tool()
def search_labware(category: str | None = None, search: str | None = None) -> list[dict[str, Any]]:
    """Search the SDK's built-in static labware-type catalog (carriers, plates, tip
    racks, reservoirs, tubes, adapters, lids) for type names/ids to reference when
    authoring a deck layout or an SDK call that takes a labware type name -- instead of
    grepping hamilton_venus/catalog/labware.py by hand.

    This is the catalog of labware *types* the SDK ships definitions for, not what's on
    the active deck right now -- for the spec of a labware *instance* already placed on
    the connected deck, use call_sdk_command("get_labware_spec", {"labware_id": ...})
    instead. A type name found here is not guaranteed to resolve there, and vice versa.

    Args:
        category: Restrict to one category from list_labware_categories (case-insensitive).
        search: Case-insensitive substring match over each entry's name and labware id.

    Carriers (and sample/tube carriers) come with "width_tracks": how many deck tracks they
    take, from their definition. Plan left_track values from it -- never assume a width.
    """
    results = []
    for entry in LABWARE_CATALOG:
        if category is not None and entry.category.lower() != category.lower():
            continue
        if search is not None and search.lower() not in f"{entry.name} {entry.labware_id}".lower():
            continue
        result: dict[str, Any] = {
            "name": entry.name,
            "category": entry.category,
            "labware_id": entry.labware_id,
            "access_path": entry.access_path,
        }
        if entry.category in ("CARRIER", "TUBE_RACK"):
            width = deck_tracks.carrier_width(entry.labware_id)
            if width is not None:
                result["width_tracks"] = width
        results.append(result)
    return results


# -- command execution -----------------------------------------------------------------


def _prepare_sdk_command(name: str, kwargs: dict[str, Any] | None) -> tuple[Any, dict[str, Any]]:
    """Catalog lookup, target resolution and kwarg coercion -- everything that can reject a
    call before it reaches the instrument."""
    spec = _active_catalog().get(name)
    if spec is None:
        raise ValueError(f"Unknown SDK command: {name!r}. Use list_sdk_commands to discover valid names.")

    target = _resolve_target(name)
    call_kwargs = coerce_kwargs(spec, kwargs or {})
    return getattr(target, name), call_kwargs


async def _dispatch_sdk_command(name: str, kwargs: dict[str, Any] | None) -> dict[str, Any]:
    """Shared body of call_sdk_command and poll_sdk_command_until: catalog lookup, kwarg
    coercion, target resolution, and invocation.

    Only takes _lock for STAR/Vantage-mediated commands -- standalone devices (hhc_*/odtc_*,
    per find_standalone_device) already serialize per-device access via their own Manager's
    RLock (see ODTCManager/HeaterCoolerManager), so forcing them through the same lock as
    session lifecycle and VENUS-runtime commands would only add needless contention, e.g. a
    closed-loop poll of odtc_get_temperature blocking behind an unrelated in-flight
    call_sdk_command("aspirate", ...).
    """
    method, call_kwargs = _prepare_sdk_command(name, kwargs)

    async def _invoke() -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(lambda: method(**call_kwargs))
        except VenusError as exc:
            return _with_command_warnings(
                {"command": name, "status": "error", "timestamp": time.time(), **_describe_venus_error(exc)}
            )
        return _with_command_warnings({
            "command": name,
            "status": "success",
            "timestamp": time.time(),
            "result": serialize_result(result),
        })

    if find_standalone_device(name) is None:
        async with _lock:
            return await _invoke()
    return await _invoke()


def _with_command_warnings(outcome: dict[str, Any]) -> dict[str, Any]:
    """Add the SDK's warnings from the checks before this command (e.g. a tip too short for the
    labware, so the channel went inside the container) as "warnings", for the AI to tell the user."""
    try:
        warnings = _session.star.pop_command_warnings()
    except Exception:  # no session (standalone device), or an SDK without the checks
        warnings = []
    if warnings:
        outcome["warnings"] = warnings
    return outcome


@mcp.tool()
async def call_sdk_command(
    name: str,
    kwargs: dict[str, Any] | None = None,
    expected_connection_id: str | None = None,
    recovery: bool = False,
) -> dict[str, Any]:
    """Call an SDK command by name (as returned by list_sdk_commands for the active
    session's instrument type), with keyword arguments matching describe_sdk_command's
    parameter schema. Requires an active session (see start_session) for every command
    except hhc_*/odtc_*/tilt_module_*/media_fill_* (Hamilton Heater Cooler / Inheco ODTC /
    MFX Tilt Module / Media Fill Module) -- those are pure-Python, drive their device directly (vendor COM object or
    serial port), and work even with no session started.

    Args:
        name: The SDK command to call.
        kwargs: Its keyword arguments.
        expected_connection_id: Optional safety check -- see connect_instrument. Refuses
            before calling anything if a different session is active now than the one
            this call expected (e.g. a card/step running long after start_session,
            possibly after some other workflow's start_session replaced it).
        recovery: Run this as a recovery command: it runs even while a step is held (see
            stop_commands), is journaled without a step number, and is never replayed by
            resume_commands_from. Use for door unlock/lock, tip eject/pickup and the like
            while recovering from a hold.

    Every normal STAR/Vantage command is numbered: its result carries "step". With
    hold_on_error on (start_session / set_hold_on_error), a Cancel-answered instrument
    error returns status "held" instead of "error" -- wait for the final result with
    await_command_step(step). While a step is held, a normal (non-recovery) command is
    refused.
    """
    _check_connection(expected_connection_id)
    _ensure_status_watcher()
    if find_standalone_device(name) is not None:
        return await _dispatch_sdk_command(name, kwargs)
    _prepare_sdk_command(name, kwargs)  # reject a bad name/kwargs before it gets a step number
    kwargs = dict(kwargs or {})
    # Carriers by their real width: refuse one that would run off the deck or overlap another
    # (VENUS doesn't catch every overlap), and say which tracks a placed one took.
    placement_problem, placement = deck_tracks.check(name, kwargs)
    if placement_problem:
        raise ValueError(placement_problem)
    if recovery:
        return await _run_control.run_recovery(name, kwargs, _dispatch_sdk_command)
    # A read-only query (get_*, is_*, ...) leaves the light and the spoke status alone: polling
    # an idle instrument should neither turn it green nor pay a light change first.
    activity = not is_query_command(name)
    if activity and _run_control.state == "running":
        await _status_light.running()
    try:
        result = await _run_control.submit(name, kwargs, _dispatch_sdk_command)
        if activity and _run_control.state == "running":
            _status_light.schedule_idle()
        if placement and isinstance(result, dict) and result.get("status") == "success":
            result["deck_tracks"] = placement
        if name == "instrument_get_configuration" and isinstance(result, dict) and result.get("status") == "success":
            result["note"] = CORE_GRIP_CONFIG_NOTE
        return result
    except RunControlError as exc:
        return {
            "command": name,
            "status": "error",
            "error_type": "CommandHeld",
            "message": str(exc),
            "hold": _run_control.hold,
            "timestamp": time.time(),
        }


# -- stop / resume / resume from ----------------------------------------------------------


@mcp.tool()
async def await_command_step(step: int, wait_s: float = 20.0) -> dict[str, Any]:
    """Wait for a held call_sdk_command step to finish. Returns that step's final result
    (status "success" or "error", as call_sdk_command would have) once it is resumed or
    released, or status "held" again if it is still held after wait_s (at most 25 s) --
    call again in that case.

    Args:
        step: The "step" from the call_sdk_command result that came back "held".
        wait_s: How long to wait in this one call (long poll), up to 25 s.
    """
    return await _run_control.await_step(step, wait_s)


@mcp.tool()
def stop_commands() -> dict[str, Any]:
    """Stop: hold the next normal call_sdk_command before it runs, without aborting VENUS.
    A command already running finishes normally. While held, send recovery commands with
    call_sdk_command(..., recovery=True), then resume_commands / resume_commands_from /
    release_command_hold."""
    return _run_control.request_stop()


async def _resume_with_light(resuming: Any) -> dict[str, Any]:
    """Green while the held step (and any replays) run; a new hold turns it red/blue again
    through the event, otherwise it goes back to white once idle."""
    if _run_control.state in ("held", "stop_requested"):
        await _status_light.running()
    try:
        return await resuming
    finally:
        if _run_control.state == "running":
            _status_light.schedule_idle()


@mcp.tool()
async def resume_commands() -> dict[str, Any]:
    """Resume: re-run the held step and hand its result to the caller waiting on it (after
    any replay steps still pending from an interrupted resume_commands_from). If it fails
    again with a Cancel-answered error it stays held. With a stop requested but nothing held
    yet, just cancels the stop."""
    try:
        return await _resume_with_light(_run_control.resume(_dispatch_sdk_command))
    except RunControlError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
async def resume_commands_from(step: int) -> dict[str, Any]:
    """Resume From: replay every normal step from *step* up to the held one that succeeded
    the first time, in order (recovery commands are never replayed), then re-run the held
    step. A replay failure answered as Cancel holds there again (resume_commands carries on
    from that point); an abort fails the held step.

    Args:
        step: The first step to replay (see get_command_journal); at most the held step.
    """
    try:
        return await _resume_with_light(_run_control.resume_from(step, _dispatch_sdk_command))
    except RunControlError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
def release_command_hold(message: str | None = None) -> dict[str, Any]:
    """Give up on the held step: its waiting caller gets an error (error_type
    "HoldReleased") and normal commands are accepted again. Also cancels a pending stop."""
    try:
        return _run_control.release_hold(message)
    except RunControlError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
def get_command_hold(journal_tail: int = 20) -> dict[str, Any]:
    """Stop/resume state: "running", "stop_requested", "held" or "resuming"; the held step
    with its reason ("error"/"stop") and error; whether hold_on_error is on; and the last
    journal_tail journal entries."""
    return _run_control.summary(journal_tail)


@mcp.tool()
def get_command_journal(since_step: int = 0, include_recovery: bool = True) -> list[dict[str, Any]]:
    """This session's numbered call_sdk_command steps after since_step (name, kwargs,
    status, every attempt), plus recovery commands unless include_recovery is False -- use
    it to pick the step for resume_commands_from."""
    return _run_control.journal(since_step, include_recovery)


@mcp.tool()
def set_error_profile(profile: str) -> dict[str, Any]:
    """Set how the active session recovers from instrument errors, until the session ends.

    Args:
        profile: "standard" (retry, then the operator prompt), "cancel_all" (every error is
            cancelled straight away -- no retry, no prompt -- so with hold_on_error the
            failed step is held for recovery and resume), or a full ErrorProfile as JSON
            (the format of hamilton_venus/error_handling/profiles/standard.json).
    """
    return {"error_profile": _apply_error_profile(profile)}


@mcp.tool()
async def wait_for_command_event(since_seq: int = 0, wait_s: float = 20.0) -> dict[str, Any]:
    """Long poll for stop/resume and status events: returns as soon as a step is held (kind
    "held"), a stop is requested, a hold is resumed / released, or the spoke's status changes
    (kind "status": idle / running / error / hold / paused / terminated, with "previous",
    "detail" and "source" -- session, script or venus) -- or after wait_s (at most 25 s)
    with no events. Call it again straight away with since_seq=next_since_seq to keep
    watching; an agent or orchestrator learns of a hold within a fraction of a second.

    Each event has seq, at, type ("run_hold" or "run_control"), kind, state after the event,
    and for a hold: step, command, reason ("error"/"stop"), error_type and message.
    "restarted": True means the spoke restarted since since_seq -- start again from 0.

    Args:
        since_seq: The last seq already seen (0 for everything still kept).
        wait_s: How long to wait for a new event in this one call, up to 25 s.
    """
    _ensure_status_watcher()
    restarted = since_seq > _run_control.last_event_seq
    if restarted:
        since_seq = 0
    deadline = time.monotonic() + max(0.0, min(float(wait_s), 25.0))
    events = _run_control.events_since(since_seq)
    while not events and not restarted and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
        events = _run_control.events_since(since_seq)
    return {
        "events": [{"kind": _event_kind(e), **e} for e in events],
        "next_since_seq": _run_control.last_event_seq,
        "state": _run_control.state,
        "hold": _run_control.hold_brief,
        "status": _status_view(),
        "restarted": restarted,
    }


@mcp.tool()
def subscribe_command_events(url: str, kinds: list[str] | None = None) -> dict[str, Any]:
    """Have this spoke POST a JSON body to *url* for every stop/resume, failure, operator-prompt
    and status event, the moment it happens -- so an orchestrator or hub is told without
    polling (a step held or failed, a prompt waiting, or the status turning idle / running /
    error / hold / paused / terminated). The body is the
    event (see wait_for_command_event) plus "spoke" (this spoke's name), "connection_id" and
    "kind". Delivery is best effort: one attempt, 5 s timeout, failures only logged.
    Subscriptions last until unsubscribed or the spoke restarts; HAMILTON_MCP_HOLD_WEBHOOKS
    (comma-separated URLs) subscribes URLs to every event at startup.

    Args:
        url: An http:// or https:// endpoint. Subscribing it again replaces its kinds.
        kinds: Only these kinds (held, stop_requested, resuming, resumed, released,
            replay_failed, status, error, operator_prompt, operator_prompt_resolved).
            None for all of them. "error" is a command that failed without being held
            (command, step, error_type, message); the operator_prompt kinds are session
            prompts waiting on resolve_operator_prompt.
    """
    _ensure_status_watcher()
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("url must start with http:// or https://")
    if kinds is not None:
        unknown = sorted(set(kinds) - set(COMMAND_EVENT_KINDS))
        if unknown:
            raise ValueError(f"Unknown kinds {unknown}. Use any of: {', '.join(COMMAND_EVENT_KINDS)}.")
    _command_event_webhooks[url] = frozenset(kinds) if kinds is not None else None
    return {"subscriptions": list_command_event_subscriptions()}


@mcp.tool()
def unsubscribe_command_events(url: str) -> dict[str, Any]:
    """Stop POSTing stop/resume events to *url*."""
    if _command_event_webhooks.pop(url, False) is False:
        raise ValueError(f"{url!r} is not subscribed.")
    return {"subscriptions": list_command_event_subscriptions()}


@mcp.tool()
def list_command_event_subscriptions() -> list[dict[str, Any]]:
    """The URLs this spoke POSTs stop/resume events to, and which kinds each gets."""
    return [
        {"url": url, "kinds": sorted(kinds) if kinds is not None else "all"}
        for url, kinds in _command_event_webhooks.items()
    ]


@mcp.tool()
def set_status_light_tracking(enabled: bool, idle_after_s: float | None = None) -> dict[str, Any]:
    """Whether this spoke drives the instrument's front status light, VENUS-style: white when
    the session connects and when idle, green while commands run, red while a step is held on
    an error, blue after a stop, all at full progress (5), and off (progress 0) when the session closes.
    On by default (HAMILTON_MCP_STATUS_LIGHT=0 starts the spoke with it off).

    Args:
        enabled: Drive the light (True) or leave it alone (False).
        idle_after_s: Seconds without a command before green goes back to white (default 5,
            or HAMILTON_MCP_IDLE_LIGHT_S).
    """
    _status_light.enabled = enabled
    if idle_after_s is not None:
        _status_light.idle_after_s = max(0.0, float(idle_after_s))
    return {
        "enabled": _status_light.enabled,
        "idle_after_s": _status_light.idle_after_s,
        "current": _status_light.current,
    }


@mcp.tool()
def set_hold_on_error(enabled: bool) -> dict[str, Any]:
    """Turn hold-on-error on or off for the rest of this session (see start_session)."""
    _run_control.hold_on_error = enabled
    return _run_control.summary(journal_tail=0)


def _extract_field(value: Any, field: str | None) -> Any:
    """Walk a dot-separated path of dict keys / list indices into *value*. Many SDK
    commands return a CommandResponse-style envelope (returnStatus/returnCode/
    returnParameters, sometimes with a list of per-device readings under
    returnParameters) rather than a flat dict, so a single top-level key isn't enough to
    reach the actual reading -- e.g. odtc_get_temperature's default (all-devices) result
    nests each device's blockTemperature under returnParameters.deviceIds[i]. A missing
    key or out-of-range index resolves to None instead of raising, so a wrong or
    not-yet-present path shows up as "never reached" rather than blowing up the poll loop.
    """
    if field is None:
        return value
    for segment in field.split("."):
        if isinstance(value, dict):
            value = value.get(segment)
        elif isinstance(value, (list, tuple)) and segment.lstrip("-").isdigit():
            index = int(segment)
            value = value[index] if -len(value) <= index < len(value) else None
        else:
            return None
        if value is None:
            return None
    return value


@mcp.tool()
async def poll_sdk_command_until(
    name: str,
    target: Any,
    field: str | None = None,
    tolerance: float | None = None,
    kwargs: dict[str, Any] | None = None,
    stable_reads: int = 3,
    interval_s: float = 2.0,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    """Repeatedly call an SDK command and check its result against target, until it holds
    for stable_reads consecutive polls or timeout_s elapses -- for closed-loop convergence
    checks (a temperature/position settling, instrument_is_idle() turning True while a
    method runs, ...) without the caller round-tripping one call_sdk_command per poll.

    Works against any command reachable through call_sdk_command -- STAR/Vantage or
    standalone (hhc_*/odtc_*) alike. Returns every sample with its timestamp so the caller
    can see the convergence trend, not just the final value.

    Args:
        name: SDK command to poll (as returned by list_sdk_commands).
        target: The value (or field value) to wait for.
        field: Dot-separated path into the command's result, walking dict keys and list
            indices (e.g. "returnParameters.deviceIds.0.blockTemperature" for
            odtc_get_temperature's per-device-envelope result, or a plain "blockTemperature"
            for a flat dict). Omit for a bare scalar result (e.g. instrument_is_idle's bool).
            A missing/out-of-range path segment resolves to None (never matches, doesn't
            raise) so a wrong path shows up as "never reached" rather than an error.
        tolerance: Numeric tolerance for the comparison (abs(value - target) <= tolerance),
            e.g. for a temperature or position to settle. Omit for exact equality, e.g.
            waiting for a bool or enum/string status field to reach a specific value.
        kwargs: Keyword arguments to pass to the command on every poll.
        stable_reads: Consecutive matching polls required before declaring convergence.
        interval_s: Delay between polls, in seconds.
        timeout_s: Give up and return reached=False after this many seconds.
    """
    loop = asyncio.get_running_loop()
    start = loop.time()
    samples: list[dict[str, Any]] = []
    consecutive = 0

    while True:
        response = await _dispatch_sdk_command(name, kwargs)
        if response["status"] == "error":
            return {
                "reached": False,
                "elapsed_s": loop.time() - start,
                "samples": samples,
                "error": {k: v for k, v in response.items() if k not in ("command", "status")},
            }

        value = _extract_field(response["result"], field)
        samples.append({"value": value, "timestamp": response["timestamp"]})

        if tolerance is not None:
            matched = isinstance(value, (int, float)) and abs(value - target) <= tolerance
        else:
            matched = value == target
        consecutive = consecutive + 1 if matched else 0

        if consecutive >= stable_reads:
            return {"reached": True, "elapsed_s": loop.time() - start, "samples": samples}
        if loop.time() - start >= timeout_s:
            return {"reached": False, "elapsed_s": loop.time() - start, "samples": samples}

        await asyncio.sleep(interval_s)


@mcp.tool()
async def send_raw_command(
    category: str, action_name: str, parameters: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Advanced fallback: send a structured command directly (category, dot-separated
    action_name, and parameters) for anything without a dedicated typed SDK method
    reachable through call_sdk_command.
    """
    star = _active_star()
    async with _lock:
        try:
            result = await asyncio.to_thread(star.send_command, category, action_name, parameters or {})
        except VenusError as exc:
            return {"status": "error", "timestamp": time.time(), **_describe_venus_error(exc)}
    return {"status": "success", "timestamp": time.time(), "result": serialize_result(result)}


# -- simulated error injection ------------------------------------------------------
#
# These wrap the ErrorSimulatorCommandsMixin methods (also reachable via
# call_sdk_command) with explicit tools so an agent can discover them directly and
# see the valid module/step/error values. Simulation-mode sessions only.


@mcp.tool()
async def set_simulated_error(
    module: str, step: str, error: str, channels: list[int] | None = None
) -> dict[str, Any]:
    """Make the next *step* on *module* fail with *error* on the active (simulated)
    session's instrument. Writes the chosen error into ``<instrument>_Simulator.cfg``.

    Only one simulated error is active at a time -- this clears any previous one
    first (VENUS's firmware simulator misbehaves with several at once), so call
    it immediately before the step it targets.

    Args:
        module: one of list_simulatable_errors' modules, e.g. "1mL", "IPG", "MPH96".
        step: firmware step description, e.g. "Aspirate", "Tip Pick Up" (fuzzy-matched).
        error: error description, e.g. "No tip picked up" (fuzzy-matched), or a
            "1.<desc>;2.<desc>" per-channel string.
        channels: for a per-channel module (1mL/5mL/X1/MagPip), the channels to
            apply the error to; omit to apply it to all 8 channels.
    """
    star = _active_star()
    async with _lock:
        try:
            await asyncio.to_thread(star.simulate_error, module, step, error, channels=channels)
        except VenusError as exc:
            return {"status": "error", **_describe_venus_error(exc)}
    return {"status": "success"}


@mcp.tool()
async def set_simulated_error_by_code(
    firmware_command: str, error_code: str, error_recovery: str = ""
) -> dict[str, Any]:
    """Write *error_code* as the raw simulated reply for *firmware_command* with no
    keyword matching (advanced; prefer set_simulated_error). Clears any previously
    injected error first, so only this one is active."""
    star = _active_star()
    async with _lock:
        try:
            await asyncio.to_thread(
                star.simulate_error_by_code, firmware_command, error_code, error_recovery
            )
        except VenusError as exc:
            return {"status": "error", **_describe_venus_error(exc)}
    return {"status": "success"}


@mcp.tool()
async def clear_simulated_errors() -> dict[str, Any]:
    """Reset every firmware command to its "no error" reply for the active session."""
    star = _active_star()
    async with _lock:
        try:
            await asyncio.to_thread(star.clear_simulated_errors)
        except VenusError as exc:
            return {"status": "error", **_describe_venus_error(exc)}
    return {"status": "success"}


@mcp.tool()
async def list_simulatable_errors(module: str) -> dict[str, Any]:
    """List the error descriptions known for *module* on the active session's
    instrument (use with set_simulated_error)."""
    star = _active_star()
    errors = await asyncio.to_thread(star.list_simulatable_errors, module)
    steps = await asyncio.to_thread(star.list_simulatable_steps, module)
    return {"module": module, "steps": steps, "errors": errors}


# -- catalog maintenance --------------------------------------------------------------


@mcp.tool()
async def regenerate_catalog() -> dict[str, Any]:
    """Regenerate this machine's local static labware/liquid-class catalog
    (hamilton_venus.catalog.LABWARE/LIQUID_CLASSES) from the active session's connected
    client and this machine's local VENUS install. Requires an active, connected session
    (see start_session/connect_instrument). Useful after installing new labware
    definitions or liquid classes in VENUS -- reuses the already-open connection rather
    than starting a second one.

    Returns which of labware.py/liquid_classes.py/__init__.py actually changed.
    """
    star = _active_star()
    async with _lock:
        changed = await asyncio.to_thread(_regenerate_local_catalog, star)
    return {"changed": changed}


# -- events / operator escalation --------------------------------------------------------


@mcp.tool()
def get_recent_events(max_items: int = 50) -> list[dict[str, Any]]:
    """Drain up to max_items pending events (SDK trace log lines, operator_prompt events)
    from the active session's event queue. Call after call_sdk_command to see SDK trace
    output, and to detect operator_prompt events that need resolve_operator_prompt.
    """
    events: list[dict[str, Any]] = []
    while len(events) < max_items:
        try:
            events.append(_session.log_queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return events


@mcp.tool()
def resolve_operator_prompt(
    error_uuid: str, action: str | None = None, channel_actions: dict[str, int] | None = None
) -> dict[str, Any]:
    """Resolve a pending operator_prompt event (surfaced via get_recent_events) raised
    when an instrument error needs a human/AI recovery decision.

    Args:
        error_uuid: The prompt's error_uuid field.
        action: One of the prompt's advertised top_level_actions/per_channel_actions
            (e.g. "retry", "ignore", "abort"), applied to the whole error.
        channel_actions: Instead of action, a recovery per failed channel/position:
            {detail_uuid: action id}, using the ids the prompt's channel_errors list.
    """
    resolved = _session.resolve_operator_prompt(error_uuid, action, channel_actions)
    if not resolved:
        raise ValueError(f"No pending operator prompt with error_uuid={error_uuid!r}")
    return {"resolved": True}


# -- script runs ------------------------------------------------------------------------------------
#
# Whole scripts, run from one controlled folder, with the run's simulate setting forced in,
# progress you can follow, and errors that wait for a *human* (see script_runs/operator_gate.py).
# A script's own StarClient is separate from this module's interactive session (_session), so a run
# and a session cannot both be active: run_script refuses while a session exists, start_session
# refuses while a run is active.


def _session_active() -> bool:
    try:
        _session.star
        return True
    except RuntimeError:
        return False


def start_operator_ui() -> OperatorServer:
    """Start the operator web page (once). Called by __main__ before serving; never raises."""
    global _operator_server
    if _operator_server is None:
        _operator_server = start_operator_server(_run_manager, _operator_gate)
    return _operator_server


def _operator_ui_info() -> dict[str, Any]:
    if _operator_server is None:
        return {"listening": False, "url": None, "error": "The operator page has not been started."}
    return _operator_server.to_dict()


async def _run_preflight() -> str | None:
    """Reasons a script cannot start right now, or None."""
    if _session_active():
        return "An interactive session is active on this spoke. Call close_session first, then run_script."
    run_state = await _session.check_run_state()
    if run_state is not None and run_state in BUSY_RUN_STATES:
        return (
            f"VENUS Run Control is currently {run_state.name}: a method is already running. Starting a script "
            "would silently abort it. Ask the user to confirm it is safe to clear, or wait for it to finish."
        )
    return None


@mcp.tool()
def list_scripts() -> dict[str, Any]:
    """List the scripts stored on this spoke: name, size, hash, and the latest validation result
    (whether it passed and whether the file has changed since). Only stored scripts can be run."""
    return {"scripts_dir": str(_store.root), "scripts": _store.list()}


@mcp.tool()
def get_script(name: str) -> dict[str, Any]:
    """Return a stored script's text, hash, and validation status."""
    return {"name": name, "content": _store.read_text(name), "sha256": _store.sha256(name), **_store.validation_status(name)}


@mcp.tool()
def import_script(
    name: str | None = None,
    content: str | None = None,
    source_path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Store a script in this spoke's scripts folder and check it against the SDK.

    Give exactly one of ``content`` (the script's text, e.g. one you just wrote) or
    ``source_path`` (a ``.py`` file already on this machine). The script is always stored, then
    validated: the result says ``runnable`` and lists every error/warning with a rule id, line and
    usually a suggestion. Fix the errors and import again with ``overwrite=True``. A script with
    validation errors is stored but cannot be run.

    Args:
        name: File name (letters, digits, ``_ - . space``, ending ``.py``, no folder). Optional with
            ``source_path`` (defaults to that file's name).
        content: The script text.
        source_path: Path of a ``.py`` file on the spoke's own machine to copy in.
        overwrite: Replace an existing script of the same name.
    """
    if (content is None) == (source_path is None):
        raise ValueError("Give exactly one of content or source_path.")
    if source_path is not None:
        default_name, content = _store.read_source_file(source_path)
        name = name or default_name
    if not name:
        raise ValueError("name is required when importing content.")
    assert content is not None
    path = _store.write(name, content, overwrite=overwrite)
    report = validate_bytes(path.read_bytes(), name)
    _store.record_validation(name, report.to_dict())
    return {
        "imported": True,
        "name": name,
        "path": str(path),
        "runnable": report.ok,
        "validation": report.to_dict(),
    }


@mcp.tool()
def validate_script(name: str) -> dict[str, Any]:
    """Re-run the static feasibility check on a stored script and return the full report."""
    report = validate_bytes(_store.read_bytes(name), name)
    _store.record_validation(name, report.to_dict())
    return {"name": name, "runnable": report.ok, "validation": report.to_dict()}


@mcp.tool()
async def run_script(script: str, simulate: bool = True, max_runtime_s: float | None = None) -> dict[str, Any]:
    """Start a stored script and return immediately with a run_id; follow it with
    get_run_events / get_run.

    The script is re-validated first (errors block the run) and the validated text is what runs.
    ``simulate`` is forced into every StarClient/VantageClient the script creates, overriding
    whatever the script says, and VENUS's system-wide simulation mode is set to match (its
    previous value is reported in the run's ``system_simulation_mode``). Refused if an interactive
    session is active, another script is running, or VENUS is busy. ``simulate=False`` drives real
    hardware and is refused unless the spoke's operator enabled it -- only ask for it when the user
    explicitly wants real hardware.

    Errors the SDK cannot recover from stop the script and wait for a human: see the
    instructions, get_spoke_state and operator_ui.

    Args:
        script: Name of a stored script (see list_scripts).
        simulate: Run against the VENUS simulator (default) or real hardware.
        max_runtime_s: Abort and fail the run after this many seconds; omit for no limit.
    """
    run = await _run_manager.start_run(
        script, simulate=simulate, max_runtime_s=max_runtime_s, preflight=_run_preflight
    )
    return {
        "run_id": run.run_id,
        "script": run.script,
        "simulate": run.simulate,
        "status": run.status,
        "next": "Call get_run_events(run_id, since_seq=0, wait_s=20) to follow it.",
        "operator_ui": _operator_ui_info(),
    }


@mcp.tool()
def get_run(run_id: str | None = None) -> dict[str, Any]:
    """Full state of a run (the active or most recent one if run_id is omitted): status, current
    line, elapsed time, error, labware added, tips picked up and remaining per pool, liquid seen
    per aspirated well, pending prompts (with the options a human can choose) and prompt history."""
    return _run_manager.get_run(run_id)


@mcp.tool()
def get_run_summary(run_id: str | None = None) -> dict[str, Any]:
    """A finished run's summary: result, duration, step/error counts, failed steps (with the
    script line that was executing), instrument errors, tips used by type, plates/lids added by
    type, volume drawn from each reservoir, and TADM totals. Only available once a run has
    finished (get_run's "status" is completed/failed/stopped) and its SDK run log was found;
    computed once, right when the run finishes."""
    return _run_manager.get_run_summary(run_id)


@mcp.tool()
def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    """Recent runs, newest first, including runs from before this server last restarted."""
    return _run_manager.list_runs(max(1, min(int(limit), 100)))


@mcp.tool()
async def get_run_events(
    run_id: str | None = None,
    since_seq: int = 0,
    max_items: int = 200,
    wait_s: float = 0.0,
    types: list[str] | None = None,
) -> dict[str, Any]:
    """Events from a run after ``since_seq``, oldest first: the script's own output (``stdout``),
    SDK log/trace lines (``stderr``), ``labware``, ``tips``, ``aspirate``, ``state`` (paused/
    running), ``prompt`` (needs a human), ``prompt_resolved``, ``run_finished``, and so on.

    A long poll: with ``wait_s`` it waits for something new instead of returning empty. Pass the
    returned ``next_since_seq`` as the next ``since_seq``. ``dropped`` counts events lost because
    the run produced more than the server keeps (the newest 5,000).

    Args:
        run_id: Omit for the active or most recent run.
        since_seq: Last sequence number already seen (0 for the beginning).
        max_items: Page size, up to 1000.
        wait_s: Seconds to wait for a new event, capped at 25 (the hub gives up at 30).
        types: Only these event types (e.g. ["prompt", "state", "run_finished"]).
    """
    wait = max(0.0, min(float(wait_s), 25.0))
    return await _run_manager.get_events(
        run_id,
        since_seq=max(0, int(since_seq)),
        max_items=max_items,
        wait_s=wait,
        types=set(types) if types else None,
    )


@mcp.tool()
def pause_run(run_id: str | None = None) -> dict[str, Any]:
    """Pause the active run: VENUS pauses at its next command and the script at its next line.
    Confirm with get_run (status "paused")."""
    return _run_manager.pause(run_id)


@mcp.tool()
def resume_run(run_id: str | None = None) -> dict[str, Any]:
    """Resume a paused run."""
    return _run_manager.resume(run_id)


@mcp.tool()
def abort_run(run_id: str | None = None) -> dict[str, Any]:
    """Abort the active run: the instrument is terminated through the SDK so VENUS tears the
    method down cleanly, and the script's process is killed if it has not stopped after a grace
    period. The run ends as "stopped"."""
    return _run_manager.abort(run_id)


@mcp.tool()
def acknowledge_run_error(run_id: str | None = None) -> dict[str, Any]:
    """Mark a failed run as seen, so get_spoke_state stops reporting the spoke as in error.
    Only do this once the user has been told about the failure."""
    return _run_manager.acknowledge(run_id)


async def _spoke_state_once() -> dict[str, Any]:
    try:
        venus_state: dict[str, Any] | None = await asyncio.to_thread(venus_api.get_run_state)
    except venus_api.VenusApiError as exc:
        venus_state = {"error": str(exc)}
    state = _run_manager.state(session_active=_session_active(), venus_run_state=venus_state)
    state["operator_ui"] = _operator_ui_info()
    state["scripts_dir"] = str(_store.root)
    state["name"] = _spoke_name()
    state["connection_id"] = _session.connection_id
    state["installed_instrument_type"] = _installed_value()
    state["command_control"] = {
        "state": _run_control.state,
        "hold": _run_control.hold_brief,
        "last_event_seq": _run_control.last_event_seq,
    }
    # Failures, holds and operator prompts that are no longer (or never were) a hold, so a hub
    # poll after recovery still sees what went wrong; and the prompts a command is blocked on.
    state["recent_errors"] = _run_control.recent_errors(20)
    state["pending_operator_prompts"] = _session.pending_operator_prompts
    _ensure_status_watcher()
    _publish_status()
    # idle | running | error | hold | paused | terminated, with detail, source and since.
    state["status"] = _status_view()
    # Lets a hub see whether its own event callback is still subscribed (lost on a restart).
    state["event_subscriptions"] = list(_command_event_webhooks)
    return state


# While a run is active, run.elapsed_s() ticks every poll, so a long-poll below effectively
# returns after one _STATE_POLL_INTERVAL_S rather than idling for the full wait_s -- still a
# large win over the hub's 5s background poll / dashboard's 2-3s poll, and it's genuinely idle
# (returns only at wait_s) once nothing is running, which is when "wait for a real change"
# matters most (idle -> running, or an error appearing).
_STATE_POLL_INTERVAL_S = 0.3


@mcp.tool()
async def get_spoke_state(wait_s: float = 0.0) -> dict[str, Any]:
    """This spoke's overall state, in one call: ``state`` is ``idle``, ``running`` (a script is
    active; ``paused`` says whether it is paused) or ``error`` -- a human is needed, because a
    prompt is waiting (``error_kind`` "prompt_pending") or the last run failed and has not been
    acknowledged ("run_failed"). Also the active run, pending prompts with their options, the last
    run, whether an interactive session is active, VENUS's own run state, and where the operator
    page is.

    Args:
        wait_s: Long-poll instead of a fixed polling interval -- watches for the state to change
            from what it is right now (any field, not just ``state``) and returns the instant it
            does, or after wait_s seconds if nothing changes (clamped to 25, matching
            get_run_events' own ceiling). 0 (default) returns immediately, exactly like before.
            Prefer this over calling get_spoke_state in a sleep loop: call it again with the same
            wait_s as soon as it returns, for near-immediate updates instead of a fixed cadence.
    """
    first = await _spoke_state_once()
    wait_s = max(0.0, min(float(wait_s), 25.0))
    if wait_s <= 0:
        return first
    deadline = asyncio.get_event_loop().time() + wait_s
    current = first
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(_STATE_POLL_INTERVAL_S)
        current = await _spoke_state_once()
        if current != first:
            return current
    return current


@mcp.tool()
def operator_resolve_prompt(
    run_id: str,
    prompt_id: str,
    token: str,
    action: str | None = None,
    channel_actions: dict[str, int] | None = None,
    operator: str | None = None,
) -> dict[str, Any]:
    """HUMAN OPERATORS ONLY -- do not call this yourself. Answers a run's pending prompt with one
    of the options it offered. It needs the operator token, which is not available to agents; the
    people who answer prompts use the operator page or the hub dashboard, which call this for them.

    Args:
        run_id: The run the prompt belongs to.
        prompt_id: The prompt's id, from get_run / get_run_events / get_spoke_state.
        token: The operator token.
        action: One of the prompt's options (e.g. "retry", "abort", "continue").
        channel_actions: For an instrument error, independent per-channel picks (detail uuid ->
            action id) instead of one ``action``.
        operator: The person's name, recorded with the decision.
    """
    return _operator_gate.resolve(
        token,
        run_id,
        prompt_id,
        action=action,
        channel_actions=channel_actions,
        operator=operator,
        source="mcp_tool",
    )


# -- consumables: thresholds, usage over time, current levels, reloads -----------------------
#
# Tracking itself happens inside a run's own child process (see script_runs/child_bootstrap.py)
# and is recorded to the ledger once, when the run finishes (script_runs/manager.py's
# _record_consumables). These tools configure what is tracked and how it is reported; they never
# touch a live run directly.


@mcp.tool()
def get_consumables_config() -> dict[str, Any]:
    """Configured tip pool thresholds and tracked reagent sources on this spoke."""
    return _run_manager.consumables_config.snapshot()


@mcp.tool()
def set_tip_threshold(tip_pool: str, low_threshold: int) -> dict[str, Any]:
    """Set the low-tip-count warning threshold for a tip pool. A run's tip pickups below this
    count fire one consumable_warning event (edge-triggered: once when crossing below, again
    only after climbing back above and crossing below again)."""
    entry = _run_manager.consumables_config.set_tip_threshold(tip_pool, int(low_threshold))
    _run_manager.ledger.set_config("tip", entry.tip_pool, low_threshold=float(entry.low_threshold))
    return {"tip_pool": entry.tip_pool, "low_threshold": entry.low_threshold}


@mcp.tool()
def register_reagent(
    labware: str,
    well: str = "all",
    label: str = "",
    low_percent: float = 0.10,
    lot: str | None = None,
    capacity_ul: float | None = None,
) -> dict[str, Any]:
    """Track a labware position as a reagent source, with its own low-percent-full threshold.

    A reservoir-class labware (e.g. a trough) is auto-tracked the first time a run aspirates
    from it, using the default 10% threshold -- register it here only to rename it, set a
    different threshold, or tag a lot. A tube or plate well is never auto-tracked; register it
    explicitly to have it tracked and reported at all.

    Args:
        labware: Labware id on the deck. IMPORTANT: matched exactly, case-sensitive, against the
            key a run's own live tracking builds from the script's ``positions=`` selector
            string -- not against VENUS's (lower-cased) storage. Pass this in the same casing
            the script actually uses in its selector (e.g. "Trough1" if the script pipettes
            "Trough1@all"), or the threshold set here will silently never match that run's
            tracked key and this reagent's low-volume warning will never fire.
        well: The well/position (e.g. "1", "A1"), or "all" for a pooled reservoir.
        label: Human-readable name; defaults to the labware/well key.
        low_percent: Fraction (0.0-1.0) of capacity below which a consumable_warning fires.
        lot: Optional lot/batch label, recorded with the registration.
        capacity_ul: Full-container volume (uL) that percent-full is measured against. By default it
            comes from the labware's own geometry, which can differ from the nominal size (the 60 mL
            trough's geometry works out to about 80 mL, so 33 mL would read 42% instead of 55%).
            Set it to what "100% full" means for you; leave it out to keep the geometry value (or
            the one set earlier).
    """
    entry = _run_manager.consumables_config.register_reagent(
        labware, well, label, float(low_percent), lot, None if capacity_ul is None else float(capacity_ul)
    )
    _run_manager.ledger.set_config("reagent", entry.key, label=entry.label or None, low_threshold=float(entry.low_percent))
    return {
        "key": entry.key,
        "labware": entry.labware,
        "well": entry.well,
        "label": entry.label,
        "low_percent": entry.low_percent,
        "lot": entry.lot,
        "capacity_ul": entry.capacity_ul,
    }


@mcp.tool()
def remove_reagent_threshold(key: str) -> dict[str, Any]:
    """Stop tracking a reagent source registered with register_reagent (or auto-discovered).
    ``key`` is the labware id (pooled) or ``labware@well``, from get_consumables_config /
    get_consumables_levels."""
    return {"key": key, "removed": _run_manager.consumables_config.remove_reagent(key)}


@mcp.tool()
def get_consumables_usage(
    start: str | None = None,
    end: str | None = None,
    kind: str | None = None,
    item_key: str | None = None,
    script: str | None = None,
    simulate: bool = False,
    group_by: str = "item",
) -> list[dict[str, Any]]:
    """Total consumption over a period, across every run on this spoke -- "how many tips of type
    X", "how much of reagent Y", "how many plates". ``kind`` is "tip", "reagent", "plate", or
    "lid". ``simulate=False`` (default) counts only real-hardware runs; pass ``True`` to include
    simulated ones too (they are always recorded, just excluded from this default view).

    Args:
        start: ISO timestamp; only usage from runs at/after this time.
        end: ISO timestamp; only usage from runs before this time.
        kind: Restrict to one consumable kind.
        item_key: Restrict to one item (a tip type, reservoir labware id, or labware definition).
        script: Restrict to one script name.
        simulate: Include simulated runs' usage.
        group_by: "item" (default, total per item), "day", "run", or "script".
    """
    return _run_manager.ledger.usage_report(
        start=start, end=end, kind=kind, item_key=item_key, script=script, simulate=bool(simulate), group_by=group_by
    )


@mcp.tool()
def get_consumables_levels(kind: str | None = None) -> list[dict[str, Any]]:
    """The most recently recorded level for every tracked consumable (one row per item):
    current level, capacity, percent, whether it is below its configured threshold, and when it
    was last updated (from the most recent run that touched it)."""
    return _run_manager.ledger.current_levels(kind)


@mcp.tool()
def list_low_consumables(kind: str | None = None) -> list[dict[str, Any]]:
    """Only the tracked consumables currently below their configured low threshold."""
    return _run_manager.ledger.low_items(kind)


@mcp.tool()
def get_consumables_events(kind: str | None = None, item_key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Recent reload/correction events for tracked consumables, most recent first. A reload
    recorded automatically (an operator continuing a tip/liquid reload prompt during a run) has
    ``run_id`` set; one recorded with record_consumable_event does not."""
    return _run_manager.ledger.events(kind=kind, item_key=item_key, limit=int(limit))


@mcp.tool()
def record_consumable_event(
    kind: str,
    item_key: str,
    event_type: str,
    token: str,
    amount: float | None = None,
    operator: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """HUMAN OPERATORS ONLY -- do not call this yourself. Records a manual consumables event: a
    tip rack physically reloaded, a reagent bottle refilled, or a hand count correction. This
    changes what get_consumables_levels/get_consumables_usage report, so it needs the operator
    token, the same as resolving an instrument-error prompt.

    Args:
        kind: "tip" or "reagent" (matching get_consumables_config's/levels' own kind values).
        item_key: The tip pool name, or the reagent's key (labware id, or labware@well).
        event_type: "reload", "counter_reset", "counter_set", or another short label.
        token: The operator token.
        amount: Optional quantity (e.g. tips added, or the new count for counter_set).
        operator: The person's name, recorded with the event.
        note: Optional free-text note.
    """
    _operator_gate.verify(token)
    event_id = _run_manager.ledger.add_event(kind, item_key, event_type, amount=amount, operator=operator, note=note)
    return {"id": event_id, "kind": kind, "item_key": item_key, "type": event_type}


# -- VENUS itself (whatever is running, whoever started it) ----------------------------------------


async def _venus_call(fn: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(fn, *args, **kwargs)
    except venus_api.VenusApiError as exc:
        return {"status": "error", "message": str(exc), "timestamp": time.time()}
    return {"status": "success", "result": result, "timestamp": time.time()}


@mcp.tool()
async def get_venus_run_state() -> dict[str, Any]:
    """VENUS's own run state (e.g. NOT_INITIALIZED, RUNNING, PAUSED) from its Web API."""
    return await _venus_call(venus_api.get_run_state)


@mcp.tool()
async def get_venus_current_run_data() -> dict[str, Any]:
    """Detailed runtime information for the method VENUS is running right now (result is null
    when nothing is running)."""
    return await _venus_call(venus_api.get_current_run_data)


@mcp.tool()
async def list_venus_run_history(
    limit: int = 25,
    offset: int = 1,
    run_state: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    sort_property: str | None = None,
    sort_order: str | None = None,
) -> dict[str, Any]:
    """VENUS's own run history (every method run on this machine, including runs not started
    through this server), newest first. ``offset`` is 1-based (1 = the newest run; VENUS rejects
    0). Dates are ISO strings; ``run_state`` filters by outcome."""
    return await _venus_call(
        venus_api.list_run_history,
        limit=max(1, min(int(limit), 200)),
        offset=max(1, int(offset)),
        run_state=run_state,
        start_date=start_date,
        end_date=end_date,
        sort_property=sort_property,
        sort_order=sort_order,
    )


@mcp.tool()
async def get_venus_run_detail(run_guid: str) -> dict[str, Any]:
    """Detailed runtime information for one past run, by its VENUS run GUID (from
    list_venus_run_history)."""
    return await _venus_call(venus_api.get_run_detail, run_guid)


@mcp.tool()
async def get_venus_run_trace(run_guid: str | None = None, method_name: str | None = None) -> dict[str, Any]:
    """The VENUS trace (log) lines for a run, by run GUID or method name."""
    return await _venus_call(venus_api.get_run_trace, run_guid=run_guid, method_name=method_name)


@mcp.tool()
async def venus_pause() -> dict[str, Any]:
    """Pause the method VENUS is running, whoever started it. For a script started with
    run_script, prefer pause_run, which also pauses the script itself."""
    global _venus_paused
    result = await _venus_call(venus_api.pause)
    _venus_paused = True
    _publish_status()
    return result


@mcp.tool()
async def venus_resume() -> dict[str, Any]:
    """Resume the method VENUS has paused."""
    global _venus_paused
    result = await _venus_call(venus_api.resume)
    _venus_paused = False
    _publish_status()
    return result


@mcp.tool()
async def venus_abort() -> dict[str, Any]:
    """Abort the method VENUS is running, whoever started it. Use this for a run that was not
    started through run_script; for one that was, prefer abort_run, which shuts the script down
    cleanly first."""
    global _venus_paused
    result = await _venus_call(venus_api.abort)
    _venus_paused = False
    _publish_status()
    return result
