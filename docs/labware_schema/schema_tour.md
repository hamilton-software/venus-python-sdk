# A Tour of the Hamilton Labware Schema

This is a narrative companion to the Hamilton labware JSON schema. It is meant for everyone who reviews or consumes the schema — engineers, architects, product managers, applications support, and customers — some with VENUS or InstinctV / MLPrep background, some with none. The schema document itself is the reference; this document makes the *shape* and the *intent* obvious before anyone has to read a `$ref` or a JSON-schema keyword. By the end you should be able to answer: why a new structure, and why this model rather than the alternatives; what a definition looks like top to bottom; where it deliberately stops; and where extensions go.

The schema covers everything Hamilton instruments treat as labware: microplates, tip racks, tube racks, carriers, reservoirs, lids, assemblies, single tubes, mechanical adapters, and — significantly — *probes* (tips and needles) and *tools* (grippers, sensors, readers) as first-class members of the same family.

**Using this with the SDK:** the schema files sit alongside this tour ([`labware.schema.json`](labware.schema.json) plus the `geometry`, `alignment`, and `site` schemas). In this SDK you build a definition with `hamilton_venus.labware_builder` and send it to VENUS with `StarClient.labware_add_definition` — see the [labware builder guide](../examples/advanced/labware_builder.md).

---

## 1. Why a new labware structure

Hamilton has described labware before, and most readers will know at least one prior model. **VENUS** — the established platform holding the largest installed base of Hamilton labware definitions — is fast to author and simple, but it has a well-known failure pattern: hardware-alignment problems are fixed by editing the labware definition, so one physical plate accumulates many near-duplicate definitions that differ only by small tolerance corrections. **InstinctV** — a newer-generation model whose data layer continues in MLPrep — was richer and more typed, with runtime-resolved alignment and an attempted separation of definition from calibration; but rich definitions proved heavy to author, the separation leaked in practice, and process and operational data lived in the definition. **MLPrep** adds a curated catalog and image metadata on top of InstinctV and is widely regarded as successful, in part because the catalog is tightly controlled.

So the first decision was not which fields to define. It was: **what kind of artifact should be the authoritative description of a labware item?** §1.1 lays out the candidate foundations and the chosen one. The sections after it unpack what the choice delivers: the definition describes **physical reality only** (§1.2), one definition scales **from minimal to extensive** (§1.3), and everything stands on a **modern, content-addressed JSON foundation** built for versioning and GxP (§1.4). The rest — typed concepts, simplified alignment, namespaced extension — is §1.5.

### 1.1 The foundation choice

Four candidate foundations were considered. Each is a defensible position; the table states what each optimizes and why it was not chosen, and the paragraphs after it expand the two that raise the most reviewer questions. This section carries the reasoning in full.

| Candidate foundation | What it optimizes | Why it is not the foundation |
|---|---|---|
| **A true geometric model** — a 3D artifact (glTF, STEP, a mesh) *is* the definition; dimensions, volumes, and collision data are derived from it | Fidelity — one artifact serves visualization, collision, and volume | Most labware authors work from a specification sheet, not CAD; some internal geometry is protected IP; every consumer would need a geometry engine to answer questions a number answers directly |
| **The VENUS model, adopted as-is** | Authoring economy; compatibility with the largest existing catalog | The data is proven; the packaging is not — COM files with embedded XML, identity by filename, no publisher, no tamper evidence, extension only through an opaque XML trait blob, one grid per rack |
| **The InstinctV model, progressed** | Typing and rigor; runtime-resolved alignment already worked | Heavy to author; the definition/calibration separation leaked; operational data sits in the definition; identity is a bare GUID with no publisher signal and no integrity check |
| **An open ecosystem format** (Opentrons, pylabrobot) | Community familiarity and tooling | Not built for Hamilton's hardware range (probes, tools, carriers, multi-grid labware) or for regulated provenance |

**Why not the true geometric model.** It is the obvious modern answer, and it was seriously considered. Three facts ruled it out as the *authoritative* source. First, authoring: labware definitions are written by application engineers, lab managers, and vendors working from a manufacturer's specification sheet — numbers, not CAD — and Hamilton's own experience extracting working dimensions from CAD, in both VENUS and InstinctV, was cumbersome even for the engineers who designed the parts. Requiring a maintained 3D model would make the most common authoring case the hardest one. Second, IP: a tip's internal bore profile or a vendor's mechanism geometry often cannot be shipped at all, while its public physical facts — outer dimensions, volumes, mount measurements — can. Third, consumer cost: collision checking is optional in many deployments, but pipetting is not, and a volume-at-height question must be answerable from plain fields without a geometry engine. So geometry is declared as numbers a specification sheet supplies directly. The 3D model is not gone: it returns as an optional, non-authoritative `visualModel` asset (§11), and the shared geometry model deliberately leaves room for a detailed-geometry tier to be added later without changing this foundation.

**Why VENUS's data, but not VENUS's format.** For two decades Hamilton instruments have pipetted into, moved, and detected labware described by the VENUS parametric core — footprint, grid layout, container geometry, volumes. That data set is the most widely supported description of labware Hamilton has, and its long routine use demonstrates it is sufficient to drive an instrument. What failed was everything around the data: identity by filename with no publisher and no tamper evidence, an opaque extension blob, one grid per rack, and — the deepest problem — nowhere to put alignment knowledge except the geometry itself, which is exactly why tolerance corrections get edited into definitions. This schema therefore keeps the *data* as its required core and replaces the *packaging*: the same specification-sheet numbers, in JSON, under publisher-namespaced, content-addressed identity, with a named alignment contract (§8) so one definition seats on any compatible carrier — and the deployment-specific tolerance itself moves out of the definition onto the system (§1.2).

**The chosen model, in one rule.** Every field in the core passes two questions. *Can a typical labware author supply it from the manufacturer's specification sheet or a simple measurement?* If not, it cannot be required. *Does some instrument operation need it to behave correctly?* If not, it does not enter the core at all — `tags` and `customAttributes` absorb it. "Enough for instrument usage" is concrete: pipetting (container geometry and the volume model), placement (alignment and sites), transport (grip points and weight), identification and presence detection (barcode locations and detection zones), and collision checking (outer dimensions and collision shapes). The result is the simplest definition an author can write that still tells an instrument everything it needs — minimal like VENUS, typed where typing helps the consumer like InstinctV, with the alignment contract kept from InstinctV in simplified form, and publisher namespacing and content-addressed versioning added because the legacy systems showed what their absence costs.

A practical consequence of building on the proven data core: the existing catalog converts. A VENUS, InstinctV, or MLPrep definition already contains the required data, so conversion is mechanical and recorded (`source`, §3.3); authoring a new minimal definition is no more work than authoring a VENUS rack was (§12 walks through one).

### 1.2 Physical reality only

