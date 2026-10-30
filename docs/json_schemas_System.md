> **Who needs this page?** This is the raw VENUS WebAPI wire format for the Deck Layout, System, Sample Tracking, and Teaching command categories (shared by STAR and Vantage). Most users should call the typed `StarClient`/`VantageClient` methods instead (see [STAR Commands](star_commands.md) and [Vantage Commands](vantage_commands.md)). Use this page when calling `client.send_command(category=..., action_name=..., parameters=...)` for commands without an SDK method, or when debugging the JSON the SDK sends. `send_command` builds the `channel`/`data` envelope for you.
>
> API base: `http://localhost:42400/api/vector/v3/run-messages` (default `base_url`; see [Configuration](configuration.md))

# Deck Layout

### Deck File

#### deck.deleteSavedDeck
```json
{
  "channel": "action",
  "data": { "category": "Deck Layout", "actionName": "deck.deleteSavedDeck", "parameters": { "name": "MyDeck" } }
}
```
**Returns:**
```json
{
  "message": "\"MyDeck\" was deleted"
}
```

#### deck.getPreviousDeck
```json
{ "channel": "action", "data": { "category": "Deck Layout", "actionName": "deck.getPreviousDeck", "parameters": {} } }
```
**Returns:**
```json
{
  "deckAvailable": true
}
```

#### deck.getSavedDecks
```json
{ "channel": "action", "data": { "category": "Deck Layout", "actionName": "deck.getSavedDecks", "parameters": {} } }
```
**Returns:**
```json
{
  "savedDecks": [
    "MyDeck"
  ]
}
```

#### deck.loadDeck
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "deck.loadDeck",
    "parameters": { "deck": "MyDeck", "previous": false }
  }
}
```
> Set `"previous": true` (and omit `deck`) to reload the last used deck.

**Returns:**
```json
{
  "message": "Load \"MyDeck\""
}
```

#### deck.saveDeck
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "deck.saveDeck",
    "parameters": { "name": "MyDeck", "overwrite": false }
  }
}
```

**Returns:**
```json
{
  "message": "\"MyDeck\" was saved"
}
```

#### deck.importDeck
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "deck.importDeck",
    "parameters": { "path": "C:\\Users\\User\\Documents\\layout.lay" }
  }
}
```
> `path`: full file-system path to a `.lay` layout file

**Returns:**
```json
{
  "carriersAdded": [
    {
      "labwareName": "tip_car_480bc_tip_50f_pink_0002",
      "leftTrack": 12
    },
    {
      "labwareName": "mfx_car_odtc_mtp",
      "x": 100,
      "y": 63,
      "z": 100,
      "angle": 0
    },
    {
      "labwareName": "mfx_car_2mtp_hptab_midi_hptab_2dwp_hptab_0001",
      "leftTrack": 35
    }
  ]
}
```

#### deck.GetRackIdsFromDeck
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "deck.GetRackIdsFromDeck",
    "parameters": {
      "path": "path to the layout.lay",
      "carrierFilter": [],
      "onlyFloatingRacks": true
    }
  }
}
```
> `path`: full file-system path to a `.lay` layout file  
> `carrierFilter`: array of carrier names to filter results (empty = no filter)  
> `onlyFloatingRacks`: when `true`, returns only floating (non-track) racks

---
**Returns:**
```json
{
  "racksFound": {
    "LiquidWaste_0001": {
      "file": "C:\\Users\\User\\Documents\\LiquidWaste.rck",
      "x": 1332,
      "y": 341,
      "z": 187,
      "angle": 0
    },
    "Ham_ComfortLid_Waste": {
      "file": "C:\\Users\\User\\Documents\\Ham_1_NB_Lid_ODTC_V1.0.rck",
      "x": 1415,
      "y": 300,
      "z": 265,
      "angle": 180
    }
  }
}
```

#### deck.importRackAsSite
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "deck.importRackAsSite",
    "parameters": {
      "path": "path to the layout.lay",
      "carrierFilter": [],
      "onlyFloatingRacks": true,
      "targetLabwareName": "sealer",
      "siteName": "plate sealer"
    }
  }
}
```
> `path`: full file-system path to a `.lay` layout file  
> `carrierFilter`: array of carrier names to filter results (empty = no filter)  
> `onlyFloatingRacks`: when `true`, returns only floating (non-track) racks  
> `targetLabwareName`: the labware name to import as a site  
> `siteName` *(optional)*: name for the new site; defaults to `targetLabwareName` if not specified

**Returns:**
```json
{
  "siteAdded": "plate sealer"
}
```

### Deck Status

#### status.getOccupiedTracks
```json
{ "channel": "action", "data": { "category": "Deck Layout", "actionName": "status.getOccupiedTracks", "parameters": {} } }
```
**Returns:**
```json
{
  "tracksOccupied": [
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    13
  ]
}
```
#### status.isTrackOccupied
```json
{
  "channel": "action",
  "data": { "category": "Deck Layout", "actionName": "status.isTrackOccupied", "parameters": { "trackId": 5 } }
}
```

**Returns:**
```json
{
  "isOccupied": true
}
```

#### status.getAvailableTracks
```json
{ "channel": "action", "data": { "category": "Deck Layout", "actionName": "status.getAvailableTracks", "parameters": {} } }
```

**Returns:**
```json
{
  "tracksAvailable": [
    -3,
    -2,
    -1,
    0,
    14,
    15,
    16,
    45,
    46,
    47,
    48,
    49,
    50,
    51,
    52,
    53,
    54
  ]
}
```

#### status.getAvailableCarrierSites
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "status.getAvailableCarrierSites",
    "parameters": { "carrier": "Deep Well Carrier" }
  }
}
```

**Returns:**
```json
{
  "availableSites": [
    "3",
    "4",
    "5"
  ]
}
```

#### status.getOccupiedCarrierSites
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "status.getOccupiedCarrierSites",
    "parameters": { "carrier": "Deep Well Carrier" }
  }
}
```

**Returns:**
```json
{
  "usedSites": [
    {
      "site": "1",
      "labwareCount": 1
    },
    {
      "site": "2",
      "labwareCount": 1
    }
  ]
}
```

#### status.getAddedPlates
```json
{ "channel": "action", "data": { "category": "Deck Layout", "actionName": "status.getAddedPlates", "parameters": {} } }
```

**Returns:**
```json
{
  "totalPlates": 1,
  "platesAdded": [
    "plate 1"
  ]
}
```

#### status.getAddedCarriers
```json
{ "channel": "action", "data": { "category": "Deck Layout", "actionName": "status.getAddedCarriers", "parameters": {} } }
```

**Returns:**
```json
{
  "totalCarriers": 3,
  "carriersAdded": [
    "deep well carrier",
    "tube carrier 1",
    "tip carrier"
  ]
}
```

#### status.getAddedTipRacks
```json
{ "channel": "action", "data": { "category": "Deck Layout", "actionName": "status.getAddedTipRacks", "parameters": {} } }
```

**Returns:**
```json
{
  "totalTipRacks": 1,
  "tipRacksAdded": [
    "st_l_0001"
  ]
}
```

#### status.getAddedReservoirs
```json
{ "channel": "action", "data": { "category": "Deck Layout", "actionName": "status.getAddedReservoirs", "parameters": {} } }
```

**Returns:**
```json
{
  "totalReservoirs": 1,
  "reservoirsAdded": [
    "reservoir 1"
  ]
}
```

#### status.getLabwareOnCarrier
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "status.getLabwareOnCarrier",
    "parameters": { "carrier": "Deep Well Carrier" }
  }
}
```

**Returns:**
```json
{
  "totalLabware": 2,
  "labware": [
    {
      "labwareName": "plate 1",
      "labwareType": "plate"
    },
    {
      "labwareName": "reservoir 1",
      "labwareType": "reservoir"
    }
  ]
}
```

