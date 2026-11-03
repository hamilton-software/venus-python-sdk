"""FastMCP hub that fans tool calls out to networked hamilton_venus_mcp spokes.

Each spoke is an unmodified hamilton_venus_mcp server (see the mcp_server project) running
on its own instrument PC. This hub never talks to hamilton_venus/VENUS directly -- it only
ever relays MCP tool calls to a spoke's own session (see spokes.py) and compiles the
results, mirroring call_sdk_command's own generic name+kwargs dispatch philosophy instead of
hand-writing one hub tool per spoke tool.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import os
import socket
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from mcp.server.fastmcp import FastMCP
from mcp.types import BlobResourceContents, CallToolResult, ListResourcesResult, ReadResourceResult, TextContent
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response

from hamilton_venus_mcp_hub import discovery
from hamilton_venus_mcp_hub.auth import callback_key
from hamilton_venus_mcp_hub.spokes import DEFAULT_CALL_TIMEOUT_S, STATE_LABELS, SpokeGroup

_logger = logging.getLogger("hamilton_venus_mcp_hub.server")

_STATIC_DIR = (Path(__file__).parent / "static").resolve()
# The pages and their CSS/JS change together; without this a browser can keep an old stylesheet
# next to a new page (revalidating each load is cheap -- the files are local and ETag'd).
_NO_CACHE = {"Cache-Control": "no-cache"}


def _html_page(path: Path) -> Response:
    """An HTML page whose /static/... links carry the file's modification time (?v=...), so a
    browser that already holds an older hub.css/hub.js/trace.js under the plain URL fetches the
    new one instead of mixing a new page with an old stylesheet."""
    html = path.read_text(encoding="utf-8")
    for name in ("hub.css", "hub.js", "trace.js"):
        asset = _STATIC_DIR / name
        if asset.is_file():
            html = html.replace(f'"/static/{name}"', f'"/static/{name}?v={int(asset.stat().st_mtime)}"')
    return HTMLResponse(html, headers=_NO_CACHE)
_DASHBOARD_HTML_PATH = _STATIC_DIR / "dashboard.html"
_INSTRUMENT_HTML_PATH = _STATIC_DIR / "instrument.html"
_ACTIVITY_LOG_SIZE = 200

_spokes: SpokeGroup | None = None
_activity: deque[dict[str, Any]] = deque(maxlen=_ACTIVITY_LOG_SIZE)
_hub_started_at = time.time()


def set_spokes(group: SpokeGroup) -> None:
    """Configure which spokes this hub talks to. Called by __main__ before mcp.run(); tests
    call it directly instead of going through env-var parsing.
    """
    global _spokes
    _spokes = group


def _active_spokes() -> SpokeGroup:
    if _spokes is None:
        raise RuntimeError("Hub spokes are not configured. Call set_spokes() (or run via __main__) first.")
    return _spokes


_INSTRUCTIONS = (
    "Fans tool calls out to networked hamilton_venus_mcp spokes (one per instrument PC) "
    "and compiles their results. This hub has no tools of its own for controlling an "
    "instrument -- every capability below is a spoke's own hamilton_venus_mcp tool, "
    "reached through this hub's call_tool_on/broadcast_tool_call. If you are only "
    "connected to this hub (no direct connection to a spoke's own MCP server), the "
    "reference sections further down are your only source for spoke tool names, "
    "argument shapes, and selector syntax -- they will not appear anywhere else.\n\n"
    "Clients often pass the model only the first part of these instructions, so the spoke's "
    "own full guide is the way to read the details: call_tool_on(spoke_id, \"get_usage_guide\", "
    "{\"search\": \"<topic>\"}) (e.g. \"positions\", \"reservoir\", \"tube carriers\", \"liquid "
    "class\", \"tip counter\", \"transport\"). Essentials on every spoke: the user chooses "
    "simulation vs live and the deck layout; carrier widths come from search_labware's "
    "width_tracks, never assumed; CO-RE grips are a separate tool that "
    "instrument_get_configuration never reports (gripper is the iSWAP / IPG) -- when the user "
    "says the system has them, add them (add_1ml_core_grip / add_qcg) if get_transport_tool_ids "
    "is empty; use the CO-RE grips for on-deck moves and the iSWAP only for off-deck, rotations "
    "or when asked.\n\n"
    "Hub mechanics:\n"
    "1. list_spokes() to see configured spokes and whether each is connected.\n"
    "2. call_tool_on(spoke_id, tool_name, arguments) for a single spoke -- tool_name is "
    "any tool that spoke's own hamilton_venus_mcp server exposes (start_session, "
    "call_sdk_command, poll_sdk_command_until, ...).\n"
    "3. broadcast_tool_call(tool_name, arguments, spoke_ids) to run the same call across "
    "several (default: all) spokes concurrently and get back one dict keyed by spoke id "
    "-- e.g. broadcast_tool_call('call_sdk_command', {'name': 'odtc_get_temperature'}) to "
    "read every STAR's ODTC in one round trip.\n\n"
    "4. list_resources_on(spoke_id) / read_resource_on(spoke_id, uri) reach a spoke's MCP "
    "resources -- a separate capability from tools, for pulling reference content on demand "
    "rather than performing an action. Every spoke exposes "
    "\"docs://hamilton-venus/getting-started\", its own full reference guide (session "
    "lifecycle, deck layout, command/labware discovery, positions selector DSL) -- read it "
    "directly if the summarized version in this hub's reference sections below isn't "
    "enough, or if a spoke has since been updated with more/different guidance than what's "
    "duplicated here. This hub's own such guide is this very text, also available as the "
    "resource \"docs://hamilton-venus-hub/getting-started\" for a client that can pull "
    "resources but doesn't surface server instructions to the model.\n\n"
    "add_spoke(spoke_id, url)/remove_spoke(spoke_id) register or drop a spoke at runtime, "
    "no hub restart needed -- runtime-only, though: update HAMILTON_MCP_SPOKES too if the "
    "change should survive the hub's next restart.\n\n"
    "A live status/activity dashboard is served at /dashboard on this hub's own port -- it "
    "can add/remove spokes too.\n\n"
    "Fleet state and whole-script runs:\n"
    "- list_spokes() / get_fleet_status() report each spoke as idle, running (a script is "
    "active), error (a human is needed), unreachable, or unknown; list_pending_interventions() "
    "lists every run waiting on a human operator, with the options VENUS offers; "
    "list_command_holds() lists every spoke whose call_sdk_command stream is held (stop/resume) "
    "waiting for recovery and resume; "
    "get_fleet_consumables(kind=None) merges every spoke's current tip/reagent levels into one "
    "list (each row tagged with its spoke_id) plus a pre-filtered low_items list -- the "
    "fleet-wide equivalent of calling a single spoke's own list_low_consumables one at a time. "
    "Also shown on the dashboard's \"Low consumables\" card.\n"
    "- To run a whole script on a spoke: call_tool_on(spoke_id, \"import_script\", {\"name\": "
    "..., \"content\": ...}) stores it and validates it against the SDK; fix any errors it "
    "reports and re-import with overwrite=True; call_tool_on(spoke_id, \"run_script\", "
    "{\"script\": ..., \"simulate\": true}) starts it (simulate is forced into the script) and "
    "returns a run_id; follow it with call_tool_on(spoke_id, \"get_run_events\", {\"run_id\": "
    "..., \"since_seq\": <next_since_seq>, \"wait_s\": 20}, call_timeout_s=30) -- keep wait_s "
    "under call_timeout_s -- and control it with pause_run / resume_run / abort_run. The "
    "get_venus_* / venus_* tools on a spoke look at and control VENUS itself.\n"
    "- Prefer long-polling over polling on a fixed interval: both get_run_events and "
    "call_tool_on(spoke_id, \"get_spoke_state\", {\"wait_s\": 20}, call_timeout_s=30) block "
    "until something actually changes (or wait_s elapses) and return immediately at that point "
    "-- call again right away with the same wait_s for near-immediate updates on a spoke's "
    "idle/running/error state, instead of re-polling every few seconds.\n"
    "- When an instrument error the SDK cannot recover from happens: if that spoke has an "
    "operator token configured, the script stops and waits for a HUMAN -- tell the user which "
    "spoke and what the options are; they answer on this hub's /dashboard, and you cannot "
    "answer it yourself. If that spoke has NO operator token configured, it does not wait for a "
    "remote answer at all (nobody could give one) -- it hands the error straight to VENUS's own "
    "local operator dialog and keeps going once a person at that instrument resolves it there; "
    "you will see an informational operator_error_deferred event but there is nothing to do or "
    "tell anyone to do through this hub.\n\n"
    "=== Reference: calling a spoke's hamilton_venus_mcp tools ===\n\n"
    "IMPORTANT -- argument nesting: call_tool_on's own `arguments` becomes that spoke "
    "tool's kwargs, one level in. For a tool that itself takes a name+kwargs pair (namely "
    "call_sdk_command), this means TWO levels of nesting from here, easy to flatten by "
    "mistake. Correct shape:\n"
    "  call_tool_on(spoke_id=\"star1\", tool_name=\"call_sdk_command\", "
    "arguments={\"name\": \"aspirate\", \"kwargs\": {\"positions\": \"Plate1@A1\", "
    "\"volumes\": 100.0, \"liquid_class\": \"...\"}})\n"
    "Tools that do not themselves take a name+kwargs pair (start_session, "
    "connect_instrument, list_sdk_commands, ...) only need the one level: "
    "arguments={\"simulate\": True}, not arguments={\"kwargs\": {\"simulate\": True}}.\n\n"
    "1. Session lifecycle -- call_tool_on(spoke_id, ...) for each, per spoke, before any "
    "SDK command on that spoke:\n"
    "   a. start_session -- the USER chooses simulation vs live and the deck layout; never "
    "pick either for them. Ask simulation or live first, then pass simulate (True, or False "
    "only when they chose the live instrument) and instrument_type (\"STAR\"|\"Vantage\"). "
    "Unless the user already named a layout, pass no deck choice: the result then has "
    "deck_choice_required=True and deck_options (blank, last_layout with its details, "
    "saved_layouts), read from VENUS without connecting the instrument. Show those to the "
    "user, ask which they want, and call_tool_on(spoke_id, \"select_deck_layout\", "
    "{\"deck_name\": \"...\"} | {\"load_previous_deck\": True} | {\"blank_deck\": True}); "
    "connect_instrument refuses until then. A layout the user named up front goes straight "
    "into start_session as deck_name / load_previous_deck=True / blank_deck=True.\n"
    "   b. connect_instrument -- brings the instrument runtime online for that session. "
    "Always follow it with two more call_sdk_command calls before running any protocol, "
    "real hardware or simulated: name=\"instrument_get_configuration\" to learn the actual "
    "arm/tool configuration (per-arm channels_1_ml/channels_5_ml/channels_mag_pip/mph96/"
    "mph384/gripper, and each arm's x_min/x_max physical reach range) rather than assuming "
    "which tools exist or how far they reach; and name=\"autoload_get_carrier_sensor_"
    "status\" to verify every carrier the deck layout expects is actually physically "
    "loaded -- each entry's `status` is True if that carrier is physically pushed in, "
    "False if the sensor doesn't see it (only meaningful where `sensorAvailable` is also "
    "True for that track). IMPORTANT: confirmed directly against real hardware -- in a "
    "simulate=True session `status` comes back False for every single carrier, "
    "unconditionally, regardless of what the deck layout actually specifies. Do NOT "
    "interpret that as \"no carriers are loaded\" or fail/warn on it when simulate=True; "
    "there is no physical sensor to read in simulation, so this check is only "
    "authoritative against real hardware and should be skipped entirely otherwise.\n"
    "   c. After connecting, verify what's actually on the deck rather than assuming -- "
    "there is no single \"get whole deck layout\" call_sdk_command; query per category "
    "instead: call_sdk_command names \"get_added_plates\", \"get_added_carriers\", "
    "\"get_added_tip_racks\", \"get_added_reservoirs\".\n"
    "   d. Before pipetting with a specific tool (1mL/5mL/MagPip channels, MPH96, "
    "gripper, ...), verify every labware you're about to target is actually reachable by "
    "that tool: cross-check call_sdk_command(\"get_labware_coordinates\", {\"labware_"
    "name\": ...})'s origin x coordinate (returned under \"origin\" when no well is "
    "given, next to a \"wells\" list with every well's coordinates; pass \"well\" to get "
    "one well's x/y/z at the top level instead) against step b's matching arm's x_min/x_max range -- "
    "this matters most on a dual-arm Vantage, or any deck with labware on a far track.\n"
    "   e. close_session when done with that spoke.\n\n"
    "2. Command discovery on a spoke -- all via call_tool_on(spoke_id, tool_name, "
    "arguments):\n"
    "   - tool_name=\"list_sdk_categories\" -- distinct command groupings for that "
    "spoke's active instrument type, e.g. \"Channel\", \"Deck\", \"TipPool\".\n"
    "   - tool_name=\"list_sdk_commands\", arguments={\"category\": ..., \"search\": ...} "
    "(both optional) -- list commands, optionally filtered.\n"
    "   - tool_name=\"describe_sdk_command\", arguments={\"name\": \"aspirate\"} -- full "
    "docstring and parameter JSON schema for one command; always check this before a "
    "first call_sdk_command to an unfamiliar command rather than guessing argument names.\n"
    "   - tool_name=\"call_sdk_command\", arguments={\"name\": ..., \"kwargs\": {...}} -- "
    "run it (see the nesting example above). send_raw_command is a fallback for anything "
    "without a dedicated typed method.\n"
    "   - tool_name=\"poll_sdk_command_until\" -- closed-loop wait (e.g. block until a "
    "temperature settles or an instrument reports idle) without one round trip per poll "
    "tick; give call_tool_on's own call_timeout_s headroom above this tool's own "
    "timeout_s so the hub's ceiling doesn't fire first.\n\n"
    "3. Positions selector syntax -- any call_sdk_command whose kwargs include a "
    "`positions`-style argument (aspirate, dispense, tip_pickup, tip_eject, "
    "detect_liquid_level, add_reagent's reagent_source/dest_plate, pool_samples/"
    "replicate_samples' source_plate/dest_plate, serial_dilution's plate_id, ...) accepts "
    "a compact selector string -- prefer it over building explicit position objects by "
    "hand. The colon after `row`/`col` is required, not optional -- `row2`/`col1` are NOT "
    "valid syntax and will be rejected or misparsed as a literal (nonsense) well name, not "
    "silently corrected:\n"
    "   - \"Plate1\" -- every well (equivalent to \"Plate1@all\")\n"
    "   - \"Plate1@A1\" -- one well\n"
    "   - \"Plate1@A1,B1,C1\" -- explicit wells, any number, comma-separated\n"
    "   - \"Plate1@A1:C3\" -- a rectangular range\n"
    "   - \"Plate1@row:A,C:E\" -- whole rows (note the colon: row: not row)\n"
    "   - \"Plate1@col:1,3:5\" -- whole columns (note the colon: col: not col)\n"
    "   A single-well selector is automatically repeated across every channel when more "
    "than one channel is used (e.g. every tip pooling into one shared destination well on "
    "a plate) -- that is not a channel-count mismatch. Not every command uses `positions` "
    "as the parameter name for this DSL (e.g. core_transport uses `site` instead) -- "
    "always check describe_sdk_command's parameter list rather than assuming a parameter "
    "named `positions` exists on every command.\n"
    "   IMPORTANT -- reservoirs specifically: always address a reservoir with the \"@all\" "
    "selector (e.g. \"Trough1@all\"), never a single well like \"Trough1@A1\" alone. A "
    "reservoir is a connected-container labware whose several row/column positions are "
    "meant to be distributed one per channel via \"@all\" -- addressing only the first "
    "well undersupplies or misdirects every channel past the first instead of spreading "
    "them across the reservoir's actual usable positions. This is also a real performance "
    "cost, confirmed directly: pipetting channels are rigidly spaced on the arm and "
    "physically cannot occupy the same point at once, so a single well repeated across "
    "channels forces the instrument to aspirate them one at a time (repositioning between "
    "each) instead of one simultaneous multi-channel aspirate -- \"@all\" lets the SDK's "
    "own spacing-aware interleaving engine assign each channel a distinct, physically-"
    "reachable position so the whole group aspirates together.\n"
    "   IMPORTANT -- labware id casing: VENUS stores every labware id lower-cased on the "
    "deck layout, regardless of the case it was added with -- adding a reservoir with "
    "labware_id=\"Trough1\" is later reported back by VENUS, and by every tracking event or "
    "query result that names it, as \"trough1\". A positions selector string (e.g. "
    "\"Trough1@all\") is matched against VENUS's storage server-side, so it does not need to "
    "be lower-cased -- but if you compare a labware id you typed against one read back from "
    "a spoke tool result, normalize both to the same case first rather than assuming the "
    "original casing survives the round trip.\n\n"
    "4. Labware type catalog (not the same as an instance on the active deck) -- via "
    "call_tool_on(spoke_id, tool_name, arguments):\n"
    "   - tool_name=\"list_labware_categories\" -- category names, e.g. \"CARRIER\", "
    "\"PLATE\", \"TIP_RACK\".\n"
    "   - tool_name=\"search_labware\", arguments={\"category\": ..., \"search\": ...} "
    "(both optional) -- find a labware type name/id, e.g. for a deck layout, without "
    "reading hamilton_venus/catalog/labware.py by hand.\n"
    "   - This is distinct from call_sdk_command(\"get_labware_spec\", {\"labware_id\": "
    "...}), which looks up a labware *instance already placed on the connected deck*, "
    "not a type name -- a name found via search_labware is not guaranteed to resolve "
    "there, and vice versa.\n\n"
    "5. Choosing a liquid class for a transfer -- all via call_tool_on(spoke_id, "
    "\"call_sdk_command\", {...}):\n"
    "   a. name=\"tip_pool_get_tip_counter\", kwargs={\"tip_pool\": ...} -- its response's "
    "tip_type (numeric) is the tip type actually loaded in that pool; cross-reference "
    "name=\"get_tip_types\" if you need it resolved to a name.\n"
    "   b. name=\"get_liquid_devices\" -- returns {device_name, device_id} pairs; resolve "
    "whichever device you're pipetting with (1mL channels, MPH96, etc.) to its device_id.\n"
    "   c. name=\"get_liquid_classes\", kwargs={\"tip_type\": ..., \"device\": ..., "
    "\"dispense_mode\": ...} -- filters to matching liquid_class_names in one call (pass "
    "the dispense mode from step d below in this same call rather than filtering "
    "afterward).\n"
    "   d. Dispense mode to pass as that filter, matching DispenseMode's real values: no "
    "liquid contact + single dispense (empty well, or dispensing above the liquid surface) "
    "-> JET_EMPTY_TIP (\"Jet Empty\"), fixed-height only -- jet modes do not support cLLD "
    "(DispenseSettings.capacitive_lld must be CapacitiveLLD.OFF). No contact + "
    "multi-dispense -> JET_PART_VOLUME (\"Jet Part\"), also fixed-height only. Dispensing "
    "while touching the liquid + single dispense -> SURFACE_EMPTY_TIP (\"Surface Empty\"), "
    "can use either capacitive_lld=CapacitiveLLD.ON (cLLD) or DispenseSettings.fixed_"
    "height. Touching + multi-dispense -> SURFACE_PART_VOLUME (\"Surface Part\"), same "
    "either-cLLD-or-fixed-height flexibility.\n"
    "   e. Among step c's candidates, match by liquid: liquid names are embedded in each "
    "class name (e.g. \"HighVolume_Water_...\"); name=\"get_liquid_names\" lists the "
    "canonical liquid names to match against. There may be no exact match for the actual "
    "liquid in use -- pick the closest one rather than treating \"no exact match\" as a "
    "failure.\n"
    "   f. Before using the chosen class, confirm it with name=\"get_liquid_class\", "
    "kwargs={\"name\": ...} -- its definition.applies_to (liquid/tip_type/dispense_mode/"
    "pipetting_device) is the authoritative per-class metadata, not just what the name "
    "string implies.\n\n"
    "6. Standalone benchtop devices -- commands named hhc_* (Hamilton Heater Cooler, e.g. "
    "hhc_connect) or odtc_* (Inheco ODTC, e.g. odtc_connect) drive their own vendor COM "
    "object directly and do NOT touch the STAR/Vantage instrument or VENUS runtime at "
    "all. They still go through call_sdk_command exactly like every other command, and "
    "start_session/connect_instrument are NOT required first for these specifically -- "
    "do not assume they need a separate session just because they aren't "
    "instrument-related.\n\n"
    "7. Error recovery, all via call_tool_on(spoke_id, ...): tool_name="
    "\"get_recent_events\" after a call to see SDK trace output; if an instrument error "
    "raises an operator_prompt event, resolve it with tool_name="
    "\"resolve_operator_prompt\" before retrying. To exercise error-recovery in a "
    "simulated session: tool_name=\"set_simulated_error\", arguments={\"module\": ..., "
    "\"step\": ..., \"error\": ...} before a step to make it fail, then tool_name="
    "\"clear_simulated_errors\" to restore normal replies; tool_name="
    "\"list_simulatable_errors\", arguments={\"module\": ...} shows valid values.\n\n"
    "8. IMPORTANT -- name=\"tip_pool_show_tip_counter\"/\"tip_pool_show_tip_counters\": these "
    "open a dialog on VENUS's own screen, on the instrument PC -- through a spoke, and "
    "doubly so through this hub, there is no way to see or interact with that dialog. The "
    "call_tool_on call simply blocks (potentially indefinitely) until a human physically at "
    "the instrument closes it, then returns whatever the dialog's result was; a long-blocked "
    "call here is normal, not a hung spoke. For any tip-counter change you need to make "
    "programmatically -- initializing, resetting, setting counts, or just reading the current "
    "state -- use name=\"tip_pool_initialize_tip_counter\" / \"tip_pool_reset_tip_counter\" / "
    "\"tip_pool_set_tip_counter\" / \"tip_pool_get_tip_counter\" / \"tip_pool_get_tip_counters\" "
    "instead; none of those open a dialog."
)

mcp = FastMCP("hamilton-venus-hub", instructions=_INSTRUCTIONS)


@mcp.resource(
    "docs://hamilton-venus-hub/getting-started",
    name="hamilton-venus-hub getting started guide",
    description=(
        "Full reference for calling spoke tools through this hub -- session lifecycle, deck "
        "layout options, command/labware discovery, and the positions selector DSL. Same "
        "content as this server's own MCP `instructions` field, exposed as a pull-able "
        "resource for clients that don't surface server instructions to the model."
    ),
    mime_type="text/plain",
)
def getting_started_doc() -> str:
    return _INSTRUCTIONS


def _record_activity(spoke_id: str, tool_name: str, status: str, latency_ms: float) -> None:
    _activity.appendleft(
        {
            "timestamp": time.time(),
            "spoke_id": spoke_id,
            "tool_name": tool_name,
            "status": status,
            "latency_ms": latency_ms,
        }
    )


def _unwrap_call_tool_result(result: CallToolResult) -> dict[str, Any]:
    """A spoke tool that returns a dict comes back with that dict as-is in
    structuredContent; a non-dict return (e.g. list_sdk_categories' list[str]) comes back
    wrapped as {"result": ...} per the MCP spec. Passed through transparently either way --
    this is a generic proxy, not a per-tool-shape adapter.
    """
    if result.isError:
        text = "\n".join(block.text for block in result.content if isinstance(block, TextContent))
        return {"status": "error", "message": text or "Tool call failed with no error detail"}
    if result.structuredContent is not None:
        return dict(result.structuredContent)
    text = "\n".join(block.text for block in result.content if isinstance(block, TextContent))
    return {"status": "success", "result": text}


def _unwrap_read_resource_result(result: ReadResourceResult) -> dict[str, Any]:
    """A resource's contents come back as a list (usually one entry) of text or binary
    blocks -- flattened into a single string here since every resource this hub/spoke
    pair actually serves today is text/plain, mirroring _unwrap_call_tool_result's
    transparent-passthrough approach rather than a per-resource-shape adapter.
    """
    texts = [c.text for c in result.contents if not isinstance(c, BlobResourceContents)]
    blobs = [c.blob for c in result.contents if isinstance(c, BlobResourceContents)]
    payload: dict[str, Any] = {"status": "success"}
    if texts:
        payload["text"] = "\n".join(texts)
    if blobs:
        payload["blobs_base64"] = blobs
    return payload


def _unwrap_list_resources_result(result: ListResourcesResult) -> list[dict[str, Any]]:
    return [
        {"uri": str(r.uri), "name": r.name, "description": r.description, "mimeType": r.mimeType}
        for r in result.resources
    ]


async def _dispatch_hub_call(
    spoke_id: str, tool_name: str, arguments: dict[str, Any] | None, call_timeout_s: float
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = await _active_spokes().call_tool(spoke_id, tool_name, arguments, timeout_s=call_timeout_s)
        payload = _unwrap_call_tool_result(result)
        # A command the instrument rejected comes back as a normal result whose envelope says so.
        status = "error" if result.isError or payload.get("status") == "error" else "success"
    except Exception as exc:  # noqa: BLE001 - reported as an error envelope, not raised, so
        # one bad spoke can never take down a broadcast_tool_call's asyncio.gather
        payload = {"status": "error", "message": str(exc)}
        status = "error"
    latency_ms = (time.monotonic() - started) * 1000
    _record_activity(spoke_id, tool_name, status, latency_ms)
    payload.setdefault("timestamp", time.time())
    return payload


_STATE_TOOL = "get_spoke_state"
_STATE_POLL_TIMEOUT_S = 8.0
STATE_POLL_INTERVAL_S = 5.0
_OPERATOR_TOKEN_ENV = "HAMILTON_MCP_OPERATOR_TOKEN"
_RESOLVE_TIMEOUT_S = 15.0


# -- spoke event push ------------------------------------------------------------------------
#
# Each spoke POSTs its status changes and holds to this hub the moment they happen (its
# subscribe_command_events webhook), so the dashboard does not wait for the next poll. The hub
# subscribes itself: whenever a poll shows a spoke without this hub's callback URL (a new
# spoke, or one that restarted), it calls subscribe_command_events on it.

HUB_URL_ENV = "HAMILTON_MCP_HUB_URL"  # how spokes reach this hub, e.g. http://hub-pc:8000
EVENT_PUSH_ENABLED = os.environ.get("HAMILTON_MCP_HUB_EVENT_PUSH", "1").strip().lower() not in ("0", "false", "no", "off")
_SPOKE_EVENTS_PATH = "/api/spoke-events"


def _local_address_towards(url: str) -> str:
    """This PC's own address on the route to *url*'s host -- what that spoke should call back on.
    A UDP connect sends nothing; it only makes the OS pick the outgoing interface."""
    host = urlparse(url).hostname or "127.0.0.1"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((host, 9))
            return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def hub_callback_url(spoke_id: str, spoke_url: str) -> str:
    base = os.environ.get(HUB_URL_ENV, "").strip().rstrip("/")
    if not base:
        base = f"http://{_local_address_towards(spoke_url)}:{mcp.settings.port}"
    url = f"{base}{_SPOKE_EVENTS_PATH}?spoke_id={quote(spoke_id)}"
    key = callback_key(spoke_id)
    return f"{url}&key={key}" if key else url


def _is_our_callback_for(subscription: str, spoke_id: str, callback: str) -> bool:
    """An older subscription of this hub for the same spoke (e.g. from before a token was
    configured, so without the key) -- replaced, so the spoke stops posting to it."""
    return subscription != callback and subscription.split("&key=")[0] == callback.split("&key=")[0]


async def _ensure_event_subscription(spoke_id: str, payload: dict[str, Any]) -> None:
    """Subscribe this hub to the spoke's events if it is not already (never raises)."""
    subscriptions = payload.get("event_subscriptions")
    if not EVENT_PUSH_ENABLED or subscriptions is None:  # None: an older spoke without events
        return
    group = _active_spokes()
    try:
        callback = hub_callback_url(spoke_id, group.url_of(spoke_id))
    except ValueError:
        return
    stale = [url for url in subscriptions if _is_our_callback_for(url, spoke_id, callback)]
    if callback in subscriptions and not stale:
        return
    try:
        if callback not in subscriptions:
            await group.call_tool(spoke_id, "subscribe_command_events", {"url": callback}, timeout_s=_STATE_POLL_TIMEOUT_S)
            _logger.info("Subscribed to %s's events", spoke_id)
        for url in stale:
            await group.call_tool(spoke_id, "unsubscribe_command_events", {"url": url}, timeout_s=_STATE_POLL_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("Could not subscribe to %s's events: %s", spoke_id, exc)


async def _poll_one_state(spoke_id: str) -> None:
    """Ask one spoke for its state and remember the answer. Never raises: a spoke that cannot
    be reached is recorded as such (call_tool has already flagged the connection), and a spoke
    removed mid-poll is simply skipped."""
    group = _active_spokes()
    try:
        try:
            result = await group.call_tool(spoke_id, _STATE_TOOL, None, timeout_s=_STATE_POLL_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            group.record_state(spoke_id, None, error=str(exc))
            return
        payload = _unwrap_call_tool_result(result)
        if payload.get("state") in ("idle", "running", "error"):
            group.record_state(spoke_id, payload)
            await _ensure_event_subscription(spoke_id, payload)
        else:
            group.record_state(
                spoke_id,
                None,
                error=payload.get("message") or "The spoke did not report a state (an older spoke without script runs?).",
            )
    except ValueError:
        return  # the spoke was removed while we were asking it


async def poll_spoke_states() -> None:
    """Refresh every spoke's state, concurrently."""
    group = _active_spokes()
    await asyncio.gather(*(_poll_one_state(spoke_id) for spoke_id in group.ids))


async def run_state_poller(interval_s: float = STATE_POLL_INTERVAL_S) -> None:
    """Background loop keeping each spoke's state fresh (started by __main__)."""
    while True:
        try:
            await poll_spoke_states()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - one bad round must not end the loop
            _logger.exception("Spoke state poll failed")
        await asyncio.sleep(interval_s)


@mcp.tool()
async def list_spokes() -> list[dict[str, Any]]:
    """List every configured spoke: connection status plus what each is doing -- ``state`` is
    ``idle``, ``running`` (a script is active), ``error`` (a human is needed: a run is waiting on
    an operator's decision, or the last run failed and has not been acknowledged),
    ``unreachable`` or ``unknown``. State comes from each spoke's own get_spoke_state, refreshed
    every few seconds; call get_fleet_status for a fresh read."""
    return _active_spokes().status()


@mcp.tool()
async def get_fleet_status(refresh: bool = True) -> dict[str, Any]:
    """One call for the whole fleet: every spoke's state (idle / running / error / unreachable /
    unknown), a count of each, and every prompt currently waiting for a human operator.

    Args:
        refresh: Ask every spoke right now (default) instead of using the last background poll.
    """
    if refresh:
        await poll_spoke_states()
    group = _active_spokes()
    spokes = group.status()
    counts = {label: 0 for label in STATE_LABELS}
    for spoke in spokes:
        counts[spoke["state"]] += 1
    return {
        "spokes": spokes,
        "counts": counts,
        "pending_interventions": group.pending_interventions(),
        "command_holds": group.command_holds(),
        "polled_at": time.time(),
    }


@mcp.tool()
async def list_pending_interventions(refresh: bool = True) -> list[dict[str, Any]]:
    """Every run across the fleet that is waiting for a human operator: which spoke and script,
    what went wrong, and the options that can be chosen. Tell the user about these; they answer
    on the hub dashboard (/dashboard) or the spoke's operator page. An agent cannot answer them.

    Args:
        refresh: Ask every spoke right now (default) instead of using the last background poll.
    """
    if refresh:
        await poll_spoke_states()
    return _active_spokes().pending_interventions()


_ERROR_KINDS = ("error", "held", "operator_prompt")


@mcp.tool()
def get_spoke_errors(
    spoke_id: str, since: float | None = None, kind: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """The instrument errors a spoke has reported, newest first, kept by the hub even after the
    instrument recovered: failed commands (kind "error", including ones that were not held), held
    steps ("held") and operator prompts ("operator_prompt", with resolved_at/resolved_action once
    answered). Each has at, session_id, step, command, error_type and message (prompts: code,
    error_uuid and actions). Read from the hub's memory, so nothing is sent to the spoke; the
    last 200 per spoke are kept until the hub restarts. To catch up after being away, pass the
    "at" of the newest record you already have as since.

    Args:
        spoke_id: The spoke to read.
        since: Only records after this epoch time (seconds).
        kind: Only "error", "held" or "operator_prompt".
        limit: At most this many records (default 50).
    """
    if kind is not None and kind not in _ERROR_KINDS:
        raise ValueError(f"kind must be one of {', '.join(_ERROR_KINDS)}")
    return _active_spokes().error_history(spoke_id, since=since, kind=kind, limit=limit)


@mcp.tool()
async def list_command_holds(refresh: bool = True) -> list[dict[str, Any]]:
    """Every spoke whose command stream is held: a call_sdk_command step that failed with an
    error answered as Cancel (with hold_on_error on), or one held by stop_commands. Each entry
    has spoke_id, the held step, its command, reason ("error"/"stop"), error_type, message and
    since. Nothing here is answered on the dashboard: recover with call_sdk_command(...,
    recovery=True) on that spoke, then resume_commands / resume_commands_from /
    release_command_hold (via call_tool_on). To be woken by a hold instead of polling, use the
    spoke's own wait_for_command_event or subscribe_command_events.

    Args:
        refresh: Ask every spoke right now (default) instead of using the last background poll.
    """
    if refresh:
        await poll_spoke_states()
    return _active_spokes().command_holds()


async def _fleet_consumables(
    kind: str | None, spoke_ids: list[str] | None, call_timeout_s: float
) -> dict[str, Any]:
    """Fan get_consumables_levels out to every targeted spoke and merge the rows into one list,
    each tagged with which spoke it's on. One spoke's failure (offline, tool-level error, timeout)
    never hides the others -- same isolation as broadcast_tool_call, just pre-merged since the
    whole point here is one fleet-wide view rather than one entry per spoke to page through."""
    targets = spoke_ids if spoke_ids is not None else _active_spokes().ids
    arguments = {"kind": kind} if kind else None
    payloads = await asyncio.gather(
        *(_shared_hub_call(spoke_id, "get_consumables_levels", arguments, call_timeout_s) for spoke_id in targets)
    )
    items: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for spoke_id, payload in zip(targets, payloads, strict=True):
        if payload.get("status") == "error":
            errors[spoke_id] = str(payload.get("message") or "unknown error")
            continue
        rows = payload.get("result")
        if not isinstance(rows, list):
            errors[spoke_id] = "get_consumables_levels did not return a list (older spoke?)"
            continue
        for row in rows:
            items.append({"spoke_id": spoke_id, **row})
    return {
        "items": items,
        "low_items": [i for i in items if i.get("low")],
        "errors": errors,
        "polled_at": time.time(),
    }


@mcp.tool()
async def get_fleet_consumables(
    kind: str | None = None, spoke_ids: list[str] | None = None, call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S
) -> dict[str, Any]:
    """Every configured spoke's current consumable levels (tips, reagents, ...), merged into one
    fleet-wide view -- each row carries its own spoke_id so you can tell which instrument it's on.
    ``low_items`` is the same list pre-filtered to just what's below its configured threshold, the
    fleet-wide equivalent of a single spoke's list_low_consumables. A spoke that's offline or
    errors is reported in ``errors`` (keyed by spoke_id) rather than failing the whole call or
    silently dropping that spoke's rows.

    Args:
        kind: Filter to one consumable kind ("tip"/"reagent"/...), or omit for everything.
        spoke_ids: Which spokes to include; omit for every configured spoke (see list_spokes).
        call_timeout_s: Per-spoke timeout; see call_tool_on.
    """
    return await _fleet_consumables(kind, spoke_ids, call_timeout_s)


@mcp.tool()
async def add_spoke(spoke_id: str, url: str) -> dict[str, Any]:
    """Register a new spoke at runtime and probe it immediately -- no hub restart needed.
    Persisted to spokes.json, so it's still here on the hub's next restart -- unless
    spoke_id is also listed in HAMILTON_MCP_SPOKES, which always wins on a conflict.

    Args:
        spoke_id: Unique id for the new spoke (used in list_spokes/call_tool_on/
            broadcast_tool_call). Must not already be in use.
        url: The spoke's streamable-http endpoint, e.g. http://192.168.1.13:8000/mcp.
            See discover_spokes to find one instead of typing it by hand.
    """
    await _active_spokes().add_spoke(spoke_id, url)
    return next(s for s in _active_spokes().status() if s["id"] == spoke_id)


@mcp.tool()
async def remove_spoke(spoke_id: str) -> dict[str, Any]:
    """Drop a spoke at runtime -- no hub restart needed. Persisted: it stays gone on the
    hub's next restart too, unless it's listed in HAMILTON_MCP_SPOKES.
    """
    _active_spokes().remove_spoke(spoke_id)
    return {"removed": spoke_id}


async def _discover_spokes() -> list[dict[str, Any]]:
    """Shared by discover_spokes (tool) and GET /api/spokes/discover."""
    found = await discovery.scan()
    known_urls = {s["url"] for s in _active_spokes().status()}
    return [{"url": d.url, "name": d.name} for d in found if d.url not in known_urls]


@mcp.tool()
async def discover_spokes() -> list[dict[str, Any]]:
    """Scan this network (and this computer, on other ports) for hamilton_venus_mcp spokes
    not already connected to this hub. Takes a few seconds. Pass a result's url straight to
    add_spoke (any id you like -- the returned name is just a suggestion, the spoke's own
    HAMILTON_MCP_SPOKE_NAME).
    """
    return await _discover_spokes()


@mcp.tool()
async def call_tool_on(
    spoke_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S,
) -> dict[str, Any]:
    """Call any tool on exactly one spoke's own hamilton_venus_mcp server by id.

    Works uniformly for session lifecycle and SDK-command tools alike -- e.g.
    tool_name="start_session", arguments={"simulate": True}, or
    tool_name="call_sdk_command", arguments={"name": "odtc_get_temperature"}. See
    list_spokes for valid spoke_id values.

    Args:
        call_timeout_s: How long to wait for this one spoke before giving up and reporting
            it as an error (a dead spoke can otherwise hang indefinitely rather than fail
            fast). Raise this above its default for a tool that's meant to run long, e.g.
            poll_sdk_command_until with a large timeout_s of its own -- give it headroom
            above that tool's own internal timeout so this one doesn't fire first.
    """
    return await _dispatch_hub_call(spoke_id, tool_name, arguments, call_timeout_s)


@mcp.tool()
async def broadcast_tool_call(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    spoke_ids: list[str] | None = None,
    call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S,
) -> dict[str, dict[str, Any]]:
    """Call the same tool on every targeted spoke concurrently and compile the results into
    one dict keyed by spoke id -- e.g. broadcast_tool_call("call_sdk_command", {"name":
    "odtc_get_temperature"}) to read every STAR's ODTC in one round trip instead of one
    call_tool_on per spoke. One spoke failing (offline, tool-level error, or timing out
    past call_timeout_s) never fails or blocks the others -- its entry just carries
    status="error" instead.

    Args:
        tool_name: Tool to call on each targeted spoke.
        arguments: Arguments to pass to that tool on every spoke.
        spoke_ids: Which spokes to target; omit for every configured spoke (see list_spokes).
        call_timeout_s: Per-spoke timeout; see call_tool_on.
    """
    targets = spoke_ids if spoke_ids is not None else _active_spokes().ids
    results = await asyncio.gather(
        *(_dispatch_hub_call(spoke_id, tool_name, arguments, call_timeout_s) for spoke_id in targets)
    )
    return dict(zip(targets, results, strict=True))


@mcp.tool()
async def list_resources_on(spoke_id: str, call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S) -> dict[str, Any]:
    """List the MCP resources exposed by exactly one spoke's own hamilton_venus_mcp server --
    e.g. its "docs://hamilton-venus/getting-started" reference guide. Resources are a
    separate MCP capability from tools (see call_tool_on) -- static or semi-static reference
    content a client can pull on demand, as opposed to an action the server performs.

    Args:
        call_timeout_s: See call_tool_on.
    """
    started = time.monotonic()
    try:
        result = await _active_spokes().list_resources(spoke_id, timeout_s=call_timeout_s)
        payload: dict[str, Any] = {"status": "success", "resources": _unwrap_list_resources_result(result)}
        status = "success"
    except Exception as exc:  # noqa: BLE001 - reported as an error envelope, not raised
        payload = {"status": "error", "message": str(exc)}
        status = "error"
    latency_ms = (time.monotonic() - started) * 1000
    _record_activity(spoke_id, "list_resources", status, latency_ms)
    payload.setdefault("timestamp", time.time())
    return payload


@mcp.tool()
async def read_resource_on(spoke_id: str, uri: str, call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S) -> dict[str, Any]:
    """Read one MCP resource from exactly one spoke's own hamilton_venus_mcp server by uri --
    e.g. uri="docs://hamilton-venus/getting-started" for that spoke's full reference guide
    (session lifecycle, deck layout options, positions selector DSL, ...). Use
    list_resources_on first if you don't already know a spoke's resource uris.

    Args:
        call_timeout_s: See call_tool_on.
    """
    started = time.monotonic()
    try:
        result = await _active_spokes().read_resource(spoke_id, uri, timeout_s=call_timeout_s)
        payload = _unwrap_read_resource_result(result)
        status = payload["status"]
    except Exception as exc:  # noqa: BLE001 - reported as an error envelope, not raised
        payload = {"status": "error", "message": str(exc)}
        status = "error"
    latency_ms = (time.monotonic() - started) * 1000
    _record_activity(spoke_id, "read_resource", status, latency_ms)
    payload.setdefault("timestamp", time.time())
    return payload


@mcp.custom_route("/dashboard", methods=["GET"])
async def dashboard(_request: Request) -> Response:
    return _html_page(_DASHBOARD_HTML_PATH)


@mcp.custom_route("/static/{path:path}", methods=["GET"])
async def static_asset(request: Request) -> Response:
    """Shared CSS/JS/images for the dashboard pages (hub.css, hub.js, img/logo*.png) -- plain
    file serving, no build step. Resolves under _STATIC_DIR and refuses anything that escapes
    it (e.g. "../../..") rather than trusting the path param.
    """
    requested = (_STATIC_DIR / request.path_params["path"]).resolve()
    if _STATIC_DIR not in requested.parents or not requested.is_file():
        return JSONResponse({"error": "Not found"}, status_code=404)
    return FileResponse(requested, headers=_NO_CACHE)


@mcp.custom_route("/spokes/{spoke_id}", methods=["GET"])
async def instrument_page(_request: Request) -> Response:
    """Per-instrument detail page -- one static template for every spoke_id; the page itself
    reads the id from the URL and fetches /api/spokes/{spoke_id}/detail.json."""
    return _html_page(_INSTRUMENT_HTML_PATH)


@mcp.custom_route("/api/spokes/{spoke_id}/events.json", methods=["GET"])
async def spoke_events_json(request: Request) -> Response:
    """The hub's record of one spoke's instrument errors (see the get_spoke_errors tool), for
    scripts and the dashboard. Query: since (epoch seconds), kind (error | held |
    operator_prompt), limit (default 200). Served from hub memory, so it is cheap to poll."""
    spoke_id = request.path_params["spoke_id"]
    params = request.query_params
    kind = params.get("kind") or None
    if kind is not None and kind not in _ERROR_KINDS:
        return JSONResponse({"error": f"kind must be one of {', '.join(_ERROR_KINDS)}"}, status_code=400)
    try:
        since = float(params["since"]) if params.get("since") else None
        limit = int(params.get("limit") or 200)
    except ValueError:
        return JSONResponse({"error": "since must be a number and limit an integer."}, status_code=400)
    try:
        events = _active_spokes().error_history(spoke_id, since=since, kind=kind, limit=limit)
    except ValueError:
        return JSONResponse({"error": f"Unknown spoke_id {spoke_id!r}"}, status_code=404)
    return JSONResponse({"spoke_id": spoke_id, "events": events, "polled_at": time.time()})


@mcp.custom_route("/api/spokes/{spoke_id}/detail.json", methods=["GET"])
async def spoke_detail_json(request: Request) -> Response:
    """Everything the per-instrument page needs about one spoke: its fleet-state row (from the
    background poll) plus live reads of its current/last run, run history, and consumables
    levels -- fetched fresh on every call rather than cached, since a person is looking at this
    one spoke specifically. A spoke tool call that fails (unreachable, or nothing to report yet,
    e.g. "no run has happened yet") comes back as its own {"status": "error", "message": ...}
    entry rather than failing the whole response -- see _dispatch_hub_call.
    """
    spoke_id = request.path_params["spoke_id"]
    fleet_row = next((s for s in _active_spokes().status() if s["id"] == spoke_id), None)
    if fleet_row is None:
        return JSONResponse({"error": f"Unknown spoke_id {spoke_id!r}"}, status_code=404)
    run, runs, levels, low = await asyncio.gather(
        _shared_hub_call(spoke_id, "get_run", None, DEFAULT_CALL_TIMEOUT_S),
        _shared_hub_call(spoke_id, "list_runs", {"limit": 25}, DEFAULT_CALL_TIMEOUT_S),
        _shared_hub_call(spoke_id, "get_consumables_levels", None, DEFAULT_CALL_TIMEOUT_S),
        _shared_hub_call(spoke_id, "list_low_consumables", None, DEFAULT_CALL_TIMEOUT_S),
    )
    return JSONResponse(
        {
            "spoke": fleet_row,
            "errors": _active_spokes().error_history(spoke_id, limit=100),
            "run": run,
            "runs": runs,
            "consumables": {"levels": levels, "low": low},
            "polled_at": time.time(),
        }
    )


@mcp.custom_route("/api/spokes/{spoke_id}/runs/{run_id}/detail.json", methods=["GET"])
async def spoke_run_detail_json(request: Request) -> Response:
    """One run's full picture, for the per-instrument page's run-history drill-down: its live
    state (tips/reagents/labware/error, from get_run), its finished-run summary (result,
    duration, tips/plates used, failed steps -- from get_run_summary, available once the run has
    finished and its SDK run log was found), and its recent event trace (from get_run_events).
    Each of the three is fetched and isolated independently (see _dispatch_hub_call) -- a run
    still in progress has no summary yet, and an old run the spoke has since pruned from memory
    (get_run_events only serves in-memory runs -- see RunManager.get_events) has no event trace,
    but neither failure should hide the other two.
    """
    spoke_id = request.path_params["spoke_id"]
    run_id = request.path_params["run_id"]
    fleet_row = next((s for s in _active_spokes().status() if s["id"] == spoke_id), None)
    if fleet_row is None:
        return JSONResponse({"error": f"Unknown spoke_id {spoke_id!r}"}, status_code=404)
    run, summary, events = await asyncio.gather(
        _dispatch_hub_call(spoke_id, "get_run", {"run_id": run_id}, DEFAULT_CALL_TIMEOUT_S),
        _dispatch_hub_call(spoke_id, "get_run_summary", {"run_id": run_id}, DEFAULT_CALL_TIMEOUT_S),
        _all_run_events(spoke_id, run_id),
    )
    return JSONResponse({"run": run, "summary": summary, "events": events, "polled_at": time.time()})


# Several browser tabs (or an AI client) polling the same spoke should cost the spoke one call, not
# one each: identical read-only calls made by the pages within this window share a single result.
_UI_CACHE_TTL_S = 2.5
_ui_cache: dict[tuple[str, str, str], tuple[float, "asyncio.Future[dict[str, Any]]"]] = {}


async def _shared_hub_call(spoke_id: str, tool_name: str, arguments: dict[str, Any] | None, call_timeout_s: float) -> dict[str, Any]:
    """_dispatch_hub_call for the pages' read-only polls, coalescing concurrent and just-repeated
    identical calls (see _UI_CACHE_TTL_S). Not for anything that changes state."""
    if _UI_CACHE_TTL_S <= 0:
        return await _dispatch_hub_call(spoke_id, tool_name, arguments, call_timeout_s)
    key = (spoke_id, tool_name, json.dumps(arguments, sort_keys=True, default=str))
    now = time.monotonic()
    entry = _ui_cache.get(key)
    if entry is not None and (not entry[1].done() or now - entry[0] < _UI_CACHE_TTL_S):
        return dict(await asyncio.shield(entry[1]))
    task = asyncio.ensure_future(_dispatch_hub_call(spoke_id, tool_name, arguments, call_timeout_s))
    _ui_cache[key] = (now, task)
    if len(_ui_cache) > 200:
        for stale in [k for k, (t, f) in _ui_cache.items() if f.done() and now - t > _UI_CACHE_TTL_S]:
            _ui_cache.pop(stale, None)
    return dict(await asyncio.shield(task))


_RUN_EVENTS_PAGE = 1000  # the spoke's own per-call cap
_RUN_EVENTS_MAX_PAGES = 5  # the spoke keeps at most 5000 events per run anyway


async def _all_run_events(spoke_id: str, run_id: str) -> dict[str, Any]:
    """Every saved event of one run, fetched page by page (a spoke returns at most 1000 per
    call). An error from the first page is returned as-is so the caller can show why there is
    no trace; an error on a later page just ends the list there."""
    merged: dict[str, Any] | None = None
    since = 0
    for _ in range(_RUN_EVENTS_MAX_PAGES):
        page = await _dispatch_hub_call(
            spoke_id, "get_run_events", {"run_id": run_id, "since_seq": since, "max_items": _RUN_EVENTS_PAGE}, DEFAULT_CALL_TIMEOUT_S
        )
        if not isinstance(page.get("events"), list):
            return merged if merged is not None else page
        if merged is None:
            merged = {**page, "events": list(page["events"])}
        else:
            merged["events"].extend(page["events"])
            merged["next_since_seq"] = page.get("next_since_seq", merged.get("next_since_seq"))
        nxt = page.get("next_since_seq")
        if len(page["events"]) < _RUN_EVENTS_PAGE or not isinstance(nxt, int) or nxt <= since:
            break
        since = nxt
    return merged or {}


_CURRENT_RUN_EVENTS_WAIT_S = 3.0


@mcp.custom_route("/api/spokes/{spoke_id}/current-run/events.json", methods=["GET"])
async def spoke_current_run_events_json(request: Request) -> Response:
    """Live trace feed for whichever run is currently active on this spoke (or its most recent
    one, if none is active -- same run_id=None convention as get_run/get_run_events). The
    instrument page polls this with ?since_seq=<next_since_seq from the last call> to tail the
    trace incrementally, the same cursor pattern used for a single run's own event stream --
    just always pointed at "whatever is running right now" rather than one fixed run_id. Blocks
    briefly (get_run_events' own wait_s) so a tight poll loop here is still reasonably immediate
    without hammering the spoke on every tick.
    """
    spoke_id = request.path_params["spoke_id"]
    fleet_row = next((s for s in _active_spokes().status() if s["id"] == spoke_id), None)
    if fleet_row is None:
        return JSONResponse({"error": f"Unknown spoke_id {spoke_id!r}"}, status_code=404)
    try:
        since_seq = int(request.query_params.get("since_seq", "0"))
    except ValueError:
        since_seq = 0
    events = await _dispatch_hub_call(
        spoke_id,
        "get_run_events",
        {"run_id": None, "since_seq": since_seq, "max_items": 200, "wait_s": _CURRENT_RUN_EVENTS_WAIT_S},
        DEFAULT_CALL_TIMEOUT_S,
    )
    return JSONResponse({"events": events, "polled_at": time.time()})


@mcp.custom_route(_SPOKE_EVENTS_PATH, methods=["POST"])
async def spoke_events(request: Request) -> Response:
    """Where spokes push their events (subscribe_command_events). A status change is shown at
    once; anything else (a hold, resume, release) also triggers a fresh poll of that spoke so
    the dashboard's hold details catch up immediately instead of on the next poll."""
    spoke_id = request.query_params.get("spoke_id", "")
    expected_key = callback_key(spoke_id)
    if expected_key is not None and not hmac.compare_digest(
        request.query_params.get("key", "").encode(), expected_key.encode()
    ):
        return JSONResponse({"error": "Missing or wrong key for this spoke's event callback."}, status_code=403)
    try:
        event = await request.json()
    except ValueError:
        return JSONResponse({"error": "Expected a JSON body."}, status_code=400)
    if not isinstance(event, dict):
        return JSONResponse({"error": "Expected a JSON object."}, status_code=400)
    try:
        _active_spokes().apply_pushed_event(spoke_id, event)
    except ValueError:
        return JSONResponse({"error": f"Unknown spoke_id {spoke_id!r}"}, status_code=404)
    if event.get("kind") != "status":
        task = asyncio.create_task(_poll_one_state(spoke_id))
        _push_refreshes.add(task)
        task.add_done_callback(_push_refreshes.discard)
    return JSONResponse({"ok": True})


_push_refreshes: set[asyncio.Task[Any]] = set()


@mcp.custom_route("/api/status.json", methods=["GET"])
async def status_json(_request: Request) -> Response:
    return JSONResponse(
        {
            "hub": {
                "started_at": _hub_started_at,
                "uptime_s": time.time() - _hub_started_at,
                "operator_gate_configured": bool(os.environ.get(_OPERATOR_TOKEN_ENV, "").strip()),
            },
            "spokes": _active_spokes().status(),
            "pending_interventions": _active_spokes().pending_interventions(),
            "command_holds": _active_spokes().command_holds(),
            "recent_activity": list(_activity),
        }
    )


@mcp.custom_route("/api/fleet-consumables.json", methods=["GET"])
async def fleet_consumables_json(_request: Request) -> Response:
    """Dashboard-facing counterpart to the get_fleet_consumables tool -- the fleet-wide low-stock
    list the dashboard's "Low consumables" card polls."""
    return JSONResponse(await _fleet_consumables(None, None, DEFAULT_CALL_TIMEOUT_S))


@mcp.custom_route("/api/interventions/resolve", methods=["POST"])
async def resolve_intervention_route(request: Request) -> Response:
    """Dashboard-facing: a person's answer to a spoke's pending prompt. The hub passes it on to
    that spoke's operator_resolve_prompt with the operator token from the hub's own environment
    -- the token is never sent to, or accepted from, an MCP client, so an agent using this hub
    cannot answer a prompt; a person at the dashboard can."""
    token = os.environ.get(_OPERATOR_TOKEN_ENV, "").strip()
    if not token:
        return JSONResponse(
            {"error": f"{_OPERATOR_TOKEN_ENV} is not set on the hub, so it cannot answer prompts for spokes."},
            status_code=503,
        )
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "Send a JSON body."}, status_code=400)
    channel_actions = body.get("channel_actions") if isinstance(body, dict) else None
    if (
        not isinstance(body, dict)
        or not all(body.get(k) for k in ("spoke_id", "run_id", "prompt_id"))
        or not (body.get("action") or channel_actions)
    ):
        return JSONResponse(
            {"error": "spoke_id, run_id, prompt_id and either action or channel_actions are required."},
            status_code=400,
        )
    if channel_actions is not None and not isinstance(channel_actions, dict):
        return JSONResponse({"error": "channel_actions must map an error detail id to an action id."}, status_code=400)
    operator = str(body["operator"])[:80] if body.get("operator") else None
    arguments: dict[str, Any] = {
        "run_id": str(body["run_id"]),
        "prompt_id": str(body["prompt_id"]),
        "operator": operator or "hub dashboard",
        "token": token,
    }
    if channel_actions:
        arguments["channel_actions"] = channel_actions
    else:
        arguments["action"] = str(body["action"])
    payload = await _dispatch_hub_call(str(body["spoke_id"]), "operator_resolve_prompt", arguments, _RESOLVE_TIMEOUT_S)
    with contextlib.suppress(Exception):
        await _poll_one_state(str(body["spoke_id"]))
    if payload.get("status") == "error" or not payload.get("resolved"):
        message = str(payload.get("message") or "The spoke refused that answer.")
        return JSONResponse({"error": message.replace(token, "***")}, status_code=400)
    return JSONResponse({"ok": True, **payload})


@mcp.custom_route("/api/spokes", methods=["POST"])
async def add_spoke_route(request: Request) -> Response:
    """Dashboard-facing counterpart to the add_spoke tool -- same persisted semantics."""
    body = await request.json()
    spoke_id = str(body.get("id", "")).strip()
    url = str(body.get("url", "")).strip()
    if not spoke_id or not url:
        return JSONResponse({"error": "id and url are both required"}, status_code=400)
    try:
        await _active_spokes().add_spoke(spoke_id, url)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True})


@mcp.custom_route("/api/spokes/{spoke_id}", methods=["DELETE"])
async def remove_spoke_route(request: Request) -> Response:
    """Dashboard-facing counterpart to the remove_spoke tool -- same persisted semantics."""
    spoke_id = request.path_params["spoke_id"]
    try:
        _active_spokes().remove_spoke(spoke_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"ok": True})


@mcp.custom_route("/api/spokes/discover", methods=["GET"])
async def discover_spokes_route(_request: Request) -> Response:
    """Dashboard-facing counterpart to the discover_spokes tool."""
    return JSONResponse({"spokes": await _discover_spokes()})
