// Detailed per-labware report, opened from a Sample Tracking card's "Report"
// button (sample-tracking-view.js's _renderCard). Built entirely from what the
// view already holds for that labware -- its sample_event steps (grouped by
// target well, chronological within each) and the tadm_result messages whose
// transfer_id belongs to one of those steps -- so it always matches the card.
//
// show() first reduces that into one plain report object (_buildReport); the
// modal and the JSON export are both that object, so they cannot drift apart.
//
// Layout, top to bottom: a row of stat cards, the transfer table (in its own
// height-capped scroll area, so its horizontal scrollbar stays on screen), and
// the TADM curves of this labware's transfers, grouped by liquid class, then
// by step (aspirate/dispense) and volume -- the same chart
// renderSummaryTadmChart draws on the Summary tab.
//
// Table columns: source and target of every transfer, the scanned barcodes
// on both sides, liquid class, the cLLD liquid level / measured volume the
// aspirate reported (only when cLLD was on for that channel), TADM flags,
// and status. A transfer that hit an instrument error is highlighted, with
// one line per error underneath: what it was and the recovery submitted
// (sample_event's "errors" -- see script_runner.py's
// _record_sample_error_recovery).
const LABWARE_REPORT_COLUMNS = [
  "Time", "Operation", "Source", "Source barcode", "Target", "Target barcode", "Ch", "Volume (µL)",
  "Liquid class", "cLLD level (mm)", "cLLD volume (µL)", "TADM", "Status",
];

class LabwareReportModal {
  constructor() {
    this.modalEl = document.getElementById("labware-report-modal");
    this.titleEl = document.getElementById("labware-report-title");
    this.bodyEl = document.getElementById("labware-report-body");
    this.report = null;
    document.getElementById("labware-report-modal-close").addEventListener("click", () => this.close());
    document.getElementById("labware-report-close").addEventListener("click", () => this.close());
    document.getElementById("labware-report-export-csv").addEventListener("click", () => this._exportCsv());
    document.getElementById("labware-report-export-json").addEventListener("click", () => this._exportJson());
    this.modalEl.addEventListener("click", (event) => {
      if (event.target === this.modalEl) this.close();
    });
  }

  // entry: the view's labware entry ({labware_class, barcode, wells: {well -> {current_volume_ul, steps}}}).
  // tadmByTransferId: Map transfer_id -> tadm_result message.
  // aspirateTarget: aspirate transfer_id -> {labware, well, barcode} it was dispensed to, or null.
  show({ labwareId, entry, tadmByTransferId, aspirateTarget = () => null }) {
    this.report = _buildReport(labwareId, entry, tadmByTransferId, aspirateTarget);
    this.titleEl.textContent = `Report — ${labwareId}`;
    this.bodyEl.innerHTML = "";
    this.bodyEl.appendChild(this._summary(this.report));
    this.bodyEl.appendChild(this._tableSection(this.report));
    this.bodyEl.appendChild(this._tadmSection(this.report));
    this.modalEl.hidden = false;
  }

  close() {
    this.modalEl.hidden = true;
    this.bodyEl.innerHTML = "";
    this.report = null;
  }

  _summary(report) {
    const tiles = [
      ["Labware", report.labware],
      ["Type", report.type],
      ["Barcode", report.barcode || "—"],
      ["Wells", String(report.summary.wells)],
      ["Transfers", String(report.summary.transfers)],
      ["Errors", String(report.summary.errors), report.summary.errors > 0],
      ["TADM flagged", String(report.summary.tadm_flagged), report.summary.tadm_flagged > 0],
    ];
    const row = document.createElement("div");
    row.className = "summary-stat-row labware-report-stats";
    tiles.forEach(([label, value, alert]) => {
      const tile = document.createElement("div");
      tile.className = "summary-stat-tile";
      if (alert) tile.classList.add("labware-report-stat-alert");
      const l = document.createElement("div");
      l.className = "summary-stat-label";
      l.textContent = label;
      const v = document.createElement("div");
      v.className = "summary-stat-value";
      v.textContent = value;
      v.title = value;
      if (label === "TADM flagged") tile.title = "Transfers with a flagged or failed TADM curve";
      tile.append(l, v);
      row.appendChild(tile);
    });
    return row;
  }

