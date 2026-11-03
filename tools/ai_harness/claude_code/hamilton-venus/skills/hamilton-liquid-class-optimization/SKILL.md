---
name: hamilton-liquid-class-optimization
description: Choosing and tuning Hamilton VENUS liquid classes and pipetting settings for a STAR or Vantage. Use when picking a channel, tip size, dispense mode (jet / surface, empty / part volume, WhiPip) or a starting liquid class for a liquid; when creating, cloning or adjusting a liquid class (flow rate, blowout, air transport, swap speed, settling time, over-aspirate, stop flow / stop back volume, correction curve); when deciding LLD (cLLD / pLLD), fixed height, ADC, pre-wetting, liquid following or tip reuse for a transfer; when setting up multi-dispense, low-volume or serial-dilution transfers; when planning gravimetric (balance) verification; or when choosing between MAD and TADM monitoring or setting TADM tolerance bands.
---

# Hamilton liquid class & pipetting optimization

The full guide is [reference/hamilton-liquid-handling-optimization-guide.md](reference/hamilton-liquid-handling-optimization-guide.md). It is the **decision heuristics** layer. Its companion references live in this repo:

- `docs/liquid_class_schema/JSON_Liquid-Class-Model_sdk.md`: liquid class JSON structure and field meanings
- `docs/liquid_class_schema/JSON_Liquid-Class-Reference-Values.md`: enums (tip types, dispense modes, devices) and the **legal min/max per device**. Clip every generated value to these ranges before writing a liquid class.

## Workflow (from the guide)

1. Classify the liquid: aqueous / volatile organic / involatile organic / viscous / blood product; note viscosity, volatility, adhesion.
2. Pick channel, tip, dispense mode and a starting predefined class (§1), within what this instrument actually has (see "Hard constraints" below).
3. Set the per-step method settings: LLD, ADC, fixed height, tip reuse … (§3).
4. Adjust liquid class parameters with the directional rules, using the example values as sanity bounds (§4).
5. For trueness, verify gravimetrically and update the correction curve (§5, §6).
6. For low volume, multi-dispense or serial dilution, start from the recipes (§8).
7. Decide on MAD or TADM monitoring (§9).

## Hard constraints: what the instrument has

Check these before any heuristic below. A class that breaks one is wrong, however good its name looks.

