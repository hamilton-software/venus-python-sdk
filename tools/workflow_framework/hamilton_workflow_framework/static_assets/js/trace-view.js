// Terminal/trace pane for Hamilton Script Manager.
//
// Every stdout/stderr line the running script produces arrives here as one
// "log" entry, regardless of what actually produced it: a bare print() in
// the script, the SDK's own `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
// logging handler (forced to DEBUG for every run -- see script_runner.py),
// or the separate VenusTrace stream (its own handler, format is just
// "%(message)s"). The backend's "level" field only reflects which file
// descriptor a line arrived on (stdout -> INFO, stderr -> ERROR) -- it is NOT
// a real severity signal, because the SDK's `logging.StreamHandler()` calls
// (venus_client, _signalr_listener, VenusTrace) all default to stderr, so
// practically everything the SDK logs -- comms, debug, traces, plain info --
// shows up tagged "ERROR" even though none of it is an actual error. Only a
// bare script print() lands on real stdout. So "level" is ignored entirely
// here; every line is classified purely by its own text.

const CATEGORIES = [
  { id: "terminal", label: "Terminal" },
  { id: "venus", label: "VENUS" },
  { id: "communication", label: "Communication" },
  { id: "comtrace", label: "COM Trace" },
  { id: "debug", label: "Debug" },
  { id: "info", label: "Info" },
  { id: "error", label: "Error" },
];
const CATEGORY_LABEL = Object.fromEntries(CATEGORIES.map((c) => [c.id, c.label]));
// COM Trace is the raw firmware < / > exchange scraped from VENUS's .trc --
// high volume, so it starts hidden (like Debug); click the chip to reveal it.
const DEFAULT_HIDDEN_CATEGORIES = new Set(["comtrace", "debug"]);

const HIDDEN_CATEGORIES_KEY = "hamiltonScriptManager.trace.hiddenCategories";
const WORD_WRAP_KEY = "hamiltonScriptManager.trace.wordWrap";
const AUTO_SCROLL_KEY = "hamiltonScriptManager.trace.autoScroll";

const TRACEBACK_START_RE = /^Traceback \(most recent call last\):/;
const EXCEPTION_LINE_RE = /^[\w.]+(Error|Exception)(:|$)/;

// Splits a traceback frame line ("  File "x.py", line 12, in foo") and a
// terminal exception line ("ValueError: bad thing") into the pieces that get
// their own highlight color -- these two shapes carry no logger prefix, so
// they must be recognized structurally rather than by a `[LEVEL]`/`name:` tag.
const FILE_FRAME_RE = /^(\s*)File "([^"]*)", line (\d+), in (.*)$/;
const EXCEPTION_SPLIT_RE = /^([\w.]+(?:Error|Exception))(:\s*)?(.*)$/;

