// Renders the "Sample Tracking" tab: one card per labware that has received
// at least one dispense ("target"), driven live by sample_labware_info/
// sample_event WS messages from the running subprocess (see script_runner.py's
// bootstrap item 8). Plates render as a well grid (including untouched cells,
// so "nothing happened here" is visually meaningful); anything else (e.g. a
// tube rack) renders as a list of only the wells actually touched. Clicking a
// well expands an inline breakdown of every aspirate/dispense step that
// touched it, color-coded by source.

// Same categorical palette as summary-view.js's TADM chart, kept as a local
// copy (not a shared import -- this app has no module system linking view
// files) so source colors here stay visually consistent with the rest of the
// app rather than introducing an unrelated palette.
const SAMPLE_SOURCE_COLORS_LIGHT = ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"];
const SAMPLE_SOURCE_COLORS_DARK = ["#3987e5", "#199e70", "#c98500", "#008300", "#9085e9", "#e66767", "#d55181", "#d95926"];

function _sampleSourceColors() {
  const theme = document.documentElement.getAttribute("data-theme");
  return theme === "dark" ? SAMPLE_SOURCE_COLORS_DARK : SAMPLE_SOURCE_COLORS_LIGHT;
}

// Mirrors hamilton_venus.models.position.LabwareLayoutSpec's
// _index_to_alpha_label/cell_to_number/emit_well exactly (0-based row index,
// 1-based column -> well id), so a plate's full grid -- including untouched
// cells -- can be rendered without waiting for an event to reveal each well's
// real id.
function _sampleIndexToAlphaLabel(index) {
  let label = "";
  let n = index;
  for (;;) {
    label = String.fromCharCode(65 + (n % 26)) + label;
    n = Math.floor(n / 26) - 1;
    if (n < 0) return label;
  }
}

function _sampleCellToNumber(rowIndex, col, rows, cols, pattern) {
  if (pattern === "ROW_MAJOR") return rowIndex * cols + (col - 1) + 1;
  return (col - 1) * rows + rowIndex + 1;
}

function _sampleEmitWell(rowIndex, col, rows, cols, numericAddressing, pattern) {
  if (numericAddressing) return String(_sampleCellToNumber(rowIndex, col, rows, cols, pattern));
  return `${_sampleIndexToAlphaLabel(rowIndex)}${col}`;
}

class SampleTrackingView {
  constructor(bodyEl, { tadmModal = null, reportModal = null } = {}) {
    this.bodyEl = bodyEl;
    this.tadmModal = tadmModal;
    this.reportModal = reportModal;
    // labware id -> {labware_class, rows, cols, numeric_addressing, pattern,
    // wells: {well -> {current_volume_ul, has_error, dominant_source_key, steps: []}}}
    this.labware = {};
    this.sourceColors = {}; // source_key -> palette index, first-seen order
    this.selectedWell = null; // {labware, well} or null
    this.activeFilter = "all"; // "all" | "plate" | "tube_rack" | "errors"
    // transfer_id -> raw tadm_result message. Populated live as curves arrive
    // (see applyTadm) -- may still be empty when a breakdown row referencing
    // it first renders, since a tadm_result can arrive slightly after (or
    // before) the sample_event it belongs to; re-rendering on each one keeps
    // a row's clickability current once its curve does show up.
    this._tadmByTransferId = new Map();
    // aspirate transfer_id -> {labware, well} of the dispense that used it
    // (a dispense's source_transfer_id), so an aspirate row can show where
    // its liquid went. Kept separately because the aspirate may arrive after
    // that dispense (held until its labware became a target).
    this._targetByAspirateId = new Map();
    this._render();
  }

  reset() {
    // Called when a new run starts, mirroring ConsumablesView.reset() -- drop
    // every card/well from the previous run rather than letting stale state
    // linger into the new one.
    this.labware = {};
    this.sourceColors = {};
    this.selectedWell = null;
    this.activeFilter = "all";
    this._tadmByTransferId.clear();
    this._targetByAspirateId.clear();
    this._render();
  }

  applyTadm(msg) {
    this._tadmByTransferId.set(msg.transfer_id, msg);
    this._render();
  }

  addLabware(msg) {
    const existing = this.labware[msg.labware];
    if (existing) {
      // Re-sent when the labware's barcode changes after it was first shown
      // (e.g. assigned later with set_barcodes) -- update just the barcode.
      if (msg.barcode && msg.barcode !== existing.barcode) {
        existing.barcode = msg.barcode;
        this._render();
      }
      return;
    }
    this.labware[msg.labware] = {
      labware_class: msg.labware_class,
      rows: msg.rows,
      cols: msg.cols,
      numeric_addressing: msg.numeric_addressing,
      pattern: msg.pattern || "COLUMN_MAJOR",
      barcode: msg.barcode || null,
      wells: {},
    };
    this._render();
  }

