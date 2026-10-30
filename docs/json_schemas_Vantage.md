# Hamilton VENUS SDK — Command Catalog

> **Who needs this page?** This is the raw VENUS WebAPI wire format for Vantage commands. Most users should call the typed `VantageClient` methods instead (see [Vantage Commands](vantage_commands.md)). Use this page when calling `vantage.send_command(category=..., action_name=..., parameters=...)` for commands without an SDK method, or when debugging the JSON the SDK sends. `send_command` builds the `channel`/`data` envelope for you; some examples below show only the inner `data` object.

> API base: `http://localhost:42400/api/vector/v3/run-messages` (default `base_url`; see [Configuration](configuration.md))  
> All commands are sent as `POST { "channel": "action", "data": { "category", "actionName", "parameters" } }`

---

# Instrument

### Status

#### status.isIdle
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "status.isIdle", "parameters": {} } }
```
**Returns:**
```json
{
  "isIdle": true
}
```
#### status.isConnected
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "status.isConnected", "parameters": {} } }
```
**Returns:**
```json
{
  "isConnected": true
}
```
#### status.init
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "status.init",
    "parameters": {
      "forceInit": true
    }
  }
}
```
**Returns:**
```json
{
  "instrumentName": "ML_STAR",
  "autoloadCurrentTrack": 74
}
```
#### status.connect
```json
{
  "category": "Instrument",
  "actionName": "status.connect",
  "parameters": {
    "initialize": true
  }
}
```
**Returns:**
```json
{
  "instrumentName": "ML_STAR",
  "autoloadCurrentTrack": 54,
  "message": "Instrument "
}
```
#### status.terminate
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "status.terminate", "parameters": {} } }
```
**Returns:**
```json
{}
```
#### status.getInstrumentType
```json
{
  "category": "Instrument",
  "actionName": "status.getInstrumentType",
  "parameters": {}
}
```
**Returns:**
```json
{
  "instrumentType": "VANTAGE"
}
```
---
### Configuration
#### configuration.getConfiguration
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "configuration.getConfiguration", "parameters": {} } }
```
**Returns:**
```json
{
  "LeftArm": {
    "armId": 1,
    "gripper": {
      "type": "IPG"
    },
    "MPH96": {
      "total": 96,
      "raster": 9.0,
      "type": "MPH96",
      "capacity": 300.0,
      "xMin": 100.0,
      "xMax": 1225.0,
      "yMin": 17.0,
      "yMax": 605.5
    },
    "channels1mL": {
      "total": 8,
      "raster": 9,
      "type": "Legacy",
      "capacity": 1000,
      "maxY": [
        605.5,
        596.5,
        587.5,
        578.5,
        569.5,
        560.5,
        551.5,
        542.5
      ],
      "minY": [
        71,
        62,
        53,
        44,
        35,
        26,
        17,
        8
      ]
    },
    "xMin": 225.2,
    "xMax": 929.8
  },
  "RightArm": {
    "armId": 2,
    "channelsMagPip": {
      "total": 8,
      "raster": 9,
      "type": "Legacy",
      "capacity": 750,
      "maxY": [
        605.5,
        596.5,
        587.5,
        578.5,
        569.5,
        560.5,
        551.5,
        542.5
      ],
      "minY": [
        71,
        62,
        53,
        44,
        35,
        26,
        17,
        8
      ]
    },
    "xMin": 453.4,
    "xMax": 1158
  },
  "type": "Vantage 1.3",
  "wasteType": "2T Waste",
  "Autoload": true,
  "tracks": 54,
  "MaxAutoloadTrack": 44
}
```
> `MPH96` is `null` when no MPH96 head is installed on that arm.

#### configuration.disableCleanup
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "configuration.disableCleanup", "parameters": {} } }
```
**Returns:**
```json
{}
```
#### configuration.getSerialNumber
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "configuration.getSerialNumber", "parameters": {} } }
```
**Returns:**
```json
{
  "serialNumber": "0000"
}
```

#### configuration.getDeckTracks
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "configuration.getDeckTracks", "parameters": {} } }
```
**Returns:**
```json
{
  "totalTracks": 54,
  "autoloadableTracks": 44,
  "activeTracks": [
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
    13,
    14,
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    23,
    24,
    25,
    26,
    27,
    28,
    29,
    30,
    31,
    32,
    33,
    34,
    37,
    38,
    39,
    40,
    41,
    42,
    43,
    44,
    45,
    46,
    47,
    48,
    49,
    50,
    51,
    52,
    53,
    54,
    55
  ]
}
```
#### configuration.getDeckDimensions
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "configuration.getDeckDimensions", "parameters": {} } }
```
**Returns:**
```json
{
  "x": 1608,
  "y": 672
}
```
#### configuration.getWasteLocations
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "configuration.getWasteLocations", "parameters": {} } }
```
**Returns:**
```json
{
  "wasteLocations": [
    {
      "1": {
        "x": -46.3,
        "y": 116.9,
        "z": 218,
        "carrier": "Core384SlideWaste_0001",
        "labwareName": "core384slidewaste_0001",
        "isDefault": true,
        "isMPH384Waste": true
      }
    },
    {
      "2": {
        "x": -42,
        "y": 120.3,
        "z": 205,
        "carrier": "Core96SlideWaste_0001",
        "labwareName": "core96slidewaste_0001",
        "isDefault": true,
        "isMPH96Waste": true
      }
    },
    {
      "3": {
        "x": 1340,
        "y": 405,
        "z": 187,
        "carrier": "WasteBlock",
        "labwareName": "Waste",
        "isDefault": true
      }
    }
  ]
}
```
---
### Maintenance Status