// One alternation used as a tokenizer: for each match, exactly one named
// group is populated, and that name picks the CSS class. Order only matters
// where two alternatives could start at the same position -- logger/key both
// require a specific trailing character (":" vs "="), so they never compete
// for the same span of text. The VenusTrace-specific patterns (id/action/
// star-step/channel) go first since they're multi-word shapes that the
// single-token patterns below (key, number, ...) would otherwise fragment.
const INLINE_TOKEN_RE = new RegExp(
  [
    String.raw`(?<time>\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[,.]\d{3}\b)`,
    String.raw`(?<level>\[(?:DEBUG|INFO|WARNING|ERROR|CRITICAL)\])`,
    String.raw`(?<venus>\bVenusTrace:)`,
    // "ID:  2b184780-...", "Action:  channels.1mL.tipEject" -- label plus
    // the whole value token, kept as one match so the value isn't also
    // picked apart by the generic number/key patterns further down.
    String.raw`(?<idLabel>\bID:)\s+(?<idValue>\S+)`,
    String.raw`(?<actionLabel>\bAction:)\s+(?<actionValue>\S+)`,
    // "Microlab STAR : 1000ul Channel Dispense (Single Step) - start;" --
    // just the step name between the "Microlab STAR :" label and " - ".
    String.raw`Microlab STAR\s*:\s*(?<starStep>.+?)\s+-\s+`,
    // "> channel 1: bluedye, 1, 0 uL" -- channel number, then labware+well
    // together as one highlight, then volume as another. Matched against
    // already-HTML-escaped text, so ">" here is literally "&gt;".
    String.raw`&gt;\s*(?<chLabel>channel \d+:)\s*(?<chLabware>[^,]+),\s*(?<chWell>[^,]+),\s*(?<chVol>[^,]+?)(?=\s*&gt;|\s*$)`,
    // Other "> CODE: value" firmware-response segments that aren't a channel
    // breakdown, e.g. "> ST: er00/00", "> RU: er00/00ru01000 12250 01400 13375".
    String.raw`&gt;\s*(?<respLabel>[A-Za-z]\w*:)\s*(?<respVal>.+?)(?=\s*&gt;|\s*$)`,
    // "... - progress; Firmware version of main module: 0.0X 2002-05-08" --
    // leave the label before the colon alone and highlight everything after
    // it as one value, instead of only picking out the embedded numbers.
    String.raw`(?<progLabel>progress;\s+[^:]+:)\s*(?<progVal>.+)$`,
    String.raw`(?<logger>\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+:)(?=\s)`,
    String.raw`(?<string>'[^'\\]*(?:\\.[^'\\]*)*'|"[^"\\]*(?:\\.[^"\\]*)*")`,
    String.raw`(?<key>\b[A-Za-z_]\w*)(?==(?!=))`,
    String.raw`(?<bool>\b(?:True|False|None)\b)`,
    String.raw`(?<number>\b\d+(?:\.\d+)?\b)`,
  ].join("|"),
  "g"
);

function escapeHtml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Applies INLINE_TOKEN_RE to text that has already been HTML-escaped.
function inlineHighlight(escapedText) {
  return escapedText.replace(INLINE_TOKEN_RE, (match, ...rest) => {
    const groups = rest[rest.length - 1];
    if (groups.time) return `<span class="tok-time">${match}</span>`;
    if (groups.level) return `<span class="tok-level-${match.slice(1, -1).toLowerCase()}">${match}</span>`;
    if (groups.venus) return `<span class="tok-venus">${match}</span>`;
    if (groups.idValue) {
      return `<span class="tok-field-label">${groups.idLabel}</span> <span class="tok-id-value">${groups.idValue}</span>`;
    }
    if (groups.actionValue) {
      return `<span class="tok-field-label">${groups.actionLabel}</span> <span class="tok-action-value">${groups.actionValue}</span>`;
    }
    if (groups.starStep) {
      return match.replace(groups.starStep, `<span class="tok-star-step">${groups.starStep}</span>`);
    }
    if (groups.chLabel) {
      return (
        `> <span class="tok-channel">${groups.chLabel}</span> ` +
        `<span class="tok-labware-well">${groups.chLabware}, ${groups.chWell}</span>, ` +
        `<span class="tok-volume">${groups.chVol}</span>`
      );
    }
    if (groups.respLabel) {
      return `> <span class="tok-channel">${groups.respLabel}</span> <span class="tok-response-value">${groups.respVal}</span>`;
    }
    if (groups.progLabel) {
      return `${groups.progLabel} <span class="tok-progress-value">${groups.progVal}</span>`;
    }
    if (groups.logger) return `<span class="tok-logger">${match}</span>`;
    if (groups.string) return `<span class="tok-string">${match}</span>`;
    if (groups.key) return `<span class="tok-key">${match}</span>`;
    if (groups.bool) return `<span class="tok-bool">${match}</span>`;
    if (groups.number) return `<span class="tok-number">${match}</span>`;
    return match;
  });
}

