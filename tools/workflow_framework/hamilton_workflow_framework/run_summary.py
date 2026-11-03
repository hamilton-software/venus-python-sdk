"""Computes a Summary-tab payload from a finalized SdkRunLog.json.

Pure Python, no FastAPI/pydantic dependency -- keeps this trivially unit
testable and independent of the wire-layer models `hamilton_venus` itself
uses to build the log. Every entry field is read defensively (`.get(...)`
with a default) because a run can end with a truncated or crash-recovered
log (see `hamilton_venus._internal._run_log.RunLog.recover`) that's missing
whole sections -- `summarize_run` must degrade to zeroed counts rather than
raise, since a broken summary must never take down the route that serves it.

Originally `python_script_manager_app/backend/run_summary.py` (Script Manager's own
Summary tab). Moved here so `hamilton_venus_mcp`'s `get_run_summary` tool can share it
without depending on the app -- Script Manager's `routes_http.py` now imports it from
here instead.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class RunLogError(Exception):
    """Raised when a run log file is missing, unreadable, or not valid JSON."""


def load_run_log(log_path: Path) -> dict[str, Any]:
    """Read and JSON-parse a finalized run log file."""
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RunLogError(f"Could not read {log_path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RunLogError(f"Invalid JSON in {log_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RunLogError(f"{log_path} does not contain a JSON object at the top level")
    return data


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _line_at_timestamp(line_timeline: list[Any] | None, ts: float | None) -> int | None:
    """Look up the script line executing at *ts* (epoch seconds) from the
    (epoch_seconds, line_number) samples ScriptRunner records live via
    sys.settrace (see script_runner.py's _LINE_MARKER handling and
    _persist_line_timeline). Samples are chronological, so the last one at or
    before *ts* is the line that was executing when this command was issued --
    it stays "current" until the next line-change sample, which for a command
    call only ever arrives after that command's own request is logged."""
    if not line_timeline or ts is None:
        return None
    result: int | None = None
    for entry in line_timeline:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            continue
        sample_ts, sample_line = entry
        if not isinstance(sample_ts, (int, float)):
            continue
        if sample_ts > ts:
            break
        result = sample_line
    return result


