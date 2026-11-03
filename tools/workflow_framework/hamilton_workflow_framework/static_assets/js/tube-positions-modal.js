// "Tube Positions" builder modal for Add Tubes To Carrier's positions field --
// same "Fetch Positions" flow as the inline widget it replaced, just packaged
// as a modal to match the existing "Build..." (PositionPicker) convention: open
// immediately on click, fetch in the background, populate once the reply lands.
//
// Needs live backend access (StarClient.get_labware_positions(), via the
// GetLabwarePositions/LabwarePositions WS messages -- see ws_protocol.py), which
// this shared framework file has no global access to on its own: `ws` in
// demo_app's app.js is a variable local to its own main() closure, not a global,
// so it's threaded in explicitly via setWs() -- see app.js's `tubePositionsModal
// .setWs(ws)` call, made right after `ws` itself is constructed.
class TubePositionsModal {
  constructor() {
    this.modalEl = document.getElementById("tube-positions-modal");
    this.closeBtn = document.getElementById("tube-positions-close");
    this.cancelBtn = document.getElementById("tube-positions-cancel");
    this.insertBtn = document.getElementById("tube-positions-insert");
    this.statusEl = document.getElementById("tube-positions-status");
    this.applyRowEl = document.getElementById("tube-positions-apply-row");
    this.tableWrapEl = document.getElementById("tube-positions-table-wrap");

    this.ws = null;
    this.onInsert = null;
    this._handlerRegistered = false;
    this._awaitingReply = false;
    this._existingByPosition = {};
    this._tubeNames = [];
    this._tubeOptionsHtml = "";

    this.closeBtn.addEventListener("click", () => this._close());
    this.cancelBtn.addEventListener("click", () => this._close());
    this.insertBtn.addEventListener("click", () => this._save());
  }

  setWs(ws) {
    this.ws = ws;
  }

  // labwareName: current value of the step's "Labware Name" field.
  // currentPositions: existing {position, tube, x_offset, y_offset, z_offset}[]
  //   (e.g. reopening after a previous save) -- re-applied to matching rows once
  //   the fresh position list loads.
  // onInsert(result): called with the finalized array when the user clicks Save.
  open(labwareName, currentPositions, onInsert) {
    this.onInsert = onInsert;
    this.modalEl.hidden = false;
    this.tableWrapEl.hidden = true;
    this.tableWrapEl.innerHTML = "";
    this.applyRowEl.hidden = true;
    this.applyRowEl.innerHTML = "";
    this.insertBtn.disabled = true;
    this._awaitingReply = false;

    if (!labwareName) {
      this._setStatus("Set the Labware Name above first, then reopen this dialog.", "warn");
      return;
    }
    if (!this.ws) {
      this._setStatus("Not connected to the backend yet -- try again in a moment.", "warn");
      return;
    }

    this._existingByPosition = {};
    (Array.isArray(currentPositions) ? currentPositions : []).forEach((row) => {
      if (row && row.position !== undefined) this._existingByPosition[String(row.position)] = row;
    });

    const datalist = document.getElementById("labware-definitions-TUBE");
    this._tubeNames = datalist ? [...datalist.options].map((o) => o.value) : [];
    this._tubeOptionsHtml =
      '<option value="">— none —</option>'
      + this._tubeNames.map((n) => `<option value="${n}">${n}</option>`).join("");

    this._registerReplyHandlerOnce();
    this._setStatus("Fetching…");
    this._awaitingReply = true;
    this.ws.send({ type: "get_labware_positions", labware_name: labwareName });
  }

  // Registered once for this modal's entire lifetime (it's a page-level
  // singleton, unlike the old inline widget that got rebuilt -- and its
  // handlers re-registered -- every time a step editor opened), so there's no
  // listener pileup to worry about.
  _registerReplyHandlerOnce() {
    if (this._handlerRegistered) return;
    this._handlerRegistered = true;
    this.ws.onMessage("labware_positions", (msg) => this._handleReply(msg));
  }

  _handleReply(msg) {
    // Ignore replies that arrive after the modal was closed (or a duplicate/
    // stale one after we've already processed the one we were waiting for) --
    // WS delivery here is a single in-order connection with one request in
    // flight at a time, so this flag is sufficient without needing a
    // request-id round trip.
    if (!this._awaitingReply) return;
    this._awaitingReply = false;

    if (msg.error) {
      this._setStatus("Error: " + msg.error, "error");
      return;
    }
    const sites = msg.positions || [];
    if (sites.length === 0) {
      this._setStatus("No positions found for this labware.", "warn");
      return;
    }
    this._renderTable(sites);
    this._renderApplyRow();
    this.insertBtn.disabled = false;
    this._setStatus(
      `${sites.length} position${sites.length !== 1 ? "s" : ""} loaded, `
        + `${this._tubeNames.length} tube type${this._tubeNames.length !== 1 ? "s" : ""} available`,
    );
  }

