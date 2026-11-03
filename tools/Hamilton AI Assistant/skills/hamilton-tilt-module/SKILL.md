---
name: hamilton-tilt-module
description: 'Using a Hamilton MFX Tilt Module with the SDK. Use when a script or session tilts a plate, adds a tilt module, or pipettes from a tilted labware, to make sure both the tilt module driver command and the tilt labware command are used with the same angle.'
---

# Tilt module

A tilt module needs **two** things, and the **degrees must match**:

1. The tilt module **driver** command (`tilt_module_*`, `TiltModuleClient`) that physically moves the module.
2. The **tilt labware** command (`tilt_labware`) that tells the deck layout the labware is tilted, so pipetting positions are corrected.

Using only one gives a physical tilt the pipetting does not know about, or a layout that is tilted while the module is flat.

The module cannot report its angle, and the plate needs time to settle before pipetting. Details: `docs/tilt_module_hardware_notes.md` and `docs/examples/tilt_module.md` in the SDK.