// Renders one log line's own text (not the leading [hh:mm:ss] we add) as
// syntax-highlighted HTML. Traceback headers/frames and exception lines have
// no logger prefix to key off, so they're matched by shape first; everything
// else gets run through the generic tokenizer.
function highlightLine(text) {
  if (TRACEBACK_START_RE.test(text)) {
    return `<span class="tok-traceback">${escapeHtml(text)}</span>`;
  }
  const frame = text.match(FILE_FRAME_RE);
  if (frame) {
    const [, indent, path, lineno, func] = frame;
    return (
      escapeHtml(indent) +
      `File "<span class="tok-path">${escapeHtml(path)}</span>", line ` +
      `<span class="tok-lineno">${escapeHtml(lineno)}</span>, in ` +
      `<span class="tok-func">${escapeHtml(func)}</span>`
    );
  }
  if (EXCEPTION_LINE_RE.test(text)) {
    const exc = text.match(EXCEPTION_SPLIT_RE);
    if (exc) {
      const [, cls, sep, rest] = exc;
      return (
        `<span class="tok-exception">${escapeHtml(cls)}</span>${escapeHtml(sep || "")}` +
        (rest ? inlineHighlight(escapeHtml(rest)) : "")
      );
    }
  }
  const comm = text.match(DISPATCHER_MESSAGE_LABEL_RE);
  if (comm) {
    const [, label, rest] = comm;
    return `<span class="tok-comm-label">${escapeHtml(label)}</span>${inlineHighlight(escapeHtml(rest))}`;
  }
  return inlineHighlight(escapeHtml(text));
}

// A VENUS firmware COM-trace line: "<dir> HH:MM:SS.mmm <port>: <payload>"
// (dir is "< " sent / "> " received / "! " info / "  " broadcast). Rendered
// with a "COM Trace:" label (mirroring "VenusTrace:"), the direction char and
// port highlighted, and -- for a real "< "/"> " firmware exchange -- only the
// leading command (the run of capitals/digits before the id, e.g. C0AS, C0RL,
// A1AMQY) picked out. Everything after the command is left as one plain string:
// running raw firmware parameters (ids, & separators, bare numbers) through the
// generic tokenizer just fragments them into meaningless colour.
const COMTRACE_LINE_RE = /^([<>!] |  )(\d{2}:\d{2}:\d{2}\.\d{3}) (.+?): (.*)$/;

function renderComTrace(text) {
  if (typeof text !== "string") text = String(text ?? "");
  const label = `<span class="tok-comtrace">COM Trace:</span> `;
  const m = text.match(COMTRACE_LINE_RE);
  if (!m) return label + escapeHtml(text);
  const [, dir, , port, payload] = m;
  let body;
  if ((dir[0] === "<" || dir[0] === ">") && /^[A-Z0-9]+[a-z]/.test(payload)) {
    const cmd = payload.match(/^[A-Z0-9]+/)[0];
    body = `<span class="tok-comm-cmd">${escapeHtml(cmd)}</span>${escapeHtml(payload.slice(cmd.length))}`;
  } else {
    body = escapeHtml(payload);
  }
  return (
    label +
    `<span class="tok-comm-dir">${escapeHtml(dir.trim() || "·")}</span> ` +
    `<span class="tok-logger">${escapeHtml(port)}:</span> ` +
    body
  );
}

// The redundant "[VenusTrace: ] YYYY-MM-DD HH:MM:SS[.,]mmm [ [LEVEL] ]" that
// leads every SDK-logger line and every VenusTrace line. We show one clean
// [HH:MM:SS.mmm] column plus the category label instead, so this prefix is
// stripped from the displayed body -- but its time (VENUS/SDK local
// wall-clock) is what the column shows.
const TRACE_PREFIX_RE =
  /^(?:VenusTrace:\s*)?(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:[.,](\d+))?\s*(?:\[(?:DEBUG|INFO|WARNING|ERROR|CRITICAL)\]\s*)?/;

function pad(n, width = 2) {
  return String(n).padStart(width, "0");
}

// Any Date-parseable string (the backend sends UTC ISO) -> local "HH:MM:SS.mmm".
function localClock(timestamp) {
  if (!timestamp) return "";
  const d = new Date(timestamp);
  if (Number.isNaN(d.getTime())) return "";
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
}