#### maintenance.getDailyMaintenanceData
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "maintenance.getDailyMaintenanceData", "parameters": {} } }
```
**Returns:**
```json
{
  "status": "Not Required",
  "expirationDate": "2002-04-24T12:25:00Z",
  "processedDate": "2002-04-23T12:25:00Z",
  "processedStatus": "Success",
  "processedCode": 1,
  "isMandatory": false
}
```
#### maintenance.getWeeklyMaintenanceData
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "maintenance.getWeeklyMaintenanceData", "parameters": {} } }
```
**Returns:**
```json
{
  "status": "Not Required",
  "expirationDate": "2002-04-24T12:25:00Z",
  "processedDate": "2002-04-23T12:25:00Z",
  "processedStatus": "Success",
  "processedCode": 1,
  "isMandatory": false
}
```
#### maintenance.getVerificationData
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "maintenance.getVerificationData", "parameters": {} } }
```
**Returns:**
```json
{
  "status": "Not Required",
  "expirationDate": "2002-04-24T12:25:00Z",
  "processedDate": "2002-04-23T12:25:00Z",
  "processedStatus": "Success",
  "processedCode": 1,
  "isMandatory": false
}
```
---
### Firmware

#### firmware.debugMode
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "firmware.debugMode",
    "parameters": {
      "enable": true
    }
  }
}
```
**Returns:**
```json
{
  "message": "Enable firmware debug..."
}
```
#### firmware.command
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "firmware.command",
    "parameters": {
      "command": "C0AS",
      "parameters": "tm1 1 1 1 1 1 1 1",
      "safetyBypassToken": "OVERRIDE_SAFETY_CHECKS"
    }
  }
}
```
> `safetyBypassToken` (optional): `"OVERRIDE_SAFETY_CHECKS"`
**Returns:**
```json
{
  "return": ""
}
```
---
### Front Cover

#### frontCover.isClosed
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "frontCover.isClosed", "parameters": {} } }
```
**Returns:**
```json
{
  "isClosed": true
}
```
#### frontCover.isLocked
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "frontCover.isLocked", "parameters": {} } }
```

#### frontCover.lock
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "frontCover.lock", "parameters": {} } }
```
**Returns:**
```json
{}
```
#### frontCover.unlock
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "frontCover.unlock", "parameters": {} } }
```
**Returns:**
```json
{}
```
---

### Autoload

#### autoload.moveTo
```json
{
  "channel": "action",
  "data": { "category": "Instrument", "actionName": "autoload.moveTo", "parameters": { "trackId": 5 } }
}
```
**Returns:**
```json
{}
```
#### autoload.parkLeft / autoload.parkRight
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "autoload.parkLeft", "parameters": {} } }
```
**Returns:**
```json
{}
```
#### autoload.loadCarrierById
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "autoload.loadCarrierById",
    "parameters": {
      "carrierId": "MyCarrier_1",
      "scanPositions": "?"
    }
  }
}
```
> `scanPositions`: `"1,2,3"` = specific positions, `"?"` = scan all, `""` = no scan
**Returns:**
```json
{
  "track": 6,
  "carrierBarcode": "CarrierBC",
  "carrierLabwareID": "mycarrier_1",
  "barcodeReturns": [
    {
      "barcode": "",
      "position": "",
      "barcodeMask": ""
    },
    {
      "barcode": "",
      "position": "",
      "barcodeMask": ""
    },
    {
      "barcode": "",
      "position": "",
      "barcodeMask": ""
    },
    {
      "barcode": "",
      "position": "",
      "barcodeMask": ""
    },
    {
      "barcode": "",
      "position": "",
      "barcodeMask": ""
    }
  ]
}
```
#### autoload.loadCarrierByTrack
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "autoload.loadCarrierByTrack",
    "parameters": { "trackId": 5, "scanPositions": "?" }
  }
}
```
**Returns:**
```json
{
  "track": 6,
  "carrierBarcode": "CarrierBC",
  "carrierLabwareID": "deep well carrier",
  "barcodeReturns": [
    {
      "barcode": "",
      "position": "",
      "barcodeMask": ""
    },
    {
      "barcode": "",
      "position": "",
      "barcodeMask": ""
    },
    {
      "barcode": "",
      "position": "",
      "barcodeMask": ""
    },
    {
      "barcode": "",
      "position": "",
      "barcodeMask": ""
    },
    {
      "barcode": "",
      "position": "",
      "barcodeMask": ""
    }
  ]
}
```
#### autoload.unloadCarrierById
```json
{
  "channel": "action",
  "data": { "category": "Instrument", "actionName": "autoload.unloadCarrierById", "parameters": { "carrierId": "MyCarrier_1" } }
}
```
**Returns:**
```json
{}
```
#### autoload.unloadCarrierByTrack
```json
{
  "channel": "action",
  "data": { "category": "Instrument", "actionName": "autoload.unloadCarrierByTrack", "parameters": { "trackId": 5 } }
}
```
**Returns:**
```json
{}
```
#### autoload.getCarrierSensorStatus
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "autoload.getCarrierSensorStatus", "parameters": {} } }
```
**Returns:**
```json
{
  "carrierSensorStatus": [
    {
      "carrier": "ntr carrier",
      "sensorTrack": 6,
      "sensorAvailable": true,
      "status": false
    },
    {
      "carrier": "dwc",
      "sensorTrack": 13,
      "sensorAvailable": true,
      "status": false
    },
    {
      "carrier": "tip carrier",
      "sensorTrack": 25,
      "sensorAvailable": true,
      "status": false
    }
  ]
}
```
---

### Load Tray

#### loadTray.lowerTray
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "loadTray.lowerTray", "parameters": {} } }
```
**Returns:**
```json
{
  "message": "Tray lowered successfully."
}
```

#### loadTray.raiseTray
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "loadTray.raiseTray", "parameters": {} } }
```
**Returns:**
```json
{
  "message": "Tray raised successfully."
}
```
---

### Status Light

#### statusLight.setFrontLight
```json
{
  "category": "Instrument",
  "actionName": "statusLight.setFrontLight",
  "parameters": {
    "color": 2,
    "blink" : true,
    "progress": 5
  }
}
```
> `color`: 0=White, 1=Red, 2=Green, 3=Blue
> `progress`: 0=Off, 1=20%, 2=40%, 3=60%, 4=80%, 5=100%
**Returns:**
```json
{}
```
#### statusLight.setInteriorLight
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "statusLight.setInteriorLight",
    "parameters": {
      "lightState": 1,
      "lightIntensity": 100,
      "blinkInterval": 750,
      "colors": {
        "white": 0,
        "red": 0,
        "green": 57,
        "blue": 94
      }
    }
  }
}
```
> `lightState`: 0=Off, 1=On, 2=Blink, 3=Rainbow Dash  
> `lightIntensity`: 0–100 (optional; only used when `lightState` is `1` or `2`)  
> `blinkInterval`: 1–10000 ms (optional; only used when `lightState` is `2` or `3`)  
> `colors`: object with `white`, `red`, `green`, `blue` each 0–100 (optional; only used when `lightState` is `1` or `2`)
**Returns:**
```json
{}
```
---
### Pipetting Arm

#### pipArm.getXPosition
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "pipArm.getXPosition",
    "parameters": { "armId": 1 }
  }
}
```
> `armId`: 1 = Left, 2 = Right
**Returns:**
```json
{
  "x": 1034.3
}
```
#### pipArm.parkLeft
```json
{
  "channel": "action",
  "data": { "category": "Instrument", "actionName": "pipArm.parkLeft", "parameters": { "armId": 1 } }
}
```
**Returns:**
```json
{}
```
#### pipArm.parkRight
```json
{
  "channel": "action",
  "data": { "category": "Instrument", "actionName": "pipArm.parkRight", "parameters": { "armId": 1 } }
}
```
**Returns:**
```json
{}
```
#### pipArm.moveTo
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "pipArm.moveTo",
    "parameters": {
      "value": 100.0,
      "mode": 0,
      "armId": 1,
      "speed": "Standard"
    }
  }
}
```
> `mode`: 0=absolute, 1=relative | `speed`: `"Standard"`, `"Fast"`, `"Slow"`  
> `safetyBypassToken` (optional): `"OVERRIDE_SAFETY_CHECKS"`
**Returns:**
```json
{}
```
### 1mL Channels

#### channels.1mL.tipPickup
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.1mL.tipPickup",
    "parameters": {
      "channels": [1, 2, 3, 4, 5, 6, 7, 8],
      "tipPool": "300 uL Tips"
    }
  }
}
```
> Use `tipPool` **or** `positions` (array of `{"labwareId","wellId"}`), not both.  
> `optimizedPickup` (bool, optional) — only valid with `tipPool`.

**Returns:**
```json
{
  "remainingTips": 80
}
```
**Error:**
```json
{
  "message": "Tips \"300ul tips\" failed to return a sequence: NoMoreTipsAvailable: A sequence is requested, but not enough or no tips are left in the tip counter sequence.",
  "code": 2001
}
```


#### channels.1mL.tipEject
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.1mL.tipEject",
    "parameters": { "ejectMode": "waste" }
  }
}
```
> `ejectMode` values:
> - `"waste"` — eject to waste (no extra params)
> - `"return"` — return to pickup position (no extra params)
> - `"tipPool"` — add `"channels"` (array) and `"tipPool"` (string)
> - `"positions"` — add `"channels"` (array) and `"positions"` (array of `{"labwareId","wellId"}`)

**Returns:**
```json
{}
```

