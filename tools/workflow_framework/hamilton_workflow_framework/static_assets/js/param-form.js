// Group names must match hamilton_venus.catalog.LABWARE's own namespace
// attribute names (ADAPTER/CARRIER/LID/PLATE/RESERVOIR/TIP_RACK/TUBE/TUBE_RACK
// as of the labware:v1 catalog rewrite) -- these are introspected generically
// server-side (see demo_app's _labware_catalog_groups()), not hardcoded there,
// so this map is the only place that needs to track a catalog rename.
// "TIP_RACK_NTR" is a server-derived group, not a raw catalog namespace --
// see _labware_catalog_groups() -- narrowed to the nestable-stack tip racks
// that are actually valid for Add NTR.
const LABWARE_DEFINITION_GROUP_BY_COMMAND = {
  add_carrier: "CARRIER",
  add_carrier_to_site: "ADAPTER",
  add_tube_carrier: "TUBE_RACK",
  add_tip_rack: "TIP_RACK",
  add_tip_box: "TIP_BOX",
  add_ntr: "TIP_RACK_NTR",
  add_plate: "PLATE",
  add_lidded_plate: "PLATE",
  add_lid: "LID",
  add_reservoir: "RESERVOIR",
};

// One datalist per "Define ... Settings" source command (e.g.
// define_aspirate_settings vs define_dispense_settings) so a compound command
// combining both an aspirate-settings and a dispense-settings profile field
// (see ParamSpec.profile_source) doesn't mix the two name pools together.
function _refreshProfileOptions(profileSource, names) {
  const datalistId = `settings-profile-options-${profileSource}`;
  let datalist = document.getElementById(datalistId);
  if (!datalist) {
    datalist = document.createElement("datalist");
    datalist.id = datalistId;
    document.body.appendChild(datalist);
  }
  datalist.innerHTML = "";
  (names || []).forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    datalist.appendChild(opt);
  });
  return datalistId;
}

// Populated live from the instrument (see GetTipPools/GetCarriers/GetPlates in
// ws_protocol.py) whenever the app is connected -- see setTipPoolNames() /
// setCarrierNames() / setPlateNames() in app.js. Empty while disconnected, which
// is what naturally limits the suggestion dropdown to "only when connected":
// the field itself stays a normal free-text input either way, so typing a name
// always works.
function _makeLiveDatalist(datalistId) {
  let names = [];
  return {
    get: () => names,
    set: (newNames) => {
      names = newNames || [];
      let datalist = document.getElementById(datalistId);
      if (!datalist) {
        datalist = document.createElement("datalist");
        datalist.id = datalistId;
        document.body.appendChild(datalist);
      }
      datalist.innerHTML = "";
      names.forEach((name) => {
        const opt = document.createElement("option");
        opt.value = name;
        datalist.appendChild(opt);
      });
    },
  };
}

const _tipPoolDatalist = _makeLiveDatalist("tip-pool-options");
const _carrierDatalist = _makeLiveDatalist("carrier-options");
const _plateDatalist = _makeLiveDatalist("plate-options");
const _trackDatalist = _makeLiveDatalist("track-options");

function setTipPoolNames(names) {
  _tipPoolDatalist.set(names);
}

function setCarrierNames(names) {
  _carrierDatalist.set(names);
}

function setPlateNames(names) {
  _plateDatalist.set(names);
}

// Available (unoccupied) deck tracks -- see GetTracks/Tracks in ws_protocol.py.
// Refreshed after add_carrier succeeds (see app.js), since placing a carrier
// consumes a track and narrows what's still available for the next one.
function setTrackNumbers(tracks) {
  _trackDatalist.set((tracks || []).map(String));
}