  applyEvent(msg) {
    // The bootstrap always announces a labware (sample_labware_info) before
    // its first sample_event, so this fallback only guards a dropped/
    // reordered WS delivery, not the normal case.
    const entry = this.labware[msg.labware] || (this.labware[msg.labware] = {
      labware_class: "unknown", rows: 8, cols: 12, numeric_addressing: false, pattern: "COLUMN_MAJOR",
      barcode: null, wells: {},
    });
    const well = entry.wells[msg.well] || (entry.wells[msg.well] = {
      current_volume_ul: 0, has_error: false, dominant_source_key: null, steps: [],
    });
    well.current_volume_ul = msg.current_volume_ul;
    // A failed transfer, or one that hit an instrument error and was recovered
    // (sample_event's "errors") -- both mark the well, its card's Error badge
    // and the "Errors only" filter.
    if (!msg.success || (msg.errors && msg.errors.length > 0)) well.has_error = true;
    // Only a dispense step carries a source_key -- an aspirate-out never
    // recolors the well (design: this well itself IS the source for
    // whatever downstream dispense uses it, not the other way around).
    if (msg.source_key !== null && msg.source_key !== undefined) {
      if (!(msg.source_key in this.sourceColors)) this.sourceColors[msg.source_key] = Object.keys(this.sourceColors).length;
      well.dominant_source_key = msg.source_key;
    }
    well.steps.push(msg);
    if (msg.operation === "dispense" && msg.source_transfer_id !== null && msg.source_transfer_id !== undefined) {
      this._targetByAspirateId.set(msg.source_transfer_id, { labware: msg.labware, well: msg.well });
    }
    this._render();
  }

  // Where an aspirate's liquid was dispensed ({labware, well, barcode}), or null if not (yet) known.
  _aspirateTarget(transferId) {
    const target = this._targetByAspirateId.get(transferId);
    if (!target) return null;
    return { ...target, barcode: this.labware[target.labware]?.barcode || null };
  }

  _render() {
    this.bodyEl.innerHTML = "";
    const labwareEntries = Object.entries(this.labware);
    if (labwareEntries.length === 0) {
      this.bodyEl.appendChild(this._emptyHint("No dispense targets yet."));
      return;
    }
    this.bodyEl.appendChild(this._renderFilters());
    const grid = document.createElement("div");
    grid.className = "sample-card-grid";
    labwareEntries.forEach(([labwareId, entry]) => {
      if (!this._passesFilter(labwareId, entry)) return;
      grid.appendChild(this._renderCard(labwareId, entry));
    });
    this.bodyEl.appendChild(grid);
  }

  // The channel liquid waste container is a fixed, always-present system
  // labware named "liquid_waste" -- its VENUS definition reports
  // labware_class "plate" (it does have a rows x cols well grid), but
  // conceptually it isn't a plate a method dispenses samples into, so it gets
  // its own category/filter instead of bucketing into "Plates".
  _category(labwareId, entry) {
    if (labwareId === "liquid_waste") return "waste";
    return entry.labware_class === "plate" ? "plate" : "tube_rack";
  }

  _passesFilter(labwareId, entry) {
    if (this.activeFilter === "errors") return Object.values(entry.wells).some((w) => w.has_error);
    if (this.activeFilter === "all") return true;
    return this._category(labwareId, entry) === this.activeFilter;
  }