def summarize_run(log: dict[str, Any], line_timeline: list[Any] | None = None) -> dict[str, Any]:
    """Reduce a parsed SdkRunLog dict to the Summary tab's payload. Never raises.

    *line_timeline* is the optional sibling ScriptRunner._persist_line_timeline
    output for this same run -- when present, failed_steps entries get a "line"
    field naming the script line that was executing when the command fired.
    """
    entries = log.get("log")
    if not isinstance(entries, list):
        entries = []

    # Pass 1: command_request entries give the human-readable action_name/
    # category/parameters -- command_response payloads carry none of that in
    # practice (VENUS doesn't currently echo it back), so every later lookup
    # by command_id joins back into this table. Also builds tip_pool ->
    # labware_definition ("tip type") from every add-tip-rack/box/NTR call,
    # since a tip pickup's own request only ever names the pool, not the
    # physical tip type it was mounted with. Same pass tallies plates/lids
    # added by type (labware.addPlate/addLid/addLiddedPlate -- the latter
    # adds one of each) and records which labware ids were explicitly added
    # as reservoirs (labware.addReservoir) THIS run -- this static log has no
    # connected client of its own to ask VENUS whether some other labware's
    # definition also happens to be labware_class "reservoir" (e.g. one
    # already present on a deck loaded via deck_load()/backup-restore, which
    # never re-issues labware.addReservoir), so a second pass right below
    # unions in the live bootstrap's own "reservoir_labware" entries, which
    # cover exactly that gap -- see that pass's comment for detail.
    command_context: dict[str, dict[str, Any]] = {}
    tip_pool_labware: dict[str, str] = {}
    # Which of the 3 add-tip actions registered a pool -- the Summary tab
    # splits "Tips Used by Type" into a section per kind, not just one flat
    # tip-type breakdown, since the same tip_type string could in principle
    # come from more than one of them.
    tip_pool_kind: dict[str, str] = {}
    TIP_LABWARE_ACTION_KIND = {
        "labware.addtiprack": "tip_rack",
        "labware.addtipbox": "tip_box",
        "labware.addntr": "ntr",
    }
    plates_by_type: dict[str, int] = {}
    lids_by_type: dict[str, int] = {}
    reservoir_ids: set[str] = set()
    # Indexed by response "id" (== the originating request's command_id) so
    # an add-tip-* request that omitted tip_pool/labware_id (VENUS then
    # auto-assigns both) can still be classified below by reading the
    # auto-assigned name back out of that same call's own response, since
    # the request's own parameters have no "tipPool" key to key off in that
    # case.
    responses_by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "command_response":
            continue
        response_payload = entry.get("payload")
        if isinstance(response_payload, dict) and isinstance(response_payload.get("id"), str):
            responses_by_id[response_payload["id"]] = response_payload
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "command_request":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        command_id = payload.get("command_id")
        if not isinstance(command_id, str):
            continue
        action_name = payload.get("action_name") or ""
        parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
        request_dt = _parse_iso(entry.get("timestamp"))
        command_context[command_id] = {
            "action_name": action_name,
            "category": payload.get("category") or "",
            "parameters": parameters,
            "timestamp": request_dt.timestamp() if request_dt is not None else None,
        }
        action_lower_req = action_name.lower()
        tip_kind = TIP_LABWARE_ACTION_KIND.get(action_lower_req)
        if tip_kind is not None:
            labware = parameters.get("labwareDefinition")
            # Register under both the client-supplied request name (if any)
            # and the response's own tipPoolName. VENUS lower-cases whatever
            # name it's given when it echoes the pool back in the response
            # (e.g. request "TransferTips" -> response "transfertips"), and
            # a later tip_pickup call may key off either string depending on
            # whether the caller reused its own name or the one VENUS
            # returned -- so both need to resolve to the same kind/tip_type,
            # not just whichever one happens to have been supplied at
            # add-time. When tip_pool was omitted entirely (VENUS then
            # auto-assigns it), the response's tipPoolName is the only name
            # that exists at all.
            candidate_pools: list[str] = []
            request_pool = parameters.get("tipPool")
            if isinstance(request_pool, str) and request_pool:
                candidate_pools.append(request_pool)
            response_payload = responses_by_id.get(command_id)
            return_parameters = (
                response_payload.get("returnParameters") if isinstance(response_payload, dict) else None
            )
            response_pool = return_parameters.get("tipPoolName") if isinstance(return_parameters, dict) else None
            if isinstance(response_pool, str) and response_pool:
                candidate_pools.append(response_pool)
            for pool in candidate_pools:
                tip_pool_kind[pool] = tip_kind
                if isinstance(labware, str):
                    tip_pool_labware[pool] = labware
        if action_lower_req in ("labware.addplate", "labware.addliddedplate"):
            plate_def = parameters.get("labwareDefinition")
            if isinstance(plate_def, str):
                plates_by_type[plate_def] = plates_by_type.get(plate_def, 0) + 1
        if action_lower_req == "labware.addliddedplate":
            lid_def = parameters.get("lidDefinition")
            if isinstance(lid_def, str):
                lids_by_type[lid_def] = lids_by_type.get(lid_def, 0) + 1
        elif action_lower_req == "labware.addlid":
            lid_def = parameters.get("labwareDefinition")
            if isinstance(lid_def, str):
                lids_by_type[lid_def] = lids_by_type.get(lid_def, 0) + 1
        if action_lower_req == "labware.addreservoir":
            reservoir_id = parameters.get("labwareName")
            if isinstance(reservoir_id, str):
                reservoir_ids.add(reservoir_id)

    # A labware.addReservoir request (above) is the only reservoir signal a
    # script that adds its own labware ever produces -- but a deck loaded via
    # deck_load()/backup-restore never re-issues labware.addReservoir for
    # labware that was already part of the saved layout, and deck.loadDeck's
    # own response carries no labware list at all (confirmed against
    # docs/json_schemas_System.md: `{"message": ...}`
    # only). ScriptRunner's live bootstrap (script_runner.py's
    # _is_reservoir_labware) has a connected client and so CAN still ask
    # VENUS whether such a labware's own definition is labwareClass
    # "reservoir" -- it writes that answer into the run log as a
    # "reservoir_labware" entry the first time it discovers one, specifically
    # so this static, connection-less summary pass can trust it exactly like
    # a real labware.addReservoir call. Without this, add_reagent (or any
    # other compound command) drawing from a reservoir that was already on a
    # loaded deck had its volume silently dropped from "Volume Consumed from
    # Reservoirs" below, with no error anywhere.
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "reservoir_labware":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        labware = payload.get("labware")
        if isinstance(labware, str):
            reservoir_ids.add(labware)

    step_count = 0
    error_count = 0
    failed_steps: list[dict[str, Any]] = []
    tip_pickup_calls = 0
    tips_used = 0
    tips_by_type: dict[tuple[str, str], int] = {}  # (kind, tip_type) -> count
    reservoir_volume_ul: dict[str, float] = {}
    tadm_groups: dict[tuple[str, str, float], dict[str, Any]] = {}
    tadm_curve_count = 0
    tadm_flagged_count = 0
    tadm_error_count = 0

    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "command_response":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue

        step_count += 1
        ctx = command_context.get(payload.get("id"), {"action_name": "", "category": "", "parameters": {}, "timestamp": None})

        # Mirrors hamilton_venus.models.commands.CommandResponse.success exactly:
        # return_code == 0 and return_status == "Success".
        is_success = payload.get("returnCode") == 0 and payload.get("returnStatus") == "Success"
        if not is_success:
            error_count += 1
            failure_return_parameters = payload.get("returnParameters")
            message = ""
            if isinstance(failure_return_parameters, dict):
                raw_message = failure_return_parameters.get("message")
                if isinstance(raw_message, str):
                    message = raw_message.strip()
            failed_steps.append({
                "action_name": ctx["action_name"],
                "category": ctx["category"],
                "command_id": payload.get("id") or "",
                "return_code": payload.get("returnCode"),
                "return_status": payload.get("returnStatus"),
                "status": payload.get("status"),
                "message": message,
                "line": _line_at_timestamp(line_timeline, ctx.get("timestamp")),
            })

        action_lower = ctx["action_name"].lower()
        if "tippickup" in action_lower:
            # Channel arms report exactly which channels picked up a tip; the
            # MPH96 head has no per-channel selection -- a full pickup is
            # always all 96, and a partial pickup's count is columns/rows of
            # tips on a standard 96-well (8x12) grid, not a literal channel list.
            if "mph96" in action_lower:
                if "partial" in action_lower:
                    mode = ctx["parameters"].get("mode")
                    count = ctx["parameters"].get("count") or 0
                    per_unit = 8 if mode == "cols" else 12 if mode == "rows" else 0
                    n = count * per_unit
                else:
                    n = 96
            else:
                channels = ctx["parameters"].get("channels")
                n = len(channels) if isinstance(channels, list) else 0

            tip_pickup_calls += 1
            tips_used += n
            pool = ctx["parameters"].get("tipPool")
            tip_type = tip_pool_labware.get(pool, pool) if isinstance(pool, str) else "(unknown tip type)"
            kind = tip_pool_kind.get(pool, "unknown") if isinstance(pool, str) else "unknown"
            key = (kind, tip_type)
            tips_by_type[key] = tips_by_type.get(key, 0) + n

        # Volume drawn from each reservoir added this run (reservoir_ids, from
        # pass 1). Channel-based aspirate (1mL/5mL) carries a "positions" list
        # already expanded to one entry per channel (see AspirateParameters --
        # a single-well selector repeated across channels lands here as N
        # copies of the same position) alongside "volumes", either a scalar
        # applied to every channel or a list matching positions 1:1; mph96
        # aspirate instead names one labware directly with a single "volume"
        # applied across the whole head (or the mphSelection subset, when set).
        if "aspirate" in action_lower:
            if "mph96" in action_lower:
                labware = ctx["parameters"].get("labwareName")
                if isinstance(labware, str) and labware in reservoir_ids:
                    mph_selection = ctx["parameters"].get("mphSelection")
                    channels_used = len(mph_selection) if isinstance(mph_selection, list) else 96
                    try:
                        volume = float(ctx["parameters"].get("volume") or 0.0)
                    except (TypeError, ValueError):
                        volume = 0.0
                    reservoir_volume_ul[labware] = reservoir_volume_ul.get(labware, 0.0) + volume * channels_used
            else:
                positions = ctx["parameters"].get("positions")
                volumes = ctx["parameters"].get("volumes")
                if isinstance(positions, list) and positions:
                    if isinstance(volumes, list) and len(volumes) == len(positions):
                        volume_list = volumes
                    else:
                        try:
                            scalar_volume = float(volumes)
                        except (TypeError, ValueError):
                            scalar_volume = 0.0
                        volume_list = [scalar_volume] * len(positions)
                    for pos, vol in zip(positions, volume_list):
                        if not isinstance(pos, dict):
                            continue
                        labware = pos.get("labwareId")
                        if not isinstance(labware, str) or labware not in reservoir_ids:
                            continue
                        try:
                            reservoir_volume_ul[labware] = reservoir_volume_ul.get(labware, 0.0) + float(vol)
                        except (TypeError, ValueError):
                            continue

        return_parameters = payload.get("returnParameters")
        if not isinstance(return_parameters, dict):
            continue
        tadm = return_parameters.get("TADM")
        if not isinstance(tadm, dict):
            continue
        curves = tadm.get("tadmCurves")
        if not isinstance(curves, list):
            continue
        for curve in curves:
            if not isinstance(curve, dict):
                continue
            liquid_class_name = curve.get("liquidClassName") or ""
            step_type_name = curve.get("stepTypeName") or ""
            try:
                volume = float(curve.get("volume") or 0.0)
            except (TypeError, ValueError):
                volume = 0.0
            key = (liquid_class_name, step_type_name, round(volume, 3))
            group = tadm_groups.setdefault(
                key,
                {"liquid_class_name": liquid_class_name, "step_type_name": step_type_name, "volume": volume, "curves": []},
            )
            raw_points = curve.get("curvePoints")
            curve_points = (
                [
                    {"time_ms": p.get("timeMs"), "pressure": p.get("pressure")}
                    for p in raw_points
                    if isinstance(p, dict)
                ]
                if isinstance(raw_points, list)
                else []
            )
            group["curves"].append({
                "channel_number": curve.get("channelNumber"),
                "curve_id": curve.get("curveId"),
                "error": curve.get("error") or 0,
                "curve_flagged": curve.get("curveFlagged") or 0,
                "step_number": curve.get("stepNumber"),
                "action_name": ctx["action_name"],
                "category": ctx["category"],
                "curve_points": curve_points,
            })
            tadm_curve_count += 1
            if curve.get("curveFlagged"):
                tadm_flagged_count += 1
            if curve.get("error"):
                tadm_error_count += 1

    # Hardware-level errors surface as a SignalR "instrument_error" event
    # (ErrorData.model_dump() -- plain attribute names, NOT by_alias, unlike
    # the WebAPI command entries) and, once the operator or error profile
    # picks a response, a separate "device_error_handled" event
    # (InstrumentErrorHandled.model_dump(): {"uuid", "recovery_action"})
    # sharing the same uuid. These are distinct from a command_response's own
    # returnCode/returnStatus failure -- a successfully recovered instrument
    # error can still end with the retried command reporting success, so this
    # is additional signal, not a duplicate of failed_steps above.
    recovery_by_uuid: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("source") != "SignalR" or entry.get("type") != "device_error_handled":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        uuid = payload.get("uuid")
        if isinstance(uuid, str):
            recovery_by_uuid[uuid] = payload.get("recovery_action") or ""

    # device_error_handled.recovery_action is only accurate for the *simple*
    # path (one action, e.g. "Abort", submitted directly as the top-level
    # selectedActionId). When a per-channel selection was submitted instead
    # (this app's operator-recovery-modal.js's grouped dropdowns), the actual
    # POST .../recovery request's top-level selectedActionId is always the
    # fixed "Execute" wrapper id -- meaning "apply the detailedErrorRecoveries
    # below" -- NOT the real per-channel action the operator picked, so
    # device_error_handled reports "Execute" regardless of what was actually
    # chosen. The genuine per-channel choice only exists in that same
    # http_request's own body.detailedErrorRecoveries[i].selectedActionId,
    # keyed by each detail's own uuid -- captured here so it can override the
    # generic "Execute" below.
    detail_action_id_by_uuid: dict[str, int] = {}
    action_id_to_name: dict[int, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("source") != "WebAPI" or entry.get("type") != "http_request":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict) or payload.get("method") != "POST":
            continue
        path = payload.get("path") or ""
        if not (path.startswith("/api/vector/v3/instrument-errors/") and path.endswith("/recovery")):
            continue
        body = payload.get("body")
        if not isinstance(body, dict):
            continue
        for detail_recovery in body.get("detailedErrorRecoveries") or []:
            if not isinstance(detail_recovery, dict):
                continue
            detail_uuid = detail_recovery.get("uuid")
            action_id = detail_recovery.get("selectedActionId")
            if isinstance(detail_uuid, str) and isinstance(action_id, int):
                detail_action_id_by_uuid[detail_uuid] = action_id

    # Grouped by (event uuid, exact detail message) rather than flattened to
    # one row per channel -- error.message is frequently just the raw code
    # (e.g. "P1:06/71"); the real description lives in error.title (the step
    # that failed) and, for multi-channel errors, in each detailed_errors[i]
    # .message (e.g. "Not enough liquid..."). Multiple channels overwhelmingly
    # share the exact same message for the exact same event (VENUS raises one
    # message template per failure kind, tagged per-channel via each detail's
    # own attributes) -- grouping those into one row with a "channels" list
    # avoids repeating the identical sentence 3-8 times, while channels that
    # genuinely got a *different* message within the same event still land in
    # their own row, since that's a real distinction worth keeping visible.
    instrument_errors: list[dict[str, Any]] = []
    instrument_error_uuids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("source") != "SignalR" or entry.get("type") != "instrument_error":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        uuid = payload.get("uuid")
        if isinstance(uuid, str):
            instrument_error_uuids.add(uuid)
        step = payload.get("title") or payload.get("message") or payload.get("code") or "(unknown error)"
        fallback_recovery_action = recovery_by_uuid.get(uuid) if isinstance(uuid, str) else None
        date = payload.get("date")

        for descriptor in payload.get("recovery_actions") or []:
            if isinstance(descriptor, dict) and isinstance(descriptor.get("id"), int) and descriptor.get("name"):
                action_id_to_name[descriptor["id"]] = descriptor["name"]

        detailed_errors = payload.get("detailed_errors")
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        group_order: list[tuple[str, str]] = []
        if isinstance(detailed_errors, list):
            for detail in detailed_errors:
                if not isinstance(detail, dict):
                    continue
                message = detail.get("message")
                if not message:
                    continue
                for descriptor in detail.get("recovery_actions") or []:
                    if isinstance(descriptor, dict) and isinstance(descriptor.get("id"), int) and descriptor.get("name"):
                        action_id_to_name[descriptor["id"]] = descriptor["name"]
                channel = None
                for attr in detail.get("attributes") or []:
                    if isinstance(attr, dict) and attr.get("name") == "channel":
                        channel = attr.get("value")
                        break
                code = detail.get("code") or payload.get("code")
                key = (message, code or "")
                if key not in groups:
                    groups[key] = {"channels": [], "detail_uuids": [], "detail": message, "code": code}
                    group_order.append(key)
                if channel:
                    groups[key]["channels"].append(channel)
                detail_uuid = detail.get("uuid")
                if isinstance(detail_uuid, str):
                    groups[key]["detail_uuids"].append(detail_uuid)
        if not groups:
            message = payload.get("message")
            fallback_detail = message if message and message != payload.get("code") else step
            key = (fallback_detail, payload.get("code") or "")
            groups[key] = {"channels": [], "detail_uuids": [], "detail": fallback_detail, "code": payload.get("code")}
            group_order.append(key)

        for key in group_order:
            group = groups[key]
            # The genuine per-channel action a group was actually resolved
            # with only exists in the matching http_request's own
            # detailedErrorRecoveries -- device_error_handled's top-level
            # recovery_action is always the fixed "Execute" wrapper name
            # whenever that path was used, which isn't what the operator
            # actually picked for this specific group. Only fall back to it
            # when no per-detail submission was found at all (the plain
            # top-level path, e.g. a straight "Abort").
            recovery_action = fallback_recovery_action
            for detail_uuid in group["detail_uuids"]:
                submitted_id = detail_action_id_by_uuid.get(detail_uuid)
                if submitted_id is not None:
                    recovery_action = action_id_to_name.get(submitted_id, recovery_action)
                    break
            instrument_errors.append({
                "uuid": uuid or "",
                "step": step,
                "channels": group["channels"],
                "detail": group["detail"],
                "code": group["code"],
                "recovery_action": recovery_action,
                "date": date,
            })

    # session_start/session_end (source "SDK") give simulate mode and the
    # authoritative pass/fail + duration -- preferred over the top-level
    # reason/started_at/ended_at fields, which are the fallback when a
    # crash-recovered log never got a session_end entry written at all.
    simulate: bool | None = None
    duration_seconds: float | None = None
    reason: str | None = log.get("reason") if isinstance(log.get("reason"), str) else None
    error_type: str | None = None
    error_message: str | None = None

    for entry in entries:
        if not isinstance(entry, dict) or entry.get("source") != "SDK":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        if entry.get("type") == "session_start" and "simulate" in payload:
            simulate = bool(payload.get("simulate"))
        elif entry.get("type") == "session_end":
            if isinstance(payload.get("duration_seconds"), (int, float)):
                duration_seconds = float(payload["duration_seconds"])
            if isinstance(payload.get("reason"), str):
                reason = payload["reason"]
            error_type = payload.get("error_type")
            error_message = payload.get("error_message")

    if duration_seconds is None:
        started = _parse_iso(log.get("started_at"))
        ended = _parse_iso(log.get("ended_at"))
        if started is not None and ended is not None:
            duration_seconds = (ended - started).total_seconds()

    if reason == "normal":
        result = "success"
    elif reason == "error":
        result = "error"
    else:
        result = "unknown"

    # Grouped by kind first (in this fixed display order), count descending
    # within each kind -- not just one flat count-descending list -- so the
    # Summary tab can split "Tips Used by Type" into its 3 (or 4, for a pool
    # this log has no matching add-tip-* request for at all) sections.
    TIP_KIND_ORDER = ["tip_rack", "tip_box", "ntr", "unknown"]
    TIP_KIND_LABELS = {"tip_rack": "Tip Rack", "tip_box": "Tip Box", "ntr": "Nested Tip Rack", "unknown": "Other"}
    sorted_tips_by_type = sorted(
        tips_by_type.items(),
        key=lambda kv: (TIP_KIND_ORDER.index(kv[0][0]), -kv[1]),
    )
    sorted_plates_by_type = sorted(plates_by_type.items(), key=lambda kv: kv[1], reverse=True)
    sorted_lids_by_type = sorted(lids_by_type.items(), key=lambda kv: kv[1], reverse=True)
    # Only reservoirs actually drawn from -- one that was added but never
    # aspirated has nothing to report and is dropped here rather than shown
    # at 0 uL, mirroring "no plates/lids used" also omitting that breakdown.
    sorted_reservoir_volumes = sorted(
        ((labware, volume) for labware, volume in reservoir_volume_ul.items() if volume > 0),
        key=lambda kv: kv[1],
        reverse=True,
    )

    return {
        "script_name": log.get("script_name"),
        "simulate": simulate,
        "started_at": log.get("started_at"),
        "ended_at": log.get("ended_at"),
        "duration_seconds": duration_seconds,
        "result": result,
        "error_type": error_type,
        "error_message": error_message,
        "step_count": step_count,
        # Counts distinct error *events*, not the per-channel rows below -- one
        # hardware error affecting 8 channels is one error, not eight, even
        # though the table renders a row per channel for readability.
        "error_count": error_count + len(instrument_error_uuids),
        "failed_steps": failed_steps,
        "instrument_errors": instrument_errors,
        "tip_pickup_calls": tip_pickup_calls,
        "tips_used": tips_used,
        "tips_by_type": [
            {"kind": kind, "kind_label": TIP_KIND_LABELS[kind], "tip_type": name, "count": count}
            for (kind, name), count in sorted_tips_by_type
        ],
        "plates_by_type": [{"labware_definition": name, "count": count} for name, count in sorted_plates_by_type],
        "lids_by_type": [{"labware_definition": name, "count": count} for name, count in sorted_lids_by_type],
        "reservoir_volumes": [
            {"labware": name, "volume_ul": round(volume, 2)} for name, volume in sorted_reservoir_volumes
        ],
        "tadm_totals": {
            "curve_count": tadm_curve_count,
            "flagged_count": tadm_flagged_count,
            "error_count": tadm_error_count,
        },
        "tadm_groups": [
            {
                "liquid_class_name": group["liquid_class_name"],
                "step_type_name": group["step_type_name"],
                "volume": group["volume"],
                "curves": group["curves"],
            }
            for group in tadm_groups.values()
        ],
    }
