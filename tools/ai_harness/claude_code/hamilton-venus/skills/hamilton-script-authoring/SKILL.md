---
name: hamilton-script-authoring
description: Write, check and try out Python scripts for a Hamilton STAR or Vantage with the hamilton_venus SDK (StarClient / VantageClient). Use whenever the user asks for a script, protocol, method or "a program that..." to run on the instrument; when turning steps done interactively in a session into a reusable script; when reviewing or fixing an existing script; when a script fails validation (rule ids V001-V027, W030-W037) or fails during a run; or when choosing which example script to start from.
---

# Writing Hamilton SDK scripts

A script is plain Python that opens a `StarClient` / `VantageClient`, builds the deck, and runs commands. Start from [template.py](template.py): it follows today's conventions and passes the spoke's validator. Copy it, then change the deck, volumes and steps.

## Shape of a script

1. **Docstring:** what the script does and the deck (track, carrier, site, labware name for each item).
2. **Constants at the top:** `SIMULATE`, volumes, liquid, tip pool names, heights. No magic numbers in the steps.
3. **`with StarClient(simulate=SIMULATE) as star:`** inside `try` / `except VenusError`. The `with` block starts VENUS, connects, writes the run log and closes cleanly. Don't call `instrument_connect` yourself unless you passed `auto_connect=False`.
4. **Deck:** carriers first (`add_carrier(..., labware_id="TipCarrier")`), then labware on them with your own names (`plate_id=`, `labware_id=`, `tip_pool=`). Or load a saved layout with `StarClient(deck_name=...)`.
5. **Tip counters** in the script itself, after the last tip rack: `if star.simulate:` reset, `else:` show the tip counters (see the template). Never rely on a counter reset in an earlier session. Nested tip racks: `add_ntr(..., stack=N)`, after asking the user whether they have single racks or stacks. See `hamilton-tip-counter-setup`.
6. **Liquid class:** ask the user what the liquid is when they haven't said (aqueous buffer, viscous, foaming, volatile, ...), then call `find_liquid_classes(liquid, dispense_mode=..., volume=..., tip_pool=...)` in the script and use `candidates[0].name`. Never hard-code a class name. Judge a candidate by its `summary` (device, tip type, volume range, liquid, mode) and its aspirate / dispense numbers (flow rate, blow-out, air transport ...), never by its name: `1000ul` in a 96-head class name is the head, not the tip. `liquid_match: fallback` is about the liquid, not the tip. The 96 head's dispense uses the class it aspirated with.
7. **Steps:** `tip_pickup` → `aspirate` → `dispense` → `tip_eject`, with `tip_eject` in `finally` so a failed step doesn't leave tips on, except after a VENUS abort (below). Or a compound command (`add_reagent`, `replicate_samples`, `serial_dilution_by_volume`, ...) when it fits the job.
   **A VENUS abort cannot be cleaned up after.** When the operator aborts from the VENUS error dialog, the command raises `VenusCommandAbortedError` and the SDK has already stopped the client. A `finally: tip_eject()` then raises `RuntimeError("Client is not started...")`, hides the abort, and the tips stay on the channels (remove them by hand or at the next initialization). There is no supported way to eject after an abort. Don't call the client in `finally` once it was aborted: set a flag in `except VenusCommandAbortedError` and skip the eject (the template does this). Tell the user the tips are still on.
8. **`print`** progress lines: they show up in `get_run_events` as `stdout`.

