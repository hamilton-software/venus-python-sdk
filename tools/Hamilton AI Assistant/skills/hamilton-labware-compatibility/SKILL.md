---
name: hamilton-labware-compatibility
description: Which Hamilton carrier a given labware fits on, and whether carrier + labware stays under the 145 mm deck clearance limit. Use when choosing carriers or carrier sites for plates (microtiter, deep well, PCR, filter, specialty), reservoirs (SBS and Hamilton 20/50/60/100/120/200/400 mL), tip racks/boxes or tubes; when building a deck layout (add_carrier / add_plate / add_reservoir / add_tip_rack / add_tube_carrier); when checking a user's layout for collision risk or a wrong footprint; or when asked about SBS format, Multiflex (MFX) modules or carrier site heights on a STAR or Vantage.
---

# Hamilton labware ↔ carrier compatibility

The full guide is [reference/Hamilton_Labware_Compatibility_Guide_V2.md](reference/Hamilton_Labware_Compatibility_Guide_V2.md) (source: Hamilton SDK labware JSON definitions, updated 2026-09-24). It is organized **by labware type**: find the labware, then read its compatible / incompatible carriers and notes.

## Always check

1. **145 mm clearance.** `carrier site height + labware height ≤ 145 mm`, or the pipetting head can collide. Check this for anything taller than a standard plate.
2. **Footprint.** SBS labware (127.76 × 85.48 mm) goes on plate carriers (`PLT_CAR_*`). Non-SBS Hamilton reagent containers go only on their dedicated reagent carrier (`RGT_CAR_*`). Never put plates on `TIP_CAR_*` or `RGT_CAR_*`.
3. **Carrier width.** Never assume it: not 5, not 10. Look up **every** carrier type before choosing any `left_track`. The MCP server's `search_labware` gives each carrier's `width_tracks`; in a script, read `customAttributes["hamilton:star"].widthAsTracks` (`hamilton:rck_properties.MlStarCarWidthAsT` for sample/tube carriers) from `labware_get_definition(<type>)`. A carrier with neither property takes its `dimensions.x` / 22.5 mm (one track), rounded up. Typical widths:

   | Carriers | Tracks |
   |---|---|
   | Most plate and tip carriers (`PLT_CAR_L5_MTP`, `PLT_CAR_L5_DWP`, `TIP_CAR_480BC`, ...) | 6 or 7 |
   | Reagent and sample / tube carriers (`RGT_CAR_5R60`, `SMP_CAR_*`, ...) | 1 or 2 |
   | `TIP_CAR_288` | 4 |

   With several carriers, start each one at or after the previous `left_track + widthAsTracks`, so they don't overlap and the last one still fits the deck (`instrument_get_configuration()` reports `tracks`).
4. **Replacing a definition.** A corrected or new labware definition needs a **new name**: one registered under the name of a definition already loaded is not loaded. Add it under a new name (for example `MyPlate_v2`) and use that name from then on.
5. **The pipetting device.** The 96 head (MPH96) and 384 head pipette only from SBS labware whose grid matches the head. Their reservoirs are the SBS troughs named for the head: `HAM_DW_RGT_96`, `NUN_96_RGT`, `NUN_100ML_96C_RGT`, `NUN_300ML_96C_RGT` (96 head), `NUN_300ML_384C_RGT` (384 head). They are SBS like plates, so they go on a **plate carrier** (`PLT_CAR_L5_DWP` for the tall ones), never on a reagent carrier. The Hamilton troughs (`RGT_CONT_*`, `RGT_VESSEL_*`, `RGT_200ML`, 20 mL containers) and the `..._8C_...` reservoirs are for the 1 mL / 5 mL channels only.
6. **Share carriers.** Put labware that fits the same carrier on that carrier's sites, rather than one carrier each: a 96-well trough and a deep well plate both go on one `PLT_CAR_L5_DWP` (site 1 and site 2, say). Use another carrier only when clearance, footprint or the user's layout needs one.

## Quick decisions

