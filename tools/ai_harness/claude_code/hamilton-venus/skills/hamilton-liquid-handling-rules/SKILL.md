---
name: hamilton-liquid-handling-rules
description: Operational rules for writing or reviewing Hamilton STAR / Vantage liquid handling scripts with the hamilton_venus SDK (StarClient / VantageClient), so command sequences don't fail at runtime. Use when generating, editing or reviewing a pipetting script; when ordering tip pickup → aspirate → dispense → tip eject; when checking volumes against tip capacity, position counts against channel counts, MPH96 patterns, liquid class vs tip type, tip pool setup or deck layout before use; when choosing plate transport hardware (CO-RE Grips, QCG, iSWAP, IPG) or holding a lid while pipetting; or when diagnosing errors such as "no tips loaded", "volume exceeds capacity", "labware not found" or "position mismatch".
---

# Hamilton liquid handling rules

The full rule set, with valid/invalid examples for each rule, is [reference/liquid-handling-rules.md](reference/liquid-handling-rules.md) (v1.1, 2026-09-29).

**Core principle:** VENUS and the SDK execute commands as issued. They don't track tip or liquid state or validate sequences for you, so the script must.

## The rules

| # | Rule | Violation |
|---|---|---|
| 1 | Tip pickup before aspirate / dispense (1 mL, 5 mL, MagPip, MPH96) | no tips loaded |
| 2 | Aspirate before dispense; total dispensed ≤ aspirated | no liquid / liquid class |
| 3 | Eject only loaded tips (no eject without pickup, no double eject) | no tips to eject |
| 4 | Volume ≤ tip capacity (50 / 300 / 1000 / 5000 µL); no auto-splitting. The tip must also be long enough for the container: its `length_below_channel` (tip length − collar depth, 51.9 mm for a 300 µL tip) must cover how deep it pipettes, or the channel itself goes inside the well/tube and can touch the wall -- check with `check_tip_reach` | volume exceeds capacity; contamination warning |
| 5 | `liquid_class` on every aspirate (dispense uses the aspirate's) | missing parameter |
| 6 | Don't mix channel types in one command | invalid channel configuration |
| 7 | Position count = channel count | position mismatch |
| 8 | Same MPH96 pattern across pickup, aspirate, dispense, eject | wrong wells |
| 9 | Add labware to the deck before referencing it | labware not found |
| 10 | Tip pools set up before use, and their counters reset (simulation) or confirmed with the user (live) after the last rack is added -- see `hamilton-tip-counter-setup` | tip pool not found; "Rack transport is not possible" |
| 11 | Liquid class matches a fitted device, the tip type loaded, the dispense mode and the liquid -- pick it with `find_liquid_classes`, never by name | `LiquidClassMismatchError`; inaccurate volumes / rejection |
| 12 | Transport: on-deck moves use the CO-RE grips (CO-RE Grips on Legacy channels, QCG on Fluid Motion / Vantage) whenever fitted; iSWAP / IPG only for off-deck or extended reach, rotations, no CO-RE grips, or when asked -- see "Choosing transport" below | collision; hardware can't perform it |

## Choosing transport

Don't use the iSWAP just because it's fitted. It grips from the side: a narrow grip (`grip_width` under 100 mm) needs room left and right of the labware, a wide grip needs room in front and behind, and adjacent labware taller than the target can collide with it. The CO-RE grips come straight down, so they reach into stackers and low labware between tall carriers with no clearance needed.

1. **iSWAP / IPG** for off-deck or extended-reach moves (incubators, readers, hotels), rotations, when the instrument has no CO-RE grips, or when the user asks. Check side clearance first. `iswap_park()` after the series of moves.
2. **CO-RE grips** for every other on-deck move. Legacy STAR channels use CO-RE Grips (`add_1ml_core_grip()`); Fluid Motion channels and the Vantage use the QCG (`add_qcg()`); `channels_1_ml.type` tells which.
   - The grips are a separate tool, **not** in the instrument configuration: `gripper.type` only reports the iSWAP / IPG arm device. Systems may or may not have CO-RE grips, so a configuration showing only an iSWAP doesn't mean there are none.
   - If the deck doesn't already have the grip tool (`get_transport_tool_ids()`), ask the user whether the system has CO-RE grips.
   - "The system has CO-RE grips" means they are physically fitted, **not** that they are in the layout. A blank or newly built layout has no grip tool until it is added: when the user says the system has them, check `get_transport_tool_ids()` and add them (`add_1ml_core_grip()` / `add_qcg()`) as part of building the layout. Never report them as set up without that check.
   - Eject tips first: the grips use the 1 mL channels (2 for CO-RE Grips, 4 for the QCG).
   - Keep the grips on for consecutive moves (`core_transport(..., eject_grip=False)`), and eject them after the last (`eject_grip=True`, or `core_eject_grips()`).
3. **Holding a lid** while pipetting:
   - CO-RE Grips (`core_hold_lid`) or the iSWAP can hold a lid while the **MPH** pipettes the plate.
   - Neither works for **channel** pipetting, except an iSWAP on a second arm (Vantage only).

Full detail and examples: the reference's Rule 12.

Checklist for generated code (from the reference's "For LLM Code Generators"):
- Validate rules 1–12 against the planned sequence.
- When system state is assumed, say so in a comment.
- Wrap tip use in `try` / `finally` so tips are ejected after a failure. Not after a VENUS abort: `VenusCommandAbortedError` means the operator aborted from the VENUS error dialog and the SDK has already stopped the client, so any command in `finally` fails with "Client is not started" and masks the abort. Skip the eject in that case (see `hamilton-script-authoring`) and tell the user the tips are still on the channels.

## API notes: write code against the current SDK

The reference's examples predate some SDK names and use a schematic position syntax. Use the current API (checked 2026-10-06):

| Reference shows | Current SDK |
|---|---|
| `tip_rack["A1:H1"]`, `plate["A1"]` | position selector strings: `"TipRack_1@A1:H1"`, `"Plate_1@A1"`, `"Plate_1@col:1"`, `"Plate_1@all"`, or `Position` objects |
| `iswap_get(...)` / `iswap_place(...)` | `iswap_get_labware(...)` / `iswap_put_labware(...)`, or one-call `iswap_transport(labware_name, carrier, site, grip_height_above_bottom, ...)` (on a Vantage these drive the IPG) |
| `core_gripper_get(...)` / `core_gripper_place(...)` | `core_transport(...)`, `core_transport_return_plate(...)`, `core_hold_lid(...)`, `core_eject_grips()`; add the tool first (`add_1ml_core_grip()` / `add_qcg()`) |
| `create_tip_pool(...)` | none; `add_tip_rack(..., tip_pool="Name")` creates or extends the pool |
| `initialize_tip_pool(...)` | `tip_pool_initialize_tip_counter("Name")` (also `tip_pool_reset_tip_counter`, `tip_pool_show_tip_counters`) |
| `tip_check().tips_loaded[i]` | `tip_check().return_parameters.active_channels` |
| liquid class names like `Water_50ulTip_Surface`, `tip_type=1` for 1 mL | real names such as `StandardVolume_Water_DispenseJet_Empty` (use `hamilton_venus.catalog.LIQUID_CLASSES` or `get_liquid_classes`); tip type IDs: 1000 µL = 4, 300 µL = 0 |

When unsure of a name or signature, check `src/hamilton_venus/mixins/` or `docs/star_commands.md` / `docs/vantage_commands.md` rather than the reference's examples.

Related skills: `hamilton-liquid-class-optimization` (choosing and tuning the liquid class for rule 11), `hamilton-labware-compatibility` (which carrier for rule 9's deck layout), `hamilton-tip-counter-setup` (resetting or showing tip counters for rule 10) and `hamilton-script-authoring` (template, pre-flight checklist and try-out loop for whole scripts).