- **Device fitted.** The class's `appliesTo.pipettingDevice` must be a device this instrument has. `instrument_get_configuration` reports it per arm: `channels1mL` → `channels_1000ul`, `channels5mL` → `channels_5ml`, `channelsMagPip` → `channels_magpip`, `MPH96` → `head_96`, `MPH384` → `head_384`. MagPip classes exist only in the Vantage library and need MagPip channels; a STAR never has them.
- **Tip registered and loaded.** `get_registered_tip_types()` (works once a session is started, before connecting) lists the tip types VENUS knows, by id: name, `max_liquid_volume`, `tip_length` (the whole tip) and `length_below_channel` (tip length minus the collar depth up to the channel's stop disk: 59.9 − 8 = 51.9 mm for a 300 µL tip; use this one for heights), `filter`, `conductive`, and the devices that can use each one. A tip type not in this list cannot be used. The class's `_internal.tipTypeId` must be the tip actually picked up (the tip pool's `tip_type`), filter and non-filter included.
- **Volume.** At most the tip's `max_liquid_volume`, and inside the class's `volumeRange`.
- **Use the finder.** `find_liquid_classes(liquid, dispense_mode=…, volume=…, tip_pool=…)` applies all of this and returns the matching classes best first (closest liquid, Hamilton's validated originals before custom ones). It refuses, with the reason, a device that isn't fitted, an unregistered or unusable tip, or too much volume. Start from its first candidate; don't pick a class by its name, and don't judge one by it either: read the candidate's `summary` and numbers, which come from the class definition (`appliesTo`: device, tip type, volume range, liquid, dispense mode; `pipettingProperties`: flow rates, blow-out, air transport, swap speed, settling time, stop flow). The 96 CORE head classes have `1000ul` in their names because the head is a 1000 µL head, whatever the tip: `StandardVolume_96COREHead1000ul_Water_DispenseJet_Empty` is a 300 µL tip class (0-300 µL). `liquid_match: fallback` only says the liquid isn't named exactly (e.g. a buffer matched to Water), not that the tip is wrong.
- Pipetting commands refuse a class made for another device or the other instrument before anything is sent (`LiquidClassMismatchError`).

## Quick decisions

**Tip:** aim for the transfer volume at 5–100 % of the tip's capacity.
- Dispense > 300 µL → 1000 µL tips (5 mL channels above 1000 µL).
- Dispense < 15 µL → 50 or 10 µL tips.
- Otherwise → 300 µL tips; reconsider 1000 µL if multi-dispensing ≥ 50 µL or aspirating > 300 µL.

**Dispense mode:**
- Mixing after dispense, or dispense < 5 % of tip volume → Surface Empty.
- Precision matters → Jet Empty (single dispense), or Jet Part Volume (multi-dispense).
- Otherwise → Surface Empty, or Surface Part Volume (multi-dispense).
- Viscous liquids: Surface only. Volumes ≤ 20 µL: Surface. Sub-µL on MagPip (only when the instrument has MagPip channels): `whipip`.

**Multi-dispense:** use single aspirate/dispense instead if ADC is required, the liquid is volatile, or precision is critical and conditions aren't ideal (§1.3).

**Monitoring:** MAD and TADM can't both be active.
- MAD: built in; aspirate only; ≥ 50 µL; aqueous; unused tips; 1000 µL and 5 mL channels only.
- TADM: licensed; aspirate and dispense; > 10 µL; liquid-class-specific tolerance bands (`tadmBands`, raw sensor units, derived empirically).

## Rules to respect

- **Valid parameters only.** Set only the parameters valid for the chosen aspirate/dispense mode, e.g. no blowout on Consecutive Aspiration, no mix flow on Aspirate All. An inapplicable parameter is a validation error.
- **Ranges differ by device.** For example, `flowRate` is 1–500 µL/s on `channels_1000ul` but 0.1–10,000 µL/s on `channels_magpip`; take bounds from the reference-values file.
- **WhiPip.** Treat `whiPipJson` as opaque calibration data. Copy it verbatim from a validated class, and never drop or alter it on a read-modify-write.
- **Tuning heuristics.** The §1.4 property → parameter table comes from 1000 µL / 5 mL / 300 µL channels. Don't extrapolate it to MagPip.
- **Run environment.** Flag a liquid class for re-verification when the run environment (temperature, elevation, humidity) differs materially from where it was developed.

## Where to look in the reference

§1 Quick Decision Reference · §2 Hardware & Tip Specifications (trueness / CV tables, tip ↔ channel compatibility) · §3 Method Settings · §4 Liquid Class Parameters (§4.1 directional rules, §4.2 example defaults for 1000 µL channels) · §5 Correction Curve · §6 Closed-Loop Verification via the Integrated Balance · §7 Development Workflow · §8 Common Transfer Patterns · §9 MAD / TADM · Appendix (Hamilton ↔ industry terminology) · Glossary.

## Using it with this SDK

- **Finding existing classes:**
  - `find_liquid_classes(liquid, dispense_mode=…, volume=…, tip_pool=…)`: the classes that fit this instrument and transfer, ranked, with what each applies to. Use this first.
  - `get_registered_tip_types()`: the registered tip types with their volumes, length, filter, conductivity and devices.
  - `get_liquid_classes(tip_type=…, device=…, dispense_mode=…, has_tadm_enabled=…)`: names only, filtered in VENUS. The ID for each filter comes from a definition's `_internal` fields. Tip type IDs: 1000 µL tips = 4, 300 µL = 0. Dispense modes: 2 jet part, 3 jet empty, 4 surface part, 5 surface empty.
  - `get_liquid_class(name)`: the full definition.
- **Creating or changing a class:** `update_liquid_class(definition)` imports a definition. A new `id` creates a new user class; system (original) classes are read-only. To make a variant, copy a system class's definition, then change its `id`, `is_user_defined` and the fields you need.
- **Catalog names:** `hamilton_venus.catalog.LIQUID_CLASSES.STAR…` / `.VANTAGE…`, e.g. `LIQUID_CLASSES.VANTAGE.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY`.
- **Mix position:** `AspirateSettings` / `DispenseSettings` `mix_position` is a relative move from the aspirate/dispense position, not an absolute height: with `fixed_height=5` and `mix_position=2` the channel moves down 2 mm and mixes 3 mm above the bottom. Use `mix_position=0` (mix where the channel already is) unless there's a reason to move.
- **TADM curves:** a liquid class with TADM enabled returns curves on every aspirate/dispense response (`return_parameters.tadm.tadm_curves`, each with `liquid_class_name`, `step_type_name`, `volume`, `channel_number`), with or without `adc=True`.
