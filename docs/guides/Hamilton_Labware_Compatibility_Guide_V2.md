# Hamilton Labware Compatibility Reference Guide
## Labware-Centric Organization

## Overview
This document provides compatibility information organized by **labware type**. Find your labware below to see which carriers are compatible.

**Last Updated:** 2026-09-24  
**Source:** Hamilton SDK Labware JSON definitions

---

## Table of Contents
1. [Critical Safety Constraint: 145mm Clearance](#critical-safety-constraint-145mm-clearance)
2. [Understanding SBS Format](#understanding-sbs-format)
3. [How to Use This Guide](#how-to-use-this-guide)
4. [Multiflex (MFX) Modular Carriers](#multiflex-mfx-modular-carriers)
5. [Plates](#plates)
   - [Standard Microtiter Plates](#standard-microtiter-plates)
   - [Deep Well Plates](#deep-well-plates)
   - [PCR Plates](#pcr-plates)
   - [Filter Plates](#filter-plates)
   - [Specialty Plates](#specialty-plates)
6. [Reservoirs](#reservoirs)
   - [SBS Format Reservoirs](#sbs-format-reservoirs)
   - [Hamilton Reagent Containers (Non-SBS)](#hamilton-reagent-containers-non-sbs)
7. [Tips and Tip Racks](#tips-and-tip-racks)
8. [Tubes and Tube Racks](#tubes-and-tube-racks)
9. [Quick Reference](#quick-reference)
10. [Carrier Technical Specifications](#carrier-technical-specifications)

---

## Critical Safety Constraint: 145mm Clearance

⚠️ **MAXIMUM HEIGHT ABOVE DECK: 145mm**

**The total height of carrier + labware must NOT exceed 145mm to avoid collision with the pipetting head.**

### Formula
```
Total Height = Carrier Site Height + Labware Height

REQUIREMENT: Total Height ≤ 145mm
```

This constraint affects which carriers can be used with tall labware. See individual labware sections for specific guidance.

---

## Understanding SBS Format

### SBS (Society for Biomolecular Screening) Standard
- **Standard Footprint:** 127.76mm (W) × 85.48mm (D)
- **Tolerance Range:** Typically 125-130mm × 84-88mm

### Why It Matters
- **SBS format labware** fits on plate carriers (PLT_CAR_*)
- **Non-SBS format labware** (like Hamilton 60/120mL reservoirs) requires specialized carriers (RGT_CAR_*)

---

## How to Use This Guide

1. **Find your labware type** in the sections below
2. **Check the compatible carriers list** - these will work
3. **Check the incompatible carriers list** - these won't work
4. **Read the notes** for special considerations
5. **Verify clearance** if using tall labware (check carrier site heights in appendix)

---

## Multiflex (MFX) Modular Carriers

### What are Multiflex Carriers?

Multiflex (MFX) carriers are **modular, custom-configured carriers** where different module types can be mounted on individual sites of a common carrier base. Because each MFX carrier is configured individually in the labware editor, **no default definitions are included with the software**.

### Module Types and Compatibility

Each MFX module follows the compatibility rules of its corresponding standard carrier:

| MFX Module Type | Follows Compatibility of | Compatible Labware |
|-----------------|-------------------------|-------------------|
| MTP module | Standard plate carriers (PLT_CAR_L5_MTP) | Standard microtiter plates |
| DWP module | Deep well carriers (PLT_CAR_L5_DWP) | Deep well plates |
| PCR96 module | PCR carriers | 96-well PCR plates only |
| Tip rack module | Tip carriers (TIP_CAR_*) | Standard tip racks |
| NTR module | Nestable tip carriers | Nestable tip racks |
| Stack module | Stack carriers | Stacked plates |

### Height Restrictions

**Height restrictions depend on the specific module and its mounting height on the MFX base.** Check your custom MFX carrier definition's site heights to calculate clearance (Total = Site Height + Labware Height ≤ 145mm).

### Finding Module Compatibility

- **MTP module** → See [Standard Microtiter Plates](#standard-microtiter-plates) section
- **DWP module** → See [Deep Well Plates](#deep-well-plates) section
- **PCR96 module** → See [PCR Plates](#pcr-plates) section
- And so on for other module types

**Note:** Module definitions can be found in: `C:\Program Files (x86)\Hamilton\SDK\Labware\System\adapter`

---

# PLATES

## Standard Microtiter Plates

### Description
Standard 96-well, 384-well, 1536-well (or any other well format) microplates with SBS footprint and full skirts.

**Typical dimensions:** 127 × 86 × 14mm (height varies 10-15mm)  
**Examples:** Costar 96-well round/square, Greiner 384-well, Corning plates

### ✅ Compatible Carriers
**All of these carriers work:**
- **PLT_CAR_L5_MTP** (most common, 5 sites) - Site height: 107.3mm → Total: ~121mm ✅
- **PLT_CAR_L5_DWP** (5 sites, also works for deep wells) - Site height: 81.8mm → Total: ~96mm ✅
- **PLT_CAR_L5MD** (5 sites) - Site height: 111.8mm → Total: ~126mm ✅
- **PLT_CAR_L5AC** (5 sites) - Site height: 86.2mm → Total: ~100mm ✅
- **PLT_CAR_L5FLEX_MD** (5 sites, adjustable height) - Site height: 115.8mm → Total: ~130mm ✅
- **PLT_CAR_L5FLEX_AC** (5 sites, adjustable height) - Site height: 89.1mm → Total: ~103mm ✅
- **PLT_CAR_P3MD** (3 sites, portrait) - Site height: 111.5mm → Total: ~126mm ✅
- **PLT_CAR_P3AC** (3 sites, portrait) - Site height: 85.9mm → Total: ~100mm ✅
- **PLT_CAR_P3HD** (3 sites, portrait) - Site height: 117.7mm → Total: ~132mm ✅
- **PLT_CAR_L4HD** (4 sites) - Site height: 118.2mm → Total: ~132mm ✅
- **PLT_CAR_L4HHC** (4 sites with heater/cooler) - Site height: 80.6mm → Total: ~95mm ✅
- **PLT_CAR_L4HHS_*** (4 sites with heater/shaker, all variants) - Site height: 112.7mm → Total: ~127mm ✅
- **PLT_CAR_L4ST_*** (4 stack carriers) - Various heights ✅

**All clearances are SAFE** (well under 145mm limit)

### ❌ Incompatible Carriers
**Do NOT use these:**
- **RGT_CAR_*** (all reagent carriers) - Non-SBS footprint receptacles
- **TIP_CAR_*** (tip carriers) - Wrong footprint/alignment
- Tube carriers - Wrong footprint

### Notes


---

## Deep Well Plates

### Description
Deep well plates with SBS footprint, typically 1mL or 2mL well capacity.

**Typical dimensions:** 127 × 86 × 43-47mm (tall!)  
**Examples:** Corning 2mL deep well, Axygen 1mL deep well, Hamilton deep well plates

**⚠️ CRITICAL:** Deep wells are TALL - clearance is critical!

### ✅ Compatible Carriers
**These carriers have sufficient clearance:**
- **PLT_CAR_L5_DWP** (5 sites) ⭐ **BEST CHOICE** - Site height: 81.8mm → Total: 125mm ✅
- **PLT_CAR_L5AC** (5 sites) - Site height: 86.2mm → Total: 129mm ✅
- **PLT_CAR_P3AC** (3 sites, portrait) - Site height: 85.9mm → Total: 129mm ✅
- **PLT_CAR_L4HHC** (4 sites with heater/cooler) - Site height: 80.6mm → Total: 124mm ✅
- **PLT_CAR_L5FLEX_AC** (5 sites, adjustable) - Site height: 89.1mm → Total: 132mm ✅
- **PLT_CAR_L5_ALT** (5 sites with AutoLys) - Site height: 75.5mm → Total: 119mm ✅
- **PLT_CAR_L4_HHS-ALT** (4 sites heater/shaker) - Site height: 83.0mm → Total: 126mm ✅

### ❌ Incompatible Carriers
**Do NOT use - COLLISION RISK:**
- **PLT_CAR_L5_MTP** ❌ - Site height: 107.3mm → Total: 150mm ❌ **EXCEEDS 145mm!**
- **PLT_CAR_L5MD** ❌ - Site height: 111.8mm → Total: 155mm ❌ **EXCEEDS 145mm!**
- **PLT_CAR_P3MD** ❌ - Site height: 111.5mm → Total: 155mm ❌ **EXCEEDS 145mm!**
- **PLT_CAR_L5PCR** ❌ - Site height: 109.2mm → Total: 152mm ❌ **EXCEEDS 145mm!**
- **PLT_CAR_L4HD** ❌ - Site height: 118.2mm → Total: 161mm ❌ **EXCEEDS 145mm!**
- **PLT_CAR_P3HD** ❌ - Site height: 117.7mm → Total: 161mm ❌ **EXCEEDS 145mm!**
- **PLT_CAR_L4HHS_*** (heater/shaker variants) ❌ - Site height: 112.7mm → Total: 156mm ❌
- **PLT_CAR_L5FLEX_MD** ❌ - Site height: 115.8mm → Total: 159mm ❌
- All reagent carriers (RGT_CAR_*) - Wrong footprint
- All tip carriers (TIP_CAR_*) - Wrong footprint

### Notes
- **ALWAYS use PLT_CAR_L5_DWP or PLT_CAR_L5AC for deep wells** - these are specifically designed for tall labware
- PLT_CAR_L5_MTP is a common mistake - it looks right but causes collision!
- Calculate exact total height if using specialty deep well plates with unusual heights

---

## PCR Plates

### Fully Skirted PCR Plates

**Description:** PCR plates with full SBS-format skirt  
**Typical dimensions:** 127 × 86 × 15mm  
**Examples:** Bio-Rad Hard-Shell, Eppendorf twin.tec, fully skirted variants

#### ✅ Compatible Carriers
**Same as standard microtiter plates - all PLT_CAR carriers work:**
- PLT_CAR_L5_MTP, PLT_CAR_L5_DWP, PLT_CAR_L5MD, etc.
- **PLT_CAR_L5PCR** (specifically designed for 96-well PCR) - Site height: 109.2mm→ Total: ~126mm ✅
- **PCR_CAR_L5_384** (specifically designed for 384-well PCR) - Site height: 113.5mm → Total: ~129mm ✅
- All clearances SAFE

#### ❌ Incompatible Carriers
- RGT_CAR_* (reagent carriers) - Wrong footprint
- TIP_CAR_* (tip carriers) - Wrong footprint

#### Notes


---

### Semi-Skirted or Non-Skirted PCR Plates

**Description:** PCR plates without full skirts or with semi-skirts  
**Typical dimensions:** Varies - may not be full SBS footprint

#### ✅ Compatible Carriers
**Requires adapter or specialized carrier:**
- **PLT_CAR_L5PCR** (may work depending on skirt design) - Site height: 109.2mm
- **PCR_CAR_L5_384** (for 384-well) - Site height: 113.5mm
- **Use SBS PCR adapter** on any standard plate carrier (PLT_CAR_L5_MTP, PLT_CAR_L5_DWP, etc.)

#### ❌ Incompatible Carriers
- Most plate carriers **without adapter**
- RGT_CAR_* (reagent carriers)
- TIP_CAR_* (tip carriers)

#### Notes
- **Adapters are typically required** for proper alignment
- Check adapter availability for your specific PCR plate brand


---

## Filter Plates

### Description
Filtration plates (96-well format with membranes)

**Typical dimensions:** 127 × 86 × ~15-20mm (SBS footprint)  
**Examples:** Corning 96-well filter plates, Millipore filter plates

### ✅ Compatible Carriers

#### For Vacuum Filtration:
- **Vacuum manifold** (required for filtration operation)
- **Plate adapter on vacuum manifold** (if needed for fit)

#### For Liquid Handler Access (non-vacuum):
- All Deep well Plate compatible carriers (if not actively filtering, using an SBS adapter or sitting on top of a Deep Well Plate ):
  - PLT_CAR_L5_DWP, PLT_CAR_L5AC, etc.
  - **But clearance must be verified** - filter plates can be taller than standard plates

### ❌ Incompatible Carriers
- RGT_CAR_* (reagent carriers) - Wrong footprint
- TIP_CAR_* (tip carriers) - Wrong footprint
- **Any carrier where the filtrate cannot drain** (if filtering)

### Notes
- **Filtration requires vacuum manifold** - carriers alone cannot filter
- For pre/post-filtration pipetting, use standard SBS carriers
- Verify height clearance for your specific filter plate model

---

## Specialty Plates

### Half-Area Plates, Low-Volume Plates, UV Plates, etc.

**Description:** Specialized plates with SBS footprint but unusual well designs  
**Typical dimensions:** 127 × 86 × varies

### ✅ Compatible Carriers
**Most SBS plate carriers work**
- Consider carrier that provides optimal height compatibility:
  - **PLT_CAR_L5_MTP** - Good for most specialty plates
  - **PLT_CAR_L5_DWP** - Lower profile for taller plates

### ❌ Incompatible Carriers
- RGT_CAR_* (reagent carriers)
- TIP_CAR_* (tip carriers)

### Notes


---

# RESERVOIRS

## SBS Format Reservoirs

### Description
Reagent reservoirs with SBS footprint (127 × 86mm), typically multi-channel or 96-channel designs

**Available in various heights:**
- **Low profile (25-30mm):** Nunc 100mL series 
- **Tall (40-42mm):** Hamilton 250mL, Nunc 300mL, Nalgene 300mL series

**Consider the pipetting device compatibility for each definition**
- Each SBS reservoir definition has a defined wells grid for optimal pipetting location with different devices (for example, with 8 channels always pipette at the X center of the reservoir). The grid is defined in the labware JSON under "containerGrids". 
- The reservoir filename indicates the grid and device compatibility with the suffix "96" (for MPH96),  "384" (for MPH384), or "8" (for independent channels).


### Low Profile SBS Reservoirs (Height ≤ 30mm)

**Examples:** Nunc 100mL 8-channel, Nunc 100mL 96-channel

#### ✅ Compatible Carriers
**All SBS plate carriers work:**
- PLT_CAR_L5_MTP - Site height: 107.3mm → Total: ~132mm ✅
- PLT_CAR_L5_DWP - Site height: 81.8mm → Total: ~107mm ✅
- PLT_CAR_L5MD - Site height: 111.8mm → Total: ~137mm ✅
- PLT_CAR_L5AC - Site height: 86.2mm → Total: ~111mm ✅
- All other PLT_CAR carriers ✅

#### ❌ Incompatible Carriers
- RGT_CAR_* (reagent carriers) - Wrong footprint (designed for non-SBS Hamilton reservoirs)
- TIP_CAR_* (tip carriers)

---

### Tall SBS Reservoirs (Height 40-42mm)

**Examples:** , Hamilton 250mL, Nunc 300mL 8-channel, Nunc 300mL 96-channel, Nunc 300mL 384-channel

**⚠️ CRITICAL:** These are tall - clearance matters!

#### ✅ Compatible Carriers
**These have sufficient clearance:**
- **PLT_CAR_L5_DWP** ⭐ **BEST CHOICE** - Site height: 81.8mm → Total: ~124mm ✅
- **PLT_CAR_L5AC** **SECOND BEST CHOICE**- Site height: 86.2mm → Total: ~128mm ✅
- **PLT_CAR_P3AC** - Site height: 85.9mm → Total: ~128mm ✅
- **PLT_CAR_L4HHC** - Site height: 80.6mm → Total: ~123mm ✅
- **PLT_CAR_L5FLEX_AC** - Site height: 89.1mm → Total: ~131mm ✅
- **PLT_CAR_L5_ALT** - Site height: 75.5mm → Total: ~118mm ✅

#### ❌ Incompatible Carriers
**COLLISION RISK - Do NOT use:**
- **PLT_CAR_L5_MTP** ❌ - Site height: 107.3mm → Total: 149mm ❌ **TOO CLOSE TO LIMIT**
- **PLT_CAR_L5MD** ❌ - Site height: 111.8mm → Total: 154mm ❌ **EXCEEDS 145mm!**
- **PLT_CAR_P3MD** ❌ - Similar issue
- **PLT_CAR_L5PCR** ❌ - Similar issue
- All high-profile plate carriers ❌
- RGT_CAR_* (reagent carriers) - Wrong footprint
- TIP_CAR_* (tip carriers)

#### Notes
- Use the same carriers as deep well plates (similar height constraint)
- PLT_CAR_L5_DWP is designed for this type of tall SBS labware

---

## Hamilton Reagent Containers (Non-SBS)

### Hamilton 20mL, 50mL, 60mL, 100mL, 120mL, 200mL, 400mL Reservoirs

**Description:** Narrow, non-SBS format reagent containers. Start with the suffix "RGT_" in the System > Reservoir folder.


#### ✅ Compatible Carriers
**ONLY these specialized carriers:**
- **RGT_20ml_Container_<black or natural>**:  Hamilton 20mL reservoir .  Use **RGT_CAR_5R60** (5 positions for 60mL. Fits 5x 20mL reservoirs with adapter PN 95477-01) 
- **RGT_CONT_50ml**:  Hamilton 50mL reservoir .  Use **RGT_CAR_5R** (5 positions for 50mL) 
- **RGT_CONT_60ml**:  Hamilton 50mL reservoir .  Use **RGT_CAR_5R60** (5 positions for 60mL) 
- **RGT_CONT_120ml**:  Hamilton 120mL reservoir .  Use **RGT_CAR_3R120** (3 positions for 120mL) 
- **RGT_CONT_200ml**:  Hamilton 200mL reservoir .  Use **RGT_CAR_4R200** (4 positions for 200mL) 
- **RGT_VESSEL_100ml**:  Hamilton 100mL reservoir .  Use **RGT_CAR_4R100** (4 positions for 100mL) 
- **RGT_VESSEL_400ml**:  Hamilton 400mL reservoir .  Use **RGT_CAR_1R400** (1 positions for 400mL) 


#### ❌ Incompatible Carriers
**Will NOT fit - wrong footprint:**
- ❌ **All PLT_CAR_*** carriers - Designed for SBS format (127×86mm), reservoir is only 20mm wide!
- ❌ All tip carriers
- ❌ Other plate carriers


#### Notes
- **CRITICAL:** These are NOT SBS format - do not attempt to use on plate carriers
- The 20mm width does not match the 127mm SBS carrier sites
- Must use dedicated RGT_CAR carriers
- Some custom carriers may have dedicated positions for these reservoirs. Confirm compatibility with Hamilton.

---

### Hamilton 100mL Vessel

**Description:** Non-SBS reagent vessel  
**Dimensions:** 21 × 120 × 110mm (non-SBS, very tall!)

#### ✅ Compatible Carriers
**ONLY this carrier:**
- **RGT_CAR_4R100** (4 positions) - Site height: 17.5mm → Total: 128mm ✅

#### ❌ Incompatible Carriers
- All PLT_CAR_* (wrong footprint)
- Other RGT_CAR_* (wrong size)
- All tip carriers

#### Notes


---

### Hamilton 120mL Reservoir

**Description:** Long, non-SBS format reservoir  
**Dimensions:** 21 × 142 × 95mm (non-SBS!)

#### ✅ Compatible Carriers
**ONLY this carrier:**
- **RGT_CAR_3R120** (3 positions) - Site height: 45.0mm → Total: 140mm ✅ (barely!)

#### ❌ Incompatible Carriers
- All PLT_CAR_* (wrong footprint - reservoir is 142mm long)
- RGT_CAR_5R60, RGT_CAR_5R (too short for this reservoir)
- Other RGT_CAR sizes
- All tip carriers

#### Notes
- **Near the 145mm limit!** Total height is 140mm
- Do not stack or add adapters

---

### Hamilton 400mL Vessel

**Description:** Full-length non-SBS vessel  
**Dimensions:** 21 × 460 × 110mm (non-SBS, full deck length!)

#### ✅ Compatible Carriers
**ONLY this carrier:**
- **RGT_CAR_1R400** (1 position) - Site height: 17.5mm → Total: 128mm ✅

#### ❌ Incompatible Carriers
- All PLT_CAR_* (wrong footprint)
- Other RGT_CAR_* (vessel is 460mm long - takes full deck track)
- All tip carriers

#### Notes
- This vessel spans nearly the full deck length
- Occupies one full carrier position

---

### 200mL Reagent Container

**Description:** Wider non-SBS reagent container  
**Dimensions:** 38 × 118 × 110mm (non-SBS, taller)

#### ✅ Compatible Carriers
**ONLY this carrier:**
- **RGT_CAR_4R200** (4 positions) - Site height: 34.1mm → Total: 144mm ⚠️ **VERY CLOSE TO LIMIT**

#### ❌ Incompatible Carriers
- All PLT_CAR_* (wrong footprint)
- Other RGT_CAR_* (wrong dimensions)
- All tip carriers

#### Notes
- **⚠️ WARNING:** Total height 144mm is extremely close to 145mm limit!
- Verify clearance before use
- Do not use taller variants if available

---

# TIPS AND TIP RACKS

### Standard Tip Racks (SBS footprint). 

**Description:** Standard tip racks with SBS-compatible footprint. Also described as framed tip racks. 
**Typical dimensions:** ~122 × 83mm (slightly smaller than full SBS)

#### ✅ Compatible Carriers
**Dedicated tip carriers:**
- **TIP_CAR_480BC** (5 positions) - Site height: 115.0mm
- **TIP_CAR_384BC** (4 positions with barcode) - Site height: 114.8mm
- **TIP_CAR_288** (3 positions, portrait) - Site height: 114.7mm


#### ❌ Incompatible Carriers
- PLT_CAR_* (plate carriers)
- RGT_CAR_* (reagent carriers)

#### Notes
- These tip racks have a specific footprint and snapping tabs, They can only be placed on the dedicated tip carriers or individual multiflex tip modules.

---


### Nested Tip Racks (SBS footprint). 

**Description:** Stackable tip racks with SBS-compatible footprint. Also described as NTR.  
- Only non-filter tips
- 10µL, 50µL or 300µL NTR tip sizes available for 1mL channels or MPH96. 
- Only 50µL NTR tip size available for MPH384. 
**Typical dimensions:** ~122 × 83mm (slightly smaller than full SBS)

#### ✅ Compatible Carriers
**Dedicated tip carriers:**
- **TIP_CAR_NTR** (5 positions, can stack up to 4xNTR on each position, 20 NTR total). - Site height: 29mm


#### ❌ Incompatible Carriers
- PLT_CAR_* (plate carriers)
- RGT_CAR_* (reagent carriers)

#### Notes
- These tip racks have a specific footprint. They can only be placed on the dedicated tip carriers or individual multiflex tip modules.

---


### Tip Boxes

**Description:** Hamilton tip boxes for 50µL, 300µL, 1mL tips

#### ✅ Compatible Carriers
**Dedicated tip box carriers:**
- **Tip Box 50uL and 300uL**, Ham_MLTipBox_Car_Base_50uL_300uL, (4 positions) - Site height: 57.2mm - For 50µL and 300µL tip boxes
- **Tip Box Carrier Base (1mL)** , Ham_MLTipBox_Car_Base_1mL, (4 positions) - Site height: 22.7mm - For 1mL tip boxes

#### ❌ Incompatible Carriers
- PLT_CAR_* (plate carriers)
- RGT_CAR_* (reagent carriers)
- Standard tip rack carriers
- Nested tip rack (NTR) carriers


---

# TUBES AND TUBE RACKS

### Standard Tube Racks (SBS footprint)

**Description:** Tube racks holding various tube sizes with SBS-compatible footprint

#### ✅ Compatible Carriers
- May work on some PLT_CAR carriers depending on tube rack height

#### ❌ Incompatible Carriers
- RGT_CAR_* (reagent carriers) - Wrong footprint
- TIP_CAR_* (tip carriers) - Wrong footprint

---

# QUICK REFERENCE

## Decision Matrix: "I have X labware, which carrier should I use?"

| Labware | Recommended Carrier(s) | Avoid |
|---------|------------------------|-------|
| Standard 96/384-well plates | PLT_CAR_L5_MTP, PLT_CAR_L5_DWP, PLT_CAR_L5MD | RGT_CAR_*, TIP_CAR_* |
| Deep well plates (1-2mL) | **PLT_CAR_L5_DWP**, PLT_CAR_L5AC | PLT_CAR_L5_MTP (collision risk!) |
| PCR plates (fully skirted) | PLT_CAR_L5_MTP, PLT_CAR_L5PCR | RGT_CAR_*, TIP_CAR_* |
| PCR plates (semi-skirted) | PLT_CAR_L5PCR (96-well), PCR_CAR_L5_384 (384-well), or adapter on any PLT_CAR | Most carriers without adapter |
| Filter plates (vacuum) | Vacuum manifold + adapter | Carriers alone (cannot filter) |
| Filter plates (no vacuum) | PLT_CAR_L5_MTP, PLT_CAR_L5_DWP with an adapter or a base plate | RGT_CAR_*, TIP_CAR_* |
| SBS reservoirs (low, <30mm) | Any PLT_CAR_* carrier | RGT_CAR_*, TIP_CAR_*  |
| SBS reservoirs (tall, 40-42mm) | **PLT_CAR_L5_DWP**, PLT_CAR_L5AC | RGT_CAR_*, TIP_CAR_*, PLT_CAR_L5_MTP (too close to height limit) |
| Hamilton 20mL reservoir | **RGT_CAR_5R60** ONLY with adapter | Any other carrier|
| Hamilton 50mL reservoir | **RGT_CAR_5R** ONLY | Any other carrier|
| Hamilton 60mL reservoir | **RGT_CAR_5R60** ONLY | Any other carrier|
| Hamilton 120mL reservoir | **RGT_CAR_3R120** ONLY | Any other carrier |
| Hamilton 200mL reservoir | **RGT_CAR_4R200** ONLY | Any other carrier |
| Hamilton 100mL vessel | **RGT_CAR_4R100** ONLY | Any other carrier|
| Hamilton 400mL vessel | **RGT_CAR_1R400** ONLY | Any other carrier |
| Standard tip racks | TIP_CAR_480BC, TIP_CAR_384BC, TIP_CAR_288 | RGT_CAR_* , PLT_CAR_*|
| Nested tip racks | TIP_CAR_NTR | RGT_CAR_* , PLT_CAR_*|
| Hamilton tip boxes | Tip Box carriers (50µL/300µL or 1mL) | PLT_CAR_*, RGT_CAR_*, TIP_CAR_* |
| MFX carrier with MTP module | Follow PLT_CAR_L5_MTP rules | Check specific module site height |
| MFX carrier with DWP module | Follow PLT_CAR_L5_DWP rules | Check specific module site height |
| MFX carrier with other modules | Follow rules for corresponding standard carrier | Check specific module site height |

---

## Common Mistakes to Avoid

### ❌ MISTAKE #1: Using PLT_CAR_L5_MTP for deep well plates
**Problem:** Total height exceeds 145mm → collision risk  
**Solution:** Use PLT_CAR_L5_DWP instead

### ❌ MISTAKE #2: Trying to put Hamilton 60/120mL on plate carriers
**Problem:** Non-SBS footprint (20-21mm wide vs 127mm required)  
**Solution:** Must use dedicated RGT_CAR_5R60 or RGT_CAR_3R120

### ❌ MISTAKE #3: Using tall SBS reservoirs (300mL) on high carriers
**Problem:** May exceed or come very close to 145mm limit  
**Solution:** Use PLT_CAR_L5_DWP or other low-profile carrier

### ❌ MISTAKE #4: Semi-skirted PCR plates without adapter
**Problem:** Poor alignment, may not seal properly  
**Solution:** Use PCR adapter or dedicated PCR carrier

---

## Format Compatibility at a Glance

### SBS Format (127 × 86mm footprint)
**Use PLT_CAR_* carriers:**
- Standard plates
- Deep well plates
- PCR plates (fully skirted)
- Filter plates
- SBS reservoirs (Nunc series, Hamilton 250mL)

### Non-SBS Format
**Use RGT_CAR_* carriers:**
- Hamilton 20/50/60mL reservoirs
- Hamilton 100mL reservoirs
- Hamilton 120mL reservoirs
- Hamilton 200mL reservoirs
- Hamilton 400mL reservoirs


### Tip-Specific Format
**Use TIP_CAR_* or tip box carriers:**
- Standard tip racks
- Hamilton tip boxes

---

# CARRIER TECHNICAL SPECIFICATIONS

## Quick Reference: Carrier Site Heights

For clearance calculations: Total Height = Site Height + Labware Height (must be ≤ 145mm)

### Plate Carriers (by Available Clearance)

**⚠️ Low Clearance (<30mm available) - Standard plates only:**
| Carrier | Sites | Site Height | Max Labware |
|---------|-------|-------------|-------------|
| PLT_CAR_L4HD | 4 | 118.2mm | 26.8mm |
| PLT_CAR_P3HD | 3 | 117.7mm | 27.3mm |
| PLT_CAR_L5FLEX_MD | 5 | 115.8mm | 29.2mm |

**📊 Medium Clearance (30-50mm) - Standard plates & PCR:**
| Carrier | Sites | Site Height | Max Labware |
|---------|-------|-------------|-------------|
| PLT_CAR_L5MD | 5 | 111.8mm | 33.2mm |
| PLT_CAR_P3MD | 3 | 111.5mm | 33.5mm |
| PLT_CAR_L5PCR | 5 | 109.2mm | 35.8mm |
| **PLT_CAR_L5_MTP** | **5** | **107.3mm** | **37.7mm** |
| PLT_CAR_L4HHS (all) | 4 | 112.7mm | 32.3mm |

**✅ High Clearance (>50mm) - Deep wells & tall SBS OK:**
| Carrier | Sites | Site Height | Max Labware |
|---------|-------|-------------|-------------|
| PLT_CAR_L5FLEX_AC | 5 | 89.1mm | 55.9mm |
| PLT_CAR_L5AC | 5 | 86.2mm | 58.8mm |
| PLT_CAR_P3AC | 3 | 85.9mm | 59.1mm |
| PLT_CAR_L4_HHS-ALT | 4 | 83.0mm | 62.0mm |
| **PLT_CAR_L5_DWP** | **5** | **81.8mm** | **63.2mm** |
| PLT_CAR_L4HHC | 4 | 80.6mm | 64.4mm |
| PLT_CAR_L5_ALT | 5 | 75.5mm | 69.5mm |

### Reagent Carriers

| Carrier | Sites | Site Height | Max Labware | For Labware |
|---------|-------|-------------|-------------|-------------|
| **RGT_CAR_5R60** | 5 | 63.2mm | 81.8mm | Hamilton 60mL and Hamilton 20mL|
| **RGT_CAR_5R** | 5 | 18.5mm | 126.5mm | Hamilton 50mL |
| **RGT_CAR_3R120** | 3 | 45.0mm | 100.0mm | Hamilton 120mL |
| **RGT_CAR_4R200** | 4 | 34.1mm | 110.9mm | Hamilton 200mL |
| RGT_CAR_4R100 | 4 | 17.5mm | 127.5mm | Hamilton 100mL |
| RGT_CAR_1R400 | 1 | 17.5mm | 127.5mm | Hamilton 400mL |
| RGT_CAR_12R | 12 | 81.0mm | 64.0mm | Troughs |
| RGT_CAR_2R6C | 8 | 63.2mm | 81.8mm | 2 reagent + 6 control |

### Tip Carriers

| Carrier | Sites | Site Height | Max Labware |
|---------|-------|-------------|-------------|
| TIP_CAR_480BC | 5 | 115.0mm | 30.0mm |
| TIP_CAR_384BC | 4 | 114.8mm | 30.2mm |
| TIP_CAR_288 | 3 | 114.7mm | 30.3mm |
| TIP_CAR_NTR | 5 | 29.0mm | 116.0mm |
| Tip Box 50µL/300µL | 4 | 57.2mm | 87.8mm |
| Tip Box 1mL | 4 | 22.7mm | 122.3mm |

### PCR Carriers

| Carrier | Sites | Site Height | Max Labware |
|---------|-------|-------------|-------------|
| PCR_CAR_L5_384 | 5 | 113.5mm | 31.5mm |

---

## Revision History

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-09-24 | 2.0 | Restructured to labware-centric organization | [Your Name] |
| 2026-09-24 | 1.0 | Initial version | [Your Name] |

---

## How to Use This Document with an LLM

This labware-centric organization makes it easy to get answers:

**Example queries:**
- "What carriers work with 2mL deep well plates?"
  → Look up "Deep Well Plates" section, get complete list

- "Can I use Hamilton 60mL reservoir on PLT_CAR_L5_DWP?"
  → Look up "Hamilton 60mL" section → NO, wrong footprint, use RGT_CAR_5R60

- "I have Nunc 300mL reservoir, which carrier?"
  → Look up "Tall SBS Reservoirs" → PLT_CAR_L5_DWP recommended

**The structure answers the question: "I have THIS labware - what are my options?"**

---

**End of Document**
