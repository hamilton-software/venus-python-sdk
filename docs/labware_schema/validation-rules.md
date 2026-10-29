# Labware v1 — validation rules

The labware JSON schema (`../schema/labware.schema.json`) enforces the **structure** of a definition: field presence, types, value shapes, enumerations, and the class/kind couplings expressible in JSON Schema. It cannot express the **semantic invariants** the model also depends on — cross-field arithmetic, monotonicity, reference resolution across definitions, graph properties, and uniqueness beyond a single map's keys.

This document is the consolidated catalog of both. It exists because those rules were otherwise scattered across the schema `$comment`s, the requirements' acceptance criteria, and the ADR Compliance sections. Each rule names the layer that enforces it and cites the authoritative source. This is a **reference, not a rationale store and not a backlog**: *why* a rule exists lives in the cited ADR or requirement; *that* it must hold is recorded here so a reader can see the whole contract in one place.

## How to read this

Every rule is tagged with the layer responsible for upholding it:

| Tag | Enforced where | Example |
|---|---|---|
| **Schema** | JSON Schema validation of a single document. Already machine-checked by `validate.mjs`. | `totalDepth` is required. |
| **Catalog** | Catalog service, at publish time, on one definition (cross-field / intra-document checks JSON Schema cannot do). | `maxPipettingDepth ≤ totalDepth`. |
| **Load** | Active-system load, when references resolve across definitions. | `contentsRef` resolves to a published definition. |
| **Composition** | System-composition / deployment, where instrument knowledge is available. | A sensor overlaps a presence-detection zone. |
| **Runtime** | Upheld during execution by the consuming runtime. | Placement = offset subtraction; volume conservation across a passthrough. |
| **Convention** | Author/consumer discipline; not currently machine-checked anywhere. | Reserved namespaces are not registered under. |

The **Schema** rules are listed for completeness (so the contract is visible whole), but the actionable set for implementers is everything tagged **Catalog / Load / Composition / Runtime** — those are the fitness functions a conforming implementation must add beyond JSON Schema.

Sources are cited at section granularity (ADR section, requirement acceptance criterion, or schema `$def`) rather than line number, so this document does not go stale on minor edits.

---

## 1. Identity, versioning & references

| # | Rule | Layer | Source |
|---|---|---|---|
| 1.1 | `id` is bare `publisher:identifier` form; no suffix. Content hashing is runtime-only, never authored. | Schema | `PublisherIdentifier`; ADR-MLAPI-0019; ADR-MLAPI-0033 §2.3 |
| 1.2 | `schemaVersion` matches `1.x.y[-prerelease]`; the major is fixed at 1 by the URN `:v1`. | Schema | `schemaVersion`; ADR-MLAPI-0021 |
| 1.3 | `contentsRef`, `labwareRef` match `PublisherRef` — bare `publisher:identifier`, no suffix. MicrolabAPI pins loaded content by content hash at execution time; pinning is never authored. | Schema | `PublisherRef` |
| 1.4 | `contentsRef` resolves to a stored labware definition. | Load | ADR-MLAPI-0035 §2.2; REQ-LABWARE-0013 |
| 1.5 | `labwareRef` (assembly component) resolves to a stored definition. | Load | ADR-MLAPI-0037 §2.6; REQ-LABWARE-0015 |
| 1.6 | `gripPoints` and all `customAttributes` keys are two-segment publisher form. | Schema | `propertyNames` on each map; ADR-MLAPI-0019; ADR-MLAPI-0040 |
| 1.7 | The `mlapi` and `hamilton` namespaces are reserved; authors do not register `customAttributes` / keys under them. | Convention | ADR-MLAPI-0040 §2.2 (schema permits the syntax; reservation is convention) |
| 1.8 | `tags` entries are unique within the array. | Schema | `tags.uniqueItems` |
| 1.10 | No two definitions from the same publisher share a `publisher:identifier`, regardless of `labwareClass`. | Catalog | REQ-LABWARE-0010 |

## 2. Container geometry