**Settings, always.** Every aspirate and dispense gets a settings object built at the top for this liquid and labware, passed as `settings=`: `AspirateSettings` / `DispenseSettings` for the channels, `MPH96AspirateSettings` / `MPH96DispenseSettings` for the 96 head. The defaults (LLD off, 5 mm fixed height, no mixing) are a placeholder, not a choice. Decide and state:
- **Aspirate from a trough or any container whose level isn't known: cLLD** (`capacitive_lld=CapacitiveLLD.MAX`, or the level the liquid needs) with a `submerge_depth` and `liquid_following=True`. An unknown volume is not a reason to skip LLD: the level found tells you the volume after the aspiration.
- **Liquid following needs LLD.** With LLD off the tip starts at `fixed_height` and follows further down from there, into the bottom, and VENUS stops with an insufficient liquid level error (validator W037). A fixed height is only for a known level where cLLD can't work (non-conductive or foaming liquid), and then with `liquid_following=False`.
- **Dispense:** jet into empty wells from above the liquid, or surface dispense at a fixed height for small volumes or wells that already hold liquid. `DispenseMode.FROM_LIQUID_CLASS` unless a drain-tip dispense is needed.
- **Mixing** after the dispense when the reagent must be mixed in.

Tell the user which liquid class and settings you chose and why. The validator warns (W036) on an aspirate or dispense without `settings=`.

**96 head (MPH96):** the source must be an SBS trough for the head (`HAM_DW_RGT_96`, ...) on a plate carrier, which it can share with the plates; the 60 mL troughs are channels only. See `hamilton-labware-compatibility` (rules 5 and 6).

## Pre-flight checklist

Before handing over or running a script, check:

- [ ] Carriers and labware fit together and stay under 145 mm (`hamilton-labware-compatibility`).
- [ ] Every command in order, volumes within tip capacity, channel and position counts match (`hamilton-liquid-handling-rules`).
- [ ] Tip counters reset (simulation) or shown (instrument) in the script, after the last tip rack (W035).
- [ ] Every aspirate and dispense has settings chosen for the liquid and labware (W036); liquid following only with LLD on (W037).
- [ ] Labware that fits one carrier shares it; 96 / 384 head sources are SBS troughs on a plate carrier.
- [ ] Liquid class picked for this instrument's device, tip and volume (`hamilton-liquid-class-optimization`).
- [ ] Deep wells or tubes: `check_tip_reach(labware, tip_pool=..., height_from_bottom=...)` says the tip is long enough.
- [ ] Every labware name used in a step was added (validator warning W030 otherwise).
- [ ] `SIMULATE = True` unless the user asked for the instrument; never hard-code `simulate=False` (W033).

## Scripts run by the MCP spoke are headless

`run_script` runs the script on the spoke with nobody at its console, so the validator refuses:

- **GUI or console input:** `tkinter`, `input()` (V012). For live tip counters use `tip_pool_show_tip_counters`: VENUS shows its own dialog on the instrument PC.
- **Unsafe modules and calls:** `subprocess`, `socket`, `requests`, `eval`/`exec`, deleting files, ... (V010, V011).

A script meant only for the Script Manager may use dialogs. Say so in its docstring, and don't send it to `run_script`.

## Try it out (MCP tools)

1. **Store and validate:** `import_script(name="my_protocol.py", content=...)`. Fix each error by its rule id and line, then import again with `overwrite=True` until `runnable` is true.
2. **Free the instrument:** `run_script` refuses while an interactive session is open, so `close_session()` first.
3. **Simulate:** `run_script("my_protocol.py", simulate=True)`, then follow it with `get_run_events(run_id, since_seq=..., wait_s=20)` until `run_finished`. A `prompt` event needs a person: tell the user, don't resolve it yourself.
4. **Review:** `get_run_summary(run_id)` gives failed steps with their script line, instrument errors, tips used and volumes drawn. Fix and repeat.
5. **Live:** `simulate=False` only when the user asks for the real instrument, and only once it has run clean in simulation.

`validate_script(name)` re-checks a stored script; `get_script(name)` returns its text.

## Where to look for more

- [reference/example_scripts.md](reference/example_scripts.md): what each script in the SDK's `example_scripts/` folder shows. Read the closest one before writing something new.
- SDK docs through `list_sdk_docs` / `read_sdk_doc`: `examples/liquid_handling.md`, `examples/compound-commands/*`, `examples/position_and_well_selection.md`, `error_handling.md`, `examples/advanced/run_log.md`.
- `describe_sdk_command(name)` for any command's exact parameters.
