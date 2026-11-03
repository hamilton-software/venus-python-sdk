"""WebSocket message schema for the script manager app.

Unlike hamilton_workflow_framework's own ws_protocol.py (built around a
persistent StarClient session driving a step list), this app has no shared
session -- each run is its own subprocess with its own StarClient (see
script_runner.py) -- so this is a standalone message union. It reuses the
framework's generic envelope-building helpers (make_envelope_model /
parse_message), which are shape-agnostic, rather than re-implementing them.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from hamilton_workflow_framework.ws_protocol import make_envelope_model, parse_message

# --------------------------------------------------------------------------
# Client -> Server
# --------------------------------------------------------------------------


class ListShortcuts(BaseModel):
    type: Literal["list_shortcuts"] = "list_shortcuts"


class CreateFolder(BaseModel):
    type: Literal["create_folder"] = "create_folder"
    name: str
    parent_id: str | None = None


class RenameFolder(BaseModel):
    type: Literal["rename_folder"] = "rename_folder"
    folder_id: str
    name: str


class DeleteFolder(BaseModel):
    type: Literal["delete_folder"] = "delete_folder"
    folder_id: str


class CreateShortcut(BaseModel):
    type: Literal["create_shortcut"] = "create_shortcut"
    name: str
    source_path: str
    folder_id: str | None = None


class UpdateShortcut(BaseModel):
    type: Literal["update_shortcut"] = "update_shortcut"
    shortcut_id: str
    name: str


class ResyncShortcut(BaseModel):
    type: Literal["resync_shortcut"] = "resync_shortcut"
    shortcut_id: str


class DeleteShortcut(BaseModel):
    type: Literal["delete_shortcut"] = "delete_shortcut"
    shortcut_id: str


class MoveItem(BaseModel):
    type: Literal["move_item"] = "move_item"
    item_id: str
    item_type: Literal["folder", "shortcut"]
    new_parent_id: str | None = None
    new_index: int


class GetScript(BaseModel):
    type: Literal["get_script"] = "get_script"
    shortcut_id: str


class RunShortcut(BaseModel):
    type: Literal["run_shortcut"] = "run_shortcut"
    shortcut_id: str
    simulate: bool


class Pause(BaseModel):
    type: Literal["pause"] = "pause"


class Resume(BaseModel):
    type: Literal["resume"] = "resume"


class Stop(BaseModel):
    type: Literal["stop"] = "stop"


class Ping(BaseModel):
    type: Literal["ping"] = "ping"


class OperatorPromptResponse(BaseModel):
    """Reply to a live "operator_prompt" (see script_runner.py's bootstrap).
    Started as the same shape as hamilton_workflow_framework.ws_protocol.
    OperatorPromptResponse (reused here as a plain field-for-field
    redeclaration, not an import, since this app's ClientMessage union has its
    own discriminated members rather than the framework's) but adds
    `channel_actions` for independent per-channel recovery picks, which that
    shared shape/modal doesn't support. Exactly one of `action` (applied
    uniformly -- Abort/Cancel-style) or `channel_actions` (detail_uuid ->
    chosen action id) is expected to be set. `channel_inputs` (detail_uuid ->
    [{"id": input id, "value": str}]) goes with `channel_actions` when a chosen
    action takes inputs, e.g. the barcode typed in for a failed scan position."""

    type: Literal["operator_prompt_response"] = "operator_prompt_response"
    error_uuid: str
    action: str | None = None
    channel_actions: dict[str, int] | None = None
    channel_inputs: dict[str, list[dict]] | None = None


class RunControlBusyResponse(BaseModel):
    """Reply to a live "run_control_busy" prompt (see script_runner.py's
    _confirm_if_run_control_busy). Field-for-field the same shape as
    hamilton_workflow_framework.ws_protocol.RunControlBusyResponse, redeclared
    here rather than imported for the same reason OperatorPromptResponse above
    is -- this app's ClientMessage union has its own discriminated members.
    `action` is "abort" (explicitly abort + unload the existing run, then start
    this script) or "cancel" (do nothing -- leave the existing run untouched,
    don't start the script)."""

    type: Literal["run_control_busy_response"] = "run_control_busy_response"
    prompt_id: str
    action: Literal["abort", "cancel"]


class AddReservoir(BaseModel):
    """Register a labware position as a tracked reagent reservoir (see
    consumables_store.py). Also used to relabel/re-add an already-known
    (e.g. auto-discovered) reservoir -- always promotes it to source="manual"."""

    type: Literal["add_reservoir"] = "add_reservoir"
    labware: str
    well: str
    label: str = ""


class SetTipThreshold(BaseModel):
    type: Literal["set_tip_threshold"] = "set_tip_threshold"
    tip_pool: str
    threshold: int


class ConsumableReloadAction(BaseModel):
    """Reply to a live "consumable_reload_prompt" (see script_runner.py's
    bootstrap). "show_counter" triggers VENUS's own tip-counter dialog and
    waits for it to close; "abort" cancels the run."""

    type: Literal["consumable_reload_action"] = "consumable_reload_action"
    reload_uuid: str
    action: Literal["show_counter", "abort"]


class UserInputResponse(BaseModel):
    """Reply to a live "user_input_request" (see script_runner.py's bootstrap
    _input_via_manager, installed as builtins.input so any input() call in the
    script -- direct, or via a script-local wrapper -- round-trips through
    here automatically). `cancelled` is carried separately from `value` since
    "" is itself a legitimate answer to a script's input() call."""

    type: Literal["user_input_response"] = "user_input_response"
    uuid: str
    value: str | None = None
    cancelled: bool = False


class TkDialogResponse(BaseModel):
    """Reply to a live "tk_dialog_request" (see script_runner.py's bootstrap
    _tk_dialog_request, invoked from whichever patched tkinter.messagebox/
    simpledialog function the script called -- direct, no script changes
    needed). Unlike UserInputResponse, `value` alone carries the whole
    answer -- its type varies by the request's `kind` (bool for
    askyesno/askokcancel/askretrycancel, True/False/None for
    askyesnocancel, int/float/str/None for askinteger/askfloat/askstring,
    the chosen option str (or None) for askchoice, ignored for the no-cancel
    showinfo/showwarning/showerror kinds). `None` is tkinter's own unambiguous
    "cancelled" signal for every kind that has one, so no separate flag is
    needed."""

    type: Literal["tk_dialog_response"] = "tk_dialog_response"
    uuid: str
    value: bool | int | float | str | None = None


class UpdateSettings(BaseModel):
    """Partial update from the Settings modal (see settings_store.py) --
    unset fields are left unchanged, matching SettingsStore.update_settings.
    Fields mirror settings_store.DEFAULT_SETTINGS exactly."""

    type: Literal["update_settings"] = "update_settings"
    warn_on_stale_shortcut: bool | None = None
    auto_resync_shortcuts: bool | None = None
    default_tip_warning_threshold: int | None = None
    reservoir_warning_percent: float | None = None
    debug_logging_enabled: bool | None = None


class TkFileDialogResponse(BaseModel):
    """Reply to a live "tk_filedialog_request" (see script_runner.py's
    bootstrap _tk_filedialog_request, invoked from whichever patched
    tkinter.filedialog function the script called -- direct, no script
    changes needed). `value` is a string path (askopenfilename/
    asksaveasfilename/askdirectory), a list of paths (askopenfilenames), or
    None on cancel -- the bootstrap turns None into the real tkinter cancel
    value ("" or ()) for that specific kind."""

    type: Literal["tk_filedialog_response"] = "tk_filedialog_response"
    uuid: str
    value: str | list[str] | None = None


ClientMessage = Annotated[
    Union[
        ListShortcuts,
        CreateFolder,
        RenameFolder,
        DeleteFolder,
        CreateShortcut,
        UpdateShortcut,
        ResyncShortcut,
        DeleteShortcut,
        MoveItem,
        GetScript,
        RunShortcut,
        Pause,
        Resume,
        Stop,
        Ping,
        OperatorPromptResponse,
        RunControlBusyResponse,
        AddReservoir,
        SetTipThreshold,
        ConsumableReloadAction,
        UserInputResponse,
        TkDialogResponse,
        TkFileDialogResponse,
        UpdateSettings,
    ],
    Field(discriminator="type"),
]

_ClientEnvelope = make_envelope_model(ClientMessage)


def parse_client_message(raw: dict[str, Any]) -> ClientMessage:
    return parse_message(raw, _ClientEnvelope)


# --------------------------------------------------------------------------
# Server -> Client (documented for reference; constructed as plain dicts at
# the send sites, same convention as hamilton_workflow_framework/ws_protocol.py)
# --------------------------------------------------------------------------

# {"type": "shortcuts_tree", "folders": [...], "shortcuts": [...]}
# {"type": "script_loaded", "shortcut_id", "name", "source"}
# {"type": "run_state", "state": "idle"|"running"|"pausing"|"paused"|"stopped"|"completed"|"error", "run_id"?, "log_file"?, "detail"?}
# {"type": "instrument_serial", "serial": str, "simulated": bool}
#   -- sent once per connected client, right after script_runner.py's bootstrap _report_serial_number
#   queries instrument_get_serial_number() following a successful connect (real connect, or the
#   script's own instrument_connect() call). "simulated" is true for Hamilton's fixed simulated-
#   instrument serial ("0000"/"0"/""), which is reported regardless of this run's Simulate toggle
#   state -- it reflects which INSTRUMENT answered (VENUS's system-wide simulation setting), not
#   this run's own simulate flag. Never sent if the script never connects, or the probe itself fails.
# {"type": "script_line", "line": int}
# {"type": "log", "source": "script", "level", "text", "timestamp"}
# {"type": "error", "message": str}
# {"type": "operator_prompt", "error_uuid", "code", "title",
#  "channel_errors": [{"channels": [str], "message", "detail_uuids": [str],
#                       "actions": [{"id", "name"}], "default_action_id"}],
#  "top_level_actions": [str], "access_actions": [{"id", "key", "label"}], "timestamp"}
#   -- "access_actions" (unlock/lock door, raise/lower load tray) do not answer the error: the UI
#   replies with action=<key>, keeps the modal open, and gets a fresh operator_prompt for the same
#   error_uuid once the instrument has carried the action out.
#   -- built inside the subprocess bootstrap (script_runner.py) rather than a WorkflowSession, since
#   this app has no shared session. Diverges from hamilton_workflow_framework.ws_protocol.OperatorPrompt
#   (and its shared operator-prompt-modal.js) by grouping channels that hit the exact same message
#   (one error type -> one group -> one dropdown of that group's own server-advertised recovery-action
#   id/name options, defaulting to "Repeat" if offered) rather than a flat per-channel message string --
#   consumed by this app's own operator-recovery-modal.js, which renders one dropdown per group.
# {"type": "run_control_busy", "prompt_id", "context": "run", "state"}
#   -- pushed by script_runner.py's _confirm_if_run_control_busy instead of letting the SDK's
#   StarClient/VantageClient __enter__ silently abort a VENUS run already in progress when the
#   stored script constructs one. "state" is the VENUS RunState member name (e.g. "Running").
#   No timeout -- the script isn't spawned until a run_control_busy_response answers this.
# {"type": "pong"}
# {"type": "consumables_config", "tip_pools": {tip_pool: {tip_pool, low_threshold}},
#  "reservoirs": {key: {key, labware, well, label, source: "manual"|"auto", created_at}}}
#   -- sent once at connect (config only, no live counts) and again after every add_reservoir/
#   set_tip_threshold mutation. Live measured values arrive separately via the two updates below.
# {"type": "tip_count_update", "tip_pool", "current_count", "total_capacity", "low_threshold"}
# {"type": "reagent_level_update", "key", "labware", "well", "label", "source": "manual"|"auto",
#  "remaining_volume_ul", "total_volume_ul", "percent_full", "last_updated"}
#   -- total_volume_ul/percent_full are null ("n/a" in the UI) when the reservoir's container depth
#   couldn't be resolved; remaining_volume_ul still tracks via measured/decrement updates regardless.
# {"type": "consumable_warning", "kind": "tip", "tip_pool", "current_count", "threshold"}
# {"type": "consumable_warning", "kind": "reagent", "reservoir_key", "label", "percent_full", "threshold_percent"}
#   -- edge-triggered: fires once when the count/percentage crosses below threshold, not on every
#   pickup/aspirate. "threshold_percent" is a whole number (10, not 0.10) to match reservoir_warning_percent.
# {"type": "settings", "warn_on_stale_shortcut", "auto_resync_shortcuts",
#  "default_tip_warning_threshold", "reservoir_warning_percent",
#  "com_trace_enabled", "com_trace_logfiles_dir", "debug_logging_enabled"}
#   -- sent once at connect (see settings_store.py) and again after every update_settings.
#   com_trace_enabled / com_trace_logfiles_dir have no Settings-modal control -- edit
#   data/settings.json to change them (see the "com_trace" message below).
#   default_tip_warning_threshold seeds a tip pool's low_threshold the first time script_runner.py's
#   bootstrap sees it with no configured override (see consumables_store.py's TipPoolConfig);
#   reservoir_warning_percent (0-100) is the global "warn below N% full" trigger for every tracked
#   reservoir -- there is no per-reservoir override, unlike tip pools.
# {"type": "sample_labware_info", "labware", "labware_class", "rows", "cols", "numeric_addressing",
#  "pattern": "COLUMN_MAJOR"|"ROW_MAJOR", "barcode": str|None}
#   -- sent once per labware per run, the first time it becomes a dispense target (see
#   script_runner.py's bootstrap _announce_sample_labware). Drives the Sample Tracking tab's card
#   creation -- "labware_class" == "plate" renders a grid (rows x cols); anything else (e.g.
#   "tube_rack") renders a list. "barcode" is the whole labware's own barcode, resolved via
#   _resolve_labware_barcode: null unless this labware was placed (add_plate/add_reservoir/
#   add_lidded_plate) at a carrier site that was itself scanned via an autoload.loadCarrierBy*
#   call's scan_positions (see script_runner.py's _patch_autoload_scan_tracking/
#   _patch_labware_site_tracking) -- never set for a tube rack (each of its own wells has its own
#   barcode instead, carried per-transfer on sample_event's "source_barcode" below).
# {"type": "sample_event", "labware", "well", "operation": "aspirate"|"dispense", "channel":
#  int|"MPH"|str, "volume", "current_volume_ul", "success": bool, "error": str|None,
#  "source_labware": str|None, "source_well": str|None, "source_key": int|None,
#  "transfer_id": int|None, "source_transfer_id": int|None, "source_barcode": str|None,
#  "source_barcode_type": "well"|"plate"|"reservoir"|...|None,
#  "liquid_class": str|None, "lld": bool, "liquid_level_mm", "liquid_volume_ul",
#  "errors": [{"error_uuid", "time", "during": "aspirate"|"dispense", "code", "detail_code", "title",
#  "message", "channel": int|None,
#  "position": str|None, "recovery": str, "kind": "recovery"|"action",
#  "decided_by": "automatic"|"operator", "inputs": [{"name", "value"}]}], "timestamp"}
#   -- "errors" lists the instrument errors answered while this event's SDK call was in flight that
#   belong to its channel (its own per-channel errors plus any error with no channel; MPH96 and
#   dispense_on_the_fly events carry every error of the call), one entry per recovery submitted --
#   so a transfer that was retried twice and then succeeded has two entries and "success": true.
#   A dispense also carries the errors of the aspirate that filled its tip ("during": "aspirate"),
#   since an aspirate from a labware that is not itself a target sends no event of its own.
#   "recovery" is the name VENUS advertises for the submitted action ("VENUS operator dialog" when
#   the error was handed to VENUS's own dialog); "kind" "action" is a door / loading-tray action,
#   which does not answer the error. See script_runner.py's _patch_sample_error_capture.
#   -- built inside the subprocess bootstrap's sample-tracking patches (aspirate/aspirate_5ml/
#   aspirate_mph96/dispense/dispense_5ml/dispense_mph96/dispense_on_the_fly/dispense_on_the_fly_5ml
#   -- module docstring item 8, separate from the reservoir-only tracking in item 7). One event per
#   well touched by a single SDK call (a multi-channel aspirate/dispense emits several). "channel"
#   is the literal string "MPH" (never a number) for 96-head operations, or a comma-joined string
#   of engaged channel numbers (e.g. "1,2,3,4") for dispense_on_the_fly, which sweeps every engaged
#   channel across every well in one pass with no single-channel-per-well mapping. "source_labware"/
#   "source_well"/"source_key" are only set for "dispense" events, resolved via a per-channel "last
#   aspirate source" heuristic (the SDK has no built-in aspirate<->dispense pairing) -- null when
#   that channel never aspirated this run; a reservoir's several addressable sub-positions collapse
#   to one shared source identity (see script_runner.py's _sample_source_position). "current_volume_ul"
#   is a running per-well ledger clamped at a minimum of 0. Only ever sent for labware that has
#   become a target (received >= 1 dispense); aspirate-only labware, and dispensing INTO a reservoir
#   (a refill, not a sample), are tracked/ignored server-side but never surface here. "transfer_id" is
#   a per-(call, channel) id, minted whether or not the event above was itself emitted (an
#   aspirate-only labware is ledgered silently -- see above -- but its transfer_id still exists so a
#   later dispense can reference it), letting a matching tadm_result be found for THIS event. A
#   dispense's "source_transfer_id" is its paired aspirate's own transfer_id (same heuristic as
#   source_labware/source_well), so a UI can show both curves for one physical transfer. Only ever
#   non-null for aspirate/aspirate_5ml/dispense/dispense_5ml (the only calls "adc" is a parameter of;
#   see tadm_result) -- MPH96 and dispense_on_the_fly variants always send null for both fields.
#   "source_barcode" (dispense only, same last-aspirate-per-channel heuristic) is the scanned
#   barcode of whatever this channel's tip last aspirated from: a specific tube's own barcode when
#   the source was a well on a scanned tube rack, that source's whole-labware barcode when it was a
#   scanned plate/reservoir (see sample_labware_info's "barcode" above), or null when that source
#   was never scanned this run. A barcode the script assigned with set_barcodes() replaces a scanned
#   one for the same labware or well. "source_barcode_type" says what the barcode identifies: "well"
#   for the well/container the liquid came from, otherwise the source labware's class ("plate",
#   "reservoir", ...) for a whole-labware barcode. A well's barcode travels with the sample: a well
#   that received liquid from a barcoded tube or well reports that barcode (several, "; "-joined,
#   when it was pooled) when it is aspirated from in turn, in preference to its plate's barcode.
# {"type": "tadm_result", "transfer_id", "channel": int, "step_type_name", "curve_flagged": bool,
#  "error_code": str|None, "curve_points": [{"time_ms", "pressure"}], "timestamp"}
#   -- one message per TADM (Aspiration/Dispense Control) curve found on an aspirate/aspirate_5ml/
#   dispense/dispense_5ml response, sent only when that call was made with adc=True (see
#   channel_commands.py's "adc" param) -- most calls never produce one. "transfer_id" matches the
#   transfer_id of the sample_event this curve belongs to (see above) -- there is no other link
#   between the two messages, and delivery order relative to that sample_event isn't guaranteed.
#   "curve_flagged"/"error_code" are VENUS's own pass/fail signal for the curve; "curve_points" is the
#   raw per-sample pressure/time trace (may be empty even when curve_flagged/error_code are set --
#   whether firmware always populates it is unverified, see workflow_framework's tadm.py docstring).
# {"type": "com_trace", "lines": [str], "ts_ms": int, "timestamp"}
#   -- a batch of newly-appended lines from VENUS's firmware COM trace (.trc) file, scraped live
#   during the run by script_runner.py's bootstrap _start_com_trace_tail (which uses the SDK's
#   hamilton_venus._internal._com_trace helper). One message per ~0.5s poll tick (plus a final
#   flush at run end); "lines" are raw "< sent" / "> received" / "! info" firmware lines, each
#   "<dir> HH:MM:SS.mmm <port>: <payload>". The UI renders them under the hidden-by-default
#   "COM Trace" filter with a "COM Trace:" label, and takes each line's [timestamp] column from
#   the line's own embedded local time (not "ts_ms"/"timestamp", which are UTC receipt times).
#   Disabled when settings.com_trace_enabled is false, or silently when the SDK lacks the helper.
# {"type": "consumable_reload_prompt", "reload_uuid", "tip_pool", "required", "available"}
#   -- a pickup needs more tips than remain; re-sent with a fresh reload_uuid if a "show_counter"
#   reload still wasn't enough. Nothing is called on VENUS until the operator answers with
#   consumable_reload_action.
# {"type": "consumable_reload_done", "reload_uuid", "cancelled": bool}
# {"type": "user_input_request", "uuid", "prompt", "timestamp"}
#   -- built inside the subprocess bootstrap's _input_via_manager (installed as builtins.input),
#   so this fires for any input() call the script makes, direct or via a script-local wrapper
#   (e.g. plate_stamp_demo.py's get_user_int()) -- no script changes needed. Nothing resumes on
#   VENUS/in the script until user_input_response arrives; a script-side retry loop (like
#   get_user_int's own range check) re-prompts with a fresh uuid on invalid input.
# {"type": "tk_dialog_request", "uuid", "kind", "title", "message", "minvalue"?, "maxvalue"?,
#  "initialvalue"?, "show"?, "options"?, "timestamp"}
#   -- built inside the subprocess bootstrap's _tk_dialog_request, called from whichever patched
#   tkinter.messagebox.*/simpledialog.ask* function the script invoked -- no script changes
#   needed. "kind" is one of showinfo/showwarning/showerror/askyesno/askokcancel/
#   askretrycancel/askyesnocancel/askinteger/askfloat/askstring/askchoice; minvalue/maxvalue/
#   initialvalue only apply to askinteger/askfloat (initialvalue also to askchoice), "show" only
#   to askstring (e.g. "*" for password masking), "options" only to askchoice (the ordered list
#   of selectable strings). askchoice is a non-standard single-select dropdown picker this bootstrap
#   injects onto simpledialog -- not part of real tkinter (see script_runner.py's _tk_askchoice).
#   Nothing resumes in the script until tk_dialog_response arrives with a matching uuid.
# {"type": "tk_filedialog_request", "uuid", "kind", "title", "initialdir", "initialfile",
#  "defaultextension", "filetypes", "timestamp"}
#   -- built inside the subprocess bootstrap's _tk_filedialog_request, called from whichever
#   patched tkinter.filedialog function the script invoked -- no script changes needed. "kind"
#   is one of askopenfilename/askopenfilenames/asksaveasfilename/askdirectory. Answered with
#   the app's existing file-browser-modal.js (previously operator-only, via the shortcut
#   "Browse..." button) rather than a plain text-field modal, since browsing the real local
#   filesystem is exactly what that component already does.
