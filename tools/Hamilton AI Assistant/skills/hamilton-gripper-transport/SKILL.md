---
name: hamilton-gripper-transport
description: 'Moving labware on a Hamilton STAR or Vantage with the QCG (Quick Change Gripper), CO-RE grips or the iSWAP / IPG, and what blocks pipetting while a gripper is in use. Use when adding a QCG (ask which type), choosing between QCG, CO-RE grips and iSWAP / IPG, planning a series of plate moves, picking channels for a QCG, transporting 1 mL tip boxes, setting grip and open widths for SBS plates, or when pipetting fails or is unsafe because grips are still picked up or a plate is still held.'
---

# Gripper and transport rules

## QCG (Quick Change Gripper)

- A QCG uses **4 consecutive channels**.
- Prefer the **middle channels**: 3-6 on an 8 channel system. This gives the best random access on the deck.
- More than 8 channels: use the channel group that reaches the sites needed. A 16 channel system should use channels 5-8, and even then cannot reach every site.
- **Ask the user which QCG they have** whenever you are asked to add one. The type changes access and Z heights:
  - **Standard QCG**: the oldest and longest. Works well on Vantage. On a STAR with FM (Fluid Motion) channels it has Z reach problems with tall labware.
  - **Mid QCG**: becoming the standard. Slightly shorter, so it reaches taller labware on a STAR with QCG.
  - **Deep Grip QCG (DGQCG)**: required to transport 1 mL tip boxes. Use channels 3-6 with it, otherwise random access problems occur on sites 1 and 5 of carriers. It can transport other labware too.
- The MagPip channels cannot transport: no QCG and no CO-RE grips on them.

## Naming

- STAR with legacy channels: the gripper is the **iSWAP**.
- STAR with FM channels: the gripper is the **IPG**.
- Vantage, any channels: the gripper is the **IPG**.
- iSWAP and IPG use the same commands and the user may use either name. The Python commands call both `iswap_*`.

## What blocks pipetting

Pipetting on **any channel** must not happen while:
- QCG are picked up: eject them first (the MPH96 may still be used);
- CO-RE grips are picked up: eject them first (the MPH96 may still be used);
- the iSWAP / IPG is holding labware: place it first (the MPH96 may still be used).

## Series of moves

- Several transports in a row: **keep the grips on and eject them only after the last move** (`core_eject_grips`).
- Park the iSWAP after its series.
- Moving labware on top of other labware stacks the two, with the moved one on top.

## Widths

For SBS plates a grip width of **80** and an open width of **90** work for most plates.

See also the `hamilton-liquid-handling-rules` skill for choosing the transport hardware, and `hamilton-channel-random-access` for channel reach.