// { time, body }: the line's own clock time and its text with the redundant
// date/level prefix removed. Falls back to the WS receipt time (converted to
// local) for lines that carry no embedded timestamp (script print(),
// [script-runner] diagnostics, traceback frames).
function splitTraceLine(entry) {
  const text = typeof entry.text === "string" ? entry.text : String(entry.text ?? "");
  const m = text.match(TRACE_PREFIX_RE);
  if (!m) return { time: localClock(entry.timestamp), body: text };
  let frac = m[7] ? m[7].slice(0, 3).padEnd(3, "0") : "";
  if (!frac) {
    const d = new Date(entry.timestamp);
    if (!Number.isNaN(d.getTime())) frac = pad(d.getMilliseconds(), 3);
  }
  const time = frac ? `${m[4]}:${m[5]}:${m[6]}.${frac}` : `${m[4]}:${m[5]}:${m[6]}`;
  return { time, body: text.slice(m[0].length) };
}

// How far back (in entries) a late-arriving line may be repositioned to sit in
// event-time order. Normal COM-trace lag is a handful of lines; a line that
// would land further back than this (the tail catching up after a stall) is
// left at the tail instead of causing a large scroll jump / DOM shuffle.
const REORDER_WINDOW = 400;

// Local wall-clock milliseconds-since-midnight for an entry, used only to order
// lines by when their event actually happened rather than when the line reached
// the browser. Draws on the same time sources splitTraceLine()/localClock()
// display from, so the [hh:mm:ss] column and the ordering always agree:
//   1. an embedded "YYYY-MM-DD HH:MM:SS[.,]mmm" (VenusTrace / SDK-logger lines) -- local
//   2. otherwise the WS receipt timestamp (UTC ISO -> local); for a COM-trace
//      line app.js passes the line's own "HH:MM:SS.mmm" as 1970-01-01T<time>,
//      which parses as local and lands here too.
// Returns null when no time can be derived (caller keeps the line at the current
// tail). A run crossing local midnight is not handled -- ordering resets at 00:00.
function sortKeyOf(entry) {
  const text = typeof entry.text === "string" ? entry.text : "";
  const m = text.match(TRACE_PREFIX_RE);
  if (m) {
    const frac = m[7] ? Number(m[7].slice(0, 3).padEnd(3, "0")) : 0;
    return ((Number(m[4]) * 60 + Number(m[5])) * 60 + Number(m[6])) * 1000 + frac;
  }
  const d = new Date(entry.timestamp);
  if (!Number.isNaN(d.getTime())) {
    return ((d.getHours() * 60 + d.getMinutes()) * 60 + d.getSeconds()) * 1000 + d.getMilliseconds();
  }
  return null;
}

// Full innerHTML for one entry: "[time] Label: body". COM Trace builds its own
// label; Terminal gets no label (its lines already read cleanly).
function traceLineHtml(entry) {
  const tsHtml = (t) => `<span class="log-ts">[${escapeHtml(t)}]</span> `;
  if (entry.category === "comtrace") {
    return tsHtml(localClock(entry.timestamp) || "") + renderComTrace(entry.text);
  }
  const { time, body } = splitTraceLine(entry);
  const label = entry.category === "terminal" ? "" : CATEGORY_LABEL[entry.category] || "";
  const labelHtml = label ? `<span class="tok-cat-label">${escapeHtml(label)}:</span> ` : "";
  return tsHtml(time) + labelHtml + highlightLine(body);
}