The schema describes the **physical reality** of a piece of labware — its outer envelope, internal geometry, alignment features, the sites it exposes, the barcodes on its body — and nothing else. Everything about how a *specific instance* sits in a *specific deployment* — where it is placed, how well it is calibrated there, any user adjustment after teaching — lives on whatever system Part the labware is loaded onto (a deck site, a carrier position, or a standalone device's site such as a heater-shaker), never in the labware definition.

VENUS bakes tolerance straight into the geometry — which is how an apparently unchanged Nunc 96-well plate accumulates a spread of subtly different `.rck` definitions across an applications team. InstinctV went further and carried much richer data, but some of it was process- and operation-related, and the definition-versus-calibration separation it *attempted* — the same split this design makes — leaked in practice. Keeping pose, calibration, and process on the system rather than in the definition is the right goal; this schema is where it actually holds. One Nunc plate is one definition; per-instrument deltas live on the system Part. (How that placement is layered and given provenance is a *system* concern, described by the system schema and its own documentation.)

Read the physical-reality discipline on its own and the schema looks oddly minimal in places; read it knowing that anything deployment-dependent is the system's job, and the cuts make sense.

### 1.3 One definition, minimal to extensive

You used to choose: VENUS labware is quick to author but thin; InstinctV labware is rich but heavy to produce. This schema collapses that choice: the same schema holds both a bare definition (just enough to pipette) and a fully measured one, and nothing forces the richer form when you only have the simpler. A minimal plate carries a few numbers; a validated assay plate carries a measured height-volume curve.

The **volume model** is the clearest example. A pipettable container has a shape that gives a volume-at-height function, but real labware deviates from ideal geometry — draft angles, fillets, meniscus effects, tolerances — so the parametric formula and the actual height-volume curve disagree. `volumeModel` lets you supply up to three tiers — pick whichever you have:

```json
"volumeModel": {
  "lookupTable": { "0.0": 0, "5.0": 96.8, "10.0": 193.6 },
  "segments":    [ { "type": "conical_frustum", ... } ],
  "inferredFromShape": { "shape": "flat_bottom_cylinder", ... }
}
```

At runtime the highest-fidelity tier wins, in this order: `lookupTable > segments > inferredFromShape`. Empirical measurement takes precedence over the analytic model because empirical measurement is what actually happens in the well. When `segments` and `lookupTable` disagree, the lookup table is ground truth; the parametric segments are advisory and authors should fix them rather than rely on stale numbers.

Minimal definitions get to ship with just `inferredFromShape` (a few numbers — shape, diameter, depth, max volume) and the system still has enough data to pipette. Authoring a validated assay plate? Ship the lookup table from a real volumetric calibration and the system uses it. Both extremes are fully supported forms of the same field. Author the highest tier your data supports, and add a second tier only when it carries independent information (a measured `lookupTable` next to parametric `segments`); do not restate a lower tier derived from the same source — it adds nothing, and the two copies can disagree.

### 1.4 A modern JSON foundation, owned by the client

The definition is plain **JSON** — queryable, diff-able, and readable by tools, generated clients, and AI agents — where VENUS used COM objects with embedded XML and InstinctV used XML. That alone is a large gain in how usable the data is.

Plain files have a second consequence: the client's own repository is the **system of record**. The API holds one current representation per definition — a working set — while versioning, history, comparison, and rollback live in the client's version control, where those tools already exist. The runtime computes a **canonical content hash** for every definition and reports it on store and read, so a client can verify any deployment against its own files; the same content hash is pinned and recorded when content is loaded for execution. The working set stays **tamper-evident and auditable** — exactly what regulated (**GxP**) deployments need: you can prove which bytes were in use when work executed. The prior models had no equivalent foundation.

### 1.5 The rest

Those three distinctions are the foundation. The rest is doing the details right, and several are genuine improvements on VENUS and InstinctV rather than mere plumbing:

- **Typed concepts, not generalized labels.** First-class `probe`, `tool`, `lid`, and `assembly` types, where InstinctV used generalized labeled areas — specific where specificity helps a consumer reason about the data. (Alignment is the deliberate exception: it stays an open, name-matched vocabulary rather than a typed one — see the next point.)
- **Alignment, kept and simplified.** The InstinctV alignment model — still in service today underneath MLPrep — was a good idea: typed rule structures keyed by a free-form name, resolved at runtime so one definition already worked across carriers without per-carrier variants. This schema keeps the two parts that mattered in practice — the free-form name match and the runtime resolution — and simplifies what carries them: symmetric features and receptacles, a bare name + offset instead of typed rule objects, and warnings rather than hard blocks.
- **Open extension without collisions.** InstinctV already had custom properties and device-specific grip points; this schema keeps them but **namespaces them per publisher** (`customAttributes`, per-instrument keyed maps like `gripPoints`), so Hamilton, a customer, and a third party never overwrite each other. The conventions document records the recommended vocabulary, so the catalog grows without the schema growing.
- **Proprietary geometry stays internal.** The schema captures public physical facts — volumes, dimensions, mount geometry — not the proprietary internal CAD (a tip's exact bore profile); the public fields carry enough for volume, collision, and selection without exposing the IP (one of the reasons §1.1 rejects a 3D model as the foundation).

---

## 2. Quick anatomy

Every Hamilton labware definition has five required fields:

| Field | What it carries |
|---|---|
| `id` | Globally unique identifier in `publisher:identifier` form (e.g., `hamilton:nunc_96_flat`). |
| `schemaVersion` | A `1.x.y` string (currently `1.0.0-alpha.1`) — the version of the schema this definition was written against. |
| `labwareClass` | Structural category: `plate`, `tip_rack`, `tube_rack`, `carrier`, `reservoir`, `probe`, `tool`, `lid`, `assembly`, `tube`, `adapter`. Custom values are allowed under the same snake_case shape. |
| `displayName` | Human-readable name for UIs. |
| `dimensions` | The labware's outer bounding box (`x`, `y`, `z` in mm), origin at left-front-bottom. |

Those five are the schema's only unconditional requirements — two identity fields, a class, a display name, and one block of specification-sheet numbers — the authoring half of the §1.1 test at work. Classes with containers — `plate`, `tip_rack`, `tube_rack`, `reservoir`, `tube` — must also carry `containerGrids` (a plate with no grid has nothing to pipette into) and a seating feature, which the base schema now *conditionally* requires per declared `labwareClass`, alongside the four class-specific blocks of §10. Carriers, adapters, lids, probes, and tools have no containers and omit `containerGrids`, but each defined class still has its own conditionally required aspects. What a *complete* definition of each defined class carries — a plate's grid and seating feature, a carrier's sites — is now enforced by the base schema and rejected at the catalog when missing (§10.6).

Everything else is optional and falls into a small number of groups:

- **Identity and provenance**: `source`, `manufacturer`.
- **Physical envelope**: `material`, `weight`.
- **Internal structure**: `containerGrids`, `connectedContainerGroups`, `intraLabwarePassthroughs`.
- **External structure**: `collisionShapes`, `presenceDetectionZones`, `barcodeLocations`, `selfStack`.
- **Placement**: `sites`, `alignmentFeatures`.
- **Instrument-facing metadata**: `gripPoints`, `customAttributes`.
- **Class-specific blocks**: the block matching `labwareClass` is required (`probe`, `tool`, `assembly`, `tipRack`); additional blocks may accompany it when one labware physically plays several roles (§10). `lid` carries no class-specific block.
- **Visualization**: `visualModel`.
- **Search and filtering**: `tags`.

One rule is worth carrying through the rest of the tour: the schema's value vocabularies come in two kinds, chosen per field by a single test. Where a consumer can degrade gracefully on a value it does not recognize, the vocabulary is **open** — free snake_case with recommended values in the conventions document — so vendors extend it without a schema-version change: `labwareClass`, `material`, `probeType`, the alignment `name`, the tool `kind`, tags. Where the runtime must understand every value to behave correctly, the vocabulary is a **closed enum**, and adding a value is a deliberate schema change: `iterationOrder` (an unrecognized value would silently mis-order multi-channel work), the passthrough `mode` (volume would be mis-routed), `tipRack.style`. When a later section shows one field as an enum and its neighbor as free-form, this test is the reason.

That's the whole tour at one level of zoom. The rest of this document goes one level deeper into each group.

---

## 3. Identity and versioning

### 3.1 The `id` field

A labware ID is two segments separated by a colon: `publisher:identifier`.

```json
"id": "hamilton:nunc_96_flat"
```

The publisher portion is registry-policed. `hamilton` is publisher-locked through signing. Customers and third-party authors use their own registered publisher namespaces. Identifier portions are intentionally permissive — mixed case is allowed because Hamilton legacy IDs like `TR384t50gchm4COR` need to survive conversion.

There is also a separate URN form (`urn:hamilton:schemas:microlab:labware:v1`, `urn:hamilton:schemas:microlab:geometry:v1`, etc.) used as the `$id` of the schema documents themselves. The two forms have distinct concerns: schema files use structured URNs so they are stable and resolvable through the published catalog; labware authors use two-segment publisher form because it is shorter, registry-friendly, and signing-locked for the `hamilton` namespace. Don't confuse the two.

**Prior systems**: a VENUS definition is identified by its filename plus a category id — no per-definition UUID, and the only integrity mechanism is an optional, recomputable checksum (corruption detection, not tamper evidence). InstinctV gives each definition a GUID `InstanceID`, which provides uniqueness but no integrity and no publisher signal. Neither says who *published* a definition. The `publisher:identifier` form makes the publisher first-class and lets one catalog safely hold definitions from many vendors.

### 3.2 Versioning and the content hash

One field in the document tracks the schema; one value outside the document tracks the content:

| What | Cadence |
|---|---|
| `schemaVersion` | Changes when the **schema** changes. Currently `"1.0.0-alpha.1"` (pre-release). |
| Content hash | Computed by the runtime over the definition's canonical form. Tamper-evident; not a field you write — it is reported alongside the definition on store and read, never embedded in it. |

The definition carries no version field of its own. The API holds exactly one current representation per `id` — storing a definition again replaces it — and a definition's history lives in the client's own repository, where diff, review, and rollback already exist. The reported content hash ties the two sides together: the same file produces the same content hash, so "does this deployment hold what my repository holds?" is a content hash comparison, not a content comparison.

When a definition is referenced from elsewhere — from a `contentsRef`, from an assembly component, from a stored system — the reference is the bare id (`hamilton:tip_50ul`) and resolves to the catalog's current representation when it is used. Active systems and audit records pin loaded content by content hash at every manipulation, so "exactly which definition content was in use when this happened?" always has an answer. Pinning is runtime evidence the system records, not something authors write into documents.

**Prior systems**: VENUS revises a definition by overwriting the file, with no record of what changed; forking is by file copy with no record of the original. InstinctV did version its definitions, but the version was consulted only when validating a workflow — not a general history, comparison, or fork-lineage model around the definition. This design puts that history where version control already solves it — the client's repository — and adds the content hash so the deployed copy is verifiable against it.

### 3.3 `source`

Conversion provenance — where the definition came from when it was *imported* rather than authored fresh. A field for converters to fill in:

```json
"source": {
  "system": "instinctv",
  "originalId": "P96w2000gcgkxCOS",
  "originalFile": "P96w2000gcgkxCOS.json",
  "convertedDate": "2026-06-09",
  "convertedBy": "LabwareConverter v1.0",
  "notes": "Square wells. InstinctV Shape 4 (4.0x4.0mm) modeled as rectangular_prism."
}
```

`source` records the previous *system* a converter pulled from — not lineage between definitions in this catalog. A client that adapts an existing definition tracks that relationship in its own repository.

---

## 4. Physical envelope

```json
"dimensions": { "x": 127.76, "y": 85.48, "z": 14.22 },
"material":   "polypropylene",
"weight":     35
```

`dimensions` is the outer bounding box at the labware's defined origin (left-front-bottom corner; X+ right, Y+ back, Z+ up); these values typically come straight from the manufacturer's specification sheet. Collision-detection consumers use this as the worst-case envelope. If features stick out beyond the box, declare them in `collisionShapes` rather than inflating `dimensions`. The origin convention itself — left-front-bottom, X+ right, Y+ back, Z+ up — is chosen to match where the numbers come from and where they go: manufacturer drawings dimension from that corner, Hamilton liquid-handling instruments position from it, and the converted VENUS corpus already uses it. (InstinctV moved to center-based origins, which authors found confusing.)

`material` is a snake_case identifier — recommended values (`polypropylene`, `polystyrene`, `glass`, `stainless_steel`, ...) are listed in the conventions document. It feeds chemical-compatibility checks and rendering hints. Omit for composite labware where no single material dominates.

`weight` is the empty mass in grams (no liquid, no children). Centrifuge balancing, integrated-scale presence detection, and payload-mass tallies read this.

**Prior systems**: VENUS and InstinctV both have a bounding box; neither has a typed material or empty-weight field at the top level.

---

## 5. Containers

This is where most of the real geometry lives, and it is the most likely place a reader will pause. The model is built up in three layers: a labware has *grids* of containers; each grid has a *container definition* describing one of the containers' geometry; each grid can have per-position *overrides* for the few cases where one position differs from the rest.

### 5.1 `containerGrids` is a keyed map

A labware can have one grid or many. The grid identifier is the JSON key:

```json
"containerGrids": {
  "default": {
    "columns": 12, "rows": 8,
    "columnPitch": 9.0, "rowPitch": 9.0,
    "iterationOrder": "column_major",
    "firstContainerCenter": { "x": 14.38, "y": 11.24, "z": 1.0 },
    "containerDefinition": { ... }
  }
}
```

Single-grid labware conventionally uses the key `default`. Multi-grid labware — dispense control plates, hybrid tube racks where one face holds 2 mL tubes and the other 1.5 mL tubes — uses semantic keys (`dispense`, `collection`, `lower`, `upper`). All cross-grid references in audit logs, group memberships, intra-labware passthroughs, and per-container barcode reads use the qualified form `gridId.containerName` (`default.A1`, `dispense.A1`). This is uniform even for single-grid labware, so consumers reading stored references never have to special-case "single grid". (At the API boundary a client may still name a container by bare position — `A1` — for single-grid labware; the resolver canonicalizes it to `default.A1`, so the stored and audited form stays qualified.) Using a JSON object rather than an array gives JSON-level uniqueness on the grid id.

**Prior systems**: VENUS models one grid per rack, so multi-grid labware there is composed from separate racks on a carrier — which requires split definitions when the grids are physically one piece. InstinctV already allows multiple grids in a single labware; what this schema adds is an explicit, typed description of *flow between* grids (`intraLabwarePassthroughs`, connected groups).

### 5.2 Naming and iteration order

Each grid has a `namingConvention` (default produces A1–H12 for a 96-well plate) and an `iterationOrder` (`column_major` or `row_major`) that maps linear index 1..N to `[row, column]`. SBS convention is column-major: A1=1, B1=2, ..., H1=8, A2=9. Common tip-rack convention is row-major: A1=1, A2=2, ..., A12=12, B1=13. CO-RE 8-channel pipetting picks 8 tips at once and relies on this; consumers that address by name can ignore it. The field is *required* (not defaulted) because getting it wrong silently mis-orders multi-channel operations.

### 5.3 `ContainerDefinition` and overrides

The grid declares one `containerDefinition` that applies to every position by default. Fields you can declare on a container: opening shape and dimensions, total depth, recommended max pipetting depth (below which the system will not descend), bottom-wall thickness, the three-tier volume model, an optional restricted-channel shape (`pipettingChannelGeometry`, §6.5), working volume bounds (manufacturer-recommended min and max), LLD properties, and `contentsRef` (the labware that occupies this container — used by tip racks and tube racks). `totalDepth` is the one field every container must declare. A container that holds liquid directly also declares a `volumeModel` (the liquid volume-at-height curve); a tip- or tube-rack position omits it — its occupant's volume comes from the `contentsRef` target (the probe or tube), not from the rack position itself.

Per-position overrides handle the small variations:

```json
"containerOverrides": {
  "A1": { "disabled": true },
  "H12": { "maxPipettingDepth": 8.5 }
}
```

Only the fields you list are overridden; everything else inherits. Typical uses: marking an alignment-pin position disabled, fine-tuning one corner well, marking a damaged position out of service. If a position has *fundamentally different* geometry — say, a tube rack with three different tube sizes — declare a separate grid instead.

**Prior systems**: VENUS calls this `SingleContainer` mode; InstinctV does it the same way. This schema generalizes the pattern with explicit overrides and lifts it onto the multi-grid model.

---

## 6. Volume tracking

### 6.1 The three tiers

A container's `volumeModel` may carry any combination of three tiers. The runtime picks the highest fidelity present:

| Tier | What it looks like | When to use it |
|---|---|---|
| `lookupTable` | Map of height (mm) → volume (uL). Linearly interpolated. | You have a real volumetric calibration. |
| `segments` | Ordered list of geometric segments stacked bottom-to-top. Each has its own volume integral. | You have mechanical-drawing geometry but no measured curve. |
| `inferredFromShape` | One simple shape descriptor (`flat_bottom_cylinder`, `v_bottom_rectangle`, etc.) plus a max volume. | Minimal definition; the system derives an approximate curve analytically. |

Precedence: `lookupTable > segments > inferredFromShape`. Empirical measurement wins over the analytic model because real labware deviates from ideal geometry. When `segments` and `lookupTable` disagree, the lookup table is ground truth and the segments are the thing that needs fixing.

Carry one tier unless a second adds independent information. A measured `lookupTable` alongside parametric `segments` is two genuine sources; `inferredFromShape` alongside `segments` derived from the same drawing is one source written twice, and the redundant copy only creates room for the two to disagree (precedence then hides the disagreement).

### 6.2 Segment shapes

When a definition uses `segments`, each segment is one of six shapes: `cylinder`, `rectangular_prism`, `conical_frustum`, `rectangular_frustum`, `spherical_cap`, `paraboloid`. The list is ordered bottom-to-top, so `segments[0]` — the first array entry — is the deepest segment (the container floor), and each later entry stacks on top of it. Each segment carries its own cross-section dimensions and height.

```json
"segments": [
  { "type": "rectangular_frustum", "widthBottom": 0.0, "depthBottom": 0.0,
    "widthTop": 8.0, "depthTop": 8.0, "height": 4.0 },
  { "type": "rectangular_prism", "width": 8.0, "depth": 8.0, "height": 38.0 }
]
```

A square deep-well: a tapered V-shaped base 4 mm tall transitioning into a 38 mm straight bore.

**Prior systems**: this stacked-segment model is InstinctV's (and VENUS's), adopted for the same volume-integration math — but without InstinctV's complex per-segment transformations (per-segment origin and rotation), which no surveyed labware needed. Segments are a plain bottom-to-top stack; a genuinely asymmetric internal feature is modeled with multiple grids or external `collisionShapes` instead.

Segments and external collision shapes (Section 7.1) draw from the same shared geometry catalog — the six-primitive `Solid3D`. The difference is in use, not vocabulary: a volume segment exploits the precise primitives (paraboloids and spherical caps change the volume integral), while an external collision body is a coarse envelope that needs only the prism/frustum primitives in practice. Mesh references and composite primitives can be added to `Solid3D` later without disturbing either use.

### 6.3 `connectedContainerGroups`

A reagent trough may look like ten wells but be one connected pool — pour liquid into one well and the surface rises in all ten. `connectedContainerGroups` declares such pools:

```json
"connectedContainerGroups": {
  "trough_main": {
    "containers": ["default.A1","default.B1","default.C1","default.D1"],
    "connectionTopology": "base",
    "maxVolume": 60000
  }
}
```

Like `containerGrids` (§5.1), the field is a keyed map — the JSON key is the group identifier. Containers not listed in any group are independent (the default for most labware). Volume-tracking consumers see the group and treat it as a single shared pool. When a whole grid is one pool, list the bare grid id — `"containers": ["trough"]` — instead of every position.

**Prior systems**: VENUS handles this only by convention. InstinctV declared it but did not consume it: a grid could carry an `ItemsConnected` flag — whole-grid only, with no position subsets and no group volume — and the runtime never read it; in practice a trough was one large container with computed channel positions. `connectedContainerGroups` makes the pool an explicit, consumed fact: any subset of positions (or a whole grid), a connection topology, and a group `maxVolume`.

### 6.4 `intraLabwarePassthroughs`

This is the multi-grid sibling. When a single labware has multiple grids and liquid flows between them — a dispense control plate where the `dispense` grid drains into a `collection` grid — declare the flow:

```json
"intraLabwarePassthroughs": [
  { "fromGrid": "dispense", "toGrid": "collection", "mode": "one_to_one" }
]
```

The `mode` field tells the system how to distribute volume: `one_to_one` (paired by index), `one_to_many` (each source fans to N targets, source volume divided equally), `many_to_one` (N sources converge to each target, accumulating), or `mapped` (with an explicit `map` from source position names to target position names). Non-uniform / weighted distribution is deliberately not modeled — it would be easy to misuse and no concrete labware needs it today.

### 6.5 `pipettingChannelGeometry` — the restricted channel shape

Most pipetting channel families are firmware-restricted: they cannot consume the volume model above and accept exactly one container description — a truncated cone joined **flush** under a cylindrical shaft (the cone's upper diameter *is* `cylinderDiameter`; the channel cannot represent a step at the junction). The shared geometry schema names this shape `CylindricalConicalGeometry`, and a container may carry it explicitly:

```json
"pipettingChannelGeometry": {
  "cylinderDiameter": 8.0,
  "cylinderHeight": 38.0,
  "coneHeight": 4.0,
  "coneBottomDiameter": 1.2
}
```

The field is **supplementary, not a fourth volume tier**: volume and liquid-level math never read it, and a container that carries it must still carry its `volumeModel`. It exists for explicit control over what restricted channels receive. When absent, the runtime derives the shape from `volumeModel.segments` (one shared reduction, so the same container yields the same shape on every instrument); a container whose volume model is only a `lookupTable` has nothing to derive from and needs the authored shape to be usable on restricted channels. Heights may be zero — `coneHeight: 0` for a straight-walled shaft (then `coneBottomDiameter` is omitted), `cylinderHeight: 0` for a pure cone — and `coneBottomDiameter` never exceeds `cylinderDiameter` (the cone narrows toward the bottom).

The authored shape is deliberately **not** validated against the volume model: an author may intentionally present a restricted channel with a shape that deviates from the true geometry (a safety margin near a delicate bottom, for example). Unrestricted channel families consume the full volume model and ignore this field; which families are restricted is instrument knowledge, not labware data.

**Prior systems**: VENUS is the direct precedent — it reduces every container to a bottom-section height and diameter ratio at command time, so only this coarse shape ever reaches the channel. This schema keeps the full-fidelity volume model for every consumer that can use it and makes the reduced shape an explicit, optional field instead of an implicit lossy projection.

---

## 7. External geometry

The container model handles the *insides* of the labware. The next three fields handle the *outside*.

### 7.1 `collisionShapes`

A keyed map of external collision-relevant shapes — carrier corner tabs, mounting brackets, multiflex pedestal posts, raised rims:

```json
"collisionShapes": {
  "body": {
    "shape": { "type": "rectangular_prism", "width": 39.0, "depth": 61.0, "height": 24.0 },
    "origin": { "x": 19.5, "y": 30.5, "z": 0.0 }
  }
}
```

Distinct in *purpose* from container interiors (well shape) and presence-detection zones (solid material for sensors). Its `shape` is the shared geometry `Solid3D` — the same catalog the volume segments use — but an external collision body is a coarse envelope, so the prism/frustum primitives are the usual choice (paraboloids and spherical caps are rarely needed) and the catalog is not restricted to them. VENUS lacks a typed external-shape model (collision is implicit in the bounding box); this schema adopts the per-shape-transform idea from VENUS's collision avoidance system work — an improvement effort that was never completed.

### 7.2 `presenceDetectionZones`

Presence detection (is anything sitting on this site?) requires *solid material* under the sensor. A solid plate has solid material everywhere; a Nestable Tip Rack (NTR) has it only at its four legs. Declaring where the solid is lets the system know whether a given sensor will see anything:

```json
"presenceDetectionZones": {
  "base_center": {
    "footprint": { "shape": "rectangle", "width": 80.0, "depth": 50.0 },
    "center": { "x": 63.88, "y": 42.74 },
    "zRange": { "min": 0.0, "max": 3.0 },
    "compatibleSensors": ["optical", "capacitive", "ultrasonic", "weight"]
  }
}
```

The `footprint` reuses the shared `Shape2D` type from the geometry schema (same shape vocabulary as `SiteDefinition.footprint`). Each zone is a 2D footprint extruded vertically through `zRange`, positioned at `center`. An NTR declares four zones — one per leg. The labware schema itself doesn't check sensor overlap (it has no instrument knowledge); when a labware is composed into a system, the system-composition tool — knowing both the labware's zones and the instrument's sensor positions — warns when no zone overlaps a sensor.

### 7.3 `selfStack`

How this labware stacks on *itself* in a stacker or hotel. `height` is the Z increment per copy — the stack pitch, not the total assembly height. The consumer expands it to a self-matching alignment keyed off this definition's id, so only an identical copy stacks; it is the shorthand for that common case (§8.1; conventions §5.8). Distinct from `sites` and `alignmentReceptacles`, which place *different* labware (a plate on a carrier, a lid on a plate).

```json
"selfStack": { "height": 8.4 }
```

Two things a legacy stacking block would have carried are deliberately absent. A stack-count limit is not a fact about the labware — how high a stack may safely grow belongs to the system and the stacker operating it, which can impose a limit at composition or run time (a vendor that wants to record a recommendation can use `customAttributes`). And there is no height tolerance: matching is by name (§8.1), and the pitch is a single number the consumer trusts.

---

## 8. Placement: sites and alignment

The schema models how a labware sits on something else with two symmetric fields:

- A labware that is **placed onto** something declares `alignmentFeatures` — physical features on its body that locate it (the rim of an SBS plate, the pin holes on a carrier).
- A labware that **receives** other labware declares `sites`, each of which has `alignmentReceptacles` — the receiving features (the ledge on a carrier site that the plate rim seats on, the pins that match the carrier's holes).

At placement time the system matches features against receptacles by name and auto-calculates the position. A mismatch is a soft warning, never a hard block, and lets placement proceed. The reasoning: a labware present enough to be loaded should be allowed to run, and a warning at setup costs far less than a hard failure partway through a protocol.

### 8.1 `alignmentFeatures` and the alignment `name`

An alignment feature is a labeled physical engagement:

```json
"alignmentFeatures": [
  {
    "name": "sbs_rim",
    "offset": { "z": 3.0 }
  }
]
```

Here the alignment's `offset.z` is the height on the labware — measured up from its own base (Z=0) — at which the feature seats onto the receiving site. For an `sbs_rim` that's the underside of the skirt flange that lands on the carrier ledge: on a standard SBS plate a few millimeters up (≈3 mm here), *not* the very bottom of the skirt. A nest-style feature (e.g. `sbs_nest`) instead names the container-base surface the site's raised center lifts, which sits near Z=0 — so rim-seat and nest contact heights describe *different surfaces*, not the same one at different values. `offset.x`/`offset.y` are optional and default to the labware's footprint center, so the common case states only Z. There is no envelope or tolerance on the alignment: a feature and a receptacle match purely by `name`, and any footprint check is an advisory comparison against the site's `footprint`, never a hard gate.

The `name` field is a free-form snake_case string (optionally `publisher:`-prefixed for a vendor-private mating) that identifies a specific mating *interface* — `sbs_rim`, `sbs_lid`, `mfx_module`, `pcr96_well_cradle`. The name carries the footprint, pattern, or product so a match means "these actually mate"; conventions §5 records the naming convention and the common mechanisms (rim seat, nest, pin-and-hole, well-cradle, and the rest). Vendors can introduce new interfaces without a schema-version change. Matching is exact string equality between the feature `name` and the receptacle `name`, so typos still fail. This deliberately keeps the part of the InstinctV / MLPrep alignment model that has worked in the field — compatibility decided by a free-form name matched at runtime — while dropping the typed rule objects around it (§1.5).

When more than one feature–receptacle pair could seat the same placement, the consumer resolves in a fixed order: an explicit `preference` value on the alignment wins first (the author's tiebreak when a labware deliberately offers alternatives); otherwise the match with the greatest resting Z (the contact that is physically reached first as the labware is lowered); declaration order settles any remaining tie deterministically.

### 8.2 Sites on labware, not just on decks

Sites are addressable placement positions that materialize as runtime Parts: a carrier exposes labware positions, a Multiflex base carrier exposes ten module positions, a deck exposes deck positions. A labware that simply *receives* a lid or a stacked copy needs no site for it — that attachment is a labware-root `alignmentReceptacles` entry (the supporting side, §8.1), not an addressable Part. So a plain plate has alignment features and receptacles but no sites; a carrier has features (it mounts on the deck) and sites (its positions). Sites use one schema wherever they sit.

```json
"sites": {
  "pos_1": {
    "label": "Position 1",
    "origin": { "x": 63.5, "y": 45.5, "z": 0.0 },
    "footprint": { "shape": "rectangle", "width": 130.0, "depth": 92.0 },
    "alignmentReceptacles": [
      { "name": "sbs_rim", "offset": { "z": 5.0 } }
    ]
  }
}
```

A site carries a small set of fields. Two are required — `origin` (the center of the site's footprint, in labware coordinates) and `footprint` — and the rest are optional:

- **`origin`** is the XYZ center of the site's footprint in labware coordinates: the origin of the site's local frame, on which the footprint is centered and from which its `alignmentReceptacles` offsets are measured. A placed child labware's footprint center seats here. (Center-anchored, like a container position — see conventions §8.) Both VENUS and this schema place this frame at the left-front-bottom labware corner (§4), but VENUS dimensions a carrier's sites by the site *corner*, so converting one shifts by half the footprint to reach this center — the agreement on the labware frame does not mean site coordinates carry over unchanged.
- **`rotationZ`** is an optional rotation (degrees) of the site's local frame about the vertical axis, relative to the labware frame; defaults to 0.
- **`label`** is an optional human-readable name for UIs.
- **`footprint`** is a 2D footprint (`Shape2D`: rectangle/circle/polygon) used for collision checking, rendering, and an advisory footprint comparison. Required on a labware site (the shared SiteDefinition leaves it optional only so a standalone system site may omit it). An over-size footprint is a soft warning, never a hard block.
- **`alignmentReceptacles`** are the receiving side (§8.1), matched by `name` against a placed labware's `alignmentFeatures`; the matched alignment's `offset` — measured relative to the site `origin` — positions the seated labware, so the site needs no `face` of its own.
- **`customAttributes`** carries site-scoped vendor extensions, including site purpose by convention (§8.3).

The full field-by-field contract lives in the site schema's own field comments (`urn:hamilton:schemas:microlab:site:v1`).

### 8.3 Site purpose by convention, not by enum

Notice what is *not* in a site definition: a typed `role` field. The first instinct is to add one — "is this site the waste site? the tool-dock site? the lid-park site?" — and the schema deliberately rejects that. Site purpose is conveyed by convention via a `customAttributes` entry on the site itself:

```json
"sites": {
  "waste_drop": {
    "customAttributes": {
      "hamilton:site_purpose": { "purpose": "waste" }
    }
  }
}
```

(Shown with only the purpose attribute to keep the focus; a real site still carries the required `origin` and `footprint` from §8.2.)

The recommended purpose values live in the conventions document — `waste`, `tip_eject`, `tool_dock`, `lid_park`, `teach_fixture`. A consumer looking for "the waste site" scans the sites for one whose `hamilton:site_purpose.purpose` is `waste`. Because the attribute lives on the site, it cannot dangle, more than one site can share a purpose, and new purposes don't need a schema change.

**Prior systems**: InstinctV *did* carry site purpose — but as a set of independent boolean flags on the site type (`IsWaste`, `IsVirtual`, `IsInternalToDevice`, alongside capability flags like `SupportsPipetting`), a closed vocabulary that grows only by adding schema fields. VENUS has no per-site purpose field at all: a site carries geometry and a free-text id, so "waste" is conveyed by a rack literally named `Waste` plus untyped labware properties like `MlStarIsWasteRack`. This schema uses a convention instead because the set of purposes is open-ended and vendor-specific — a closed enum, or a fixed flag set, either sprawls over time or forces a schema-version change for every new instrument workflow.

### 8.4 Occupant seating in a container position

Sections 8.1–8.3 place one whole labware on another — a plate on a carrier. The same alignment primitive also seats the *occupant* of a container position: the tip or tube a rack holds through `contentsRef`.

Most occupants need no alignment. They bottom out on the cavity floor, and the grid geometry (`firstContainerCenter.z` plus the container depth) already locates them. The case that needs it is an occupant that **hangs** — a tip resting on its collar shoulder, not the hole bottom — or one a feature **biases** to one side (a spring-loaded tube position). For those, the container position carries an optional `alignmentReceptacles` (the supporting side):

```json
"alignmentReceptacles": [ { "name": "core_tip_300", "offset": { "z": 52.0 } } ]
```

and the held item declares a matching `alignmentFeature` on its own definition (the placeable side):

```json
"alignmentFeatures": [ { "name": "core_tip_300", "offset": { "z": 52.0 } } ]
```

It is exactly the §8.1 mechanism — match by `name`, position by offset subtraction, greatest-resting-Z when more than one could contact — applied to the occupant-in-container relationship rather than the labware-on-site one. Two things are specific to this use. The receptacle's `offset` is measured from the **cavity floor**, so it composes with the grid that replicates the container across every position. And the held item's feature is **tip-intrinsic** — the collar-shoulder height on the tip itself — so one probe or tube definition seats correctly in every compatible rack, with the rack supplying only the catch height. A position may declare more than one receptacle when different occupants seat differently in the same hole.

This is the benefit of the single primitive: labware-on-carrier, lid-on-plate, self-stacking, and tip-in-rack are all the same `name` + `offset` match, differing only in which two parts carry the feature and the receptacle.

---

## 9. Instrument-facing data

The schema can't anticipate every instrument's needs, so several fields are designed to grow independently per instrument.

### 9.1 `gripPoints`

A keyed map from instrument identifier (publisher form) to an array of grip-point variants for that instrument:

```json
"gripPoints": {
  "hamilton:iswap": [
    {
      "center":     { "x": 63.5, "y": 43.0, "z": 22.0 },
      "approach":   ["front", "back"],
      "openWidth":  134.0,
      "gripWidth":  127.0,
      "maxGripForce": 10.0
    }
  ],
  "hamilton:core_grip": [ { ... } ]
}
```

Each instrument owns its own slice. Adding `hamilton:lablync` adds a key; iSWAP grip data is unaffected. The `approach` array lists faces from which this specific grip is reachable — symmetric plates list multiple faces; asymmetric labware lists one. The contact height is `center.z` — `center` is the contact midpoint, so there is no separate height field. `maxGripForce` is the labware's own tolerance, not an operating force: it states the most squeeze the item survives at this grip (a flexible lid deforms above it), and the instrument chooses how firmly to grip within that bound. Operating parameters — the actual force applied, transport and approach speeds, hold time — are runtime concerns, tunable per instrument through the grip point's `customAttributes`. Each variant may also carry an optional `label` — a client-facing snake_case selector (e.g. `landscape`, `portrait`) so a consumer can pick a specific variant by name rather than by fragile array index; recommended unique within the instrument's grip array.

### 9.2 `barcodeLocations`

A keyed map of declared barcode positions. Each location is described by two dimensions:

```json
"barcodeLocations": {
  "side_barcode": {
    "surface": "labware",
    "face": "front",
    "symbology": "code128",
    "zone": { "origin": { "x": 10.0, "y": 3.0 }, "width": 65.0, "height": 16.0 },
    "orientation": "horizontal"
  }
}
```

- **`surface`** is `labware` (the barcode is on the labware body) or `container` (the barcode is on each container — e.g., the side of every tube in a rack).
- **`face`** is which face the barcode is on. For `surface: labware`, one of the six bounding-box faces. For `surface: container`, one of the three container faces (side/top/bottom).

How many distinct reads to expect at runtime is derived, not declared: `surface: labware` → 1 read (the one labware body); `surface: container` → one read per container in scope (all containers across all grids by default; restricted to a single grid when the location's optional `grid` field names one). The separate `unique` field captures whether each manufactured instance carries a distinct value (`true` — serial-printed) or all share a labware-family identifier (`false`).

A labware can declare multiple barcode locations — a tube rack might have one on its side and per-tube on each container. Whether any given instrument's reader can reach a given location from a given site is the *instrument*'s decision; the labware just states what is there to read.

### 9.3 `customAttributes`

The extension surface for everything else. Keys are publisher-form (`publisher:concept`); values are unconstrained JSON objects:

```json
"customAttributes": {
  "hamilton:star": { "tipEjectHeight": 2.5, "managedSequenceName": "MlStar1000ulHighVolumeTipWithFilter" },
  "mylab:lims":    { "catalogNumber": "12-3456-78", "storageCondition": "2-8°C" }
}
```

The schema validates the key shape — the value shape is the publisher's responsibility. The recommendation in the conventions document is for each publisher namespace to publish and maintain a JSON Schema for its value payload like a public API contract.

Two patterns to know:

- **Vendor-specific instrument data** — STAR-specific touch-offs, XRP carrier track properties, autoload mask prefixes. Each instrument plugin gets its namespace.
- **Site-purpose conventions** — the `hamilton:site_purpose` attribute on a site, above. The conventions document is the registry.

**Prior systems**: VENUS uses `XmlLabwareTraits` — an opaque XML blob embedded in the COM definition file. InstinctV uses typed property hierarchies. This schema's `customAttributes` is the clean refactor of `XmlLabwareTraits`: the same "vendor-specific bag" purpose, but with publisher-namespaced keys and JSON values that downstream consumers can validate against their own schemas.

---

## 10. Class-specific blocks

Four of the eleven recommended `labwareClass` values trigger a required *class-specific block*. The other values (`plate`, `tube_rack`, `tube`, `carrier`, `reservoir`, `adapter`, `lid`) are covered by common fields plus `customAttributes` only; what a complete definition of each defined class must carry is now enforced by the base schema (§10.6).

The four with blocks: `probe`, `tool`, `assembly`, `tip_rack`.

The schema enforces the class-to-block direction: if `labwareClass` is `probe`, a `probe` block must be present; if `labwareClass` is `tool`, a `tool` block must be present; and so on. A definition declaring `labwareClass: "tool"` with no `tool` block is rejected.

The reverse direction is *not* enforced — the schema permits additional class-specific blocks alongside the class-matching one when the labware item physically plays more than one role (see conventions doc §2.13). A wash station that is both wells and a tip-cleaning station may declare `labwareClass: "plate"` with `containerGrids` plus an additional `tipRack` block, or `labwareClass: "wash_station"` (custom) with both blocks. The schema validates the same in either case; the choice is naming discipline.

### 10.1 `probe`

Used for tips and needles — anything that mounts on a pipetting channel and holds liquid. Tips (disposable) and needles (reusable) share the schema, distinguished by `isReusable`.

```json
"labwareClass": "probe",
"probe": {
  "isReusable": false,
  "isConductive": true,
  "supportedLLDModes": ["capacitive", "pressure"],
  "maxVolume": 1000,
  "deadVolume": 6,
  "hasFilter": true,
  "probeType": "standard",
  "length": 95.0,
  "diameter": 6.8,
  "collarHeight": 10.0,
  "mountInterface": { ... }
}
```

`isConductive` is required because silent assumptions about conductivity cause capacitive-LLD failures on tips that look standard but aren't. `supportedLLDModes` is the set of LLD modes the probe can participate in (empty array means none — teaching needles, specialty bonded-cap tips). `collarHeight` is the cylindrical sleeve at the top of the tip that engages with the pipetting channel — tip-intrinsic, distinct from how far the collar protrudes above any specific rack (a rack-relative computation done at runtime). `probeType` is an open-vocabulary mechanical class — recommended values `standard`, `wide_bore`, `low_retention`, `needle_blunt`, `needle_beveled`, with custom snake_case values allowed (a new mechanical class needs no schema-version change); functional designations (gel-loading, anti-static) live in `tags` because they are labels, not driving math. The instrument-specific tip identifiers Hamilton firmware needs to drive a STAR or VANTAGE — the managed *tip type* and *tip class* — are deliberately not core probe fields either; they live in `customAttributes` under the instrument namespace (`hamilton:star`, `hamilton:vantage`), which keeps the `probe` block instrument-neutral (§9.3).

The public fields above are enough for any consumer to do volume tracking, collision detection, and tip selection; the tip's proprietary internal bore geometry is not modeled in the schema — only its public physical facts.

A probe is typically referenced from a tip rack's container `contentsRef` — the rack is one labware, the tip is another, and the link is by reference.

### 10.2 `tool`, with a polymorphic `MountInterface`

A tool is a channel- or wrist-mountable transport item — grippers, sensors, readers. All physical-only: jaw geometry, sensor specs, mount interface. **No operations.** A gripper does not declare how to grip; it declares its opening width range.

```json
"labwareClass": "tool",
"tool": {
  "kind": "gripper",
  "mountInterface": {
    "mountKind": "channel",
    "compatibleHosts": ["hamilton:core_channel_x1"],
    "hostGroupSize": 2,
    "channel": {}
  },
  "gripper": { "minOpenWidth": 26.0, "maxOpenWidth": 26.0 }
}
```

`kind` is an open snake_case vocabulary — recommended values `gripper`, `barcode_reader`, `optical_sensor`, `force_sensor` — so a new tool category needs no schema-version change. The schema enforces that a `gripper`-kind tool has a `gripper` block; sensor-kind values require a `sensor` block. Custom kinds declare no kind-specific block until one is added. A tool that physically plays more than one kind — a gripper with an integrated barcode reader, for example — may carry additional kind-specific blocks alongside the kind-matching one (parallel to the labware-class rule in §10 above).

The `mountInterface` is shared between probes and tools — both mount on something, both want the same vocabulary. It is polymorphic on `mountKind`: `channel` (Hamilton CO-RE pipetting channel or 384-head; sub-block carries channel-specific fields like `stopDiskImmersionDepth`) or `robot_wrist` (robot wrist flange, e.g., the LabLync robotic-arm end-effector; sub-block carries the tool-center-point offset). `compatibleHosts` lists publisher-form host identifiers this mount fits (`hamilton:core_channel_x1`, `hamilton:lablync_wrist`); the host concept is owned by the instrument plugin that publishes it. `hostGroupSize` is how many host points engage at once — 1 for a single tip, 2 for a two-prong gripper, 96 for a CO-RE 96 head.

A tool's `kind` tells the instrument what *category* of behavior it offers; the instrument owns the actual behavior.

### 10.3 `lid`

A lid is a removable cover for a plate (or other labware). Separability is inherent to being an assembly component (Section 10.4): a part that can never be separated is modeled as one labware, not an assembly component, so there is no `removable` field. When a runtime separates a component is runtime behavior, in neither the lid nor the assembly. Lids are *by definition* removable; heat-sealed films and adhesive foils are a different concept (a future `seal` labware class) and not modeled as a non-removable lid.

```json
"labwareClass": "lid",
"alignmentFeatures": [
  { "name": "sbs_lid", "offset": { "z": 4.5 } }
]
```

A lid carries no class-specific block. It is identified by `labwareClass: "lid"` and seats through the alignment contract: its `sbs_lid` feature matches the covered plate's labware-root `sbs_lid` receptacle, and the feature `offset.z` (how far up the lid's body the seat contacts) combines with the plate's receptacle height to place it. There is no separate `nestingDepth` — the overlap falls out of the two offsets.

### 10.4 `assembly`

A pre-configured multi-labware stack — for example, collection plate + filter membrane + lid — sold and handled as one item. It is a catalog definition of its own, not a runtime arrangement, for two reasons. The kit is a purchasable product: its composition is a physical fact of the item, with its own part number and provenance. And the assembled whole has physical facts none of its components carries alone: its own stack pitch, grip points that move once a lid is on, a barcode location that may be readable on one component but not another. The assembly definition is where those facts live:

```json
"labwareClass": "assembly",
"assembly": {
  "components": {
    "collection_plate": {
      "labwareRef": "thermofisher:nunc_96_flat"
    },
    "filter_membrane": {
      "labwareRef": "millipore:multiscreen_hn_96",
      "parentComponent": "collection_plate",
      "containerPassthrough": { "mode": "one_to_one", "targetComponent": "collection_plate" }
    },
    "lid": {
      "labwareRef": "hamilton:lid_96_standard",
      "parentComponent": "filter_membrane"
    }
  }
}
```

Each component has no `role` field — the map key (`collection_plate`, `filter_membrane`, `lid`, …) labels the component. A component carries a `labwareRef` (a reference to the component's own labware definition) and — for every non-base component — a `parentComponent` naming the component it sits on. The base is the single component that omits `parentComponent` (exactly one per assembly). Parent and child are positioned by their matching alignments, the child's `alignmentFeatures` against the parent's `alignmentReceptacles`, exactly as a lid seats on a plate — so there is no `parentSiteId` and no `nestingDepth`; the effective assembly height falls out of the component heights and those seating offsets. `containerPassthrough` is the assembly-level analog to the intra-labware passthrough (Section 6.4): liquid leaving a filter component flows to a target component. Without it, the volume tracker can't follow liquid through a filter assembly.

### 10.5 `tipRack`

A small class-specific block carrying rack-level structural properties beyond what `containerGrids` + `contentsRef` express:

```json
"labwareClass": "tip_rack",
"tipRack": { "style": "nestable" }
```

`style` is `nestable` (NTR — open frame, tip collars protrude above the rack surface, so racks can nest into one another for storage) or `framed` (FTR — enclosing walls, tips seat below the rim). This determines whether tips protrude above the rack and influences stacking interactions.

The tips themselves are *separate labware definitions* of class `probe`, referenced from the tip rack's `containerDefinition.contentsRef`. The rack and the tip are decoupled: one rack definition can host different tip variants (filtered vs unfiltered, conductive vs non-conductive) by varying the `contentsRef`.

### 10.6 Class completeness — what a definition of your class must carry

§2's five required fields are deliberately minimal, but the base schema requires more than those five. Its root `allOf` coupling requires, per declared `labwareClass`, the aspects that make a definition of that class usable: a `plate` with no `containerGrids` and no `alignmentFeatures` describes a plate that cannot be pipetted into or placed, so a `plate` — like the other defined classes — must carry them. The catalog runs the full schema on store and on seeding, so an incomplete definition of a **defined** class is rejected (HTTP 422), not merely flagged. A custom or unknown `labwareClass` matches no branch and is held only to the universal rules, so the open vocabulary stays open.

The core completeness the base requires, per declared `labwareClass`:

| Class | Core completeness the base requires |
|---|---|
| `plate`, `tube_rack`, `reservoir`, `tube` | `containerGrids` and at least one `alignmentFeatures` entry |
| `tip_rack` | `tipRack`, `containerGrids`, and at least one `alignmentFeatures` entry |
| `carrier` | `sites` with at least one position, and at least one `alignmentFeatures` entry |
| `assembly` | the `assembly` block and at least one `alignmentFeatures` entry |
| `probe` | the `probe` block and `material` — the latter read by capacitive liquid-level detection and chemical-compatibility checks |
| `lid` | at least one `alignmentFeatures` entry — a lid is the class plus the feature that mates its host's lid seat (§10.3) |
| `adapter` | at least one `alignmentFeatures` entry, plus a receiving side — either `sites` (the addressable case, e.g. a magnetic stand) or a labware-root `alignmentReceptacles` entry |

`tool` needs only its schema-required `tool` block, which already carries the class's defining content.

These rules are `if`/`then` conditionals on `labwareClass`: a validator evaluates them, but an authoring editor does not surface them as required-field prompts. An authoring UI that wants per-class prompts is intended to consume **per-kind views** — lean per-class schemas generated from this base schema (each references the base by URN and adds only that class's completeness). A definition file never names these rules: the optional `$schema` field always points at the base schema's URN, and the matching class rule applies automatically from the definition's `labwareClass`.

These requirements were added while the schema is still pre-freeze (`1.0.0-alpha.1`). Within a published major, requirements may only be loosened, never tightened, so completeness discovered after the v1 freeze cannot be added to the base — it would need the next schema major.

---

## 11. Visualization

```json
"visualModel": {
  "modelRef": "models/mfx_car_base.glb",
  "modelFormat": "glb",
  "modelOrigin": "center_center_bottom",
  "color": "#C8D8E8",
  "opacity": 0.85
}
```

Optional. If no model is available the renderer draws the bounding box; no definition is invalid for lack of a model. 3D model files typically use center-center-bottom origin (natural for CAD and 3D-printer workflows) while labware definitions use left-front-bottom — `modelOrigin` declares the file's convention so the renderer can correct. `color` and `opacity` are fallbacks for schematic rendering when a model is unavailable. The model is deliberately a visualization asset, never the authoritative geometry — §1.1 explains why; volume and collision consumers read the declared numeric fields, not the model file.

---

## 12. Worked example — the minimal Nunc 96-well plate

To put it all together, here is a worked example: a deliberately minimal definition of a Thermo Fisher Nunc 96-well flat-bottom microtiter plate. It uses the inferred-shape volume tier, has one container grid, one alignment feature, a labware-root lid receptacle, self-stacking, one barcode location, one presence-detection zone, and no custom attributes.

Walking the file top to bottom:

```json
{
  "$schema": "urn:hamilton:schemas:microlab:labware:v1",
  "id": "thermofisher:nunc_96_flat",
  "schemaVersion": "1.0.0-alpha.1",
  "displayName": "Nunc 96 Flat Bottom MTP",
  "description": "Standard SBS 96-well flat-bottom microplate. Minimal definition using inferred volume model.",
  "labwareClass": "plate",
```

`$schema` is an authoring-tool hint (so VS Code can find the schema for IntelliSense); not used by the runtime. Publisher `thermofisher`, identifier `nunc_96_flat`, written against schema `1.0.0-alpha.1`; the one-line `description` aids search and disambiguation in UIs. (Earlier sections used `hamilton:nunc_96_flat` for the same plate — the publisher segment names who authored and signed the definition, not who manufactures the plastic.) Class `plate`, so no class-specific block is required. Then a `manufacturer` block (catalog matching), a `source` block (marks this as manually authored), and the bounding box:

```json
  "dimensions": { "x": 127.76, "y": 85.48, "z": 14.22 },
```

Standard SBS plate footprint, 14.22 mm tall. Next, the one and only container grid:

```json
  "containerGrids": {
    "default": {
      "columns": 12, "rows": 8,
      "columnPitch": 9.0, "rowPitch": 9.0,
      "iterationOrder": "column_major",
      "firstContainerCenter": { "x": 14.38, "y": 11.24, "z": 1.0 },
      "containerDefinition": {
        "openingDimensions": { "shape": "circle", "diameter": 6.86 },
        "totalDepth": 10.67,
        "maxPipettingDepth": 10.0,
        "bottomWallThickness": 1.0,
        "volumeModel": {
          "inferredFromShape": {
            "shape": "flat_bottom_cylinder",
            "diameter": 6.86, "totalDepth": 10.67, "maxVolume": 360
          }
        },
        "liquidDetection": {
          "supportsLLD": true,
          "liquidSeekingStartHeight": 3.0
        }
      }
    }
  },
```

One grid keyed `default` — single-grid convention. 12 × 8 on 9 mm SBS pitch, column-major. A1 centered at (14.38, 11.24, 1.0). Each well is a 6.86 mm cylinder, 10.67 mm deep, max pipetting depth 10.0 mm, bottom wall 1.0 mm thick. Inferred-tier volume only: 360 uL max. LLD supported; the channel starts seeking liquid 3 mm above the well opening.

Notice what is *not* declared: no `containerOverrides`, no `connectedContainerGroups`, no `intraLabwarePassthroughs`. All 96 wells are identical and independent. No `segments`, no `lookupTable` — just the inferred tier. The author has prioritized speed of authoring over volume fidelity, and the schema lets them.

```json
  "alignmentFeatures": [
    { "name": "sbs_rim", "offset": { "z": 3.0 } }
  ],
  "alignmentReceptacles": [
    { "name": "sbs_lid", "offset": { "z": 14.22 } }
  ],
```

One alignment feature (the SBS rim, `sbs_rim`, contacting at Z=3.0 mm) and one labware-root receptacle (`sbs_lid` at Z=14.22 mm, the plate's top). An SBS lid declaring an `sbs_lid` feature mates and auto-locates from the matched offsets — and because the lid seat is a plain receptacle, not a site, this plate carries no `sites` at all.

```json
  "barcodeLocations": {
    "side_barcode": {
      "surface": "labware", "face": "front",
      "symbology": "code128",
      "zone": { "origin": { "x": 10.0, "y": 3.0 }, "width": 65.0, "height": 16.0 },
      "orientation": "horizontal"
    }
  },
  "presenceDetectionZones": {
    "base_center": {
      "footprint": { "shape": "rectangle", "width": 80.0, "depth": 50.0 },
      "center": { "x": 63.88, "y": 42.74 },
      "zRange": { "min": 0.0, "max": 3.0 },
      "compatibleSensors": ["optical","capacitive","ultrasonic","weight"]
    }
  },
  "selfStack": { "height": 8.4 },
  "visualModel": { "color": "#C8D8E8", "opacity": 0.85 },
  "tags": ["sbs_footprint","flat_bottom","cell_culture","96_well"]
}
```

One Code 128 barcode on the front face (the labware body, so one read per labware) in a 65 × 16 mm zone. One presence-detection zone in the plate center — 80 × 50 mm of guaranteed solid material from Z=0 to Z=3 mm, detectable by any of four sensor types. Stacks on itself with an 8.4 mm increment. A bare `visualModel` — just a fallback color and opacity, no 3D model. Four tags for filtering. No `customAttributes` at all: nothing vendor-specific to declare, so the map is simply omitted.

That's the whole file. A reader following along has seen identity, provenance, footprint, the inferred-shape volume tier, alignment, barcode, presence detection, stacking, a fallback visual model, and tags. Notice also what kind of numbers these are: every value above comes from the manufacturer's specification sheet or a simple measurement — a VENUS author would recognize all of them. Relative to a legacy rack file, the only genuinely new data is the identity block, the provenance block, and two alignment names. Richer definitions (a deep-well plate with explicit segments, a carrier with ten sites, a filter assembly with passthroughs, a tip with a channel mount interface, a grip tool with a two-prong gripper block) extend the same pattern — same shape, more fields filled in.

---

## 13. What's *not* in this schema, and why

The other side of the physical-reality discipline is a list of things that are *deliberately* not in the schema. Each one was easy to imagine adding; each one was cut for a reason. For VENUS- or InstinctV-experienced readers, several entries will feel like missing features; for readers expecting a 3D-model-first design, §13.1 is the relevant entry. They are not oversights; they are positions.

The largest omission is the one §1.2 already named: every deployment-dependent quantity — placement, calibration, and the tolerance corrections VENUS bakes straight into the geometry — is absent from the definition and lives on the system Part instead. That single cut is what keeps one Nunc plate from accumulating a spread of near-identical `.rck` files. The entries below are the rest, and they draw on both prior systems, not only InstinctV.

### 13.1 An authoritative 3D model

The most common question from readers used to modern 3D tooling: why is the definition not simply a 3D file (glTF, STEP) with everything derived from it? That was a candidate foundation, considered and rejected for authoring, IP, and consumer-cost reasons — §1.1 has the full reasoning. The position: geometry an instrument needs is declared as plain numeric fields a specification sheet supplies; a 3D model is welcome as an optional `visualModel` (§11) but is never the authoritative source.

### 13.2 Operations

The schema models no operations and no operational metadata. A gripper-class tool declares its physical jaw geometry, not how to grip; a tip rack declares tip positions, not a `pickup`; a plate declares wells, not an `aspirate`. The definition describes the *object*, never the actions taken on it.

That is a genuine cut from InstinctV — though not the one a reader might assume. Neither InstinctV nor VENUS declared operation *methods* like `grip()`; what InstinctV carried was operational *metadata* on the definition itself: per-position capability flags (`SupportsPipetting`, `SupportsTipRackOperations`, `CanStackLabware`) and transport defaults (`TransportInfo` — transport speed, grip force in Newtons, extra gripper-opening distance). VENUS carried almost none of this — a VENUS definition holds only tube de-cap grip positions, no transport or capability defaults — so this cut is mostly InstinctV's. In practice these InstinctV fields were little-known — many users never realized an InstinctV definition carried handling metadata at all — and *which* behavior actually ran still depended on configuration the definition could not see. The same labware is operated by STAR-specific routines on a Hamilton STAR and by LabLync-specific routines on a LabLync arm; baking either one's handling into the definition would force the two to agree, or force the definition to carry both. Dropping the metadata makes the labware's scope unambiguous: it describes what the thing *is*, and the instrument owns what to do with it. The one force-related fact a grip point does carry is `maxGripForce` (§9.1) — the labware's own tolerance ceiling, how much squeeze the item survives. That is a fact about the thing, not about handling it; the instrument still chooses its operating force, within the bound.

### 13.3 Consumption and loading modes

Both prior systems put loading metadata on the definition, and this schema drops it. InstinctV declares a `LoadingMode` (`Auto` / `Manual` / `Fixed` / `ManualWithTipCheck`) and a consumption mode (`Process` vs `Consumption`); VENUS carries `MlStarCarIsAutoLoad` / `MlStarCarIsLoadable` / `MlStarCarIsRecognizable` loading-and-recognition flags on its carriers. Rejected for the same reason as operations: they describe runtime and deployment behavior, not the labware. A "single use" tip on one workflow is a "rerack and reuse" tip on another — the *labware* is the same. Whether a plate auto-loads is a property of the deployment and of the instrument that reads its barcode, not of the plate.

These end up in `customAttributes` under publisher-namespaced keys when an instrument or a deployment needs to record them. The schema doesn't force everyone to acknowledge them.

### 13.4 Scheduling and protocol semantics

No fields for time, batch identity, or workflow position — neither prior system carried scheduling on the definition, so nothing is lost. ("Sequence" here means scheduling order. The pipetting channel-sequence VENUS records as `managedSequenceName` — the ordered positions a channel traverses — is a different concept, and it is preserved in two parts: the traversal-order semantics map to `iterationOrder` (§5.2), and the firmware-known sequence name itself is carried under `hamilton:star` in `customAttributes` (§9.3).) Protocol-level concerns live in the protocol layer; they don't survive a round trip back into the catalog.

### 13.5 Sterility, treatment, lot data as typed fields

`sterile`, `dnase_free`, `low_retention`, and similar properties live in `tags` (or in vendor `customAttributes`), not as typed top-level fields. Two reasons: the vocabulary is open-ended (adding `isSterile: boolean` invites `isDnaseFree`, `isRnaseFree`, `isAutoclavable`, ...; tags absorb the long tail), and the semantics are lot-dependent (a "sterile" plate may not be sterile after the box has been open for a week; typed fields imply machine-readable guarantees the schema can't actually make). The conventions document records the recommended tag vocabulary so the tag set stays consistent even though it is open. Neither prior system carried typed sterility either: VENUS left it in free-text descriptions, and InstinctV used its free-form `MetaQualities` tag bag — the direct ancestor of this schema's `tags`. Putting these labels in tags continues that approach rather than inventing typed fields the data can't support.

### 13.6 Site role enums

Already discussed in Section 8.3 but worth repeating. The temptation to add a `role` enum to sites ("waste", "tool-dock", "lid-park", "teach-fixture") was real and rejected. Site purpose is conveyed by a `hamilton:site_purpose` `customAttributes` entry on the site; the conventions document is the registry. (InstinctV marked purpose per-site with booleans like `IsWaste` and `IsVirtual`; VENUS marked it on the whole rack with traits like `MlStarIsWasteRack` — different shapes, the same closed-vocabulary problem.) Closed enums for vocabulary that vendors and customers will continue to extend would freeze the schema or force frequent schema-version changes.

### 13.7 Meta-labware abstractions

InstinctV has a "Meta-Labware" concept: a definition flagged `IsMetaLabware` that carries only the `MetaQualities` tags that matter (`PlateDepth=DeepWell`, `Size=SBS`, ...), so any concrete plate whose qualities are a superset counts as compliant — a tag-based match a protocol can target instead of naming one plate. It shipped as real catalog entries (a "META 1 Well Reagent Troughs" definition, for instance). In practice it added a compliance model that saw limited uptake — thick enough to need its own model, thin enough that most users worked around it. VENUS had no equivalent — every VENUS reference names a concrete file. This schema follows VENUS here and rejects the abstraction: protocols reference concrete labware ids, and equivalence reasoning is left to AI agents acting on the rich metadata every concrete definition carries.

### 13.8 A separate 'hole' and 'container' split

Both prior systems used more concepts here than this schema. InstinctV separates an occupiable opening (`CldeHole`) from what fills it (`CldeHoleItem` — a `CldeContainer` cavity, a tip, or nested labware), with whole-labware placement a third concept again (`CldeSite`). VENUS divides it differently: a `Site` where a rack is placed, a rack type (`RectRack` or `CircRack`) carrying the grid of positions, and a `Container` (`SingleCntr`) referenced per position — but that `Container` is both the cavity and its occupant (a tip, tube, and well are all one `Container`), so VENUS never splits an opening from what fills it. This schema collapses the opening and its cavity into a single `ContainerDefinition`, names any tip or tube occupant with `contentsRef`, and keeps `sites` for placement. The naming rationale, and the rejected alternatives (`holes`, `wells`, `cavities`), are in conventions.md §1.2.

### 13.9 The pattern

The schema is small in these dimensions because every cut keeps it from leaking back into the runtime/deployment layer that owns those concerns. The places it *is* generous (the three-tier volume model, the open-vocabulary `labwareClass` and alignment `name` fields, the publisher-namespaced extension surfaces) are also positions — they expand to absorb future variation without forcing a schema-version change. Narrow on what every definition must say, generous on what any definition *may* say. This section is the list of omissions; the matching account of what this schema *adds or improves* over VENUS and InstinctV is in §1.5 and in the per-section comparisons throughout.

---

## 14. Where to go next

- **The schema itself**: `urn:hamilton:schemas:microlab:labware:v1` ([`labware.schema.json`](labware.schema.json)), with sibling schemas — `urn:hamilton:schemas:microlab:geometry:v1` ([`geometry.schema.json`](geometry.schema.json); Point2D/Point3D/Dimensions3D, Shape2D, Solid3D), `urn:hamilton:schemas:microlab:site:v1` ([`site.schema.json`](site.schema.json); SiteDefinition), and `urn:hamilton:schemas:microlab:alignment:v1` ([`alignment.schema.json`](alignment.schema.json); Alignment, AlignmentOffset).
- **Validation rules** ([`validation_rules.md`](validation_rules.md)) — every rule the schema enforces plus the semantic checks it cannot express.
- **The conventions document** ([`conventions.md`](conventions.md), alongside this tour) — recommended `labwareClass` values with per-class summaries, recommended tag vocabulary, canonical site-purpose `customAttributes` keys. Anyone authoring a new labware definition or instrument plugin should read it.
- **Class completeness** (§10.6) — the base schema requires each defined class's core aspects (containers, seating features, sites), so the catalog validates the full schema and rejects an incomplete definition of a defined class. Editors are intended to get these as per-kind required-field hints from generated per-kind views.

This document, the conventions document, and the schema are self-contained: nothing beyond them is needed to evaluate or author against the schema.

The schema's job is to make Hamilton's labware catalog legible across customers, instruments, and time. Anyone reading a definition file should be able to tell what the labware is, how it sits on a deck, what is inside it, and how their instrument plugs in — without reading JSON Schema syntax or knowing which version of VENUS the definition was converted from. If this document has done its job, you should now be able to do the same with the rest of the catalog.