| # | Rule | Layer | Source |
|---|---|---|---|
| 2.1 | `totalDepth` is present on every `ContainerDefinition`. | Schema | `ContainerDefinition.required`; ADR-MLAPI-0035 §2.1 |
| 2.2 | `volumeModel` is present exactly when there is no `contentsRef` (liquid-holders carry it; tip/tube positions delegate to the occupant). | Schema | `ContainerDefinition.allOf`; ADR-MLAPI-0035 §2.1; ADR-MLAPI-0043 §2.1 |
| 2.3 | `firstContainerCenter.z ≥ bottomWallThickness` (the container's exterior bottom cannot fall below the labware base). | Not enforced — a deep-well plate's cavity floor legitimately sits below the base plane (e.g. `corning_96_deep_well_2ml`: z 0.6 < 1.0), so a hard check false-rejects a valid shipped plate; see `LabwareDefinitionConsistencyValidator`. | schema `firstContainerCenter` / `bottomWallThickness` `$comment`s |
| 2.4 | `maxPipettingDepth ≤ totalDepth`. | Catalog | `maxPipettingDepth` `$comment`; ADR-MLAPI-0043 §2.2 |
| 2.5 | `openingDimensions`: `circle` needs `diameter`; `rectangle` / `rounded_rectangle` need `width` + `depth`. | Schema | `openingDimensions.allOf` |
| 2.6 | `inferredFromShape`: required dims by shape (cylindrical → `diameter`; rectangular → `width` + `depth`); plus `shape`, `totalDepth`, `maxVolume`. | Schema | `VolumeModel.inferredFromShape.allOf` |
| 2.7 | `workingVolumeMin ≤ workingVolumeMax` when both are present. | Catalog | `workingVolumeMin` / `workingVolumeMax` |
| 2.8 | A container carrying `pipettingChannelGeometry` carries a `volumeModel` (the channel shape is supplementary and never substitutes for the volume model). | Schema | `ContainerDefinition.dependentRequired`; ADR-MLAPI-0043 §2.3 |
| 2.9 | `pipettingChannelGeometry.coneBottomDiameter ≤ cylinderDiameter` (the cone narrows toward the bottom; the flush junction fixes the cone's upper diameter to `cylinderDiameter`). | Catalog | ADR-MLAPI-0034 §2.4 (validity domain) |
| 2.10 | `CylindricalConicalGeometry` structure: `cylinderDiameter > 0`; heights ≥ 0; `coneBottomDiameter` present exactly when `coneHeight > 0`. | Schema | geometry schema `CylindricalConicalGeometry`; ADR-MLAPI-0034 §2.4 |
| 2.11 | `pipettingChannelGeometry` is deliberately **not** validated against the `volumeModel`: authored deviation from the true geometry is an intended capability (e.g. a safety margin near a delicate bottom); consistency checking is at most advisory, never blocking. | Convention | ADR-MLAPI-0043 §2.3 |

## 3. Volume model

| # | Rule | Layer | Source |
|---|---|---|---|
| 3.1 | A `VolumeModel` carries at least one of `lookupTable` / `segments` / `inferredFromShape`. | Schema | `VolumeModel.anyOf` |
| 3.2 | Tier precedence is `lookupTable > segments > inferredFromShape`; the highest present tier is authoritative. | Runtime | ADR-MLAPI-0043 §2.1; REQ-LABWARE-0011 |
| 3.3 | `lookupTable` heights are monotonically non-decreasing, and the entry at height 0 is volume 0. | Catalog | `lookupTable` `$comment`; ADR-MLAPI-0043 §2.1 |
| 3.4 | `lookupTable` volumes are monotonically non-decreasing as height rises. | Catalog | ADR-MLAPI-0043 §2.1 (physics of a volume-at-height curve) |
| 3.5 | When `segments` and `lookupTable` disagree, `lookupTable` is ground truth (a quality check, not a hard error). | Catalog | `VolumeModel` `$comment` |
| 3.6 | `segments` are ordered bottom-to-top (segment 0 is the deepest). | Catalog | `segments` `$comment`; ADR-MLAPI-0043 §2.1 |
| 3.7 | `inferredFromShape.maxVolume` is physically plausible for the declared shape and `totalDepth`. | Catalog | `inferredFromShape`; ADR-MLAPI-0043 §2.1 |
| 3.8 | `inferredFromShape.totalDepth` equals the container `totalDepth`, and its cross-section dims agree with `openingDimensions`, when both are present (the restatement is intentional — the two structures are kept separate, not merged). | Catalog | `inferredFromShape` / `openingDimensions` `$comment`s |

## 4. Alignment & placement

| # | Rule | Layer | Source |
|---|---|---|---|
| 4.1 | An alignment `offset` carries `z`; `x` / `y` are optional and default to the carrying object's footprint center. A labware site's `origin` is its footprint center; site receptacle offsets are site-local (relative to that origin) and omit `x` / `y` in the common centered case (resolving to the site center = origin). | Schema (z, site footprint) / Runtime (default) | `AlignmentOffset`; `SiteDefinition`; `LabwareSite`; ADR-MLAPI-0045 §2.1 |
| 4.2 | Compatibility is exact, case-sensitive string equality of alignment `name` between a feature and a receptacle. | Runtime | ADR-MLAPI-0045 §2.3; REQ-LABWARE-0017 |
| 4.3 | Placement = `receptacle.offset − feature.offset`; placed rotation = `receptacle.rotationZ − feature.rotationZ`. | Runtime | ADR-MLAPI-0045 §2.3 |
| 4.4 | Multi-match resolution: greatest summed `preference`, then greatest resting Z, then declaration order. | Runtime | ADR-MLAPI-0045 §2.4; REQ-LABWARE-0017 |
| 4.5 | Fit is soft — a name mismatch or over-footprint condition produces a soft warning, never blocks. | Runtime | ADR-MLAPI-0038 §2.3; ADR-MLAPI-0045 §2.5; REQ-LABWARE-0017 |
| 4.6 | A bare alignment `name` is shared cross-publisher; a `publisher:`-prefixed name mates only the same publisher's parts. | Runtime / Convention | ADR-MLAPI-0045 §2.3 |
| 4.7 | `selfStack` and a hand-authored self-matching feature/receptacle pair are mutually exclusive. | Catalog | `selfStack` `$comment`; REQ-LABWARE-0022 |
| 4.8 | `selfStack.height > 0` (typically `< dimensions.z` when copies nest). | Catalog | `selfStack.height`; REQ-LABWARE-0022 |

## 5. Grids, addressing, passthroughs & connected groups

| # | Rule | Layer | Source |
|---|---|---|---|
| 5.1 | `containerGrids` has at least one grid; grid ids are unique (map keys). | Schema | `containerGrids.minProperties`; ADR-MLAPI-0036 §2.1 |
| 5.2 | `iterationOrder` is explicitly declared on every grid (required, not defaulted). | Schema | `ContainerGrid.required`; ADR-MLAPI-0036 |
| 5.3 | Intra-definition container references use the qualified `gridId.containerName` form (a bare `gridId` in a connected group means the whole grid). | Schema (shape) | `from`/`to`/`containers` patterns; ADR-MLAPI-0036 §2.2 |
| 5.4 | Every passthrough `from`/`to` resolves to a declared `gridId.containerName` in this definition. | Catalog | ADR-MLAPI-0036 Compliance; REQ-LABWARE-0012 |
| 5.5 | Every connected-group `containers` reference resolves to a declared container/grid in this definition. | Catalog | REQ-LABWARE-0012 |
| 5.6 | A passthrough uses exactly one reference form: position-level (`from`+`to`) or grid-level (`fromGrid`+`toGrid`). | Schema | `IntraLabwarePassthrough.oneOf` |
| 5.7 | `mode = "mapped"` requires `map` (both passthrough types; `map` shape is the shared `PassthroughMap`). | Schema | `allOf` on both; `PassthroughMap` |
| 5.8 | `ContainerPassthrough.targetComponent` resolves to a component in the same assembly. | Catalog | ADR-MLAPI-0037 §2.3 |
| 5.9 | `PassthroughMode` is one shared definition across both passthrough types (cannot diverge). | Schema | `PassthroughMode` `$def` |
| 5.10 | `connectedContainerGroups` group ids are unique (map keys). | Schema | `connectedContainerGroups` (map form) |
| 5.11 | Passthrough volume is conserved: total debited from sources equals total credited to targets under the declared mode. | Runtime | ADR-MLAPI-0036 Compliance; `mode` `$comment` |
| 5.12 | A connected group's `maxVolume` is the pool capacity; the group tracks volume as one unit, not per member. | Runtime | ADR-MLAPI-0043 §2.3 |

## 6. Collision & presence detection

| # | Rule | Layer | Source |
|---|---|---|---|
| 6.1 | The `dimensions` bounding box encloses all `collisionShapes`. Intentionally **not** validated in v1; the bounding box is also the coarse collision envelope when no `collisionShapes` are declared. | Convention | `dimensions` `$comment`; ADR-MLAPI-0043 §2.4; REQ-LABWARE-0018 |
| 6.2 | `CollisionShape.origin` is in labware coordinates; `InteriorObstruction.origin` is in container-local coordinates (z=0 at the cavity floor). The two frames must not be confused. | Convention | `CollisionShape` / `InteriorObstruction` `$comment`s |
| 6.3 | A presence-detection zone overlaps the instrument's sensor position at each site, or the deployment warns. | Composition | `presenceDetectionZones` `$comment`; ADR-MLAPI-0033 §2.7 |
| 6.4 | `PresenceDetectionZone.zRange` is required; `zRange.min < max`. | Schema (required) / Catalog (ordering) | `PresenceDetectionZone.required`; geometry `ZRange` |

## 7. Assembly graph

| # | Rule | Layer | Source |
|---|---|---|---|
| 7.1 | An assembly declares at least two components. | Schema | `AssemblyData.components.minProperties` |
| 7.2 | Exactly one component has no `parentComponent` — that component is the base. | Catalog | ADR-MLAPI-0037 §2.2; `AssemblyComponent` `$comment` |
| 7.3 | Every `parentComponent` resolves to a key in the same `components` map. | Catalog | ADR-MLAPI-0037 §2.2 |
| 7.4 | The component graph is acyclic (a tree rooted at the base). | Catalog | ADR-MLAPI-0037 Compliance |
| 7.5 | A non-base component's labware carries an `alignmentFeature` whose name matches an `alignmentReceptacle` on its parent component's labware. | Load | ADR-MLAPI-0037 Compliance |
| 7.6 | A component carries no stored pose/offset/nesting-depth; the seat derives from the matched alignment. | Schema | `AssemblyComponent.additionalProperties:false`; ADR-MLAPI-0037 §2.2 |
| 7.7 | An assembly's labware-root `dimensions` encloses the stack height derived from its components' heights and seating alignment offsets (the authored coarse envelope and the derived height must agree). | Catalog | `AssemblyData` `$comment`; ADR-MLAPI-0037 |
| 7.8 | When a component's labware and its parent share more than one matching alignment name, the seat is chosen by the standard alignment resolution (greatest summed `preference`, then greatest resting Z, then declaration order — rule 4.4); the assembly declares no per-component selector. | Runtime | `AssemblyComponent.parentComponent` `$comment`; ADR-MLAPI-0045 §2.4; ADR-MLAPI-0037 |

## 8. Barcode

| # | Rule | Layer | Source |
|---|---|---|---|
| 8.1 | `surface=labware` ⇒ `face` ∈ {front,back,left,right,top,bottom}; `surface=container` ⇒ `face` ∈ {side,top,bottom}. | Schema | `BarcodeLocation.allOf` |
| 8.2 | The `grid` scoping field is only valid with `surface=container`. | Schema | `BarcodeLocation.allOf` |
| 8.3 | `grid` resolves to a declared grid in `containerGrids`. | Catalog | `grid` `$comment` |
| 8.4 | Expected read count derives from `surface` (+ optional `grid` scoping). | Runtime | `BarcodeLocation` `$comment`; REQ-LABWARE-0024 |

## 9. Probe, tool & mount

| # | Rule | Layer | Source |
|---|---|---|---|
| 9.1 | `labwareClass` ∈ {probe, tool, assembly, tip_rack} requires the matching class block; extra class blocks are allowed for multi-role items. (`lid` carries no block — a lid is `labwareClass: lid` + an `alignmentFeature` matching the host's lid-seat receptacle.) | Schema | root `allOf`; ADR-MLAPI-0033 §2.8 |
| 9.2 | `ProbeData` requires `isReusable`, `isConductive`, `maxVolume`, `length`, `diameter`. | Schema | `ProbeData.required` |
| 9.3 | A probe listing `capacitive` in `supportedLLDModes` has `isConductive: true`. | Catalog | `supportedLLDModes` `$comment`; ADR-MLAPI-0035 §2.4 |
| 9.4 | `maxTipCapacity ≥ maxVolume` when present (absent ⇒ equal to `maxVolume`). | Catalog | `maxTipCapacity` `$comment`; REQ-LABWARE-0013 |
| 9.5 | `MountInterface.mountKind` is bidirectionally coupled to its block (`channel`↔`channel`, `robot_wrist`↔`robotWrist`). | Schema | `MountInterface.allOf` |
| 9.6 | `robotWrist` requires `tcpOffset`; `compatibleHosts` has at least one host. | Schema | `MountInterface` |
| 9.7 | `ToolData.kind = gripper` requires `gripper`; a sensor kind requires `sensor`; extra kind blocks allowed for multi-kind tools. | Schema | `ToolData.allOf` |
| 9.8 | `GripPoint.approach` is non-empty and unique; `openWidth ≥ gripWidth`. | Schema (non-empty/unique) / Catalog (inequality) | `GripPoint` |
| 9.9 | `GripPoint.label` (when present) is unique within each instrument's grip-point array, so it is a stable client-facing selector. | Catalog | `GripPoint.label` `$comment` |
| 9.10 | A runtime gripping at a grip point never applies more than its `maxGripForce` when one is declared (the labware's physical tolerance; omitted means no labware-imposed bound). | Runtime | `GripPoint.maxGripForce` |

## 10. Cross-cutting

| # | Rule | Layer | Source |
|---|---|---|---|
| 10.1 | `CollisionShape`, `InteriorObstruction`, and `VolumeModel.segments` all use the shared geometry `Solid3D`; consumers do not redefine the solid catalog. | Schema | `$ref` to geometry; ADR-MLAPI-0034 Compliance |
| 10.2 | `Solid3D.type` couples to its required dimension fields; all solids require `height`. | Schema | geometry `Solid3D.allOf` |
| 10.3 | All positions and dimensions use the left-front-bottom origin (X+ right, Y+ back, Z+ up), millimeters. | Runtime / Convention | schema descriptions; ADR-MLAPI-0018 |
| 10.4 | An alignment's omitted `x`/`y` resolve to the carrying object's footprint center before subtraction. For labware-root alignments this is the labware footprint center (`dimensions.x/2`, `dimensions.y/2`); for a site receptacle it is the site footprint center, which for a center-origin site is the site `origin` itself. | Runtime | `AlignmentOffset`; `LabwareSite`; ADR-MLAPI-0045 §2.1 |
| 10.5 | Positioning anchor: the `dimensions` bounding box is anchored at the front-left(-bottom) datum corner; everything placed within — `firstContainerCenter`, `sites[].origin`, `collisionShapes.origin` (center X/Y, base Z), `presenceDetectionZones.center`, `gripPoints.center` — is center-anchored. | Convention | conventions.md §8 |

---

## Implementer's note

The **Schema** rules are already enforced by `../schema/labware.schema.json` and exercised by `../schema/.ajv-test/validate.mjs` against `../schema/examples/`. The rules tagged **Catalog**, **Load**, **Composition**, and **Runtime** are the checks a conforming implementation must add on top of JSON Schema, at the layer named.

Rule **6.4** (`zRange.min < max`) cannot be made structural — JSON Schema 2020-12 has no portable way to compare two numeric fields — so it stays a Catalog check, documented once against the shared geometry `ZRange`.