function classify(entry) {
  const text = entry.text || "";
  // 1. Strong, structured error signals take priority over every subsystem
  //    bucket below -- e.g. a [ERROR]-level signalr line is Error, not Debug.
  //    Uncaught Python exceptions print with no logging format at all, so
  //    they're detected by shape (the "Traceback ..." header / a trailing
  //    "SomeError: ..." line) rather than by a logger prefix.
  if (/\[ERROR\]|\[CRITICAL\]/.test(text) || TRACEBACK_START_RE.test(text) || EXCEPTION_LINE_RE.test(text)) {
    return "error";
  }
  // 2. Specific SDK subsystems, regardless of their own log level -- a
  //    venus_client/_run_message_command_dispatcher line logged at DEBUG is
  //    still Communication, not Debug -- both are the get/put API traffic
  //    with VENUS, just from two different modules (direct HTTP calls vs.
  //    the run-message action queue).
  if (text.includes("hamilton_venus.venus_client:")) {
    // Every request made through venus_client's shared _send_http_request
    // helper -- every run-messages peek/pop poll, every command push, plus
    // one-off calls like abort/unload-method -- logs this same generic
    // "GET/POST <path> with/without Authorization header" line, purely for
    // header bookkeeping with no path-specific content. It's the single
    // busiest line in the whole trace and never carries anything the
    // Communication tab needs: real content (queued commands, drained
    // messages, method lifecycle) is always logged separately by its own
    // more specific debug line (_push_command, _run_message_command_dispatcher,
    // load_method/abort_method/etc.), so hiding this exact shape loses nothing.
    if (/\bwith(?:out)? Authorization\b/.test(text)) return "debug";
    return "communication";
  }
  if (text.includes("_run_message_command_dispatcher:")) return "communication";
  if (text.includes("VenusTrace:")) return "venus";
  // 3. Any other DEBUG/INFO-level SDK internal logging (_async_star_client,
  //    _method_file_manager, _signalr_listener, etc.) that isn't one of the
  //    specific subsystems above.
  if (/\[DEBUG\]/.test(text)) return "debug";
  if (/\[INFO\]/.test(text)) return "info";
  // 4. Plain print() output carries none of the brackets/prefixes above, so
  //    this is the only way to catch a script's own error message (e.g.
  //    `print(f"SDK error: {e}")` in say hi.py's except block).
  if (/error/i.test(text)) return "error";
  return "terminal";
}

function loadSet(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return new Set(fallback);
    const parsed = JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch (e) {
    return new Set(fallback);
  }
}

function saveSet(key, set) {
  try {
    localStorage.setItem(key, JSON.stringify([...set]));
  } catch (e) {
    // Storage unavailable; selection just won't persist.
  }
}

function loadBool(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : raw === "true";
  } catch (e) {
    return fallback;
  }
}

function saveBool(key, value) {
  try {
    localStorage.setItem(key, String(value));
  } catch (e) {
    // Storage unavailable; preference just won't persist.
  }
}

// _run_message_command_dispatcher logs each drained communication message as
// "Communication message: category=... command=... status=... id=<uuid>" --
// category/command/id are internal bookkeeping the operator doesn't need line
// by line; only the human-readable status text is worth showing in the
// Communication tab, so collapse the rest away for this one dispatcher shape.
const DISPATCHER_MESSAGE_RE = /Communication message: .*?\bstatus=(.*?)\s+id=\S+\s*$/;
// Matches the simplified line's own "Communication message: " lead-in so
// highlightLine() can bold it -- kept separate from DISPATCHER_MESSAGE_RE
// above, which parses the original unsimplified SDK log line instead.
const DISPATCHER_MESSAGE_LABEL_RE = /^(Communication message: )(.*)$/;

function simplifyDispatcherLine(text) {
  if (!text.includes("_run_message_command_dispatcher:")) return text;
  const match = text.match(DISPATCHER_MESSAGE_RE);
  return match ? `Communication message: ${match[1]}` : text;
}