#### status.getTopLabware
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "status.getTopLabware",
    "parameters": { "carrierId": "Deep Well Carrier", "site": "1" }
  }
}
```

**Returns:**
```json
{
  "labwareId": "plate 1",
  "type": "plate",
  "hasLid": true,
  "lid": "plate 1_LID"
}
```

#### status.getLabwarePositions
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "status.getLabwarePositions",
    "parameters": { "labwareName": "Plate 1" }
  }
}
```
**Returns**
```json
{
  "plate 1": {
    "count": 96,
    "positions": [
      "A1",
      "B1",
      "C1",
      "D1",
      "E1",
      "F1",
      "G1",
      "H1",
      ...
      "A12",
      "B12",
      "C12",
      "D12",
      "E12",
      "F12",
      "G12",
      "H12"
    ]
  }
}
```
#### status.getLabwareLocation
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "status.getLabwareLocation",
    "parameters": { "labwareName": "Plate 1" }
  }
}
```
**Returns:**
>`plate`
```json
{
  "carrier": "deep well carrier",
  "site": "1"
}
```
>`carrier`
```json
{
  "trackWidth": 6,
  "leftTrack": 1
}
```
#### status.getLabwareCoordinates
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "status.getLabwareCoordinates",
    "parameters": {
      "labwareName": "Test Labware",
      "well": "A1"
    }
  }
}
```
> `well` is optional, and the response has a different shape with and without it.

**Returns:**
>with `well` -- that well's coordinates (`well` is echoed back upper-cased)
```json
{
  "well": "A1",
  "x": 100.0,
  "y": 200.0,
  "z": 245.0,
  "angle": 0.0
}
```
>without `well`, rack-type labware (`.rck`: plate, tip rack, tube rack, reservoir) -- the labware `origin` and the coordinates of every position in `wells`, ordered by column (A1, B1, ..., A2, ...)
```json
{
  "origin": { "x": 95.5, "y": 63.0, "z": 186.15, "angle": 0.0 },
  "wells": [
    { "well": "A1", "x": 100.0, "y": 200.0, "z": 245.0, "angle": 0.0 },
    { "well": "B1", "x": 100.0, "y": 191.0, "z": 245.0, "angle": 0.0 }
  ]
}
```
>without `well`, carrier -- `origin` only (a carrier has no wells; `wells` is not returned)
```json
{
  "origin": { "x": 95.5, "y": 63.0, "z": 186.15, "angle": 0.0 }
}
```
> The top-level `x` / `y` / `z` / `angle` are returned only when `well` is specified.

---

### Labware

#### labware.addCarrier
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addCarrier",
    "parameters": {
      "labwareName": "Deep Well Carrier",
      "labwareDefinition": "DW_Carrier_3Pos",
      "leftTrack": 10
    }
  }
}
```
> `labwareName` *(optional)*: if omitted, a name is auto-generated  

**Returns:**
```json
{
  "labwareName": "deep well carrier"
}
```

#### labware.addCarrierToSite
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addCarrierToSite",
    "parameters": {
      "labwareName": "Test Carrier",
      "labwareDefinition": "Alpaqua_MagEx",
      "carrier": "PLT_CAR_L5_DWP",
      "site": "5"
    }
  }
}
```
> `labwareName` *(optional)*: the name to assign the new carrier being added; if omitted, a name is auto-generated  
> `labwareDefinition` *(required)*: the name of the definition for the carrier to add to the site  
> `carrier` *(optional)*: allows specifying an already existent carrier to load the new carrier onto, e.g. a Magnet module; if not specified, the carrier is added to a site on the deck  
> `site` *(required)*: the name of the site to load the carrier

**Returns:**
```json
{
  "labwareName": "test carrier"
}
```

#### labware.moveCarrier
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.moveCarrier",
    "parameters": {
      "labwareName": "ntr carrier",
      "leftTrack": 40,
      "site": ""
    }
  }
}
```
> `site` *(optional)*: carrier site; if omitted, Venus assigns an available site automatically

**Returns:**
```json
{
  "message": "ntr carrier moved to site \"6T-40\""
}
```

#### labware.addSampleTubeCarrier
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addSampleTubeCarrier",
    "parameters": {
      "labwareName": "Tube Carrier 1",
      "labwareDefinition": "SampleCarrier_16Pos",
      "leftTrack": 5
    }
  }
}
```
> `labwareName` *(optional)*: if omitted, a name is auto-generated

**Returns:**
```json
{
  "labwareName": "tube carrier 1"
}
```

#### labware.addTipRack
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addTipRack",
    "parameters": {
      "tipPool": "300 uL Tips",
      "labwareDefinition": "TipRack_300uL",
      "carrier": "Tip Carrier",
      "site": "1",
      "labwareName": "300uLTip"
    }
  }
}
```

**Returns:**
```json
{
  "totalTips": 96,
  "tipPoolName": "300ul tips",
  "labwareName": "st_l_0001",
  "tipType": 0
}
```

#### labware.addTipBox
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addTipBox",
    "parameters": {
      "tipPool": "300 uL Tips",
      "labwareDefinition": "ST_L",
      "carrier": "Test Carrier",
      "site": "5",
      "labwareName": "300uLTip"
    }
  }
}
```
**Returns:**
```json
{
  "totalTips": 96,
  "tipPoolName": "300ul tips",
  "labwareName": "st_l_0001",
  "tipType": 0
}
```

#### labware.addNTR
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addNTR",
    "parameters": {
      "tipPool": "300 uL Tips",
      "labwareDefinition": "ST_L_NTR",
      "carrier": "Test Carrier",
      "site": "5",
      "stack": 4,
      "labwareName": "300uLTip"
    }
  }
}
```
> `stack` range: 1–4  
> `labwareDefinition`: tip_rack labware definitions containing "NTR" in the name

**Returns:**
```json
{
  "totalTips": 384,
  "tipPoolName": "300ul tips",
  "labwareName": ["300ultip_0001", "300ultip_0002", "300ultip_0003", "300ultip_0004"],
  "tipType": 0
}
```
> `labwareName` lists the stack's racks bottom to top. With a `labwareName` parameter they are named from it, lowercased, with the first free `_NNNN` suffix (a second stack with the same name continues at `_0005`); without one, from the definition (`st_l_ntr_0001`, ...).

#### labware.addPlate
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addPlate",
    "parameters": {
      "labwareName": "Plate 1",
      "labwareDefinition": "Cos_96_Rd",
      "carrier": "Deep Well Carrier",
      "site": "1"
    }
  }
}
```
> `labwareName` *(optional)*: if omitted, a name is auto-generated

**Returns:**
```json
{
  "labwareName": "plate 1"
}
```
#### labware.addLiddedPlate
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addLiddedPlate",
    "parameters": {
      "labwareName": "Test Plate",
      "labwareDefinition": "Nun_96_Fl_HB",
      "lidDefinition": "Nunc_Lid",
      "carrier": "Test Carrier",
      "site": "5"
    }
  }
}
```
> `labwareName` *(optional)*: if omitted, a name is auto-generated  
> `lidDefinition` *(required)*: the name of the definition for the lid to add on top of the plate

**Returns:**
```json
{
  "labwareName": "test plate",
  "lidName": "test plate_lid"
}
```

#### labware.addLid
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addLid",
    "parameters": {
      "labwareName": "Test Lid",
      "labwareDefinition": "Nunc_Lid",
      "carrier": "Test Carrier",
      "site": "5"
    }
  }
}
```
> `labwareName` *(optional)*: if omitted, a name is auto-generated

**Returns:**
```json
{
  "labwareName": "test lid"
}
```

#### labware.addReservoir
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addReservoir",
    "parameters": {
      "labwareName": "Reservoir 1",
      "labwareDefinition": "Trough_100ml",
      "carrier": "Reagent Carrier",
      "site": "1"
    }
  }
}
```
> `labwareName` *(optional)*: if omitted, a name is auto-generated

**Returns:**
```json
{
  "labwareName": "reservoir 1"
}
```

#### labware.addTipSupport
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addTipSupport",
    "parameters": {
      "carrier": "Tip Carrier",
      "site": "2"
    }
  }
}
```

**Returns:**
```json
{
  "labwareName": "tip support 1"
}
```

#### labware.removeLabware
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.removeLabware",
    "parameters": { "labwareName": "Plate 1" }
  }
}
```

**Returns:**
```json
{
  "labwareRemoved": [
    "reservoir 1"
  ]
}
```

#### labware.shiftLabware
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.shiftLabware",
    "parameters": {
      "labwareName": "Test Plate",
      "relativeX": 0.0,
      "relativeY": 0.0,
      "relativeZ": 0.0,
      "relativeAngle": 0.0
    }
  }
}
```
> `relativeX`, `relativeY`, `relativeZ`, `relativeAngle` are all *(optional)*, default `0.0`

