# Hamilton VENUS Liquid Class & Pipetting Reference (Agentic Method Generation)

## Document set

This guide is one of several kept as **separate files by responsibility**, not merged into one document:

| File | Role |
|---|---|
| `hamilton-liquid-handling-optimization-guide.md` (this file) | Decision heuristics: liquid → class/tip/settings, parameter directionality, recipes |
| `JSON_Liquid-Class-Model_sdk.md` | Liquid class JSON structure/field meanings |
| `JSON_Liquid-Class-Reference-Values.md` | Enums (tip types, dispense modes, devices) and numeric min/max bounds per device |
| SDK command reference / error-handling docs | How to call the SDK, what errors mean |

## How to use this reference when generating a method

1. Classify the liquid (aqueous / volatile organic solvent / involatile organic solvent / viscous / blood product) and note what's known about it: viscosity, volatility, surface tension/adhesion behavior.
2. Use **Section 1** to pick a channel, tip, dispense mode, and a starting predefined liquid class.
3. Use **Section 3** for the per-step method settings (LLD, ADC, fixed height, tip reuse, etc.) that go with that choice.
4. Use **Section 4** to set or adjust liquid class parameters, using the directional rules and example values as sanity bounds/defaults.
5. If the method needs trueness verification, drive the integrated balance via the SDK and apply **Section 5**'s formula to update the correction curve (Section 6 covers the gravimetric workflow and its caveats).
6. For known patterns — low volume, multi-dispense/aliquot, serial dilution — start from the recipes in **Section 8** rather than deriving settings from first principles.
7. Use **Section 9** to decide whether to enable MAD or TADM on the transfer for runtime error detection (clots, air aspiration, foam) independent of trueness verification.

---

## 1. Quick Decision Reference

### 1.1 Channel & tip selection

Pick a tip so the target transfer volume falls at roughly **5–100% of the tip's rated capacity** — below 5%, trueness/precision degrade sharply (see Section 2 tables for exact numbers).

Decision order:
1. Dispense > 300 µL → use **1000 µL tips** (or 5 mL channel/tips if > 1000 µL, or the 1000 µL CO-RE 96-Probe Head if the same volume goes to every well of a plate simultaneously).
2. Dispense < 15 µL → use **50 µL or 10 µL tips** (or the 50 µL CO-RE 384-Probe Head for high-throughput low-volume work).
3. Otherwise (15–300 µL range):
   - If multi-dispensing and dispense ≥ 50 µL, or aspirate > 300 µL → reconsider larger tips (1000 µL).
   - Default → **300 µL tips**.

### 1.2 Dispense mode selection

1. Need to mix after dispense? → **Surface Empty Tip**.
2. Low dispense volume (<5% of tip volume)? → **Surface Empty Tip**.
3. Precision is important?
   - Not multi-dispensing → **Jet Empty Tip**.
   - Multi-dispensing → **Jet Part Volume**.
4. Precision not critical:
   - Not multi-dispensing → **Surface Empty Tip**.
   - Multi-dispensing → **Surface Part Volume**.

Notes: Jet keeps the tip out of existing well liquid but is ineffective on high-viscosity liquids — use Surface for those regardless of the tree above. Surface is required for all volumes ≤20 µL. The schema also defines a `whipip` dispense mode, specific to MagPip channels — see Section 3 for what it does and when to use it instead of standard Jet/Surface modes.

### 1.3 Multi-dispense go/no-go

Prefer a **single aspirate/dispense** instead of multi-dispense if any of the following are true: Anti-Droplet Control is required, the liquid is volatile, or precision is critical AND (the target container isn't empty, or you aren't dispensing in surface mode, or pre-/post-dispense volume margin is insufficient). Otherwise multi-dispense is viable — see Section 8.2 for the settings recipe.

### 1.4 Liquid property → parameter cheat sheet