| Labware | Use | Avoid |
|---|---|---|
| Standard 96/384-well plate | `PLT_CAR_L5_MTP`, `PLT_CAR_L5_DWP`, `PLT_CAR_L5MD` | `RGT_CAR_*`, `TIP_CAR_*` |
| Deep well plate (1–2 mL) | **`PLT_CAR_L5_DWP`**, `PLT_CAR_L5AC` | `PLT_CAR_L5_MTP` (collision risk) |
| PCR plate, fully skirted | `PLT_CAR_L5_MTP`, `PLT_CAR_L5PCR` | `RGT_CAR_*`, `TIP_CAR_*` |
| PCR plate, semi-skirted | `PLT_CAR_L5PCR` (96), `PCR_CAR_L5_384` (384), or an adapter | carriers without adapter |
| Tall SBS reservoir (40–42 mm) | **`PLT_CAR_L5_DWP`**, `PLT_CAR_L5AC` | `PLT_CAR_L5_MTP` |
| Reservoir for the 96 head | `HAM_DW_RGT_96`, `NUN_96_RGT`, `NUN_*_96C_RGT` on **`PLT_CAR_L5_DWP`** (can share it with the plates) | `RGT_CONT_*` / `RGT_VESSEL_*` troughs (channels only), `RGT_CAR_*` |
| Hamilton 20 mL reservoir | `RGT_CAR_5R60` with adapter | anything else |
| Hamilton 50 / 60 / 100 / 120 / 200 / 400 mL | `RGT_CAR_5R` / `RGT_CAR_5R60` / `RGT_CAR_4R100` / `RGT_CAR_3R120` / `RGT_CAR_4R200` / `RGT_CAR_1R400` only | anything else |
| Standard tip racks (any size: 10 / 50 / 300 / 1000 µL) | **`TIP_CAR_480BC`** (5 sites, the default); `TIP_CAR_384BC` (4 sites grouped toward the center, for 16-channel systems); `TIP_CAR_288` (3 sites portrait, for 12-channel systems to pick a full row at once). The carrier follows the channel count, never the tip size. | `PLT_CAR_*`, `RGT_CAR_*` |
| Nested tip racks (the 1 mL channels and the 96 head can both pick up from them) | `TIP_CAR_NTR`, added with `add_ntr(..., stack=N)`. Ask the user whether each site holds a single rack or a stack, and how many; up to 4 per site. | `PLT_CAR_*`, `RGT_CAR_*`; `add_tip_rack` |

Plate carrier site heights (max labware height = 145 − site height):

| Clearance | Carriers (site height → max labware) |
|---|---|
| Low (<30 mm) | `PLT_CAR_L4HD` 118.2→26.8, `PLT_CAR_P3HD` 117.7→27.3, `PLT_CAR_L5FLEX_MD` 115.8→29.2 |
| Medium (30–50 mm) | `PLT_CAR_L5MD` 111.8→33.2, `PLT_CAR_P3MD` 111.5→33.5, `PLT_CAR_L5PCR` 109.2→35.8, `PLT_CAR_L5_MTP` 107.3→37.7, `PLT_CAR_L4HHS_*` 112.7→32.3 |
| High (>50 mm) | `PLT_CAR_L5FLEX_AC` 89.1→55.9, `PLT_CAR_L5AC` 86.2→58.8, `PLT_CAR_P3AC` 85.9→59.1, `PLT_CAR_L4_HHS-ALT` 83.0→62.0, `PLT_CAR_L5_DWP` 81.8→63.2, `PLT_CAR_L4HHC` 80.6→64.4, `PLT_CAR_L5_ALT` 75.5→69.5 |

## Where to look in the reference

Search the reference file for these headings:

- `# PLATES`: `## Standard Microtiter Plates`, `## Deep Well Plates`, `## PCR Plates`, `## Filter Plates`, `## Specialty Plates`
- `# RESERVOIRS`: `## SBS Format Reservoirs`, `## Hamilton Reagent Containers (Non-SBS)`
- `# TIPS AND TIP RACKS`, `# TUBES AND TUBE RACKS`
- `## Multiflex (MFX) Modular Carriers`: each module follows the rules of its standard carrier; heights come from the custom MFX definition
- `# QUICK REFERENCE`: `## Decision Matrix`, `## Common Mistakes to Avoid`, `## Format Compatibility at a Glance`
- `# CARRIER TECHNICAL SPECIFICATIONS`: site heights for plate, reagent and tip carriers

## Using it with this SDK

- Carrier and labware names in the guide are the SDK catalog names: `LABWARE.CARRIER.PLT_CAR_L5_MTP`, `LABWARE.PLATE.NUN_96_FL`, … (`hamilton_venus.catalog`). `PLT_CAR_L4HHS` is a family; the catalog has its variants (`PLT_CAR_L4HHS_05_FLB_MD`, …).
- Carrier and labware definitions, including site heights, are under `C:\Program Files (x86)\Hamilton\SDK\Labware\` (`System\carrier`, `System\adapter`, …) and `sdk_method_structure/Labware/` in this repo.
- When a requested combination is incompatible, say why (clearance or footprint) and name the compatible carrier, rather than silently substituting one.
