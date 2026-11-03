/* Human-readable, filterable, searchable event trace for a script run -- the hub's analog of
   Script Manager's trace-view.js, adapted to the spoke's structured JSON events (get_run_events)
   instead of raw text lines, so classification is by each event's own "type" field rather than
   regex-guessing at text shape. */

const TRACE_CATEGORIES = {
  lifecycle: { label: "Lifecycle", color: "var(--color-primary)" },
  output: { label: "Script output", color: "var(--text-base)" },
  tracking: { label: "Tracking", color: "var(--color-secondary-3)" },
  prompt: { label: "Prompts / errors", color: "var(--color-negative)" },
  log: { label: "Log", color: "var(--text-muted)" },
};

const TRACE_TYPE_CATEGORY = {
  run_started: "lifecycle", started: "lifecycle", sim_mode: "lifecycle", state: "lifecycle",
  script_exit: "lifecycle", run_finished: "lifecycle", pause_requested: "lifecycle",
  resume_requested: "lifecycle", abort_requested: "lifecycle", hard_kill: "lifecycle",
  run_timeout: "lifecycle", prompt_timeout: "lifecycle", acknowledged: "lifecycle",
  stdout: "output", stderr: "output", line: "output",
  client: "tracking", labware: "tracking", tips: "tracking", aspirate: "tracking",
  dispense: "tracking", reload: "tracking", consumable_warning: "tracking", tracking_error: "tracking",
  summary_error: "tracking", ledger_error: "tracking",
  prompt: "prompt", operator_error_deferred: "prompt", prompt_resolved: "prompt",
  log: "log",
};