| Property | Condition | Adjust | Direction |
|---|---|---|---|
| Viscosity | High (e.g. glycerin, plasma) | Flow rate | Slower (fast aspirate causes suction that keeps fluid out, under-filling) |
| Viscosity | High | Dispense mode | Surface only — jet is ineffective |
| Viscosity | Low (e.g. water, hexane) | Flow rate | Faster |
| Adhesion | Low (liquid releases easily) | Blowout volume | Decrease |
| Adhesion | High (sticky liquid) | Blowout volume | Increase |
| Cohesion | Low (liquid separates from itself) | Air transport volume | Increase (protects against drips) |
| Cohesion | High | Air transport volume | Decrease; may need larger blowout volume |
| Capillary action | High at low volumes (e.g. water in 10/50 µL tips) | — | Caution only: more liquid than intended can be aspirated; verify precision empirically |
| Surface tension | Low (e.g. ethanol) | Air transport volume, Settling time | Increase air transport; decrease settling time |
| Surface tension | High (e.g. glycerin) | Air transport volume, Swap speed | Decrease air transport; use high swap speed; consider side touch |
| Contact angle | Low (spreads thin) | Aspirate/dispense position | Use bottom touch-off; caution at low volumes |
| Contact angle | High (liquid beads up) | Aspirate/dispense position | Ensure proper tip entry; consider side touch on dispense |
| Vapor pressure / volatility | High (e.g. acetone, methanol, ethanol) | ADC, blowout volume, pre-wet | Enable Anti-Droplet Control; larger blowout volume; pre-wet tip |
| Vapor pressure / volatility | Low | — | No special adjustment needed |

Liquid classes are conditions-specific: if a class was developed at a materially different temperature, elevation, or humidity than the current run environment, flag it for re-verification rather than trusting stored parameters blindly.

These directional rules were derived from 1000 µL/5 mL/300 µL channel behavior and aren't validated for MagPip channels — for MagPip, rely on its own hardware specs (Section 2), its default WhiPip settings (Section 3), and closed-loop empirical tuning (Section 6) instead of extrapolating this table to it.

---

## 2. Hardware & Tip Specifications

### 2.1 Channel Types & Volume Ranges

| Channel type | Nominal volume | Volume range | Max per robot |
|---|---|---|---|
| 1000 µL Standard Channel | 1000 µL | 0.5–1000 µL | 16× |
| 5 mL Standard Channel | 5 mL | 50–5000 µL | 8× |
| 1000 µL X1 Channel | 1000 µL | 0.5–1000 µL | 16× |
| 750 µL MagPip Channel | 750 µL | 350 nL – 750 µL | 8× |
| 1000 µL CO-RE 96-Probe Head | 1000 µL max/channel | 1–1000 µL | 96 channels, simultaneous |
| 50 µL CO-RE 384-Probe Head | 50 µL max/channel | 0.5–50 µL (up to 300 µL with Rocket Tips, acting as a 96-channel head) | 384 channels, simultaneous |

**Feature availability by pipetting tool:**

| Feature | MagPip | 1000 µL X1 | 1000 µL | 5 mL | CO-RE 96 | CO-RE 384 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| cLLD | ✓ | ✓ | ✓ | ✓ | ✓ ¹ | ✓ ² |
| pLLD | ✓ | ✓ | ✓ | ✓ | | |
| MAD | | ✓ | ✓ | ✓ | | |
| Capacitance-Based Clot Detection | | ✓ | ✓ | ✓ | | |
| ADC | ✓ | ✓ | ✓ | ✓ | | |
| TADM ³ | ✓ | ✓ | ✓ | ✓ | ✓ ⁴ | |

¹ CO-RE 96 Probe Head: cLLD only on channels A1 and H12, not the full head.
² CO-RE 384 Probe Head: cLLD only on channels A5 and P24, not the full head.
³ Requires the VENUS TADM feature/license.
⁴ Only on the CO-RE 96 head hardware variant built with 96 independent per-channel pressure sensors. There are two CO-RE 96 head variants — with and without TADM hardware; both have identical cLLD detection (footnote 1), so TADM support depends on which physical head is installed, not on cLLD availability. Confirm which variant is on the target robot before assuming TADM is available on a CO-RE 96 method.

This confirms ADC **is** available on MagPip channels (resolving the earlier "unconfirmed" flag) and that capacitance-based clot detection is not available on MagPip despite MagPip having cLLD.

