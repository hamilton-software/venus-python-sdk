---
name: hamilton-channel-random-access
description: 'Which Hamilton STAR or Vantage channels, arms and heads can reach which deck positions (random access). Use when choosing which channels to pipette or grip with, when a system has more than 8 channels, mixed 1 mL and 5 mL channels, MagPip channels, an MPH96 / 96 head or a second arm, when a position is reported unreachable, or when planning a layout where reach in X or Y matters. Covers channel order, arm slot capacity and where the reach limits are reported.'
---

# Channel layout and random access

## Channel order

Channels run from the **back** of the system (highest Y) to the **front** (lowest Y), smaller channels first, larger channels after. Example: 8 x 1 mL channels followed by 4 x 5 mL channels.

## Arm capacity

- Each arm has **16 slots of 9 mm**.
- A 1 mL channel takes one slot, a 5 mL channel takes two. 8 x 1 mL + 4 x 5 mL is full; so are 8 x 5 mL and 16 x 1 mL.
- **MagPip channels are always alone on their own arm.**

## Reach problems

- More than 8 channels on one arm means random access limits. Example: a 12 channel system cannot reach A1 of a plate on site 1 with channel 12.
- A **mixed arm** (1 mL and 5 mL) is more complex: the 5 mL channels have a different raster than the 1 mL channels.
- An **MPH96** on an arm limits that arm's X range: the MPH cannot reach the far right of the system. Assess the X range for it.
- With a **second arm**, assess the X reach of both arms.
- Do not guess. **Access in X and Y is reported by `instrument_get_configuration`**; read it and use it before choosing channels or sites.

See `hamilton-deck-geometry` to turn carrier tracks into X ranges, and `hamilton-gripper-transport` for QCG channel choice.