// Attaches the live datalist named by spec.suggest (see ParamSpec.suggest in
// command_registry.py) to `input`, regardless of the field's type/name --
// this is what lets string_list plate-selector params (compound commands'
// source_plate, dest_plate, reagent_source, etc.) get the same autocomplete
// as standard pipetting steps' positions-adjacent fields.
function _attachSuggestDatalist(input, spec) {
  switch (spec.suggest) {
    case "plate":
      setPlateNames(_plateDatalist.get());
      input.setAttribute("list", "plate-options");
      break;
    case "tip_pool":
      setTipPoolNames(_tipPoolDatalist.get());
      input.setAttribute("list", "tip-pool-options");
      break;
    case "carrier":
      setCarrierNames(_carrierDatalist.get());
      input.setAttribute("list", "carrier-options");
      break;
    case "track":
      setTrackNumbers(_trackDatalist.get());
      input.setAttribute("list", "track-options");
      break;
    default:
      break;
  }
}

// Builds the "Add Tubes To Carrier" positions field: a "Fetch Positions" button
// that opens tubePositionsModal (see tube-positions-modal.js) -- same
// open-immediately-then-fetch-in-the-background convention as the "Build..."
// button uses for pipetting positions (see positionPicker below), just backed
// by a live StarClient.get_labware_positions() call (via the
// GetLabwarePositions/LabwarePositions WS messages, see ws_protocol.py) instead
// of a purely client-side well grid. Emits an array of {position, tube,
// x_offset, y_offset, z_offset} objects via onChange -- a real JS array, not a
// JSON string, so it flows through DemoKwargsBuilder/codegen's plain
// pass-through branch untouched (see kwargs_builder.py's
// `spec.name == "positions" and isinstance(value, str)` guard, which this
// deliberately does not trigger).
function _buildTubePositionsField(field, spec, currentValue, values, onChange) {
  const wrap = document.createElement("div");
  wrap.className = "positions-input-wrap";

  const summary = document.createElement("input");
  summary.type = "text";
  summary.readOnly = true;
  const updateSummary = () => {
    const rows = Array.isArray(currentValue) ? currentValue : [];
    summary.value = rows.length === 0 ? "" : `${rows.length} position${rows.length !== 1 ? "s" : ""} set`;
    field.classList.toggle("param-missing", spec.required && rows.length === 0);
  };
  updateSummary();
  wrap.appendChild(summary);

  const fetchBtn = document.createElement("button");
  fetchBtn.type = "button";
  fetchBtn.className = "btn btn-secondary";
  fetchBtn.textContent = "Fetch Positions";
  fetchBtn.addEventListener("click", () => {
    const labwareName = (values["labware_name"] || "").trim();
    tubePositionsModal.open(labwareName, currentValue, (result) => {
      currentValue = result;
      updateSummary();
      onChange(spec.name, result);
    });
  });
  wrap.appendChild(fetchBtn);

  field.appendChild(wrap);
}