  _tableSection(report) {
    const section = document.createElement("div");
    section.className = "labware-report-section";
    const title = document.createElement("div");
    title.className = "summary-section-title";
    title.textContent = "Transfers";
    section.appendChild(title);

    const wrap = document.createElement("div");
    wrap.className = "labware-report-table-wrap";
    const table = document.createElement("table");
    table.className = "labware-report-table";

    const head = table.createTHead().insertRow();
    LABWARE_REPORT_COLUMNS.forEach((text) => {
      const th = document.createElement("th");
      th.textContent = text;
      if (text.startsWith("cLLD")) {
        th.title = "Liquid level and measured volume reported by the aspirate, when cLLD was on for that channel " +
          "(for a dispense: its source aspirate)";
      }
      head.appendChild(th);
    });

    const body = table.createTBody();
    report.wells.forEach((well) => {
      const groupRow = body.insertRow();
      groupRow.className = "labware-report-well-row";
      const cell = groupRow.insertCell();
      cell.colSpan = LABWARE_REPORT_COLUMNS.length;
      // Pinned to the left edge so the well stays readable while the table is
      // scrolled sideways (same for the error lines below).
      const label = document.createElement("div");
      label.className = "labware-report-sticky";
      cell.appendChild(label);
      label.textContent =
        `${report.labware}@${well.well} — ${well.transfer_count} transfer${well.transfer_count === 1 ? "" : "s"}, ` +
        `current volume ${_fmt(well.current_volume_ul, 0)} µL` +
        (well.error_count ? ` — ${well.error_count} error${well.error_count === 1 ? "" : "s"}` : "");

      well.transfers.forEach((t) => {
        const hasError = t.error_count > 0;
        const tadmIssue = _tadmSides(t).some((s) => s.flagged || s.error);
        const row = body.insertRow();
        if (hasError) row.className = "labware-report-row-error";
        const values = [
          _formatTime(t.time),
          t.operation === "dispense" ? "Dispense" : "Aspirate",
          t.source,
          _barcodeText(t.source_barcode, t.source_barcode_type),
          t.target || "",
          t.target_barcode || "",
          String(t.channel),
          `${t.operation === "dispense" ? "+" : "-"}${_fmt(t.volume_ul, 1)}`,
          t.liquid_class || "",
          _fmt(t.clld_level_mm, 1),
          _fmt(t.clld_volume_ul, 1),
          _tadmText(_tadmSides(t)),
          t.status,
        ];
        values.forEach((text, i) => {
          const td = row.insertCell();
          td.textContent = text;
          if (i === 11 && tadmIssue) td.className = "labware-report-flagged";
          if (i === 12 && hasError) td.className = "labware-report-error";
        });
        if (hasError) body.appendChild(this._errorDetailRow(t));
      });
    });
    wrap.appendChild(table);
    section.appendChild(wrap);
    return section;
  }

  // The line(s) under a highlighted transfer: each instrument error it hit and
  // the recovery submitted for it, then the failure message if the command
  // itself ended in an error.
  _errorDetailRow(transfer) {
    const row = document.createElement("tr");
    row.className = "labware-report-row-error labware-report-error-detail";
    const cell = row.insertCell();
    cell.colSpan = LABWARE_REPORT_COLUMNS.length;
    const list = document.createElement("div");
    list.className = "labware-report-error-list labware-report-sticky";

    transfer.errors.forEach((e) => {
      const item = document.createElement("div");
      item.className = "labware-report-error-item";
      const what = document.createElement("span");
      what.className = "labware-report-error-what";
      what.textContent = [
        _formatTime(e.time),
        e.during ? e.during.charAt(0).toUpperCase() + e.during.slice(1) : null,
        e.channel !== null && e.channel !== undefined ? `Ch ${e.channel}` : e.position ? `Pos ${e.position}` : null,
        e.code,
        e.message || e.title || "Instrument error",
      ].filter(Boolean).join(" · ");
      const recovery = document.createElement("span");
      recovery.className = "labware-report-error-recovery";
      recovery.textContent = _recoveryText(e);
      item.append(what, recovery);
      list.appendChild(item);
    });
    if (!transfer.success) {
      const item = document.createElement("div");
      item.className = "labware-report-error-item";
      const what = document.createElement("span");
      what.className = "labware-report-error-what";
      what.textContent = `Command failed · ${transfer.error || "no error message reported"}`;
      item.appendChild(what);
      list.appendChild(item);
    }
    cell.appendChild(list);
    return row;
  }

