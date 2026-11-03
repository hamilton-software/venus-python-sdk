const FB_FOLDER_ICON =
  '<svg width="14" height="14" viewBox="0 0 640 640" fill="currentColor"><path d="M64 160c0-17.7 14.3-32 32-32h140.1c9.7 0 18.9 4.4 25 12l30 37.5c6.1 7.6 15.3 12 25 12H544c17.7 0 32 14.3 32 32v32H64V160zm0 125.3h512V480c0 17.7-14.3 32-32 32H96c-17.7 0-32-14.3-32-32V285.3z"/></svg>';
const FB_FILE_ICON =
  '<svg width="14" height="14" viewBox="0 0 640 640" fill="currentColor"><path d="M144 64c-17.7 0-32 14.3-32 32v448c0 17.7 14.3 32 32 32h352c17.7 0 32-14.3 32-32V245.3c0-8.5-3.4-16.6-9.4-22.6L374.6 73.4c-6-6-14.1-9.4-22.6-9.4H144zm208 32v128c0 17.7 14.3 32 32 32h96v256H144V96h208z"/></svg>';

// Modes:
// - "open" (default): click a file row to select it (existing behavior,
//   used by the shortcut-modal "Browse..." button).
// - "open-multiple": click file rows to toggle-select several, then
//   "Open Selected" confirms the set (backs tkinter.filedialog.askopenfilenames).
// - "save": type a new filename (may not exist yet) and click "Save"
//   (backs tkinter.filedialog.asksaveasfilename).
// - "directory": navigate folders only; "Select This Folder" confirms the
//   current one (backs tkinter.filedialog.askdirectory).
class FileBrowserModal {
  constructor() {
    this.modalEl = document.getElementById("file-browser-modal");
    this.titleEl = document.getElementById("file-browser-title");
    this.closeBtn = document.getElementById("file-browser-close");
    this.cancelBtn = document.getElementById("file-browser-cancel");
    this.upBtn = document.getElementById("file-browser-up");
    this.pathEl = document.getElementById("file-browser-path");
    this.listEl = document.getElementById("file-browser-list");
    this.selectDirBtn = document.getElementById("file-browser-select-dir");
    this.saveRowEl = document.getElementById("file-browser-save-row");
    this.saveNameEl = document.getElementById("file-browser-save-name");
    this.saveBtn = document.getElementById("file-browser-save");
    this.openMultipleBtn = document.getElementById("file-browser-open-multiple");

    this.ext = "";
    this.mode = "open";
    this.currentDir = null;
    this.parentDir = null;
    this.onSelect = null;
    this.onCancel = null;
    this.resolved = false;
    this.selectedPaths = new Set();

    this.closeBtn.addEventListener("click", () => this._cancel());
    this.cancelBtn.addEventListener("click", () => this._cancel());
    this.upBtn.addEventListener("click", () => {
      if (this.parentDir) this._load(this.parentDir);
    });
    this.selectDirBtn.addEventListener("click", () => {
      if (this.currentDir) this._select(this.currentDir);
    });
    this.saveBtn.addEventListener("click", () => this._submitSave());
    this.saveNameEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") this._submitSave();
    });
    this.openMultipleBtn.addEventListener("click", () => {
      if (this.selectedPaths.size > 0) this._select([...this.selectedPaths]);
    });
  }

  // open(currentValue, ext, onSelect, options?) -- options: {mode, title,
  // initialDir, initialFile, onCancel}. The 3-arg call (no options) keeps
  // working exactly as before for the existing shortcut-source-file picker.
  open(currentValue, ext, onSelect, options = {}) {
    this.ext = ext || "";
    this.mode = options.mode || "open";
    this.onSelect = onSelect;
    this.onCancel = options.onCancel || null;
    this.resolved = false;
    this.selectedPaths = new Set();

    this.titleEl.textContent = options.title || (this.ext ? `Select a .${this.ext} File` : "Select a File");
    this.selectDirBtn.hidden = this.mode !== "directory";
    this.saveRowEl.hidden = this.mode !== "save";
    this.saveBtn.hidden = this.mode !== "save";
    this.openMultipleBtn.hidden = this.mode !== "open-multiple";
    if (this.mode === "save") this.saveNameEl.value = options.initialFile || "";

    this.modalEl.hidden = false;

    const startDir = options.initialDir
      || (currentValue && /[\\/]/.test(currentValue)
        ? currentValue.slice(0, Math.max(currentValue.lastIndexOf("\\"), currentValue.lastIndexOf("/")))
        : null);
    this._load(startDir);
  }

  async _load(dir) {
    this.listEl.innerHTML = '<div class="file-browser-empty">Loading…</div>';
    const params = new URLSearchParams();
    if (dir) params.set("dir", dir);
    if (this.ext) params.set("ext", this.ext);
    try {
      const resp = await fetch(`/api/browse-files?${params.toString()}`);
      const data = await resp.json();
      this.currentDir = data.current_dir;
      this.parentDir = data.parent_dir;
      this.pathEl.value = this.currentDir;
      this.upBtn.disabled = !this.parentDir;
      this._renderEntries(data.entries || []);
    } catch (e) {
      this.listEl.innerHTML = '<div class="file-browser-empty">Failed to load this folder.</div>';
    }
  }

  _renderEntries(entries) {
    this.listEl.innerHTML = "";
    // "directory" mode only offers folders to navigate -- there's nothing to
    // do with a file row, so leave them out entirely.
    const visible = this.mode === "directory" ? entries.filter((e) => e.is_dir) : entries;
    if (visible.length === 0) {
      const empty = document.createElement("div");
      empty.className = "file-browser-empty";
      empty.textContent = this.ext ? `No folders or .${this.ext} files here.` : "This folder is empty.";
      this.listEl.appendChild(empty);
      return;
    }
    visible.forEach((entry) => {
      const row = document.createElement("div");
      row.className = "file-browser-row" + (entry.is_dir ? " is-dir" : "");
      row.innerHTML = `<span class="file-browser-icon">${entry.is_dir ? FB_FOLDER_ICON : FB_FILE_ICON}</span><span class="file-browser-name"></span>`;
      row.querySelector(".file-browser-name").textContent = entry.name;
      row.addEventListener("click", () => {
        if (entry.is_dir) {
          this._load(entry.path);
          return;
        }
        if (this.mode === "open-multiple") {
          row.classList.toggle("is-selected");
          if (this.selectedPaths.has(entry.path)) this.selectedPaths.delete(entry.path);
          else this.selectedPaths.add(entry.path);
          return;
        }
        if (this.mode === "save") {
          this.saveNameEl.value = entry.name;
          return;
        }
        this._select(entry.path);
      });
      this.listEl.appendChild(row);
    });
  }

  _submitSave() {
    const name = this.saveNameEl.value.trim();
    if (!name || !this.currentDir) return;
    const sep = this.currentDir.includes("/") && !this.currentDir.includes("\\") ? "/" : "\\";
    const trimmedDir = this.currentDir.endsWith(sep) ? this.currentDir.slice(0, -1) : this.currentDir;
    this._select(`${trimmedDir}${sep}${name}`);
  }

  _select(path) {
    this.resolved = true;
    const callback = this.onSelect;
    this._close();
    if (callback) callback(path);
  }

  _cancel() {
    const callback = this.onCancel;
    const alreadyResolved = this.resolved;
    this._close();
    if (!alreadyResolved && callback) callback();
  }

  _close() {
    this.modalEl.hidden = true;
    this.onSelect = null;
    this.onCancel = null;
  }
}

const fileBrowserModal = new FileBrowserModal();