Valid `pipettingDevice` / `tipType` identifiers, and the exact numeric bounds for every liquid class parameter by device, are enumerated in `JSON_Liquid-Class-Reference-Values.md` — treat that file as canonical (it's generated from SDK source) and this section as the reasoning layer on top of it, not a substitute.

### 2.2 Trueness (|R|%) / Precision (CV%) by Tip Size — Individual 1000 µL Channels

| Tip size | Volume | Trueness | Precision |
|---|---|---|---|
| 10 µL | 0.5 µL | 10.0% | 6.0% |
| 10 µL | 1 µL | 5.0% | 4.0% |
| 10 µL | 5 µL | 2.5% | 1.5% |
| 10 µL | 10 µL | 1.5% | 1.0% |
| 50 µL | 0.5 µL | 10.0% | 6.0% |
| 50 µL | 1 µL | 5.0% | 4.0% |
| 50 µL | 5 µL | 2.5% | 1.5% |
| 50 µL | 50 µL | 2.0% | 0.75% |
| 300 µL | 10 µL | 5.0% | 2.0% |
| 300 µL | 50 µL | 2.0% | 0.75% |
| 300 µL | 200 µL | 1.0% | 0.75% |
| 1000 µL | 10 µL | 7.5% | 3.5% |
| 1000 µL | 100 µL | 2.0% | 0.75% |
| 1000 µL | 1000 µL | 1.0% | 0.75% |

**5 mL channel**: 50 µL→5.0%/2.5%, 500 µL→2.0%/1.5%, 1000 µL→1.5%/1.0%, 5000 µL→1.0%/0.5% (trueness/precision).

**1000 µL CO-RE 96-Probe Head**: similar shape, slightly wider at low volumes (e.g. 10 µL tip/1 µL: 5.0%/5.0%).

**50 µL CO-RE 384-Probe Head (precision CV%)**: Surface 0.1 µL→8.0%, Surface 0.5 µL→6.0%, Surface 1 µL→3.5%, Jet 1 µL→15.0%, Surface 5 µL→3.0%, Jet 5 µL→4.0%, Surface 10 µL→2.0%, Jet 10 µL→3.0%, Surface/Jet 50 µL→2.0%. As a 96-head with 300 µL Rocket Tips: 2 µL→4.0%, 5–300 µL→2.0%.

**MagPip Pipetting Specifications** (accuracy/precision % by tip size and volume):

| Tip size | Volume (µL) | Accuracy (%) | Precision CV (%) |
|---|---|---|---|
| 10 µL | 0.35 | 5 | 5 |
| 10 µL | 1 | 3 | 3.75 |
| 10 µL | 5 | 2 | 1.75 |
| 10 µL | 10 | 1 | 1 |
| 50 µL | 0.5 | 5 | 5 |
| 50 µL | 5 | 2 | 1.75 |
| 50 µL | 10 | 1 | 1 |
| 50 µL | 50 | 2.0 | 0.75 |
| 300 µL | 1 | 3 | 3.75 |
| 300 µL | 100 | 1.25 | 1.75 |
| 300 µL | 300 | 1 | 1.75 |
| 1000 µL | 100 | 1.25 | 1.75 |
| 1000 µL | 750 | 1 | 0.75 |

Treat all tables in this section as best-case reference values — real performance depends on liquid type, lab conditions, and the specific liquid class in use. Use them as sanity bounds when a method's measured precision looks implausibly good or bad for the tip/volume combination.

### 2.3 Tip ↔ Channel Compatibility

Which tip sizes a given channel/head can physically use:

| Tip size | 1000 µL Channel | 5 mL Channel | 1000 µL X1 | MagPip | CO-RE 96 | CO-RE 384 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 10 µL | ✓ | | ✓ | ✓ | ✓ | |
| 50 µL | ✓ | | ✓ | ✓ | ✓ | |
| 50 µL (384) | | | | | | ✓ |
| 300 µL | ✓ | | ✓ | ✓ | ✓ | |
| 1000 µL | ✓ | | ✓ | ✓ | ✓ | |
| 5 mL | | ✓ | | | | |

Notably, MagPip (750 µL nominal channel) is compatible with 10/50/300/1000 µL tips, not just a dedicated MagPip-specific tip — the tip caps the achievable max volume, but MagPip's plunger can still address its full 350 nL–750 µL range through a compatible tip. Confirm the exact `tipType` enum values valid per device in `JSON_Liquid-Class-Reference-Values.md`.

### 2.4 Tip Selection Factors

- **Material**: black plastic (conductive — required for cLLD) vs. clear plastic (non-conductive) vs. reusable steel needles (require wash cycles between uses; factor into carryover assumptions).
- **Filtered**: use for volatile liquids or when carryover/cross-contamination is a concern. Filtered tips can slightly affect flow and max correction volume (extra physical barrier) but still pipette their full rated volume, except 5 mL tips.
- **Wide bore**: use for viscous liquids, liquids containing cells, or liquids containing clots — larger orifice, but reduced max volume and shorter tip. Prefer wide bore over shrinking the volume-to-capacity ratio when clot/cell risk is present. The schema exposes specific orifice sizes as distinct tip types (e.g. `tip_300ul_wide_bore_0p71mm` vs. `tip_300ul_wide_bore_1p55mm`) — pick the smallest orifice that still clears the expected clot/cell size, not the largest available.
- **Piercing tips** (e.g. `tip_250ul_piercing`, `tip_150ul_filter_piercing`) exist in the schema for penetrating a sealed labware foil/septum — not covered in the source Reference Guide at all. Use these only when the method explicitly targets sealed labware; they aren't a substitute for a normal tip on open labware.
- **Legacy tip and dispense-mode values** (anything prefixed `old_` in the schema, e.g. `old_needle_50ul`, `old_jet`, `old_surface`) are for predefined/historical liquid classes only — never select these when generating a **new** custom liquid class.
- The full tip type enum (including slim and clear variants, 384-head-specific tips, and the Rocket Tip) and its exact `volumeRange.max` per type are in `JSON_Liquid-Class-Reference-Values.md` — this section covers selection logic, that file has the authoritative identifier list.

---

## 3. Method Settings (per aspirate/dispense step)

These are set per transfer step in the method, as opposed to liquid class parameters (Section 4), which travel with the liquid class across methods.

- **Aspiration mode**: `Aspiration` (default, first aspirate in a cycle) / `Consecutive Aspiration` (repeated aspirates with the same tip before dispensing — no blowout volume aspirated on these steps; time-saving but harder to tune) / `Aspirate All` (aspirates entire available volume without volume-insufficient errors, following the falling liquid level to the container bottom; monitoring and volume estimation are disabled — use when requested volume may exceed what's present, or to combine LLD height-following with tolerance for a false insufficient-volume reading).
- **Liquid Level Detection (LLD)**: `cLLD` (capacitive — requires conductive liquid + conductive tip; needs a minimum liquid volume to signal reliably, e.g. ~30 µL in a 384-well plate; cannot detect involatile organic solvents; usable on dispense; tip reuse OK) vs. `pLLD` (pressure-based — broader liquid compatibility but requires sufficient resistance; **always use unused/dry tips** — residual liquid degrades low-volume precision). If neither is reliable (e.g. insufficient liquid volume), use **fixed height** instead. Combining cLLD+pLLD can flag foam if the two readings diverge beyond a threshold. In the schema this is `detection.lld.pressureSensitivity` (numeric sensitivity setting) and `lldMaxHeightDifference` (the foam-detection threshold) — neither has a documented valid range in `JSON_Liquid-Class-Reference-Values.md`, so treat these as needing empirical tuning/testing rather than a known-good default.
- **Fixed height**: required when LLD can't work reliably; minimizes dead volume and improves speed. Optional sub-settings: `Touch Off` (finds the container bottom mechanically before rising to a set height — compensates for labware warping) and `Side Touch` (dispenses at the container wall — helps with liquids prone to residual droplets/foam).
- **Anti-Droplet Control (ADC)**: enable for volatile, low-viscosity, high-vapor-pressure liquids (acetone, methanol). When enabled, also set: air transport volume ≈ 0, stop back volume < 10 µL, swap speed low (~2 mm/s). Do **not** enable if the liquid has low vapor pressure or the tip will be reused multiple times (e.g. multi-dispense) — can introduce precision errors. Available on 1000 µL, 1000 µL X1, 5 mL, and MagPip channels — not available on CO-RE 96/384 Multi-Probe Heads (see the feature table in Section 2.1).
- **Tip reuse**: default to single-use tips (new tip per transfer) to avoid carryover. Reuse only when carryover is not a concern; a reused tip carries slightly more residual volume than intended.
- **Pre-wetting**: aspirate-then-immediately-dispense mixing step that saturates vapor pressure and reduces drop formation; also useful before serial dilution transfers. May interfere with pLLD (residual liquid), transfers slightly more volume than intended, and typically needs its own correction curve (different from an unused tip).
- **Liquid following**: tip tracks the liquid level (down on aspirate, up on dispense) based on volume and known container geometry — reduces submersion depth and carryover. Turn **off** for low-volume 1000 µL-channel transfers (Section 8.1).
- **Minimize z-move**: uses a lower traverse height on dispense to speed up multi-dispense sequences. Verify no taller labware sits between the start/end positions, or a collision can occur.
- **Dispense on the fly**: tip stays at fixed height and dispenses while moving continuously in x — fastest option for multi-dispense but harder to tune (x-speed and x-offset must both match the dispensed volume; start the dispense at the beginning of the well).
- **WhiPip dispense** (`whipip` in the schema, MagPip channels only): a contact-free jet-dispense technique purpose-built for sub-µL volumes, down to 350 nL. The plunger accelerates downward to impulse the liquid out of the tip orifice, then immediately reverses direction to shear the liquid sphere off the tip — this can repeat immediately for fast repeated aliquoting without touching the target surface. Use `whipip` when: the channel is MagPip, the target volume is well under 1 µL (or otherwise near the low end of MagPip's 350 nL–750 µL range), and contact-free/fast-repeat dispensing is wanted.

  In the JSON, a `whipip` liquid class carries its normal `aspirate`/`dispense`/`correction` blocks *plus* a `whiPipJson` object under `pipettingProperties` — a dense, versioned calibration payload (general metadata like density/tip/template, the capture conditions it was calibrated under, and a `software_data` block of raw plunger motion-curve arrays per volume point, e.g. acceleration/amplitude/deceleration/plateau timing, plus a separate hydrostatic pressure-vs-volume curve). This is calibration output, not a hand-tunable parameter set: **treat `whiPipJson` as opaque**. Don't attempt to derive or hand-author its contents, and don't apply Section 4's directional rules to it — those govern the standard aspirate/dispense fields, not this block. When generating or cloning a WhiPip liquid class programmatically, the practical rule is: copy `whiPipJson` verbatim from a validated predefined/reference class for that liquid+tip combination, and never let a round-trip (read → modify an unrelated field like a correction point → write) silently drop or corrupt it. New WhiPip calibration data comes from Hamilton's own calibration tooling, not from this SDK's method-generation logic.

---

## 4. Liquid Class Parameters

| Parameter | JSON field | Definition | Aspirate | Dispense |
|---|---|---|:---:|:---:|
| Flow rate | `flowRate` | Plunger-speed-driven liquid flow, µL/s | ✓ | ✓ |
| Mix flow rate | `mixFlowRate` | Flow rate used during mixing, µL/s | ✓ | ✓ |
| Air transport volume | `airTransportVolume` | Air aspirated at end of aspirate/dispense step | ✓ | ✓ |
| Blowout volume | `blowOutVolume` | Air aspirated first during aspirate; dispensed (part/all) on empty-tip dispense | ✓ | ✓ |
| Swap speed | `swapSpeed` | Speed (mm/s) the head moves out of the liquid | ✓ | ✓ |
| Settling time | `settlingTime` | Time (s) the head stays in the liquid after aspirate/dispense | ✓ | ✓ |
| Over-aspirate volume | `overAspirateVolume` | Extra volume aspirated then immediately dispensed back | ✓ | — |
| Clot retract height | `clotRetractHeight` | Max height (mm) head can move out of liquid while a liquid-detect signal persists, before flagging a clot | ✓ | — |
| Stop flow rate | `stopFlowRate` | Flow rate at which dispense terminates abruptly | — | ✓ |
| Stop back volume | `stopBackVolume` | Volume re-aspirated immediately after dispense | — | ✓ |

Exact numeric min/max bounds per device (`channels_1000ul`, `channels_5ml`, `channels_magpip`, `head_96`, `head_384`) are in `JSON_Liquid-Class-Reference-Values.md` under "Parameter Ranges by Device" — that table is generated from SDK source and is the authoritative validation reference. The directional rules in Section 4.1 and example values in Section 4.2 tell you *which way* to move a value; the reference-values table tells you the *legal range* to clip it to before writing the JSON. Note the ranges vary substantially by device — e.g. `flowRate` is 1–500 µL/s on `channels_1000ul` but 0.1–10,000 µL/s on `channels_magpip` — so a value that's reasonable for one device can be out of range or absurdly conservative for another.

**Availability by mode**: `Aspirate All` disables mix flow rate (no mix step applies when the entire container is aspirated). `Consecutive Aspiration` disables blowout volume for that step. On dispense, `Stop Flow Rate` and `Stop Back Volume` are only meaningful/editable in modes with a defined stop behavior (jet part volume in particular). When generating a method, only set parameters that are valid for the selected aspirate/dispense mode combination — setting an inapplicable parameter should be treated as a validation error, not silently ignored.

### 4.1 Directional Best Practices

- **Flow rate** (influenced by tip geometry, viscosity, density, vapor pressure): slower for smaller tip diameters and high-viscosity liquids; faster for volatile liquids. On dispense, also slower for surface dispense, faster for jet dispense.
- **Mix flow rate**: same directional logic as flow rate, applied to mixing.
- **Air transport volume** (tip geometry, vapor pressure): keep less than the liquid volume; use only what's needed — too little or too much can cause tip leaks. Small for smaller tips; large for volatile liquids. Caution: surface dispense + air transport volume can cause bubbles.
- **Blowout volume** (viscosity, vapor pressure): aspirate value ≥ dispense value; higher on aspirate for volatile liquids. Small for surface dispense; large for jet dispense and high-viscosity liquids. Caution: too much in jet mode can aerosolize liquid (contamination risk); in surface mode can create bubbles/foam.
- **Swap speed** (viscosity, vapor pressure): slow for high-viscosity liquids; fast for volatile liquids.
- **Settling time** (tip geometry, viscosity): short for aqueous and highly volatile liquids (keep very short specifically for volatiles); long for viscous liquids and surface-dispense-into-empty-container.
- **Over-aspirate volume** (viscosity, vapor pressure; aspirate only): useful at low volumes as pre-conditioning against capillary effect; set lower than the aspirate volume; small/zero for dilution steps; large for high-viscosity and volatile liquids.
- **Clot retract height**: affects clot-detection error generation only, not the transfer itself.
- **Stop flow rate** (viscosity; dispense only): ≤ dispense flow rate; slower than dispense flow rate for surface dispense; ≈ dispense flow rate for jet dispense (especially multi-dispense).
- **Stop back volume** (viscosity; dispense only): acts as an air-transport buffer between transfers in jet-part-volume mode to prevent post-dispense droplets. Caution: if dispense height is too low, dispensed liquid could be re-aspirated instead of air.

### 4.2 Example Default Parameter Values (1000 µL channels)

General rules observed across Hamilton's default liquid classes — use these to sanity-check generated values:
- Larger tip sizes → faster aspirate flow rates, larger air transport volumes, larger blowout volumes.
- More viscous liquid → slower aspirate flow rate, larger blowout volume.
- More volatile liquid → larger air transport volume, faster aspirate flow rate.
- Jet Empty mode needs faster dispense flow rates and larger blowout volumes than Surface Empty mode.

**50 µL Surface Empty Liquid Class**

| | Ethanol | Water | Glycerin 80% |
|---|---|---|---|
| Aspirate flow rate (µL/s) | 100 | 100 | 50 |
| Aspirate air transport (µL) | 2 | 0 | 0 |
| Aspirate blowout (µL) | 2 | 1 | 2 |
| Dispense flow rate (µL/s) | 75 | 120 | 50 |
| Dispense air transport (µL) | 2 | 0 | 0 |
| Dispense blowout (µL) | 2 | 1 | 2 |

**300 µL Surface Empty Liquid Class**

| | Ethanol | Water | Glycerin 80% |
|---|---|---|---|
| Aspirate flow rate (µL/s) | 100 | 100 | 50 |
| Aspirate air transport (µL) | 3 | 5 | 0 |
| Aspirate blowout (µL) | 0 | 0 | 0 |
| Dispense flow rate (µL/s) | 150 | 120 | 10 |
| Dispense air transport (µL) | 5 | 5 | 0 |
| Dispense blowout (µL) | 0 | 0 | 0 |

**1000 µL Surface Empty Liquid Class**

| | Ethanol | Water | Glycerin 80% |
|---|---|---|---|
| Aspirate flow rate (µL/s) | 250 | 250 | 150 |
| Aspirate air transport (µL) | 5 | 5 | 0 |
| Aspirate blowout (µL) | 10 | 0 | 30 |
| Dispense flow rate (µL/s) | 120 | 120 | 120 |
| Dispense air transport (µL) | 15 | 5 | 10 |
| Dispense blowout (µL) | 10 | 0 | 30 |

**1000 µL Jet Empty Liquid Class**

| | Ethanol | Water | Glycerin 80% |
|---|---|---|---|
| Aspirate flow rate (µL/s) | 250 | 250 | 200 |
| Aspirate air transport (µL) | 5 | 5 | 5 |
| Aspirate blowout (µL) | 0 | 40 | 50 |
| Dispense flow rate (µL/s) | 400 | 400 | 300 |
| Dispense air transport (µL) | 15 | 5 | 15 |
| Dispense blowout (µL) | 0 | 40 | 50 |

---

## 5. Correction Curve (Trueness Tuning)

Liquid class **parameters** (Section 4) govern precision (repeatability). The **correction curve** governs trueness (accuracy vs. target). It's a set of (target value, corrected value) points; the corrected value tells the plunger how far to move to actually deliver the target volume. Values between defined points are derived by **linear interpolation**, so more points across the working range improve trueness at intermediate volumes. Points can be set in increments as small as 0.1 µL.

**Update formula**, from measured verification data:

```
New Corrected Value = (Current Corrected Value / Measured Value) × Target Value
```

Apply, re-test, and iterate until trueness converges. This is the core update rule for a closed loop that adjusts a liquid class based on balance feedback (Section 6).

In the schema this is the `correction` array — `[{ "targetedVolume": ..., "correctedVolume": ... }, ...]` — any number of points.

Note: predefined/default liquid classes' correction curves cannot be edited directly — save the class under a new name before adjusting. Concretely, check `isUserDefined`: `false` means predefined/read-only, `true` means a custom class you can modify. To adjust a predefined class's correction, clone it under a new `id` (which must match both the JSON filename and the VENUS `LiquidClassName`) with `isUserDefined: true`, rather than writing to the original.

---

## 6. Closed-Loop Verification via the Integrated Balance

The VENUS Python SDK exposes commands to drive the integrated Mettler Toledo WXS 205S balance for gravimetric checks — this is the practical, scriptable verification path for a closed loop (no plate reader / dye handling required).

**Core formulas**:

```
Trueness (%R)  = 100 × |(Measured Volume − Target Volume) / Target Volume|   (lower is better)
Precision (%CV) = 100 × (Standard Deviation / Mean)                          (lower is better; needs replicate transfers)
```

**Workflow**: dispense a known target volume → weigh it on the balance → convert mass to volume using the liquid's known density → repeat for replicates to compute %CV, and compare the mean measured volume to target to compute %R → if out of spec, apply the correction-curve formula (Section 5) to the relevant target point(s) → re-test → repeat until both trueness and precision are within the method's required tolerance (or the device's own trueness/precision spec from Section 2.2, if no application-specific tolerance is defined).

**Caveats to account for when scripting this loop**:
- Requires knowing the liquid's density; look it up or determine it empirically if unknown.
- Density (and thus the mass→volume conversion) is temperature-sensitive — keep temperature consistent between weighing runs and record it.
- Only one channel/transfer can be weighed at a time — this does not parallelize across a 96- or 384-probe head; verifying those requires testing representative channels serially or accepting a sampling strategy.
- Balance resolution limits usefulness at very low volumes — don't expect a reliable %CV from single-digit-µL transfers on this hardware alone.
- Vibration during weighing corrupts readings — avoid triggering the balance step while other deck motion is in progress.

---

## 7. Liquid Class Development Workflow

Use this sequence when a predefined liquid class needs to be adapted for a new liquid, rather than tuning blind:

1. **Select a starting predefined class** by liquid category — closest match, not automatically "Water":

   | Category | Example liquids |
   |---|---|
   | Aqueous solution | Water, PBS, Master Mix, TRIS |
   | Volatile organic solvents | Ethanol, Isopropanol, Acetone, Formaldehyde |
   | Involatile organic solvents | DMSO, Alkane |
   | Viscous liquids | Glycerol, Beads, Oil |
   | Blood products | Serum, Plasma, Whole Blood, Red Blood Cell |

2. **Run a minimal test method** against the target labware/tip combination (use water as a stand-in if the real liquid is costly/scarce for initial passes).
3. **Enable MAD or TADM** (Section 9) to catch aspiration/dispense execution errors (air, clots, foam) during testing.
4. **Adjust method settings first** (Section 3), then **liquid class parameters** (Section 4) one at a time if method settings alone don't resolve the issue — save the class under a new name before modifying, since default classes' parameters/correction curves are not editable in place.
5. **Verify trueness/precision** via the integrated balance (Section 6) and tune the correction curve (Section 5) until within spec. Re-verify if the run environment (temperature, elevation, humidity) changes materially from when the class was developed.

---

## 8. Common Transfer Patterns

### 8.1 Low-Volume Pipetting on 1000 µL Channels (0.5–20 µL)
- **Method settings**: 50 µL tips; single dispense where possible; surface empty dispense mode; minimize tip-to-surface distance without blocking the tip; liquid following **off**; new tip per transfer.
- **Liquid class parameters**: may need increased settling time; slow swap speed; increase blowout volume on aspirate but minimize it on dispense (creates overpressure that counters capillary effect).

### 8.2 Multi-Dispensing (Aliquoting)
Check Section 1.3's go/no-go logic first.
- **Method settings**: 50 µL tips or larger; discard the first and last aliquots (least accurate — some liquids need 2 pre-dispenses); limit aliquots per cycle for easier control (e.g. cap at half- or full-plate transfer counts); pre-wet the tip on the first aspirate (can neutralize correction-curve effects); use minimize z-move (set dispense height equal to clearance height) or dispense-on-the-fly for max speed (harder to tune).
- **Liquid class parameters**: increase stop back flow rate to match dispense flow rate; use a small stop back volume (dry dispense only); build the correction curve using a **step-down approach** based on remaining total volume after each aliquot, not the per-aliquot target (e.g. six 50 µL aliquots from a 300 µL tip → correct at 300, 250, 200 µL, etc.); use more correction curve points to raise trueness of each individual transfer.

### 8.3 Serial Dilution
- **Method settings**: new tip per transfer; surface dispense where possible; thorough mixing before/after each transfer (start with more mix cycles, reduce only if speed requires and quality allows); mix at a fixed position; accurate labware definitions are critical if using LLD + liquid following; keep mix volume **under 80%** of the well's total volume (above that, risk of aspirating air/bubbles rises sharply); watch retract distance for air transport at fixed height (too-low retract + fixed height can cause liquid to be re-aspirated instead of air).
- **Liquid class parameters**: different classes may be needed per dilution step depending on dilution factor; remove/zero the over-aspirate volume (can cause carryover into the next dilution/mix step).

---

## 9. Execution Monitoring (MAD / TADM)

These catch execution errors (air aspiration, clots, foam) in real time — they do **not** measure actual transferred volume (use Section 6 for that).

| | MAD (Monitored Air Displacement) | TADM (Total Aspiration & Dispense Monitoring) |
|---|---|---|
| Cost | Built-in | Requires TADM license |
| Monitors | Aspiration only | Aspiration and dispense |
| Lower volume limit | 50 µL | 10 µL (1000 µL channels) |
| Scope | General process control across a volume range | Liquid-class- and volume-specific tolerance bands |
| Liquid class dependency | Independent | Dependent |
| Curve recording | No (most recent only, service-tool access) | Yes — Recording or Monitoring mode |
| Tip reuse | OK if tip emptied each transfer | OK, may need separate class/tolerance bands |
| Channel support | 1000 µL, 5 mL only | 1000 µL, 1000 µL X1, 5 mL, MagPip, CO-RE 96 (TADM-hardware variant only — see Section 2.1) |

- **Use MAD when**: aqueous solutions, unused disposable tips, aspiration-only monitoring is sufficient.
- **Avoid MAD when**: dispense monitoring is also needed (use TADM); tips/needles are reused (false-error risk); liquid is non-aqueous; volume ≤50 µL (may need threshold re-tuning) or ≤10 µL (pressure delta too small to be reliable).
- **Use TADM when**: both aspirate and dispense monitoring are needed; transfer/aliquot volumes are >10 µL; liquid type varies beyond aqueous.
- **Avoid/limit TADM when**: volume <10 µL (unstable pressure profiles); highly variable transfer volumes make per-volume tolerance bands impractical (can still record without monitoring).
- MAD and TADM **cannot** be active simultaneously.
- **TADM guardbands**: collect pressure curves across representative transfers, confirm consistency, then set upper/lower tolerance bounds; a curve crossing the guardband trips an error (route to automated or user error recovery as appropriate). In the schema this is the `tadmBands` array (populated only when `tadmEnabled: true`), one entry per (step type, volume) combination captured, each holding `upperCurve`/`lowerCurve` as `{timeMs, pressure}` point arrays. `pressure` is in **raw sensor units**, not a calibrated physical unit — there's no documented conversion, so guardband thresholds must be derived empirically from captured curves for your specific liquid/tip/device combination, not assumed from a spec.

---

## Appendix: Hamilton Parameter ↔ Industry Terminology

| Hamilton Parameter | Other Industry Terms |
|---|---|
| Flow rate | Aspiration Speed / Dispense Speed |
| Mix flow rate | Aspiration Speed / Dispense Speed |
| Air transport volume | Trailing Air Gap (TAG) |
| Blowout volume | System Trailing Air Gap (STAG) |
| Swap speed | Retract Speed |
| Settling time | Delay |
| Over-aspirate volume | Conditioning Volume |
| Clot retract height | Exit Signal Detection |
| Stop flow rate | Dispense Speed / Break-off Speed |
| Stop back volume | No direct equivalent |

## Glossary

- **ADC** — Anti-Droplet Control
- **cLLD / pLLD** — capacitive / pressure Liquid Level Detection
- **MAD** — Monitored Air Displacement
- **TADM** — Total Aspiration & Dispense Monitoring
- **Dead volume** — liquid that must remain in a container/tip but is not itself transferred
- **Trueness (%R)** — closeness of measured average to target (systematic error)
- **Precision (%CV)** — repeatability of replicate transfers (random error)