  _tadmSection(report) {
    const section = document.createElement("div");
    section.className = "labware-report-section labware-report-tadm";
    const title = document.createElement("div");
    title.className = "summary-section-title";
    title.textContent = "TADM Pressure Curves";
    section.appendChild(title);

    // Every curve of this labware's transfers: a dispense's own curve and its
    // source aspirate's curve, an aspirate-out's own curve. Deduplicated by
    // transfer_id (a multi-dispense aspirate feeds several wells).
    const curves = new Map();
    report.wells.forEach((well) => well.transfers.forEach((t) => {
      Object.values(t.tadm || {}).forEach((tadm) => curves.set(tadm.transfer_id, tadm));
    }));
    if (curves.size === 0) {
      const hint = document.createElement("div");
      hint.className = "summary-empty-hint";
      hint.textContent = "No TADM data was collected for this labware's transfers.";
      section.appendChild(hint);
      return section;
    }

    // liquid class -> "step · volume" -> [tadm]
    const byClass = new Map();
    curves.forEach((tadm) => {
      const lc = tadm.liquid_class_name || "(unknown liquid class)";
      const sub = `${tadm.step_type_name || "?"} · ${tadm.volume !== null && tadm.volume !== undefined ? _fmt(tadm.volume, 0) + " µL" : "?"}`;
      if (!byClass.has(lc)) byClass.set(lc, new Map());
      const groups = byClass.get(lc);
      if (!groups.has(sub)) groups.set(sub, []);
      groups.get(sub).push(tadm);
    });

    [...byClass.keys()].sort().forEach((lc) => {
      const lcEl = document.createElement("div");
      lcEl.className = "summary-tadm-lc-section";
      const lcTitle = document.createElement("div");
      lcTitle.className = "summary-tadm-lc-title";
      lcTitle.textContent = lc;
      lcEl.appendChild(lcTitle);
      const grid = document.createElement("div");
      grid.className = "summary-tadm-groups";
      [...byClass.get(lc).entries()].sort(([a], [b]) => _stepOrder(a) - _stepOrder(b) || a.localeCompare(b)).forEach(([sub, list]) => {
        const groupEl = document.createElement("div");
        groupEl.className = "summary-tadm-group";
        const header = document.createElement("div");
        header.className = "summary-tadm-group-header";
        const t = document.createElement("span");
        t.className = "summary-tadm-group-title";
        t.textContent = sub;
        const flagged = list.filter((x) => x.curve_flagged).length;
        const errors = list.filter((x) => x.error_code).length;
        const c = document.createElement("span");
        c.className = "summary-tadm-group-counts";
        c.textContent = `${list.length} curve${list.length === 1 ? "" : "s"}` +
          (flagged || errors ? ` · ${flagged} flagged · ${errors} error${errors === 1 ? "" : "s"}` : "");
        header.append(t, c);
        groupEl.appendChild(header);
        const host = document.createElement("div");
        groupEl.appendChild(host);
        grid.appendChild(groupEl);
        renderSummaryTadmChart(host, list.map(_toChartCurve));
      });
      lcEl.appendChild(grid);
      section.appendChild(lcEl);
    });
    return section;
  }

  // One row per target well: target plate, its barcode, the well, the scanned
  // barcode(s) of whatever was dispensed into it, its current volume and its
  // error count.
  _exportCsv() {
    if (!this.report) return;
    const report = this.report;
    const rows = [[
      "target_plate", "target_plate_barcode", "target_well", "source_barcode", "source_barcode_type",
      "total_volume_ul", "error_count",
    ]];
    report.wells.forEach((well) => {
      rows.push([
        report.labware,
        report.barcode || "",
        well.well,
        well.source_barcodes.join("; "),
        well.source_barcode_types.join("; "),
        _fmt(well.current_volume_ul, 1),
        String(well.error_count),
      ]);
    });
    const csv = rows.map((row) => row.map(_csvCell).join(",")).join("\r\n") + "\r\n";
    // BOM so Excel reads the file as UTF-8.
    _downloadFile(`${_fileStem(report)}.csv`, "﻿" + csv, "text/csv;charset=utf-8");
  }