  _setStatus(text, kind) {
    this.statusEl.textContent = text;
    this.statusEl.classList.remove("tube-positions-status-warn", "tube-positions-status-error");
    if (kind) this.statusEl.classList.add(`tube-positions-status-${kind}`);
  }

  _makeOffsetInput(cls, value) {
    const inp = document.createElement("input");
    inp.type = "number";
    inp.step = "any";
    inp.className = cls;
    inp.value = String(value || 0);
    return inp;
  }

  _renderTable(sites) {
    const table = document.createElement("table");
    table.className = "tube-positions-table";
    table.innerHTML =
      "<thead><tr><th>Position</th><th>Tube</th><th>xOffset</th><th>yOffset</th><th>zOffset</th></tr></thead>";
    const tbody = document.createElement("tbody");
    sites.forEach((site) => {
      const existing = this._existingByPosition[String(site)];
      const tr = document.createElement("tr");
      tr.dataset.position = site;

      const tdPos = document.createElement("td");
      tdPos.className = "tube-pos-position";
      tdPos.textContent = site;

      const tdTube = document.createElement("td");
      const tubeSel = document.createElement("select");
      tubeSel.className = "tube-pos-tube";
      tubeSel.innerHTML = this._tubeOptionsHtml;
      if (existing) tubeSel.value = existing.tube;
      tdTube.appendChild(tubeSel);

      const tdX = document.createElement("td");
      tdX.appendChild(this._makeOffsetInput("tube-pos-x", existing && existing.x_offset));
      const tdY = document.createElement("td");
      tdY.appendChild(this._makeOffsetInput("tube-pos-y", existing && existing.y_offset));
      const tdZ = document.createElement("td");
      tdZ.appendChild(this._makeOffsetInput("tube-pos-z", existing && existing.z_offset));

      tr.appendChild(tdPos);
      tr.appendChild(tdTube);
      tr.appendChild(tdX);
      tr.appendChild(tdY);
      tr.appendChild(tdZ);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    this.tableWrapEl.innerHTML = "";
    this.tableWrapEl.appendChild(table);
    this.tableWrapEl.hidden = false;
  }

  _renderApplyRow() {
    this.applyRowEl.innerHTML = "";
    const label = document.createElement("span");
    label.className = "tube-positions-apply-label";
    label.textContent = "Apply to all:";
    const tubeSel = document.createElement("select");
    tubeSel.innerHTML = this._tubeOptionsHtml;
    const xInp = this._makeOffsetInput("", 0);
    xInp.title = "xOffset";
    const yInp = this._makeOffsetInput("", 0);
    yInp.title = "yOffset";
    const zInp = this._makeOffsetInput("", 0);
    zInp.title = "zOffset";
    const applyBtn = document.createElement("button");
    applyBtn.type = "button";
    applyBtn.className = "btn btn-secondary";
    applyBtn.textContent = "Apply to All";
    applyBtn.addEventListener("click", () => {
      [...this.tableWrapEl.querySelectorAll("tbody tr")].forEach((row) => {
        row.querySelector(".tube-pos-tube").value = tubeSel.value;
        row.querySelector(".tube-pos-x").value = xInp.value;
        row.querySelector(".tube-pos-y").value = yInp.value;
        row.querySelector(".tube-pos-z").value = zInp.value;
      });
    });
    this.applyRowEl.appendChild(label);
    this.applyRowEl.appendChild(tubeSel);
    this.applyRowEl.appendChild(xInp);
    this.applyRowEl.appendChild(yInp);
    this.applyRowEl.appendChild(zInp);
    this.applyRowEl.appendChild(applyBtn);
    this.applyRowEl.hidden = false;
  }

  _collectPositions() {
    const rows = [...this.tableWrapEl.querySelectorAll("tbody tr")];
    return rows
      .filter((row) => row.querySelector(".tube-pos-tube").value !== "")
      .map((row) => ({
        position: row.dataset.position,
        tube: row.querySelector(".tube-pos-tube").value,
        x_offset: parseFloat(row.querySelector(".tube-pos-x").value) || 0,
        y_offset: parseFloat(row.querySelector(".tube-pos-y").value) || 0,
        z_offset: parseFloat(row.querySelector(".tube-pos-z").value) || 0,
      }));
  }

  _save() {
    const result = this._collectPositions();
    if (this.onInsert) this.onInsert(result);
    this._close();
  }

  _close() {
    this._awaitingReply = false;
    this.modalEl.hidden = true;
    this.onInsert = null;
  }
}

const tubePositionsModal = new TubePositionsModal();
