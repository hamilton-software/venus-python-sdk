// Shown when the SDK escalates a hardware error to the registered operator callback
// (see WorkflowSession._handle_operator_escalation) because automatic recovery is
// exhausted. The instrument stays halted until this modal is answered -- there is
// deliberately no close/dismiss affordance other than the action buttons themselves,
// including "Abort", so a stray click can't silently leave the SDK's callback (and
// therefore the instrument) waiting the same way the missing callback used to.
//
// Channels are grouped by their exact error message (one error type -> one group ->
// one dropdown of that group's own server-advertised recovery-action choices) so
// every channel hit by the SAME error type shares ONE dropdown -- "set all recoveries
// for this error type at once" -- rather than a separate dropdown per channel that
// would usually just be set identically anyway. A channel with a genuinely different
// message (a different failure kind within the same escalation) gets its own separate
// group/dropdown. Every dropdown defaults to "Repeat" when the server offers it for
// that group (the most commonly-useful blind retry), falling back to whatever VENUS's
// own suggested default names otherwise (see session.py's ``_channel_rows_with_actions``).
// Submitted together via one "Apply Selections" button, fanning each group's one chosen
// action out to every detail uuid it covers. Abort/Cancel remain flat, always-available
// buttons alongside it, since those don't need per-channel context -- both are handed
// straight to the SDK's own recovery-submission path (never handled client-side only),
// same as every other recovery action here.
//
// Matches python_script_manager_app/backend/static/js/operator-recovery-modal.js's
// format exactly (this module is the shared, canonical implementation both apps use;
// script manager's own copy predates this file gaining the same capability and stays
// as its own fork since it has no shared WorkflowSession to route through).
class OperatorPromptModal {
  constructor({ ws, consolePane }) {
    this.ws = ws;
    this.consolePane = consolePane;
    this.modalEl = document.getElementById("operator-prompt-modal");
    this.codeEl = document.getElementById("operator-prompt-code");
    this.titleEl = document.getElementById("operator-prompt-title");
    this.channelsEl = document.getElementById("operator-prompt-channels");
    this.actionsEl = document.getElementById("operator-prompt-actions");
    this.currentUuid = null;
    this._groupSelects = []; // [{detailUuids, select}]
    this._pulse = null;
    this._busyTimer = null;
  }

