# Conventions for the Hamilton Labware Schema

## 1. Purpose and scope

This document records the recommended values for the open-vocabulary fields in the Hamilton labware schema (`urn:hamilton:schemas:microlab:labware:v1`). The schema enforces shape (snake_case, optional publisher prefix, length bounds); it does not enforce vocabulary. Authors who follow these recommendations get consistent metadata across the catalog and predictable behavior from consumers that key off these values. Authors who need values that are not listed here use the same snake_case pattern under their own publisher namespace.

This document is non-normative. Conformance is by author discipline, supported by linting in authoring tools. This document and the schema are self-contained for authoring against the schema. In this SDK, labware definitions are produced by `hamilton_venus.labware_builder` and sent to VENUS with `StarClient.labware_add_definition`.

The document is living. New entries are added by pull request and require no schema-version change.

### 1.1 Naming convention — keys versus values

The schema uses two distinct conventions, by surface:

- **JSON property names (keys)** follow **camelCase**: `displayName`, `schemaVersion`, `containerGrids`, `tipRack`, `customAttributes`. This matches .NET HTTP/JSON serialization defaults (`System.Text.Json` produces camelCase keys), so the schema interoperates cleanly with the .NET-based API surface and its generated clients.
- **String values in open-vocabulary fields** follow **snake_case**: `labwareClass: "tip_rack"`, `mountKind: "robot_wrist"`, `material: "stainless_steel"`, `kind: "barcode_reader"`, tag values like `deep_well`, alignment names like `sbs_rim`. This matches existing Hamilton vocabulary (Hamilton's VENUS / InstinctV / MLPrep software use these forms), the lab-automation peer ecosystem (pyLabRobot, Opentrons), and reads better at a glance for multi-word identifiers (`cyclo_olefin` over `cycloOlefin`).

The split is intentional: keys are *structure* (the serializer cares) and values are *data* (the serializer doesn't). The two conventions never collide because they apply to different surfaces.

**Class-specific block names** sit in the keys-camelCase surface, so the block name for a snake_case `labwareClass` value is its camelCase equivalent. The mapping is mechanical:

| labwareClass value | Block name |
|---|---|
| `probe` | `probe` |
| `tool` | `tool` |
| `assembly` | `assembly` |
| `tip_rack` | `tipRack` |

Single-word class values match exactly. Multi-word values lose underscores and capitalize each subsequent word. If a future class block lands for a multi-word custom class (for example a `magneticStand` block paired with `magnetic_stand`), it follows the same rule.

**Keys inside open keyed maps** (the user-named entries in `containerGrids`, `connectedContainerGroups`, `sites`, `barcodeLocations`, `presenceDetectionZones`, `collisionShapes`, `assembly.components`) follow snake_case. Two styles cover newly-authored labware:

- **Semantic names** for special-purpose entries: `magnet_site`, `lid_park`, `waste_site`, `dispense`, `collection`, `pyramids`, `pool`, `base_center`, `corner_tab`. Pick a name that conveys the entry's role.
- **Letter-prefix ordinals** for numbered series: `pos_1`, `pos_2`, ..., `pos_10` for carrier positions; `A1`, `B1`, ... for grid containers using SBS-style (ANSI/SLAS microplate standard) naming.

The schema pattern (`^[a-z0-9][a-z0-9_-]*$`) also accepts **bare ordinal numbers** (`1`, `2`, ..., `24`, `96`) — use them only on conversion from VENUS, InstinctV, or MLPrep, to preserve the source labware's original numbering without injecting a `pos_` prefix. Avoid bare numbers in fresh authoring — letter-first keys are easier to distinguish from numeric values in tooling, and don't trigger JS's numeric-key iteration reordering (numbers-as-keys enumerate first in numerical order, before string keys, regardless of insertion order).

### 1.2 Naming choices worth knowing

A few schema names use a deliberately broader sense than their colloquial lab meaning. Knowing the reasoning prevents misreads.

**`containerGrids` / `ContainerDefinition`.** A "container" here names the *physical cavity* at a grid position, not the contents that occupy it. The cavity geometry (opening dimensions, depth, volume model) applies whether the position holds liquid directly (a well), a tip (`contentsRef → probe`), or a tube (`contentsRef → tube`). The schema separates the cavity (`ContainerDefinition`) from what occupies it (`contentsRef`).

This deliberately collapses InstinctV's opening-plus-occupant split — a `CldeHole` (the opening) holding a `CldeHoleItem` (a `CldeContainer` cavity, a tip, or nested labware) — to one cavity concept plus an optional content pointer. VENUS-experienced reviewers will recognize `Container` as the same concept VENUS uses (with `SingleContainer` for shared-geometry-across-positions). InstinctV-experienced reviewers should appreciate the simplification to two orthogonal concepts: geometry in `ContainerDefinition`, contents named by `contentsRef`.

Alternative names that were considered and rejected:

| Alternative | Why rejected |
|---|---|
| `holes` (InstinctV term) | Negative framing — "hole" implies a gap, not a structured cavity with opening, depth, and volume model. |
| `wells` | Too liquid-specific; reviewers familiar with SBS would expect liquid-only and be confused by tip racks declaring `wells`. |
| `positions` | Too abstract; the schema also has grip positions, alignment positions, sensor positions. Reusing dilutes meaning. |
| `slots` | Suggests a discrete insertion shape that doesn't fit liquid wells. |
| `cavities` / `receptacles` | Precise but jargon-heavy and unfamiliar in lab-automation discourse. |

**`labwareClass: "tube"` versus `"tube_rack"`.** A `tube` is a single-tube labware definition (geometry of a single tube — wall thickness, depth, opening, volume model). A `tube_rack` is a multi-position rack whose positions hold tubes (via `contentsRef → tube`). The split mirrors `probe` (single tip) versus `tip_rack` (rack holding tips). A standalone tube on a deck site uses `labwareClass: "tube"`; a rack of 24 tubes uses `labwareClass: "tube_rack"` with each grid position's `contentsRef` pointing at the tube definition.

**`probe` versus `tip` or `needle`.** A `probe` is the abstract category covering disposable tips, reusable needles, and any future channel-mounted pipetting consumable. The discriminator `isReusable` separates a disposable tip (`false`) from a reusable needle (`true`) — "reusable" here meaning washed and re-mounted across runs, *not* whether the probe can perform multiple aspirate/dispense steps. A disposable tip is freely reused for many transfers without washing before it is ejected; what makes it `isReusable: false` is that it is ultimately discarded rather than cleaned and returned to service. Using the more specific `tip` or `needle` as the class would force a two-class split where one suffices; `probe` covers both with one cleaner data shape.

### 1.3 Publisher form vs bare vocabularies

Two open-identifier conventions coexist, distinguished by whether the content is *vendor-owned* or a *shared vocabulary*:

- **Publisher form** (`publisher:identifier` or `publisher:concept`) — for vendor-owned surfaces where the namespace owner is meaningful and collision protection matters: the labware `id` and its references (`contentsRef`, `labwareRef`), per-instrument map **keys** (`gripPoints`), and `customAttributes` namespace **keys**.
- **Bare snake_case** — for shared semantic vocabularies coordinated by convention between consumers and owned by no single vendor: classification and type **values** (`labwareClass`, `material`, `ToolData.kind`, `MountInterface.mountKind`, alignment `name`, bare `tags`), and author-named structural map **keys** (`containerGrids`, `connectedContainerGroups`, `sites`, `barcodeLocations`, `presenceDetectionZones`, `collisionShapes`, `assembly.components`).

The split is intentional. A vendor's `customAttributes["hamilton:star"]` is Hamilton's namespace to fill, so publisher form protects it from collision and names the owner. But an alignment `name` of `sbs_rim` is a name a site and a labware must *agree on* to engage — making such a shared mating publisher-owned would split up a vocabulary that only works when coordinated, so it stays bare. The same reasoning makes `labwareClass`, `material`, and tool `kind` bare. (The `urn:` form is a third, separate convention, reserved for the schema documents' own `$id`.)

### 1.4 Open-vocabulary vs closed-enum fields

**Criterion.** A field's vocabulary is **OPEN** when a consumer can degrade gracefully on an unrecognized value — it skips, defaults, or passes the value through without breaking correctness. A field's vocabulary is **CLOSED** (a schema enum) when the runtime must understand every value to behave correctly — an unknown value is an error, not a graceful skip.

**Closed fields** — the schema enforces the complete value set:

| Field | Reason |
|---|---|
| `ContainerGrid.iterationOrder` (`column_major \| row_major`) | Determines which physical tip slot maps to linear index N; a wrong value silently mis-orders multi-channel picks. |
| `ConnectedContainerGroup.connectionTopology` (`base \| side \| full \| merged_above`) | Drives volume-pooling math; an unknown topology has no safe default. |
| `IntraLabwarePassthrough.mode` / `ContainerPassthrough.mode` (`one_to_one \| one_to_many \| many_to_one \| mapped`) | Drives volume distribution logic; unknown mode cannot be skipped. |
| Opening/container shape enums (`openingDimensions.shape`, `inferredFromShape.shape`, `Solid3D.type`) | Drive volume-integral geometry; an unknown shape type cannot be approximated. |

**Open-vocabulary fields** — the schema enforces the snake_case pattern only; recommended values are listed here so the catalog stays consistent, but consumers must not reject unrecognized values:

| Field | Recommended values |
|---|---|
| `labwareClass` | `plate \| tip_rack \| tube_rack \| carrier \| reservoir \| probe \| tool \| lid \| assembly \| tube \| adapter` |
| `material` | `polypropylene \| polystyrene \| polycarbonate \| cyclo_olefin \| glass \| quartz \| stainless_steel \| aluminum \| peek` |
| `ProbeData.probeType` | `standard \| wide_bore \| low_retention \| needle_blunt \| needle_beveled` |
| `ToolData.kind` | `gripper \| barcode_reader \| optical_sensor \| force_sensor` |
| `MountInterface.mountKind` | `channel \| robot_wrist` |
| `Alignment.name` | `sbs_rim \| sbs_lid \| mfx_module \| pcr96_well_cradle \| pcr384_well_cradle \| core_tip_rack \| deck_track \| flat_base` (and others; §5) |
| `PresenceDetectionZone.compatibleSensors` items | `optical \| capacitive \| ultrasonic \| weight \| vision` |
| `VisualModel.modelFormat` | `obj \| stl \| gltf \| glb \| step` |

For `PresenceDetectionZone.compatibleSensors`: a consumer whose instrument lacks the named sensor type skips that zone rather than failing, so an unrecognized value is safe to ignore. For `VisualModel.modelFormat`: a renderer that does not support the named format falls back to bounding-box rendering rather than failing, so an unrecognized value is safe to skip. For `MountInterface.mountKind`: the bidirectional block coupling binds only the known kinds (`channel` requires the `channel` block, `robot_wrist` the `robotWrist` block), so an unrecognized kind requires no sub-block and a consumer that cannot drive that mount skips it rather than failing validation — the same open-vocabulary posture as `labwareClass` and `ToolData.kind`.

## 2. Recommended labwareClass values

`labwareClass` is the primary structural discriminator. The schema accepts any snake_case identifier; four recommended values (`probe`, `tool`, `assembly`, `tip_rack`) require a matching class-specific block. `lid` and all other recommended values use only common fields plus `customAttributes`. Custom values (for example `magnetic_stand`, `heating_block`) also use only common fields plus `customAttributes`.

### 2.1 plate

A multi-well microtiter plate. Pick this value when the labware presents a regular grid of wells holding liquid samples and is itself loaded as a unit. Use `tube_rack` if the wells hold removable tubes; use `reservoir` for a single large cavity or a small number of large cavities. No class-specific block; geometry lives in `containerGrids`.

### 2.2 tip_rack

A rack of disposable or reusable pipetting tips. Pick this value when the positions hold tip or needle labware, addressed through `contentsRef`. Use `tube_rack` if the positions hold tubes. Requires the `tipRack` block, which carries rack-level structural properties (`style`: `nestable` or `framed`) beyond what `containerGrids` plus `contentsRef` express.

### 2.3 tube_rack

A rack of tube positions. Pick this value when the positions hold tube labware (addressed through `contentsRef`) rather than the liquid samples themselves. Use `plate` for fixed-well plates; use `tip_rack` for tip positions. No class-specific block.

### 2.4 carrier

A deck-mountable carrier with sites for other labware. Pick this value for deck carriers, multiflex bases, modules, pedestals, waste carriers, and lid park carriers — anything whose primary role is to hold child labware at known sites on the deck. The sites map and alignment features carry the structural detail. No class-specific block.

### 2.5 reservoir

A single- or multi-chamber liquid container — troughs, waste reservoirs, divided pans. Pick this value when the labware is a bulk liquid container rather than a grid of independent wells. Use `connectedContainerGroups` to model divided reservoirs whose chambers share a single volume pool. No class-specific block.

### 2.6 probe

A channel-mounted tip or needle (disposable or reusable). Pick this value when authoring a tip or needle definition that will be referenced from a `tip_rack` container's `contentsRef`. Requires the `probe` block, which carries public physical fields (collar height, length, liquid-level detection (LLD) support, mount interface); the tip's proprietary internal geometry is not modeled.

### 2.7 tool

A channel- or wrist-mountable transport item — grippers, paddles, sensors, readers. Pick this value when the item is mounted on an instrument channel and performs a non-pipetting action. The `tool` block subdivides by `kind` (for example `gripper`, `sensor`) with kind-specific physical-property sub-blocks. Operations are not modeled; the schema captures jaw geometry, sensor specs, and the mount interface only.

### 2.8 lid

A removable cover for a plate or other labware. Pick this value for any cover that is gripped, lifted, and placed back — distinct from heat-sealed films or adhesive foils (which are out of scope for v1 and may receive a `seal` class later). A lid carries no class-specific block; the lid seats through the alignment contract — an `sbs_lid`-style alignment feature whose `offset` carries the seating height — not a separate `nestingDepth`.

### 2.9 assembly

A pre-configured multi-labware stack — for example filter plate plus collection plate plus lid, or layered consumables. Pick this value when the catalog entry represents the composed stack rather than the individual pieces. Requires the `assembly` block, which lists components seated on their parents by matching alignments — the effective stack height derives from the component heights and their seating offsets, not a separate nesting depth — and routes volume through filter layers via `containerPassthrough`.

### 2.10 tube

A single-position tube definition. Pick this value when authoring a tube that will be referenced from a `tube_rack` container's `contentsRef`. Also acceptable for standalone single-tube labware (a microcentrifuge tube loaded directly on a deck site). No class-specific block; the tube's geometry lives in a single-container `containerGrids` entry.

### 2.11 adapter

A passive mechanical fitting with no containers — shims, spacers, magnetic stands, alignment plates, mounting frames. Pick this value when the labware exists to position other labware but does not itself hold liquid or tips. Sites and alignment features carry the structural detail. No class-specific block.

### 2.12 Custom labwareClass values

Authors may use any snake_case identifier matching the pattern. Custom values (for example `magnetic_stand`, `heating_block`, `centrifuge_rotor`, `shaker_platform`, `wash_station`) get no required class-specific block. They may carry class-specific blocks of their choice when the labware item physically plays one or more of the recommended-class roles — a `wash_station` may carry both `containerGrids` (the wells role) and a `tipRack` block (the tip-cleaning role). When a custom value sees broad adoption, propose its addition to this document by pull request. Promotion of a custom value to a recommended class with its own owned block requires a schema change.

### 2.13 Multi-role labware: recommended class vs. custom class

Some labware items physically play more than one role at once — a wash station with both wells and tip-cleaning channels; a magnetic carrier-plate that both aligns onto a deck and holds magnets for separation; a heat-sealing plate with an embedded reagent reservoir. The schema lets a single definition carry the class-specific blocks for each role the item plays. The author's choice is how to name the item via `labwareClass`. Two patterns:

| Pattern | Use when | Example |
|---|---|---|
| **Recommended class with additional blocks** | The item is recognizably a [class] with extras. Customers and consumer filters expect it under that class. | A plate with an integrated tip-eject channel — still a plate to operators. `labwareClass: "plate"` + `containerGrids` + additional `tipRack` block. |
| **Custom class with the relevant blocks** | The item is its own kind of thing. Customers say "wash station" or "magnetic stand," not "a plate that also…". | A molded wash station. `labwareClass: "wash_station"` (custom) + `containerGrids` + `tipRack` block. |

Rule of thumb: if a customer asked "what is this?" and would not name a recommended class first, use a custom class. The schema validates the same either way; the choice is naming for consumers.

## 3. Recommended tag vocabulary

The `tags` field accepts two shapes: bare tags (`deep_well`) and publisher-namespaced tags (`hamilton:validated`). Bare tags are recommended for cross-cutting properties listed below; publisher-namespaced tags are recommended for vendor-specific or customer-specific labels (`hamilton:validated`, `mylab:gmp_approved`).

### 3.1 Footprint and form factor

| Tag | Meaning |
|---|---|
| `sbs_footprint` | ANSI/SLAS standard SBS footprint (127.76 by 85.48 mm) |
| `deep_well` | Deep-well variant of a plate format |
| `low_volume` | Low-volume variant (small per-well volume) |
| `half_skirted` | Half-skirted PCR plate format |
| `full_skirted` | Full-skirted PCR plate format |
| `frosted` | Frosted writing surface present |

### 3.2 Treatment

| Tag | Meaning |
|---|---|
| `sterile` | Manufactured sterile |
| `autoclavable` | Tolerates standard autoclave cycles |
| `dnase_free` | DNase-free |
| `rnase_free` | RNase-free |
| `low_retention` | Low protein or nucleic-acid retention |

### 3.3 Material qualifiers

| Tag | Meaning |
|---|---|
| `conductive` | Conductive material (typical for probes used with capacitive LLD) |
| `filtered` | Carries an internal filter (typical for filtered tips) |
| `anti_static` | Anti-static treatment present |
| `gel_loading` | Gel-loading geometry (typical for narrow flat-tipped probes) |

### 3.4 Lifecycle

| Tag | Meaning |
|---|---|
| `single_use` | Intended for a single use |
| `reusable` | Intended for repeated use |
| `validated` | Customer-side validation completed |
| `deprecated` | Author has marked this definition as not for new use |
| `beta` | Pre-release or pilot-only |

### 3.5 Application

| Tag | Meaning |
|---|---|
| `pcr` | Designed for PCR |
| `qpcr` | Designed for qPCR |
| `cell_culture` | Designed for cell culture |
| `elisa` | Designed for ELISA |
| `dna_purification` | Designed for DNA purification |
| `protein_assay` | Designed for protein assays |

### 3.6 Publisher-namespaced tags

Vendor-specific or customer-specific tags use the publisher form `publisher:label`. Common patterns:

- `hamilton:validated` — Hamilton has validated this definition against the referenced labware.
- `hamilton:autoload_supported` — Hamilton autoload reader can read this labware's barcode.
- `mylab:gmp_approved` — internal GMP approval marker (example customer namespace).

Authors are free to introduce additional publisher-namespaced tags; the publisher portion is bound by the publisher-namespace policy.

## 4. Site purpose convention

The labware schema does not model site purpose (waste, tool dock, lid park, teach fixture, tip eject) as a typed `role` field. Site purpose is conveyed by a vendor-namespaced `customAttributes` entry **on the site itself**. The recommended Hamilton key is `hamilton:site_purpose`; its value is an object naming the purpose.

```json
"sites": {
  "waste_drop": {
    "customAttributes": {
      "hamilton:site_purpose": { "purpose": "waste" }
    }
  }
}
```

A consumer that needs "the waste site for this carrier" scans the labware's `sites` for one whose `customAttributes['hamilton:site_purpose'].purpose` is `waste`. Because the attribute lives on the site, it cannot dangle (there is no separate site id to resolve), more than one site can share a purpose, and a site can carry more than one publisher's purpose data side by side. Custom publishers may mirror the pattern under their own namespace key.

### 4.1 Recommended purpose values

| `purpose` value | Meaning |
|---|---|
| `waste` | Liquid waste is delivered here. |
| `tip_eject` | Used tips are ejected here. Distinct from `waste`, which is for liquid. |
| `tool_dock` | A tool parks here when not mounted on a channel. |
| `lid_park` | A lid is parked here while the plate underneath is in use. |
| `teach_fixture` | Holds a teaching or verification fixture. |
| `magnetic_separation` | A plate seats here for magnetic-bead separation. The site usually still seats the plate by its rim, with the magnets between the wells (§5.5). |

Custom purposes follow the same shape under the same key (`hamilton:site_purpose` → `{ "purpose": "<snake_case>" }`). Where a purpose needs more than a label — a tool dock that names which tool it docks, for example — the value object carries additional fields the namespace owner defines: `{ "purpose": "tool_dock", "tool": "hamilton:iswap" }`.
## 5. Alignment names and the common mechanisms

The alignment `name` is the compatibility key shared by alignment features (on the placed part) and alignment receptacles (on the supporting part): a feature and a receptacle that share a name mate, by exact string equality, and the offsets then position the part. This section records the naming convention behind that name-matching, symmetric feature/receptacle model.

Because the name *is* the gate, it identifies a specific mating **interface**, not merely a mechanism. Name it by the footprint or family and the role — `sbs_rim` for an SBS skirt seating on a carrier, `sbs_lid` for an SBS lid seat, `pcr96_well_cradle` for a 96-well PCR cooling block — or by the product coupling — `mfx_module`, `core_tip_rack`, `deck_track`. A bare `rim_seat` would be too coarse: every rim-seating part of any footprint would match, and the name would stop meaning "these actually mate." The footprint, pattern, or product qualifier is what carries that meaning. The schema enforces only the snake_case shape (optionally a `publisher:` prefix for a deliberately vendor-private mating); it does not close the vocabulary, and there are no per-type geometric fields — an alignment is a `name` plus an `offset` (`{ z }`, with `x`/`y` optional and defaulting to the footprint center). Fit beyond the name match is an advisory comparison of the placed part's footprint against the site's `footprint`, never a hard gate.

The subsections below describe the common mating **mechanisms** that an interface name names an instance of. The mechanism guides the offset and the contact geometry; the name records *which* interface it is. A part that can seat more than one way declares one feature per mechanism, and the **greatest-resting-Z** rule picks whichever contacts first.

**Converted definitions: what counts as an alignment.** Legacy VENUS / InstinctV / MLPrep definitions carry several kinds of "alignment" data, and conversion applies a single test: *does the entry name a physical mating surface present on this item?* A surface that mates — a rim seat, a module pin — becomes an alignment feature or receptacle with its measured offset. An entry that names software behavior rather than a surface — a site-alignment profile selector (`Framed`, `SingleNTR`, `HHS1Adapter`), a per-adapter rule configuration (`HHC_67391_02`), an alignment-rule parameter (`zOffsetBetweenAlignmentSurfaces`) — is preserved under the owning publisher's `customAttributes` namespace instead: the typed-rule layer those entries configure is deliberately not part of the alignment contract. Deck-layout-editor facts (snap and boundary flags) are dropped entirely — no runtime consumes them.

### 5.1 Flat surface

A flat contact plane with no in-plane locating: the part rests on the plane and its X/Y comes from another feature or from gravity. The `offset.z` carries the contact height. A skirtless labware that simply lands on a deck or block is the typical case (`flat_base`).

### 5.2 Rim seat

The part's outer rim or skirt drops onto a recessed ledge that locates it by its perimeter — the classic SBS microplate into a carrier position (`sbs_rim`). The `offset.z` is the rim-bottom contact height (a few millimeters up the plate body, not the very bottom of the skirt); `offset.x`/`offset.y` default to the footprint center. The ledge envelope is not modeled on the alignment — matching is by name, and an over-size footprint versus the site's `footprint` is only an advisory warning, never a hard gate.

### 5.3 Nest

The part rests on a raised central feature on the support rather than on its own rim — the feature contacts the container bases or underside and lifts the part off the carrier surface, which improves capacitive liquid-level detection and bottom-of-well pipetting. The `offset.z` is the height of the surface that rests on the raised feature.

Nest seating — a single raised center — is not the PCR-plate case: skirted PCR plates seat by `sbs_rim` on a carrier and, on a thermal block, drop into it by their wells. That distributed per-well contact is a different geometry a single nest cannot capture — the well-cradle mechanism (§5.7), which such plates also declare.

A part that can seat either on its rim or on a raised center declares both an `sbs_rim` feature and a nest feature (e.g. `sbs_nest`). Which one actually rests depends on the specific support — whether the part's container-base-to-rim distance exceeds the support's raised-center height decides which surface contacts first. The runtime resolves this per placement by greatest resting Z, so one definition seats on its rim on one carrier and on its container bases on another, with no per-carrier variant.

### 5.4 Pin and hole

A pin on one side engages a matching hole on the other, locating the pair precisely and — because the pin sits off-center — fixing rotation. Multiflex modules onto a Multiflex base are the canonical case (`mfx_module`). The pin or hole position relative to the origin is the `offset` (`x`/`y` the in-plane pin location, `z` the contact height); no pin diameter is modeled — matching is by name.

### 5.5 Magnetic

A magnetic pad or insert holds the part against the support by magnetic force rather than a mechanical fit. Note that a magnet stand usually still *seats* the plate by its rim — the Alpaqua Magnum is an `sbs_rim` landing with the magnets between the wells — so the magnetic role is recorded as the site's purpose (`hamilton:site_purpose`), and a dedicated magnetic name is needed only when a skirtless part rests directly on the magnet face.

### 5.6 Snap fit

Flexible projections — clips or tabs — on one side snap into matching recesses on the other, holding by elastic deformation. Like every alignment it carries only `name` plus `offset`; matching is by name.

### 5.7 Well cradle

A plate seats by its array of wells dropping into a matching array of pockets the support presents — a thermocycler-style cooling or heating block milled to cradle every well (`pcr96_well_cradle`). Unlike a nest (a single raised center) or a rim seat (the perimeter skirt), the locating contact is distributed across the whole well array, so the plate is held by its underside cone geometry rather than by its rim. The placed plate's `offset.z` is where its wells bottom out, and the detailed pocket array stays in the support's `visualModel`, not in the alignment. The cooling block is the receiving side; a 96-well PCR plate carries the matching `pcr96_well_cradle` feature. A plate that can also seat by its skirt declares both `sbs_rim` and the well-cradle name, leaving the runtime to resolve which contacts first (§5.3). The name is density-specific so a 96-well plate never false-matches a 384 block: a 384-well PCR plate carries `pcr384_well_cradle`.

### 5.8 Self-stacking: the `selfStack` shorthand

Same-definition stacking — a plate resting on an identical plate in a stacker or hotel — does not need a hand-authored alignment pair. Declare `selfStack: { height }` on the labware root, where `height` is the stack pitch (the Z rise per copy, less than the full height when copies nest). The consumer expands it internally to a self-matching alignment keyed off the definition's own id, so only an identical copy stacks and the opaque per-type names this would otherwise need never appear. Cross-type stacking (a copy resting on a *different* compatible labware) still uses an explicit shared alignment name. Declaring both `selfStack` and an explicit self-matching pair for the same definition is an authoring error the validator rejects.

### 5.9 Occupant seating in a container position

A tip or tube that rests on a container's floor needs no alignment: `contentsRef` plus the grid geometry (`firstContainerCenter.z`) locates it. When the occupant instead hangs — a tip on its collar shoulder — or is biased to one side by a leaf-spring, declare an `alignmentReceptacles` array on the `ContainerDefinition` and a matching `alignmentFeatures` entry on the occupant. The offsets are relative to the cavity floor, and where several occupants seat differently in the same position the greatest-resting-Z rule picks the contact.

Every alignment — whatever its name — carries the same shape: a `name` plus an `offset`, with no per-type geometric fields. Matching is by name; a custom name's physical meaning is documented under your publisher namespace.

## 6. Adding a custom class, tag, alignment name, or convention key

The schema's open-vocabulary discipline (pattern-bounded freedom rather than closed enums) is deliberate. The labware ecosystem covers many vendors and customer workflows; closed enums would either freeze the catalog or force schema-version changes for routine additions. The pattern constraint (lowercase letters, digits, underscore, hyphen, starting with a letter) keeps the values machine-readable and rejects typos like `Rim_Seat` or `rim set`.

To add a custom value:

1. **Pick the right surface.** A new structural category goes in `labwareClass`. A new descriptive label goes in `tags`. A new mating interface goes in an alignment feature/receptacle `name`. A new vendor-specific extension goes in `customAttributes` under your publisher namespace.
2. **Use the snake_case pattern.** Lowercase letters, digits, underscore, hyphen; start with a letter. The schema rejects other shapes at validation time.
3. **Choose the right namespace.** Bare values (no publisher prefix) are reserved for cross-cutting concepts documented here. Vendor-specific values use the publisher form `publisher:value` for tags or `publisher:concept` for `customAttributes` keys. The `hamilton` publisher is locked via signing; other publishers register under their own namespace.
4. **Coordinate with consumers.** A custom value that no consumer reads adds no behavior. Document the value alongside the consumer that interprets it. When the value sees use across multiple publishers or vendors, propose its addition to this document by pull request.
5. **Publish a value-shape schema for `customAttributes` payloads.** The schema treats `customAttributes` values as opaque JSON. The owning publisher is responsible for the value shape; publishing and maintaining a JSON Schema for each namespace's payload is the recommended discipline.

The pattern-bounded approach yields three properties that closed enums cannot match: vendors extend without schema-version changes; typos and casing errors still fail validation; and the canonical recommended set in this document remains discoverable to authors and consumers without restricting authoring freedom.

## 7. Reserved publishers and the `mlapi:discovery` namespace

The publisher portion of a two-segment key — a labware `id`, a per-instrument map key, or a `customAttributes` namespace — is open, with these reservations:

| Publisher | Status |
|---|---|
| `hamilton` | Publisher-locked: only Hamilton-signed definitions may use it. |
| `mlapi` | Reserved for Hamilton built-in kinds, validators, runtime extensions, and metadata such as `mlapi:discovery`. Authors do not register labware or `customAttributes` under it. |

### 7.1 `mlapi:discovery`

`mlapi:discovery` is a reserved `customAttributes` namespace carrying opt-in metadata that helps AI agents reason about labware equivalence — the catalog deliberately has no Meta-Labware type, so agents reason over rich metadata instead. It is opt-in: a definition without it is not penalized, and agents fall back to the structured fields (`manufacturer`, `dimensions`, `containerGrids`, `tags`).

```json
"customAttributes": {
  "mlapi:discovery": {
    "applications":            ["genomics", "high_throughput_screening"],
    "incompatibleWith":        ["protein_a_affinity"],
    "preferredAlternativeIds": ["acme:plate_xyz"],
    "notes":                   "Validated for 200 uL fill volume"
  }
}
```

The namespace owner (Hamilton) maintains this value shape. It is recorded here so the convention has one authoritative home.

### 7.2 Instrument concepts (`gripPoints` keys)

Per-instrument maps — `gripPoints` today — are keyed by a two-segment `publisher:concept` instrument identifier naming a gripper or transport mechanism. The schema enforces only the key syntax, so this list is the registry that tells authors which concepts exist to target. New concepts (Hamilton or third-party) are registered here.

| Instrument concept | Notes |
|---|---|
| `hamilton:iswap` | iSWAP plate-handler grip |
| `hamilton:core_grip` | CO-RE gripper |
| `hamilton:core_paddle` | CO-RE paddle |
| `hamilton:track_gripper` | track-mounted gripper |
| `hamilton:lablync` | LabLync transport |

A third party registers its own under its publisher namespace (e.g. `acme:fingertip`). The same `publisher:token` can name both a `gripPoints` concept and a `customAttributes` namespace (§7) — distinct surfaces told apart by the field the key appears in, not by syntax.

## 8. Coordinate anchoring: corner vs. center

Positions are expressed in the labware coordinate frame, whose origin is the **left-front-bottom corner** of the bounding box (X+ right, Y+ back, Z+ up). Within the frame, one rule covers everything placed:

> The `dimensions` bounding box is measured from the datum corner (it *is* the datum's extent). **Everything placed within the frame — container positions (`firstContainerCenter`), `sites`, `collisionShapes`, `presenceDetectionZones`, and `gripPoints` — is anchored at its center.**

| Anchored at the datum **corner** | Anchored at its **center** |
|---|---|
| `dimensions` — the outer bounding box (the corner-datum envelope) | `containerGrids.firstContainerCenter` — a well / position |
| | `sites[].origin` — a child labware seats here (the labware-level analog of a container position) |
| | `collisionShapes[].origin` — center in X/Y, base in Z |
| | `presenceDetectionZones[].center` |
| | `gripPoints[].center` |

Sites are center-anchored, not corner-anchored, for consistency: a site is the labware-level analog of a container position — both are "a child seats here, carrying its own alignment receptacles" — and a container position is already anchored at its center (`firstContainerCenter`). Center anchoring also keeps `rotationZ` coherent (a rotated site or receptacle pivots about its center, so the origin *is* the pivot) and gives authors one model. Engineering drawings and prior systems vary — some dimension a site to its center, others to a corner or edge. VENUS, for example, locates a carrier's sites by the site's front-left corner (a five-position plate carrier dimensions its site corners at 96 mm pitch), so converting a VENUS site to a labware-schema site `origin` adds half the footprint once to reach the center — even though the labware *frame* itself is the same left-front-bottom corner in both systems. The same half-footprint step applies to any corner- or edge-dimensioned drawing.

A barcode is the one location that is neither: `barcodeLocations[].zone` places a label rectangle by its `origin` + `width`/`height` in the face's own u/v plane.

Alignment offsets default a missing `x`/`y` to the carrying object's footprint center, so the common centered seat states only `z` — for a center-origin object that resolves to the origin itself.
