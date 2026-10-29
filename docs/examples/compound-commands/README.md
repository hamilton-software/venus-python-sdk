# Compound Commands

High-level workflow helpers that orchestrate multiple low-level SDK commands into a single call. Each compound command handles tip management, batching, and result aggregation automatically.

## Available Commands

### [Add Reagent](./add-reagent.md)

Dispense a reagent from one or more source locations into destination wells with automatic tip management, single-dispense and multi-dispense modes, and optional CSV-driven multi-plate transfers.

```python
result = star.add_reagent(
    reagent_source="ReagentTrough",
    dest_plate="DestPlate",
    volume=50.0,
    tip_pool="TipPool300uL",
)
```

**Covers:**
- Basic single-plate reagent addition
- single-dispense vs multi-dispense dispense modes
- Pre-aliquot and post-aliquot (multi-dispense mode)
- `reuse_tips` (one shared tip set across the whole call)
- Connected-container sources (multi-channel aspiration)
- CSV-driven multi-plate transfers
- Operator-prompted tip reload callback
- Custom channel selection
- Inspecting `AddReagentResult`

### [Copy Plate](./copy-plate.md)

Transfer the contents of one plate to another with automatic tip management and multi-iteration batching.

```python
result = star.copy_plate(
    source_plate_id="SourcePlate",
    dest_plate_id="DestPlate",
    volume=100.0,
    tip_pool="TipPool300uL",
)
```

**Covers:**
- Basic plate-to-plate transfer
- Tip reuse mode
- Custom channel selection
- Per-channel variable volumes
- Inspecting `CopyPlateResult`

### [Hit Picking](./hit-picking.md)

Transfer samples between arbitrary source and destination wells from a CSV-driven worklist ("cherry pick"), with three tip-management strategies and automatic batching.

```python
result = star.hit_picking(
    transfer_csv="path/to/hits.csv",
    liquid_class="StandardVolume_Water_DispenseJet_Empty",
    tip_pool="TipPool300uL",
)
```

**Covers:**
- CSV-driven many-to-many transfers
- Fresh-tips, reuse-tips, and minimize-tips (one tip per source well) modes
- Single-tip mode (`minimize_tips=True, change_tips=False`)
- Transfer ordering (`follow_csv_order`)
- Operator-prompted tip reload callback
- Custom channel selection and error profiles
- Inspecting `HitPickingResult`

### [Pool Samples](./pool-samples.md)

Combine `pool_size` source wells into a single destination well, one pool at a time, with optional in-pool tip reuse and optional final mix.

```python
result = star.pool_samples(
    source_plate="SourcePlate",
    dest_plate="DestPlate",
    pool_size=4,
    volume_per_source=25.0,
    liquid_class="StandardVolume_Water_DispenseJet_Empty",
    tip_pool="TipPool300uL",
)
```

**Covers:**
- Basic many-to-one pooling (fresh tip per source well)
- `reuse_tips_within_pool=True` (one tip per pool)
- `mix_after_pool=True` final mix at the destination
- Incomplete final pool handling
- Custom `WellOrder` for source/destination traversal
- Operator-prompted tip reload callback
- Custom channel selection and error profiles
- Inspecting `PoolSamplesResult`

### [Replicate Samples](./replicate-samples.md)

Aliquot every source well into `replicates_per_source` destination wells, with single-dispense and multi-dispense modes, multi-dispense auto-split, and pre/post-aliquot handling.

```python
result = star.replicate_samples(
    source_plate="SourcePlate",
    dest_plate="DestPlate",
    replicates_per_source=3,
    volume_per_replicate=25.0,
    liquid_class="StandardVolume_Water_DispenseJet_Empty",
    tip_pool="TipPool300uL",
)
```

**Covers:**
- Basic one-to-many replication
- single-dispense vs multi-dispense dispense modes
- multi-dispense auto-split when volume exceeds tip capacity
- Pre-aliquot and post-aliquot (multi-dispense mode, `SOURCE` / `WASTE` disposal)
- Custom `WellOrder` for source/destination traversal
- Operator-prompted tip reload callback
- Custom channel selection and error profiles
- Inspecting `ReplicateSamplesResult`

### [Serial Dilution](./serial-dilution.md)

Dilute a sample across the columns of a plate, one series per row (rows run in parallel), with a global diluent pre-charge phase followed by the transfer chains. Provided as two peer commands: by dilution factor or by explicit volume.

```python
result = star.serial_dilution_by_dilution_factor(
    plate_id="AssayPlate",
    start_column=1,
    num_dilutions=6,
    transfer_volume=20.0,
    dilution_factor=2.0,
    diluent_source="ReagentTrough",
    diluent_tip_pool="TipPool300uL",
    transfer_tip_pool="TipPool300uL",
)
```

**Covers:**
- By dilution factor vs by explicit volume
- The two-phase model (diluent pre-charge then transfer chains) and separate tip sets
- 1-based `start_column`, `exclude_columns`, and `exclude_rows` (ints and letters)
- Separate diluent / transfer liquid classes, settings, and error profiles
- `mix_after_dispense` and `diluent_multi_dispense`
- Multi-source `diluent_source` with reactive draining and `on_liquid_reload_prompt`
- Connected-container diluent sources (multi-channel aspiration)
- Multi-plate and multi-pass (384-well) processing
- `reuse_tips` cross-pass contamination semantics
- `discard_last_excess` (`NONE` / `TO_WASTE` / `WITH_TIP_EJECT`) and `waste_location`
- Inspecting `SerialDilutionResult`