  _renderFilters() {
    const row = document.createElement("div");
    row.className = "sample-tracking-filters";
    [["all", "All"], ["plate", "Plates"], ["tube_rack", "Tube Racks"], ["waste", "Waste"], ["errors", "Errors only"]].forEach(([value, label]) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "filter-chip";
      chip.classList.toggle("active", this.activeFilter === value);
      chip.textContent = label;
      chip.addEventListener("click", () => {
        this.activeFilter = value;
        this._render();
      });
      row.appendChild(chip);
    });
    return row;
  }

  _renderCard(labwareId, entry) {
    // .sample-card-body (header + wells) over .sample-card-footer (actions), the
    // card-body/card-footer split the rest of the design system uses.
    const card = document.createElement("div");
    card.className = "sample-card";
    const body = document.createElement("div");
    body.className = "sample-card-body";
    card.appendChild(body);

    const header = document.createElement("div");
    header.className = "sample-card-header";
    const title = document.createElement("span");
    title.className = "sample-card-title";
    title.textContent = labwareId;
    title.title = labwareId;
    header.appendChild(title);
    const category = this._category(labwareId, entry);
    const classLabel = document.createElement("span");
    classLabel.className = "sample-card-class";
    classLabel.textContent = category === "waste" ? "waste" : entry.labware_class;
    header.appendChild(classLabel);
    if (entry.barcode) {
      const barcodeLabel = document.createElement("span");
      barcodeLabel.className = "sample-card-barcode";
      barcodeLabel.textContent = entry.barcode;
      barcodeLabel.title = "Scanned barcode";
      header.appendChild(barcodeLabel);
    }
    if (Object.values(entry.wells).some((w) => w.has_error)) {
      const badge = document.createElement("span");
      badge.className = "consumable-badge sample-card-error-badge";
      badge.textContent = "Error";
      header.appendChild(badge);
    }
    body.appendChild(header);

    // Waste still renders as a well grid (it has a real rows x cols layout,
    // just like a plate) -- only the filter category treats it separately.
    body.appendChild(
      category === "tube_rack" ? this._renderTubeList(labwareId, entry) : this._renderPlateGrid(labwareId, entry),
    );

    if (this.reportModal) {
      const footer = document.createElement("div");
      footer.className = "sample-card-footer";
      const reportBtn = document.createElement("button");
      reportBtn.type = "button";
      reportBtn.className = "btn btn-secondary btn-small";
      reportBtn.textContent = "Report";
      reportBtn.title = "Detailed transfer report for this labware";
      reportBtn.addEventListener("click", () =>
        this.reportModal.show({
          labwareId, entry, tadmByTransferId: this._tadmByTransferId,
          aspirateTarget: (transferId) => this._aspirateTarget(transferId),
        }),
      );
      footer.appendChild(reportBtn);
      card.appendChild(footer);
    }

    return card;
  }

  _wellColor(well) {
    if (well.dominant_source_key === null || well.dominant_source_key === undefined) return null;
    const colorIndex = this.sourceColors[well.dominant_source_key];
    if (colorIndex === undefined) return null;
    const colors = _sampleSourceColors();
    return colors[colorIndex % colors.length];
  }

  _wellHasMultipleSources(well) {
    const sourceKeys = new Set(
      well.steps.filter((s) => s.source_key !== null && s.source_key !== undefined).map((s) => s.source_key),
    );
    return sourceKeys.size > 1;
  }

  // Distinct scanned source barcodes across every dispense into this well
  // (see script_runner.py's source_barcode docs) -- a well can carry more
  // than one if it received transfers from several scanned tubes/plates.
  _wellBarcodes(well) {
    return [...new Set(well.steps.map((s) => s.source_barcode).filter(Boolean))];
  }

  _renderPlateGrid(labwareId, entry) {
    // Outer plain-flow wrapper, not itself a grid: the breakdown panel (below)
    // gets appended here as a normal block sibling of the well grid rather
    // than as a `grid-column: 1 / -1` cell inside it. If it were a grid cell,
    // its width would be capped by the well grid's own fixed-width columns
    // (see below) -- fine for the wells themselves, but it squeezed the
    // breakdown's time/source/volume row into that same narrow width. As a
    // plain sibling it can report its own natural (wider) preferred width,
    // which is what lets .sample-card (width: max-content) expand to fit it.
    const container = document.createElement("div");
    container.className = "sample-plate-grid-container";

    const wrap = document.createElement("div");
    wrap.className = "sample-plate-grid";
    container.appendChild(wrap);
    // Fixed (capped) well size rather than 1fr: with 1fr, a low-column-count
    // labware (e.g. a single-well liquid_waste) puts all the card's spare
    // width into that one column, and since wells are circles pinned to
    // aspect-ratio 1/1, the row height balloons with it. A capped px size
    // keeps every card's row height determined by row count alone, so a
    // liquid_waste card (8 rows) lines up with a 96-well plate card (also 8
    // rows) instead of dwarfing it.
    wrap.style.gridTemplateColumns = `24px repeat(${entry.cols}, minmax(0, 26px))`;

    // Corner cell + column-number header row.
    wrap.appendChild(document.createElement("div"));
    for (let col = 1; col <= entry.cols; col++) {
      const colLabel = document.createElement("div");
      colLabel.className = "sample-well-label";
      colLabel.textContent = String(col);
      wrap.appendChild(colLabel);
    }

    let breakdownEl = null;
    for (let rowIndex = 0; rowIndex < entry.rows; rowIndex++) {
      const rowLabel = document.createElement("div");
      rowLabel.className = "sample-well-label";
      rowLabel.textContent = entry.numeric_addressing ? "" : _sampleIndexToAlphaLabel(rowIndex);
      wrap.appendChild(rowLabel);

      for (let col = 1; col <= entry.cols; col++) {
        const wellId = _sampleEmitWell(rowIndex, col, entry.rows, entry.cols, entry.numeric_addressing, entry.pattern);
        const well = entry.wells[wellId];
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "sample-well";
        btn.dataset.well = wellId;
        if (well) {
          btn.classList.add("sample-well-active");
          btn.style.backgroundColor = this._wellColor(well) || "";
          if (well.has_error) btn.classList.add("sample-well-error");
          if (this._wellHasMultipleSources(well)) btn.classList.add("sample-well-multi-source");
          btn.title = `${labwareId}@${wellId} — ${Math.round(well.current_volume_ul)} µL`;
          const barcodes = this._wellBarcodes(well);
          if (barcodes.length) btn.title += ` — Barcode: ${barcodes.join(", ")}`;
        } else {
          btn.title = `${labwareId}@${wellId}`;
        }
        const isSelected = !!this.selectedWell && this.selectedWell.labware === labwareId && this.selectedWell.well === wellId;
        btn.classList.toggle("sample-well-selected", isSelected);
        btn.addEventListener("click", () => this._toggleWell(labwareId, wellId, well));
        wrap.appendChild(btn);

        if (isSelected && well) breakdownEl = this._renderBreakdown(labwareId, wellId, well);
      }
    }

    if (breakdownEl) container.appendChild(breakdownEl);
    return container;
  }

  _renderTubeList(labwareId, entry) {
    const list = document.createElement("div");
    list.className = "sample-tube-list";
    const wellIds = Object.keys(entry.wells);
    if (wellIds.length === 0) {
      list.appendChild(this._emptyHint("No wells touched yet."));
      return list;
    }
    wellIds.forEach((wellId) => {
      const well = entry.wells[wellId];
      const row = document.createElement("div");
      row.className = "sample-tube-row";
      if (well.has_error) row.classList.add("sample-well-error");
      row.addEventListener("click", () => this._toggleWell(labwareId, wellId, well));

      const colorDot = document.createElement("span");
      colorDot.className = "sample-source-swatch";
      colorDot.style.background = this._wellColor(well) || "transparent";
      row.appendChild(colorDot);

      const label = document.createElement("span");
      label.className = "sample-tube-well";
      label.textContent = wellId;
      row.appendChild(label);

      const volume = document.createElement("span");
      volume.className = "sample-tube-volume";
      volume.textContent = `${Math.round(well.current_volume_ul)} µL`;
      row.appendChild(volume);

      list.appendChild(row);

      const isSelected = !!this.selectedWell && this.selectedWell.labware === labwareId && this.selectedWell.well === wellId;
      if (isSelected) list.appendChild(this._renderBreakdown(labwareId, wellId, well));
    });
    return list;
  }

  _toggleWell(labwareId, wellId, well) {
    if (!well) return;
    const isSame = !!this.selectedWell && this.selectedWell.labware === labwareId && this.selectedWell.well === wellId;
    this.selectedWell = isSame ? null : { labware: labwareId, well: wellId };
    this._render();
  }

  _renderBreakdown(labwareId, wellId, well) {
    const panel = document.createElement("div");
    panel.className = "sample-well-breakdown";

    const header = document.createElement("div");
    header.className = "sample-well-breakdown-header";
    header.textContent = `${labwareId}@${wellId} — Current volume: ${Math.round(well.current_volume_ul)} µL`;
    panel.appendChild(header);

    const colors = _sampleSourceColors();
    well.steps.forEach((step) => {
      const row = document.createElement("div");
      row.className = "sample-breakdown-step";

      const time = document.createElement("span");
      time.className = "sample-breakdown-time";
      time.textContent = this._formatTime(step.timestamp);
      row.appendChild(time);

      // Time | source (the only part that wraps) | channel | volume | badge:
      // a long source or barcode wraps inside its own column instead of
      // pushing the channel/volume/badge onto another line.
      const source = document.createElement("span");
      source.className = "sample-breakdown-source";
      row.appendChild(source);

      if (step.operation === "dispense" && step.source_labware) {
        const swatch = document.createElement("span");
        swatch.className = "sample-source-swatch";
        const colorIndex = this.sourceColors[step.source_key];
        swatch.style.background = colorIndex !== undefined ? colors[colorIndex % colors.length] : "transparent";
        source.appendChild(swatch);
        const sourceLabel = document.createElement("span");
        sourceLabel.textContent = `${step.source_labware}@${step.source_well}`;
        source.appendChild(sourceLabel);
        if (step.source_barcode) {
          const barcodeLabel = document.createElement("span");
          barcodeLabel.className = "sample-breakdown-barcode";
          barcodeLabel.textContent = step.source_barcode;
          barcodeLabel.title = step.source_barcode_type
            ? `Source barcode (${step.source_barcode_type})`
            : "Barcode of the source";
          source.appendChild(barcodeLabel);
        }
      } else if (step.operation === "aspirate") {
        const removal = document.createElement("span");
        removal.className = "sample-step-removal";
        const target = this._aspirateTarget(step.transfer_id);
        removal.textContent = target ? `Aspirated out → ${target.labware}@${target.well}` : "Aspirated out";
        source.appendChild(removal);
      } else {
        const unknown = document.createElement("span");
        unknown.textContent = "Unknown source";
        source.appendChild(unknown);
      }

      const channel = document.createElement("span");
      channel.className = "sample-breakdown-fixed";
      channel.textContent = step.channel === "MPH" ? "MPH" : `CH ${step.channel}`;
      row.appendChild(channel);

      const volume = document.createElement("span");
      volume.className = "sample-breakdown-fixed sample-breakdown-volume";
      const sign = step.operation === "dispense" ? "+" : "-";
      volume.textContent = `${sign}${Math.round(step.volume)} µL`;
      row.appendChild(volume);

      const stepErrors = step.errors || [];
      if (!step.success) {
        const errBadge = document.createElement("span");
        errBadge.className = "sample-step-error";
        errBadge.textContent = "Failed";
        errBadge.title = step.error || "The command failed";
        row.appendChild(errBadge);
      } else if (stepErrors.length > 0) {
        const errBadge = document.createElement("span");
        errBadge.className = "sample-step-error";
        errBadge.textContent = "Recovered";
        errBadge.title = "This transfer hit an instrument error and completed after recovery";
        row.appendChild(errBadge);
      }

      // A dispense step's own transfer_id (its dispense-side TADM curve, if
      // adc=True was set) and source_transfer_id (its paired aspirate's own
      // curve -- see ws_protocol.py's sample_event docs) are two independent
      // lookups; either, both, or neither may have a curve. Only make the row
      // clickable once at least one side actually has data -- an aspirate
      // step ("Aspirated out") has no destination-side pairing to show here,
      // so it's never clickable.
      if (step.operation === "dispense") {
        const dispenseTadm = this._tadmByTransferId.get(step.transfer_id);
        const aspirateTadm = this._tadmByTransferId.get(step.source_transfer_id);
        if (dispenseTadm || aspirateTadm) {
          row.classList.add("sample-breakdown-step-clickable");
          row.title = "View TADM pressure curves for this transfer";
          row.addEventListener("click", () => {
            if (!this.tadmModal) return;
            const sourceLabel = step.source_labware ? `${step.source_labware}@${step.source_well}` : "unknown source";
            this.tadmModal.show({
              title: "Transfer TADM",
              subtitle: `${sourceLabel} → ${labwareId}@${wellId} — ${step.channel === "MPH" ? "MPH" : `CH ${step.channel}`}`,
              aspirateTadm,
              dispenseTadm,
            });
          });
        }
      }

      panel.appendChild(row);

      // One line per instrument error the transfer hit: what it was and the
      // recovery submitted (the labware report shows the same details).
      stepErrors.forEach((e) => {
        const line = document.createElement("div");
        line.className = "sample-breakdown-error";
        const recovery = e.recovery
          ? ` → ${e.kind === "action" ? "Action" : "Recovery"}: ${e.recovery}${e.decided_by ? ` (${e.decided_by})` : ""}`
          : "";
        const during = e.during ? e.during.charAt(0).toUpperCase() + e.during.slice(1) : null;
        line.textContent = [during, e.code, e.message || e.title || "Instrument error"].filter(Boolean).join(" · ") + recovery;
        panel.appendChild(line);
      });
      if (!step.success) {
        // The failure message can be a whole exception text: its own line, not the badge.
        const line = document.createElement("div");
        line.className = "sample-breakdown-error";
        line.textContent = `Command failed · ${step.error || "no error message reported"}`;
        panel.appendChild(line);
      }
    });

    return panel;
  }

  _formatTime(isoString) {
    if (!isoString) return "—";
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) return "—";
    return `${date.toLocaleTimeString(undefined, { hour12: false })}.${String(date.getMilliseconds()).padStart(3, "0")}`;
  }

  _emptyHint(text) {
    const el = document.createElement("div");
    el.className = "consumables-empty";
    el.textContent = text;
    return el;
  }
}