class TraceView {
  // autoScrollToggleEl may be null (a finished log has nothing to follow). maxEntries
  // caps a live trace; the Log Viewer passes Infinity to keep a whole run.
  constructor(linesEl, filtersEl, wrapToggleEl, autoScrollToggleEl, searchInputEl, { maxEntries = 5000 } = {}) {
    this.linesEl = linesEl;
    this.filtersEl = filtersEl;
    this.wrapToggleEl = wrapToggleEl;
    this.autoScrollToggleEl = autoScrollToggleEl;
    this.searchInputEl = searchInputEl;
    this.maxEntries = maxEntries;
    this.entries = [];
    // Highest sort key assigned so far -- lines that carry no derivable time
    // (continuation lines, bare print()s with an unparseable timestamp) inherit
    // it so they stay glued to whatever preceded them.
    this._lastKey = null;
    this.hiddenCategories = loadSet(HIDDEN_CATEGORIES_KEY, DEFAULT_HIDDEN_CATEGORIES);
    this.searchTerm = "";

    this._renderFilters();

    const wordWrap = loadBool(WORD_WRAP_KEY, true);
    this.wrapToggleEl.checked = wordWrap;
    this.linesEl.classList.toggle("no-wrap", !wordWrap);
    this.wrapToggleEl.addEventListener("change", () => {
      this.linesEl.classList.toggle("no-wrap", !this.wrapToggleEl.checked);
      saveBool(WORD_WRAP_KEY, this.wrapToggleEl.checked);
    });

    if (this.autoScrollToggleEl) {
      this.autoScrollToggleEl.checked = loadBool(AUTO_SCROLL_KEY, true);
      this.autoScrollToggleEl.addEventListener("change", () => {
        saveBool(AUTO_SCROLL_KEY, this.autoScrollToggleEl.checked);
        if (this._autoScroll) this._scrollToBottom();
      });
    }

    this.searchInputEl.addEventListener("input", () => {
      this.searchTerm = this.searchInputEl.value.trim().toLowerCase();
      this._rerender();
    });
  }