**Returns:**
```json
{
  "x": 100.0,
  "y": 200.0,
  "z": 245.0,
  "angle": 0.0
}
```

#### labware.tiltLabware
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.tiltLabware",
    "parameters": {
      "labwareName": "Plate_1",
      "tiltDegrees": 7,
      "pivotPoint": "LeftEdge",
      "pivotXOffset": 0.0,
      "pivotZOffset": 0.0,
      "wellPosition": "Center",
      "wells": [
        {"well": "A1", "deltaX": -0.5394, "deltaY": 0.0, "deltaZ": 5.2496},
        {"well": "B1", "deltaX": -0.5394, "deltaY": 0.0, "deltaZ": 5.2496},
        {"well": "H12", "deltaX": -1.2774, "deltaY": 0.0, "deltaZ": 17.3146}
      ]
    }
  }
}
```
> Sent by `tilt_labware()`, which computes `wells` from the plate's labware definition (plates only, 0-10 degrees). The example is Cos_96_Fl at 7 degrees, left-edge pivot (wells A1, B1 and H12 of 96 shown).
> - Every well of the plate is sent, column by column, including at 0 degrees.
> - Set each well's X / Y to its **nominal** X / Y plus `deltaX` / `deltaY` (`deltaY` is always 0), and its container base offset to `deltaZ`. Never accumulate onto the current values.
> - `deltaZ` includes the rack-base-to-container-base offset, so at 0 degrees every well is `deltaX 0.0`, `deltaZ` = the definition's `firstContainerCenter.z` (3.57 for Cos_96_Fl): the plate is back to normal.
> - `deltaZ` can be negative with `"pivotPoint": "Center"` (left half of the plate drops below the pivot).
> - Keep the labware item (no remove / re-add) so sample tracking survives. Fail on an unknown well name.
> - `pivotPoint` (`"LeftEdge"` / `"Center"`), `pivotXOffset`, `pivotZOffset` and `wellPosition` are informational; only `wells` is applied.
> - `wellPosition` is where in each well the deltas aim: `"Center"`, `"DeepestPoint"` (as close to the low wall as one tip fits) or `"HighestPoint"` (as close to the high wall as it fits); the SDK computes that aim from the tip, the tip end height and the wall margins and folds it into `wells`. At 0 degrees it is always `"Center"`.

**Returns:**
```json
{
  "labwareName": "plate_1",
  "tiltDegrees": 7.0,
  "wells": [
    {"well": "A1", "x": 275.4606, "y": 146.0, "z": 107.0496},
    {"well": "H12", "x": 373.7226, "y": 83.0, "z": 119.1146}
  ]
}
```
> `wells` holds each updated well's deck coordinates after the tilt (one entry per well sent).

#### labware.addSplitWellSite
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addSplitWellSite",
    "parameters": {
      "splitLabwareName": "plate_1_a1_split_1ml_4slots",
      "parentLabwareName": "Plate_1",
      "parentWell": "A1",
      "definition": {
        "$schema": "urn:hamilton:schemas:microlab:labware:v1",
        "id": "user:plate_1_a1_split_1ml_4slots",
        "schemaVersion": "1.0.0-alpha.1",
        "displayName": "plate_1_a1_split_1ml_4slots",
        "description": "Temporary split-well rack (4 x 9 mm)",
        "labwareClass": "plate",
        "source": {"system": "manual"},
        "dimensions": {"x": 9.0, "y": 36.0, "z": 16.5},
        "containerGrids": {
          "default": {
            "columns": 1,
            "rows": 4,
            "columnPitch": 9.0,
            "rowPitch": 9.0,
            "iterationOrder": "row_major",
            "firstContainerCenter": {"x": 4.5, "y": 4.5, "z": 0.0},
            "namingConvention": {"rowStyle": "numeric", "columnStyle": "numeric", "format": "[row][col]"},
            "containerDefinition": {
              "openingDimensions": {"shape": "circle", "diameter": 7.2},
              "totalDepth": 16.5,
              "maxPipettingDepth": 0.0,
              "bottomWallThickness": 0.0,
              "volumeModel": {"segments": [{"type": "cylinder", "height": 16.5, "diameter": 7.2}]},
              "liquidDetection": {"supportsLLD": true, "liquidSeekingStartHeight": 21.5},
              "customAttributes": {
                "hamilton:touch_off": {"enabled": false, "frontMm": 0.0, "backMm": 0.0, "leftMm": 0.0, "rightMm": 0.0, "baseMm": 0.0, "heightMm": 0.0},
                "hamilton:clearance": {"clearanceMm": 21.5}
              }
            },
            "customAttributes": {"hamilton:ix_params": {"first": 1, "startingCorner": "back_left"}}
          }
        },
        "alignmentFeatures": [{"name": "sbs_rim", "offset": {"z": 0.0}}],
        "selfStack": {"height": 0.0},
        "visualModel": {"color": "#FFFFFF", "opacity": 0},
        "customAttributes": {"hamilton:is_user_defined": {"value": true}}
      },
      "slots": [
        {"well": "1", "deltaX": 0.0, "deltaY": 13.5, "deltaZ": 0.0},
        {"well": "2", "deltaX": 0.0, "deltaY": 4.5, "deltaZ": 0.0},
        {"well": "3", "deltaX": 0.0, "deltaY": -4.5, "deltaZ": 0.0},
        {"well": "4", "deltaX": 0.0, "deltaY": -13.5, "deltaZ": 0.0}
      ],
      "rackDeltaX": -4.5,
      "rackDeltaY": -18.0,
      "rackDeltaZ": 0.0
    }
  }
}
```
> Sent by `split_wells()`, once per parent well. It places a temporary rack of channel-pitch slots inside one large well, so several channels can pipette into it at once. The example is Greiner_Culture_Plate_6 well A1 split for 1 mL channels: 4 slots at 9 mm.
> - `splitLabwareName`: id of the temporary rack, `<parent>_<well>_split_<1ml|5ml>_<N>slots` (N = the slot count), lower-cased. An existing rack with this id is removed first.
> - `parentLabwareName` / `parentWell`: the well being split. The parent must be on the deck.
> - `definition`: the rack's complete labware:v1 definition (not a definition name). It has one column of N positions at the channel pitch (9 mm for 1 mL channels, 18 mm for 5 mL), numbered `1`..`N` from the back. Its own wells are placeholders: every slot gets the parent well's container file, so depth, Z bottom and LLD behave as in the parent well.
> - `slots`: one entry per slot, back to front. `well` is the slot's position in the rack. `deltaX` / `deltaY` / `deltaZ` are deck millimetres from the parent well's **current** position (as `DevGetLabwarePositionEx` reports it, so it already includes any `tilt_labware` offset). Each delta is in -100..100 mm.
>   - `deltaY` spreads the slots at the channel pitch.
>   - `deltaX` is non-zero only on a tilted plate, when `split_wells` aims the slots away from where the parent well is aimed.
>   - `deltaZ` raises a slot's container base: onto a V- or round-bottom floor, or up a tilted floor.
> - `rackDeltaX` / `rackDeltaY`: where the rack's origin goes relative to the parent well, so the rack sits over the well; each slot is still placed on its own.
> - `rackDeltaZ` is always slot 1's `deltaZ`. VENUS ignores a container Z offset on rack position 1, so the whole rack is raised to slot 1's height and the other slots are placed relative to it.
> - Each slot is placed so its final position is the parent well's position plus its deltas, whatever the rack's origin or row direction: add the parent's container with no offset, read the slot's position, then add it again with the difference to the target.
> - The rack sits on the deck rather than on a carrier site. Layout tracking does not track it, and `labware.removeLabware` removes it.
> - On failure, the partly built rack is removed.

