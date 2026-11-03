// Renders the "Summary" tab once a run reaches a terminal state, from the
// condensed payload GET /api/logs/{filename}/summary computes off the same
// SdkRunLog.json "Export Log" already downloads (see backend/run_summary.py).
//
// The TADM chart below is an adapted copy of demo_app's canvas.js
// renderTadmChart (same axes/tooltip/legend machinery), not a shared import
// -- this app has no module system linking the two -- extended with
// grouping-aware filtering and flagged/error highlighting, which the
// original never needed since it only ever rendered one step's curves at a
// time. Unlike the original, the categorical palette here is pulled live
// from this app's own OneHamilton CSS custom properties (see
// _summaryCategoricalColors) rather than a hand-picked hex list, so chart
// colors are always on-brand and correct for the active light/dark theme
// with no separate light/dark array to keep in sync.

function _summaryCssVar(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

// Categorical series colors for the TADM chart legend/lines and the pie
// charts (tips/plates/lids/reservoirs) -- the non-semantic OneHamilton brand
// hues (primary blue, the two secondary teals, positive green, info blue,
// and the primary hover tint), read live from CSS custom properties so they
// track the active theme automatically. Deliberately excludes --color-negative
// and --trace-warning/--color-warning: those are reserved for the TADM
// chart's own error/flagged overlay (see colorFor below) and must never
// double as an ordinary series color, or a flagged/error curve could land on
// the same hue as an unrelated healthy one by coincidence of channel index.
function _summaryCategoricalColors() {
  return [
    _summaryCssVar("--color-primary", "#1c2d57"),
    _summaryCssVar("--color-secondary-3", "#00858f"),
    _summaryCssVar("--color-secondary-4", "#009988"),
    _summaryCssVar("--color-positive", "#1bc300"),
    _summaryCssVar("--color-info", "#0092d3"),
    _summaryCssVar("--color-primary-hover", "#495779"),
  ];
}

// Mirrors consumables-view.js's _formatReservoirVolumeUl (duplicated, not
// imported -- see this file's header comment on why: no module system links
// the view files). Above 1000 uL, mL at 3 decimals reads far easier than a
// long integer, e.g. 50667 uL -> "50.667 mL".
function _formatReservoirVolumeUl(volumeUl) {
  if (volumeUl === null || volumeUl === undefined) return "—";
  if (Math.abs(volumeUl) > 1000) return `${(volumeUl / 1000).toFixed(3)} mL`;
  return `${Math.round(volumeUl)} µL`;
}

function _formatDuration(seconds) {
  if (seconds === null || seconds === undefined || !isFinite(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// Adapted from demo_app/backend/static/js/canvas.js's renderTadmChart.
// New here: pre-filtering by onlyFlagged/hiddenCurveIds before axis-fitting,
// error/flagged-specific stroke styling, and a clickable legend that toggles
// hiddenCurveIds instead of just labeling.
function renderSummaryTadmChart(container, curves, { onlyFlagged = false, hiddenCurveIds = new Set(), onToggleCurve = null } = {}) {
  container.innerHTML = "";
  if (!Array.isArray(curves) || curves.length === 0) return;

  const visibleCurves = curves.filter((c) => {
    if (hiddenCurveIds.has(c.curve_id)) return false;
    if (onlyFlagged && !c.error && !c.curve_flagged) return false;
    return true;
  });

  const colors = _summaryCategoricalColors();
  const chrome = {
    // --bg-card, not --bg-surface-2: the chart canvas sits inside a
    // .summary-tadm-group card (also --bg-card) -- matching it blends the
    // plot into that card instead of reading as a mismatched inset panel.
    surface: _summaryCssVar("--bg-card", "#ffffff"),
    border: _summaryCssVar("--border-muted", "rgba(0,0,0,0.12)"),
    text: _summaryCssVar("--text-muted", "#636363"),
    negative: _summaryCssVar("--color-negative", "#d11313"),
    warning: _summaryCssVar("--trace-warning", "#a15c00"),
  };

  const legend = document.createElement("div");
  legend.className = "tadm-legend";
  curves.forEach((curve, ci) => {
    const isHidden = hiddenCurveIds.has(curve.curve_id);
    const item = document.createElement("div");
    item.className = "tadm-legend-item";
    if (isHidden) item.classList.add("disabled");
    if (curve.error) item.classList.add("error");
    else if (curve.curve_flagged) item.classList.add("flagged");

    const swatch = document.createElement("span");
    swatch.className = "tadm-legend-swatch";
    swatch.style.background = curve.error ? chrome.negative : curve.curve_flagged ? chrome.warning : colors[ci % colors.length];

    const label = document.createElement("span");
    const suffix = curve.error ? " (ERROR)" : curve.curve_flagged ? " (FLAGGED)" : "";
    label.textContent = `Ch ${curve.channel_number ?? ci + 1}${suffix}`;

    item.appendChild(swatch);
    item.appendChild(label);
    if (onToggleCurve) {
      item.addEventListener("click", () => onToggleCurve(curve.curve_id));
    }
    legend.appendChild(item);
  });

  if (visibleCurves.length === 0) {
    const empty = document.createElement("div");
    empty.className = "summary-empty-hint";
    empty.textContent = onlyFlagged ? "No flagged or error curves in this group." : "All curves in this group are hidden.";
    container.appendChild(empty);
    container.appendChild(legend);
    return;
  }

  const PAD = { top: 20, right: 16, bottom: 44, left: 54 };
  const W = 760, H = 320;
  const cw = W - PAD.left - PAD.right;
  const ch = H - PAD.top - PAD.bottom;

  let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
  visibleCurves.forEach((c) => {
    (c.curve_points || []).forEach((p) => {
      if (p.time_ms < xMin) xMin = p.time_ms;
      if (p.time_ms > xMax) xMax = p.time_ms;
      if (p.pressure < yMin) yMin = p.pressure;
      if (p.pressure > yMax) yMax = p.pressure;
    });
  });
  if (!isFinite(xMin) || !isFinite(yMin)) return;

  const xRange = xMax - xMin || 1;
  const yRange = yMax - yMin || 1;
  xMin -= xRange * 0.02; xMax += xRange * 0.02;
  yMin -= yRange * 0.06; yMax += yRange * 0.06;

  const toX = (v) => PAD.left + ((v - xMin) / (xMax - xMin)) * cw;
  const toY = (v) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * ch;

  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  canvas.className = "tadm-canvas";
  const ctx = canvas.getContext("2d");

  function colorFor(curve, ci) {
    if (curve.error) return chrome.negative;
    if (curve.curve_flagged) return chrome.warning;
    return colors[ci % colors.length];
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = chrome.surface;
    ctx.fillRect(0, 0, W, H);

    const TICK_COUNT = 5;
    ctx.strokeStyle = chrome.border;
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 4]);
    for (let i = 0; i <= TICK_COUNT; i++) {
      const y = toY(yMin + ((yMax - yMin) * i) / TICK_COUNT);
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + cw, y); ctx.stroke();
    }
    for (let i = 0; i <= TICK_COUNT; i++) {
      const x = toX(xMin + ((xMax - xMin) * i) / TICK_COUNT);
      ctx.beginPath(); ctx.moveTo(x, PAD.top); ctx.lineTo(x, PAD.top + ch); ctx.stroke();
    }
    ctx.setLineDash([]);

    ctx.strokeStyle = chrome.border;
    ctx.lineWidth = 1;
    ctx.strokeRect(PAD.left, PAD.top, cw, ch);

    ctx.fillStyle = chrome.text;
    ctx.font = '11px "Roboto Flex", system-ui, sans-serif';
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let i = 0; i <= TICK_COUNT; i++) {
      const v = yMin + ((yMax - yMin) * i) / TICK_COUNT;
      ctx.fillText(Math.round(v), PAD.left - 6, toY(v));
    }
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (let i = 0; i <= TICK_COUNT; i++) {
      const v = xMin + ((xMax - xMin) * i) / TICK_COUNT;
      ctx.fillText(Math.round(v), toX(v), PAD.top + ch + 6);
    }

    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillText("Time (ms)", PAD.left + cw / 2, H - 2);
    ctx.save();
    ctx.translate(14, PAD.top + ch / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textBaseline = "top";
    ctx.fillText("Pressure", 0, 0);
    ctx.restore();

    visibleCurves.forEach((curve, ci) => {
      const pts = curve.curve_points || [];
      if (pts.length < 2) return;
      ctx.strokeStyle = colorFor(curve, ci);
      ctx.lineWidth = curve.error ? 3 : 2;
      ctx.lineJoin = "round";
      ctx.setLineDash(curve.curve_flagged && !curve.error ? [6, 3] : []);
      ctx.beginPath();
      ctx.moveTo(toX(pts[0].time_ms), toY(pts[0].pressure));
      for (let i = 1; i < pts.length; i++) ctx.lineTo(toX(pts[i].time_ms), toY(pts[i].pressure));
      ctx.stroke();
      ctx.setLineDash([]);
    });
  }
  draw();

  const tooltip = document.createElement("div");
  tooltip.className = "tadm-tooltip";

  const wrap = document.createElement("div");
  wrap.className = "tadm-chart-wrap";
  wrap.appendChild(canvas);
  wrap.appendChild(tooltip);

  canvas.addEventListener("mousemove", (evt) => {
    const rect = canvas.getBoundingClientRect();
    const scaleX = W / rect.width;
    const scaleY = H / rect.height;
    const mx = (evt.clientX - rect.left) * scaleX;
    const my = (evt.clientY - rect.top) * scaleY;

    if (mx < PAD.left || mx > PAD.left + cw || my < PAD.top || my > PAD.top + ch) {
      tooltip.style.display = "none";
      return;
    }

    let bestDist = Infinity, bestPt = null, bestCurve = null, bestCi = -1;
    visibleCurves.forEach((curve, ci) => {
      (curve.curve_points || []).forEach((p) => {
        const dx = toX(p.time_ms) - mx, dy = toY(p.pressure) - my;
        const d = dx * dx + dy * dy;
        if (d < bestDist) { bestDist = d; bestPt = p; bestCurve = curve; bestCi = ci; }
      });
    });
    if (!bestPt || bestDist > 40 * 40) { tooltip.style.display = "none"; return; }

    const color = colorFor(bestCurve, bestCi);
    const suffix = bestCurve.error ? " ERROR" : bestCurve.curve_flagged ? " FLAGGED" : "";
    tooltip.textContent = "";
    const chLabel = document.createElement("span");
    chLabel.style.color = color;
    chLabel.style.fontWeight = "600";
    chLabel.textContent = `Ch ${bestCurve.channel_number ?? bestCi + 1}${suffix}`;
    const timeLabel = document.createElement("span");
    timeLabel.style.marginLeft = "8px";
    timeLabel.textContent = `Time: ${bestPt.time_ms} ms`;
    const pressureLabel = document.createElement("span");
    pressureLabel.style.marginLeft = "8px";
    pressureLabel.textContent = `Pressure: ${bestPt.pressure}`;
    tooltip.appendChild(chLabel);
    tooltip.appendChild(timeLabel);
    tooltip.appendChild(pressureLabel);

    const tipW = 240, tipH = 28;
    let tx = mx / scaleX + 12;
    let ty = my / scaleY - tipH - 8;
    if (tx + tipW > rect.width) tx = mx / scaleX - tipW - 8;
    if (ty < 0) ty = my / scaleY + 8;
    tooltip.style.left = `${tx}px`;
    tooltip.style.top = `${ty}px`;
    tooltip.style.display = "block";
  });
  canvas.addEventListener("mouseleave", () => { tooltip.style.display = "none"; });

  container.appendChild(wrap);
  container.appendChild(legend);
}

// items: [{label, value}, ...], pre-sorted descending by value (see
// run_summary.py) -- rendering just assigns colors in that fixed order,
// never re-sorted here, so a color always tracks the same item. formatLabel
// (item, pct) => string builds both the hover tooltip and the legend text,
// so callers control units ("3 tips" vs "800 µL") without duplicating the
// chart itself. Shared by Tips/Plates/Lids Used by Type and Reservoir Volume
// Consumed on the Summary tab.
function renderCountPieChart(container, items, formatLabel) {
  container.innerHTML = "";
  const total = items.reduce((sum, it) => sum + it.value, 0);
  if (total === 0) return;

  const colors = _summaryCategoricalColors();
  const cardBg = _summaryCssVar("--bg-card", "#ffffff");
  const size = 160;
  const cx = size / 2, cy = size / 2, r = size / 2 - 2;

  const wrap = document.createElement("div");
  wrap.className = "summary-pie-wrap";

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
  svg.setAttribute("class", "summary-pie-chart");

  let angle = -Math.PI / 2; // 12 o'clock start
  items.forEach((it, i) => {
    const color = colors[i % colors.length];
    const fraction = it.value / total;
    const pct = Math.round(fraction * 100);
    const titleText = formatLabel(it, pct);

    let shape;
    if (items.length === 1) {
      // Arc math degenerates for a single full-circle slice.
      shape = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      shape.setAttribute("cx", cx);
      shape.setAttribute("cy", cy);
      shape.setAttribute("r", r);
    } else {
      const sliceAngle = fraction * Math.PI * 2;
      const x1 = cx + r * Math.cos(angle);
      const y1 = cy + r * Math.sin(angle);
      angle += sliceAngle;
      const x2 = cx + r * Math.cos(angle);
      const y2 = cy + r * Math.sin(angle);
      const largeArc = sliceAngle > Math.PI ? 1 : 0;
      shape = document.createElementNS("http://www.w3.org/2000/svg", "path");
      shape.setAttribute("d", `M ${cx},${cy} L ${x1},${y1} A ${r},${r} 0 ${largeArc},1 ${x2},${y2} Z`);
    }
    shape.setAttribute("fill", color);
    shape.setAttribute("stroke", cardBg);
    shape.setAttribute("stroke-width", "2");

    const titleEl = document.createElementNS("http://www.w3.org/2000/svg", "title");
    titleEl.textContent = titleText;
    shape.appendChild(titleEl);

    svg.appendChild(shape);
  });
  wrap.appendChild(svg);

  const legend = document.createElement("div");
  legend.className = "summary-pie-legend";
  items.forEach((it, i) => {
    const pct = Math.round((it.value / total) * 100);
    const item = document.createElement("div");
    item.className = "summary-pie-legend-item";
    const swatch = document.createElement("span");
    swatch.className = "summary-pie-legend-swatch";
    swatch.style.background = colors[i % colors.length];
    const label = document.createElement("span");
    label.textContent = formatLabel(it, pct);
    item.appendChild(swatch);
    item.appendChild(label);
    legend.appendChild(item);
  });
  wrap.appendChild(legend);

  container.appendChild(wrap);
}

class SummaryView {
  constructor(containerEl) {
    this.containerEl = containerEl;
    this.onlyFlagged = false;
    this._hiddenCurvesByGroup = new Map();
    this._renderHint("Run a script to see its summary here once it finishes.");
  }

  clear() {
    this.onlyFlagged = false;
    this._hiddenCurvesByGroup = new Map();
    this._renderHint("Run a script to see its summary here once it finishes.");
  }

  // A summarize_run payload the caller already has (the Log Viewer).
  show(summary) {
    this.onlyFlagged = false;
    this._hiddenCurvesByGroup = new Map();
    this._render(summary);
  }

  showHint(text) {
    this._renderHint(text);
  }

  // logFile: string -> fetch + render; null -> the SDK ran but wrote no log;
  // undefined -> the run never even got that far (see app.js's run_state handler).
  async setRun(logFile) {
    if (logFile === undefined) {
      this._renderHint("This run never produced a log file.");
      return;
    }
    if (logFile === null) {
      this._renderHint("No log was captured for this run.");
      return;
    }
    this.onlyFlagged = false;
    this._hiddenCurvesByGroup = new Map();
    this._renderHint("Loading summary…");
    let summary;
    try {
      const resp = await fetch(`/api/logs/${encodeURIComponent(logFile)}/summary`);
      if (!resp.ok) {
        this._renderHint(`Could not load run summary (HTTP ${resp.status}).`);
        return;
      }
      summary = await resp.json();
    } catch (err) {
      this._renderHint(`Could not load run summary: ${err}`);
      return;
    }
    this._render(summary);
  }

  _renderHint(text) {
    this.containerEl.innerHTML = "";
    const hint = document.createElement("div");
    hint.className = "summary-empty-hint";
    hint.textContent = text;
    this.containerEl.appendChild(hint);
  }

  _render(summary) {
    this.containerEl.innerHTML = "";
    this.containerEl.appendChild(this._buildStatTiles(summary));
    if (summary.error_count > 0) {
      this.containerEl.appendChild(this._buildErrorsSection(summary));
    }
    if (summary.tips_by_type && summary.tips_by_type.length > 0) {
      this.containerEl.appendChild(this._buildTipsSection(summary));
    }
    const labwareSection = this._buildLabwareSection(summary);
    if (labwareSection) this.containerEl.appendChild(labwareSection);
    this.containerEl.appendChild(this._buildTadmSection(summary));
  }

  _buildStatTiles(summary) {
    const row = document.createElement("div");
    row.className = "summary-stat-row";

    const resultLabel = { success: "Success", error: "Error", unknown: "Unknown" }[summary.result] || "Unknown";
    const resultClass = { success: "completed", error: "error", unknown: "idle" }[summary.result] || "idle";

    const tiles = [
      { label: "Result", pill: { text: resultLabel, cls: resultClass } },
      { label: "Total Run Time", value: _formatDuration(summary.duration_seconds) },
      { label: "Mode", value: summary.simulate === null || summary.simulate === undefined ? "—" : (summary.simulate ? "Simulate" : "Live") },
      { label: "Total Errors", value: String(summary.error_count) },
      {
        label: "Total Tips Used",
        value: String(summary.tips_used),
        sub: `${summary.tip_pickup_calls} pickup${summary.tip_pickup_calls === 1 ? "" : "s"}`,
      },
      {
        label: "TADM Curves",
        value: String(summary.tadm_totals.curve_count),
        sub: summary.tadm_totals.curve_count
          ? `${summary.tadm_totals.flagged_count} flagged · ${summary.tadm_totals.error_count} error${summary.tadm_totals.error_count === 1 ? "" : "s"}`
          : "",
      },
    ];

    tiles.forEach((t) => row.appendChild(this._buildStatTile(t)));
    return row;
  }

  _buildStatTile({ label, value, sub, pill }) {
    const tile = document.createElement("div");
    tile.className = "summary-stat-tile";

    const labelEl = document.createElement("div");
    labelEl.className = "summary-stat-label";
    labelEl.textContent = label;
    tile.appendChild(labelEl);

    const valueEl = document.createElement("div");
    valueEl.className = "summary-stat-value";
    if (pill) {
      const badge = document.createElement("span");
      badge.className = `status-pill status-${pill.cls}`;
      badge.textContent = pill.text;
      valueEl.appendChild(badge);
    } else {
      valueEl.textContent = value;
    }
    tile.appendChild(valueEl);

    if (sub) {
      const subEl = document.createElement("div");
      subEl.className = "summary-stat-sub";
      subEl.textContent = sub;
      tile.appendChild(subEl);
    }
    return tile;
  }

  // Combines two distinct error signals into one table: a command_response
  // that came back non-success (no "recovery" concept -- it just failed),
  // and a VENUS-level instrument_error/device_error_handled pair (which
  // does carry a recovery action, since a recovered error can still leave
  // the retried command reporting success). See run_summary.py for why
  // these aren't deduplicated against each other.
  _buildErrorsSection(summary) {
    const section = document.createElement("div");
    section.className = "summary-section";

    const title = document.createElement("div");
    title.className = "summary-section-title";
    title.textContent = `Errors (${summary.error_count})`;
    section.appendChild(title);

    const table = document.createElement("div");
    table.className = "summary-error-table";

    const header = document.createElement("div");
    header.className = "summary-error-row summary-error-header";
    ["Source", "Step", "Detail", "Recovery Action"].forEach((label) => {
      const cell = document.createElement("span");
      cell.textContent = label;
      header.appendChild(cell);
    });
    table.appendChild(header);

    (summary.failed_steps || []).forEach((step) => {
      const code = step.return_code === null || step.return_code === undefined ? "?" : step.return_code;
      const header = `${step.return_status || step.status || "Error"} (code ${code})${step.category ? ` · ${step.category}` : ""}`;
      table.appendChild(this._buildErrorRow({
        source: "Command",
        step: step.action_name || "(unknown action)",
        line: step.line ?? null,
        // returnParameters.message carries VENUS's actual error description
        // (e.g. "Liquid class not found (...)") -- without it this row only
        // ever said "Error (code 0) · Instrument", which is true of every
        // non-hardware failure and tells the operator nothing about *why*.
        detail: step.message ? `${header} — ${step.message}` : header,
        recovery: null,
      }));
    });

    // One row per distinct message within an error event -- run_summary.py
    // already groups channels that hit the exact same message (the common
    // case: VENUS raises one message template per failure kind) so this loop
    // is a direct render, not a fan-out or a re-grouping.
    (summary.instrument_errors || []).forEach((err) => {
      const channels = err.channels || [];
      const label = channels.length === 1 ? `Channel ${channels[0]}` : channels.length > 1 ? `Channels ${channels.join(", ")}` : "";
      const detail = label ? `${err.detail} (${label})` : err.detail;
      table.appendChild(this._buildErrorRow({
        source: "Instrument",
        step: err.step || "(unknown error)",
        detail: detail || "",
        recovery: err.recovery_action || null,
      }));
    });

    section.appendChild(table);
    return section;
  }

  _buildErrorRow({ source, step, line, detail, recovery }) {
    const row = document.createElement("div");
    row.className = "summary-error-row";

    const sourceEl = document.createElement("span");
    sourceEl.textContent = source;
    row.appendChild(sourceEl);

    const stepEl = document.createElement("span");
    stepEl.className = "summary-error-name";
    stepEl.textContent = step;
    if (line !== null && line !== undefined) {
      const lineEl = document.createElement("span");
      lineEl.className = "summary-error-line";
      lineEl.textContent = ` (line ${line})`;
      stepEl.appendChild(lineEl);
    }
    row.appendChild(stepEl);

    const detailEl = document.createElement("span");
    detailEl.className = "summary-error-detail";
    detailEl.textContent = detail || "";
    row.appendChild(detailEl);

    const recoveryEl = document.createElement("span");
    if (recovery) {
      recoveryEl.className = "summary-error-recovery";
      recoveryEl.textContent = recovery;
    } else {
      recoveryEl.className = "summary-error-recovery summary-error-recovery-none";
      recoveryEl.textContent = "—";
    }
    row.appendChild(recoveryEl);

    return row;
  }

  _buildTipsSection(summary) {
    const section = document.createElement("div");
    section.className = "summary-section";

    const title = document.createElement("div");
    title.className = "summary-section-title";
    title.textContent = "Tips Used by Type";
    section.appendChild(title);

    const groups = document.createElement("div");
    groups.className = "summary-pie-card-row";

    // Split into one card per add-tip-* action that registered the pool --
    // Tip Rack (add_tip_rack, the default/common case), Tip Box
    // (add_tip_box), Nested Tip Rack (add_ntr) -- see run_summary.py's
    // TIP_KIND_ORDER, which is also the order tips_by_type already arrives
    // in, so grouping here just has to preserve that order, not re-sort it.
    const byKind = new Map(); // kind -> { label: kind_label, items: [{label, value}] }
    summary.tips_by_type.forEach((t) => {
      if (!byKind.has(t.kind)) byKind.set(t.kind, { label: t.kind_label, items: [] });
      byKind.get(t.kind).items.push({ label: t.tip_type, value: t.count });
    });
    byKind.forEach(({ label, items }) => {
      groups.appendChild(this._buildLabwareGroup(
        label,
        items,
        (it, pct) => `${it.label} — ${it.value} tip${it.value === 1 ? "" : "s"} (${pct}%)`,
      ));
    });

    section.appendChild(groups);
    return section;
  }

  // Plates/lids by type mirror Tips Used by Type (a pie of counts); Volume
  // Consumed from Reservoirs gets its own pie keyed by µL instead of a count.
  // Each sub-block only appears when it has data -- a run that never adds a
  // plate or lid (e.g. tube-rack-only) shouldn't show an empty "Plates by
  // Type"/"Lids by Type" heading, and the whole section is skipped when none
  // of the three have anything to show.
  _buildLabwareSection(summary) {
    const hasPlates = summary.plates_by_type && summary.plates_by_type.length > 0;
    const hasLids = summary.lids_by_type && summary.lids_by_type.length > 0;
    const hasReservoirs = summary.reservoir_volumes && summary.reservoir_volumes.length > 0;
    if (!hasPlates && !hasLids && !hasReservoirs) return null;

    const section = document.createElement("div");
    section.className = "summary-section";

    const title = document.createElement("div");
    title.className = "summary-section-title";
    title.textContent = "Labware Used";
    section.appendChild(title);

    const groups = document.createElement("div");
    groups.className = "summary-pie-card-row";

    if (hasPlates) {
      groups.appendChild(this._buildLabwareGroup(
        "Plates by Type",
        summary.plates_by_type.map((p) => ({ label: p.labware_definition, value: p.count })),
        (it, pct) => `${it.label} — ${it.value} plate${it.value === 1 ? "" : "s"} (${pct}%)`,
      ));
    }
    if (hasLids) {
      groups.appendChild(this._buildLabwareGroup(
        "Lids by Type",
        summary.lids_by_type.map((l) => ({ label: l.labware_definition, value: l.count })),
        (it, pct) => `${it.label} — ${it.value} lid${it.value === 1 ? "" : "s"} (${pct}%)`,
      ));
    }
    if (hasReservoirs) {
      groups.appendChild(this._buildLabwareGroup(
        "Volume Consumed from Reservoirs",
        summary.reservoir_volumes.map((r) => ({ label: r.labware, value: r.volume_ul })),
        (it, pct) => `${it.label} — ${_formatReservoirVolumeUl(it.value)} (${pct}%)`,
      ));
    }

    section.appendChild(groups);
    return section;
  }

  _buildLabwareGroup(title, items, formatLabel) {
    const wrap = document.createElement("div");
    wrap.className = "summary-pie-card";

    const heading = document.createElement("div");
    heading.className = "summary-pie-card-title";
    heading.textContent = title;
    wrap.appendChild(heading);

    const host = document.createElement("div");
    wrap.appendChild(host);
    renderCountPieChart(host, items, formatLabel);

    return wrap;
  }

  _buildTadmSection(summary) {
    const section = document.createElement("div");
    section.className = "summary-section";

    const title = document.createElement("div");
    title.className = "summary-section-title";
    title.textContent = "TADM Pressure Curves";
    section.appendChild(title);

    const groups = summary.tadm_groups || [];
    if (groups.length === 0) {
      const hint = document.createElement("div");
      hint.className = "summary-empty-hint";
      hint.textContent = "No TADM data was collected for this run.";
      section.appendChild(hint);
      return section;
    }

    const filterRow = document.createElement("div");
    filterRow.className = "summary-tadm-filter-row";
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "filter-chip";
    chip.textContent = "Show only flagged/error bands";
    chip.classList.toggle("active", this.onlyFlagged);
    chip.addEventListener("click", () => {
      this.onlyFlagged = !this.onlyFlagged;
      chip.classList.toggle("active", this.onlyFlagged);
      groups.forEach((group, i) => this._renderGroup(groupEls[i], group));
    });
    filterRow.appendChild(chip);
    section.appendChild(filterRow);

    // One block per liquid class (sorted by name), its cards ordered aspirate
    // before dispense, then by volume. groupEls stays index-aligned with
    // `groups` for the flagged-only chip above.
    const groupEls = new Array(groups.length);
    const byClass = new Map();
    groups.forEach((group, i) => {
      const lc = group.liquid_class_name || "(unknown liquid class)";
      if (!byClass.has(lc)) byClass.set(lc, []);
      byClass.get(lc).push(i);
    });
    const stepRank = (g) => ((g.step_type_name || "").toLowerCase().startsWith("aspirat") ? 0 : 1);
    [...byClass.keys()].sort().forEach((lc) => {
      const lcEl = document.createElement("div");
      lcEl.className = "summary-tadm-lc-section";
      const lcTitle = document.createElement("div");
      lcTitle.className = "summary-tadm-lc-title";
      const indexes = byClass.get(lc);
      const curveCount = indexes.reduce((n, i) => n + groups[i].curves.length, 0);
      lcTitle.textContent = `${lc} · ${curveCount} curve${curveCount === 1 ? "" : "s"}`;
      lcEl.appendChild(lcTitle);
      const groupsContainer = document.createElement("div");
      groupsContainer.className = "summary-tadm-groups";
      indexes
        .sort((a, b) => stepRank(groups[a]) - stepRank(groups[b]) || (groups[a].volume || 0) - (groups[b].volume || 0))
        .forEach((i) => {
          const groupEl = document.createElement("div");
          groupEl.className = "summary-tadm-group";
          groupsContainer.appendChild(groupEl);
          this._renderGroup(groupEl, groups[i]);
          groupEls[i] = groupEl;
        });
      lcEl.appendChild(groupsContainer);
      section.appendChild(lcEl);
    });

    return section;
  }

  _renderGroup(groupEl, group) {
    groupEl.innerHTML = "";

    const flaggedCount = group.curves.filter((c) => c.curve_flagged).length;
    const errorCount = group.curves.filter((c) => c.error).length;

    const header = document.createElement("div");
    header.className = "summary-tadm-group-header";
    const titleEl = document.createElement("span");
    titleEl.className = "summary-tadm-group-title";
    // The liquid class is the heading of the block this card sits in.
    titleEl.textContent = `${group.step_type_name || "?"} · ${group.volume} µL`;
    header.appendChild(titleEl);
    const countsEl = document.createElement("span");
    countsEl.className = "summary-tadm-group-counts";
    countsEl.textContent =
      `${group.curves.length} curve${group.curves.length === 1 ? "" : "s"}` +
      (flaggedCount || errorCount ? ` · ${flaggedCount} flagged · ${errorCount} error${errorCount === 1 ? "" : "s"}` : "");
    header.appendChild(countsEl);
    groupEl.appendChild(header);

    if (!this._hiddenCurvesByGroup.has(group)) this._hiddenCurvesByGroup.set(group, new Set());
    const hiddenCurveIds = this._hiddenCurvesByGroup.get(group);

    const chartHost = document.createElement("div");
    groupEl.appendChild(chartHost);
    renderSummaryTadmChart(chartHost, group.curves, {
      onlyFlagged: this.onlyFlagged,
      hiddenCurveIds,
      onToggleCurve: (curveId) => {
        if (hiddenCurveIds.has(curveId)) hiddenCurveIds.delete(curveId);
        else hiddenCurveIds.add(curveId);
        this._renderGroup(groupEl, group);
      },
    });
  }
}
