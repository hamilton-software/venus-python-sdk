// Shown when an operator clicks a dispense row in the Sample Tracking tab's
// well breakdown panel (sample-tracking-view.js's _renderBreakdown) that has
// a TADM curve on either side of the transfer -- its own dispense curve, its
// paired aspirate's curve, or both (see ws_protocol.py's tadm_result /
// sample_event.transfer_id docs for how the two get matched up). Reuses
// summary-view.js's renderSummaryTadmChart as-is (same global-function
// convention as the rest of this app, no module system) rather than
// reimplementing the canvas chart -- it only needs curve objects shaped like
// {curve_id, channel_number, error, curve_flagged, curve_points}, so
// _toChartCurve below adapts a tadm_result message into that shape.
class TadmTransferModal {
  constructor() {
    this.modalEl = document.getElementById("tadm-transfer-modal");
    this.titleEl = document.getElementById("tadm-transfer-title");
    this.subtitleEl = document.getElementById("tadm-transfer-subtitle");
    this.aspirateEl = document.getElementById("tadm-transfer-aspirate");
    this.dispenseEl = document.getElementById("tadm-transfer-dispense");
    document.getElementById("tadm-transfer-modal-close").addEventListener("click", () => this.close());
    this.modalEl.addEventListener("click", (event) => {
      if (event.target === this.modalEl) this.close(); // click on the dimmed backdrop
    });
  }

  // aspirateTadm/dispenseTadm are raw tadm_result messages (or null/undefined
  // if that side never produced a curve). title/subtitle are plain strings
  // describing which transfer this is, built by the caller.
  show({ title, subtitle, aspirateTadm, dispenseTadm }) {
    this.titleEl.textContent = title || "Transfer TADM";
    this.subtitleEl.textContent = subtitle || "";
    this._renderSide(this.aspirateEl, aspirateTadm);
    this._renderSide(this.dispenseEl, dispenseTadm);
    this.modalEl.hidden = false;
  }

  _renderSide(container, tadm) {
    container.innerHTML = "";
    if (!tadm) {
      const empty = document.createElement("div");
      empty.className = "summary-empty-hint";
      empty.textContent = "No TADM data for this step.";
      container.appendChild(empty);
      return;
    }
    renderSummaryTadmChart(container, [_toChartCurve(tadm)]);
  }

  close() {
    this.modalEl.hidden = true;
  }
}

function _toChartCurve(tadm) {
  return {
    curve_id: tadm.transfer_id,
    channel_number: tadm.channel,
    error: tadm.error_code,
    curve_flagged: tadm.curve_flagged,
    curve_points: tadm.curve_points,
  };
}
