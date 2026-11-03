const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "OTHER"];
const DEFAULT_HIDDEN_LEVELS = new Set(["DEBUG"]);
const STORAGE_KEY = "hamiltonStarDemo.trace.hiddenLevels";
const WRAP_STORAGE_KEY = "hamiltonStarDemo.trace.wordWrap";

function loadHiddenLevels() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === null) return new Set(DEFAULT_HIDDEN_LEVELS);
    const parsed = JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed.filter((l) => LOG_LEVELS.includes(l)) : []);
  } catch (e) {
    return new Set(DEFAULT_HIDDEN_LEVELS);
  }
}

function saveHiddenLevels(hiddenLevels) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...hiddenLevels]));
  } catch (e) {
    // Storage unavailable; filter selection just won't persist.
  }
}

function loadWordWrap() {
  try {
    const raw = localStorage.getItem(WRAP_STORAGE_KEY);
    return raw === null ? true : raw === "true";
  } catch (e) {
    return true;
  }
}

function saveWordWrap(enabled) {
  try {
    localStorage.setItem(WRAP_STORAGE_KEY, String(enabled));
  } catch (e) {
    // Storage unavailable; wrap preference just won't persist.
  }
}

class ConsolePane {
  constructor(paneEl, linesEl, filtersEl, wrapToggleEl) {
    this.paneEl = paneEl;
    this.linesEl = linesEl;
    this.filtersEl = filtersEl;
    this.wrapToggleEl = wrapToggleEl;
    this.maxEntries = 5000;
    this.entries = [];
    this.hiddenLevels = loadHiddenLevels();

    this._renderFilters();

    const wordWrap = loadWordWrap();
    this.wrapToggleEl.classList.toggle("active", wordWrap);
    this.linesEl.classList.toggle("no-wrap", !wordWrap);
    this.wrapToggleEl.addEventListener("click", () => {
      const enabled = !this.wrapToggleEl.classList.contains("active");
      this.wrapToggleEl.classList.toggle("active", enabled);
      this.linesEl.classList.toggle("no-wrap", !enabled);
      saveWordWrap(enabled);
    });
  }

  _renderFilters() {
    this.filtersEl.innerHTML = "";
    LOG_LEVELS.forEach((level) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "filter-chip" + (this.hiddenLevels.has(level) ? "" : " active");
      btn.textContent = level;
      btn.addEventListener("click", () => {
        const nowVisible = !btn.classList.contains("active");
        btn.classList.toggle("active", nowVisible);
        if (nowVisible) this.hiddenLevels.delete(level);
        else this.hiddenLevels.add(level);
        saveHiddenLevels(this.hiddenLevels);
        this._rerender();
      });
      this.filtersEl.appendChild(btn);
    });
  }

  clear() {
    this.entries = [];
    this.linesEl.innerHTML = "";
  }

  append({ source, level, text, timestamp }) {
    const bucket = level ? level.toUpperCase() : "OTHER";
    this.entries.push({ source, level: bucket, text, timestamp });
    while (this.entries.length > this.maxEntries) this.entries.shift();

    if (this.hiddenLevels.has(bucket)) return;
    this._appendLine(this.entries[this.entries.length - 1]);
  }

  _appendLine(entry) {
    const stickToBottom = this.linesEl.scrollTop + this.linesEl.clientHeight >= this.linesEl.scrollHeight - 20;
    const line = document.createElement("div");
    line.className = `log-line log-${entry.source}`;
    const ts = entry.timestamp ? entry.timestamp.split("T")[1]?.split(".")[0] || "" : "";
    line.textContent = `[${ts}] [${entry.source}] ${entry.text}`;
    this.linesEl.appendChild(line);
    if (stickToBottom) this.linesEl.scrollTop = this.linesEl.scrollHeight;
  }

  _rerender() {
    this.linesEl.innerHTML = "";
    this.entries
      .filter((e) => !this.hiddenLevels.has(e.level))
      .forEach((e) => {
        const line = document.createElement("div");
        line.className = `log-line log-${e.source}`;
        const ts = e.timestamp ? e.timestamp.split("T")[1]?.split(".")[0] || "" : "";
        line.textContent = `[${ts}] [${e.source}] ${e.text}`;
        this.linesEl.appendChild(line);
      });
    this.linesEl.scrollTop = this.linesEl.scrollHeight;
  }
}
