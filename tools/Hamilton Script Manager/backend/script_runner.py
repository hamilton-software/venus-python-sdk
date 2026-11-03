"""Runs a stored, read-only script shortcut as a standalone subprocess.

This generalizes demo_app's ScriptRunner (demo_app/backend/script_runner.py),
which runs pasted source text once and reports the currently-executing line
via a sys.settrace-based `\\x00LINE\\x00<n>` sentinel printed to stdout. This
version instead runs an existing file on disk (a shortcut's read-only copy)
and adds four things demo_app's script tab doesn't need:

1. Syncing VENUS's own system-wide simulation mode (GET/PUT
   /api/vector/v3/system/configuration/simulation against the local Vector
   API) to match the run's toggle -- this is what actually decides whether a
   real or simulated instrument answers. StarClient(simulate=...) (see #2) is
   a separate, per-method-execution setting that does NOT choose the device.
2. Forcing the global simulate/live toggle -- plus always-on DEBUG-level SDK
   logging, VENUS trace logging, and structured run-log capture -- into
   whatever `StarClient(...)` OR `VantageClient(...)` call the stored script
   makes, without editing the script's text. `simulate` is a constructor-only
   kwarg on both classes (hamilton_venus/star_client.py,
   hamilton_venus/vantage_client.py), so this patches both classes'
   `__init__`/`__enter__` inside the subprocess bootstrap to force it --
   whichever one the script actually constructs picks it up; the patch on
   the other class is simply unused.
3. A pause/resume control channel (parent writes PAUSE/RESUME lines to the
   child's stdin) that suspends the script at the next line boundary --
   i.e. only once the in-flight statement/instrument call has fully
   finished -- and unlocks/locks the instrument's front cover around the
   suspension, mirroring sample_transfer_app's
   on_pause/on_resume -> front_cover_unlock/lock() pattern
   (sample_transfer_app/backend/routes_ws.py) but keyed off source lines
   instead of a step list.
4. Reporting the finalized SDK run-log file path once the run ends, so the
   UI can offer it for download ("Export Log").
5. Reporting which line of the script actually failed, via a `\\x00ERRLINE\\x00<n>`
   sentinel -- distinct from the ordinary `\\x00LINE\\x00<n>` "currently
   executing" one, because by the time a run ends in error the script's own
   except block has usually run several more lines (logging the error,
   `raise SystemExit(1) from e`, etc.), so the *last* traced line is that
   cleanup code, not the call that actually failed.
6. Live operator-error escalation: registers `StarClient(on_operator_error_escalation=...)`
   so a hardware error that exhausts the SDK's automatic recovery profile
   blocks and asks a human, instead of silently deferring to VENUS's own
   on-console dialog (which has no console to appear on here) or auto-aborting.
   The callback runs on the SDK's own escalation worker thread (see
   hamilton_venus._internal._operator_escalation_bridge), not this bootstrap's
   main thread, so blocking on a threading.Event while waiting for the parent's
   answer is safe -- it doesn't stall the line-trace/pause machinery above.
   Started as a straight port of hamilton_workflow_framework.session.
   WorkflowSession's own `_handle_operator_escalation`/`resolve_operator_prompt`,
   but now goes further: each affected channel gets its own server-advertised
   recovery-action choices (id/name pairs, plus VENUS's own suggested default)
   rather than one action applied to every channel uniformly, so the UI can
   offer a per-channel dropdown -- the SDK's "advanced" ErrorRecovery path
   (_error_profile_resolver.py's `isinstance(selected_action, ErrorRecovery)`
   branch), which neither WorkflowSession nor its demo_app-shared modal uses.
   Round-trips through this subprocess's stdio instead of an in-process
   concurrent.futures.Future: `\\x00PROMPT\\x00<json>` out over stdout, one of
   two shapes back in over stdin -- `PROMPT_RESPONSE <uuid> ACTION <name>` for
   a uniform Abort/Cancel-style pick, or `PROMPT_RESPONSE <uuid> CHANNELS
   <json>` (detail_uuid -> chosen action id) for independent per-channel picks.
7. Live tip/reagent consumables tracking: monkey-patches `tip_pickup`/
   `tip_pickup_5ml`/`tip_pick_up_mph96`/`tip_pick_up_mph96_partial` and
   `aspirate`/`aspirate_5ml`/`aspirate_mph96` on whichever client class the
   script constructs (same technique as #2's `__init__`/`__enter__` patch),
   since this app has no per-step hook to observe SDK calls through the way
   hamilton_workflow_framework's StepObserver does. Tip pickups are checked
   for availability *before* calling through (pausing with a "reload tips"
   prompt if short -- see `_ensure_tip_availability`) and read VENUS's own
   `remainingTips` off the real response afterward; aspirates read the
   per-channel (or, for MPH96, single) measured `liquid_level_mm`/
   `liquid_volume_ul` afterward to update a tracked reservoir's percent-full.
   Streams to the parent the same sentinel-marker way as the rest of this
   file (`_CONSUMABLE_MARKER` and friends), and reuses the exact
   `threading.Event` + stdin-line round-trip pattern #6 already established
   for its own new "reload tips" prompt kind. Also registers
   `StarClient`/`VantageClient(on_tip_reload_prompt=...)` (`_make_tip_reload_prompt`)
   so compound commands' own upfront tip-shortage check
   (`hamilton_venus.compound_commands._helpers._tip_manager.
   ensure_tips_available`, run once before any pickups for the whole
   operation) shows the same reload prompt instead of raising an unhandled
   `ValueError` -- both paths share `_run_tip_reload_prompt_cycle`.
8. Live "Sample Tracking" well-level tracking: a second, separate live-telemetry
   layer alongside #7 -- monkey-patches `aspirate`/`aspirate_5ml`/`dispense`/
   `dispense_5ml` (binding against each method's real `_aspirate_impl`/
   `_dispense_impl` signature, same technique as #7), `aspirate_mph96`/
   `dispense_mph96`, and `dispense_on_the_fly`/`dispense_on_the_fly_5ml` (which
   dispenses one uniform volume into every well of a labware except whatever's
   listed in its own `excluded_positions` arg, rather than an explicit
   `positions` selector), on top of whatever #7 has already patched. Unlike #7
   (reservoir-class labware only, pooled per-labware), this tracks EVERY
   well touched by an aspirate or dispense, individually, generically -- EXCEPT
   dispensing INTO a reservoir, which is deliberately never tracked here (a
   refill, not "delivering to a sample" -- see `_record_sample_event`'s early
   return). A labware only becomes visible to the UI once it has received >= 1
   (non-reservoir) dispense ("target") -- see `_record_sample_event`/
   `_announce_sample_labware`; aspirates from it before then are held
   (`_sample_pending_events`) and replayed at that point. Since the SDK has no aspirate<->dispense pairing
   of its own, a dispense's "source" is attributed via a per-channel "last
   aspirate source" heuristic (`_sample_channel_source`); a reservoir's several
   addressable sub-positions collapse to one shared source identity rather than
   fragmenting into near-duplicates (`_sample_source_position`), mirroring how
   #7 already pools a reservoir's sub-positions into one entry. One-way
   telemetry only (no round-trip, unlike #6/#7's reload-prompt flow) --
   streamed via `_SAMPLE_MARKER`/`_SAMPLE_LABWARE_INFO_MARKER`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from backend.consumables_store import ConsumablesStore
from backend.settings_store import SettingsStore

_logger = logging.getLogger("backend.script_runner")

SendFn = Callable[[dict[str, Any]], Awaitable[None]]

# Sentinels that can't collide with a script's own stdout output.
_LINE_MARKER = b"\x00LINE\x00"
_STATE_MARKER = b"\x00STATE\x00"
_ERR_LINE_MARKER = b"\x00ERRLINE\x00"
_PROMPT_MARKER = b"\x00PROMPT\x00"
_CONSUMABLE_MARKER = b"\x00CONSUMABLE\x00"
_CONSUMABLE_WARNING_MARKER = b"\x00CONSUMABLE_WARNING\x00"
_CONSUMABLE_RELOAD_MARKER = b"\x00CONSUMABLE_RELOAD\x00"
_CONSUMABLE_RELOAD_DONE_MARKER = b"\x00CONSUMABLE_RELOAD_DONE\x00"
_INPUT_REQUEST_MARKER = b"\x00INPUT_REQUEST\x00"
_TK_DIALOG_REQUEST_MARKER = b"\x00TK_DIALOG_REQUEST\x00"
_TK_FILEDIALOG_REQUEST_MARKER = b"\x00TK_FILEDIALOG_REQUEST\x00"
_SAMPLE_MARKER = b"\x00SAMPLE\x00"
_SAMPLE_LABWARE_INFO_MARKER = b"\x00SAMPLE_LABWARE_INFO\x00"
_TADM_MARKER = b"\x00TADM\x00"
_COMTRACE_MARKER = b"\x00COMTRACE\x00"
_SERIAL_MARKER = b"\x00SERIAL\x00"

# Raw SDK DEBUG log lines (forced on via kwargs["logging_level"] below) that are too
# high-volume/low-value for the terminal pane -- dropped entirely rather than shown.
_NOISY_LOG_SUBSTRINGS = (
    b"LabwareLoadedStateChanged raw payload",
    b"LabwarePositionStateChanged raw payload",
    b"_async_instrument_client: Progress:",
)

# asyncio's default StreamReader limit (64 KiB) is comfortably exceeded by a single
# VenusTrace line for a TADM-enabled aspirate/dispense -- venus_trace_logging (always on,
# see the module docstring's item 2) logs the instrument's full runtime trace text
# verbatim, and VENUS embeds the whole TADM curve (per-channel pressure/time samples for
# the operation) inline in that one trace line with no newline of its own. Raised well
# past any realistic single line (including a multi-channel TADM curve) so hitting the
# _stream() drain-and-continue fallback below is the rare case, not the norm.
_STREAM_READ_LIMIT = 8 * 1024 * 1024

# A run outlives the UI connection that started it (the Photino window can crash and be
# relaunched by the shell's supervisor mid-run), so every message a run sends is kept and
# replayed in order to whichever connection attaches next -- see ScriptRunner.attach().
# Capped so a very long run can't grow without bound; past the cap the oldest messages
# drop out (the run's opening messages are kept separately so a replay still starts the
# frontend's run view correctly).
_REPLAY_HISTORY_LIMIT = 20_000

# Prompt message type -> the field carrying the id its response is keyed by, so a replay
# can leave out prompts the operator already answered.
_PROMPT_ID_FIELDS = {
    "operator_prompt": "error_uuid",
    "consumable_reload_prompt": "reload_uuid",
    "user_input_request": "uuid",
    "tk_dialog_request": "uuid",
    "tk_filedialog_request": "uuid",
}

# How long Stop waits for the script to finish VENUS's terminate and its own
# shutdown before killing it. Generous: a terminate can run cleanup steps.
_STOP_CLEANUP_TIMEOUT_S = 300.0

# Substituted into the bootstrap via str.replace + repr(), same approach as
# demo_app/backend/script_runner.py's _TRACE_BOOTSTRAP_TEMPLATE.
_BOOTSTRAP_TEMPLATE = r'''
import builtins, inspect, json, logging, math, runpy, sys, threading, time, uuid as _uuid_module
import tkinter.messagebox as _tk_messagebox, tkinter.simpledialog as _tk_simpledialog, tkinter.filedialog as _tk_filedialog
from datetime import datetime as _datetime, timezone as _timezone

_SCRIPT_PATH = __SCRIPT_PATH_REPR__
_FORCED_SIMULATE = __SIMULATE_REPR__
_RUN_LOG_DIR = __RUN_LOG_DIR_REPR__
_INITIAL_TIP_THRESHOLDS = __TIP_THRESHOLDS_REPR__
_INITIAL_RESERVOIRS = __REGISTERED_RESERVOIRS_REPR__
_DEFAULT_TIP_THRESHOLD = __DEFAULT_TIP_THRESHOLD_REPR__
_RESERVOIR_WARNING_PERCENT = __RESERVOIR_WARNING_PERCENT_REPR__
_COM_TRACE_ENABLED = __COM_TRACE_ENABLED_REPR__
_COM_TRACE_DIR = __COM_TRACE_DIR_REPR__
_DEBUG_LOGGING_ENABLED = __DEBUG_LOGGING_ENABLED_REPR__

_pause_requested = threading.Event()
_resume_now = threading.Event()
_resume_now.set()
# Set by STOP: no more pause/resume handling or state reports for this run.
_stopping = threading.Event()
_captured_clients = []

# ids() of clients currently believed paused (per _make_runtime_status_callback
# below) -- guards against acting twice on a duplicate/retried NewRuntimeStatus
# event for the same transition.
_paused_clients = set()

# One-shot guard for the post-connect serial-number probe (see
# _patch_client_class). Set once the serial has been reported (or has failed
# to report) so a script that calls instrument_connect() more than once, or
# uses both a context manager and an explicit connect, only probes once.
_serial_number_reported = False

# COM-trace tail state (see _start_com_trace_tail). One-shot guard like
# _serial_number_reported; the Event stops the daemon pump at run end; the
# Lock serialises the pump thread against the final flush in the template's
# finally: (ComTraceTailer is not itself thread-safe).
_com_trace_started = False
_com_trace_stop = threading.Event()
_com_trace_tailer = None
_com_trace_lock = threading.Lock()

_VECTOR_API_BASE = "http://localhost:42400/api/vector/v3"
_VECTOR_API_HEADERS = {"accept": "text/plain; x-api-version=3.0"}

# Keyed by instrument-error uuid. Populated by _on_operator_escalation (called
# on the SDK's own escalation worker thread -- see
# hamilton_venus._internal._operator_escalation_bridge) and resolved by
# _control_reader (running on this bootstrap's stdin-reader thread) once a
# PROMPT_RESPONSE line arrives from the parent process. A plain dict + Event
# is enough here (unlike WorkflowSession's concurrent.futures.Future) because
# only one script -- and realistically one live escalation -- runs at a time.
_prompt_events = {}
_prompt_responses = {}

# Keyed by an input-request uuid (distinct from _prompt_events/_prompt_responses
# above, which are operator-error-escalation-specific). Populated by
# _input_via_manager (installed as builtins.input, so it runs on whichever thread
# the script itself calls input() from) and resolved by _control_reader once an
# INPUT_RESPONSE line arrives from the parent process.
_input_events = {}
_input_responses = {}

# Keyed by a tk-dialog-request uuid (distinct from _input_events/_input_responses
# above -- tkinter.messagebox/simpledialog calls have per-kind value types and
# cancel semantics that don't fit input()'s always-str contract). Populated by
# _tk_dialog_request (called from whichever patched messagebox/simpledialog
# function the script invokes) and resolved by _control_reader once a
# TK_DIALOG_RESPONSE line arrives from the parent process.
_tk_dialog_events = {}
_tk_dialog_responses = {}

# Keyed by a tk-filedialog-request uuid. Populated by _tk_filedialog_request
# (called from whichever patched tkinter.filedialog function the script
# invoked) and resolved by _control_reader once a TK_FILEDIALOG_RESPONSE line
# arrives. Kept separate from _tk_dialog_events/_tk_dialog_responses since
# the wire cancel signal is always null here too, but the FUNCTION RETURN
# VALUE the script actually sees on cancel is "" or () (real tkinter's own
# filedialog cancel convention -- verified via inspect.getsource -- unlike
# messagebox/simpledialog, which return None), coerced by the patched
# functions below rather than by this dict.
_tk_filedialog_events = {}
_tk_filedialog_responses = {}

# Consumables tracking state (see module docstring item 7). tip_pool -> {
# "current_count", "total_capacity", "low_threshold", "below_threshold"}.
# Seeded from this run's persisted per-pool thresholds; current_count/
# total_capacity start unknown (None) until the first pickup/pre-check on
# that pool -- deck contents can change between runs, so a prior run's counts
# are never carried forward, only the configured threshold is.
_tip_pools = {
    pool: {"current_count": None, "total_capacity": None, "low_threshold": cfg["low_threshold"], "below_threshold": False}
    for pool, cfg in _INITIAL_TIP_THRESHOLDS.items()
}

# Pools whose current_count is known to match VENUS's counter -- set whenever a
# count comes from VENUS (a getTipCounter query or a pickup's own remainingTips),
# cleared by anything that can change the counter without this bootstrap seeing
# the new value: a failed pickup, or the script's own tip_pool_* initialize/reset/
# set/show-counter calls. While a pool is trusted and its count covers a pickup,
# _ensure_tip_availability skips its getTipCounter query -- a full VENUS command
# that otherwise roughly doubled every tip pickup's time.
_trusted_tip_counts = set()

# "labware@well" -> {"labware", "well", "label", "source", "remaining_volume_ul",
# "total_volume_ul", "percent_full", "last_updated", "below_threshold"}. Seeded
# from this run's persisted explicit registrations; remaining_volume_ul/
# total_volume_ul/percent_full start unknown (None) until the first aspirate
# measures them, same reasoning as tip pool counts above. "below_threshold"
# mirrors the tip pool's own edge-trigger flag -- see _check_reservoir_threshold.
_reservoirs = {
    key: {
        "labware": cfg["labware"], "well": cfg["well"], "label": cfg["label"], "source": cfg["source"],
        "remaining_volume_ul": None, "total_volume_ul": None, "percent_full": None, "last_updated": None,
        "below_threshold": False,
    }
    for key, cfg in _INITIAL_RESERVOIRS.items()
}
_labware_definition_cache = {}
_container_volume_cache = {}
_reservoirs_persisted_this_run = set()
# Labware ids already written to the run log as reservoir-class (see
# _is_reservoir_labware) -- recorded once per labware per run, not once per
# aspirate.
_reservoir_labware_logged = set()

# Sample-tracking state (see module docstring item 8; "Sample Tracking" tab).
# Separate from _reservoirs above, which stays reservoir-only for the
# Consumables tab. Keyed by "labware@well" -- applies to EVERY labware/well
# touched by an aspirate or dispense, not just labware whose own definition
# says labwareClass == "reservoir". A labware only ever gets announced (and
# therefore rendered as a card) once it has received >= 1 dispense -- see
# _sample_target_labware/_record_sample_event -- but its ledger is still
# maintained before that, in case a later dispense elsewhere on it makes it
# a target.
_sample_well_volumes = {}
_sample_target_labware = set()
# labware -> sample_event payloads recorded while it was not yet a target
# (e.g. media aspirated from a plate before buffer is dispensed into it).
# Replayed, with their own timestamps, when the labware becomes a target, and
# never sent for labware that stays a pure source.
_sample_pending_events = {}
_sample_labware_announced = set()
# labware -> the sample_labware_info payload last sent for it (see
# _refresh_sample_labware_barcodes, which re-sends it when the barcode changes).
_sample_labware_payloads = {}

# Per-channel (int) or the literal string "MPH" (96-head) -> {"labware",
# "well", "transfer_id"} of the most recent successful aspirate on that
# channel. The SDK has no built-in aspirate<->dispense pairing (positions is a
# symmetric parameter on both calls; there's no transfer() method), so a
# dispense's "source" (and, for TADM, its paired aspirate curve -- see
# "source_transfer_id" on _record_sample_event) is attributed heuristically
# from whatever this channel last picked up.
_sample_channel_source = {}

# Monotonic id minted once per (call, channel) aspirate/dispense event -- lets
# the frontend pair a dispense's own TADM curve with its source aspirate's
# curve (via source_transfer_id below) without any timestamp-based guessing.
# Distinct from _sample_source_key, which identifies a *labware@well*
# location for coloring, not a single physical liquid-transfer event.
_sample_transfer_seq = 0


def _next_sample_transfer_id():
    global _sample_transfer_seq
    _sample_transfer_seq += 1
    return _sample_transfer_seq


# Stable "labware@well" -> palette-index assignment, in first-seen order --
# lets the frontend render a consistent color per distinct source across the
# whole run (well fills, breakdown swatches, and the legend all key off this).
_sample_source_color_index = {}

# Instrument errors answered while an aspirate/dispense call was in flight, one
# entry per (recovery submission, channel) -- see _patch_sample_error_capture.
# Appended from the SDK's event-loop thread while the script's own thread is
# blocked inside the call, so every read/write goes through the lock. The
# sample-tracking wrappers slice out whatever was appended during their call
# (_sample_errors_mark/_sample_errors_since) and attach it to each
# sample_event as "errors".
_sample_error_log = []
_sample_error_lock = threading.Lock()
# error uuid -> the ErrorData VENUS last published for it (names for the
# action ids a recovery submission carries).
_sample_error_seen = {}
# error uuids whose next recovery submission was chosen by the operator
# (set by _on_operator_escalation), not by the error profile.
_sample_operator_uuids = set()

# (carrier_labware_id, position) -> scanned barcode string, populated from
# autoload.loadCarrierBy* responses whenever scan_positions was set (see
# _patch_autoload_scan_tracking). "position" is 1-based-as-a-string, matching
# VENUS's own barcodeReturns[].position. For a sample tube rack scanned AS
# the carrier, carrier_labware_id == the rack's own labware id and position
# == a tube's well number directly (see _resolve_well_barcode). For a plate
# carrier, carrier_labware_id == the CARRIER's labware id and position == a
# SITE on it -- resolving a plate's own barcode needs _labware_carrier_site
# below to find which site it occupies (see _resolve_labware_barcode).
_carrier_site_barcodes = {}

# labware_id -> (carrier_labware_id, site), populated whenever a plate/
# reservoir/lidded-plate is added to a carrier site (see
# _patch_labware_site_tracking). Only meaningful for barcode resolution --
# nothing else in this module needs "what carrier/site is this labware at".
_labware_carrier_site = {}

# Barcodes the script assigned itself with set_barcodes() (see
# _record_assigned_barcodes): labware_id -> barcode, and (labware_id, well) ->
# barcode. An assigned barcode replaces a scanned one for the same labware or
# well -- a script corrects or fills in a scan this way, and in simulation the
# scan only returns placeholders ("Barcode01", ...).
_assigned_labware_barcodes = {}
_assigned_well_barcodes = {}

# (labware_id, well) -> the well/container barcodes of everything dispensed into
# that well, first-seen order. A sample keeps the barcode of the tube (or well)
# it came from as it moves on: tube -> well -> well reports the tube's barcode
# at every step, not the barcode of the plate it passed through.
_sample_well_lineage = {}

# VENUS stores deck labware IDs lower-cased (autoload responses report
# "platecarrier" for a carrier the script added as "PlateCarrier"), so both
# ledgers above are keyed by lower-cased IDs and looked up the same way.


def _resolve_labware_barcode(labware):
    """The single barcode for *labware* as a whole (a plate/reservoir sitting
    at a scanned carrier site) -- never applies to a labware that was itself
    scanned AS a carrier (a tube rack), since that has one barcode per well,
    not one for the whole labware. See _resolve_well_barcode for that case.
    """
    key = str(labware or "").lower()
    if key in _assigned_labware_barcodes:
        return _assigned_labware_barcodes[key]
    site = _labware_carrier_site.get(key)
    if not site:
        return None
    return _carrier_site_barcodes.get(site) or None


def _resolve_well_barcode(labware, well):
    """The barcode for one specific well of *labware*, when *labware* was
    itself scanned as a carrier (a sample tube rack) -- e.g. the tube at
    well "31" of a scanned rack. Returns None for anything else (a plate's
    barcode belongs to the whole labware -- see _resolve_labware_barcode).
    """
    key = (str(labware or "").lower(), str(well))
    return _assigned_well_barcodes.get(key) or _carrier_site_barcodes.get(key) or None


def _sample_source_barcode(client, labware, well):
    """What an aspirate from labware@well picks up, as (barcode, type, lineage).

    type "well": the barcode of the well/container itself -- its own barcode (a
    scanned tube, or one assigned with set_barcodes), else the barcode(s) of the
    samples dispensed into it earlier ("; "-joined when several were pooled).
    Otherwise the labware's barcode, typed by its labware class ("plate",
    "reservoir", ...). lineage is what a well this is dispensed into inherits:
    the well barcodes only, never a labware barcode.
    """
    own = _resolve_well_barcode(labware, well)
    if own:
        return own, "well", [own]
    lineage = list(_sample_well_lineage.get((str(labware or "").lower(), str(well)), ()))
    if lineage:
        return "; ".join(lineage), "well", lineage
    barcode = _resolve_labware_barcode(labware)
    if not barcode:
        return None, None, []
    definition = _get_labware_definition(client, labware)
    labware_class = (getattr(definition, "labware_class", "") or "").strip().lower() if definition else ""
    return barcode, labware_class or "labware", []


def _tracked_labware_barcodes(client, labware_ids):
    """Labware-level barcodes VENUS sample tracking holds for *labware_ids*,
    keyed by lower-cased labware ID. Covers barcodes no scan ledger above
    explains -- e.g. one assigned with set_barcodes() -- and is the source of
    truth when both exist. Empty when the client has no sample tracking
    commands or the query fails (a display nicety must never break a run)."""
    getter = getattr(client, "get_labware_details", None)
    if getter is None or not labware_ids:
        return {}
    try:
        items = getter(list(labware_ids)).return_parameters.labware
    except Exception as exc:
        print(f"[script-runner] sample tracking: could not read labware barcodes: {exc}", flush=True)
        return {}
    return {
        str(getattr(item, "labware_id", "") or "").lower(): item.barcode
        for item in items
        if getattr(item, "barcode", None)
    }

# Keyed by a reload-prompt uuid (distinct from _prompt_events/_prompt_responses
# above, which are operator-error-escalation-specific). Set by _control_reader
# once a CONSUMABLE_PROMPT_RESPONSE line arrives, waking the tip_pickup wrapper
# blocked on it in _ensure_tip_availability.
_consumable_prompt_events = {}
_consumable_prompt_responses = {}


def _known_action_names(descriptors):
    # Mirrors hamilton_workflow_framework.session._known_action_names: descriptor
    # names like "Execute" are protocol-internal wrappers the SDK's resolver
    # applies automatically when submitting a selection, not something an
    # operator picks directly -- filtered out here so the top-level (Abort/
    # Cancel-style) buttons only offer real RecoveryAction values. Per-channel
    # dropdown options are built separately, in _channel_rows_with_actions,
    # from each detail's own raw recovery_actions -- those keep "Execute" out
    # for the same reason, but need the numeric id kept (not just the name),
    # since a per-channel selection round-trips back as a real server-side
    # action id, not a RecoveryAction the SDK maps for us.
    import hamilton_venus
    known = {a.value for a in hamilton_venus.RecoveryAction}
    names = []
    for descriptor in descriptors or []:
        name = (descriptor.name or "").lower()
        if name in known and name not in names:
            names.append(name)
    return names


def _position_label(value):
    # VENUS's "position" attribute on autoload barcode errors is 0-based (a scan
    # failure on plate site 1 and on tube position 1 both arrive as "0"); shown
    # 1-based to match carrier site / tube numbering. Non-numeric values pass
    # through unchanged.
    if value is None or value == "":
        return None
    try:
        return str(int(value) + 1)
    except ValueError:
        return str(value)


def _channel_rows_with_actions(error):
    # Grouped by exact message -- multiple channels overwhelmingly share the
    # exact same message for the exact same error *type* within one event
    # (VENUS raises one message template per failure kind, tagged per-channel
    # via each detail's own attributes), so one error type gets one dropdown
    # covering every channel it affects, not a separate dropdown per channel
    # that would just be set identically anyway. A channel with a genuinely
    # different message (a different failure kind within the same escalation,
    # e.g. "insufficient liquid" on some channels and "liquid level" on
    # others) lands in its own separate group. Same grouping run_summary.py
    # applies to the post-run Errors table, mirrored here rather than shared
    # since one runs in the FastAPI process and this runs inside the
    # subprocess bootstrap string.
    #
    # Each group carries the union of its member details' own server-advertised
    # recovery-action id/name pairs (not the error-wide RecoveryAction-filtered
    # list _known_action_names produces -- different error types can genuinely
    # advertise different options) plus a default: "repeat" if the server
    # advertises it for this group (the most commonly-useful blind retry), else
    # whichever action id the first detail's own default_recovery_action_id
    # names, else no default. error.message is frequently just the raw code
    # (e.g. "P1:06/71") -- the real description lives in each detail's own
    # message.
    #
    # Positional errors (autoload barcode reads) carry a "position" attribute
    # instead of "channel". Each detail also gets a display label ("Ch 3",
    # "Pos 1") so recovery inputs that need one value per detail -- e.g. the
    # barcode to use for each position that failed to read -- can be told apart.
    groups: dict[str, dict] = {}
    order: list[str] = []
    if error.detailed_errors:
        for detail in error.detailed_errors:
            if not detail.message:
                continue
            channel = None
            position = None
            for attr in (detail.attributes or []):
                if attr.name == "channel" and channel is None:
                    channel = attr.value
                elif (attr.name or "").lower() == "position" and position is None:
                    position = _position_label(attr.value)
            if detail.message not in groups:
                groups[detail.message] = {
                    "channels": [], "positions": [], "detail_uuids": [], "detail_labels": [],
                    "action_ids_seen": set(), "actions": [],
                    "fallback_default": detail.default_recovery_action_id,
                }
                order.append(detail.message)
            group = groups[detail.message]
            if channel:
                group["channels"].append(channel)
            if position:
                group["positions"].append(position)
            group["detail_uuids"].append(detail.uuid)
            group["detail_labels"].append(
                f"Ch {channel}" if channel else f"Pos {position}" if position else ""
            )
            for a in (detail.recovery_actions or []):
                if (a.name or "").lower() == "execute" or a.id in group["action_ids_seen"]:
                    continue
                group["action_ids_seen"].add(a.id)
                group["actions"].append({
                    "id": a.id,
                    "name": a.name,
                    "inputs": [
                        {
                            "id": i.id,
                            "name": i.name,
                            "default_value": i.default_value or "",
                            "value_type": i.value_type or "",
                            "pattern": i.pattern,
                        }
                        for i in (a.inputs or [])
                    ],
                })

    rows = []
    for message in order:
        group = groups[message]
        repeat_id = next((a["id"] for a in group["actions"] if a["name"].lower() == "repeat"), None)
        default_id = repeat_id if repeat_id is not None else group["fallback_default"]
        rows.append({
            "channels": group["channels"],
            "positions": group["positions"],
            "message": message,
            "detail_uuids": group["detail_uuids"],
            "detail_labels": group["detail_labels"],
            "actions": group["actions"],
            "default_action_id": default_id,
        })
    return rows


def _find_execute_action_id(error):
    # Mirrors _error_profile_resolver.py's own _find_execute_action_id: the
    # numeric id VENUS wants as ErrorRecovery.selected_action_id whenever
    # per-channel selections are being submitted (a fixed protocol-internal
    # wrapper meaning "apply the detailed_error_recoveries below", not
    # something an operator picks). -1 (matching the SDK's own fallback) if
    # this VENUS version doesn't advertise it, which the SDK's own submission
    # path is already equipped to reject safely rather than substitute a guess.
    for descriptor in error.recovery_actions or []:
        if (descriptor.name or "").lower() == "execute":
            return descriptor.id
    return -1


def _per_detail_action_ids(action_name, error):
    # Resolve action_name (e.g. "cancel"/"abort") to the server-side action id every one of
    # error.detailed_errors should carry, so it can be submitted as an explicit ErrorRecovery
    # instead of a plain top-level RecoveryAction. Mirrors
    # hamilton_workflow_framework.session's _per_detail_action_ids -- see its docstring for
    # why: Cancel/Abort are error-wide, top-level-only concepts -- a single channel can never
    # be individually cancelled or aborted, so they are never genuinely present in any one
    # channel's OWN recovery_actions (confirmed against a live VENUS instance: reusing a
    # per-channel-specific id, or expecting one to be individually advertised, both fail).
    # What a live VENUS instance actually rejects is a per-channel error submitted WITHOUT
    # detailed_error_recoveries at all ("The detailed error recoveries are missing"), which is
    # what the SDK's own resolver does for ABORT whenever a top-level id exists
    # (_error_profile_resolver.py::_submit_abort). So every detail gets the SAME top-level
    # action id here -- the operator's one error-wide choice, applied uniformly -- rather than
    # trying to find (or fabricate) a per-channel-specific one.
    #
    # Returns None (fall back to the plain top-level RecoveryAction path) only when there are
    # no detailed errors at all, or action_name has no server id anywhere on this error.
    if not error.detailed_errors:
        return None

    def _find(actions):
        for descriptor in actions or []:
            if (descriptor.name or "").lower() == action_name:
                return descriptor.id
        return None

    top_level_id = _find(error.recovery_actions)
    if top_level_id is None:
        return None
    return {detail.uuid: top_level_id for detail in error.detailed_errors}


def _on_operator_escalation(context):
    """Registered as StarClient(on_operator_error_escalation=...). Blocks the
    SDK's escalation worker thread until the parent process writes back a
    PROMPT_RESPONSE line (relayed from a browser click on the operator-recovery
    modal), then converts the response into either a plain RecoveryAction
    (Abort/Cancel-style, applies uniformly) or a fully-populated ErrorRecovery
    (independent per-channel selections -- the "advanced path" the SDK's
    resolver submits directly, see _error_profile_resolver.py's `isinstance(
    selected_action, ErrorRecovery)` branch, which self-corrects `uuid` and
    `error_handling_key` if left blank, so this doesn't need to duplicate that).
    Returning None -- covering "no response"/a torn-down run/an unrecognized
    action -- is treated by the SDK as ABORT (`if selected_action is None:
    await self._submit_abort(...)`).
    """
    import hamilton_venus
    from datetime import datetime, timezone
    from hamilton_venus.error_handling.access_actions import access_action_recovery, access_actions

    error = context.error
    error_uuid = error.uuid
    title = error.title or error.message or error.code or "Unknown instrument error."
    channel_errors = _channel_rows_with_actions(error)
    if not channel_errors and error.message and error.message != error.code:
        channel_errors = [{"channels": [], "message": error.message, "detail_uuids": [], "actions": [], "default_action_id": None}]

    payload = {
        "error_uuid": error_uuid,
        "code": error.code,
        "title": title,
        "channel_errors": channel_errors,
        "top_level_actions": _known_action_names(context.top_level_actions),
        # Unlock/lock door, raise/lower load tray: only the ones VENUS lists right
        # now. Choosing one does not answer the error -- the SDK submits it and
        # calls this again with the republished error (see access_actions.py).
        "access_actions": access_actions(error),
    }
    event = threading.Event()
    _prompt_events[error_uuid] = event
    print(f"\x00PROMPT\x00{json.dumps(payload)}", flush=True)
    event.wait()
    response = _prompt_responses.pop(error_uuid, None)
    _prompt_events.pop(error_uuid, None)
    if not response:
        return None
    _sample_operator_uuids.add(error_uuid)

    if response.get("kind") == "channels":
        selections = response.get("channel_actions") or {}
        if not selections:
            return None
        # detail_uuid -> [{"id": input id, "value": str}] for chosen actions that
        # take inputs (e.g. the barcode typed in for a position that failed to read).
        channel_inputs = response.get("channel_inputs") or {}
        from hamilton_venus.models import DetailedErrorRecovery, ErrorRecovery, InputValue
        now_str = datetime.now(timezone.utc).isoformat()
        detailed_recoveries = [
            DetailedErrorRecovery(
                date=now_str,
                uuid=detail_uuid,
                selected_action_id=int(action_id),
                inputs=[
                    InputValue(id=int(item["id"]), value=str(item.get("value") or ""))
                    for item in channel_inputs.get(detail_uuid) or []
                ],
            )
            for detail_uuid, action_id in selections.items()
        ]
        return ErrorRecovery(
            date=now_str,
            uuid=error_uuid,
            selected_action_id=_find_execute_action_id(error),
            selected_action_is_recovery=True,
            detailed_error_recoveries=detailed_recoveries,
        )

    action = response.get("action")
    if not action:
        return None
    access_recovery = access_action_recovery(error, action)
    if access_recovery is not None:
        return access_recovery
    try:
        resolved = hamilton_venus.RecoveryAction(action.lower())
    except ValueError:
        return None

    # Prefer an explicit per-channel ErrorRecovery over the plain RecoveryAction for a
    # genuinely per-channel escalation -- see _per_detail_action_ids's docstring for why.
    # Falls back to the plain RecoveryAction (the SDK's own top-level-vs-per-channel
    # handling) only when there's nothing per-channel to resolve, or *action* has no id
    # anywhere on this error at all.
    per_detail_ids = _per_detail_action_ids(resolved.value, error)
    if per_detail_ids:
        from hamilton_venus.models import DetailedErrorRecovery, ErrorRecovery

        now_str = datetime.now(timezone.utc).isoformat()
        # Cancel/Abort's own server id goes at the top level too (not the "Execute" wrapper
        # id) -- see _per_detail_action_ids's docstring: this is an error-wide choice, not a
        # set of independent per-channel picks the resolver needs to "execute". Every detail
        # carries the same id, since one channel's uuid is as good as another's for
        # identifying which id to use.
        top_level_id = next(iter(per_detail_ids.values()))
        return ErrorRecovery(
            date=now_str,
            uuid=error_uuid,
            selected_action_id=top_level_id,
            selected_action_is_recovery=True,
            detailed_error_recoveries=[
                DetailedErrorRecovery(date=now_str, uuid=detail_uuid, selected_action_id=action_id)
                for detail_uuid, action_id in per_detail_ids.items()
            ],
        )

    if error.detailed_errors and not per_detail_ids:
        # action has no id anywhere on this error (not even at the top level) -- nothing to
        # apply. Logged in full (not just names) so a recurrence gives enough to diagnose
        # what VENUS actually expects here, rather than guessing further.
        details_summary = "; ".join(
            f"{d.uuid}=[{', '.join(f'{a.name}:{a.id}' for a in (d.recovery_actions or []))}]"
            for d in error.detailed_errors
        )
        print(
            f"[script-runner] {resolved.value!r} has no id anywhere on error {error_uuid} "
            f"({len(error.detailed_errors)} channel(s)); falling back to the SDK's own "
            f"top-level submission (known to be rejected by VENUS for per-channel errors "
            f"missing detailed_error_recoveries -- see script_runner.py's "
            f"_per_detail_action_ids). Top-level recovery_actions: "
            f"[{', '.join(f'{a.name}:{a.id}' for a in (error.recovery_actions or []))}]; "
            f"per-channel recovery_actions: {details_summary}",
            file=sys.stderr,
            flush=True,
        )

    return resolved


def _sync_system_simulation_mode():
    # StarClient(simulate=...) only controls how VENUS *executes* a method --
    # it does NOT choose which instrument (real or simulated) actually
    # answers. That's this separate, system-wide VENUS setting, read/written
    # directly against the local Vector API (the same localhost:42400 service
    # the 3D deck viewer already talks to). Checking first and only writing on
    # a mismatch avoids toggling instrument state on every single run.
    url = f"{_VECTOR_API_BASE}/system/configuration/simulation"
    try:
        import httpx
    except Exception as exc:
        print(f"[script-runner] Could not import httpx -- VENUS system-wide simulation mode not synced: {exc}", flush=True)
        return
    try:
        with httpx.Client(timeout=10.0) as client:
            get_resp = client.get(url, headers=_VECTOR_API_HEADERS)
            get_resp.raise_for_status()
            current = get_resp.text.strip().strip('"').lower() == "true"
            if current == _FORCED_SIMULATE:
                print(f"[script-runner] VENUS system-wide simulation mode already {current!r} -- matches this run.", flush=True)
                return
            put_resp = client.put(
                url,
                headers=_VECTOR_API_HEADERS,
                params={"simulationMode": str(_FORCED_SIMULATE).lower()},
            )
            put_resp.raise_for_status()
            print(f"[script-runner] VENUS system-wide simulation mode changed: {current!r} -> {_FORCED_SIMULATE!r}.", flush=True)
    except Exception as exc:
        print(f"[script-runner] Could not sync VENUS system-wide simulation mode: {exc}", flush=True)


def _patch_client_class(client_cls, run_log_config_cls):
    # Force this run's simulate/trace/log-level/run-log settings into any
    # StarClient OR VantageClient the stored script constructs, and keep a
    # handle to it for door-lock control -- without touching the script's own
    # (read-only) source text. Called once per class (see the bottom of this
    # file) since a script targets exactly one of the two, but which one is
    # its own choice, not this bootstrap's -- patching both means either
    # works identically.
    original_init = client_cls.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["simulate"] = _FORCED_SIMULATE
        # Debug logging and the VENUS runtime trace only add Terminal output (the run
        # log captures HTTP/SignalR/command traffic on its own), but every line is
        # relayed through the backend and slows commands -- see the
        # "debug_logging_enabled" setting.
        kwargs["logging_level"] = logging.DEBUG if _DEBUG_LOGGING_ENABLED else logging.INFO
        kwargs["venus_trace_logging"] = _DEBUG_LOGGING_ENABLED
        run_log_cfg = run_log_config_cls(
            enabled=True,
            output_dir=_RUN_LOG_DIR,
            console_capture=True,
            include_http=True,
            include_signalr=True,
            include_cmd_comms=True,
        )
        # Also persist the firmware COM trace into *_SdkRunLog.json (so
        # "Export Log" carries it), gated by the same setting as the live
        # tail. Guarded so an older SDK without these fields still works.
        if hasattr(run_log_cfg, "include_com_trace"):
            run_log_cfg.include_com_trace = bool(_COM_TRACE_ENABLED)
            run_log_cfg.com_trace_logfiles_dir = _COM_TRACE_DIR or ""
        kwargs["run_log"] = run_log_cfg
        kwargs["on_operator_error_escalation"] = _on_operator_escalation
        kwargs["on_tip_reload_prompt"] = _make_tip_reload_prompt(self)
        original_init(self, *args, **kwargs)
        _captured_clients.append(self)

    client_cls.__init__ = patched_init

    # The `simulate` flag only affects how VENUS *executes* a method -- it does
    # NOT choose which instrument gets addressed. Whatever device is configured
    # in VENUS (real or simulated) answers either way, and Hamilton's simulated
    # device always reports serial number 0000 regardless of this flag -- so
    # printing it right after connect is the only way to see, from inside a
    # run, whether real hardware actually responded.
    #
    # instrument_get_serial_number() is a real command sent to VENUS: calling it
    # before the instrument is connected -- which is exactly the state a script
    # using StarClient(auto_connect=False) is in until it calls
    # instrument_connect() itself -- makes VENUS answer "Instrument must be
    # connected before calling this command!", and the SDK's run-log capture
    # records that as a captured error in the run summary's Errors table even
    # though the except below swallows the Python-level exception. So gate the
    # probe on instrument_is_connected() (a local SignalR channel peek, safe to
    # call disconnected -- it sends nothing to the instrument): probe now if
    # already connected (auto_connect=True), otherwise defer to the first
    # successful instrument_connect().
    original_enter = client_cls.__enter__
    original_connect = client_cls.instrument_connect

    def _wait_until_connected(self, timeout=5.0, interval=0.2):
        """instrument_is_connected() reads VENUS's own "connected" run-message
        channel, which VENUS updates asynchronously -- a status.connect (or an
        auto_connect=True __enter__) can return success before that channel
        reflects it, so a single immediate check can see a false "not
        connected" right after a real, successful connect. Nothing else ever
        retries this: a false negative here permanently skips the serial-
        number probe AND the pause/resume runtime-status listener
        (_register_runtime_status_listener) for the rest of the run -- so
        poll briefly instead of trusting one snapshot.
        """
        deadline = time.monotonic() + timeout
        while True:
            try:
                if self.instrument_is_connected():
                    return True
            except Exception:
                pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(interval)

    def _report_serial_number(self):
        global _serial_number_reported
        if _serial_number_reported:
            return
        _serial_number_reported = True
        try:
            resp = self.instrument_get_serial_number()
            serial = resp.return_parameters.serial_number
            is_simulated = serial in ("0000", "0", "")
            note = " -- this is Hamilton's simulated-instrument serial, not a real connected instrument" if is_simulated else ""
            print(f"[script-runner] Connected. Instrument serial number: {serial!r}{note}", flush=True)
            print(f"\x00SERIAL\x00{json.dumps({'serial': serial, 'simulated': is_simulated})}", flush=True)
        except Exception as exc:
            print(f"[script-runner] Connected, but could not query instrument serial number: {exc}", flush=True)

    def patched_enter(self):
        # Snapshot the .trc offset BEFORE original_enter() connects, so the
        # connect handshake (the bulk of a short script's firmware traffic) is
        # captured -- unlike the serial-number probe, this is just a file-size
        # read and needs no live connection.
        _start_com_trace_tail(self)
        result = original_enter(self)
        connected = _wait_until_connected(self)
        if connected:
            _report_serial_number(self)
            _register_runtime_status_listener(self)
        else:
            print(
                "[script-runner] Instrument not connected yet -- deferring the "
                "serial-number query until the script calls instrument_connect().",
                flush=True,
            )
        return result

    def patched_connect(self, *args, **kwargs):
        # A script may construct a client and call instrument_connect() without
        # using it as a context manager -- start the tail here too (the
        # _com_trace_started guard makes this a no-op after patched_enter).
        _start_com_trace_tail(self)
        response = original_connect(self, *args, **kwargs)
        # Only probe once the connect has actually taken -- a failed connect
        # leaves instrument_is_connected() False (even after the poll below
        # gives up), so this stays deferred.
        connected = _wait_until_connected(self)
        if connected:
            _report_serial_number(self)
            _register_runtime_status_listener(self)
        return response

    client_cls.__enter__ = patched_enter
    client_cls.instrument_connect = patched_connect


# -- COM trace tail (streams VENUS's firmware .trc into the "COM Trace" filter) --


def _start_com_trace_tail(client):
    """Once the instrument is connected, tail VENUS's firmware .trc file and
    stream newly-appended lines to the UI as \\x00COMTRACE\\x00 sentinels.
    One-shot (mirrors _serial_number_reported); no-op if disabled or if the
    installed SDK is too old to expose the shared helper."""
    global _com_trace_started, _com_trace_tailer
    if _com_trace_started or not _COM_TRACE_ENABLED:
        return
    _com_trace_started = True
    try:
        from hamilton_venus._internal._com_trace import ComTraceTailer, resolve_logfiles_dir
        from hamilton_venus.models import InstrumentType
    except Exception as exc:
        print(f"[script-runner] COM trace tail unavailable: {exc}", flush=True)
        return
    itype = InstrumentType.Vantage if type(client).__name__ == "VantageClient" else InstrumentType.STAR
    logfiles_dir = resolve_logfiles_dir(_COM_TRACE_DIR, _VECTOR_API_BASE.rsplit("/api/", 1)[0])
    try:
        _com_trace_tailer = ComTraceTailer(logfiles_dir, itype, _FORCED_SIMULATE)
    except Exception as exc:
        print(f"[script-runner] Could not start COM trace tail: {exc}", flush=True)
        _com_trace_tailer = None
        return
    print(f"[script-runner] COM trace tail started: {_com_trace_tailer.path}", flush=True)

    def _pump():
        while not _com_trace_stop.wait(0.5):
            _emit_com_trace_lines(max_bytes=256 * 1024)

    threading.Thread(target=_pump, name="com-trace-tail", daemon=True).start()


def _emit_com_trace_lines(*, max_bytes, flush_partial=False):
    """Read new complete .trc lines and print them as \\x00COMTRACE\\x00 batches,
    each capped well under the parent's stream read limit."""
    if _com_trace_tailer is None:
        return
    with _com_trace_lock:
        try:
            from hamilton_venus._internal._com_trace import iter_line_batches

            lines = _com_trace_tailer.read_new_lines(max_bytes=max_bytes, flush_partial=flush_partial)
        except Exception:
            return
        for batch in iter_line_batches(lines, max_bytes=64 * 1024, max_lines=400):
            print(
                "\x00COMTRACE\x00"
                + json.dumps({"lines": batch, "ts_ms": int(_datetime.now(_timezone.utc).timestamp() * 1000)}),
                flush=True,
            )


# -- Tip pool tracking (module docstring item 7) -----------------------------


def _emit_tip_update(tip_pool):
    pool = _tip_pools[tip_pool]
    print(
        f"\x00CONSUMABLE\x00{json.dumps({'kind': 'tip', 'tip_pool': tip_pool, **pool})}",
        flush=True,
    )


def _check_tip_threshold(tip_pool):
    # Edge-triggered: fires once when current_count crosses below low_threshold,
    # not on every subsequent low pickup -- resets once it climbs back above
    # (e.g. after a reload), so a run sitting at a low count doesn't spam.
    pool = _tip_pools[tip_pool]
    if pool["current_count"] is None:
        return
    now_low = pool["current_count"] < pool["low_threshold"]
    if now_low and not pool["below_threshold"]:
        print(
            f"\x00CONSUMABLE_WARNING\x00{json.dumps({'kind': 'tip', 'tip_pool': tip_pool, 'current_count': pool['current_count'], 'threshold': pool['low_threshold']})}",
            flush=True,
        )
    pool["below_threshold"] = now_low


_RACK_CAPACITY = 96  # standard tip rack size, used to size missing racks below


def _fetch_tip_counter(client, tip_pool):
    # tipPool.getTipCounter doesn't return a "total rack capacity" figure.
    # totalAvailableTips + totalEmptyTips reconstructs it correctly for a
    # freshly-initialized pool (confirmed against Hamilton's own example in
    # docs/json_schemas_System.md: availableTips['st_l_0001'].count=40 +
    # emptyTips['st_l_0001'].count=56 = 96, one rack) -- but that sum is a
    # running counter that persists across script runs until an operator
    # explicitly reloads/resets it, so on a pool with real usage history it
    # undercounts (confirmed live: a pool with 0 tips ever reloaded settled at
    # available+empty=56, not 96, despite the rack itself still being exactly
    # one physical 96-tip rack throughout). What stays stable regardless of
    # how depleted the counter is: which distinct rack IDs are referenced at
    # all across availableTips/emptyTips (each entry is {rackId: {"count":
    # n, "positions": [...]}} -- the SAME rack ID appears in both lists,
    # split across its available vs. spent positions, not summed twice) --
    # every rack is a fixed 96 tips whether it's fresh or nearly spent.
    params = client.tip_pool_get_tip_counter(tip_pool).return_parameters
    available = params.total_available_tips
    rack_ids = set()
    for entry in params.available_tips:
        rack_ids.update(entry.keys())
    for entry in params.empty_tips:
        rack_ids.update(entry.keys())
    rack_count = len(rack_ids) + len(params.missing_racks)
    total_capacity = _RACK_CAPACITY * rack_count if rack_count else None
    return available, total_capacity


def _update_tip_pool_state(tip_pool, available, total_capacity=None):
    pool = _tip_pools.setdefault(
        tip_pool,
        {"current_count": None, "total_capacity": None, "low_threshold": _DEFAULT_TIP_THRESHOLD, "below_threshold": False},
    )
    if total_capacity is not None:
        pool["total_capacity"] = total_capacity
    pool["current_count"] = available
    # Every caller passes a count VENUS just reported -- see _trusted_tip_counts.
    _trusted_tip_counts.add(tip_pool)
    _emit_tip_update(tip_pool)
    _check_tip_threshold(tip_pool)


def _run_tip_reload_prompt_cycle(client, tip_pool, required, available, *, command=None):
    """Run one CONSUMABLE_RELOAD prompt/modal cycle: emit the marker, block until
    the operator answers, and on "show_counter" trigger VENUS's own tip-counter
    dialog and refresh the tracked count.

    Shared by `_ensure_tip_availability` below (which owns its own retry loop
    for raw tip_pickup calls) and `_make_tip_reload_prompt` (whose returned
    callback is invoked, once per attempt, by the SDK's own
    `ensure_tips_available` retry loop for compound commands) -- both drive
    the exact same modal, so the operator sees identical behaviour either way.

    Returns ``(reloaded, available, total_capacity)``; ``reloaded`` is False
    on "abort"/cancel, in which case ``available``/``total_capacity`` are
    simply the *available*/``None`` passed in, unchanged.
    """
    reload_uuid = _uuid_module.uuid4().hex
    event = threading.Event()
    _consumable_prompt_events[reload_uuid] = event
    payload = {"reload_uuid": reload_uuid, "tip_pool": tip_pool, "required": required, "available": available}
    if command:
        payload["command"] = command
    print(f"\x00CONSUMABLE_RELOAD\x00{json.dumps(payload)}", flush=True)
    event.wait()
    _consumable_prompt_events.pop(reload_uuid, None)
    action = _consumable_prompt_responses.pop(reload_uuid, None)

    if action != "show_counter":
        # "abort", a stale/unrecognized response, or STOP (which resolves
        # every pending event this way) -- all treated as a clean cancel.
        print(
            f"\x00CONSUMABLE_RELOAD_DONE\x00{json.dumps({'reload_uuid': reload_uuid, 'cancelled': True})}",
            flush=True,
        )
        return False, available, None

    try:
        client.tip_pool_show_tip_counter(tip_pool)
    except Exception as exc:
        print(f"[script-runner] Tip counter dialog for {tip_pool!r} failed: {exc}", flush=True)
    # Re-query rather than trust anything off the dialog's own response --
    # reloading is exactly when rack composition (and so total_capacity)
    # changes, so this is the one moment it's worth paying for a fresh
    # getTipCounter call regardless of how the dialog closed.
    try:
        available, total_capacity = _fetch_tip_counter(client, tip_pool)
    except Exception as exc:
        print(f"[script-runner] Could not refresh tip pool {tip_pool!r} availability: {exc}", flush=True)
        available = client.tip_pool_get_available_tips(tip_pool).return_parameters.total_available_tips
        total_capacity = None
    _update_tip_pool_state(tip_pool, available, total_capacity)

    print(
        f"\x00CONSUMABLE_RELOAD_DONE\x00{json.dumps({'reload_uuid': reload_uuid, 'cancelled': False})}",
        flush=True,
    )
    return True, available, total_capacity


def _ensure_tip_availability(client, tip_pool, required):
    # Pre-check before letting a pickup call through. Interactive, not
    # background polling: nothing is called on VENUS until the operator
    # answers the reload prompt with "show_counter" -- see module docstring
    # item 7 and _control_reader's CONSUMABLE_PROMPT_RESPONSE handling below.
    from hamilton_venus.exceptions import OperatorCancelledError

    pool = _tip_pools.get(tip_pool)
    if tip_pool in _trusted_tip_counts and pool is not None and (pool["current_count"] or 0) >= required:
        return

    try:
        available, total_capacity = _fetch_tip_counter(client, tip_pool)
    except Exception as exc:
        print(f"[script-runner] Could not check tip pool {tip_pool!r} availability: {exc}", flush=True)
        return
    _update_tip_pool_state(tip_pool, available, total_capacity)

    while available < required:
        reloaded, available, _total_capacity = _run_tip_reload_prompt_cycle(client, tip_pool, required, available)
        if not reloaded:
            raise OperatorCancelledError(
                f"Tip reload for {tip_pool!r} cancelled (required={required}, available={available})."
            )


def _make_tip_reload_prompt(client):
    """Return a ``TipReloadPromptCallback`` bound to *client*, for registering
    as ``StarClient``/``VantageClient(on_tip_reload_prompt=...)``.

    Wired into `hamilton_venus.compound_commands._helpers._tip_manager.
    ensure_tips_available` -- the upfront tip-shortage gate every compound
    command (hit_picking, pool_samples, replicate_samples, serial_dilution,
    add_reagent, copy_plate) runs before doing any real pickups. Previously
    this callback slot was left unset (only `on_operator_error_escalation`
    was wired -- see item 6 above), so a compound-step script that ran short
    on tips got a bare, unhandled ``ValueError`` from ``ensure_tips_available``
    instead of the same CONSUMABLE_RELOAD warning a plain script's raw
    ``tip_pickup`` already gets; that ``ValueError`` isn't one of this file's
    recognized sentinel markers, so it fell through to the generic log
    relay, indistinguishable from ordinary error noise. Reusing
    `_run_tip_reload_prompt_cycle` here closes that gap with the exact same
    prompt/modal.

    Unlike `_ensure_tip_availability` above, this runs exactly one prompt
    cycle per call -- `ensure_tips_available` owns the retry loop itself (it
    re-checks availability via `tip_pool_reset_tip_counter` +
    `tip_pool_get_available_tips` after a truthy return, and re-invokes this
    callback, with `attempt` incremented, if still short).
    """

    def _on_tip_reload_prompt(context):
        reloaded, _available, _capacity = _run_tip_reload_prompt_cycle(
            client, context.tip_pool, context.required, context.available, command=context.command
        )
        return reloaded

    return _on_tip_reload_prompt


def _record_tip_pickup(tip_pool, result):
    # tip_pickup's own response already carries the refreshed remaining count
    # (confirmed against a live run's raw HTTP capture -- returnParameters.
    # remainingTips) -- read directly off the untyped return_parameters dict
    # rather than issuing a second tip_pool_get_available_tips call.
    try:
        remaining = result.return_parameters.get("remainingTips")
    except AttributeError:
        remaining = None
    if remaining is not None:
        _update_tip_pool_state(tip_pool, remaining)
    else:
        _trusted_tip_counts.discard(tip_pool)


def _call_pickup(original, client, tip_pool, args, kwargs):
    # A pickup that raises may still have taken some tips, so VENUS's count is
    # unknown afterwards -- the next pickup on this pool must query it again.
    try:
        return original(client, *args, **kwargs)
    except BaseException:
        if tip_pool:
            _trusted_tip_counts.discard(tip_pool)
        raise


def _patch_tip_counter_invalidation(client_cls):
    # The script's own tip counter changes: the runner doesn't see the resulting
    # count, so the next pickup on that pool queries VENUS again.
    for method_name in (
        "tip_pool_initialize_tip_counter",
        "tip_pool_reset_tip_counter",
        "tip_pool_set_tip_counter",
        "tip_pool_show_tip_counter",
    ):
        original = getattr(client_cls, method_name, None)
        if original is None:
            continue

        def patched(self, tip_pool, *args, _original=original, **kwargs):
            try:
                return _original(self, tip_pool, *args, **kwargs)
            finally:
                _trusted_tip_counts.discard(tip_pool)

        setattr(client_cls, method_name, patched)

    original_show_all = getattr(client_cls, "tip_pool_show_tip_counters", None)
    if original_show_all is not None:
        def show_tip_counters(self, *args, **kwargs):
            try:
                return original_show_all(self, *args, **kwargs)
            finally:
                _trusted_tip_counts.clear()

        setattr(client_cls, "tip_pool_show_tip_counters", show_tip_counters)


def _patch_tip_pool_tracking(client_cls, method_name, impl_name):
    from hamilton_venus.exceptions import OperatorCancelledError

    original = getattr(client_cls, method_name, None)
    if original is None:
        return
    # channel_commands.py installs a generic (self, *args, **kwargs) passthrough
    # as the public method (it re-scopes _ACTION_PREFIX/_CHANNEL_PITCH_MM/etc.
    # per call before delegating), so inspect.signature(original) can't recover
    # named arguments at all -- bind against the real underlying _xxx_impl
    # method's signature instead, which has proper parameter names. Both the
    # 1mL and 5mL mixins define this impl with the same parameter names (only
    # the closed-over constants differ), so whichever the MRO resolves is
    # fine purely as a signature template -- it's never actually called.
    impl = getattr(client_cls, impl_name, None)
    sig = inspect.signature(impl) if impl is not None else inspect.signature(original)

    def patched(self, *args, **kwargs):
        tip_pool = None
        try:
            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()
            tip_pool = bound.arguments.get("tip_pool")
            channels = bound.arguments.get("channels") or getattr(self, "_DEFAULT_CHANNELS", None) or list(range(1, 9))
            if tip_pool:
                _ensure_tip_availability(self, tip_pool, len(channels))
        except OperatorCancelledError:
            raise
        except Exception as exc:
            print(f"[script-runner] consumable tracking error (pre-pickup): {exc}", flush=True)
        result = _call_pickup(original, self, tip_pool, args, kwargs)
        try:
            if tip_pool:
                _record_tip_pickup(tip_pool, result)
        except Exception as exc:
            print(f"[script-runner] consumable tracking error (post-pickup): {exc}", flush=True)
        return result

    setattr(client_cls, method_name, patched)


def _patch_mph96_tip_pool_tracking(client_cls):
    from hamilton_venus.exceptions import OperatorCancelledError

    def _wrap(method_name, required_fn):
        original = getattr(client_cls, method_name, None)
        if original is None:
            return
        sig = inspect.signature(original)

        def patched(self, *args, **kwargs):
            tip_pool = None
            try:
                bound = sig.bind(self, *args, **kwargs)
                bound.apply_defaults()
                tip_pool = bound.arguments.get("tip_pool")
                required = required_fn(bound.arguments)
                if tip_pool:
                    _ensure_tip_availability(self, tip_pool, required)
            except OperatorCancelledError:
                raise
            except Exception as exc:
                print(f"[script-runner] consumable tracking error (pre-mph96-pickup): {exc}", flush=True)
            result = _call_pickup(original, self, tip_pool, args, kwargs)
            try:
                if tip_pool:
                    _record_tip_pickup(tip_pool, result)
            except Exception as exc:
                print(f"[script-runner] consumable tracking error (post-mph96-pickup): {exc}", flush=True)
            return result

        setattr(client_cls, method_name, patched)

    def _full_head_required(arguments):
        return 96

    def _partial_required(arguments):
        # A 96-well plate is 8 rows x 12 columns -- a column pickup grabs 8
        # tips per column, a row pickup grabs 12 tips per row.
        mode = arguments.get("mode")
        count = arguments.get("count") or 0
        mode_value = getattr(mode, "value", mode)
        if mode_value == "rows":
            return count * 12
        return count * 8

    _wrap("tip_pick_up_mph96", _full_head_required)
    _wrap("tip_pick_up_mph96_partial", _partial_required)


# -- Reservoir (reagent) tracking (module docstring item 7) ------------------


def _get_labware_definition(client, labware):
    # Full urn:hamilton:schemas:microlab:labware:v1 definition (labware_class,
    # container_grids/total_depth, ...) -- one lookup per labware per run,
    # cached since both depth resolution and reservoir identification below
    # need it and it's looked up on every aspirate from that labware.
    if labware in _labware_definition_cache:
        return _labware_definition_cache[labware]
    definition = None
    try:
        resp = client.labware_get_params_from_id(labware)
        definition = resp.return_parameters.to_labware_definition()
    except Exception as exc:
        print(f"[script-runner] Could not resolve labware definition for {labware!r}: {exc}", flush=True)
        definition = None
    _labware_definition_cache[labware] = definition
    return definition


def _resolve_container_depth(client, labware):
    definition = _get_labware_definition(client, labware)
    if definition is None:
        return None
    depth = None
    for grid in definition.container_grids.values():
        candidate = grid.container_definition.total_depth
        if candidate:
            depth = candidate
            break
    return depth


def _segment_volume_ul(segment):
    """Volume of one VolumeSegment, by its shape -- 1 mm^3 == 1 uL, and every
    labware:v1 length field (height/diameter/width/depth) is already in mm,
    so no unit conversion is needed beyond the geometry itself.

    Unknown/future shape types return 0.0 rather than raising: a labware
    definition using a shape this SDK doesn't model yet should undercount
    that one segment, not blow up reservoir tracking for the whole run.
    """
    height = segment.height or 0.0
    if height <= 0:
        return 0.0
    kind = (segment.type or "").strip().lower()
    if kind == "cylinder":
        radius = (segment.diameter or 0.0) / 2.0
        return math.pi * radius * radius * height
    if kind == "rectangular_prism":
        return (segment.width or 0.0) * (segment.depth or 0.0) * height
    if kind == "conical_frustum":
        # Frustum of a cone: V = (pi*h/12) * (D1^2 + D1*D2 + D2^2), D=diameter.
        d1, d2 = segment.diameter_bottom or 0.0, segment.diameter_top or 0.0
        return (math.pi * height / 12.0) * (d1 * d1 + d1 * d2 + d2 * d2)
    if kind == "rectangular_frustum":
        # Frustum of a pyramid: V = (h/3) * (A1 + A2 + sqrt(A1*A2)).
        a1 = (segment.width_bottom or 0.0) * (segment.depth_bottom or 0.0)
        a2 = (segment.width_top or 0.0) * (segment.depth_top or 0.0)
        return (height / 3.0) * (a1 + a2 + math.sqrt(a1 * a2))
    if kind == "spherical_cap":
        # Cap of height h with a flat circular base of radius a (diameter is
        # that base's diameter, not the parent sphere's): V = (pi*h/6)*(3a^2+h^2).
        a = (segment.diameter or 0.0) / 2.0
        return (math.pi * height / 6.0) * (3 * a * a + height * height)
    return 0.0


def _resolve_container_max_volume(client, labware):
    # A reservoir's nominal capacity, computed once from its labware
    # definition's volume_model (the stacked segments describing container
    # shape) and cached -- unlike the old total_depth-based estimate this
    # replaces in _update_reservoir, it's fixed for the life of the run
    # rather than drifting with each new LLD height reading, since it comes
    # from static geometry, not a live measurement.
    #
    # A labware whose own definition says labwareClass == "reservoir" is
    # tracked as ONE pooled entry spanning every one of its addressable
    # positions (see _record_reservoir_aspirate's key = pos.labware alone,
    # and its comment: every position is a distinct sub-position of the SAME
    # physical pool) -- so its capacity is the sum of every grid cell's
    # volume, not just one. A labware manually tracked as a reagent that
    # VENUS itself doesn't call reservoir-class is instead tracked per well
    # (key = "labware@well"), so it gets just that one cell's own volume.
    if labware in _container_volume_cache:
        return _container_volume_cache[labware]
    definition = _get_labware_definition(client, labware)
    total = None
    if definition is not None:
        try:
            pooled = (definition.labware_class or "").strip().lower() == "reservoir"
            total = 0.0
            for grid in definition.container_grids.values():
                segments = grid.container_definition.volume_model.segments
                if not segments:
                    continue
                cell_volume = sum(_segment_volume_ul(seg) for seg in segments)
                if cell_volume <= 0:
                    continue
                if pooled:
                    total += cell_volume * max(1, grid.rows * grid.columns)
                else:
                    total = cell_volume
                    break
            if total <= 0:
                total = None
        except AttributeError:
            # A labware definition missing volume_model/rows/columns entirely
            # (older data, or a minimal test double) -- fall back to no volume
            # model available rather than crashing reservoir tracking.
            total = None
    _container_volume_cache[labware] = total
    return total


def _is_reservoir_labware(client, labware):
    # Identified by labwareClass == "reservoir" on the labware's own
    # definition (every reservoir labware has this set), not the SDK's
    # connected_container flag -- a reservoir is still one physical liquid
    # pool addressed by several channels at once, each at its own distinct
    # sub-position, so per-channel readings must still be pooled into ONE
    # tracked reservoir, not N separate ones (see _record_reservoir_aspirate).
    definition = _get_labware_definition(client, labware)
    if definition is None:
        return False
    is_reservoir = (definition.labware_class or "").strip().lower() == "reservoir"
    if is_reservoir and labware not in _reservoir_labware_logged:
        # run_summary.py's Summary tab can only recognize a labware as a
        # reservoir by seeing its OWN labware.addReservoir request in the run
        # log -- which never appears for a reservoir that was already on a
        # deck loaded via deck_load()/backup-restore rather than added fresh
        # by this script (deck.loadDeck's own response carries no labware
        # list at all). This "reservoir_labware" entry is the fix: it's this
        # live check's own answer (backed by a real connected client, unlike
        # the post-run static log run_summary.py otherwise has to work from),
        # written once per labware so the Summary tab can trust it exactly
        # like a real labware.addReservoir call -- see run_summary.py's
        # matching read of this entry type.
        _reservoir_labware_logged.add(labware)
        run_log = getattr(client, "_run_log", None)
        if run_log is not None:
            run_log.record("Bootstrap", "Out", "reservoir_labware", {"labware": labware})
    return is_reservoir


def _is_liquid_waste(labware):
    # The fixed channel liquid waste (STAR add_channel_liquid_waste, Vantage
    # add_liquid_waste) -- always this id; the frontend's "waste" category
    # keys off the same name.
    return str(labware).lower() == "liquid_waste"


def _should_track_reservoir(client, key, labware):
    # Already registered (explicit "Add Reservoir", or auto-discovered by an
    # earlier aspirate this run/a prior run) -- always keep tracking it.
    if key in _reservoirs:
        return True
    # Otherwise only auto-track labware whose own definition identifies it as
    # a reservoir -- avoids flooding the tab with one-off sample-plate wells.
    return _is_reservoir_labware(client, labware)


def _update_reservoir(client, key, labware, well, label, readings):
    # readings: list of (liquid_level_mm, liquid_volume_ul, aspirated_volume)
    # tuples -- one per channel that hit this well (1mL/5mL), or a single
    # entry for MPH96, which reports one reading for the whole head.
    is_new = key not in _reservoirs
    entry = _reservoirs.setdefault(
        key,
        {
            "labware": labware, "well": well, "label": label or key, "source": "auto",
            "remaining_volume_ul": None, "total_volume_ul": None, "percent_full": None, "last_updated": None,
            "below_threshold": False,
        },
    )
    if is_new:
        # Seed the known capacity (static geometry, not a measurement) right
        # away, starting remaining at 0/empty rather than leaving everything
        # "n/a" until VENUS happens to report a real LLD reading -- 0 is the
        # safe assumption (never overstates what's left), and it also gives
        # the decrement-on-aspirate fallback below a non-None baseline to
        # work from immediately instead of silently dropping every aspirate
        # against this reservoir until its first measured reading.
        max_volume = _resolve_container_max_volume(client, labware)
        if max_volume:
            entry["total_volume_ul"] = max_volume
            entry["remaining_volume_ul"] = 0.0
            entry["percent_full"] = 0.0
    measured = [(h, v) for h, v, _a in readings if v and v > 0]
    if measured:
        # A measured value always overrides the running estimate -- VENUS
        # re-measures every aspirate, so prefer the fresh reading over
        # decrementing (mirrors hamilton_venus's own LiquidSourceTracker.
        # record_aspirate). Multi-channel readings from the same well are
        # averaged, per spec.
        avg_volume = sum(v for _h, v in measured) / len(measured)
        avg_height = sum(h for h, _v in measured) / len(measured)
        entry["remaining_volume_ul"] = avg_volume
        max_volume = _resolve_container_max_volume(client, labware)
        if max_volume:
            # Fixed capacity from the labware's own geometry -- constant for
            # the whole run, unlike the depth-based fallback below (or this
            # code's old total = current*(depth/height) extrapolation, which
            # visibly drifted reading to reading as VENUS's measured height
            # varied slightly between aspirates of the same reservoir).
            entry["total_volume_ul"] = max_volume
            entry["percent_full"] = min(1.0, avg_volume / max_volume)
        else:
            # No usable volume_model on this labware -- fall back to the old
            # height/depth-based linear extrapolation (assumes a uniform
            # cross-section, so it can still drift reading to reading, but
            # it's better than reporting nothing).
            depth = _resolve_container_depth(client, labware)
            if depth and avg_height > 0:
                entry["total_volume_ul"] = avg_volume * (depth / avg_height)
                entry["percent_full"] = min(1.0, avg_height / depth)
            else:
                entry["total_volume_ul"] = None
                entry["percent_full"] = None
    else:
        # No usable fresh measurement (e.g. LLD off/placeholder-only) -- fall
        # back to decrementing the last known estimate by what was aspirated.
        aspirated_sum = sum(a for _h, _v, a in readings if a)
        if entry["remaining_volume_ul"] is not None:
            entry["remaining_volume_ul"] = max(0.0, entry["remaining_volume_ul"] - aspirated_sum)
            if entry["total_volume_ul"]:
                entry["percent_full"] = min(1.0, entry["remaining_volume_ul"] / entry["total_volume_ul"])

    entry["last_updated"] = _datetime.now(_timezone.utc).isoformat()
    print(f"\x00CONSUMABLE\x00{json.dumps({'kind': 'reagent', 'key': key, **entry})}", flush=True)
    _check_reservoir_threshold(key)


def _check_reservoir_threshold(key):
    # Edge-triggered like _check_tip_threshold: fires once when percent_full
    # crosses below the globally configured warning percentage, resets once
    # it climbs back above (e.g. a manual refill re-measures higher). Silent
    # (no fire, no reset) whenever percent_full is unknown -- a reservoir
    # whose container depth can't be resolved never has anything to compare.
    entry = _reservoirs[key]
    if entry["percent_full"] is None:
        return
    now_low = entry["percent_full"] < _RESERVOIR_WARNING_PERCENT
    if now_low and not entry["below_threshold"]:
        print(
            f"\x00CONSUMABLE_WARNING\x00{json.dumps({'kind': 'reagent', 'reservoir_key': key, 'label': entry['label'], 'percent_full': entry['percent_full'], 'threshold_percent': _RESERVOIR_WARNING_PERCENT * 100})}",
            flush=True,
        )
    entry["below_threshold"] = now_low


def _record_reservoir_aspirate(client, positions_arg, channels_arg, result, channel_pitch_mm):
    channel_data = getattr(result.return_parameters, "channels", None)
    if not channel_data:
        return
    from hamilton_venus.models.position import normalize_positions

    try:
        normalized = normalize_positions(
            positions_arg,
            channel_count=len(channels_arg),
            get_spec=client.get_labware_spec,
            channel_pitch_mm=channel_pitch_mm,
        )
    except Exception as exc:
        print(f"[script-runner] consumable tracking: could not resolve aspirate positions: {exc}", flush=True)
        return
    channel_to_pos = dict(zip(channels_arg, normalized))

    groups = {}
    for cd in channel_data:
        pos = channel_to_pos.get(cd.channel)
        if pos is None:
            continue
        # A reservoir's N channels each land on their own distinct
        # sub-position of the SAME physical pool -- track it as one entry
        # (keyed by labware alone), not one per sub-position, so
        # multi-channel readings from it get pooled/averaged as intended
        # rather than fragmented into N near-duplicate "reservoirs".
        if _is_reservoir_labware(client, pos.labware):
            key, well_label = pos.labware, "all"
        else:
            key, well_label = f"{pos.labware}@{pos.well}", pos.well
        groups.setdefault(key, {"labware": pos.labware, "well": well_label, "readings": []})
        groups[key]["readings"].append((cd.liquid_level_mm, cd.liquid_volume_ul, cd.aspirated_volume))

    for key, group in groups.items():
        if not _should_track_reservoir(client, key, group["labware"]):
            continue
        existing_label = _reservoirs.get(key, {}).get("label")
        _update_reservoir(client, key, group["labware"], group["well"], existing_label, group["readings"])


def _patch_reservoir_tracking(client_cls, method_name, channel_pitch_mm, impl_name):
    original = getattr(client_cls, method_name, None)
    if original is None:
        return
    # See _patch_tip_pool_tracking's comment: the public method is a generic
    # (self, *args, **kwargs) passthrough, so bind against the real _xxx_impl
    # signature instead to actually recover "positions"/"channels" by name.
    impl = getattr(client_cls, impl_name, None)
    sig = inspect.signature(impl) if impl is not None else inspect.signature(original)

    def patched(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        try:
            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()
            positions_arg = bound.arguments.get("positions")
            channels_arg = bound.arguments.get("channels") or getattr(self, "_DEFAULT_CHANNELS", None) or list(range(1, 9))
            _record_reservoir_aspirate(self, positions_arg, channels_arg, result, channel_pitch_mm)
        except Exception as exc:
            print(f"[script-runner] consumable tracking error (aspirate): {exc}", flush=True)
        return result

    setattr(client_cls, method_name, patched)


def _patch_mph96_reservoir_tracking(client_cls):
    original = getattr(client_cls, "aspirate_mph96", None)
    if original is None:
        return
    sig = inspect.signature(original)
    # aspirate_mph96 gets wrapped again below by _patch_mph96_sample_tracking --
    # stash the true, still-unwrapped signature under a name that wrap never
    # itself replaces, so that later call can bind real argument names instead
    # of the generic (self, *args, **kwargs) this wrapper's own `patched` has.
    if not hasattr(client_cls, "_aspirate_mph96_impl"):
        client_cls._aspirate_mph96_impl = original

    def patched(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        try:
            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()
            labware_id = bound.arguments.get("labware_id")
            mph_pattern = bound.arguments.get("mph_pattern")
            volume = bound.arguments.get("volume") or 0.0
            # Number of active channels/tips: from the given pattern, else the
            # full 96-channel head by default (per spec).
            channels_used = len(mph_pattern) if mph_pattern else 96
            rp = result.return_parameters
            level = None
            vol_detected = None
            try:
                level = rp.get("liquidLevel_mm")
                vol_detected = rp.get("liquidVolume_uL")
            except AttributeError:
                pass
            key = f"{labware_id}@mph96"
            if not _should_track_reservoir(self, key, labware_id):
                return result
            existing_label = _reservoirs.get(key, {}).get("label")
            readings = [(level or 0.0, vol_detected or 0.0, channels_used * volume)]
            _update_reservoir(self, key, labware_id, "mph96", existing_label, readings)
        except Exception as exc:
            print(f"[script-runner] consumable tracking error (mph96 aspirate): {exc}", flush=True)
        return result

    setattr(client_cls, "aspirate_mph96", patched)


def _sample_source_key(labware, well):
    if labware is None or well is None:
        return None
    key = f"{labware}@{well}"
    if key not in _sample_source_color_index:
        _sample_source_color_index[key] = len(_sample_source_color_index)
    return _sample_source_color_index[key]


def _announce_sample_labware(client, labware):
    # Sent once per labware per run, the first time it becomes a target (see
    # _record_sample_event). Aspirate-only labware is never announced.
    if labware in _sample_labware_announced:
        return
    _sample_labware_announced.add(labware)
    definition = _get_labware_definition(client, labware)
    labware_class = (getattr(definition, "labware_class", "") or "").strip().lower() if definition else ""
    rows, cols, numeric_addressing, pattern = 8, 12, False, "COLUMN_MAJOR"
    try:
        spec = client.get_labware_spec(labware)
        rows = spec.rows or rows
        cols = spec.cols or cols
        numeric_addressing = bool(spec.numeric_addressing)
        pattern = spec.pattern or pattern
    except Exception as exc:
        print(f"[script-runner] sample tracking: could not resolve layout for {labware!r}: {exc}", flush=True)
    barcode = _tracked_labware_barcodes(client, [labware]).get(str(labware).lower()) or _resolve_labware_barcode(labware)
    payload = {
        "labware": labware,
        "labware_class": labware_class or "unknown",
        "rows": rows,
        "cols": cols,
        "numeric_addressing": numeric_addressing,
        "pattern": pattern,
        "barcode": barcode,
    }
    _sample_labware_payloads[labware] = payload
    print(f"\x00SAMPLE_LABWARE_INFO\x00{json.dumps(payload)}", flush=True)


def _refresh_sample_labware_barcodes(client):
    # Re-announces any already-shown labware whose labware-level barcode in
    # sample tracking has changed -- e.g. a plate barcoded with set_barcodes()
    # after its first transfer. The frontend updates an existing card's
    # barcode from a repeated sample_labware_info.
    if not _sample_labware_payloads:
        return
    current = _tracked_labware_barcodes(client, list(_sample_labware_payloads))
    for labware, payload in _sample_labware_payloads.items():
        barcode = current.get(str(labware).lower())
        if barcode and barcode != payload.get("barcode"):
            payload["barcode"] = barcode
            print(f"\x00SAMPLE_LABWARE_INFO\x00{json.dumps(payload)}", flush=True)


def _sample_source_position(client, labware, well):
    # A reservoir's several addressable sub-positions ("Water@1".."Water@8")
    # all draw from ONE physical pool -- collapse them to a single source
    # identity (and therefore a single legend/well color) rather than
    # fragmenting into N near-duplicate sources, mirroring the existing
    # Consumables reservoir-pooling convention (_record_reservoir_aspirate).
    if _is_reservoir_labware(client, labware):
        return labware, "all"
    return labware, well


def _sample_error_action_name(action_id, *descriptor_lists):
    for descriptors in descriptor_lists:
        for descriptor in descriptors or []:
            if descriptor.id == action_id:
                return descriptor.name
    return f"action {action_id}"


def _sample_error_inputs(values, *descriptor_lists):
    # [{"name", "value"}] for the inputs a recovery submission carried (e.g. the
    # barcode typed in for a position that failed to read).
    names = {}
    for descriptors in descriptor_lists:
        for descriptor in descriptors or []:
            for item in getattr(descriptor, "inputs", None) or []:
                names.setdefault(item.id, item.name)
    return [{"name": names.get(v.id, f"input {v.id}"), "value": v.value} for v in values or []]


def _record_sample_error_recovery(error_uuid, recovery, kind):
    # One _sample_error_log entry per channel of the error this submission
    # answers (a single channel-less entry for an error with no per-channel
    # details). kind: "recovery" answers the error, "action" (door / loading
    # tray) does not -- VENUS publishes the error again afterwards.
    with _sample_error_lock:
        error = _sample_error_seen.get(error_uuid)
    decided_by = "operator" if error_uuid in _sample_operator_uuids else "automatic"
    _sample_operator_uuids.discard(error_uuid)
    top_actions = list(getattr(error, "recovery_actions", None) or [])
    top_other = list(getattr(error, "actions", None) or [])
    # selected_action_id=-1 hands the error to VENUS's own operator dialog.
    deferred = recovery.selected_action_id == -1 and not recovery.selected_action_is_recovery
    if deferred:
        decided_by = "operator"
    base = {
        "error_uuid": error_uuid,
        "time": _datetime.now(_timezone.utc).isoformat(),
        "code": getattr(error, "code", None),
        "title": getattr(error, "title", None),
        "kind": kind,
        "decided_by": decided_by,
    }
    selected = {r.uuid: r for r in recovery.detailed_error_recoveries or []}
    entries = []
    for detail in getattr(error, "detailed_errors", None) or []:
        channel = position = None
        for attr in detail.attributes or []:
            name = (attr.name or "").lower()
            if name == "channel" and channel is None:
                channel = attr.value
            elif name == "position" and position is None:
                position = _position_label(attr.value)
        try:
            channel = int(channel) if channel is not None else None
        except (TypeError, ValueError):
            pass
        chosen = selected.get(detail.uuid)
        if deferred:
            action_name, inputs = "VENUS operator dialog", []
        elif chosen is not None:
            action_name = _sample_error_action_name(
                chosen.selected_action_id, detail.recovery_actions, detail.actions, top_actions, top_other,
            )
            inputs = _sample_error_inputs(chosen.inputs, detail.recovery_actions, detail.actions)
        else:
            action_name = _sample_error_action_name(recovery.selected_action_id, top_actions, top_other)
            inputs = _sample_error_inputs(recovery.inputs, top_actions, top_other)
        entries.append({
            **base,
            "detail_code": detail.code,
            "message": detail.message or getattr(error, "message", None),
            "channel": channel,
            "position": position,
            "recovery": action_name,
            "inputs": inputs,
        })
    if not entries:
        entries.append({
            **base,
            "detail_code": None,
            "message": getattr(error, "message", None),
            "channel": None,
            "position": None,
            "recovery": "VENUS operator dialog" if deferred else _sample_error_action_name(
                recovery.selected_action_id, top_actions, top_other,
            ),
            "inputs": _sample_error_inputs(recovery.inputs, top_actions, top_other),
        })
    with _sample_error_lock:
        # The resolver re-sends an unchanged payload when VENUS is slow to clear
        # the error (_reconcile_pending_detailed_error); that is not a new answer.
        signature = (id(error), kind, [(e["channel"], e["recovery"]) for e in entries])
        if _sample_error_log and _sample_error_log[-1].get("_signature") == signature:
            return
        for entry in entries:
            entry["_signature"] = signature
        _sample_error_log.extend(entries)


def _patch_sample_error_capture():
    # Sample Tracking's per-transfer error/recovery details. The SDK reports an
    # instrument error to a script only when it ends the command; an error the
    # profile (or the operator) recovered from is otherwise invisible to the
    # call that hit it. Both ends are wrapped here: the resolver's entry point
    # (what the error was) and the two VenusClient submissions every answer
    # goes through (how it was answered). Recording never alters either call.
    try:
        from hamilton_venus._internal._error_profile_resolver import ErrorProfileResolver
        from hamilton_venus.venus_client import VenusClient
    except Exception as exc:
        print(f"[script-runner] sample tracking: error/recovery capture unavailable: {exc}", flush=True)
        return

    original_on_error = ErrorProfileResolver.on_instrument_error

    async def on_instrument_error(self, error):
        try:
            with _sample_error_lock:
                _sample_error_seen[error.uuid] = error
        except Exception:
            pass
        return await original_on_error(self, error)

    ErrorProfileResolver.on_instrument_error = on_instrument_error

    def _wrap_submit(method_name, kind):
        original = getattr(VenusClient, method_name, None)
        if original is None:
            return

        async def submit(self, error_uuid, recovery):
            try:
                _record_sample_error_recovery(error_uuid, recovery, kind)
            except Exception as exc:
                print(f"[script-runner] sample tracking: could not record error recovery: {exc}", flush=True)
            return await original(self, error_uuid, recovery)

        setattr(VenusClient, method_name, submit)

    _wrap_submit("submit_error_recovery", "recovery")
    _wrap_submit("submit_error_action", "action")


def _sample_errors_mark():
    with _sample_error_lock:
        return len(_sample_error_log)


def _sample_errors_since(mark, channel=None):
    # Errors answered since *mark* that belong to *channel*: its own
    # per-channel errors plus any error with no channel of its own. channel
    # None (MPH96, dispense on the fly) takes them all.
    with _sample_error_lock:
        recorded = _sample_error_log[mark:]
    return [
        {k: v for k, v in entry.items() if k != "_signature"}
        for entry in recorded
        if channel is None or entry["channel"] is None or entry["channel"] == channel
    ]


def _sample_step_errors(mark, channel, operation, source=None):
    # A transfer's errors: those of this call (tagged with the step they happened
    # in) and, for a dispense, those of the aspirate that filled the tip
    # (*source* is that channel's _sample_channel_source entry) -- an aspirate
    # from a tube rack is never shown as an event of its own, so its errors would
    # otherwise appear nowhere.
    own = [dict(entry, during=operation) for entry in _sample_errors_since(mark, channel)]
    if operation == "dispense" and source:
        return list(source.get("errors") or []) + own
    return own


def _record_sample_event(
    client, labware, well, *, operation, channel, volume, success, error, source_labware, source_well,
    transfer_id=None, source_transfer_id=None, source_barcode=None, details=None, errors=None,
    source_barcode_type=None, source_lineage=None,
):
    # operation: "aspirate" | "dispense". channel: int, or the literal string
    # "MPH" for the 96-head. source_labware/source_well are only meaningful
    # for "dispense" (resolved via _sample_channel_source) -- an "aspirate"
    # event has no source of its own; this well itself IS the source for
    # whatever downstream dispense uses it (see module docstring item 8).
    # transfer_id identifies THIS event's own (channel, call) pair, for
    # matching against a same-id tadm_result if adc=True was set on this
    # call. source_transfer_id (dispense only) is the paired aspirate's own
    # transfer_id, letting the frontend show both curves for one transfer.
    # source_barcode (dispense only) is the scanned barcode of whatever this
    # channel last aspirated from -- a specific tube's barcode if the source
    # was a scanned tube rack, or None if that source was never scanned (see
    # _sample_source_barcode); source_barcode_type says which of the two it is
    # ("well", or the source labware's class for a labware barcode).
    # source_lineage (dispense only) is the well barcodes this well inherits.
    # details: extra per-transfer fields for the labware report -- see
    # _sample_transfer_details (liquid_class, lld, liquid_level_mm,
    # liquid_volume_ul; for a dispense, those of its source aspirate).
    # errors: the instrument errors answered during this call that belong to
    # this channel, each with the recovery submitted -- see
    # _record_sample_error_recovery and _sample_step_errors. Present on a
    # transfer that went on to succeed as well as on one that failed.
    if operation == "dispense" and not _is_liquid_waste(labware) and _is_reservoir_labware(client, labware):
        # Dispensing INTO a reservoir is a refill, not "delivering to a
        # sample" -- Sample Tracking only ever cards labware a script is
        # actually filling with something worth visualizing per-well, so
        # this is a complete no-op (no ledger, no target, no event). The
        # liquid waste is the exception: the Vantage's reports itself as a
        # reservoir, but it is where removed liquid goes, so it is a target.
        return

    if operation == "dispense" and success and source_lineage:
        held = _sample_well_lineage.setdefault((str(labware).lower(), str(well)), [])
        held.extend(barcode for barcode in source_lineage if barcode not in held)

    key = f"{labware}@{well}"
    current = _sample_well_volumes.get(key, 0.0)
    volume = volume or 0.0
    if operation == "dispense":
        current = current + volume
        if labware not in _sample_target_labware:
            _sample_target_labware.add(labware)
            _announce_sample_labware(client, labware)
    else:
        # Never let the tracked volume go negative, even if the script
        # aspirates more than was ever tracked as dispensed/present.
        current = max(0.0, current - volume)
    _sample_well_volumes[key] = current

    payload = {
        "labware": labware,
        "well": well,
        "operation": operation,
        "channel": channel,
        "volume": volume,
        "current_volume_ul": current,
        "success": success,
        "error": error,
        "source_labware": source_labware,
        "source_well": source_well,
        "source_key": _sample_source_key(source_labware, source_well),
        "transfer_id": transfer_id,
        "source_transfer_id": source_transfer_id,
        "source_barcode": source_barcode,
        "source_barcode_type": source_barcode_type if source_barcode else None,
        "liquid_class": None,
        "lld": False,
        "liquid_level_mm": None,
        "liquid_volume_ul": None,
        "errors": errors or [],
    }
    payload.update(details or {})

    # Only ever emitted (and therefore only ever rendered) once this well's
    # labware has become a target -- until then the event is held, and sent
    # with the rest of the labware's history when a dispense makes it one.
    if labware not in _sample_target_labware:
        payload["timestamp"] = _datetime.now(_timezone.utc).isoformat()
        _sample_pending_events.setdefault(labware, []).append(payload)
        return
    for pending in _sample_pending_events.pop(labware, []):
        print(f"\x00SAMPLE\x00{json.dumps(pending)}", flush=True)
    print(f"\x00SAMPLE\x00{json.dumps(payload)}", flush=True)


def _per_channel_value(value, index):
    # Settings and liquid_class may be one value for every channel or a
    # per-channel list aligned with the call's channels.
    if isinstance(value, (list, tuple)):
        return value[index] if 0 <= index < len(value) else None
    return value


def _sample_transfer_details(bound, channels_arg, channel, channel_data=None):
    """Liquid class and, when cLLD was on for *channel*, the liquid level and
    measured volume VENUS reported for an aspirate (channel_data is that
    channel's response entry). A dispense reuses its source aspirate's details."""
    try:
        index = list(channels_arg).index(channel)
    except ValueError:
        index = -1
    liquid_class = _per_channel_value(bound.arguments.get("liquid_class"), index)
    settings = bound.arguments.get("settings")
    clld = _per_channel_value(getattr(settings, "capacitive_lld", 0), index) if settings is not None else 0
    try:
        lld = int(getattr(clld, "value", clld) or 0) > 0
    except (TypeError, ValueError):
        lld = False
    level = getattr(channel_data, "liquid_level_mm", None) if (lld and channel_data is not None) else None
    measured = getattr(channel_data, "liquid_volume_ul", None) if (lld and channel_data is not None) else None
    return {
        "liquid_class": str(liquid_class) if liquid_class else None,
        "lld": lld,
        "liquid_level_mm": level,
        "liquid_volume_ul": measured,
    }


def _record_tadm_result(transfer_id, channel, curve):
    # One message per TADM curve found on an adc=True aspirate/dispense
    # response -- see _patch_sample_tracking, which mints transfer_id (the
    # same id passed to _record_sample_event for this exact (call, channel)
    # event) and matches curves to channels via curve.channel_number.
    curve_points = [
        {"time_ms": p.time_ms, "pressure": p.pressure}
        for p in (getattr(curve, "curve_points", None) or [])
    ]
    payload = {
        "transfer_id": transfer_id,
        "channel": channel,
        "step_type_name": getattr(curve, "step_type_name", ""),
        "liquid_class_name": getattr(curve, "liquid_class_name", "") or "",
        "volume": getattr(curve, "volume", None),
        "curve_flagged": bool(getattr(curve, "curve_flagged", 0)),
        "error_code": str(getattr(curve, "error", 0)) if getattr(curve, "error", 0) else None,
        "curve_points": curve_points,
    }
    print(f"\x00TADM\x00{json.dumps(payload)}", flush=True)


def _patch_sample_tracking(client_cls, method_name, impl_name, operation, channel_pitch_mm):
    original = getattr(client_cls, method_name, None)
    if original is None:
        return
    # See _patch_reservoir_tracking's comment: the public method is a generic
    # (self, *args, **kwargs) passthrough, so bind against the real _xxx_impl
    # signature instead to actually recover "positions"/"channels" by name.
    # Applied AFTER _patch_reservoir_tracking in _patch_instrument_clients, so
    # for aspirate/aspirate_5ml `original` here is already that patch's
    # wrapper -- both layers stack and fire independently on every call.
    impl = getattr(client_cls, impl_name, None)
    sig = inspect.signature(impl) if impl is not None else inspect.signature(original)

    def patched(self, *args, **kwargs):
        caught_exc = None
        result = None
        error_mark = _sample_errors_mark()
        try:
            result = original(self, *args, **kwargs)
        except Exception as exc:
            caught_exc = exc
        try:
            from hamilton_venus.models.position import normalize_positions

            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()
            positions_arg = bound.arguments.get("positions")
            channels_arg = bound.arguments.get("channels") or getattr(self, "_DEFAULT_CHANNELS", None) or list(range(1, 9))
            volumes_arg = bound.arguments.get("volumes")
            overall_success = caught_exc is None and (result.success if result is not None else False)
            error_message = str(caught_exc) if caught_exc is not None else None

            channel_data = getattr(result.return_parameters, "channels", None) if result is not None else None
            normalized = normalize_positions(
                positions_arg, channel_count=len(channels_arg),
                get_spec=self.get_labware_spec, channel_pitch_mm=channel_pitch_mm,
            )

            # TADM curves come back on the response whenever TADM is on for
            # the step -- adc=True, or a liquid class with TADM enabled (the
            # common case, and no adc involved) -- so read whatever the
            # response carries rather than keying off the adc argument.
            tadm_curves_by_channel = {}
            if result is not None:
                tadm = getattr(result.return_parameters, "tadm", None)
                for curve in getattr(tadm, "tadm_curves", None) or []:
                    tadm_curves_by_channel[getattr(curve, "channel_number", None)] = curve

            if channel_data:
                # Preferred path: the response's own per-channel data gives
                # the ACTUAL aspirated/dispensed volume (which may differ
                # from what was requested) -- same source
                # _record_reservoir_aspirate already reads for Consumables.
                channel_to_pos = dict(zip(channels_arg, normalized))
                for cd in channel_data:
                    pos = channel_to_pos.get(cd.channel)
                    if pos is None:
                        continue
                    actual_volume = getattr(cd, "aspirated_volume", None)
                    if actual_volume is None:
                        actual_volume = getattr(cd, "dispensed_volume", None)
                    source_labware = source_well = source_transfer_id = source_barcode = None
                    source_barcode_type = source_lineage = None
                    if operation == "dispense":
                        src = _sample_channel_source.get(cd.channel)
                        details = (src or {}).get("details")
                        if src:
                            source_labware, source_well = src["labware"], src["well"]
                            source_transfer_id = src.get("transfer_id")
                            source_barcode = src.get("barcode")
                            source_barcode_type = src.get("barcode_type")
                            source_lineage = src.get("lineage")
                    else:
                        details = _sample_transfer_details(bound, channels_arg, cd.channel, cd)
                    transfer_id = _next_sample_transfer_id()
                    _record_sample_event(
                        self, pos.labware, pos.well, operation=operation, channel=cd.channel,
                        volume=actual_volume, success=overall_success, error=error_message,
                        source_labware=source_labware, source_well=source_well,
                        transfer_id=transfer_id, source_transfer_id=source_transfer_id,
                        source_barcode=source_barcode, details=details,
                        source_barcode_type=source_barcode_type, source_lineage=source_lineage,
                        errors=_sample_step_errors(error_mark, cd.channel, operation, src if operation == "dispense" else None),
                    )
                    curve = tadm_curves_by_channel.get(cd.channel)
                    if curve is not None:
                        _record_tadm_result(transfer_id, cd.channel, curve)
                    if operation == "aspirate" and overall_success:
                        src_labware, src_well = _sample_source_position(self, pos.labware, pos.well)
                        barcode, barcode_type, lineage = _sample_source_barcode(self, pos.labware, pos.well)
                        _sample_channel_source[cd.channel] = {
                            "labware": src_labware, "well": src_well, "transfer_id": transfer_id,
                            "barcode": barcode, "barcode_type": barcode_type, "lineage": lineage,
                            "details": details,
                            "errors": _sample_step_errors(error_mark, cd.channel, operation),
                        }
            else:
                # No usable response (the call raised before returning one, or
                # returned zero channel entries) -- fall back to what was
                # actually requested, so a failed transfer still produces one
                # event per intended well.
                volumes_list = volumes_arg if isinstance(volumes_arg, list) else [volumes_arg] * len(channels_arg)
                for channel, pos, volume in zip(channels_arg, normalized, volumes_list):
                    source_labware = source_well = source_transfer_id = source_barcode = None
                    source_barcode_type = source_lineage = None
                    if operation == "dispense":
                        src = _sample_channel_source.get(channel)
                        details = (src or {}).get("details")
                        if src:
                            source_labware, source_well = src["labware"], src["well"]
                            source_transfer_id = src.get("transfer_id")
                            source_barcode = src.get("barcode")
                            source_barcode_type = src.get("barcode_type")
                            source_lineage = src.get("lineage")
                    else:
                        details = _sample_transfer_details(bound, channels_arg, channel)
                    transfer_id = _next_sample_transfer_id()
                    _record_sample_event(
                        self, pos.labware, pos.well, operation=operation, channel=channel,
                        volume=volume, success=overall_success, error=error_message,
                        source_labware=source_labware, source_well=source_well,
                        transfer_id=transfer_id, source_transfer_id=source_transfer_id,
                        source_barcode=source_barcode, details=details,
                        source_barcode_type=source_barcode_type, source_lineage=source_lineage,
                        errors=_sample_step_errors(error_mark, channel, operation, src if operation == "dispense" else None),
                    )
                    curve = tadm_curves_by_channel.get(channel)
                    if curve is not None:
                        _record_tadm_result(transfer_id, channel, curve)
        except Exception as exc:
            print(f"[script-runner] sample tracking error ({operation}): {exc}", flush=True)
        if caught_exc is not None:
            raise caught_exc
        return result

    setattr(client_cls, method_name, patched)


def _patch_mph96_sample_tracking(client_cls, method_name, operation, impl_name=None):
    original = getattr(client_cls, method_name, None)
    if original is None:
        return
    # For aspirate_mph96, `original` here is already _patch_mph96_reservoir_
    # tracking's own wrapper (that patch runs first) -- its generic
    # (self, *args, **kwargs) signature can't recover real argument names, so
    # bind against the stable pre-wrap signature the caller passes via
    # impl_name instead (see _patch_mph96_reservoir_tracking). dispense_mph96
    # is never double-wrapped, so it has no impl_name and uses `original`
    # directly, same as before.
    impl = getattr(client_cls, impl_name, None) if impl_name else None
    sig = inspect.signature(impl) if impl is not None else inspect.signature(original)

    def patched(self, *args, **kwargs):
        caught_exc = None
        result = None
        error_mark = _sample_errors_mark()
        try:
            result = original(self, *args, **kwargs)
        except Exception as exc:
            caught_exc = exc
        try:
            from hamilton_venus.models.position import normalize_positions

            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()
            labware_id = bound.arguments.get("labware_id")
            mph_pattern = bound.arguments.get("mph_pattern")
            volume = bound.arguments.get("volume") or 0.0
            overall_success = caught_exc is None and (result.success if result is not None else False)
            error_message = str(caught_exc) if caught_exc is not None else None

            # Explicit well ids resolve to those specific wells; None or a
            # list of ints (tip/channel indices, not well ids -- there is no
            # reliable primitive in this SDK to map those to physical wells)
            # falls back to treating the whole labware as touched, matching
            # _patch_mph96_reservoir_tracking's own existing precedent of not
            # resolving per-well for MPH96.
            if mph_pattern and all(isinstance(w, str) for w in mph_pattern):
                selector = f"{labware_id}@wells:{','.join(mph_pattern)}"
            else:
                selector = f"{labware_id}@all"
            try:
                normalized = normalize_positions(selector, get_spec=self.get_labware_spec)
            except Exception as exc:
                print(f"[script-runner] sample tracking: could not resolve MPH96 wells for {labware_id!r}: {exc}", flush=True)
                normalized = []

            for pos in normalized:
                source_labware = source_well = None
                if operation == "dispense":
                    src = _sample_channel_source.get("MPH")
                    if src:
                        source_labware, source_well = src["labware"], src["well"]
                _record_sample_event(
                    self, pos.labware, pos.well, operation=operation, channel="MPH",
                    volume=volume, success=overall_success, error=error_message,
                    source_labware=source_labware, source_well=source_well,
                    errors=_sample_errors_since(error_mark),
                )
            if operation == "aspirate" and overall_success and normalized:
                # The MPH96 head lifts from (up to) 96 wells at once and has
                # no per-well fan-out on dispense -- "source" for a later MPH
                # dispense is attributed to this whole labware (well "*" is a
                # sentinel, never itself rendered as a real breakdown entry).
                _sample_channel_source["MPH"] = {"labware": labware_id, "well": "*"}
        except Exception as exc:
            print(f"[script-runner] sample tracking error (mph96 {operation}): {exc}", flush=True)
        if caught_exc is not None:
            raise caught_exc
        return result

    setattr(client_cls, method_name, patched)


def _patch_dispense_on_the_fly_sample_tracking(client_cls, method_name, impl_name):
    # dispense_on_the_fly/_5ml has no "positions" selector at all -- it
    # translates the head across X in one continuous pass, dispensing the
    # SAME volume into every well of labware_name except whatever's listed in
    # excluded_positions (confirmed against _dispense_on_the_fly_impl's real
    # signature: channels, labware_name, volumes, ..., excluded_positions).
    # The response is a plain CommandResponse (no per-channel breakdown), so
    # there's no per-well measured volume to read back -- every touched well
    # is recorded with the single requested volume, per spec.
    original = getattr(client_cls, method_name, None)
    if original is None:
        return
    impl = getattr(client_cls, impl_name, None)
    sig = inspect.signature(impl) if impl is not None else inspect.signature(original)

    def patched(self, *args, **kwargs):
        caught_exc = None
        result = None
        error_mark = _sample_errors_mark()
        try:
            result = original(self, *args, **kwargs)
        except Exception as exc:
            caught_exc = exc
        try:
            from hamilton_venus.models.position import normalize_positions

            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()
            labware = bound.arguments.get("labware_name")
            channels_arg = sorted(bound.arguments.get("channels") or [])
            volumes_arg = bound.arguments.get("volumes")
            excluded = set(bound.arguments.get("excluded_positions") or [])
            volume = volumes_arg[0] if isinstance(volumes_arg, list) and volumes_arg else volumes_arg
            overall_success = caught_exc is None and (result.success if result is not None else False)
            error_message = str(caught_exc) if caught_exc is not None else None

            # No single well maps to a single engaged channel here (the head
            # sweeps every engaged channel across every column in one pass) --
            # the full engaged-channel set is shown for every touched well
            # rather than fabricating a false one-channel-per-well precision.
            channel_label = ",".join(str(ch) for ch in channels_arg) if channels_arg else "?"
            # Best-effort source: whichever channel is first in the engaged
            # set, on the (typical) assumption a script primes every engaged
            # channel from the same source before an on-the-fly pass.
            source_labware = source_well = None
            if channels_arg:
                src = _sample_channel_source.get(channels_arg[0])
                if src:
                    source_labware, source_well = src["labware"], src["well"]

            all_wells = normalize_positions(f"{labware}@all", get_spec=self.get_labware_spec)
            for pos in all_wells:
                if pos.well in excluded:
                    continue
                _record_sample_event(
                    self, pos.labware, pos.well, operation="dispense", channel=channel_label,
                    volume=volume, success=overall_success, error=error_message,
                    source_labware=source_labware, source_well=source_well,
                    errors=_sample_errors_since(error_mark),
                )
        except Exception as exc:
            print(f"[script-runner] sample tracking error (dispense_on_the_fly): {exc}", flush=True)
        if caught_exc is not None:
            raise caught_exc
        return result

    setattr(client_cls, method_name, patched)


def _patch_autoload_scan_tracking(client_cls, method_name):
    # Captures barcodeReturns from an autoload.loadCarrierBy* call so a later
    # sample_event/labware_info can look a barcode up by (carrier, position)
    # -- see _carrier_site_barcodes and _resolve_well_barcode/
    # _resolve_labware_barcode. Only ever populated when the script itself
    # passed scan_positions; an unscanned load leaves the ledger untouched.
    original = getattr(client_cls, method_name, None)
    if original is None:
        return

    def patched(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        try:
            rp = getattr(result, "return_parameters", None)
            carrier_labware_id = getattr(rp, "carrier_labware_id", "") if rp is not None else ""
            for entry in getattr(rp, "barcode_returns", None) or []:
                barcode = getattr(entry, "barcode", "")
                position = getattr(entry, "position", "")
                if not barcode or not position or not carrier_labware_id:
                    continue
                _carrier_site_barcodes[(str(carrier_labware_id).lower(), str(position))] = barcode
        except Exception as exc:
            print(f"[script-runner] barcode tracking error ({method_name}): {exc}", flush=True)
        return result

    setattr(client_cls, method_name, patched)


def _record_assigned_barcodes(client, labware, barcodes, well_order):
    # Mirrors set_barcodes' own two call forms (positions + barcodes, or explicit
    # labware entries) into _assigned_labware_barcodes/_assigned_well_barcodes.
    entries = labware if isinstance(labware, list) else [labware]
    if barcodes is None:
        from hamilton_venus.models.command_types import TrackingLabwareBarcodes

        for entry in entries:
            item = entry if isinstance(entry, TrackingLabwareBarcodes) else TrackingLabwareBarcodes.model_validate(entry)
            key = str(item.labware_id).lower()
            if item.barcode:
                _assigned_labware_barcodes[key] = item.barcode
            for well in item.wells or []:
                _assigned_well_barcodes[(key, str(well.id))] = well.barcode
        return
    values = iter([barcodes] if isinstance(barcodes, str) else list(barcodes))
    for entry in entries:
        labware_id, wells = client._tracking_wells(entry, well_order)
        key = str(labware_id).lower()
        if wells is None:
            _assigned_labware_barcodes[key] = next(values)
        else:
            for well in wells:
                _assigned_well_barcodes[(key, str(well))] = next(values)


def _patch_set_barcodes_tracking(client_cls):
    # A script can barcode labware and wells itself through sample tracking
    # (set_barcodes): remember what it assigned (it replaces a scanned barcode
    # for the same labware/well from then on) and refresh any card already
    # showing that labware.
    original = getattr(client_cls, "set_barcodes", None)
    if original is None:
        return
    sig = inspect.signature(original)

    def patched(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        try:
            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()
            _record_assigned_barcodes(
                self, bound.arguments.get("labware"), bound.arguments.get("barcodes"), bound.arguments.get("well_order"),
            )
        except Exception as exc:
            print(f"[script-runner] barcode tracking error (set_barcodes ledger): {exc}", flush=True)
        try:
            _refresh_sample_labware_barcodes(self)
        except Exception as exc:
            print(f"[script-runner] barcode tracking error (set_barcodes): {exc}", flush=True)
        return result

    setattr(client_cls, "set_barcodes", patched)


def _patch_labware_site_tracking(client_cls, method_name):
    # Records which (carrier, site) a plate/reservoir/lidded-plate was added
    # to, so a barcode scanned on that CARRIER's site (see
    # _patch_autoload_scan_tracking) can later be attributed to whichever
    # labware actually sits there -- see _labware_carrier_site and
    # _resolve_labware_barcode. Tube racks don't need this: they're added via
    # add_tube_carrier (no carrier/site of their own -- they're scanned AS
    # the carrier), so their barcodes resolve directly by well instead.
    original = getattr(client_cls, method_name, None)
    if original is None:
        return
    sig = inspect.signature(original)

    def patched(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        try:
            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()
            carrier_id = bound.arguments.get("carrier_id")
            site = bound.arguments.get("site")
            if not carrier_id or not site:
                return result
            rp = getattr(result, "return_parameters", None)
            labware_id = rp.get("labwareName") if isinstance(rp, dict) else getattr(rp, "labware_name", None)
            if labware_id:
                _labware_carrier_site[str(labware_id).lower()] = (str(carrier_id).lower(), str(site))
        except Exception as exc:
            print(f"[script-runner] labware-site tracking error ({method_name}): {exc}", flush=True)
        return result

    setattr(client_cls, method_name, patched)


def _patch_instrument_clients():
    # Force this run's simulate/trace/log-level/run-log settings into whichever
    # of StarClient/VantageClient the stored script actually constructs -- the
    # script's own source text decides which instrument it targets; this
    # bootstrap just makes either one behave correctly once constructed.
    # Printed up front (plain stdout, so it lands in the Terminal tab) since
    # it's otherwise invisible whether this actually took effect versus
    # whatever the script itself hardcoded.
    logging_note = "debug logging" if _DEBUG_LOGGING_ENABLED else "INFO logging (debug logging is off in Settings)"
    print(f"[script-runner] Forcing simulate={_FORCED_SIMULATE!r}, {logging_note}, and run-log capture for this run.", flush=True)
    try:
        import hamilton_venus
        from hamilton_venus.config import RunLogConfig
    except Exception as exc:
        print(f"[script-runner] Could not import hamilton_venus -- simulate/logging/run-log forcing will NOT apply: {exc}", flush=True)
        return

    _patch_client_class(hamilton_venus.StarClient, RunLogConfig)
    _patch_client_class(hamilton_venus.VantageClient, RunLogConfig)
    _patch_sample_error_capture()

    from hamilton_venus.constants import CHANNEL_PITCH_MM_1ML, CHANNEL_PITCH_MM_5ML

    for client_cls in (hamilton_venus.StarClient, hamilton_venus.VantageClient):
        _patch_tip_pool_tracking(client_cls, "tip_pickup", "_tip_pickup_impl")
        _patch_tip_pool_tracking(client_cls, "tip_pickup_5ml", "_tip_pickup_impl")
        _patch_mph96_tip_pool_tracking(client_cls)
        _patch_tip_counter_invalidation(client_cls)
        _patch_reservoir_tracking(client_cls, "aspirate", CHANNEL_PITCH_MM_1ML, "_aspirate_impl")
        _patch_reservoir_tracking(client_cls, "aspirate_5ml", CHANNEL_PITCH_MM_5ML, "_aspirate_impl")
        _patch_mph96_reservoir_tracking(client_cls)
        _patch_sample_tracking(client_cls, "aspirate", "_aspirate_impl", "aspirate", CHANNEL_PITCH_MM_1ML)
        _patch_sample_tracking(client_cls, "aspirate_5ml", "_aspirate_impl", "aspirate", CHANNEL_PITCH_MM_5ML)
        _patch_sample_tracking(client_cls, "dispense", "_dispense_impl", "dispense", CHANNEL_PITCH_MM_1ML)
        _patch_sample_tracking(client_cls, "dispense_5ml", "_dispense_impl", "dispense", CHANNEL_PITCH_MM_5ML)
        _patch_mph96_sample_tracking(client_cls, "aspirate_mph96", "aspirate", impl_name="_aspirate_mph96_impl")
        _patch_mph96_sample_tracking(client_cls, "dispense_mph96", "dispense")
        _patch_dispense_on_the_fly_sample_tracking(client_cls, "dispense_on_the_fly", "_dispense_on_the_fly_impl")
        _patch_dispense_on_the_fly_sample_tracking(client_cls, "dispense_on_the_fly_5ml", "_dispense_on_the_fly_impl")
        # MagPip (Vantage only -- StarClient has none of these methods, so every
        # _patch_* helper's getattr(client_cls, method_name, None) guard makes
        # all of this a no-op there). aspirate_magpip is wrapped twice below
        # (reservoir tracking, then sample tracking), so its true signature is
        # stashed once under a name neither wrap itself replaces -- same fix,
        # same reason, as aspirate_mph96 just above.
        _patch_tip_pool_tracking(client_cls, "tip_pickup_magpip", "tip_pickup_magpip")
        if getattr(client_cls, "aspirate_magpip", None) is not None and not hasattr(client_cls, "_aspirate_magpip_impl"):
            client_cls._aspirate_magpip_impl = client_cls.aspirate_magpip
        _patch_reservoir_tracking(client_cls, "aspirate_magpip", CHANNEL_PITCH_MM_1ML, "_aspirate_magpip_impl")
        _patch_sample_tracking(client_cls, "aspirate_magpip", "_aspirate_magpip_impl", "aspirate", CHANNEL_PITCH_MM_1ML)
        _patch_sample_tracking(client_cls, "dispense_magpip", "dispense_magpip", "dispense", CHANNEL_PITCH_MM_1ML)
        _patch_dispense_on_the_fly_sample_tracking(client_cls, "dispense_on_the_fly_magpip", "dispense_on_the_fly_magpip")
        _patch_autoload_scan_tracking(client_cls, "autoload_load_carrier_by_id")
        _patch_autoload_scan_tracking(client_cls, "autoload_load_carrier_by_track")
        _patch_set_barcodes_tracking(client_cls)
        _patch_labware_site_tracking(client_cls, "add_plate")
        _patch_labware_site_tracking(client_cls, "add_reservoir")
        _patch_labware_site_tracking(client_cls, "add_lidded_plate")


def _input_via_manager(prompt=""):
    """Installed as builtins.input (see below), so any input() call anywhere in
    the script -- a raw call, or via a script-local wrapper like
    plate_stamp_demo.py's get_user_int() -- transparently round-trips through
    the parent process instead of blocking on a stdin that's exclusively owned
    by _control_reader's stdin-reading thread and would otherwise hang forever.
    Same \\x00MARKER\\x00<json> out / threading.Event-per-uuid shape as
    _on_operator_escalation/_ensure_tip_availability above.

    "" is a legitimate real answer, so cancellation (STOP, or an explicit
    Cancel click) is carried as an explicit `cancelled` flag rather than
    inferred from an empty value -- see _control_reader's INPUT_RESPONSE
    handling and its STOP branch below.
    """
    from hamilton_venus.exceptions import OperatorCancelledError

    request_uuid = _uuid_module.uuid4().hex
    event = threading.Event()
    _input_events[request_uuid] = event
    print(f"\x00INPUT_REQUEST\x00{json.dumps({'uuid': request_uuid, 'prompt': str(prompt)})}", flush=True)
    event.wait()
    _input_events.pop(request_uuid, None)
    response = _input_responses.pop(request_uuid, None) or {"value": "", "cancelled": False}
    if response.get("cancelled"):
        raise OperatorCancelledError("Operator cancelled an input prompt.")
    return response.get("value") or ""


def _tk_dialog_request(kind, title, message=None, **extra):
    """Shared round-trip for every patched tkinter.messagebox/simpledialog
    function below (see their assignment onto the submodules at the bottom of
    this bootstrap). Separate from _input_via_manager's event/response dicts
    since each `kind` has its own value type and cancel semantics (a plain
    input()-style str-always/cancelled-flag contract doesn't fit askyesno's
    bool or askinteger's int-or-None) -- None/JSON null is tkinter's own
    unambiguous "cancelled" signal for every kind that has one, so no extra
    flag is needed here. Same \\x00MARKER\\x00<json> out / threading.Event-
    per-uuid shape as _input_via_manager/_on_operator_escalation above.
    """
    request_uuid = _uuid_module.uuid4().hex
    event = threading.Event()
    _tk_dialog_events[request_uuid] = event
    payload = {"uuid": request_uuid, "kind": kind, "title": title, "message": message, **extra}
    print(f"\x00TK_DIALOG_REQUEST\x00{json.dumps(payload)}", flush=True)
    event.wait()
    _tk_dialog_events.pop(request_uuid, None)
    return _tk_dialog_responses.pop(request_uuid, None)


# The following 10 functions replace tkinter.messagebox's/simpledialog's own
# implementations (assigned onto the submodules at the bottom of this
# bootstrap) so no real Tk window is ever constructed -- the script never
# needs to change, whether it calls `messagebox.showinfo(...)` or
# `from tkinter.simpledialog import askinteger; askinteger(...)`, since both
# call styles resolve through the same (now-patched) module attribute.
# Return values mirror real tkinter exactly (verified via inspect.getsource):
# showinfo/showwarning/showerror always return "ok" (the only button);
# askyesno/askokcancel/askretrycancel return bool; askyesnocancel returns
# True/False/None; askinteger/askfloat/askstring return the typed value or
# None on cancel.
def _tk_showinfo(title=None, message=None, **options):
    _tk_dialog_request("showinfo", title, message)
    return "ok"


def _tk_showwarning(title=None, message=None, **options):
    _tk_dialog_request("showwarning", title, message)
    return "ok"


def _tk_showerror(title=None, message=None, **options):
    _tk_dialog_request("showerror", title, message)
    return "ok"


def _tk_askyesno(title=None, message=None, **options):
    return bool(_tk_dialog_request("askyesno", title, message))


def _tk_askokcancel(title=None, message=None, **options):
    return bool(_tk_dialog_request("askokcancel", title, message))


def _tk_askretrycancel(title=None, message=None, **options):
    return bool(_tk_dialog_request("askretrycancel", title, message))


def _tk_askyesnocancel(title=None, message=None, **options):
    return _tk_dialog_request("askyesnocancel", title, message)


def _tk_askinteger(title, prompt, **kw):
    minvalue, maxvalue = kw.get("minvalue"), kw.get("maxvalue")
    value = _tk_dialog_request(
        "askinteger", title, prompt,
        minvalue=minvalue, maxvalue=maxvalue, initialvalue=kw.get("initialvalue"),
    )
    if value is None:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    # Defensive re-validation against a stale/malformed response -- the
    # browser modal already enforces this inline, this is a backstop.
    if minvalue is not None and value < minvalue:
        return None
    if maxvalue is not None and value > maxvalue:
        return None
    return value


def _tk_askfloat(title, prompt, **kw):
    minvalue, maxvalue = kw.get("minvalue"), kw.get("maxvalue")
    value = _tk_dialog_request(
        "askfloat", title, prompt,
        minvalue=minvalue, maxvalue=maxvalue, initialvalue=kw.get("initialvalue"),
    )
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if minvalue is not None and value < minvalue:
        return None
    if maxvalue is not None and value > maxvalue:
        return None
    return value


def _tk_askstring(title, prompt, **kw):
    value = _tk_dialog_request(
        "askstring", title, prompt,
        initialvalue=kw.get("initialvalue"), show=kw.get("show"),
    )
    return None if value is None else str(value)


def _tk_askchoice(title, prompt, choices, **kw):
    """Non-standard convenience dialog -- NOT part of real tkinter.simpledialog.
    A single-select picker (rendered as a dropdown modal): the formatted-modal
    equivalent of a hand-rolled Toplevel + Listbox (which this interception
    layer can't see -- see the module docstring's "standard convenience
    functions only" scope).
    Injected onto tkinter.simpledialog only inside this bootstrap, so a script
    that wants it must feature-detect (`getattr(simpledialog, "askchoice",
    None)`) and keep its own Listbox fallback for a plain `python script.py`
    run. `choices` is an ordered list of option strings; `initialvalue`
    (optional) pre-selects one. Returns the chosen string, or None on cancel.
    """
    choices = [str(c) for c in choices]
    value = _tk_dialog_request(
        "askchoice", title, prompt,
        options=choices, initialvalue=kw.get("initialvalue"),
    )
    if value is None:
        return None
    value = str(value)
    # Backstop against a stale/hand-fed response -- the modal only ever
    # submits one of the options it was given.
    return value if value in choices else None


def _tk_filedialog_request(kind, **options):
    """Shared round-trip for the 4 patched tkinter.filedialog functions below
    (assigned onto the submodule at the bottom of this bootstrap). Reuses the
    same browser-rendered file browser this app already has (previously
    operator-only, via the shortcut "Browse..." button) rather than trying to
    recreate a native OS file picker as a simple text-field modal -- browsing
    the real local filesystem is exactly what that component already does.
    Same \\x00MARKER\\x00<json> out / threading.Event-per-uuid shape as
    _tk_dialog_request above; null is always the wire cancel signal here too,
    even though the FUNCTION RETURN VALUE the script sees on cancel is ""/()
    per real tkinter's own convention (applied by each patched function).
    """
    request_uuid = _uuid_module.uuid4().hex
    event = threading.Event()
    _tk_filedialog_events[request_uuid] = event
    payload = {
        "uuid": request_uuid,
        "kind": kind,
        "title": options.get("title"),
        "initialdir": options.get("initialdir"),
        "initialfile": options.get("initialfile"),
        "defaultextension": options.get("defaultextension"),
        "filetypes": [list(ft) for ft in (options.get("filetypes") or [])],
    }
    print(f"\x00TK_FILEDIALOG_REQUEST\x00{json.dumps(payload)}", flush=True)
    event.wait()
    _tk_filedialog_events.pop(request_uuid, None)
    return _tk_filedialog_responses.pop(request_uuid, None)


def _tk_askopenfilename(**options):
    value = _tk_filedialog_request("askopenfilename", **options)
    return value if isinstance(value, str) else ""


def _tk_askopenfilenames(**options):
    value = _tk_filedialog_request("askopenfilenames", **options)
    return tuple(value) if isinstance(value, list) else ()


def _tk_asksaveasfilename(**options):
    value = _tk_filedialog_request("asksaveasfilename", **options)
    return value if isinstance(value, str) else ""


def _tk_askdirectory(**options):
    value = _tk_filedialog_request("askdirectory", **options)
    return value if isinstance(value, str) else ""


def _detach_control_channel():
    # The control reader sits in a blocking read on this pipe for the whole run.
    # On Windows, while a synchronous read is pending on a pipe handle, every
    # other operation on that handle (GetFileType, DuplicateHandle) blocks until
    # the read completes. Library imports touch the standard handles (numpy and
    # pandas via platform/subprocess), so `import numpy` hung until the next
    # control line arrived -- in practice the STOP, which then stopped the run.
    # Keep the pipe on a private fd and point the process's stdin at NUL.
    import os
    encoding, errors = sys.stdin.encoding, sys.stdin.errors
    control_fd = os.dup(sys.stdin.fileno())
    null_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null_fd, 0)
    os.close(null_fd)
    sys.stdin = open(0, encoding=encoding, errors=errors, closefd=False)
    return open(control_fd, encoding=encoding, errors=errors)


def _interrupt_script():
    # Raises KeyboardInterrupt in the main thread, where the script runs.
    import _thread
    _thread.interrupt_main()


def _control_reader(control):
    for raw in control:
        cmd = raw.strip()
        if cmd == "PAUSE":
            # _pause_requested is a fallback for a script doing pure-Python work
            # with no pending VENUS call (see _on_script_line/_handle_pause below) --
            # the real pause is VENUS's own executor method, paused directly via
            # the Vector WebAPI so it takes effect at VENUS's own HSL-command
            # granularity, not just at the next top-level script line. This is
            # what actually fixes a compound command (add_reagent, hit_picking,
            # ...) not noticing a pause until its whole internal loop finishes --
            # sys.settrace can't see inside a call into a different source file,
            # but VENUS's executor doesn't care how deep Python's call stack is.
            _pause_requested.set()
            for client in _captured_clients:
                try:
                    client._run(client._connected_instrument.venus.pause_method())
                except Exception as exc:
                    print(f"[script-runner] pause_method() failed: {exc}", flush=True)
        elif cmd == "RESUME":
            # Also set directly (not just left to the runtime-status callback
            # below) so the pure-Python fallback wait can't be stranded if the
            # SignalR round-trip is slow or the resume_method() call below fails.
            _resume_now.set()
            # If PAUSE landed while the script was blocked *inside* a VENUS
            # call (the common case -- that's the whole point of pausing at
            # VENUS's own granularity instead of only at line boundaries),
            # _on_script_line() never got a chance to run and clear this flag while
            # actually paused: it only ever fires between top-level script
            # lines, and there were none to fire on while blocked. Left set,
            # the *next* line _on_script_line() does see -- reached only after this
            # resume already completed -- reads it as a fresh pause request
            # and calls _handle_pause(), silently re-blocking the script with
            # no corresponding VENUS pause and no \x00STATE\x00 sentinel (so
            # the UI still shows "running") until some *later* runtime-status
            # RUNNING event happens to set _resume_now again. Clear it here
            # too, since a resume -- from wherever it's requested -- means
            # any pause request that predates it is moot.
            _pause_requested.clear()
            for client in _captured_clients:
                try:
                    client._run(client._connected_instrument.venus.resume_method())
                except Exception as exc:
                    print(f"[script-runner] resume_method() failed: {exc}", flush=True)
        elif cmd == "STOP":
            # A hard process kill leaves VENUS with a loaded/running method it
            # thinks is still in progress -- instrument_terminate() sends the
            # SDK's own "status.terminate" abort command first, so VENUS tears
            # the method down cleanly (the blocked SDK call in the script's own
            # thread should then raise/return, letting `with StarClient(...)`'s
            # __exit__ run its normal graceful shutdown). The parent waits for
            # that cleanup to finish (the process exiting) before reporting
            # the run stopped.
            #
            # status.terminate goes through the same run-message queue the
            # executor drains, so while VENUS is paused nobody picks it up and
            # instrument_terminate() would block forever. Send it from its own
            # thread, then resume a paused VENUS so it is processed, then wait.
            _stopping.set()
            terminators = []
            for client in _captured_clients:
                def _terminate(client=client):
                    try:
                        client.instrument_terminate()
                    except Exception as exc:
                        print(f"[script-runner] instrument_terminate() failed: {exc}", flush=True)
                thread = threading.Thread(target=_terminate, name="stop-terminate", daemon=True)
                thread.start()
                terminators.append(thread)
            was_paused = _pause_requested.is_set() or bool(_paused_clients)
            for client in _captured_clients if was_paused else []:
                try:
                    client._run(client._connected_instrument.venus.resume_method())
                except Exception as exc:
                    print(f"[script-runner] resume_method() failed: {exc}", flush=True)
            # Also release a pause the script thread is waiting out itself
            # (_handle_pause -- paused between lines, outside any VENUS call).
            _pause_requested.clear()
            _resume_now.set()
            if not _captured_clients:
                # Nothing to terminate in VENUS (the script never connected),
                # so stop the script itself.
                _interrupt_script()
            # Unblock any operator prompt still awaiting a human response --
            # otherwise a STOP mid-escalation would leave the escalation worker
            # thread (and thus this run's teardown) hanging forever.
            for pending_uuid, event in list(_prompt_events.items()):
                _prompt_responses[pending_uuid] = None
                event.set()
            # Same for a pending tip-reload prompt -- resolves as an implicit
            # abort, unblocking _ensure_tip_availability's wait.
            for pending_uuid, event in list(_consumable_prompt_events.items()):
                _consumable_prompt_responses[pending_uuid] = "abort"
                event.set()
            # Same for a pending input() prompt -- resolves as cancelled,
            # unblocking _input_via_manager's wait (it raises OperatorCancelledError
            # rather than returning "", since "" is itself a legitimate answer).
            for pending_uuid, event in list(_input_events.items()):
                _input_responses[pending_uuid] = {"value": None, "cancelled": True}
                event.set()
            # Same for a pending tkinter dialog -- None is already the correct
            # "cancelled" value for every kind that has one (askyesnocancel,
            # askinteger/askfloat/askstring); the no-cancel kinds (showinfo-
            # style, askyesno) never actually observe it since STOP tears the
            # run down regardless.
            for pending_uuid, event in list(_tk_dialog_events.items()):
                _tk_dialog_responses[pending_uuid] = None
                event.set()
            # Same for a pending filedialog prompt -- the patched functions
            # turn a null response into the real-tkinter cancel value ("" or
            # () per kind) on their own.
            for pending_uuid, event in list(_tk_filedialog_events.items()):
                _tk_filedialog_responses[pending_uuid] = None
                event.set()
            for thread in terminators:
                thread.join()
        elif cmd.startswith("ADD_RESERVOIR "):
            try:
                payload = json.loads(cmd[len("ADD_RESERVOIR "):])
            except ValueError:
                continue
            key = f"{payload.get('labware')}@{payload.get('well')}"
            entry = _reservoirs.setdefault(key, {
                "labware": payload.get("labware"), "well": payload.get("well"), "label": payload.get("label") or key,
                "source": "manual", "remaining_volume_ul": None, "total_volume_ul": None, "percent_full": None, "last_updated": None,
                "below_threshold": False,
            })
            entry["label"] = payload.get("label") or entry["label"]
            entry["source"] = "manual"
            print(f"\x00CONSUMABLE\x00{json.dumps({'kind': 'reagent', 'key': key, **entry})}", flush=True)
        elif cmd.startswith("SET_TIP_THRESHOLD "):
            parts = cmd.split(" ", 2)
            if len(parts) == 3:
                pool_name = parts[1]
                try:
                    threshold = int(parts[2])
                except ValueError:
                    continue
                pool = _tip_pools.setdefault(
                    pool_name,
                    {"current_count": None, "total_capacity": None, "low_threshold": _DEFAULT_TIP_THRESHOLD, "below_threshold": False},
                )
                pool["low_threshold"] = threshold
                _emit_tip_update(pool_name)
                _check_tip_threshold(pool_name)
        elif cmd.startswith("CONSUMABLE_PROMPT_RESPONSE "):
            parts = cmd.split(" ", 2)
            resp_uuid = parts[1] if len(parts) > 1 else ""
            action = parts[2].strip().lower() if len(parts) > 2 else ""
            _consumable_prompt_responses[resp_uuid] = action
            event = _consumable_prompt_events.get(resp_uuid)
            if event is not None:
                event.set()
        elif cmd.startswith("PROMPT_RESPONSE "):
            # Two shapes: "PROMPT_RESPONSE <uuid> ACTION <name>" (one action
            # applied uniformly -- Abort/Cancel-style) or "PROMPT_RESPONSE
            # <uuid> CHANNELS <json>" (detail_uuid -> chosen action id, one
            # independent choice per channel). An unrecognized/missing kind
            # resolves to None, same as an empty action -- the SDK treats that
            # as ABORT, which is the safe default for a malformed response.
            parts = cmd.split(" ", 3)
            resp_uuid = parts[1] if len(parts) > 1 else ""
            kind = parts[2] if len(parts) > 2 else ""
            rest = parts[3] if len(parts) > 3 else ""
            if kind == "ACTION":
                response = {"kind": "action", "action": rest or None}
            elif kind == "CHANNELS":
                # <json> is either the plain detail_uuid -> action id map, or
                # {"actions": {...}, "inputs": {detail_uuid: [{id, value}]}}
                # when a chosen action takes inputs (e.g. a typed-in barcode).
                try:
                    parsed = json.loads(rest) if rest else {}
                except ValueError:
                    parsed = {}
                if isinstance(parsed, dict) and isinstance(parsed.get("actions"), dict):
                    channel_actions = parsed["actions"]
                    channel_inputs = parsed.get("inputs") or {}
                else:
                    channel_actions = parsed if isinstance(parsed, dict) else {}
                    channel_inputs = {}
                response = {"kind": "channels", "channel_actions": channel_actions, "channel_inputs": channel_inputs}
            else:
                response = None
            _prompt_responses[resp_uuid] = response
            event = _prompt_events.get(resp_uuid)
            if event is not None:
                event.set()
        elif cmd.startswith("INPUT_RESPONSE "):
            # "INPUT_RESPONSE <uuid> <json-payload>" -- payload is
            # {"value": str|None, "cancelled": bool}, JSON-encoded (mirroring
            # ADD_RESERVOIR's payload style above) so the value can safely
            # contain spaces/unicode/be empty.
            parts = cmd.split(" ", 2)
            resp_uuid = parts[1] if len(parts) > 1 else ""
            try:
                payload = json.loads(parts[2]) if len(parts) > 2 else {}
            except ValueError:
                payload = {}
            _input_responses[resp_uuid] = payload
            event = _input_events.get(resp_uuid)
            if event is not None:
                event.set()
        elif cmd.startswith("TK_DIALOG_RESPONSE "):
            # "TK_DIALOG_RESPONSE <uuid> <json-value>" -- unlike INPUT_RESPONSE,
            # the payload IS the value itself (bool/int/float/str/null), not an
            # object wrapping it -- None/null is already tkinter's own
            # unambiguous "cancelled" signal for every kind that has one.
            parts = cmd.split(" ", 2)
            resp_uuid = parts[1] if len(parts) > 1 else ""
            try:
                value = json.loads(parts[2]) if len(parts) > 2 else None
            except ValueError:
                value = None
            _tk_dialog_responses[resp_uuid] = value
            event = _tk_dialog_events.get(resp_uuid)
            if event is not None:
                event.set()
        elif cmd.startswith("TK_FILEDIALOG_RESPONSE "):
            # "TK_FILEDIALOG_RESPONSE <uuid> <json-value>" -- value is a
            # string path, a list of paths (askopenfilenames), or null
            # (cancel); the patched functions above turn null into the real
            # tkinter cancel value ("" or ()) for the specific kind.
            parts = cmd.split(" ", 2)
            resp_uuid = parts[1] if len(parts) > 1 else ""
            try:
                value = json.loads(parts[2]) if len(parts) > 2 else None
            except ValueError:
                value = None
            _tk_filedialog_responses[resp_uuid] = value
            event = _tk_filedialog_events.get(resp_uuid)
            if event is not None:
                event.set()


def _make_runtime_status_callback(client):
    """Builds this client's NewRuntimeStatus callback -- registered via
    _register_runtime_status_listener once the client is connected. Fires on
    EVERY runtime-status transition VENUS reports for this client's executor
    method, regardless of whether Script Manager itself requested the
    pause/resume (via _control_reader's PAUSE/RESUME handling above) or an
    operator triggered it directly from VENUS's own Run Control panel -- that
    second case is exactly what lets Script Manager's UI stay correct when
    "a user may resume from VENUS" rather than only through this app's own
    Pause/Resume button.

    Runs on the client's own background event-loop thread (same thread the
    SignalR listener dispatches all its callbacks on).

    Deliberately does NOT send frontCover.lock/unlock from here: that command
    is dispatched over the same run-message "action" queue the paused
    executor HSL loop itself drains, so a frontCover.unlock sent while
    genuinely paused would just sit queued, unprocessed, until resume --
    exactly backwards from what's needed. Front-cover handling during a real
    VENUS-level pause is left to VENUS's own behavior rather than this app
    trying to drive it.
    """
    from hamilton_venus.models.enums import ExecutorEvent

    async def _on_runtime_status(event) -> None:
        if _stopping.is_set():
            # STOP resumes a paused VENUS only so it can process the terminate;
            # the run is stopping, not running again.
            return
        if event.event == ExecutorEvent.PAUSED and id(client) not in _paused_clients:
            _paused_clients.add(id(client))
            print("\x00STATE\x00paused", flush=True)
        elif event.event == ExecutorEvent.RUNNING and id(client) in _paused_clients:
            _paused_clients.discard(id(client))
            # Unblocks _handle_pause()'s fallback wait even when the resume was
            # triggered externally at VENUS rather than via this app's RESUME.
            _resume_now.set()
            # Same reasoning as _control_reader's RESUME branch: an operator
            # resuming directly from VENUS also moots any pause request
            # _on_script_line() hasn't had a chance to observe yet (it only runs
            # between top-level script lines, and there may have been none
            # while genuinely paused) -- leaving it set would trigger a
            # spurious, silent re-pause on the next line _on_script_line() does see.
            _pause_requested.clear()
            print("\x00STATE\x00running", flush=True)

    return _on_runtime_status


_listener_registered_clients = set()


def _register_runtime_status_listener(client):
    # Guarded like _report_serial_number's _serial_number_reported -- a script
    # may call instrument_connect() more than once, or use both a context
    # manager and an explicit connect, and this must only ever register once
    # per client (a second registration would double-fire every transition).
    if id(client) in _listener_registered_clients:
        return
    _listener_registered_clients.add(id(client))
    try:
        client._connected_instrument._listener.on_runtime_status(_make_runtime_status_callback(client))
    except Exception as exc:
        print(f"[script-runner] could not register pause/resume state listener: {exc}", flush=True)


def _handle_pause():
    # Fallback for the moment a script is doing pure-Python work with no
    # pending VENUS call -- there's nothing for the executor-level pause
    # (triggered in _control_reader above) to "catch" in that case, so this
    # just blocks the script thread itself. Front-cover lock/unlock and the
    # \x00STATE\x00 sentinel are NOT this function's job any more -- they're
    # driven by _make_runtime_status_callback below, off VENUS's own SignalR
    # truth, since that fires with the right timing regardless of whether the
    # pause/resume was requested from here or triggered externally at VENUS's
    # own Run Control panel.
    _resume_now.clear()
    _resume_now.wait()


_last_exception_line = None

# Script-line reporting. Printing (and flushing) a sentinel for every executed
# line made a tight loop hundreds of times slower than in a terminal, and the
# parent turns each one into a websocket message -- once the pipe filled, the
# script ran at the UI's speed. So a line is only reported when it ran for at
# least _LINE_MIN_SECONDS (anything that talks to VENUS does, which is what
# the run summary's line lookup needs), or -- via _line_reporter -- once it has
# been running for _LINE_STALE_SECONDS, so the UI follows a long call. Each
# report carries the line's own start time, so the throttling does not skew
# the timeline. _current_line is [lineno, started_at, reported], replaced
# whole on every line so the reporter thread always sees a consistent entry.
_LINE_MIN_SECONDS = 0.002
_LINE_STALE_SECONDS = 0.1
_current_line = None


def _report_line(entry):
    entry[2] = True
    sys.stdout.write(f"\x00LINE\x00{entry[0]} {entry[1]:.6f}\n")
    sys.stdout.flush()


def _stop_script_if_requested():
    # STOP can't always end the run through VENUS: a client still connecting
    # isn't started, so its terminate (and a pause before it) fails, and the
    # script would carry on once the connect finishes. Ending the script at its
    # next line covers that. KeyboardInterrupt, so a script's own
    # `except Exception:` can't swallow it; `with StarClient(...)` still shuts
    # the client down on the way out.
    if _stopping.is_set():
        raise KeyboardInterrupt("stopped from the Script Manager")


def _on_script_line(lineno):
    global _current_line
    now = time.time()
    previous = _current_line
    if previous is not None and not previous[2] and now - previous[1] >= _LINE_MIN_SECONDS:
        _report_line(previous)
    _stop_script_if_requested()
    # The previous line has fully finished executing by the time we're
    # called for the next one, so checking here -- before running the next
    # line -- never interrupts an in-flight instrument call.
    if _pause_requested.is_set():
        _pause_requested.clear()
        _report_line([lineno, now, False])
        _handle_pause()
        _stop_script_if_requested()  # STOP while paused here releases the pause
        _current_line = [lineno, time.time(), True]
        return
    _current_line = [lineno, now, False]


def _line_reporter():
    while True:
        time.sleep(_LINE_STALE_SECONDS / 2)
        entry = _current_line
        if entry is not None and not entry[2] and time.time() - entry[1] >= _LINE_STALE_SECONDS:
            _report_line(entry)


def _on_script_exception(lineno, exc_value):
    # Fires once for every exception that passes through a script frame --
    # including the script's own `except ...: raise SomeError(...) from e`
    # cleanup, which would otherwise overwrite the real failure line with
    # wherever that re-raise happens to sit. `__cause__`/`__context__` are
    # only set on a chained/re-raised exception, so only overwrite the
    # captured line when this looks like a genuinely new, unrelated
    # failure -- keeping whichever line first raised.
    global _last_exception_line
    is_rechain = exc_value.__cause__ is not None or exc_value.__context__ is not None
    if _last_exception_line is None or not is_rechain:
        _last_exception_line = lineno
        print(f"\x00ERRLINE\x00{lineno}", flush=True)


def _start_line_monitoring():
    """Follow the script's lines with sys.monitoring. Unlike sys.settrace,
    which is called for every function call anywhere, a LINE callback can
    return DISABLE for a location, which turns that location's
    instrumentation off for good -- so library code (pandas, numpy, the SDK)
    costs one callback per line location, once, and then runs at full speed.
    Returns the tool id to release at the end, or None if every tool id is
    already taken, in which case the script runs without line tracking."""
    monitoring = sys.monitoring
    # Leave DEBUGGER_ID (0) free so a debugger can still attach.
    for tool_id in (4, 3, 2, 1):
        try:
            monitoring.use_tool_id(tool_id, "script-manager-line-trace")
            break
        except ValueError:
            continue
    else:
        print("[script-runner] no free sys.monitoring tool id; running without line tracking", flush=True)
        return None
    events = monitoring.events
    script_path = _SCRIPT_PATH
    disable = monitoring.DISABLE

    def on_line(code, lineno):
        if code.co_filename != script_path:
            return disable
        _on_script_line(lineno)

    def on_exception(code, offset, exc):
        # PY_UNWIND (leaving a script frame) and EXCEPTION_HANDLED (caught in
        # one) together cover every script frame an exception passes through.
        # Frame 1 is that script frame.
        if code.co_filename == script_path:
            _on_script_exception(sys._getframe(1).f_lineno, exc)

    monitoring.register_callback(tool_id, events.LINE, on_line)
    monitoring.register_callback(tool_id, events.PY_UNWIND, on_exception)
    monitoring.register_callback(tool_id, events.EXCEPTION_HANDLED, on_exception)
    monitoring.set_events(tool_id, events.LINE | events.PY_UNWIND | events.EXCEPTION_HANDLED)
    return tool_id


def _stop_line_monitoring(tool_id):
    if tool_id is None:
        return
    sys.monitoring.set_events(tool_id, 0)
    sys.monitoring.free_tool_id(tool_id)


_sync_system_simulation_mode()
_patch_instrument_clients()
threading.Thread(target=_control_reader, args=(_detach_control_channel(),), daemon=True).start()
builtins.input = _input_via_manager
_tk_messagebox.showinfo = _tk_showinfo
_tk_messagebox.showwarning = _tk_showwarning
_tk_messagebox.showerror = _tk_showerror
_tk_messagebox.askyesno = _tk_askyesno
_tk_messagebox.askokcancel = _tk_askokcancel
_tk_messagebox.askretrycancel = _tk_askretrycancel
_tk_messagebox.askyesnocancel = _tk_askyesnocancel
_tk_simpledialog.askinteger = _tk_askinteger
_tk_simpledialog.askfloat = _tk_askfloat
_tk_simpledialog.askstring = _tk_askstring
_tk_simpledialog.askchoice = _tk_askchoice  # non-standard -- see _tk_askchoice
_tk_filedialog.askopenfilename = _tk_askopenfilename
_tk_filedialog.askopenfilenames = _tk_askopenfilenames
_tk_filedialog.asksaveasfilename = _tk_asksaveasfilename
_tk_filedialog.askdirectory = _tk_askdirectory
threading.Thread(target=_line_reporter, name="line-reporter", daemon=True).start()
_line_monitoring_tool = _start_line_monitoring()
try:
    runpy.run_path(_SCRIPT_PATH, run_name="__main__")
except KeyboardInterrupt:
    if not _stopping.is_set():
        raise
    print("[script-runner] Script stopped.", flush=True)
finally:
    _stop_line_monitoring(_line_monitoring_tool)
    if _current_line is not None and not _current_line[2]:
        _report_line(_current_line)
    _com_trace_stop.set()
    _emit_com_trace_lines(max_bytes=4 * 1024 * 1024, flush_partial=True)
'''

# -- Pre-run "is VENUS already busy?" check --------------------------------
#
# The stored script's own `with StarClient(...)`/`with VantageClient(...)`
# (inside the bootstrap template above) silently aborts any method VENUS is
# already running the moment it's entered (see the SDK's
# hamilton_venus._internal._async_instrument_client._cleanup_stale_method) --
# with zero warning. These run in the MAIN process, async, *before* the
# bootstrap file is even written or the subprocess spawned, so a confirmation
# round-trip with the UI can happen first. Independent of, and not reusing,
# _sync_system_simulation_mode above -- that's subprocess-side bootstrap text
# (sync httpx, runs after spawn); this needs to run here, before spawn.
_MAIN_VECTOR_API_BASE = "http://localhost:42400/api/vector/v3"
_MAIN_VECTOR_API_HEADERS = {"accept": "text/plain; x-api-version=3.0"}

# Mirrors hamilton_venus.models.RunState -- duplicated as a plain name table
# rather than importing the SDK enum, since this main-process code otherwise
# has no dependency on hamilton_venus at all (only the subprocess does).
_RUN_STATE_NAMES = {
    0: "NotInitialized", 1: "Initialized", 2: "Running", 3: "Aborting", 4: "Aborted",
    5: "Processed", 6: "Pausing", 7: "Paused", 8: "Starting", 9: "Terminating",
    10: "Terminated", 11: "Unknown",
}
_BUSY_RUN_STATE_NAMES = frozenset({"Running", "Aborting", "Pausing", "Paused", "Starting", "Terminating"})


async def _check_run_state() -> str | None:
    """Query VENUS's execution run-state directly over REST. Returns the
    RunState member name (e.g. "Running"), or None if VENUS is unreachable or
    the check itself fails -- fail-open, callers must treat that the same as
    "nothing to report" rather than blocking a run on it.
    """
    try:
        import httpx
    except Exception as exc:
        _logger.warning("Could not import httpx -- VENUS run-state not checked: %s", exc)
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{_MAIN_VECTOR_API_BASE}/execution/run-state", headers=_MAIN_VECTOR_API_HEADERS)
            resp.raise_for_status()
            value = int(resp.text.strip().strip('"'))
    except Exception as exc:
        _logger.warning("Could not check VENUS run-state: %s", exc)
        return None
    return _RUN_STATE_NAMES.get(value, "Unknown")


async def _check_run_guid() -> str | None:
    """Query VENUS's current-run-data directly over REST for the VENUS run
    control GUID of whatever method is currently loaded/running ("" if none).
    Returns None if VENUS is unreachable or the check fails -- fail-open, same
    as _check_run_state. Mirrors
    hamilton_workflow_framework.session.WorkflowSession.check_run_guid.
    """
    try:
        import httpx
    except Exception as exc:
        _logger.warning("Could not import httpx -- VENUS run GUID not checked: %s", exc)
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{_MAIN_VECTOR_API_BASE}/execution/current-run-data", headers=_MAIN_VECTOR_API_HEADERS)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        _logger.warning("Could not check VENUS current-run-data: %s", exc)
        return None
    return str(data.get("runGuid") or "") if isinstance(data, dict) else ""


async def _abort_and_clear_run_control(send: SendFn) -> None:
    """Explicitly abort + unload whatever VENUS is currently running, then wait
    for it to settle. Only called after the operator picks "Abort" on a
    run_control_busy prompt -- never unconditionally. Mirrors
    hamilton_workflow_framework.session.WorkflowSession.abort_and_clear_run_control.
    """
    import httpx

    async def log(text: str) -> None:
        await send({"type": "log", "source": "backend", "level": "INFO", "text": text, "timestamp": datetime.now(timezone.utc).isoformat()})

    async with httpx.AsyncClient(timeout=10.0) as client:
        await log("Aborting the instrument's current run...")
        try:
            await client.post(f"{_MAIN_VECTOR_API_BASE}/execution/abort", headers=_MAIN_VECTOR_API_HEADERS)
        except Exception as exc:
            _logger.warning("Abort request failed: %s", exc)

        loop = asyncio.get_event_loop()
        deadline = loop.time() + 30.0
        while loop.time() < deadline:
            state = await _check_run_state()
            if state is None or state not in _BUSY_RUN_STATE_NAMES:
                break
            await asyncio.sleep(1.0)
        else:
            await send({"type": "log", "source": "backend", "level": "WARNING", "text": "Timed out waiting for the aborted run to settle -- unloading anyway.", "timestamp": datetime.now(timezone.utc).isoformat()})

        await log("Unloading the previous method...")
        try:
            await client.post(f"{_MAIN_VECTOR_API_BASE}/execution/unload-method", headers=_MAIN_VECTOR_API_HEADERS)
        except Exception as exc:
            _logger.warning("Unload request failed: %s", exc)

    await log("Instrument is now clear.")


class ScriptRunner:
    """Owns at most one running script subprocess at a time."""

    def __init__(
        self,
        run_log_root: Path,
        consumables_store: ConsumablesStore,
        settings_store: SettingsStore,
        send: SendFn | None = None,
    ) -> None:
        # Every message goes through _emit (recorded for replay, then forwarded to
        # whichever UI connection is attached, if any) -- see attach(). `send` is
        # just an initially attached connection, without a replay.
        self._send: SendFn = self._emit
        self._sink: SendFn | None = send
        # Held while emitting and while replaying, so a live message can't overtake a replay.
        self._sink_lock = asyncio.Lock()
        # This run's messages from its "running" run_state onward, kept after it ends so
        # a window that attaches later still sees how it finished; cleared by the next run.
        self._history_head: list[dict[str, Any]] = []
        self._history: deque[dict[str, Any]] = deque(maxlen=_REPLAY_HISTORY_LIMIT)
        self._recording = False
        self._answered_prompts: set[str] = set()
        self._run_info: dict[str, Any] | None = None
        self._run_log_root = run_log_root
        self._consumables_store = consumables_store
        self._settings_store = settings_store
        self._proc: asyncio.subprocess.Process | None = None
        self._stop_requested = False
        # Auto-discovered reservoir keys already persisted this run -- avoids
        # re-writing consumables_store.json on every aspirate from the same well.
        self._persisted_auto_reservoirs: set[str] = set()
        # Pending run_control_busy prompts awaiting a run_control_busy_response
        # from the UI (see routes_ws.py) -- keyed by prompt_id, same pattern as
        # the operator-prompt/consumable-reload round trips below.
        self.pending_run_control: dict[str, asyncio.Future[str]] = {}
        # (epoch_seconds, line_number) samples from this run's sys.monitoring line
        # markers (see _LINE_MARKER handling in _stream()) -- persisted alongside
        # the finalized run log so the Summary tab can look up which script line
        # was executing when a given command_request fired (see _persist_line_timeline).
        self._line_timeline: list[tuple[float, int]] = []

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def _emit(self, payload: dict[str, Any]) -> None:
        async with self._sink_lock:
            if self._recording:
                if len(self._history_head) < 2:
                    # "running" + the consumables_config right behind it (see run()).
                    self._history_head.append(payload)
                else:
                    self._history.append(payload)
            if self._sink is not None:
                await self._sink(payload)

    async def attach(self, send: SendFn) -> None:
        """Make `send` the UI connection this runner talks to (the newest connection
        wins), and bring it up to date: replay the current or last run's messages in
        order, or just "idle" if there hasn't been one. Prompts the operator already
        answered are left out; once the run has ended, all prompts are -- nothing is
        waiting on them any more."""
        async with self._sink_lock:
            self._sink = send
            if self._run_info is None:
                await send({"type": "run_state", "state": "idle"})
                return
            running = self.is_running()
            await send({"type": "run_replay", **self._run_info})
            for payload in [*self._history_head, *self._history]:
                id_field = _PROMPT_ID_FIELDS.get(payload.get("type"))
                if id_field is not None and (not running or payload.get(id_field) in self._answered_prompts):
                    continue
                await send(payload)

    def _start_recording(self, shortcut_id: str, simulate: bool) -> None:
        """Start a new run's replay record, dropping the previous run's."""
        self._history_head = []
        self._history.clear()
        self._answered_prompts = set()
        # Sent ahead of a replay so a reattaching window can select and load this script.
        self._run_info = {"shortcut_id": shortcut_id, "simulate": bool(simulate)}
        self._recording = True

    def detach(self, send: SendFn) -> bool:
        """Drop `send` if it's still the attached connection. The run itself keeps
        going -- only /api/shutdown (close_all_runs) or the Stop button ends it.
        Returns whether `send` was the attached connection."""
        if self._sink is not send:
            return False
        self._sink = None
        return True

    async def _confirm_if_run_control_busy(self) -> bool:
        """Gate a Run against the SDK's silent stale-method abort (see the
        module-level docstring above _check_run_state). Returns True if it's
        safe to proceed (VENUS wasn't busy, or the operator picked "abort" and
        the existing run was cleared); False if the operator picked "cancel" --
        the caller must not spawn the script in that case. No timeout: leaving
        the prompt unanswered simply leaves the script un-started, which is safe.
        """
        state = await _check_run_state()
        if state is None or state not in _BUSY_RUN_STATE_NAMES:
            return True

        prompt_id = uuid.uuid4().hex
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self.pending_run_control[prompt_id] = future
        await self._send({"type": "run_control_busy", "prompt_id": prompt_id, "context": "run", "state": state})
        try:
            action = await future
        finally:
            self.pending_run_control.pop(prompt_id, None)

        if action != "abort":
            return False
        await _abort_and_clear_run_control(self._send)
        return True

    async def _run_heartbeat(self) -> None:
        """While the script subprocess is running, periodically confirm VENUS
        is still responding, and still running *this run's* own method.

        Catches two distinct things the subprocess itself has no way to report
        promptly: Run Control crashing mid-script (VENUS becomes unreachable),
        and -- confirmed to happen in practice -- another app's own
        run_control_busy "Abort" clearing *this* run's method to make room for
        its own, which leaves run-state reading RUNNING again throughout (now
        for the other app's method) -- run-state alone can't tell those apart,
        only the run GUID can. This run's own GUID is locked in from the first
        non-empty value observed (the subprocess's own StarClient/VantageClient
        connect happens after spawn, with no callback back to this main-process
        loop for exactly when that GUID becomes available), so a few early
        polls legitimately see none yet -- that's not a failure.

        Never touches the subprocess itself -- its own instrument calls will
        fail/exit on their own once VENUS/the run is actually gone; this only
        makes that visible sooner, both as a log line and as a run_state
        update so the pill/buttons don't stay looking stuck on "Running".
        One-shot: pushes a single warning, then stops.
        """
        consecutive_unreachable = 0
        own_run_guid: str | None = None
        try:
            while True:
                await asyncio.sleep(3.0)
                if self._stop_requested:
                    return  # the stop itself ends this run's method -- not a failure
                state = await _check_run_state()
                if state is None:
                    consecutive_unreachable += 1
                    if consecutive_unreachable < 2:
                        continue
                    await self._send({
                        "type": "log", "source": "backend", "level": "ERROR",
                        "text": "VENUS did not respond to a health check -- the instrument connection may have crashed.",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    await self._send({"type": "run_state", "state": "error", "detail": "VENUS did not respond to a health check."})
                    return
                consecutive_unreachable = 0

                current_guid = await _check_run_guid()
                if current_guid is None:
                    continue
                if not current_guid:
                    continue  # nothing loaded yet, or already cleared -- not evidence of a problem on its own
                if own_run_guid is None:
                    own_run_guid = current_guid  # first real guid seen -- lock it in as this run's own
                    continue
                if current_guid != own_run_guid:
                    await self._send({
                        "type": "log", "source": "backend", "level": "ERROR",
                        "text": "VENUS run control is no longer running this run's method (aborted or replaced by "
                                "another connection).",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    await self._send({
                        "type": "run_state", "state": "error",
                        "detail": "VENUS run control was aborted or replaced by another connection.",
                    })
                    return
        except asyncio.CancelledError:
            pass

    async def run(self, script_path: Path, simulate: bool, shortcut_id: str) -> None:
        if self.is_running():
            await self._send({"type": "error", "message": "A script is already running."})
            return

        if not await self._confirm_if_run_control_busy():
            await self._send({"type": "run_state", "state": "idle"})
            return

        run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}"
        run_log_dir = self._run_log_root
        run_log_dir.mkdir(parents=True, exist_ok=True)
        # The SDK's finalized filename is unique per run (VENUS run GUID, or the
        # SDK session id as a fallback -- see _run_log.py's _build_final_name), but
        # this directory is shared with every other app/run pointed at the same
        # LogFiles folder, so "the file this run produced" still has to be found
        # by diffing rather than just listing the directory's contents.
        pre_existing = {p.name for p in run_log_dir.glob("*_SdkRunLog.json")}
        started_at = datetime.now(timezone.utc).timestamp()

        self._stop_requested = False
        self._persisted_auto_reservoirs = set()
        self._line_timeline = []
        consumables_config = self._consumables_store.list_config()
        # Auto-discovered reservoirs are persisted so a *later* run that also
        # touches the same labware recognizes it immediately -- but seeding
        # every run's initial view with EVERY reservoir ever auto-discovered
        # by ANY past script (regardless of whether this run's script touches
        # it at all) leaves permanently-stale "n/a" cards for labware this
        # run has nothing to do with. Only explicitly-registered ("manual")
        # reservoirs are meant to persist into every run's initial display;
        # an "auto" one must be rediscovered live by THIS run to reappear --
        # that rediscovery is unaffected, since _should_track_reservoir/
        # _is_reservoir_labware classify live off the labware's own
        # labwareClass, not off this seeded config.
        consumables_config = {
            **consumables_config,
            "reservoirs": {
                key: cfg for key, cfg in consumables_config["reservoirs"].items() if cfg.get("source") == "manual"
            },
        }
        self._start_recording(shortcut_id, simulate)
        await self._send({"type": "run_state", "state": "running", "run_id": run_id})
        # Re-send config right behind "running" so the frontend's reset (which
        # drops last run's live tip/reservoir entries) repopulates with this
        # run's registered/thresholded entries rather than sitting empty.
        await self._send({"type": "consumables_config", **consumables_config})
        settings = self._settings_store.get_settings()
        bootstrap_path: Path | None = None
        try:
            bootstrap = (
                _BOOTSTRAP_TEMPLATE.replace("__SCRIPT_PATH_REPR__", repr(str(script_path)))
                .replace("__SIMULATE_REPR__", repr(bool(simulate)))
                .replace("__RUN_LOG_DIR_REPR__", repr(str(run_log_dir)))
                .replace("__TIP_THRESHOLDS_REPR__", repr(consumables_config["tip_pools"]))
                .replace("__REGISTERED_RESERVOIRS_REPR__", repr(consumables_config["reservoirs"]))
                .replace("__DEFAULT_TIP_THRESHOLD_REPR__", repr(int(settings["default_tip_warning_threshold"])))
                .replace("__RESERVOIR_WARNING_PERCENT_REPR__", repr(float(settings["reservoir_warning_percent"]) / 100.0))
                .replace("__COM_TRACE_ENABLED_REPR__", repr(bool(settings.get("com_trace_enabled", True))))
                .replace("__COM_TRACE_DIR_REPR__", repr(str(settings.get("com_trace_logfiles_dir") or "")))
                .replace("__DEBUG_LOGGING_ENABLED_REPR__", repr(bool(settings.get("debug_logging_enabled", True))))
            )
            # Passed as a file path, not `-c <bootstrap>` -- consumables tracking
            # grew this string well past Windows' ~32K CreateProcess command-line
            # length limit (WinError 206, "The filename or extension is too
            # long"), which `-c` hits directly since the whole script becomes
            # part of the command line. A temp file's path is always short.
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", prefix=f"script_manager_bootstrap_{run_id}_",
                delete=False, encoding="utf-8",
            ) as bootstrap_file:
                bootstrap_file.write(bootstrap)
                bootstrap_path = Path(bootstrap_file.name)
            self._proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(bootstrap_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_STREAM_READ_LIMIT,
            )
            heartbeat_task = asyncio.create_task(self._run_heartbeat())
            try:
                await asyncio.gather(
                    self._stream(self._proc.stdout, "INFO", is_stdout=True),
                    self._stream(self._proc.stderr, "ERROR"),
                )
            finally:
                heartbeat_task.cancel()
            returncode = await self._proc.wait()
            log_file = self._find_run_log(run_log_dir, pre_existing, started_at)
            self._persist_line_timeline(run_log_dir, log_file)
            if self._stop_requested:
                await self._send({"type": "run_state", "state": "stopped", "run_id": run_id, "log_file": log_file})
            elif returncode == 0:
                await self._send({"type": "run_state", "state": "completed", "run_id": run_id, "log_file": log_file})
            else:
                await self._send({
                    "type": "run_state",
                    "state": "error",
                    "detail": f"Script exited with code {returncode}",
                    "run_id": run_id,
                    "log_file": log_file,
                })
        except Exception as exc:  # noqa: BLE001 - surface any launch failure to the UI
            _logger.exception("Failed to run script")
            # _stream() aborting here (any exception it doesn't already recover from
            # itself, e.g. a future one _STREAM_READ_LIMIT/LimitOverrunError handling
            # above doesn't cover) must not leave the subprocess -- and therefore VENUS,
            # still mid-method -- orphaned just because the UI gave up on this run. Best
            # effort: same graceful-then-hard-kill shape as request_stop(), inline since
            # request_stop() itself expects a still-alive, still-being-drained _stream().
            if self._proc is not None and self._proc.returncode is None:
                try:
                    if self._proc.stdin is not None:
                        self._proc.stdin.write(b"STOP\n")
                        await self._proc.stdin.drain()
                    await asyncio.wait_for(self._proc.wait(), timeout=5.0)
                except Exception:
                    self._proc.terminate()
            log_file = self._find_run_log(run_log_dir, pre_existing, started_at)
            self._persist_line_timeline(run_log_dir, log_file)
            await self._send({
                "type": "run_state",
                "state": "error",
                "detail": str(exc),
                "run_id": run_id,
                "log_file": log_file,
            })
        finally:
            self._proc = None
            if bootstrap_path is not None:
                try:
                    bootstrap_path.unlink(missing_ok=True)
                except OSError:
                    _logger.warning("Could not remove temporary bootstrap file %s", bootstrap_path)

    def _persist_line_timeline(self, run_log_dir: Path, log_file: str | None) -> None:
        """Write this run's (epoch_seconds, line_number) samples to a sibling
        file next to the finalized run log, so a later /summary request --
        served fresh from disk, with no access to this ScriptRunner instance's
        in-memory state -- can look up which script line was executing when a
        given command fired (see run_summary.py's nearest-timestamp lookup)."""
        if log_file is None or not self._line_timeline:
            return
        lines_path = run_log_dir / log_file.replace("_SdkRunLog.json", "_ScriptLines.json")
        try:
            lines_path.write_text(json.dumps(self._line_timeline), encoding="utf-8")
        except OSError:
            _logger.warning("Could not write script line timeline for %s", log_file)

    @staticmethod
    def _find_run_log(run_log_dir: Path, pre_existing: set[str], started_at: float) -> str | None:
        candidates = [
            p
            for p in run_log_dir.glob("*_SdkRunLog.json")
            if p.name not in pre_existing and p.stat().st_mtime >= started_at
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime).name

    async def _stream(self, stream: asyncio.StreamReader | None, level: str, is_stdout: bool = False) -> None:
        if stream is None:
            return
        while True:
            try:
                line = await stream.readline()
            except asyncio.LimitOverrunError as exc:
                # A single line (almost always a VenusTrace line carrying inline TADM
                # curve data -- see _STREAM_READ_LIMIT above) exceeded even the raised
                # limit with no separator in sight. The offending bytes are still sitting
                # in the stream's internal buffer un-consumed (asyncio guarantees this --
                # it only drops buffered data on a *successful* read), so drain exactly
                # that many and keep going instead of letting this propagate out of
                # asyncio.gather() and abort the whole run while VENUS is still mid-method
                # and no run log ever gets reported. If the real separator is further
                # still, the next iteration hits this same branch again and keeps draining.
                discarded = await stream.read(exc.consumed)
                _logger.warning(
                    "Discarded oversized subprocess %s line (%d bytes, no separator within %d) -- likely inline TADM data",
                    "stdout" if is_stdout else "stderr",
                    len(discarded),
                    _STREAM_READ_LIMIT,
                )
                continue
            if not line:
                return
            if any(needle in line for needle in _NOISY_LOG_SUBSTRINGS):
                continue
            if is_stdout and line.startswith(_LINE_MARKER):
                # "<lineno> <epoch seconds the line started>" -- the child only
                # reports some lines (see _report_line in the bootstrap), so it
                # stamps each with its own start time; a bare "<lineno>" falls
                # back to arrival time.
                fields = line[len(_LINE_MARKER):].split()
                try:
                    lineno = int(fields[0])
                    started_at = float(fields[1]) if len(fields) > 1 else datetime.now(timezone.utc).timestamp()
                except (IndexError, ValueError):
                    continue
                self._line_timeline.append((started_at, lineno))
                await self._send({"type": "script_line", "line": lineno})
                continue
            if is_stdout and line.startswith(_STATE_MARKER):
                state = line[len(_STATE_MARKER):].strip().decode(errors="replace")
                if not self._stop_requested:  # stays "stopping" until the process exits
                    await self._send({"type": "run_state", "state": state})
                continue
            if is_stdout and line.startswith(_ERR_LINE_MARKER):
                try:
                    lineno = int(line[len(_ERR_LINE_MARKER):].strip())
                except ValueError:
                    continue
                await self._send({"type": "script_error_line", "line": lineno})
                continue
            if is_stdout and line.startswith(_SERIAL_MARKER):
                raw_json = line[len(_SERIAL_MARKER):].strip().decode(errors="replace")
                try:
                    payload = json.loads(raw_json)
                except ValueError:
                    _logger.warning("Malformed instrument-serial payload from subprocess: %r", raw_json)
                    continue
                await self._send({"type": "instrument_serial", **payload})
                continue
            if is_stdout and line.startswith(_PROMPT_MARKER):
                raw_json = line[len(_PROMPT_MARKER):].strip().decode(errors="replace")
                try:
                    payload = json.loads(raw_json)
                except ValueError:
                    _logger.warning("Malformed operator prompt payload from subprocess: %r", raw_json)
                    continue
                await self._send({
                    "type": "operator_prompt",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **payload,
                })
                continue
            if is_stdout and line.startswith(_CONSUMABLE_MARKER):
                raw_json = line[len(_CONSUMABLE_MARKER):].strip().decode(errors="replace")
                try:
                    payload = json.loads(raw_json)
                except ValueError:
                    _logger.warning("Malformed consumable update payload from subprocess: %r", raw_json)
                    continue
                kind = payload.pop("kind", None)
                if kind == "tip":
                    await self._send({"type": "tip_count_update", **payload})
                elif kind == "reagent":
                    await self._send({"type": "reagent_level_update", **payload})
                    if payload.get("source") == "auto" and payload.get("key") not in self._persisted_auto_reservoirs:
                        self._persisted_auto_reservoirs.add(payload["key"])
                        try:
                            self._consumables_store.record_auto_discovered_reservoir(payload["key"], payload["labware"], payload["well"])
                        except Exception:
                            _logger.exception("Could not persist auto-discovered reservoir %r", payload.get("key"))
                continue
            if is_stdout and line.startswith(_SAMPLE_LABWARE_INFO_MARKER):
                raw_json = line[len(_SAMPLE_LABWARE_INFO_MARKER):].strip().decode(errors="replace")
                try:
                    payload = json.loads(raw_json)
                except ValueError:
                    _logger.warning("Malformed sample-labware-info payload from subprocess: %r", raw_json)
                    continue
                await self._send({"type": "sample_labware_info", **payload})
                continue
            if is_stdout and line.startswith(_SAMPLE_MARKER):
                raw_json = line[len(_SAMPLE_MARKER):].strip().decode(errors="replace")
                try:
                    payload = json.loads(raw_json)
                except ValueError:
                    _logger.warning("Malformed sample-tracking event payload from subprocess: %r", raw_json)
                    continue
                await self._send({
                    "type": "sample_event",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **payload,
                })
                continue
            if is_stdout and line.startswith(_TADM_MARKER):
                raw_json = line[len(_TADM_MARKER):].strip().decode(errors="replace")
                try:
                    payload = json.loads(raw_json)
                except ValueError:
                    _logger.warning("Malformed TADM curve payload from subprocess: %r", raw_json)
                    continue
                await self._send({
                    "type": "tadm_result",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **payload,
                })
                continue
            if is_stdout and line.startswith(_COMTRACE_MARKER):
                raw_json = line[len(_COMTRACE_MARKER):].strip().decode(errors="replace")
                try:
                    payload = json.loads(raw_json)
                except ValueError:
                    _logger.warning("Malformed COM-trace payload from subprocess: %r", raw_json)
                    continue
                await self._send({
                    "type": "com_trace",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **payload,
                })
                continue
            if is_stdout and line.startswith(_CONSUMABLE_WARNING_MARKER):
                raw_json = line[len(_CONSUMABLE_WARNING_MARKER):].strip().decode(errors="replace")
                try:
                    payload = json.loads(raw_json)
                except ValueError:
                    _logger.warning("Malformed consumable warning payload from subprocess: %r", raw_json)
                    continue
                await self._send({"type": "consumable_warning", **payload})
                continue
            if is_stdout and line.startswith(_CONSUMABLE_RELOAD_DONE_MARKER):
                raw_json = line[len(_CONSUMABLE_RELOAD_DONE_MARKER):].strip().decode(errors="replace")
                try:
                    payload = json.loads(raw_json)
                except ValueError:
                    _logger.warning("Malformed consumable reload-done payload from subprocess: %r", raw_json)
                    continue
                await self._send({"type": "consumable_reload_done", **payload})
                continue
            if is_stdout and line.startswith(_CONSUMABLE_RELOAD_MARKER):
                raw_json = line[len(_CONSUMABLE_RELOAD_MARKER):].strip().decode(errors="replace")
                try:
                    payload = json.loads(raw_json)
                except ValueError:
                    _logger.warning("Malformed consumable reload-prompt payload from subprocess: %r", raw_json)
                    continue
                await self._send({"type": "consumable_reload_prompt", **payload})
                continue
            if is_stdout and line.startswith(_INPUT_REQUEST_MARKER):
                raw_json = line[len(_INPUT_REQUEST_MARKER):].strip().decode(errors="replace")
                try:
                    payload = json.loads(raw_json)
                except ValueError:
                    _logger.warning("Malformed input-request payload from subprocess: %r", raw_json)
                    continue
                await self._send({
                    "type": "user_input_request",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **payload,
                })
                continue
            if is_stdout and line.startswith(_TK_DIALOG_REQUEST_MARKER):
                raw_json = line[len(_TK_DIALOG_REQUEST_MARKER):].strip().decode(errors="replace")
                try:
                    payload = json.loads(raw_json)
                except ValueError:
                    _logger.warning("Malformed tk-dialog-request payload from subprocess: %r", raw_json)
                    continue
                await self._send({
                    "type": "tk_dialog_request",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **payload,
                })
                continue
            if is_stdout and line.startswith(_TK_FILEDIALOG_REQUEST_MARKER):
                raw_json = line[len(_TK_FILEDIALOG_REQUEST_MARKER):].strip().decode(errors="replace")
                try:
                    payload = json.loads(raw_json)
                except ValueError:
                    _logger.warning("Malformed tk-filedialog-request payload from subprocess: %r", raw_json)
                    continue
                await self._send({
                    "type": "tk_filedialog_request",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **payload,
                })
                continue
            await self._send({
                "type": "log",
                "source": "script",
                "level": level,
                "text": line.decode(errors="replace").rstrip("\n"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    async def request_stop(self) -> None:
        """Ask the running script to stop, preferring the SDK's own clean abort
        (instrument_terminate()) over a hard process kill -- terminating the
        subprocess directly bypasses StarClient.__exit__'s graceful shutdown
        and leaves VENUS thinking a method is still loaded/running. The run
        shows "stopping" until the script has exited after that cleanup (the
        bootstrap resumes a paused VENUS so the terminate is processed); only
        then is it reported "stopped". A hard kill is a last resort, after
        _STOP_CLEANUP_TIMEOUT_S, for a script that never unblocks."""
        if not self.is_running() or self._stop_requested:
            return
        self._stop_requested = True
        await self._send({"type": "run_state", "state": "stopping"})
        if self._proc.stdin is not None:
            try:
                self._proc.stdin.write(b"STOP\n")
                await self._proc.stdin.drain()
            except Exception:
                pass

        async def _fallback_kill(proc: asyncio.subprocess.Process) -> None:
            await asyncio.sleep(_STOP_CLEANUP_TIMEOUT_S)
            if proc.returncode is None:
                await self._send({
                    "type": "log", "source": "backend", "level": "ERROR",
                    "text": f"The script did not finish stopping within {_STOP_CLEANUP_TIMEOUT_S:.0f} s -- "
                            "ending it. Check VENUS: its method may still be loaded.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                proc.terminate()

        asyncio.create_task(_fallback_kill(self._proc))

    async def request_pause(self) -> None:
        if not self.is_running() or self._proc.stdin is None:
            return
        await self._send({"type": "run_state", "state": "pausing"})
        self._proc.stdin.write(b"PAUSE\n")
        await self._proc.stdin.drain()

    async def request_resume(self) -> None:
        if not self.is_running() or self._proc.stdin is None:
            return
        self._proc.stdin.write(b"RESUME\n")
        await self._proc.stdin.drain()

    async def resolve_run_control_prompt(self, prompt_id: str, action: str) -> None:
        """Answers a live "run_control_busy" prompt from _confirm_if_run_control_busy
        above. A stale/unknown prompt_id (already answered, or the connection
        dropped before the UI's response arrived -- see fail_pending_run_control)
        is harmless: silently ignored, same as resolve_operator_prompt's own
        stale-uuid handling.
        """
        future = self.pending_run_control.get(prompt_id)
        if future is None or future.done():
            _logger.warning("run_control_busy_response for unknown/already-resolved prompt_id=%s", prompt_id)
            return
        future.set_result(action)

    def fail_pending_run_control(self) -> None:
        """Resolve any still-pending run_control_busy prompt as "cancel" -- called
        when the attached WS connection drops while _confirm_if_run_control_busy
        is awaiting a response. That prompt isn't part of a run's replay (no run
        has started yet), so a reattaching window would never see it; cancelling
        just leaves the script un-started, which is safe (mirrors
        WorkflowSession._fail_pending_operator_prompts's reasoning).
        """
        for future in self.pending_run_control.values():
            if not future.done():
                future.set_result("cancel")

    async def resolve_operator_prompt(
        self,
        error_uuid: str,
        action: str | None = None,
        channel_actions: dict[str, int] | None = None,
        channel_inputs: dict[str, list[dict]] | None = None,
    ) -> None:
        """Answers a live "operator_prompt" this run emitted -- see the bootstrap's
        _on_operator_escalation, which is blocked on a threading.Event inside the
        subprocess until this line arrives. A stale/unknown uuid (the prompt was
        already answered, or the run ended before the UI's response arrived) is
        harmless: the subprocess's _control_reader just finds no matching event
        and silently no-ops, same as a stray line.

        Exactly one of `action` (one choice applied uniformly -- the Abort/
        Cancel-style buttons) or `channel_actions` (detail_uuid -> chosen
        action id, independent per-channel dropdown picks) is expected to be
        set; `channel_actions` wins if both somehow are, since a non-empty
        per-channel selection is the more specific answer. `channel_inputs`
        (detail_uuid -> [{"id": input id, "value": str}]) carries the values for
        chosen actions that take inputs, e.g. a barcode typed in for a position
        that failed to read.
        """
        if not self.is_running() or self._proc.stdin is None:
            return
        self._answered_prompts.add(error_uuid)
        if channel_actions and channel_inputs:
            payload = {"actions": channel_actions, "inputs": channel_inputs}
            line = f"PROMPT_RESPONSE {error_uuid} CHANNELS {json.dumps(payload)}\n"
        elif channel_actions:
            line = f"PROMPT_RESPONSE {error_uuid} CHANNELS {json.dumps(channel_actions)}\n"
        else:
            line = f"PROMPT_RESPONSE {error_uuid} ACTION {action or ''}\n"
        self._proc.stdin.write(line.encode())
        await self._proc.stdin.drain()

    async def push_add_reservoir(self, labware: str, well: str, label: str) -> None:
        """Relay an "Add Reservoir" action into the live subprocess, if one is
        running, so a run already in progress picks up the registration
        immediately rather than only on its next run."""
        if not self.is_running() or self._proc.stdin is None:
            return
        payload = {"labware": labware, "well": well, "label": label}
        self._proc.stdin.write(f"ADD_RESERVOIR {json.dumps(payload)}\n".encode())
        await self._proc.stdin.drain()

    async def push_set_tip_threshold(self, tip_pool: str, threshold: int) -> None:
        if not self.is_running() or self._proc.stdin is None:
            return
        self._proc.stdin.write(f"SET_TIP_THRESHOLD {tip_pool} {threshold}\n".encode())
        await self._proc.stdin.drain()

    async def resolve_consumable_reload_action(self, reload_uuid: str, action: str) -> None:
        """Answers a live "consumable_reload_prompt" -- see the bootstrap's
        _ensure_tip_availability, blocked on a threading.Event until this line
        arrives. `action` is "show_counter" (trigger VENUS's tip-counter
        dialog and recheck) or "abort" (cancel the run); anything else is
        treated as an abort by the bootstrap. A stale/unknown reload_uuid is
        harmless, same as resolve_operator_prompt."""
        if not self.is_running() or self._proc.stdin is None:
            return
        self._answered_prompts.add(reload_uuid)
        self._proc.stdin.write(f"CONSUMABLE_PROMPT_RESPONSE {reload_uuid} {action}\n".encode())
        await self._proc.stdin.drain()

    async def resolve_user_input(self, request_uuid: str, value: str | None, cancelled: bool = False) -> None:
        """Answers a live "user_input_request" -- see the bootstrap's
        _input_via_manager (installed as builtins.input), blocked on a
        threading.Event until this line arrives. `cancelled` is carried
        separately from `value` since "" is itself a legitimate answer to a
        script's input() call -- the bootstrap raises OperatorCancelledError
        when cancelled is set, rather than treating it as an empty string. A
        stale/unknown request_uuid is harmless, same as resolve_operator_prompt.
        """
        if not self.is_running() or self._proc.stdin is None:
            return
        self._answered_prompts.add(request_uuid)
        payload = {"value": value, "cancelled": cancelled}
        self._proc.stdin.write(f"INPUT_RESPONSE {request_uuid} {json.dumps(payload)}\n".encode())
        await self._proc.stdin.drain()

    async def resolve_tk_dialog(self, request_uuid: str, value: Any) -> None:
        """Answers a live "tk_dialog_request" -- see the bootstrap's
        _tk_dialog_request, called from whichever patched tkinter.messagebox/
        simpledialog function the script invoked, blocked on a threading.Event
        until this line arrives. Unlike resolve_user_input, `value` IS the
        whole payload (bool/int/float/str/None) -- None is already tkinter's
        own unambiguous "cancelled" signal for every kind that has one, so no
        separate flag is needed. A stale/unknown request_uuid is harmless,
        same as resolve_operator_prompt.
        """
        if not self.is_running() or self._proc.stdin is None:
            return
        self._answered_prompts.add(request_uuid)
        self._proc.stdin.write(f"TK_DIALOG_RESPONSE {request_uuid} {json.dumps(value)}\n".encode())
        await self._proc.stdin.drain()

    async def resolve_tk_filedialog(self, request_uuid: str, value: Any) -> None:
        """Answers a live "tk_filedialog_request" -- see the bootstrap's
        _tk_filedialog_request, called from whichever patched
        tkinter.filedialog function the script invoked. `value` is a string
        path, a list of paths (askopenfilenames), or None (cancel) -- the
        bootstrap's patched functions turn None into the real tkinter cancel
        value ("" or ()) for that specific kind. A stale/unknown
        request_uuid is harmless, same as resolve_operator_prompt.
        """
        if not self.is_running() or self._proc.stdin is None:
            return
        self._answered_prompts.add(request_uuid)
        self._proc.stdin.write(f"TK_FILEDIALOG_RESPONSE {request_uuid} {json.dumps(value)}\n".encode())
        await self._proc.stdin.drain()
