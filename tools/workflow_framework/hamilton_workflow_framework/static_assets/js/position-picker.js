// Standard SBS microplate formats: well count -> {rows, cols}.
const PP_PLATE_FORMATS = {
  6: { rows: 2, cols: 3 },
  24: { rows: 4, cols: 6 },
  96: { rows: 8, cols: 12 },
  384: { rows: 16, cols: 24 },
};
const PP_RESERVOIR_COUNTS = [8, 12, 96];
const PP_TUBE_CARRIER_COUNTS = [12, 24, 32];

function ppRowLetter(index) {
  return String.fromCharCode(65 + index);
}

class PositionPicker {
  constructor() {
    this.modalEl = document.getElementById("position-picker-modal");
    this.closeBtn = document.getElementById("position-picker-close");
    this.cancelBtn = document.getElementById("position-picker-cancel");
    this.insertBtn = document.getElementById("position-picker-insert");
    this.nameInput = document.getElementById("pp-labware-name");
    this.typeGroupEl = document.getElementById("pp-type-group");
    this.countGroupEl = document.getElementById("pp-count-group");
    this.selectAllBtn = document.getElementById("pp-select-all");
    this.clearBtn = document.getElementById("pp-clear");
    this.addFragmentBtn = document.getElementById("pp-add-fragment");
    this.gridWrapEl = document.getElementById("pp-grid-wrap");
    this.fragmentsWrapEl = document.getElementById("pp-fragments-wrap");
    this.fragmentsListEl = document.getElementById("pp-fragments-list");
    this.previewEl = document.getElementById("pp-preview");

    this.type = "plate";
    this.count = 96;
    this.selected = new Set();
    this.fragments = [];
    this.onInsert = null;

    this.closeBtn.addEventListener("click", () => this._close());
    this.cancelBtn.addEventListener("click", () => this._close());
    this.insertBtn.addEventListener("click", () => this._insert());
    this.selectAllBtn.addEventListener("click", () => this._selectAll());
    this.addFragmentBtn.addEventListener("click", () => this._addFragment());
    this.clearBtn.addEventListener("click", () => {
      this.selected.clear();
      this._renderGrid();
    });
    this.nameInput.addEventListener("input", () => this._updatePreview());

    this.typeGroupEl.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.type = btn.dataset.type;
        this.count = this._countsForType(this.type)[0];
        this.selected.clear();
        this._renderTypeChips();
        this._renderCountChips();
        this._renderGrid();
      });
    });
  }

  open(currentValue, onInsert) {
    this.onInsert = onInsert;
    this.type = "plate";
    this.count = 96;
    this.selected.clear();
    this.fragments = this._parseExistingFragments(currentValue);
    this.nameInput.value = "";

    this._renderTypeChips();
    this._renderCountChips();
    this._renderGrid();
    this._renderFragments();
    this.modalEl.hidden = false;
    setTimeout(() => this.nameInput.focus(), 50);
  }

  _countsForType(type) {
    if (type === "plate") return Object.keys(PP_PLATE_FORMATS).map(Number);
    if (type === "reservoir") return PP_RESERVOIR_COUNTS;
    return PP_TUBE_CARRIER_COUNTS;
  }

  _renderTypeChips() {
    this.typeGroupEl.querySelectorAll("button").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.type === this.type);
    });
  }

  _renderCountChips() {
    this.countGroupEl.innerHTML = "";
    this._countsForType(this.type).forEach((n) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "filter-chip" + (n === this.count ? " active" : "");
      btn.textContent = String(n);
      btn.addEventListener("click", () => {
        this.count = n;
        this.selected.clear();
        this._renderCountChips();
        this._renderGrid();
      });
      this.countGroupEl.appendChild(btn);
    });
  }

  _renderGrid() {
    this.gridWrapEl.innerHTML = "";
    if (this.type === "plate") {
      this._renderPlateGrid();
    } else {
      this._renderFlatGrid();
    }
    this._updatePreview();
  }

  _renderPlateGrid() {
    const { rows, cols } = PP_PLATE_FORMATS[this.count];
    const grid = document.createElement("div");
    const dense = cols > 12 || rows > 8;
    grid.className = "pp-plate-grid" + (dense ? " pp-dense" : "");
    grid.style.gridTemplateColumns = `${dense ? 20 : 28}px repeat(${cols}, ${dense ? 22 : 30}px)`;

    const corner = document.createElement("div");
    corner.className = "pp-cell pp-corner";
    grid.appendChild(corner);

    for (let c = 1; c <= cols; c++) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "pp-cell pp-header";
      btn.textContent = String(c);
      btn.title = `Select column ${c}`;
      btn.addEventListener("click", () => this._toggleColumn(c, rows));
      grid.appendChild(btn);
    }

    for (let r = 0; r < rows; r++) {
      const rLetter = ppRowLetter(r);
      const rowBtn = document.createElement("button");
      rowBtn.type = "button";
      rowBtn.className = "pp-cell pp-header";
      rowBtn.textContent = rLetter;
      rowBtn.title = `Select row ${rLetter}`;
      rowBtn.addEventListener("click", () => this._toggleRow(rLetter, cols));
      grid.appendChild(rowBtn);

      for (let c = 1; c <= cols; c++) {
        const token = `${rLetter}${c}`;
        const cell = document.createElement("button");
        cell.type = "button";
        cell.className = "pp-cell" + (this.selected.has(token) ? " selected" : "");
        cell.title = token;
        cell.addEventListener("click", () => this._toggleWell(token));
        grid.appendChild(cell);
      }
    }

    this.gridWrapEl.appendChild(grid);
  }

  _renderFlatGrid() {
    const grid = document.createElement("div");
    grid.className = "pp-flat-grid";
    for (let n = 1; n <= this.count; n++) {
      const token = String(n);
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "pp-cell" + (this.selected.has(token) ? " selected" : "");
      cell.textContent = token;
      cell.addEventListener("click", () => this._toggleWell(token));
      grid.appendChild(cell);
    }
    this.gridWrapEl.appendChild(grid);
  }

  _toggleWell(token) {
    if (this.selected.has(token)) this.selected.delete(token);
    else this.selected.add(token);
    this._renderGrid();
  }

  _toggleColumn(col, rows) {
    const tokens = [];
    for (let r = 0; r < rows; r++) tokens.push(`${ppRowLetter(r)}${col}`);
    const allSelected = tokens.every((t) => this.selected.has(t));
    tokens.forEach((t) => (allSelected ? this.selected.delete(t) : this.selected.add(t)));
    this._renderGrid();
  }

  _toggleRow(rLetter, cols) {
    const tokens = [];
    for (let c = 1; c <= cols; c++) tokens.push(`${rLetter}${c}`);
    const allSelected = tokens.every((t) => this.selected.has(t));
    tokens.forEach((t) => (allSelected ? this.selected.delete(t) : this.selected.add(t)));
    this._renderGrid();
  }

  _selectAll() {
    this.selected.clear();
    if (this.type === "plate") {
      const { rows, cols } = PP_PLATE_FORMATS[this.count];
      for (let r = 0; r < rows; r++) {
        for (let c = 1; c <= cols; c++) this.selected.add(`${ppRowLetter(r)}${c}`);
      }
    } else {
      for (let n = 1; n <= this.count; n++) this.selected.add(String(n));
    }
    this._renderGrid();
  }

  // Positions are listed in the order they were selected (this.selected is an
  // insertion-ordered Set), so a "Custom" well order runs them as clicked. The
  // all/col:/row: shorthands are used only when they expand to exactly that
  // order (as Select All and the row/column headers produce); otherwise a
  // shorthand would silently reorder the wells.
  _buildExpression() {
    if (this.selected.size === 0) return "";
    const clicked = [...this.selected];
    const matchesClickOrder = (expanded) =>
      expanded.length === clicked.length && expanded.every((t, i) => t === clicked[i]);

    if (this.type !== "plate") {
      const all = [];
      for (let n = 1; n <= this.count; n++) all.push(String(n));
      if (matchesClickOrder(all)) return "all";
      return clicked.join(",");
    }

    const { rows, cols } = PP_PLATE_FORMATS[this.count];
    const all = [];
    for (let r = 0; r < rows; r++) {
      for (let c = 1; c <= cols; c++) all.push(`${ppRowLetter(r)}${c}`);
    }
    if (matchesClickOrder(all)) return "all";

    const colsInOrder = [];
    const rowsInOrder = [];
    for (const token of clicked) {
      const m = /^([A-Za-z]+)(\d+)$/.exec(token);
      if (!m) continue;
      const c = parseInt(m[2], 10);
      if (!colsInOrder.includes(c)) colsInOrder.push(c);
      if (!rowsInOrder.includes(m[1])) rowsInOrder.push(m[1]);
    }

    const byColumns = [];
    for (const c of colsInOrder) {
      for (let r = 0; r < rows; r++) byColumns.push(`${ppRowLetter(r)}${c}`);
    }
    if (matchesClickOrder(byColumns)) return "col:" + colsInOrder.join(",");

    const byRows = [];
    for (const rl of rowsInOrder) {
      for (let c = 1; c <= cols; c++) byRows.push(`${rl}${c}`);
    }
    if (matchesClickOrder(byRows)) return "row:" + rowsInOrder.join(",");

    return clicked.join(",");
  }

  _currentFragmentText() {
    const name = this.nameInput.value.trim();
    if (!name) return "";
    const expr = this._buildExpression();
    return expr ? `${name}@${expr}` : name;
  }

  _updatePreview() {
    const parts = [...this.fragments];
    const current = this._currentFragmentText();
    if (current) parts.push(current);
    this.previewEl.value = parts.join(";");
  }

  _parseExistingFragments(value) {
    if (!value || typeof value !== "string") return [];
    return value.split(";").map((s) => s.trim()).filter((s) => s.length > 0);
  }

  _addFragment() {
    const text = this._currentFragmentText();
    if (!text) {
      showMessageBar("Enter a labware name and select at least one position first.", "warning");
      return;
    }
    this.fragments.push(text);
    this.nameInput.value = "";
    this.selected.clear();
    this._renderFragments();
    this._renderGrid();
    this.nameInput.focus();
  }

  _renderFragments() {
    this.fragmentsListEl.innerHTML = "";
    this.fragmentsWrapEl.hidden = this.fragments.length === 0;
    this.fragments.forEach((text, idx) => {
      const chip = document.createElement("div");
      chip.className = "pp-fragment-chip";

      const label = document.createElement("span");
      label.textContent = text;
      chip.appendChild(label);

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "pp-fragment-chip-remove";
      removeBtn.textContent = "✕";
      removeBtn.title = "Remove";
      removeBtn.addEventListener("click", () => {
        this.fragments.splice(idx, 1);
        this._renderFragments();
        this._updatePreview();
      });
      chip.appendChild(removeBtn);

      this.fragmentsListEl.appendChild(chip);
    });
    this._updatePreview();
  }

  _insert() {
    const parts = [...this.fragments];
    const current = this._currentFragmentText();
    if (current) parts.push(current);
    if (parts.length === 0) {
      showMessageBar("Please enter a labware name and select at least one position.", "warning");
      return;
    }
    const result = parts.join(";");
    const callback = this.onInsert;
    this._close();
    if (callback) callback(result);
  }

  _close() {
    this.modalEl.hidden = true;
    this.onInsert = null;
  }
}

const positionPicker = new PositionPicker();