#### channels.1mL.tipCheck
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "channels.1mL.tipCheck", "parameters": {} } }
```
**Returns:**
```json
{
  "activeChannels": [
    {
      "channel": 1,
      "tipType": 0,
      "tipName": "300ul Standard Volume Tip"
    }
  ]
}
```

#### channels.1mL.aspirate
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.1mL.aspirate",
    "parameters": {
      "channels": [1, 2, 3, 4, 5, 6, 7, 8],
      "positions": [
        { "labwareId": "Plate_1", "wellId": "A1" },
        { "labwareId": "Plate_1", "wellId": "B1" }
      ],
      "armId": 1,
      "volumes": 100.0,
      "liquidClass": "Water_DispenseJet_Empty",
      "aspirateMode": 0,
      "capacitiveLLD": 0,
      "pressureLLD": 0,
      "liquidFollowing": false,
      "tipTrackingFactor": 1.0,
      "submergeDepth": 2.0,
      "fixedHeight": 5.0,
      "maxLLdDifference": 3.0,
      "mixCycles": 0,
      "mixPosition": 0.0,
      "mixVolume": 0.0,
      "airTransportRetractDist": 5.0,
      "touchOff": 0,
      "touchOffHeight": 1.0,
      "madEnabled": false,
      "madThreshold": 30,
      "ADC": false
    }
  }
}
```
> `capacitiveLLD`: 0=OFF, 1=MAX, 2=HIGH, 3=MID, 4=LOW, 5=FROM LABWARE  
> `volumes`: single value `100` or array values `[100,50,100,50,100,50,100,50]`
> `liquidClass`, `aspirateMode`, `capacitiveLLD`, `pressureLLD`, `liquidFollowing`, `submergeDepth`, `fixedHeight`, `maxLLdDifference`, `mixCycles`, `mixPosition`, `mixVolume`, `airTransportRetractDist`, `touchOff`, and `touchOffHeight` all can accept single values or array values  
> `madEnabled` (optional, default `false`): enable Mid-Air Detection  
> `madThreshold` (optional, default `30`): MAD threshold, Range: 1–1023  
> `tipTrackingFactor` (optional, default `1.0`, single value only, Range: 0.1–5.0): liquid-following movement factor; `0.5` tracks half the distance, `2.0` twice  
> `ADC` (optional, default `false`): Anti-Droplet Control
**Returns:**
```json
{
  "channels": [
    {
      "channel": 1,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    },
    {
      "channel": 2,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    },
    {
      "channel": 3,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    },
    {
      "channel": 4,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    },
    {
      "channel": 5,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    },
    {
      "channel": 6,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    },
    {
      "channel": 7,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    },
    {
      "channel": 8,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    }
  ],
  "TADM":{
    "tadmCurves": [
      {
      "curveId": 2587,
      "liquidClassName": "SVF_DispenseJet_Empty",
      "stepType": 0,
      "stepTypeName": "Aspirating",
      "volume": 50.0,
      "timeStamp": "2026-05-20 17:30:50",
      "stepGuid": "d6d9133e_366d_4364_b65be48b094329cc",
      "toleranceBandGuid": "00000000-0000-0000-0000-000000000000",
      "stepNumber": 7166,
      "curvePoints": [
        {
          "timeMs": -340,
          "pressure": -29
        },
        ...
      ],
      "error": 0,
      "channelNumber": 3,
      "tadmMode": 1,
      "curveFlagged": 0,
      "checkSum": -1110657860
    },
    ...
    ]
  }
}
```
#### channels.1mL.dispense
```json
  {
    "category": "Instrument",
    "actionName": "channels.1mL.dispense",
    "parameters": {
      "channels": [1,2,3,4,5,6,7,8],
      "positions": [
        {"labwareId": "midi plate 2","wellId": "A1"},
        {"labwareId": "midi plate 2","wellId": "B1"},
        {"labwareId": "midi plate 2","wellId": "C1"},
        {"labwareId": "midi plate 2","wellId": "D1"},
        {"labwareId": "midi plate 2","wellId": "E1"},
        {"labwareId": "midi plate 2","wellId": "F1"},
        {"labwareId": "midi plate 2","wellId": "G1"},
        {"labwareId": "midi plate 2","wellId": "H1"}
      ],
      "volumes": 100,
      "dispenseMode": 8,
      "capacitiveLLD": 0,
      "liquidFollowing": true,
      "tipTrackingFactor": 1.0,
      "submergeDepth": 0,
      "fixedHeight": 5,
      "mixCycles": 0,
      "mixPosition": 0,
      "mixVolume": 0,
      "airTransportRetractDist": 5,
      "touchOff": 0,
      "touchOffHeight": 0,
      "useSideTouch": false,
      "ADC": false
    }
  }
```
> `dispenseMode`, `capacitiveLLD`, `liquidFollowing`, `submergeDepth`, `fixedHeight`, `mixCycles`, `mixPosition`, `mixVolume`, `airTransportRetractDist`, `touchOff`, and `touchOffHeight` all can accept single values or array values  
> `tipTrackingFactor` (optional, default `1.0`, single value only, Range: 0.1–5.0): liquid-following movement factor; `0.5` tracks half the distance, `2.0` twice  
> `ADC` (optional, default `false`): Anti-Droplet Control

**Returns:**
```json
{
  "channels": [
    {
      "channel": 1,
      "dispensedVolume": 100
    },
    {
      "channel": 2,
      "dispensedVolume": 100
    },
    {
      "channel": 3,
      "dispensedVolume": 100
    },
    {
      "channel": 4,
      "dispensedVolume": 100
    },
    {
      "channel": 5,
      "dispensedVolume": 100
    },
    {
      "channel": 6,
      "dispensedVolume": 100
    },
    {
      "channel": 7,
      "dispensedVolume": 100
    },
    {
      "channel": 8,
      "dispensedVolume": 100
    }
  ],
  "TADM":{
    "tadmCurves": [
      {
      "curveId": 2587,
      "liquidClassName": "SVF_DispenseJet_Empty",
      "stepType": 0,
      "stepTypeName": "Aspirating",
      "volume": 50.0,
      "timeStamp": "2026-05-20 17:30:50",
      "stepGuid": "d6d9133e_366d_4364_b65be48b094329cc",
      "toleranceBandGuid": "00000000-0000-0000-0000-000000000000",
      "stepNumber": 7166,
      "curvePoints": [
        {
          "timeMs": -340,
          "pressure": -29
        },
        ...
      ],
      "error": 0,
      "channelNumber": 3,
      "tadmMode": 1,
      "curveFlagged": 0,
      "checkSum": -1110657860
    },
    ...
    ]
  }
}
```
#### channels.1mL.dispenseOnTheFly
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.1mL.dispenseOnTheFly",
    "parameters": {
      "channels": [1, 2, 3, 4],
      "labwareName": "plate 1",
      "volumes": 100.0,
      "labwareSurfaceDistance": 3.0,
      "startXOffset": 0.0,
      "xSpeed": 0.0,
      "xAccelerationDistance": 8.0,
      "dispenseDirection": 0,
      "excludedPositions": ["A1","B1","C1","D1","E1","F1","G1","H1"]
    }
  }
}
```
> `channels`: must be one of `[1]`, `[1,2]`, `[1,2,3,4]`, or `[1,2,3,4,5,6,7,8]`  
> `volumes`: single value applied to all channels, or an array matching the number of channels  
> `labwareSurfaceDistance`: dispense height above labware surface (mm)  
> `startXOffset`: X offset from the first well (mm)  
> `xSpeed`: arm travel speed in mm/s — set to `0` to auto-calculate speed and acceleration  
> `xAccelerationDistance`: distance (mm) used to ramp up to `xSpeed`; ignored when `xSpeed` is `0`  
> `dispenseDirection`: `0` = Serpentine (alternating columns), `1` = From left only  
> `excludedPositions` (optional): array of well IDs to skip (e.g. `["A1","B1"]`); can be omitted or left empty `[]`

**Returns:**
```json
{}
```

#### channels.1mL.moveAxis
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.1mL.moveAxis",
    "parameters": {
      "channels": [1, 2, 3, 4],
      "x": 200.0,
      "y": [500, 491, 482, 473],
      "z": 245,
      "safetyBypassToken": ""
    }
  }
}
```
> `channels`: array or single integer value for one channel  
> `x`: single value only (Optional)  
> `y`: array or single value for one channel (Optional)  
> `z`: array or single value — one value applies to all channels (Optional)  
> `safetyBypassToken` (optional): `"OVERRIDE_SAFETY_CHECKS"`

