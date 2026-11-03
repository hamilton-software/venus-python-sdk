---
name: hamilton-tip-counter-setup
description: 'Set up Hamilton VENUS tip counters correctly after adding tip racks, so tip pickups don''t fail with "Tips ... failed to return a sequence: TransportNotPossible: Rack transport is not possible". Use whenever a script or MCP session adds tip racks (add_tip_rack, add_tip_box, add_ntr, or a deck layout with tip pools) before the first tip_pickup on a STAR or Vantage; when generating or reviewing a pipetting script or card that uses tip pools; when deciding between tip_pool_reset_tip_counter and tip_pool_show_tip_counter(s); or when diagnosing "Rack transport is not possible" or a tip sequence error.'
---

# Hamilton tip counter setup

## Why

A tip counter (tip pool) is remembered across sessions by its name. When a pool name that was used before now has **different labware** behind it (other racks, rack ids or positions), VENUS's saved counter no longer matches the deck, and the first pickup fails:

```
Tips "tips1000" failed to return a sequence: TransportNotPossible: Rack transport is not possible.
```

Resetting the counter, or opening the tip counter dialog, re-syncs it to the racks now on the deck. Do one of them **after all tip racks are added and before the first `tip_pickup`**.

## The rule

**Simulation** (`simulate=True`): always reset every tip pool the session uses, right after adding the last tip rack. No need to ask.

```python
star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_1000UL, carrier_id="TipCarrier", site="1", tip_pool="Tips1000")
star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_1000UL, carrier_id="TipCarrier", site="2", tip_pool="Tips1000")
star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL, carrier_id="TipCarrier", site="3", tip_pool="Tips300")

# All racks added: re-sync every pool to the deck before the first pickup.
for pool in ("Tips1000", "Tips300"):
    star.tip_pool_reset_tip_counter(tip_pool=pool)
```

**Live instrument** (`simulate=False`): the racks may be partly used, so don't reset blindly. Ask the user first, for each pool (or all at once):

- **"Are the tip racks full?"** If yes, call `tip_pool_reset_tip_counter(tip_pool=...)` for each pool.
- **Otherwise, show the tip counter** so the operator can mark which tips are present: `tip_pool_show_tip_counters(tip_pools=[...])` (or `tip_pool_show_tip_counter` for one pool). The dialog appears on VENUS's screen on the instrument PC and the call waits until someone closes it there. Through an MCP spoke or hub nobody at the AI's end can see it, so tell the user to complete it at the instrument.
- If the user can tell you exactly which tips are present, `tip_pool_set_tip_counter` sets them without the dialog (it replaces the pool's state: listed racks hold exactly the listed tips, racks left out are missing).

**In a script**, do both, chosen at run time, right after the last tip rack is added. A script must never rely on the counters left over from an earlier run:

```python
if star.simulate:
    star.tip_pool_reset_tip_counter(tip_pool=TIP_POOL)
else:
    star.tip_pool_show_tip_counters(tip_pools=[TIP_POOL])
```

The spoke's script validator warns (W035) when a script picks up tips without either. In an AI session, ask in the conversation before the first pickup.

## Nested tip racks (NTR)

NTRs come as a single rack or as a stack of racks nested on top of each other. **Ask the user** which they have, and how many racks per stack, before adding them; don't assume one. Add them with `add_ntr(labware_definition=..., carrier_id=..., site=..., stack=N, tip_pool=...)` on `TIP_CAR_NTR` (`stack=1` for a single rack), not `add_tip_rack`. The tip counter is set up for the pool afterwards as above.

## Checklist

- Every pool used by `tip_pickup` gets a reset (simulation) or a user-confirmed reset / shown tip counter (live) after its last rack is added.
- Do it again if racks are added to a pool later in the session.
- `tip_pool_get_tip_counter(s)` only reads the counter; it does not fix a mismatch.
- If the error appears anyway, reset (simulation) or show the tip counter (live), then retry the pickup.

Related skills: `hamilton-liquid-handling-rules` (rule 10, tip pools set up before use) and `hamilton-labware-compatibility` (which tip carrier for a rack).
