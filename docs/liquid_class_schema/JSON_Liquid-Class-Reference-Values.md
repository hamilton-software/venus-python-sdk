Lookup tables for the enumerated fields and numeric bounds referenced in `JSON_Liquid-Class-Model.md`. Source: `LiquidEnums` and `ParamRangesByDevice` in `Class1.cs`. If those change, regenerate this file rather than hand-editing it out of sync.

## Dispense Modes (`appliesTo.dispenseMode`)

| id | JSON value | notes |
|---|---|---|
| 2 | `jet_part` | |
| 3 | `jet_empty` | |
| 4 | `surface_part` | |
| 5 | `surface_empty` | |
| 6 | `whipip` | |
| 0 | `old_jet` | legacy — predefined classes only, don't use for new ones |
| 1 | `old_surface` | legacy — predefined classes only, don't use for new ones |
| -1 | `undefined` | reserved fallback, never a valid value to write |

## Pipetting Devices (`appliesTo.pipettingDevice`)

Exactly five values are valid; there is no numeric id to set directly (the JSON `_internal.liquidDeviceIds` array is derived from this and shouldn't be hand-authored):

| JSON value |
|---|
| `channels_1000ul` |
| `channels_5ml` |
| `channels_magpip` |
| `head_96` |
| `head_384` |

## Tip Types (`appliesTo.tipType`)

The nominal volume column is what `appliesTo.volumeRange.max` should be set to for that tip.

| id | `appliesTo.tipType` | nominal volume (µL) → `volumeRange.max` |
|---|---|---|
| 0 | `tip_300ul` | 300 |
| 1 | `tip_300ul_filter` | 300 |
| 2 | `tip_10ul` | 10 |
| 3 | `tip_10ul_filter` | 10 |
| 4 | `tip_1000ul` | 1000 |
| 5 | `tip_1000ul_filter` | 1000 |
| 6 | `old_needle_50ul` *(legacy)* | 50 |
| 7 | `old_tip_300ul` *(legacy)* | 300 |
| 8 | `old_needle_1000ul` *(legacy)* | 1000 |
| 10 | `needle_1000ul_teaching` | 1000 |
| 11 | `needle_10ul` | 10 |
| 12 | `needle_300ul` | 300 |
| 13 | `needle_1000ul` | 1000 |
| 15 | `tip_30ul_384head` | 30 |
| 20 | `tip_50ul_384head` | 50 |
| 22 | `tip_50ul` | 50 |
| 23 | `tip_50ul_filter` | 50 |
| 25 | `tip_5ml` | 5000 |
| 28 | `tip_300ul_rocket` | 300 |
| 29 | `tip_4ml_filter` | 4000 |
| 30 | `tip_300ul_clear` | 300 |
| 31 | `tip_50ul_clear` | 50 |
| 32 | `tip_10ul_clear` | 10 |
| 33 | `tip_50ul_conductive_384head` | 50 |
| 35 | `tip_250ul_piercing` | 250 |
| 36 | `tip_300ul_slim` | 300 |
| 37 | `tip_50ul_clear_384head` | 50 |
| 44 | `tip_150ul_filter_piercing` | 150 |
| 45 | `tip_300ul_filter_slim` | 300 |
| 60 | `tip_300ul_wide_bore_0p71mm` | 300 |
| 61 | `tip_300ul_wide_bore_1p55mm` | 300 |
| 62 | `tip_1000ul_wide_bore_1p2mm` | 1000 |
| 63 | `tip_1000ul_wide_bore_3p2mm` | 1000 |
| 64 | `tip_300ul_wide_bore_0p71mm_filter` | 300 |
| 65 | `tip_300ul_wide_bore_1p55mm_filter` | 300 |
| 66 | `tip_1000ul_wide_bore_1p2mm_filter` | 1000 |
| 67 | `tip_1000ul_wide_bore_3p2mm_filter` | 1000 |

## Parameter Ranges by Device

Valid min–max bounds for `pipettingProperties.aspirate` / `.dispense` fields, keyed by `appliesTo.pipettingDevice`. Same units as the schema doc (µL, µL/s, mm/s, s; `clotRetractHeight` in mm).

| Parameter | channels_1000ul | channels_5ml | channels_magpip | head_96 | head_384 |
|---|---|---|---|---|---|
| flowRate | 1–500 | 10–2500 | 0.1–10000 | 0.3–500 | 0.3–240 |
| mixFlowRate | 1–500 | 10–2500 | 0.1–10000 | 0.3–500 | 0.3–240 |
| airTransportVolume | 0–50 | 0–500 | 0–912 | 0–50 | 0–10 |
| blowOutVolume | 0–999.9 | 0–5000 | 0–912 | 0–1150 | 0–94 |
| swapSpeed | 0.3–160 | 0.3–160 | 0.3–160 | 0.3–100 | 0.3–100 |
| settlingTime | 0–9.9 | 0–9.9 | 0–9.9 | 0–9.9 | 0–9.9 |
| overAspirateVolume | 0–99.9 | 0–999.9 | 0–836 | 0–1150 | 0–94 |
| clotRetractHeight | 0–50 | 0–500 | 0–50 | *not range-checked* | *not range-checked* |
| stopFlowRate | 1–500 | 10–2500 | 0–10000 | 0.3–500 | 1.5–240 |
| stopBackVolume | 0–18 | 0–99.9 | 0–836 | 0–99.9 | 0–20 |

`clotRetractHeight` has no defined range for `head_96` / `head_384` — the field is accepted but not validated against bounds for those two devices.