**Returns:**
```json
{
  "channelStatus": [
    {"channel": 1, "x": 0, "y": 0, "z": 0 },
    {"channel": 2, "x": 0, "y": 0, "z": 0 },
    {"channel": 3, "x": 0, "y": 0, "z": 0 },
    {"channel": 4, "x": 0, "y": 0, "z": 0 },
    {"channel": 5, "x": 0, "y": 0, "z": 0 },
    {"channel": 6, "x": 0, "y": 0, "z": 0 },
    {"channel": 7, "x": 0, "y": 0, "z": 0 },
    {"channel": 8, "x": 0, "y": 0, "z": 0 }
  ]
}
```

#### channels.1mL.getStatus
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.1mL.getStatus",
    "parameters": {}
  }
}
```

**Returns:**
```json
{
  "channelStatus": [
    { "channel": 1, "x": 0, "y": 0, "z": 0, "tipLoaded": 0 },
    { "channel": 2, "x": 0, "y": 0, "z": 0, "tipLoaded": 0 },
    { "channel": 3, "x": 0, "y": 0, "z": 0, "tipLoaded": 0 },
    { "channel": 4, "x": 0, "y": 0, "z": 0, "tipLoaded": 0 },
    { "channel": 5, "x": 0, "y": 0, "z": 0, "tipLoaded": 0 },
    { "channel": 6, "x": 0, "y": 0, "z": 0, "tipLoaded": 0 },
    { "channel": 7, "x": 0, "y": 0, "z": 0, "tipLoaded": 0 },
    { "channel": 8, "x": 0, "y": 0, "z": 0, "tipLoaded": 0 }
  ]
}
```

#### channels.1mL.detectLiquidLevel
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.1mL.detectLiquidLevel",
    "parameters": {
      "channels": [1, 2, 3, 4, 5, 6, 7, 8],
      "positions": [{ "labwareId": "Plate_1", "wellId": "A1" }],
      "capacitiveLLD": 1,
      "pressureLLD": 0
    }
  }
}
```

**Returns:**
```json
{
  "channels": [
    {
      "channel": 1,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    },
    {
      "channel": 2,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    },
    {
      "channel": 3,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    },
    {
      "channel": 4,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    },
    {
      "channel": 5,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    },
    {
      "channel": 6,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    },
    {
      "channel": 7,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    },
    {
      "channel": 8,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    }
  ]
}
```
---
### 5mL Channels

#### channels.5mL.tipPickup
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.5mL.tipPickup",
    "parameters": {
      "channels": [1, 2, 3, 4, 5, 6, 7, 8],
      "tipPool": "5mL Tips"
    }
  }
}
```
> Use `tipPool` **or** `positions` (array of `{"labwareId","wellId"}`), not both.  
> `optimizedPickup` (bool, optional) — only valid with `tipPool`.

**Returns:**
```json
{
  "remainingTips": 80
}
```
**Error:**
```json
{
  "message": "Tips \"5mL tips\" failed to return a sequence: NoMoreTipsAvailable: A sequence is requested, but not enough or no tips are left in the tip counter sequence.",
  "code": 2001
}
```


#### channels.5mL.tipEject
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.5mL.tipEject",
    "parameters": { "ejectMode": "waste" }
  }
}
```
> `ejectMode` values:
> - `"waste"` — eject to waste (no extra params)
> - `"return"` — return to pickup position (no extra params)
> - `"tipPool"` — add `"channels"` (array) and `"tipPool"` (string)
> - `"positions"` — add `"channels"` (array) and `"positions"` (array of `{"labwareId","wellId"}`)

**Returns:**
```json
{}
```

#### channels.5mL.tipCheck
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "channels.5mL.tipCheck", "parameters": {} } }
```
**Returns:**
```json
{
  "activeChannels": [
    {
      "channel": 1,
      "tipType": 0,
      "tipName": "5mL Volume Tip"
    }
  ]
}
```
#### channels.5mL.aspirate
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.5mL.aspirate",
    "parameters": {
      "channels": [1, 2, 3, 4, 5, 6, 7, 8],
      "positions": [
        { "labwareId": "Plate_1", "wellId": "A1" },
        { "labwareId": "Plate_1", "wellId": "B1" }
      ],
      "armId": 1,
      "volumes": 100.0,
      "liquidClass": "Water_DispenseJet_Empty",
      "aspirateMode": 0,
      "capacitiveLLD": 0,
      "pressureLLD": 0,
      "liquidFollowing": false,
      "tipTrackingFactor": 1.0,
      "submergeDepth": 2.0,
      "fixedHeight": 5.0,
      "maxLLdDifference": 3.0,
      "mixCycles": 0,
      "mixPosition": 0.0,
      "mixVolume": 0.0,
      "airTransportRetractDist": 5.0,
      "touchOff": 0,
      "touchOffHeight": 1.0,
      "madEnabled": false,
      "madThreshold": 30,
      "ADC": false
    }
  }
}
```
> `capacitiveLLD`: 0=OFF, 1=MAX, 2=HIGH, 3=MID, 4=LOW, 5=FROM LABWARE  
> `volumes`: single value `100` or array values `[100,50,100,50,100,50,100,50]`
> `liquidClass`, `aspirateMode`, `capacitiveLLD`, `pressureLLD`, `liquidFollowing`, `submergeDepth`, `fixedHeight`, `maxLLdDifference`, `mixCycles`, `mixPosition`, `mixVolume`, `airTransportRetractDist`, `touchOff`, and `touchOffHeight` all can accept single values or array values  
> `madEnabled` (optional, default `false`): enable Mid-Air Detection  
> `madThreshold` (optional, default `30`): MAD threshold, Range: 1–1023  
> `tipTrackingFactor` (optional, default `1.0`, single value only, Range: 0.1–5.0): liquid-following movement factor; `0.5` tracks half the distance, `2.0` twice  
> `ADC` (optional, default `false`): Anti-Droplet Control
**Returns:**
```json
{
  "channels": [
    {
      "channel": 1,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    },
    {
      "channel": 2,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    },
    {
      "channel": 3,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    },
    {
      "channel": 4,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    },
    {
      "channel": 5,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    },
    {
      "channel": 6,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    },
    {
      "channel": 7,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    },
    {
      "channel": 8,
      "aspiratedVolume": 100,
      "liquidLevel_mm":0.0,
      "liquidVolume_uL":0.0
    }
  ],
  "TADM":{
    "tadmCurves": [
      {
      "curveId": 2587,
      "liquidClassName": "IDT_SVF_1stSupernatant_DispenseJet_Empty",
      "stepType": 0,
      "stepTypeName": "Aspirating",
      "volume": 50.0,
      "timeStamp": "2026-05-20 17:30:50",
      "stepGuid": "d6d9133e_366d_4364_b65be48b094329cc",
      "toleranceBandGuid": "00000000-0000-0000-0000-000000000000",
      "stepNumber": 7166,
      "curvePoints": [
        {
          "timeMs": -340,
          "pressure": -29
        },
        ...
      ],
      "error": 0,
      "channelNumber": 3,
      "tadmMode": 1,
      "curveFlagged": 0,
      "checkSum": -1110657860
    },
    ...
    ]
  }
}
```
#### channels.5mL.detectLiquidLevel
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.5mL.detectLiquidLevel",
    "parameters": {
      "channels": [1, 2, 3, 4, 5, 6, 7, 8],
      "positions": [{ "labwareId": "Plate_1", "wellId": "A1" }],
      "capacitiveLLD": 1,
      "pressureLLD": 0
    }
  }
}
```

**Returns:**
```json
{
  "channels": [
    {
      "channel": 1,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    },
    {
      "channel": 2,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    },
    {
      "channel": 3,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    },
    {
      "channel": 4,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    },
    {
      "channel": 5,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    },
    {
      "channel": 6,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    },
    {
      "channel": 7,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    },
    {
      "channel": 8,
      "liquidLevel_mm": 0,
      "liquidVolume_uL": 0
    }
  ]
}
```
#### channels.5mL.dispense
```json
  {
    "category": "Instrument",
    "actionName": "channels.5mL.dispense",
    "parameters": {
      "channels": [1,2,3,4,5,6,7,8],
      "positions": [
        {"labwareId": "midi plate 2","wellId": "A1"},
        {"labwareId": "midi plate 2","wellId": "B1"},
        {"labwareId": "midi plate 2","wellId": "C1"},
        {"labwareId": "midi plate 2","wellId": "D1"},
        {"labwareId": "midi plate 2","wellId": "E1"},
        {"labwareId": "midi plate 2","wellId": "F1"},
        {"labwareId": "midi plate 2","wellId": "G1"},
        {"labwareId": "midi plate 2","wellId": "H1"}
      ],
      "volumes": 100,
      "dispenseMode": 8,
      "capacitiveLLD": 0,
      "liquidFollowing": true,
      "tipTrackingFactor": 1.0,
      "submergeDepth": 0,
      "fixedHeight": 5,
      "mixCycles": 0,
      "mixPosition": 0,
      "mixVolume": 0,
      "airTransportRetractDist": 5,
      "touchOff": 0,
      "touchOffHeight": 0,
      "useSideTouch": false,
      "ADC": false
    }
  }