  _exportJson() {
    if (!this.report) return;
    _downloadFile(`${_fileStem(this.report)}.json`, JSON.stringify(this.report, null, 2), "application/json");
  }
}

// The report as plain data: what the modal shows and what "Export JSON" writes.
function _buildReport(labwareId, entry, tadmByTransferId, aspirateTarget = () => null) {
  const wellIds = Object.keys(entry.wells).sort(_compareWellIds);
  const tadmFor = (id) => {
    const t = id !== null && id !== undefined ? tadmByTransferId.get(id) : null;
    if (!t) return null;
    return {
      transfer_id: t.transfer_id,
      channel: t.channel,
      step_type_name: t.step_type_name || "",
      liquid_class_name: t.liquid_class_name || "",
      volume: t.volume ?? null,
      curve_flagged: !!t.curve_flagged,
      error_code: t.error_code || null,
      timestamp: t.timestamp || null,
      curve_points: t.curve_points || [],
    };
  };

  const wells = wellIds.map((wellId) => {
    const well = entry.wells[wellId];
    const transfers = well.steps.map((step) => {
      const isDispense = step.operation === "dispense";
      const errors = (step.errors || []).map((e) => ({
        time: e.time || null,
        during: e.during || null,
        code: e.code || null,
        detail_code: e.detail_code || null,
        title: e.title || null,
        message: e.message || null,
        channel: e.channel ?? null,
        position: e.position ?? null,
        recovery: e.recovery || null,
        recovery_kind: e.kind || "recovery",
        decided_by: e.decided_by || null,
        inputs: e.inputs || [],
      }));
      const tadm = {};
      const aspirate = tadmFor(isDispense ? step.source_transfer_id : step.transfer_id);
      const dispense = isDispense ? tadmFor(step.transfer_id) : null;
      if (aspirate) tadm.aspirate = aspirate;
      if (dispense) tadm.dispense = dispense;
      // An aspirate's target is the dispense that used it, once that has happened.
      const aspirateTo = isDispense ? null : aspirateTarget(step.transfer_id);
      return {
        time: step.timestamp || null,
        operation: step.operation,
        source: isDispense
          ? (step.source_labware ? `${step.source_labware}@${step.source_well}` : "unknown")
          : `${labwareId}@${wellId}`,
        source_labware: isDispense ? step.source_labware || null : labwareId,
        source_well: isDispense ? step.source_well || null : wellId,
        source_barcode: (isDispense ? step.source_barcode : entry.barcode) || null,
        // What that barcode identifies: "well" (the well/container the liquid came
        // from) or the source labware's class ("plate", ...) for a whole-labware barcode.
        source_barcode_type: isDispense
          ? (step.source_barcode ? step.source_barcode_type || null : null)
          : (entry.barcode ? entry.labware_class || "labware" : null),
        target: isDispense ? `${labwareId}@${wellId}` : aspirateTo ? `${aspirateTo.labware}@${aspirateTo.well}` : null,
        target_barcode: isDispense ? entry.barcode || null : aspirateTo?.barcode || null,
        channel: step.channel,
        volume_ul: step.volume,
        liquid_class: step.liquid_class || null,
        clld_level_mm: step.lld ? step.liquid_level_mm ?? null : null,
        clld_volume_ul: step.lld ? step.liquid_volume_ul ?? null : null,
        success: !!step.success,
        status: !step.success ? "Failed" : errors.length ? "Recovered" : "OK",
        error: step.success ? null : step.error || null,
        // A failed command counts once even when no instrument error was recorded for it.
        error_count: errors.length || (step.success ? 0 : 1),
        errors,
        ...(Object.keys(tadm).length ? { tadm } : {}),
      };
    });
    // Distinct barcodes dispensed into this well -> what each identifies.
    const sources = new Map();
    transfers.forEach((t) => {
      if (t.operation === "dispense" && t.source_barcode && !sources.has(t.source_barcode)) {
        sources.set(t.source_barcode, t.source_barcode_type || "unknown");
      }
    });
    return {
      well: wellId,
      current_volume_ul: well.current_volume_ul,
      transfer_count: transfers.length,
      error_count: transfers.reduce((n, t) => n + t.error_count, 0),
      source_barcodes: [...sources.keys()],
      source_barcode_types: [...sources.values()],
      transfers,
    };
  });

  const all = wells.flatMap((w) => w.transfers);
  return {
    labware: labwareId,
    type: entry.labware_class || "unknown",
    barcode: entry.barcode || null,
    generated_at: new Date().toISOString(),
    summary: {
      wells: wells.length,
      transfers: all.length,
      errors: all.reduce((n, t) => n + t.error_count, 0),
      tadm_flagged: all.filter((t) => _tadmSides(t).some((s) => s.flagged || s.error)).length,
    },
    wells,
  };
}

