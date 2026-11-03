---
name: hamilton-deck-tracking
description: 'Checks and tracking rules to keep a Hamilton deck layout and the real deck in agreement. Use before plate transports or long runs of pipetting steps, when taking a plate from a stack, when pipetting from a lidded plate, when a "not on top" error appears, or when moving labware onto other labware.'
---

# Deck tracking

- **Check carriers are in place** with `autoload_get_carrier_sensor_status` before transports or before a long series of pipetting steps. Do not call it between the individual tip pickup / aspirate / dispense / eject steps. If a carrier is not seen, **warn the user**: it may be on a different track than the layout says, or slightly pulled out. (Simulation always reads False; ignore it there.)
- **Taking a plate from a stack**: always call `get_top_labware` first, so the next labware in the stack is the one pulled.
- **Lidded labware**: pipetting from it raises a "not on top" error. Remove the lid first.
- **Stacking**: transporting labware onto other labware makes the two a stack, with the moved one on top.

See `hamilton-gripper-transport` for transport rules.