  _renderFilters() {
    this.filtersEl.innerHTML = "";
    CATEGORIES.forEach(({ id, label }) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "filter-chip" + (this.hiddenCategories.has(id) ? "" : " active");
      btn.textContent = label;
      btn.addEventListener("click", () => {
        const nowVisible = !btn.classList.contains("active");
        btn.classList.toggle("active", nowVisible);
        if (nowVisible) this.hiddenCategories.delete(id);
        else this.hiddenCategories.add(id);
        saveSet(HIDDEN_CATEGORIES_KEY, this.hiddenCategories);
        this._rerender();
      });
      this.filtersEl.appendChild(btn);
    });
  }

  clear() {
    this.entries = [];
    this._lastKey = null;
    this.linesEl.innerHTML = "";
  }

  get _autoScroll() {
    return this.autoScrollToggleEl ? this.autoScrollToggleEl.checked : false;
  }

  // A whole, already time-ordered trace at once ({timestamp, category, source, text}):
  // one render instead of one DOM insert per line.
  loadAll(lines) {
    this.entries = lines.map((line, index) => ({
      source: line.source,
      level: "OTHER",
      text: simplifyDispatcherLine(typeof line.text === "string" ? line.text : String(line.text ?? "")),
      timestamp: line.timestamp,
      category: line.category,
      _key: index,
    }));
    this._lastKey = this.entries.length;
    this._rerender();
  }

  // Scroll to the first shown line at or after *timestamp* (ISO) and flash it; returns
  // whether a line was found. Turns its category on and clears the search if they hide it.
  scrollToTime(timestamp) {
    const target = Date.parse(timestamp);
    if (Number.isNaN(target)) return false;
    const atOrAfter = (e) => e.timestamp && Date.parse(e.timestamp) >= target;
    let entry = this.entries.find((e) => atOrAfter(e) && this._isVisible(e));
    if (!entry) {
      entry = this.entries.find(atOrAfter);
      if (!entry) return false;
      if (this.hiddenCategories.delete(entry.category)) {
        saveSet(HIDDEN_CATEGORIES_KEY, this.hiddenCategories);
        this._renderFilters();
      }
      if (this.searchTerm) {
        this.searchTerm = "";
        this.searchInputEl.value = "";
      }
      this._rerender();
    }
    if (!entry._el) return false;
    entry._el.scrollIntoView({ block: "center" });
    entry._el.classList.remove("log-line-flash");
    void entry._el.offsetWidth; // restart the animation
    entry._el.classList.add("log-line-flash");
    return true;
  }

  append({ source, level, text, timestamp, category }) {
    const safeText = typeof text === "string" ? text : String(text ?? "");
    const entry = { source, level: level ? level.toUpperCase() : "OTHER", text: safeText, timestamp };
    // An explicit category (e.g. "comtrace" for firmware .trc lines, which
    // classify() must never regex-match) wins; otherwise infer from the text.
    entry.category = category || classify(entry);
    entry.text = simplifyDispatcherLine(entry.text);

    // Insert in event-time order, not arrival order. COM-trace lines are
    // tail-polled from the .trc ~0.5 s behind the live SignalR VenusTrace
    // stream, so without this a firmware line lands well below the
    // "- start;"/"- complete;" trace for the very step it belongs to. A normal
    // in-order line still goes straight onto the end (the while loop walks 0
    // steps); only an out-of-order late arrival moves, and never further back
    // than REORDER_WINDOW entries (beyond that it's left at the tail).
    let key = sortKeyOf(entry);
    if (key === null) key = this._lastKey == null ? 0 : this._lastKey;
    entry._key = key;
    this._lastKey = this._lastKey == null ? key : Math.max(this._lastKey, key);

    let idx = this.entries.length;
    while (idx > 0 && this.entries[idx - 1]._key > key) idx--;
    if (this.entries.length - idx > REORDER_WINDOW) idx = this.entries.length;
    this.entries.splice(idx, 0, entry);

    while (this.entries.length > this.maxEntries) {
      const dropped = this.entries.shift();
      if (dropped._el && dropped._el.parentNode) dropped._el.remove();
      idx--;
    }
    if (idx < 0) return; // this entry aged straight back out under the cap

    if (!this._isVisible(entry)) return;
    if (idx >= this.entries.length - 1) this._appendLine(entry);
    else this._insertLine(entry, idx);
  }

  _isVisible(entry) {
    if (this.hiddenCategories.has(entry.category)) return false;
    if (this.searchTerm) {
      const hay = `${CATEGORY_LABEL[entry.category] || ""} ${entry.text || ""}`.toLowerCase();
      if (!hay.includes(this.searchTerm)) return false;
    }
    return true;
  }

  _scrollToBottom() {
    this.linesEl.scrollTop = this.linesEl.scrollHeight;
  }

  _appendLine(entry) {
    const line = document.createElement("div");
    line.className = `log-line log-cat-${entry.category}`;
    try {
      line.innerHTML = traceLineHtml(entry);
    } catch (err) {
      line.textContent = entry.text || "";
    }
    entry._el = line;
    this.linesEl.appendChild(line);
    if (this._autoScroll) this._scrollToBottom();
  }

  // Like _appendLine, but drops the node into event-time position: just before
  // the first already-rendered entry that sorts after it. Used for the
  // occasional COM-trace line that arrives once later-timestamped lines are
  // already on screen.
  _insertLine(entry, idx) {
    const line = document.createElement("div");
    line.className = `log-line log-cat-${entry.category}`;
    try {
      line.innerHTML = traceLineHtml(entry);
    } catch (err) {
      line.textContent = entry.text || "";
    }
    entry._el = line;
    let ref = null;
    for (let i = idx + 1; i < this.entries.length; i++) {
      const el = this.entries[i]._el;
      if (el && el.parentNode === this.linesEl) {
        ref = el;
        break;
      }
    }
    this.linesEl.insertBefore(line, ref);
    if (this._autoScroll) this._scrollToBottom();
  }

  _rerender() {
    this.linesEl.innerHTML = "";
    const frag = document.createDocumentFragment();
    this.entries.forEach((e) => {
      let visible;
      try {
        visible = this._isVisible(e);
      } catch (err) {
        visible = true;
      }
      if (!visible) return;
      const line = document.createElement("div");
      line.className = `log-line log-cat-${e.category}`;
      try {
        line.innerHTML = traceLineHtml(e);
      } catch (err) {
        line.textContent = e.text || "";
      }
      e._el = line;
      frag.appendChild(line);
    });
    this.linesEl.appendChild(frag);
    if (this._autoScroll) this._scrollToBottom();
  }
}