// TADM curves of one report transfer: [{side, flagged, error}] for those that exist.
function _tadmSides(transfer) {
  const out = [];
  const tadm = transfer.tadm || {};
  if (tadm.aspirate) out.push({ side: "Asp", flagged: tadm.aspirate.curve_flagged, error: tadm.aspirate.error_code });
  if (tadm.dispense) out.push({ side: "Disp", flagged: tadm.dispense.curve_flagged, error: tadm.dispense.error_code });
  return out;
}

function _tadmText(sides) {
  if (sides.length === 0) return "";
  return sides.map((f) => `${f.side} ${f.error ? `error ${f.error}` : f.flagged ? "flagged" : "OK"}`).join(" · ");
}

// "SMP0001 (well)" / "PLT-0001 (plate)": the barcode and what it identifies.
function _barcodeText(barcode, type) {
  if (!barcode) return "";
  return type ? `${barcode} (${type})` : barcode;
}

function _recoveryText(error) {
  if (!error.recovery) return "Recovery: not recorded";
  const label = error.recovery_kind === "action" ? "Action" : "Recovery";
  const inputs = (error.inputs || []).map((i) => `${i.name}: ${i.value}`).join(", ");
  return `${label}: ${error.recovery}` +
    (error.decided_by ? ` (${error.decided_by})` : "") +
    (inputs ? ` — ${inputs}` : "");
}

function _stepOrder(label) {
  return label.toLowerCase().startsWith("aspirat") ? 0 : 1;
}

function _csvCell(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function _fileStem(report) {
  const safe = String(report.labware).replace(/[^A-Za-z0-9._-]+/g, "_");
  const stamp = report.generated_at.replace(/[-:]/g, "").replace(/\..*$/, "").replace("T", "_");
  return `${safe}_report_${stamp}`;
}

function _downloadFile(filename, content, mimeType) {
  const url = URL.createObjectURL(new Blob([content], { type: mimeType }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Plate wells ("A1") sort down each column (A1, B1, ... H1, A2, ...), whatever
// the labware's own addressing pattern -- the order channels pipette a plate
// in; numeric tube positions ("17") sort numerically.
function _compareWellIds(a, b) {
  const pa = _parseWellId(a);
  const pb = _parseWellId(b);
  if (pa && pb) return pa.col - pb.col || pa.row - pb.row;
  const na = Number(a);
  const nb = Number(b);
  if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
  return String(a).localeCompare(String(b));
}

function _parseWellId(id) {
  const m = /^([A-Za-z]+)(\d+)$/.exec(String(id));
  if (!m) return null;
  const letters = m[1].toUpperCase();
  let row = 0;
  for (const ch of letters) row = row * 26 + (ch.charCodeAt(0) - 64);
  return { row, col: Number(m[2]) };
}

function _fmt(value, digits) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "";
  return Number(value).toFixed(digits);
}

function _formatTime(isoString) {
  if (!isoString) return "";
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return isoString;
  return d.toLocaleTimeString([], { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
}