function fmtTime(ts) {
  // get_run_events' "time" field is an ISO 8601 string (see manager.RunEvent.to_dict), not a
  // unix timestamp -- the Date constructor parses that natively.
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

function fmtChannelErrors(rows) {
  return (rows || [])
    .map(r => (r.channels && r.channels.length ? "ch" + r.channels.join(",") + ": " : "") + r.message)
    .join(" | ");
}

const TRACE_FORMATTERS = {
  run_started: e => `Run started: ${e.script} (simulate=${e.simulate}, sha256 ${(e.sha256 || "").slice(0, 8)})`,
  started: e => `Child process started: pid ${e.pid}, python ${e.python}`,
  sim_mode: e => e.error
    ? `Could not sync VENUS's system-wide simulation mode: ${e.error}`
    : e.changed
      ? `VENUS system-wide simulation mode: ${e.previous} -> ${e.current}`
      : `VENUS system-wide simulation mode already ${e.current}`,
  state: e => `State: ${e.state}`,
  script_exit: e => `Script exited: ${e.status} (exit code ${e.exit_code})${e.error ? " -- " + e.error.message : ""}`,
  run_finished: e => `Run finished: ${e.status} (exit code ${e.exit_code})${e.error ? " -- " + e.error.message : ""}`,
  pause_requested: () => "Pause requested.",
  resume_requested: () => "Resume requested.",
  abort_requested: () => "Abort requested.",
  hard_kill: e => `Hard kill -- ${e.note || "the script did not stop in time."}`,
  run_timeout: e => `Exceeded max_runtime_s=${e.max_runtime_s}; stopping.`,
  prompt_timeout: e => `Prompt ${e.prompt_id} unanswered after ${e.after_s}s.`,
  acknowledged: () => "Run acknowledged.",
  stdout: e => e.text,
  stderr: e => e.text,
  line: e => `Executing line ${e.line}`,
  client: e => `${e.client} client created (simulate=${e.simulate})`,
  labware: e => `${e.method} ${e.labware_name || ""}${e.carrier_id ? " on " + e.carrier_id + (e.site ? "@" + e.site : "") : ""}${e.tip_pool ? " (tip pool " + e.tip_pool + ")" : ""}`,
  tips: e => `Tip pool ${e.tip_pool}: ${e.remaining ?? "?"}${e.capacity ? "/" + e.capacity : ""} remaining (picked up ${e.picked_up})`,
  aspirate: e => {
    const readings = e.readings || [];
    const shown = readings.slice(0, 4).map(r =>
      `${r.labware}@${r.well} ch${r.channel}: ${formatVolumeUl(r.aspirated_ul)}` +
      (r.percent_full != null ? ` (${Math.round(r.percent_full * 100)}% full)` : r.liquid_volume_ul != null ? ` (${formatVolumeUl(r.liquid_volume_ul)} left)` : "")
    );
    const more = readings.length > 4 ? ` (+${readings.length - 4} more)` : "";
    return `Aspirate: ${shown.join("; ")}${more}`;
  },
  dispense: e => {
    const readings = e.readings || [];
    const shown = readings.slice(0, 4).map(r =>
      `${r.labware}${r.well ? "@" + r.well : ""} ch${r.channel}: ${formatVolumeUl(r.dispensed_ul)}`
    );
    const more = readings.length > 4 ? ` (+${readings.length - 4} more)` : "";
    return `Dispense: ${shown.join("; ")}${more}`;
  },
  reload: e => `Reload: ${e.kind} ${e.item_key} via ${e.command}`,
  consumable_warning: e => `Low ${e.kind} warning: ${e.item_key} at ${e.kind === "tip" ? e.level : Math.round(e.level * 100) + "%"} (threshold ${e.kind === "tip" ? e.threshold : Math.round(e.threshold * 100) + "%"})`,
  tracking_error: e => `Tracking error in ${e.method}: ${e.error}`,
  summary_error: e => `Could not compute run summary: ${e.error}`,
  ledger_error: e => `Could not record consumables: ${e.error}`,
  prompt: e => `Prompt (${e.kind}): ${e.title}${e.channel_errors && e.channel_errors.length ? " -- " + fmtChannelErrors(e.channel_errors) : ""}`,
  operator_error_deferred: e => `Deferred to VENUS's local dialog: ${e.title}${e.code ? " (" + e.code + ")" : ""}${e.channel_errors && e.channel_errors.length ? " -- " + fmtChannelErrors(e.channel_errors) : ""}`,
  prompt_resolved: e => `Prompt ${e.prompt_id} resolved: ${e.action}${e.operator ? " by " + e.operator : ""}`,
  log: e => `[${e.level || "INFO"}]${e.source ? " (" + e.source + ")" : ""} ${e.message}`,
};

function formatTraceEntry(event) {
  const category = TRACE_TYPE_CATEGORY[event.type] || "log";
  const formatter = TRACE_FORMATTERS[event.type];
  let text;
  try {
    text = formatter ? formatter(event) : `${event.type}: ` + Object.entries(event)
      .filter(([k]) => !["seq", "time", "type"].includes(k))
      .map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ");
  } catch (err) {
    text = `${event.type}: (could not format -- ${JSON.stringify(event)})`;
  }
  return { seq: event.seq, ts: event.time, category, text, raw: event };
}

const TRACE_MAX_ENTRIES = 5000;

const TRACE_WRAP_KEY = "hub.trace.wordWrap";
const TRACE_AUTOSCROLL_KEY = "hub.trace.autoScroll";

class TraceView {
  // wrapEl / autoScrollEl are the footer's checkbox switches (both optional). Their state is
  // remembered across pages and shared by every TraceView, like Script Manager's terminal.
  constructor(containerEl, chipsEl, searchEl, storageKey, wrapEl, autoScrollEl) {
    this.containerEl = containerEl;
    this.chipsEl = chipsEl;
    this.searchEl = searchEl;
    this.wrapEl = wrapEl || null;
    this.autoScrollEl = autoScrollEl || null;
    this.storageKey = storageKey || "hub.trace.hiddenCategories";
    this.entries = [];
    this.hidden = this._loadHidden();
    if (chipsEl) this._renderChips();
    if (searchEl) searchEl.addEventListener("input", () => this._render());
    if (this.wrapEl) {
      this.wrapEl.checked = this._loadBool(TRACE_WRAP_KEY, true);
      this._applyWrap();
      this.wrapEl.addEventListener("change", () => {
        this._saveBool(TRACE_WRAP_KEY, this.wrapEl.checked);
        this._applyWrap();
      });
    }
    if (this.autoScrollEl) {
      this.autoScrollEl.checked = this._loadBool(TRACE_AUTOSCROLL_KEY, true);
      this.autoScrollEl.addEventListener("change", () => {
        this._saveBool(TRACE_AUTOSCROLL_KEY, this.autoScrollEl.checked);
        if (this.autoScrollEl.checked) this._scrollToBottom();
      });
    }
  }

  _loadBool(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : raw === "true";
    } catch (e) {
      return fallback;
    }
  }

  _saveBool(key, value) {
    try { localStorage.setItem(key, String(value)); } catch (e) { /* unavailable */ }
  }

  _applyWrap() {
    if (this.containerEl) this.containerEl.classList.toggle("no-wrap", !this.wrapEl.checked);
  }

  _scrollToBottom() {
    if (this.containerEl) this.containerEl.scrollTop = this.containerEl.scrollHeight;
  }

  _loadHidden() {
    try {
      const raw = localStorage.getItem(this.storageKey);
      return raw ? new Set(JSON.parse(raw)) : new Set();
    } catch (e) {
      return new Set();
    }
  }

  _saveHidden() {
    try { localStorage.setItem(this.storageKey, JSON.stringify([...this.hidden])); } catch (e) { /* unavailable */ }
  }

  _renderChips() {
    this.chipsEl.innerHTML = "";
    for (const [key, meta] of Object.entries(TRACE_CATEGORIES)) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "trace-chip" + (this.hidden.has(key) ? " off" : "");
      chip.style.setProperty("--chip-color", meta.color);
      chip.textContent = meta.label;
      chip.addEventListener("click", () => {
        if (this.hidden.has(key)) this.hidden.delete(key); else this.hidden.add(key);
        this._saveHidden();
        chip.classList.toggle("off");
        this._render();
      });
      this.chipsEl.append(chip);
    }
  }

  setEntries(events) {
    this.entries = (events || []).map(formatTraceEntry);
    this._render();
  }

  append(events) {
    if (!events || !events.length) return;
    this.entries.push(...events.map(formatTraceEntry));
    if (this.entries.length > TRACE_MAX_ENTRIES) this.entries.splice(0, this.entries.length - TRACE_MAX_ENTRIES);
    this._render();
  }

  clear() {
    this.entries = [];
    this._render();
  }

  _render() {
    if (!this.containerEl) return;
    const search = this.searchEl ? this.searchEl.value.trim().toLowerCase() : "";
    const visible = this.entries.filter(e => {
      if (this.hidden.has(e.category)) return false;
      if (search && !e.text.toLowerCase().includes(search)) return false;
      return true;
    });
    if (!visible.length) {
      this.containerEl.innerHTML = '<div class="empty-row">Nothing to show' + (search ? " for that search" : "") + ".</div>";
      return;
    }
    const previousTop = this.containerEl.scrollTop;
    this.containerEl.innerHTML = visible.map(e =>
      `<div class="trace-line trace-cat-${e.category}"><span class="trace-time">${esc(fmtTime(e.ts))}</span>${esc(e.text)}</div>`
    ).join("");
    // Auto-scroll on: follow the newest line. Off: stay exactly where the reader was.
    if (this.autoScrollEl && this.autoScrollEl.checked) this._scrollToBottom();
    else this.containerEl.scrollTop = previousTop;
  }
}