```
> `dispenseMode`, `capacitiveLLD`, `liquidFollowing`, `submergeDepth`, `fixedHeight`, `mixCycles`, `mixPosition`, `mixVolume`, `airTransportRetractDist`, `touchOff`, and `touchOffHeight` all can accept single values or array values  
> `tipTrackingFactor` (optional, default `1.0`, single value only, Range: 0.1–5.0): liquid-following movement factor; `0.5` tracks half the distance, `2.0` twice  
> `ADC` (optional, default `false`): Anti-Droplet Control

**Returns:**
```json
{
  "channels": [
    {
      "channel": 1,
      "dispensedVolume": 100
    },
    {
      "channel": 2,
      "dispensedVolume": 100
    },
    {
      "channel": 3,
      "dispensedVolume": 100
    },
    {
      "channel": 4,
      "dispensedVolume": 100
    },
    {
      "channel": 5,
      "dispensedVolume": 100
    },
    {
      "channel": 6,
      "dispensedVolume": 100
    },
    {
      "channel": 7,
      "dispensedVolume": 100
    },
    {
      "channel": 8,
      "dispensedVolume": 100
    }
  ],
  "TADM":{
    "tadmCurves": [
      {
      "curveId": 2587,
      "liquidClassName": "SVF_DispenseJet_Empty",
      "stepType": 0,
      "stepTypeName": "Dispensing",
      "volume": 50.0,
      "timeStamp": "2026-05-20 17:30:50",
      "stepGuid": "d6d9133e_366d_4364_b65be48b094329cc",
      "toleranceBandGuid": "00000000-0000-0000-0000-000000000000",
      "stepNumber": 7166,
      "curvePoints": [
        {
          "timeMs": -340,
          "pressure": -29
        },
        ...
      ],
      "error": 0,
      "channelNumber": 3,
      "tadmMode": 1,
      "curveFlagged": 0,
      "checkSum": -1110657860
    },
    ...
    ]
  }
}
```
#### channels.5mL.dispenseOnTheFly
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.5mL.dispenseOnTheFly",
    "parameters": {
      "channels": [1, 2, 3, 4],
      "labwareName": "plate 1",
      "volumes": 100.0,
      "labwareSurfaceDistance": 3.0,
      "startXOffset": 0.0,
      "xSpeed": 0.0,
      "xAccelerationDistance": 8.0,
      "dispenseDirection": 0,
      "excludedPositions": ["A1","B1","C1","D1","E1","F1","G1","H1"]
    }
  }
}
```
> `channels`: must be one of `[1]`, `[1,2]`, `[1,2,3,4]`, or `[1,2,3,4,5,6,7,8]`  
> `volumes`: single value applied to all channels, or an array matching the number of channels  
> `labwareSurfaceDistance`: dispense height above labware surface (mm)  
> `startXOffset`: X offset from the first well (mm)  
> `xSpeed`: arm travel speed in mm/s — set to `0` to auto-calculate speed and acceleration  
> `xAccelerationDistance`: distance (mm) used to ramp up to `xSpeed`; ignored when `xSpeed` is `0`  
> `dispenseDirection`: `0` = Serpentine (alternating columns), `1` = From left only  
> `excludedPositions` (optional): array of well IDs to skip (e.g. `["A1","B1"]`); can be omitted or left empty `[]`

**Returns:**
```json
{}
```

#### channels.5mL.moveAxis
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.5mL.moveAxis",
    "parameters": {
      "channels": [1, 2, 3, 4],
      "x": 200.0,
      "y": [500, 491, 482, 473],
      "z": 245,
      "safetyBypassToken": ""
    }
  }
}
```
> `channels`: array or single integer value for one channel  
> `x`: single value only (Optional)  
> `y`: array or single value for one channel (Optional)  
> `z`: array or single value — one value applies to all channels (Optional)  
> `safetyBypassToken` (optional): `"OVERRIDE_SAFETY_CHECKS"`

**Returns:**
```json
{
  "channelStatus": [
    {"channel": 1, "x": 0, "y": 0, "z": 0 },
    {"channel": 2, "x": 0, "y": 0, "z": 0 },
    {"channel": 3, "x": 0, "y": 0, "z": 0 },
    {"channel": 4, "x": 0, "y": 0, "z": 0 }
  ]
}
```

#### channels.5mL.getStatus
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.5mL.getStatus",
    "parameters": {}
  }
}
```

**Returns:**
```json
{
  "channelStatus": [
    { "channel": 1, "x": 0, "y": 0, "z": 0, "tipLoaded": 0 },
    { "channel": 2, "x": 0, "y": 0, "z": 0, "tipLoaded": 0 },
    { "channel": 3, "x": 0, "y": 0, "z": 0, "tipLoaded": 0 },
    { "channel": 4, "x": 0, "y": 0, "z": 0, "tipLoaded": 0 }
  ]
}
```
---
### MagPip Channels