The same well on a plate tilted 10 degrees at its deepest point, split with `fit=SplitWellFit.MAX_CHANNELS`. The slots are pulled 6.04 mm in X back from the deepest point so all four fit, which raises them 1.06 mm up the tilted floor. `rackDeltaZ` equals slot 1's `deltaZ`:
```json
{
  "slots": [
    {"well": "1", "deltaX": 6.0394, "deltaY": 13.5, "deltaZ": 1.0649},
    {"well": "2", "deltaX": 6.0394, "deltaY": 4.5, "deltaZ": 1.0649},
    {"well": "3", "deltaX": 6.0394, "deltaY": -4.5, "deltaZ": 1.0649},
    {"well": "4", "deltaX": 6.0394, "deltaY": -13.5, "deltaZ": 1.0649}
  ],
  "rackDeltaX": 1.5394,
  "rackDeltaY": -18.0,
  "rackDeltaZ": 1.0649
}
```

**Returns:**
```json
{
  "splitLabwareName": "plate_1_a1_split_1ml_4slots",
  "parentLabwareName": "plate_1",
  "parentWell": "A1",
  "slots": [
    {"well": "1", "x": 1072.7, "y": 532.9, "z": 209.65},
    {"well": "2", "x": 1072.7, "y": 523.9, "z": 209.65},
    {"well": "3", "x": 1072.7, "y": 514.9, "z": 209.65},
    {"well": "4", "x": 1072.7, "y": 505.9, "z": 209.65}
  ]
}
```
> `slots` holds the deck coordinates of each slot of this one rack after placement, from `DevGetLabwarePositionEx`. One entry is returned per slot sent. The example comes from a Vantage simulation, where the parent well A1 is at (1072.7, 519.4, 209.65).

#### labware.addTubesToCarrier
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addTubesToCarrier",
    "parameters": {
      "labwareName": "Sample Tubes",
      "positions": [
        {
          "position": "1",
          "tube": "my tube",
          "xOffset": 0.0,
          "yOffset": 0.0,
          "zOffset": 10.0
        }
      ]
    }
  }
}
```

**Returns:**
```json
{
  "positions": [
    {
      "position": "1",
      "x": 100.0,
      "y": 200.0,
      "z": 245.0
    }
  ]
}
```

#### labware.add1mLCoreGrip
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.add1mLCoreGrip",
    "parameters": { "type": 0 }
  }
}

```

**`type` values:**

| Value | Description |
|-------|-------------|
| `0` | Standard Core Grip |
| `1` | Deep Grip (Tip Box) |

**Returns:**
```json
{
  "labwareName": "CoreGrip1mL",
  "transportID": 1
}
```

#### labware.add5mLCoreGrip
```json
{ "channel": "action", "data": { "category": "Deck Layout", "actionName": "labware.add5mLCoreGrip", "parameters": {} } }
```

**Returns:**
```json
{
  "labwareName": "CoreGrip5mL",
  "transportID": 3
}
```

#### labware.addChannelLiquidWaste
```json
{ "channel": "action", "data": { "category": "Deck Layout", "actionName": "labware.addChannelLiquidWaste", "parameters": {} } }
```

**Returns:**
```json
{
  "labwareName": "liquid_waste"
}
```

#### labware.addQCG

```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addQCG",
    "parameters": { "type": 0}
  }
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `type` | int | Yes | QCG variant (see table below) |
| `track` | int | No *(Vantage only)* | QCG occupies 2 tracks. If omitted, loads in default location. |

**`type` values:**

| Value | Description |
|-------|-------------|
| `0` | QCG |
| `1` | QCG (Deep) |
| `2` | QCG (Mid) |

**Returns:**
```json
{
  "labwareName": "QCG",
  "transportID": 10
}
```


#### labware.addLiquidWaste
*(Vantage only)*
```json
{ "channel": "action", "data": { "category": "Deck Layout", "actionName": "labware.addLiquidWaste", "parameters": { "track": 0 } } }
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `track` | int | No | Track position *(optional)* — waste is 6 tracks wide, occupies site 1 of Multiflex carrier |

#### labware.addTransportSite
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.addTransportSite",
    "parameters": {
      "siteName": "ODTC",
      "xCenter": -24.1,
      "yCenter": 252.6,
      "zBottom": 201.5,
      "angleIndex": 1
    }
  }
}
```
> `angleIndex`: 1=0°, 2=90°, 3=180°, 4=270°

**Returns:**
```json
{
  "siteAdded": "odtc"
}
```

#### status.getTransportTool
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "status.getTransportTool",
    "parameters": { "is1mL": true }
  }
}
```
> Use one of `is1mL` (bool), `isQCG` (bool), or `toolId` (int) — mutually exclusive.

**Returns:**
```json
{
  "transportToolID": 1,
  "labwareName": "CoreGrip1mL",
  "transportToolPositions": {
    "count": 2,
    "positions": [
      "1",
      "2"
    ]
  }
}
```

#### status.getTransportToolIds
```json
{ "channel": "action", "data": { "category": "Deck Layout", "actionName": "status.getTransportToolIds", "parameters": {} } }
```

**Returns:**
```json
{
  "transportTools": [
    {
      "labwareName": "CoreGrip1mL",
      "toolID": 1
    },
    {
      "labwareName": "CoreGrip1mLDeep",
      "toolID": 2
    },
    {
      "labwareName": "QCG",
      "toolID": 10
    },
    {
      "labwareName": "QCG_Deep",
      "toolID": 12
    },
    {
      "labwareName": "QCG_Mid",
      "toolID": 11
    }
  ]
}
```