function renderParamForm(container, paramSpecs, values, onChange, commandId, profileNames) {
  container.innerHTML = "";
  if (!paramSpecs || paramSpecs.length === 0) return;
  container.classList.add("step-params");

  paramSpecs.forEach((spec) => {
    const field = document.createElement("div");
    field.className = "param-field";

    const label = document.createElement("label");
    label.textContent = spec.label + (spec.required ? " *" : "");
    if (spec.help) label.title = spec.help;
    field.appendChild(label);

    let input;
    let extraWrap = null; // set when the field renders as input+sibling(s) instead of a bare input
    const currentValue = values[spec.name] !== undefined ? values[spec.name] : spec.default;

    if (spec.type === "tube_positions") {
      _buildTubePositionsField(field, spec, currentValue, values, onChange);
      field.classList.add("full-width");
      container.appendChild(field);
      return;
    }

    const updateMissingState = () => {
      const isEmpty = spec.type === "bool" ? false : input.value === undefined || input.value === null || input.value === "";
      field.classList.toggle("param-missing", spec.required && isEmpty);
    };

    const hasRange = (spec.type === "int" || spec.type === "float")
      && spec.min_value !== null && spec.min_value !== undefined
      && spec.max_value !== null && spec.max_value !== undefined;

    if (hasRange) {
      const wrap = document.createElement("div");
      wrap.className = "param-range-wrap";
      input = document.createElement("input");
      input.type = "range";
      input.min = spec.min_value;
      input.max = spec.max_value;
      input.step = spec.type === "int" ? 1 : "any";
      input.value = currentValue !== undefined && currentValue !== null ? currentValue : spec.min_value;
      const readout = document.createElement("span");
      readout.className = "param-range-value";
      readout.textContent = input.value;
      input.addEventListener("input", () => { readout.textContent = input.value; });
      input.addEventListener("change", () => {
        onChange(spec.name, spec.type === "int" ? parseInt(input.value, 10) : parseFloat(input.value));
      });
      wrap.appendChild(input);
      wrap.appendChild(readout);
      extraWrap = wrap;
    } else if (spec.type === "bool") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = !!currentValue;
      input.addEventListener("change", () => onChange(spec.name, input.checked));
    } else if (spec.type === "enum") {
      input = document.createElement("select");
      const blankOpt = document.createElement("option");
      blankOpt.value = "";
      blankOpt.textContent = "(default)";
      input.appendChild(blankOpt);
      (spec.enum_choices || []).forEach((choice) => {
        const opt = document.createElement("option");
        opt.value = choice.value;
        opt.textContent = choice.label;
        input.appendChild(opt);
      });
      input.value = currentValue || "";
      input.addEventListener("change", () => {
        onChange(spec.name, input.value || null);
        updateMissingState();
      });
    } else if (spec.type === "json") {
      input = document.createElement("textarea");
      input.value = currentValue !== undefined && currentValue !== null ? currentValue : "";
      input.addEventListener("change", () => {
        onChange(spec.name, input.value);
        updateMissingState();
      });
      input.addEventListener("input", updateMissingState);
    } else if (spec.type === "int_list" || spec.type === "float_list" || spec.type === "string_list") {
      input = document.createElement("input");
      input.type = "text";
      input.value = Array.isArray(currentValue) ? currentValue.join(",") : (currentValue || "");
      input.placeholder = "comma-separated";
      _attachSuggestDatalist(input, spec);
      input.addEventListener("change", () => {
        const parts = input.value.split(",").map((s) => s.trim()).filter((s) => s.length > 0);
        const parsed = spec.type === "string_list" ? parts : parts.map((p) => (spec.type === "int_list" ? parseInt(p, 10) : parseFloat(p)));
        onChange(spec.name, parsed);
        updateMissingState();
      });
      input.addEventListener("input", updateMissingState);
    } else {
      input = document.createElement("input");
      input.type = spec.type === "int" || spec.type === "float" ? "number" : "text";
      if (spec.type === "float") input.step = "any";
      if (spec.name === "labware_definition") {
        const group = LABWARE_DEFINITION_GROUP_BY_COMMAND[commandId] || "ALL";
        input.setAttribute("list", `labware-definitions-${group}`);
      }
      // "Inject Simulated Error" (see command_registry.py's simulate_error entry):
      // module/step/error stay free-text (so codegen keeps emitting plain strings
      // and the SDK's fuzzy keyword matcher still works) but get datalist
      // suggestions from /api/error-simulator-options -- same
      // suggestion-on-a-string-input approach as labware_definition above. step/
      // error start on the union ("-ALL") list and narrow to the chosen module's
      // list once one is picked (see the module "change" listener below), since
      // this form doesn't otherwise re-render on param change.
      if (commandId === "simulate_error") {
        if (spec.name === "module") {
          input.setAttribute("list", "error-sim-modules");
          input.dataset.paramName = "module";
          input.addEventListener("change", () => {
            const module = input.value || "ALL";
            container.querySelectorAll('[data-param-name="step"]').forEach((el) => {
              el.setAttribute("list", `error-sim-steps-${module}`);
            });
            container.querySelectorAll('[data-param-name="error"]').forEach((el) => {
              el.setAttribute("list", `error-sim-errors-${module}`);
            });
          });
        } else if (spec.name === "step") {
          input.setAttribute("list", `error-sim-steps-${values.module || "ALL"}`);
          input.dataset.paramName = "step";
        } else if (spec.name === "error") {
          input.setAttribute("list", `error-sim-errors-${values.module || "ALL"}`);
          input.dataset.paramName = "error";
        }
      } else if (commandId === "simulate_error_by_code" && spec.name === "firmware_command") {
        input.setAttribute("list", "error-sim-steps-ALL");
      }
      if (spec.profile_source) {
        const datalistId = _refreshProfileOptions(spec.profile_source, (profileNames || {})[spec.profile_source]);
        input.setAttribute("list", datalistId);
      }
      if (spec.name === "tip_pool" || spec.name.endsWith("_tip_pool")) {
        setTipPoolNames(_tipPoolDatalist.get()); // ensure the (possibly still-empty) datalist exists
        input.setAttribute("list", "tip-pool-options");
      }
      if (spec.name === "carrier_id" || spec.name === "carrier") {
        setCarrierNames(_carrierDatalist.get());
        input.setAttribute("list", "carrier-options");
      }
      if (spec.name === "labware_name" && commandId === "add_tubes_to_carrier") {
        // Add Tubes To Carrier's "labware_name" refers to an already-placed tube
        // carrier (a StarClient.add_tube_carrier() result), not a plate -- so it
        // needs the carrier datalist here, unlike every other "labware_name" field
        // below (get_labware_coordinates, shift_labware, ...) which do mean a plate.
        setCarrierNames(_carrierDatalist.get());
        input.setAttribute("list", "carrier-options");
      } else if (spec.name === "plate_id" || spec.name === "source_plate_id" || spec.name === "labware_name") {
        setPlateNames(_plateDatalist.get());
        input.setAttribute("list", "plate-options");
      }
      if (spec.name === "left_track") {
        setTrackNumbers(_trackDatalist.get());
        input.setAttribute("list", "track-options");
      }
      if (!input.hasAttribute("list")) _attachSuggestDatalist(input, spec);
      input.value = currentValue !== undefined && currentValue !== null ? currentValue : "";
      input.addEventListener("change", () => {
        let v = input.value;
        if (v === "") { onChange(spec.name, null); updateMissingState(); return; }
        if (spec.type === "int") v = parseInt(v, 10);
        if (spec.type === "float") v = parseFloat(v);
        onChange(spec.name, v);
        updateMissingState();
      });
      input.addEventListener("input", updateMissingState);
    }

    updateMissingState();

    if (spec.name === "positions" && input.tagName === "INPUT") {
      const wrap = document.createElement("div");
      wrap.className = "positions-input-wrap";
      wrap.appendChild(input);

      const buildBtn = document.createElement("button");
      buildBtn.type = "button";
      buildBtn.className = "btn btn-secondary";
      buildBtn.textContent = "Build...";
      buildBtn.addEventListener("click", () => {
        positionPicker.open(input.value, (result) => {
          input.value = result;
          onChange(spec.name, result);
          updateMissingState();
        });
      });
      wrap.appendChild(buildBtn);

      field.appendChild(wrap);
    } else if (spec.type === "file_path") {
      const wrap = document.createElement("div");
      wrap.className = "positions-input-wrap";
      wrap.appendChild(input);

      const browseBtn = document.createElement("button");
      browseBtn.type = "button";
      browseBtn.className = "btn btn-secondary";
      browseBtn.textContent = "Browse...";
      browseBtn.addEventListener("click", () => {
        fileBrowserModal.open(input.value, spec.file_filter, (result) => {
          input.value = result;
          onChange(spec.name, result);
          updateMissingState();
        });
      });
      wrap.appendChild(browseBtn);

      field.appendChild(wrap);
    } else if (extraWrap) {
      field.appendChild(extraWrap);
    } else {
      field.appendChild(input);
    }

    if (spec.name === "safety_bypass_token") {
      const warning = document.createElement("div");
      warning.className = "safety-bypass-warning";
      const title = document.createElement("strong");
      title.textContent = "WARNING: Collision Risk !!";
      const body = document.createElement("span");
      body.textContent =
        "Using this token waives vendor liability for any hardware damage or injuries resulting from collisions or misuse of this command";
      warning.appendChild(title);
      warning.appendChild(body);
      field.appendChild(warning);
    }

    container.appendChild(field);
  });
}