The MagPip channels are the 1 mL pipetting channels driven in magnetic-bead (`Mag*`) firmware mode. Every command mirrors its `channels.1mL.*` counterpart — same parameters, same returns — under the `channels.MagPip` action namespace, with three additions: `aspirate` / `dispense` / `dispenseOnTheFly` accept an optional nested `TADM` object, `dispenseOnTheFly` also accepts `ADC`, and `tipTrackingFactor` is **not** supported. There are no MagPip transport commands.

> `TADM` (optional object): omit to let VENUS apply its defaults.
> - `enabled` (int, default `0`): `0` = off, `1` = recording mode, `2` = monitoring mode
> - `recording` (int, default `2`): `0` = no curves recorded, `1` = error curves only, `2` = all curves

#### channels.MagPip.tipPickup
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.MagPip.tipPickup",
    "parameters": {
      "channels": [1, 2, 3, 4, 5, 6, 7, 8],
      "tipPool": "300 uL Tips"
    }
  }
}
```
> Use `tipPool` **or** `positions` (array of `{"labwareId","wellId"}`), not both.
> `optimizedPickup` (bool, optional) — only valid with `tipPool`.

**Returns:**
```json
{
  "remainingTips": 80
}
```

#### channels.MagPip.tipEject
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.MagPip.tipEject",
    "parameters": { "ejectMode": "waste" }
  }
}
```
> `ejectMode` values: `"waste"`, `"return"`, `"tipPool"` (add `"channels"` + `"tipPool"`), `"positions"` (add `"channels"` + `"positions"`).

**Returns:**
```json
{}
```

#### channels.MagPip.tipCheck
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "channels.MagPip.tipCheck", "parameters": {} } }
```
**Returns:**
```json
{
  "activeChannels": [
    { "channel": 1, "tipType": 0, "tipName": "300ul Standard Volume Tip" }
  ]
}
```

#### channels.MagPip.aspirate
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.MagPip.aspirate",
    "parameters": {
      "channels": [1, 2, 3, 4, 5, 6, 7, 8],
      "positions": [
        { "labwareId": "Plate_1", "wellId": "A1" },
        { "labwareId": "Plate_1", "wellId": "B1" }
      ],
      "volumes": 100.0,
      "liquidClass": "Water_DispenseJet_Empty",
      "aspirateMode": 0,
      "capacitiveLLD": 0,
      "pressureLLD": 0,
      "liquidFollowing": false,
      "submergeDepth": 2.0,
      "fixedHeight": 5.0,
      "maxLLdDifference": 3.0,
      "mixCycles": 0,
      "mixPosition": 0.0,
      "mixVolume": 0.0,
      "airTransportRetractDist": 5.0,
      "touchOff": 0,
      "touchOffHeight": 1.0,
      "madEnabled": false,
      "madThreshold": 30,
      "ADC": false,
      "TADM": { "enabled": 2, "recording": 2 }
    }
  }
}
```
> Same fields and array/scalar rules as `channels.1mL.aspirate`, **except** `tipTrackingFactor` is not accepted.
> `madEnabled` (optional, default `false`); `madThreshold` (optional, default `30`, range 1–1023).
> `ADC` (optional, default `false`): Anti-Droplet Control.
> `TADM` (optional): see note above.

**Returns:** same shape as `channels.1mL.aspirate` (per-channel `aspiratedVolume` / `liquidLevel_mm` / `liquidVolume_uL`, plus a `TADM` curve payload when monitoring/recording is active).

#### channels.MagPip.dispense
```json
{
  "category": "Instrument",
  "actionName": "channels.MagPip.dispense",
  "parameters": {
    "channels": [1, 2, 3, 4, 5, 6, 7, 8],
    "positions": [
      { "labwareId": "midi plate 2", "wellId": "A1" }
    ],
    "volumes": 100,
    "dispenseMode": 8,
    "capacitiveLLD": 0,
    "liquidFollowing": true,
    "submergeDepth": 0,
    "fixedHeight": 5,
    "mixCycles": 0,
    "mixPosition": 0,
    "mixVolume": 0,
    "airTransportRetractDist": 5,
    "touchOff": 0,
    "touchOffHeight": 0,
    "useSideTouch": false,
    "ADC": false,
    "TADM": { "enabled": 2, "recording": 2 }
  }
}
```
> Same fields as `channels.1mL.dispense`, **except** `tipTrackingFactor` is not accepted.
> `ADC` (optional, default `false`). `TADM` (optional): see note above.

**Returns:** same shape as `channels.1mL.dispense` (per-channel `dispensedVolume`, plus an optional `TADM` curve payload).

#### channels.MagPip.dispenseOnTheFly
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.MagPip.dispenseOnTheFly",
    "parameters": {
      "channels": [1, 2, 3, 4],
      "labwareName": "plate 1",
      "volumes": 100.0,
      "labwareSurfaceDistance": 3.0,
      "startXOffset": 0.0,
      "xSpeed": 0.0,
      "xAccelerationDistance": 8.0,
      "dispenseDirection": 0,
      "excludedPositions": ["A1","B1"],
      "ADC": false,
      "TADM": { "enabled": 2, "recording": 2 }
    }
  }
}
```
> Same fields as `channels.1mL.dispenseOnTheFly` plus optional `ADC` (bool, default `false`) and optional `TADM` (see note above).
> `channels`: must be one of `[1]`, `[1,2]`, `[1,2,3,4]`, or `[1,2,3,4,5,6,7,8]`.
> `dispenseDirection`: `0` = Serpentine (alternating columns), `1` = From left only.

**Returns:**
```json
{}
```

#### channels.MagPip.moveAxis
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.MagPip.moveAxis",
    "parameters": {
      "channels": [1, 2, 3, 4],
      "x": 200.0,
      "y": [500, 491, 482, 473],
      "z": 245,
      "safetyBypassToken": ""
    }
  }
}
```
> Same rules as `channels.1mL.moveAxis` (`x` single value only; `y`/`z` array or single value; `safetyBypassToken` optional `"OVERRIDE_SAFETY_CHECKS"`).

**Returns:**
```json
{
  "channelStatus": [
    { "channel": 1, "x": 0, "y": 0, "z": 0 }
  ]
}
```

#### channels.MagPip.getStatus
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "channels.MagPip.getStatus", "parameters": {} } }
```
**Returns:**
```json
{
  "channelStatus": [
    { "channel": 1, "x": 0, "y": 0, "z": 0, "tipLoaded": 0 }
  ]
}
```

#### channels.MagPip.detectLiquidLevel
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "channels.MagPip.detectLiquidLevel",
    "parameters": {
      "channels": [1, 2, 3, 4, 5, 6, 7, 8],
      "positions": [{ "labwareId": "Plate_1", "wellId": "A1" }],
      "capacitiveLLD": 1,
      "pressureLLD": 0
    }
  }
}
```
**Returns:**
```json
{
  "channels": [
    { "channel": 1, "liquidLevel_mm": 0, "liquidVolume_uL": 0 }
  ]
}
```
---
### MPH96