#### labware.removeTransportTool
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.removeTransportTool",
    "parameters": { "toolId": 0 }
  }
}
```

**Returns:**
```json
{
  "message": "toolId 11 was removed"
}
```
#### labware.getLabwareParamsFromID
```json
{
  "channel": "action",
  "data": {
    "category": "Deck Layout",
    "actionName": "labware.getLabwareParamsFromID",
    "parameters": { "labwareName": "Plate 1" }
  }
}
```
> Returns full labware definition under key `definition`. Height found at `definition.rack_layout.dimensions.height_mm`.

**Returns:**
```json
{
  "definition": {
    ...
   }
}
```
# System

### Tip Pool

#### tipPool.getAvailableTips
```json
{
  "channel": "action",
  "data": { "category": "System", "actionName": "tipPool.getAvailableTips", "parameters": { "tipPool": "300 uL Tips" } }
}
```
**Returns:**
```json
{
  "totalAvailableTips": 40,
  "availableTips": [
    {
      "st_l_0001": {
        "count": 40,
        "positions": [
          "57",
          "58",
          "59",
          "60",
          "61",
          "62",
          "63",
          "64",
          "65",
          "66",
          "67",
          "68",
          "69",
          "70",
          "71",
          "72",
          "73",
          "74",
          "75",
          "76",
          "77",
          "78",
          "79",
          "80",
          "81",
          "82",
          "83",
          "84",
          "85",
          "86",
          "87",
          "88",
          "89",
          "90",
          "91",
          "92",
          "93",
          "94",
          "95",
          "96"
        ]
      }
    }
  ]
}
```

#### tipPool.getEmptyTips
```json
{
  "channel": "action",
  "data": { "category": "System", "actionName": "tipPool.getEmptyTips", "parameters": { "tipPool": "300 uL Tips" } }
}
```
**Returns:**
```json
{
  "totalEmptyTips": 48,
  "emptyTips": [
    {
      "st_l_0001": {
        "count": 56,
        "positions": [
          "1",
          "2",
          "3",
          "4",
          "5",
          "6",
          "7",
          "8",
          "9",
          "10",
          "11",
          "12",
          "13",
          "14",
          "15",
          "16",
          "17",
          "18",
          "19",
          "20",
          "21",
          "22",
          "23",
          "24",
          "25",
          "26",
          "27",
          "28",
          "29",
          "30",
          "31",
          "32",
          "33",
          "34",
          "35",
          "36",
          "37",
          "38",
          "39",
          "40",
          "41",
          "42",
          "43",
          "44",
          "45",
          "46",
          "47",
          "48",
          "49",
          "50",
          "51",
          "52",
          "53",
          "54",
          "55",
          "56"
        ]
      }
    }
  ]
}
```
#### tipPool.getMissingRacks
```json
{
  "channel": "action",
  "data": { "category": "System", "actionName": "tipPool.getMissingRacks", "parameters": { "tipPool": "300 uL Tips" } }
}
```
**Returns:**
```json
{
  "missingRacks": ["tip_nested_300ul_0002", "tip_nested_300ul_0003"]
}
```
> Rack names (labware ids) of the pool's racks marked not present: racks transported away, or racks left out of a `tipPool.setTipCounter`. Empty when every rack is present.
#### tipPool.getTipCounter
```json
{
  "channel": "action",
  "data": { "category": "System", "actionName": "tipPool.getTipCounter", "parameters": { "tipPool": "300 uL Tips" } }
}
```
**Returns:**
```json
{
  "tipType": 0,
  "totalAvailableTips": 40,
  "totalEmptyTips": 48,
  "totalConsumedTips": 0,
  "availableTips": [
    {
      "st_l_0001": {
        "count": 40,
        "positions": [
          "57",
          "58",
          "59",
          "60",
          "61",
          "62",
          "63",
          "64",
          "65",
          "66",
          "67",
          "68",
          "69",
          "70",
          "71",
          "72",
          "73",
          "74",
          "75",
          "76",
          "77",
          "78",
          "79",
          "80",
          "81",
          "82",
          "83",
          "84",
          "85",
          "86",
          "87",
          "88",
          "89",
          "90",
          "91",
          "92",
          "93",
          "94",
          "95",
          "96"
        ]
      }
    }
  ],
  "emptyTips": [
    {
      "st_l_0001": {
        "count": 56,
        "positions": [
          "1",
          "2",
          "3",
          "4",
          "5",
          "6",
          "7",
          "8",
          "9",
          "10",
          "11",
          "12",
          "13",
          "14",
          "15",
          "16",
          "17",
          "18",
          "19",
          "20",
          "21",
          "22",
          "23",
          "24",
          "25",
          "26",
          "27",
          "28",
          "29",
          "30",
          "31",
          "32",
          "33",
          "34",
          "35",
          "36",
          "37",
          "38",
          "39",
          "40",
          "41",
          "42",
          "43",
          "44",
          "45",
          "46",
          "47",
          "48",
          "49",
          "50",
          "51",
          "52",
          "53",
          "54",
          "55",
          "56"
        ]
      }
    }
  ],
  "missingRacks": []
}
```
#### tipPool.getTipCounters
```json
{ "channel": "action", "data": { "category": "System", "actionName": "tipPool.getTipCounters", "parameters": {} } }
```
**Returns:**
```json
{
  "tipCounterNames": [
    "300ul tips"
  ]
}
```

#### tipPool.initializeTipCounter
```json
{
  "channel": "action",
  "data": { "category": "System", "actionName": "tipPool.initializeTipCounter", "parameters": { "tipPool": "300 uL Tips" } }
}
```
**Returns:**
```json
{
  "availableTips": {
    "st_l_0001": {
      "count": 96,
      "positions": [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        "11",
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
        "19",
        "20",
        "21",
        "22",
        "23",
        "24",
        "25",
        "26",
        "27",
        "28",
        "29",
        "30",
        "31",
        "32",
        "33",
        "34",
        "35",
        "36",
        "37",
        "38",
        "39",
        "40",
        "41",
        "42",
        "43",
        "44",
        "45",
        "46",
        "47",
        "48",
        "49",
        "50",
        "51",
        "52",
        "53",
        "54",
        "55",
        "56",
        "57",
        "58",
        "59",
        "60",
        "61",
        "62",
        "63",
        "64",
        "65",
        "66",
        "67",
        "68",
        "69",
        "70",
        "71",
        "72",
        "73",
        "74",
        "75",
        "76",
        "77",
        "78",
        "79",
        "80",
        "81",
        "82",
        "83",
        "84",
        "85",
        "86",
        "87",
        "88",
        "89",
        "90",
        "91",
        "92",
        "93",
        "94",
        "95",
        "96"
      ]
    }
  }
}
```

#### tipPool.resetTipCounter
```json
{
  "channel": "action",
  "data": { "category": "System", "actionName": "tipPool.resetTipCounter", "parameters": { "tipPool": "300 uL Tips" } }
}
```
**Returns:**
```json
{
  "totalAvailableTips": 96,
  "availableTips": {
    "st_l_0001": {
      "count": 96,
      "positions": [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        "11",
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
        "19",
        "20",
        "21",
        "22",
        "23",
        "24",
        "25",
        "26",
        "27",
        "28",
        "29",
        "30",
        "31",
        "32",
        "33",
        "34",
        "35",
        "36",
        "37",
        "38",
        "39",
        "40",
        "41",
        "42",
        "43",
        "44",
        "45",
        "46",
        "47",
        "48",
        "49",
        "50",
        "51",
        "52",
        "53",
        "54",
        "55",
        "56",
        "57",
        "58",
        "59",
        "60",
        "61",
        "62",
        "63",
        "64",
        "65",
        "66",
        "67",
        "68",
        "69",
        "70",
        "71",
        "72",
        "73",
        "74",
        "75",
        "76",
        "77",
        "78",
        "79",
        "80",
        "81",
        "82",
        "83",
        "84",
        "85",
        "86",
        "87",
        "88",
        "89",
        "90",
        "91",
        "92",
        "93",
        "94",
        "95",
        "96"
      ]
    }
  }
}
```

#### tipPool.showTipCounter
```json
{
  "channel": "action",
  "data": { "category": "System", "actionName": "tipPool.showTipCounter", "parameters": { "tipPool": "300 uL Tips" } }
}
```
**Returns:**
```json
{
  "availableTips": {
    "st_l_0001": {
      "count": 40,
      "positions": [
        "57",
        "58",
        "59",
        "60",
        "61",
        "62",
        "63",
        "64",
        "65",
        "66",
        "67",
        "68",
        "69",
        "70",
        "71",
        "72",
        "73",
        "74",
        "75",
        "76",
        "77",
        "78",
        "79",
        "80",
        "81",
        "82",
        "83",
        "84",
        "85",
        "86",
        "87",
        "88",
        "89",
        "90",
        "91",
        "92",
        "93",
        "94",
        "95",
        "96"
      ]
    }
  }
}
```
#### tipPool.showTipCounters
```json
{
  "channel": "action",
  "data": { "category": "System", "actionName": "tipPool.showTipCounters", "parameters": { "tipPools": ["tips300ul", "tips50ul"] } }
}
```
> `tipPools` is optional -- omit it to show every tip counter.

**Returns:**
```json
{
  "tipCounters": [
    {
      "tipCounter": "tips300ul",
      "totalAvailableTips": 72,
      "availableTips": {
        "tip_rack_300ul_0001": {
          "count": 72,
          "positions": [
            "25", "26", "27", "28", "29", "30", "31", "32", "33", "34", "35", "36",
            "37", "38", "39", "40", "41", "42", "43", "44", "45", "46", "47", "48",
            "49", "50", "51", "52", "53", "54", "55", "56", "57", "58", "59", "60",
            "61", "62", "63", "64", "65", "66", "67", "68", "69", "70", "71", "72",
            "73", "74", "75", "76", "77", "78", "79", "80", "81", "82", "83", "84",
            "85", "86", "87", "88", "89", "90", "91", "92", "93", "94", "95", "96"
          ]
        }
      },
      "missingRacks": []
    },
    {
      "tipCounter": "tips50ul",
      "totalAvailableTips": 96,
      "availableTips": {
        "tip_rack_50ul_0001": {
          "count": 96,
          "positions": [
            "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
            "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24",
            "25", "26", "27", "28", "29", "30", "31", "32", "33", "34", "35", "36",
            "37", "38", "39", "40", "41", "42", "43", "44", "45", "46", "47", "48",
            "49", "50", "51", "52", "53", "54", "55", "56", "57", "58", "59", "60",
            "61", "62", "63", "64", "65", "66", "67", "68", "69", "70", "71", "72",
            "73", "74", "75", "76", "77", "78", "79", "80", "81", "82", "83", "84",
            "85", "86", "87", "88", "89", "90", "91", "92", "93", "94", "95", "96"
          ]
        }
      },
      "missingRacks": []
    }
  ]
}
```
> One entry per requested tip pool (or every tip pool if `tipPools` was omitted). `availableTips` is keyed by rack id; `missingRacks` lists the names of the pool's racks marked not present (e.g. `["tip_nested_300ul_0002"]`), as `tipPool.getMissingRacks` does.

#### tipPool.setTipCounter
```json
{
  "channel": "action",
  "data": {
    "category": "System",
    "actionName": "tipPool.setTipCounter",
    "parameters": {
    "tipPool": "300ul tips",
    "availableTips": [
      {
        "st_l_0001": {
          "count": 96,
          "positions": [
            "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
            "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
            "21", "22", "23", "24", "25", "26", "27", "28", "29", "30",
            "31", "32", "33", "34", "35", "36", "37", "38", "39", "40",
            "41", "42", "43", "44", "45", "46", "47", "48", "49", "50",
            "51", "52", "53", "54", "55", "56", "57", "58", "59", "60",
            "61", "62", "63", "64", "65", "66", "67", "68", "69", "70",
            "71", "72", "73", "74", "75", "76", "77", "78", "79", "80",
            "81", "82", "83", "84", "85", "86", "87", "88", "89", "90",
            "91", "92", "93", "94", "95", "96"
          ]
        }
      }
    ]
  }
}
}
```
**Returns:**
```json
{
  "tipPool": "300ul tips",
  "availableTips": [
    {
      "st_l_0001": {
        "count": 96,
        "positions": [
          "1",
          "2",
          "3",
          "4",
          "5",
          "6",
          "7",
          "8",
          "9",
          "10",
          "11",
          "12",
          "13",
          "14",
          "15",
          "16",
          "17",
          "18",
          "19",
          "20",
          "21",
          "22",
          "23",
          "24",
          "25",
          "26",
          "27",
          "28",
          "29",
          "30",
          "31",
          "32",
          "33",
          "34",
          "35",
          "36",
          "37",
          "38",
          "39",
          "40",
          "41",
          "42",
          "43",
          "44",
          "45",
          "46",
          "47",
          "48",
          "49",
          "50",
          "51",
          "52",
          "53",
          "54",
          "55",
          "56",
          "57",
          "58",
          "59",
          "60",
          "61",
          "62",
          "63",
          "64",
          "65",
          "66",
          "67",
          "68",
          "69",
          "70",
          "71",
          "72",
          "73",
          "74",
          "75",
          "76",
          "77",
          "78",
          "79",
          "80",
          "81",
          "82",
          "83",
          "84",
          "85",
          "86",
          "87",
          "88",
          "89",
          "90",
          "91",
          "92",
          "93",
          "94",
          "95",
          "96"
        ]
      }
    }
  ]
}
```
---

### Labware

#### labware.addLabwareDefinition
```json
{
  "channel": "action",
  "data": {
    "category": "System",
    "actionName": "labware.addLabwareDefinition",
    "parameters": {
      "labwareDefinition": "My Custom Plate",
      "definition": {}
    }
  }
}
```
**Returns:**
```json
{
  "message": "\"My Custom Plate\" added"
}
```

> The labware category is taken from the `labwareClass` inside `definition`.

#### labware.importLabwareDefinition
> Converts a VENUS labware file (`.rck`, ...) into a labware definition, instead of an inline `definition` object. Note this uses a separate `actionName` from `labware.addLabwareDefinition` above. VENUS works out the labware type from the file and stores the converted definition under `Labware\User\<type>\`.

```json
{
  "channel": "action",
  "data": {
    "category": "System",
    "actionName": "labware.importLabwareDefinition",
    "parameters": {
      "labwareDefinition": "Test Labware",
      "labwarePath": "C:\\My\\New\\Labware.rck"
    }
  }
}
```
> `labwareDefinition` *(optional)*: name for the labware definition; if omitted, the name is taken from the file name  
> `labwarePath`: path to the labware file

**Returns:**
```json
{
  "message": "\"Test Labware\" added",
  "definition": { ... }
}
```
> `definition`: the converted definition. Its 3D models are referenced as VENUS has them (`"modelRef": "Labware.hxx"` or `.x`); the SDK's `labware_definition_import_definition` converts those to glTF in `Labware\Models` and updates the stored definition (see [Custom Labware](examples/advanced/custom_labware.md#import-a-venus-labware-file)).

#### labware.deleteLabwareDefinition
```json
{
  "channel": "action",
  "data": {
    "category": "System",
    "actionName": "labware.deleteLabwareDefinition",
    "parameters": { "labwareDefinition": "My Custom Plate" }
  }
}
```

#### labware.getLabwareDefinition
```json
{
  "channel": "action",
  "data": {
    "category": "System",
    "actionName": "labware.getLabwareDefinition",
    "parameters": { "labwareDefinition": "96 Well Plate" }
  }
}
```
**Returns:**
```json
{
  "definition": {
    ...
   }
}
```
#### labware.getLabwareDefinitions
```json
{
  "channel": "action",
  "data": {
    "category": "System",
    "actionName": "labware.getLabwareDefinitions",
    "parameters": { "filter": ["plate", "carrier"] }
  }
}
```
> `filter` is optional — omit to return all definitions.
**Returns:**
```json
{
  "labware": {
    "adapter": [
    ...
    ],
    "carrier": [
    ...
    ],
    "lid": [
    ...
    ],
    "plate": [
    ...
    ],
    "reservoir": [
    ...
    ],
    "tip_rack": [
    ...
    ],
    "tube": [
    ...
    ],
    "tube_rack": [
    ...
    ]
  }
}
```
#### labware.getLabwareTypes
```json
{ "channel": "action", "data": { "category": "System", "actionName": "labware.getLabwareTypes", "parameters": {} } }
```
**Returns:**
```json
{
  "labwareTypes": [
    "adapter",
    "carrier",
    "lid",
    "plate",
    "reservoir",
    "tip_rack",
    "tube",
    "tube_rack"
  ]
}
```

#### labware.updateLabwareDefinition
```json
{
  "channel": "action",
  "data": {
    "category": "System",
    "actionName": "labware.updateLabwareDefinition",
    "parameters": {
      "labwareDefinition": "My Custom Plate",
      "definition": {}
    }
  }
}
```
**Returns:**
```json
{
  "message": "\"MyDeck\" was updated"
}
```
### Liquid Class

#### liquidClass.getLiquidClass
```json
{
  "channel": "action",
  "data": {
    "category": "System",
    "actionName": "liquidClass.getLiquidClass",
    "parameters": {
      "name": "StandardVolume_Water_DispenseJet_Empty"
    }
  }
}
```
**Returns:**
```json
{
  "definition": {
    "id": "KitName_SVF_RSB_SurfaceEmpty",
    "isUserDefined": true,
    "version": "2.0",
    "tadmEnabled": true,
    "validated": false,
    "notes": "",
    "appliesTo": {
      "instrument": "ML_STAR",
      "liquid": "Resuspension Buffer",
      "volumeRange": {
        "min": 0,
        "max": 300
      },
      "tipType": "tip_300ul_filter",
      "dispenseMode": "surface_empty",
      "pipettingDevice": "channels_1000ul"
    },
    "pipettingProperties": {
      "aspirate": {
        "flowRate": 60,
        "mixFlowRate": 75,
        "airTransportVolume": 5,
        "blowOutVolume": 10,
        "swapSpeed": 10,
        "settlingTime": 2,
        "overAspirateVolume": 0,
        "clotRetractHeight": 0
      },
      "dispense": {
        "flowRate": 60,
        "mixFlowRate": 75,
        "airTransportVolume": 5,
        "blowOutVolume": 10,
        "swapSpeed": 10,
        "settlingTime": 1,
        "stopFlowRate": 1,
        "stopBackVolume": 0
      },
      "detection": {
        "lld": {
          "pressureSensitivity": 4,
          "lldMaxHeightDifference": 0
        }
      },
      "correction": [
        {
          "targetedVolume": 0,
          "correctedVolume": 0
        },
        {
          "targetedVolume": 17,
          "correctedVolume": 19.2
        },
        {
          "targetedVolume": 23,
          "correctedVolume": 25.8
        },
        {
          "targetedVolume": 40,
          "correctedVolume": 42
        },
        {
          "targetedVolume": 300,
          "correctedVolume": 300
        }
      ],
      "tadmBands": []
    },
    "_internal": {
      "designHistory": "AQAAAAA=",
      "tipTypeId": 1,
      "dispenseMode": 5,
      "liquidDeviceIds": [
        1
      ]
    }
  }
}
```

#### liquidClass.updateLiquidClass
```json
{
  "channel": "action",
  "data": {
    "category": "System",
    "actionName": "liquidClass.updateLiquidClass",
    "parameters": {
      "definition": {
    "id": "KitName_SVF_RSB_SurfaceEmpty",
    "isUserDefined": true,
    "version": "2.0",
    "tadmEnabled": true,
    "validated": false,
    "notes": "",
    "appliesTo": {
      "instrument": "ML_STAR",
      "liquid": "Resuspension Buffer",
      "volumeRange": {
        "min": 0,
        "max": 300
      },
      "tipType": "tip_300ul_filter",
      "dispenseMode": "surface_empty",
      "pipettingDevice": "channels_1000ul"
    },
    "pipettingProperties": {
      "aspirate": {
        "flowRate": 60,
        "mixFlowRate": 75,
        "airTransportVolume": 5,
        "blowOutVolume": 10,
        "swapSpeed": 10,
        "settlingTime": 2,
        "overAspirateVolume": 0,
        "clotRetractHeight": 0
      },
      "dispense": {
        "flowRate": 60,
        "mixFlowRate": 75,
        "airTransportVolume": 5,
        "blowOutVolume": 10,
        "swapSpeed": 10,
        "settlingTime": 1,
        "stopFlowRate": 1,
        "stopBackVolume": 0
      },
      "detection": {
        "lld": {
          "pressureSensitivity": 4,
          "lldMaxHeightDifference": 0
        }
      },
      "correction": [
        {
          "targetedVolume": 0,
          "correctedVolume": 0
        },
        {
          "targetedVolume": 17,
          "correctedVolume": 19.2
        },
        {
          "targetedVolume": 23,
          "correctedVolume": 25.8
        },
        {
          "targetedVolume": 40,
          "correctedVolume": 42
        },
        {
          "targetedVolume": 300,
          "correctedVolume": 300
        }
      ],
      "tadmBands": []
    },
    "_internal": {
      "designHistory": "AQAAAAA=",
      "tipTypeId": 1,
      "dispenseMode": 5,
      "liquidDeviceIds": [
        1
      ]
    }
  }
    }
  }
}
```
**Returns:**
```json
{
  "message": "\"StandardVolume_Water_DispenseJet_Empty\" was updated"
}
```

#### liquidClass.pullLiquidClasses
```json
{
  "channel": "action",
  "data": {
    "category": "System",
    "actionName": "liquidClass.pullLiquidClasses",
    "parameters": { "names": ["Water_DispenseJet_Empty", "Water_DispenseSurface_Empty"] }
  }
}
```
**Returns:**
```json
{
  "recordsExported": 11,
  "exportedClasses": [
   ...
  ]
}
```
#### liquidClass.pushLiquidClasses
```json
{
  "channel": "action",
  "data": {
    "category": "System",
    "actionName": "liquidClass.pushLiquidClasses",
    "parameters": { "names": ["Water_DispenseJet_Empty"] }
  }
}
```
**Returns:**
```json
{
  "filesProcessed": 11,
  "recordsUpdated": 11,
  "importedClasses": [
   ...
  ],
  "skippedOriginals": [],
  "failedImports": []
}
```
#### liquidClass.getLiquidDevices
```json
{ "channel": "action", "data": { "category": "System", "actionName": "liquidClass.getLiquidDevices", "parameters": {} } }
```
**Returns:**
```json
{
  "devices": [
    {
      "deviceName": "1mL Channels",
      "deviceId": 1
    },
    {
      "deviceName": "96 head",
      "deviceId": 3
    },
    {
      "deviceName": "5mL channels",
      "deviceId": 2
    },
    {
      "deviceName": "384 head",
      "deviceId": 4
    },
    {
      "deviceName": "MagPip Channels",
      "deviceId": 10
    }
  ]
}
```
### liquidClass.getLiquidNames
```json
{ "channel": "action", "data": { "category": "System", "actionName": "liquidClass.getLiquidNames", "parameters": {} } }
```
**Returns:**
```json
{
  "liquidNames": [
    ...
  ]
}
```

### liquidClass.getLiquidClasses
```json
{
  "channel": "action",
  "data": {
    "category": "System",
    "actionName": "liquidClass.getLiquidClasses",
    "parameters": {
      "tipType": 0,
      "device": 1,
      "dispenseMode": 3,
      "isOriginal": -1,
      "hasTadmEnabled": -1
    }
  }
}
```
**Parameter enums:**
| Parameter | Values |
|---|---|
| `tipType` | `-1` = Any, or tip type ID from `getTipTypes` |
| `device` | `-1` = Any, `1` = Channel 1mL, `2` = Channel 5mL, `3` = MPH96, `4` = MPH384, `5` = MagPip |
| `dispenseMode` | `-1` = Any, `2` = Jet Part, `3` = Jet Empty, `4` = Surface Part, `5` = Surface Empty, `6` = WhiPip |
| `isOriginal` | `-1` = Any, `0` = User Created, `1` = Predefined |
| `hasTadmEnabled` | `-1` = Any, `0` = Disabled, `1` = Enabled |
**Returns:**
```json
{
  "count": 11,
  "liquidClassNames": [
    ...
  ]
}
```
### liquidClass.getTipTypes
```json
{ "channel": "action", "data": { "category": "System", "actionName": "liquidClass.getTipTypes", "parameters": {} } }
```
**Returns:**
```json
{
  "tipTypes": {
    "0": {
      "Data Version": 2,
      "Max Liquid Volume": 300,
      "Conductivity": true,
      "Max Tip Volume": 400,
      "Visibility Flag": true,
      "Stop Disk Immersion Depth": 8,
      "Filter": false,
      "Overflow Volume": 0,
      "Tip Collar": "300uL/50uL",
      "Tip Length": 59.9,
      "Liquid Device List": [
        "1mL Channels",
        "96 head",
        "96 wash station",
        "1mL X1 Channels"
      ],
      "Tip View Name": "300ul Standard Volume Tip (Ham org. name)",
      "CR Wash Fill Time": 6,
      "Tip Class": "tip"
    }
  }
}
```

# Sample Tracking

### Tracking

#### tracking.getBarcodeLocations
```json
{
  "channel": "action",
  "data": {
    "category": "Sample Tracking",
    "actionName": "tracking.getBarcodeLocations",
    "parameters": {
      "barcodes": [
        "barcode01",
        "barcode02"
      ]
    }
  }
}
```
> `well` is empty when the barcode belongs to the labware itself. Barcodes that are not tracked are listed in `notFound`.

**Returns:**
```json
{
  "barcodes": [
    {
      "barcode": "barcode01",
      "labwareType": "Well",
      "labwareId": "Plate_1",
      "well": "A1"
    }
  ],
  "notFound": [
    "barcode02"
  ],
  "totalBarcodesFound": 1
}
```

#### tracking.getLabwareDetails
```json
{
  "channel": "action",
  "data": {
    "category": "Sample Tracking",
    "actionName": "tracking.getLabwareDetails",
    "parameters": {
      "labware": [
        {
          "labwareId": "Plate_1",
          "wells": [
            {
              "id": "A1"
            },
            {
              "id": "A2"
            },
            {
              "id": "A3"
            }
          ]
        }
      ]
    }
  }
}
```
> `labwareId` is required. `wells` is optional; if no well is specified, all wells loaded in the labware are reported. A labware that cannot be reported (not on the layout, nothing tracked on it yet) is returned with only `labwareId` and a `message`. Sample tracking keeps no volume for reservoirs (connected containers), tip racks or carriers: ignore `volume` for labware of type `Reservoir Rack`, `Tip Rack` and `Template` (the Python SDK returns it as `None`). Reservoirs also track no well state and no well barcode, so ignore `labwareState` and `barcode` on their wells (also `None` in the SDK). The Python SDK sorts `wells` by X ascending, then Y descending, then Z descending.

**Returns:**
```json
{
  "labware": [
    {
      "labwareId": "Plate_1",
      "barcode": "PlateBarcode",
      "type": "Rack",
      "x": 100.0,
      "y": 200.0,
      "z": 150.0,
      "wells": [
        {
          "id": "A1",
          "barcode": "barcode1",
          "volume": 50.0,
          "labwareType": "Well",
          "labwareState": "No Error",
          "x": 100.0,
          "y": 200.0,
          "z": 150.0
        },
        {
          "id": "A2",
          "barcode": "barcode2",
          "volume": 50.0,
          "labwareType": "Well",
          "labwareState": "No Error",
          "x": 100.0,
          "y": 200.0,
          "z": 150.0
        },
        {
          "id": "A3",
          "barcode": "barcode3",
          "volume": 0.0,
          "labwareType": "Well",
          "labwareState": "No Error",
          "x": 100.0,
          "y": 200.0,
          "z": 150.0
        }
      ]
    }
  ]
}
```

#### tracking.setBarcodes
```json
{
  "channel": "action",
  "data": {
    "category": "Sample Tracking",
    "actionName": "tracking.setBarcodes",
    "parameters": {
      "labware": [
        {
          "labwareId": "Plate_1",
          "barcode": "PlateBarcode",
          "wells": [
            {
              "id": "A1",
              "barcode": "barcode1"
            },
            {
              "id": "A2",
              "barcode": "barcode2"
            },
            {
              "id": "A3",
              "barcode": "barcode3"
            }
          ]
        }
      ]
    }
  }
}
```
> `labwareId` is required. `barcode` is optional and assigns the barcode to the labware itself. `wells` is optional and sets barcodes on individual wells.

**Returns:**
```json
{
  "totalLabwareBarcodesSet": 1,
  "totalWellBarcodesSet": 3
}
```

#### tracking.setLabwareVolume
```json
{
  "channel": "action",
  "data": {
    "category": "Sample Tracking",
    "actionName": "tracking.setLabwareVolume",
    "parameters": {
      "labware": [
        {
          "labwareId": "Plate_1",
          "volume": 100.0,
          "wells": [
            {
              "id": "A1",
              "volume": 50.0
            },
            {
              "id": "A2",
              "volume": 75.0
            }
          ]
        }
      ]
    }
  }
}
```
> `labwareId` is required. `volume` is optional and sets every well of the labware (uL). `wells` is optional and sets individual wells, applied after `volume`. No return parameters. Has no effect on reservoirs, tip racks or carriers, which have no tracked volume.

# Teaching

Teaching-needle commands for automated teaching with the 1 mL channel Z-stall sensor.
All coordinates are needle-tip coordinates in mm. `teaching.1mL.moveChannelToPosition`,
`measureZHeight` and `measureXY` need a teaching needle on the teaching channel; they fail
with code 101 otherwise. A failed command returns `message` and `code`.

### Teaching

#### teaching.1mL.setTeachingChannel
```json
{
  "channel": "action",
  "data": {
    "category": "Teaching",
    "actionName": "teaching.1mL.setTeachingChannel",
    "parameters": {
      "channel": 8
    }
  }
}
```
> `channel` is required, 1 to the number of 1 mL channels. Not allowed while a needle is held. The instrument configuration's teaching channel is restored on every `status.connect`.

**Returns:**
```json
{
  "channel": 8
}
```

#### teaching.1mL.getTeachingChannel
```json
{
  "channel": "action",
  "data": {
    "category": "Teaching",
    "actionName": "teaching.1mL.getTeachingChannel",
    "parameters": {}
  }
}
```

**Returns:**
```json
{
  "channel": 8
}
```

#### teaching.1mL.pickupTeachingNeedle
```json
{
  "channel": "action",
  "data": {
    "category": "Teaching",
    "actionName": "teaching.1mL.pickupTeachingNeedle",
    "parameters": {}
  }
}
```
> Picks up a needle from a teaching-needle rack on the deck (`MlStarTipRack` = 10) with the teaching channel and measures the needle length.

**Returns:**
```json
{
  "channel": 8
}
```

#### teaching.1mL.ejectTeachingNeedle
```json
{
  "channel": "action",
  "data": {
    "category": "Teaching",
    "actionName": "teaching.1mL.ejectTeachingNeedle",
    "parameters": {}
  }
}
```

**Returns:**
```json
{
  "message": "Teaching needle ejected"
}
```

#### teaching.1mL.isNeedlePickedUp
```json
{
  "channel": "action",
  "data": {
    "category": "Teaching",
    "actionName": "teaching.1mL.isNeedlePickedUp",
    "parameters": {}
  }
}
```

**Returns:**
```json
{
  "isNeedlePickedUp": true
}
```

#### teaching.1mL.getLabwareDimensions
```json
{
  "channel": "action",
  "data": {
    "category": "Teaching",
    "actionName": "teaching.1mL.getLabwareDimensions",
    "parameters": {
      "labwareName": "Plate_1",
      "well": "A1"
    }
  }
}
```
> `well` is optional; without it the labware's first position is reported. `labware.center` is the center of the labware footprint, `labware.bottomZ` the skirt bottom and `labware.height` the labware height. `well.bottomZ` is the well bottom and `well.depth` the depth from the well bottom up to its entrance.

**Returns:**
```json
{
  "labware": {
    "labwareId": "plate_1",
    "center": { "x": 245.3, "y": 146.05 },
    "bottomZ": 102.5,
    "height": 14.35
  },
  "well": {
    "positionId": "A1",
    "center": { "x": 196.3, "y": 177.55 },
    "bottomZ": 103.6,
    "depth": 10.9
  }
}
```

#### teaching.1mL.moveChannelToPosition
```json
{
  "channel": "action",
  "data": {
    "category": "Teaching",
    "actionName": "teaching.1mL.moveChannelToPosition",
    "parameters": {
      "x": 196.3,
      "y": 177.55,
      "z": 114.5,
      "zTraverse": 245.0
    }
  }
}
```
> All parameters are optional; an omitted axis keeps its current value and `zTraverse` defaults to the current Z. `x` and `y` must be within the teaching channel's range; `z` and `zTraverse` are 105-245.

**Returns:**
```json
{
  "x": 196.3,
  "y": 177.5,
  "z": 114.5
}
```

#### teaching.1mL.measureZHeight
```json
{
  "channel": "action",
  "data": {
    "category": "Teaching",
    "actionName": "teaching.1mL.measureZHeight",
    "parameters": {
      "zStart": 114.5,
      "zMin": 98.6,
      "zEnd": -1,
      "useSlowSpeed": false
    }
  }
}
```
> Searches down from `zStart` to `zMin` (both 100-334) until the needle stalls. `zEnd` -1 returns the needle to its start height after a find. `status.code`: 0 `WALL_NOT_FOUND` (no stall before `zMin`), 1 `WALL_FOUND`, 2 `FOUND_EARLY` (stalled before `zStart`).

**Returns:**
```json
{
  "measuredZ": 103.8,
  "status": {
    "code": 1,
    "name": "WALL_FOUND"
  }
}
```

#### teaching.1mL.measureXY
```json
{
  "channel": "action",
  "data": {
    "category": "Teaching",
    "actionName": "teaching.1mL.measureXY",
    "parameters": {
      "safeHeight": 119.5,
      "minSearchZ": 111.5,
      "wellWidth": 6.9,
      "direction": 1,
      "stepDistance": 0.6
    }
  }
}
```
> Start with the needle inside the well at its entrance height. The channel steps toward one wall (`direction` 1 = +X, 2 = -X, 3 = +Y, 4 = -Y) and at each step searches Z from `safeHeight` (above the labware) down to `minSearchZ` (2-3 mm inside the well). A stall above `minSearchZ` is the wall top; the channel then steps back until the needle drops into the well again. `wallCoordinate` is that last in-well X or Y and `entranceZ` the wall-top stall height. `wellWidth` (2-100) is the farthest the search travels; `stepDistance` is 0.3-2.4 (default 0.6). `status.code`: 0 `WALL_NOT_FOUND`, 1 `WALL_FOUND`, 2 `FOUND_EARLY`.

**Returns:**
```json
{
  "wall": "+X",
  "status": {
    "code": 1,
    "name": "WALL_FOUND"
  },
  "measured": {
    "axis": "x",
    "wallCoordinate": 199.4,
    "entranceZ": 114.6
  }
}
```