  // Unlock/lock door and raise/lower load tray only change access to the inside
  // of the instrument -- they do not answer the error. So the modal stays open:
  // everything is disabled, and the clicked button pulses, until the instrument
  // has carried the action out and the backend pushes a fresh operator_prompt
  // for the same error (re-rendered in place by show(), with the opposite
  // action offered and the picks kept). They get their own boxed "Instrument
  // Utilities" group in the actions area, apart from the recoveries; a single
  // button keeps its natural width, several share the row.
  _renderAccessActions(accessActions) {
    if (accessActions.length === 0) return;
    const sectionEl = document.createElement("div");
    sectionEl.className = "operator-prompt-access";
    sectionEl.style.cssText =
      "display:flex;flex-direction:column;gap:8px;padding:12px;border-radius:8px;" +
      "border:1px solid var(--border-muted, rgba(128, 128, 128, 0.35));";
    if (this.actionsEl.children.length > 0) sectionEl.style.marginTop = "12px";
    const headingEl = document.createElement("span");
    headingEl.textContent = "Instrument Utilities:";
    headingEl.style.cssText = "font-size:13px;font-weight:600;";
    sectionEl.appendChild(headingEl);
    const rowEl = document.createElement("div");
    rowEl.style.cssText = "display:flex;justify-content:center;gap:8px;";
    accessActions.forEach((accessAction) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-secondary";
      if (accessActions.length === 1) btn.style.width = "auto";
      else btn.style.flex = "1 1 0";
      btn.textContent = accessAction.label;
      btn.addEventListener("click", () => this._requestAccess(accessAction, btn));
      rowEl.appendChild(btn);
    });
    sectionEl.appendChild(rowEl);
    this.actionsEl.appendChild(sectionEl);
  }

  _requestAccess(accessAction, btn) {
    if (!this.currentUuid) return;
    this.ws.send({ type: "operator_prompt_response", error_uuid: this.currentUuid, action: accessAction.key });
    this._logResponse(`Operator requested "${accessAction.label}" for error ${this.currentUuid}`);
    this._setBusy(true, btn);
  }

  _setBusy(busy, activeBtn = null) {
    clearTimeout(this._busyTimer);
    this._busyTimer = null;
    if (this._pulse) this._pulse.cancel();
    this._pulse = null;
    this.modalEl.querySelectorAll("button, select, input").forEach((el) => { el.disabled = busy; });
    if (busy) {
      if (activeBtn && activeBtn.animate) {
        this._pulse = activeBtn.animate(
          [{ opacity: 1 }, { opacity: 0.35 }, { opacity: 1 }],
          { duration: 1000, iterations: Infinity, easing: "ease-in-out" },
        );
      }
      // Never leave the operator locked out if no update arrives.
      this._busyTimer = setTimeout(() => this._setBusy(false), 30000);
    }
  }

  show(msg) {
    // The same error again after an access action: keep what the operator picked.
    const isRefresh = this.currentUuid !== null && msg.error_uuid === this.currentUuid;
    const keptSelections = new Map();
    if (isRefresh) {
      this._groupSelects.forEach((entry) => keptSelections.set(entry.detailUuids.join("|"), entry.select.value));
    }
    this._setBusy(false);
    this.currentUuid = msg.error_uuid;
    this._groupSelects = [];
    this.codeEl.textContent = msg.code || "";
    this.titleEl.textContent = msg.title || "";

    const channelErrors = msg.channel_errors || [];
    this.channelsEl.innerHTML = "";
    let anyDropdowns = false;
    channelErrors.forEach((group) => {
      const rowEl = document.createElement("div");
      rowEl.className = "operator-prompt-channel-row";
      const channels = group.channels || [];
      if (channels.length > 0) {
        const badge = document.createElement("span");
        badge.className = "operator-prompt-channel-badge";
        badge.textContent = channels.length === 1 ? `Ch ${channels[0]}` : `Ch ${channels.join(", ")}`;
        rowEl.appendChild(badge);
      }
      const text = document.createElement("span");
      text.className = "operator-prompt-channel-message";
      text.textContent = group.message;
      rowEl.appendChild(text);

      const detailUuids = group.detail_uuids || [];
      if (detailUuids.length > 0 && group.actions && group.actions.length > 0) {
        anyDropdowns = true;
        const select = document.createElement("select");
        select.className = "operator-prompt-channel-select";
        group.actions.forEach((action) => {
          const opt = document.createElement("option");
          opt.value = String(action.id);
          opt.textContent = action.name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
          if (action.id === group.default_action_id) opt.selected = true;
          select.appendChild(opt);
        });
        rowEl.appendChild(select);
        const keptValue = keptSelections.get(detailUuids.join("|"));
        if (keptValue !== undefined && [...select.options].some((o) => o.value === keptValue)) select.value = keptValue;
        this._groupSelects.push({ detailUuids, select });
      }
      this.channelsEl.appendChild(rowEl);
    });

    // Three groups, top to bottom, with extra space between them: Apply
    // Selections (directly under the error details), Instrument Utilities,
    // then the error-wide buttons (Abort/Cancel) side by side.
    this.actionsEl.innerHTML = "";
    this.actionsEl.style.cssText = "display:flex;flex-direction:column;align-items:stretch;gap:8px;";
    if (anyDropdowns) {
      const applyBtn = document.createElement("button");
      applyBtn.type = "button";
      applyBtn.className = "btn btn-primary";
      applyBtn.textContent = "Apply Selections";
      applyBtn.addEventListener("click", () => this._respondWithChannels());
      this.actionsEl.appendChild(applyBtn);
    }
    this._renderAccessActions(msg.access_actions || []);

    const topLevelRowEl = document.createElement("div");
    topLevelRowEl.style.cssText = "display:flex;gap:8px;";
    if (this.actionsEl.children.length > 0) topLevelRowEl.style.marginTop = "12px";
    const topLevelNames = [...new Set(msg.top_level_actions || [])];
    if (!topLevelNames.includes("abort")) topLevelNames.push("abort");
    topLevelNames.forEach((name) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = name === "abort" ? "btn btn-secondary operator-prompt-abort" : "btn btn-secondary";
      btn.textContent = name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
      btn.style.flex = "1 1 0";
      btn.addEventListener("click", () => this._respondWithAction(name));
      topLevelRowEl.appendChild(btn);
    });
    this.actionsEl.appendChild(topLevelRowEl);

    this.modalEl.hidden = false;
    if (isRefresh) return;

    if (this.consolePane) {
      const channelSummary = channelErrors
        .map((g) => ((g.channels || []).length ? `ch${g.channels.join(",")}: ${g.message}` : g.message))
        .join("; ");
      this.consolePane.append({
        source: "backend",
        level: "WARNING",
        text: `Operator action required: ${msg.code || ""} ${msg.title || ""}${channelSummary ? " (" + channelSummary + ")" : ""}`.trim(),
        timestamp: msg.timestamp || new Date().toISOString(),
      });
    }
    showMessageBar("Instrument stopped: operator action required.", "warning");
  }

  _respondWithAction(action) {
    if (!this.currentUuid) return;
    this.ws.send({ type: "operator_prompt_response", error_uuid: this.currentUuid, action });
    this._logResponse(`Operator chose "${action}" (applied to all channels) for error ${this.currentUuid}`);
    this._close();
  }

  _respondWithChannels() {
    if (!this.currentUuid) return;
    const channelActions = {};
    for (const { detailUuids, select } of this._groupSelects) {
      const actionId = parseInt(select.value, 10);
      detailUuids.forEach((detailUuid) => { channelActions[detailUuid] = actionId; });
    }
    this.ws.send({ type: "operator_prompt_response", error_uuid: this.currentUuid, channel_actions: channelActions });
    this._logResponse(`Operator applied per-error-type recovery selections for error ${this.currentUuid}`);
    this._close();
  }

  _logResponse(text) {
    if (this.consolePane) {
      this.consolePane.append({ source: "backend", text, timestamp: new Date().toISOString() });
    }
  }

  _close() {
    // The "operator action required" warning bar (showMessageBar's "warning"
    // type deliberately never auto-dismisses, unlike other message types --
    // so it doesn't get missed while the instrument sits halted) has served
    // its purpose once a recovery choice is actually sent; leaving it up after
    // the modal closes would look like the instrument is still stuck even
    // though it isn't.
    if (typeof dismissMessageBar === "function") dismissMessageBar();
    this._setBusy(false);
    this.modalEl.hidden = true;
    this.currentUuid = null;
    this._groupSelects = [];
  }
}