#### mph96.tipPickup
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "mph96.tipPickup",
    "parameters": {
      "tipPool": "300 uL Tips",
      "preAirAspirate": 0
    }
  }
}
```
> Use `labwareId` (string) **or** `tipPool` (both optional, but one should be supplied). `preAirAspirate`: 0–3; use 3 for custom volume with `preAirVolume`.  
> `preAirVolume` (optional): required only when `preAirAspirate` is `3`
```text
PreAirAspirate Enum:
0 = Disabled
1 = Blowout maxium tip volume
2 = Aspirate maxium tip volume
3 = Aspirate custom volume (requires preAirVolume)
```
**Returns:**
```json
{
  "remainingTips": 368
}
```
#### mph96.tipPickupPartial
```json
{
  "channel": "action",
  "data": {
  "category": "Instrument",
  "actionName": "mph96.tipPickupPartial",
    "parameters": {
      "tipPool": "tips1mL",
      "count": 1,
      "mphPickupSide": 1,
      "preAirAspirate": 3,
      "preAirVolume": 5.0
    }
  }  
}
```
> `mphPickupSide`: 0=Left, 1=Right, 2=Rear, 3=Front  
> `preAirVolume` (optional): required only when `preAirAspirate` is `3`
```text
PreAirAspirate Enum:
0 = Disabled
1 = Blowout maxium tip volume
2 = Aspirate maxium tip volume
3 = Aspirate custom volume (requires preAirVolume)
```
**Returns:**
```json
{
  "remainingTips": 368
}
```
#### mph96.tipEject
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "mph96.tipEject",
    "parameters": {
    "ejectMode": "waste"
    }
  }
}
```
> `ejectMode` values:
> - `"waste"` — eject to waste (no extra params)
> - `"return"` — return to pickup position (no extra params)
> - `"tipPool"` — add `"tipPool"` (string)
> - `"positions"` — add `"mphSelection"` (array of `"wellId"`, optional — defaults to all 96 wells if omitted), and `"labwareName"` (string)
**Returns:**
```json
{}
```
#### mph96.aspirate
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "mph96.aspirate",
      "parameters": {
         "labwareName": "Plate 1",
         "mphSelection": ["A1", "B1", "C1","D1","E1","F1","G1","H1"],
         "volume": 100.0,
         "liquidClass": "",
         "aspirateMode": 0,
         "capacitiveLLD": 0,
         "liquidFollowing": false,
         "tipTrackingFactor": 1.0,
         "submergeDepth": 2.0,
         "fixedHeight": 1.0,
         "mixCycles": 0,
         "mixPosition": 0.0,
         "mixVolume": 0.0,
         "airTransportRetractDist": 5.0
       }
  }
}
```
>`"mphSelection"` is optional and the system will default to all 96 wells if this is not specified
```text
Aspirate Mode enum:
0 = Normal, 1 = Consecutive, 2 = Aspirate All

Capacitive LLD enum:
0 = Off, 1 = Max, 2 = High, 3 = Mid, 4 = Low, 5 = From labware definition
```
**Returns:**
```json
{
  "aspiratedVolume": 100,
  "detectedLiquidHeight": 0,
  "detectedLiquidVolume": 0
}
```
#### mph96.dispense
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "mph96.dispense",
    "parameters": {
     "labwareName": "Plate 1",
     "mphSelection": ["A1", "B1", "C1","D1","E1","F1","G1","H1"],
     "volume": 100.0,
     "dispenseMode": 0,
     "capacitiveLLD": 0,
     "liquidFollowing": false,
     "tipTrackingFactor": 1.0,
     "submergeDepth": 2.0,
     "fixedHeight": 1.0,
     "mixCycles": 0,
     "mixPosition": 0.0,
     "mixVolume": 0.0,
     "airTransportRetractDist": 5.0,
     "useSideTouch": false
   }
  }
}
```
>`"mphSelection"` is optional and the system will default to all 96 wells if this is not specified
```text
Dispense Mode enum:
0 = Jet part volume, 1 = Jet empty tip, 2 = Surface part volume, 3 = Surface empty tip, 4 = Drain tip in jet mode, 8 = From liquid class definition, 9 = Blowout tipl

Capacitive LLD enum:
0 = Off, 1 = Max, 2 = High, 3 = Mid, 4 = Low, 5 = From labware definition
```
**Returns:**
```json
{
  "dispensedVolume": 100,
  "detectedLiquidHeight": 0,
  "detectedLiquidVolume": 0
}
```
#### mph96.clearTipSupport
```json
{
  "channel": "action",
  "data": { "category": "Instrument", "actionName": "mph96.clearTipSupport", "parameters": { "tipPool": "300ul tips"} }
}
```
**Returns:**
```json
{
  "remainingTips": 80
}
```
#### mph96.parkBack
```json
{
  "channel": "action",
  "data": { "category": "Instrument", "actionName": "mph96.parkBack", "parameters": {} }
}
```
**Returns:**
```json
{}
```
#### mph96.parkFront
```json
{
  "channel": "action",
  "data": { "category": "Instrument", "actionName": "mph96.parkFront", "parameters": {} }
}
```
**Returns:**
```json
{}
```
#### mph96.moveAxis
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "mph96.moveAxis",
    "parameters": {
      "axis": 0,
      "value": 132.1,
      "mode": 0,
      "safetyBypassToken": "OVERRIDE_SAFETY_CHECKS"
    }
  }
}
```
```text
Mode Enum:
0 = Absolute coordinates
1 = Relative movement

Axis Enum:
0 = X
1 = Y
2 = Z

Safety Bypass Token = "OVERRIDE_SAFETY_CHECKS"
```
> `safetyBypassToken` (optional): `"OVERRIDE_SAFETY_CHECKS"` or blank
**Returns:**
```json
{
  "x": 0.0,
  "y": 0.0,
  "z": 0.0
}
```
#### mph96.getStatus
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "mph96.getStatus",
    "parameters": {}
  }
}
```
**Returns:**
```json
{
  "mph96Status": {
    "x": 0.0,
    "y": 0.0,
    "z": 0.0,
    "tipLoaded": 0
  }
}
```
#### mph96.detectLiquidLevel
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "mph96.detectLiquidLevel",
    "parameters": {
      "labwareName": "Plate 1",
      "capacitiveLLD": 1
    }
  }
}
```
```text
Capacitive LLD enum:
1 = Max, 2 = High, 3 = Mid, 4 = Low, 5 = From labware definition
```
**Returns:**
```json
{
  "detectedLiquidHeight": 0.0,
  "detectedLiquidVolume": 0.0
}
```
---

### Transport 1mL

#### transport.1mL.moveLabware
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "transport.1mL.moveLabware",
    "parameters": {
      "labwareName": "Plate 1",
      "carrier": "Deep Well Carrier",
      "site": "2",
      "gripHeightAboveBottom": 15.5,
      "gripWidth": 80.0,
      "gripOpen": 90.0,
      "toolId": 0,
      "frontChannel": 8,
      "gripForce": 5,
      "pressDistance": 1.0,
      "xAcceleration": 4,
      "gripCloseSpeed": 277.8,
      "gripZSpeed": 128.7,
      "offsetGrip": 0.0,
      "checkPresence": {
        "get": true,
        "put": false
      },
      "ejectGrip": true
    }
  }
}
```
> `gripHeightAboveBottom` tip: use `height_mm / 2` from labware definition (8=MTP, 27=DWP, 35=TipRack)  
> Optional: `gripWidth` (default `80.0`), `gripOpen` (default `90.0`), `toolId`, `frontChannel`, `gripForce`, `pressDistance`, `xAcceleration`, `gripCloseSpeed`, `gripZSpeed`, `offsetGrip`, `checkPresence`, `ejectGrip`

**Returns:**
```json
{
  "message": "Successfully transported plate 1 from deep well carrier [1] to deep well carrier [2]."
}
```

#### transport.1mL.isHoldingLabware
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "transport.1mL.isHoldingLabware", "parameters": {} } }
```
**Returns:**
```json
{
  "isHoldingPlate": true,
  "labwareName": "plate 1",
  "carrier": "deep well carrier",
  "site": "1",
  "offsetGrip": 0
}
```
#### transport.1mL.clearHeldLabware
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "transport.1mL.clearHeldLabware", "parameters": {} } }
```
**Returns:**
```json
{
  "message": "Transport tracking reset"
}
```
#### transport.1mL.ejectGrips
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "transport.1mL.ejectGrips", "parameters": {} } }
```
**Returns:**
```json
{
  "message": "Grips successfully removed"
}
```
#### transport.1mL.returnLabware

**mode: "return"** — returns plate to original pickup position (no carrier/site required)
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "transport.1mL.returnLabware",
    "parameters": {
      "mode": "return",
      "gripZSpeed": 128.7,
      "xAcceleration": 4,
      "pressDistance": 1.0,
      "ejectGrip": true
    }
  }
}
```
> Optional: `checkPresencePut`, `gripZSpeed` (default `128.7`), `xAcceleration` (default `4`), `pressDistance`, `ejectGrip`
**Returns:**
```json
{
  "message": "Successfully returned plate 1 to deep well carrier [1]."
}
```
**mode: "new"** — places plate at a new carrier/site
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "transport.1mL.returnLabware",
    "parameters": {
      "mode": "new",
      "carrier": "Deep Well Carrier",
      "site": "2",
      "checkPresence": { "put": false },
      "gripZSpeed": 128.7,
      "xAcceleration": 4,
      "pressDistance": 1.0,
      "ejectGrip": true
    }
  }
}
```
> `carrier` and `site` are only used when `mode` is `"new"`  
> Optional: `carrier`, `site`, `checkPresencePut`, `gripZSpeed` (default `128.7`), `xAcceleration` (default `4`), `pressDistance`, `ejectGrip`
**Returns:**
```json
{
  "message": "Successfully returned plate 1 to deep well carrier [1]."
}
```
#### transport.1mL.moveToWaste
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "transport.1mL.moveToWaste",
    "parameters": {
      "labwareName": "Plate 1",
      "gripHeightAboveBottom": 15.5,
      "gripWidth": 80.0,
      "gripOpen": 90.0,
      "toolId": 0,
      "frontChannel": 8,
      "gripForce": 5,
      "xAcceleration": 4,
      "gripCloseSpeed": 277.8,
      "gripZSpeed": 128.7,
      "offsetGrip": 0.0,
      "checkPresence": { "get": true },
      "ejectGrip": true
    }
  }
}
```
> Optional: `gripWidth` (default `80.0`), `gripOpen` (default `90.0`), `toolId`, `frontChannel`, `gripForce`, `xAcceleration`, `gripCloseSpeed`, `gripZSpeed`, `offsetGrip`, `checkPresence`, `ejectGrip`

**Returns:**
```json
{
  "message": "Successfully transported plate 1 from deep well carrier [1] to waste."
}
```
#### transport.1mL.holdLid
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "transport.1mL.holdLid",
    "parameters": {
      "toolId": 0,
      "labwareName": "test plate_lid",
      "gripHeightFromTop": 5,
      "frontChannel": 8,
      "gripForce": 5,
      "gripWidth": 80,
      "gripOpen": 85,
      "checkPresence": {
        "get": true
      },
      "gripCloseSpeed": 277.8,
      "gripZSpeed": 128.7,
      "xAcceleration": 4
    }
  }
}
```
> Optional: `toolId`, `frontChannel`, `gripForce` (default `5`), `gripWidth` (default `80.0`), `gripOpen` (default `85.0`), `gripCloseSpeed` (default `277.8`), `gripZSpeed` (default `128.7`), `xAcceleration` (default `4`)

**Returns:**
```json
{
  "message": "Successfully holding test plate_lid."
}
```
---
### Transport iSWAP

#### transport.iswap.moveLabware
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "transport.iswap.moveLabware",
    "parameters": {
      "labwareName": "Plate1",
      "carrier": "SomeShakerCarrier",
      "site": "1",
      "gripHeightAboveBottom": 8.0,
      "gripForce": 5,
      "gripWidth": 80.0,
      "gripOpen": 85.0,
      "tolerance": 5.0,
      "gripInverse": false,
      "placeRotation": 1,
      "offsetGrip": 0.0
    }
  }
}
```
> `placeRotation`: 1=0°, 2=90°, 3=180°, 4=270°  
> `gripInverse`: `true` = grip from left side; `false` = grip from right side  
> `tolerance` (optional, default `5.0`)

**Returns:**
```json
{
  "message": "Successfully transported plate 1 from deep well carrier [1] to someshakercarrier [1]."
}
```

#### transport.iswap.clearHeldLabware
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "transport.iswap.clearHeldLabware", "parameters": {} } }
```
**Returns:**
```json
{
    "message": "Transport tracking reset"
}
```

#### transport.iswap.getLabware
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "transport.iswap.getLabware",
    "parameters": {
      "labwareName": "Plate1",
      "gripHeightAboveBottom": 8.0,
      "gripForce": 5,
      "gripWidth": 80.0,
      "gripOpen": 85.0,
      "tolerance": 5.0,
      "gripInverse": false,
      "offsetGrip": 0.0
    }
  }
}
```
> Picks up labware without placing it — pair with `transport.iswap.putLabware` for split-move workflows.  
> `gripInverse`: `true` = grip from left side; `false` = grip from right side (ignored with `complexMovement`)  
> `complexMovement` (optional object): a hotel get. Its presence switches complex movement on; give all three of its fields, since a missing one is 0 (or orientation 4):  
> `"complexMovement": { "retractDistance": 139.0, "liftHeight": 35.0, "orientation": 1 }` — `retractDistance` (mm) is how far the iSWAP reaches into the hotel, `liftHeight` (mm) the lift, `orientation` the direction the iSWAP faces, toward the hotel (1=Front, 2=Right, 3=Rear, 4=Left); a put facing another way than the get gripped needs the matching `placeRotation` (180° for the opposite side), since the labware turns with the iSWAP  
> `tolerance` (optional, default `5.0`)

**Returns:**
```json
{
  "message": "Successfully picked up Plate1."
}
```

#### transport.iswap.isHoldingLabware
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "transport.iswap.isHoldingLabware", "parameters": {} } }
```
**Returns:**
```json
{
  "isHoldingPlate": false,
  "labwareName": "",
  "carrier": "",
  "site": "",
  "offsetGrip": 0
}
```

#### transport.iswap.moveToWaste
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "transport.iswap.moveToWaste",
    "parameters": {
      "labwareName": "Plate1",
      "gripHeightAboveBottom": 8.0,
      "gripForce": 5,
      "gripWidth": 80.0,
      "gripOpen": 85.0,
      "tolerance": 5.0,
      "gripInverse": false,
      "offsetGrip": 0.0
    }
  }
}
```
> `gripInverse`: `true` = grip from left side; `false` = grip from right side  
> `tolerance` (optional, default `5.0`)

**Returns:**
```json
{
  "message": "Successfully moved Plate1 to waste."
}
```

#### transport.iswap.park
```json
{ "channel": "action", "data": { "category": "Instrument", "actionName": "transport.iswap.park", "parameters": {} } }
```
**Returns:**
```json
{}
```

#### transport.iswap.putLabware
```json
{
  "channel": "action",
  "data": {
    "category": "Instrument",
    "actionName": "transport.iswap.putLabware",
    "parameters": {
      "carrier": "SomeShakerCarrier",
      "site": "1",
      "placeRotation": 1
    }
  }
}
```
> Places currently-held labware at a carrier/site — pair with `transport.iswap.getLabware` for split-move workflows.  
> `placeRotation`: 1=0°, 2=90°, 3=180°, 4=270°  
> `complexMovement` (optional object): a hotel put, with the same three fields as for `transport.iswap.getLabware`

**Returns:**
```json
{
  "message": "Successfully placed labware at someshakercarrier [1]."
}
```

