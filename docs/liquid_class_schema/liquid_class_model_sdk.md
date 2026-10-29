Valid values for the enumerated fields below (`tipType`, `dispenseMode`, `pipettingDevice`) and the numeric min/max bounds for `pipettingProperties` fields, keyed by device, are in `JSON_Liquid-Class-Reference-Values.md`.

```jsonc
{
  "id": "HighVolume_Water_DispenseSurface_Empty",   // unique identifier == the 'LiquidClassName' value in the VENUS database, and matches the JSON file name (no "hamilton:" prefix, no separate label field)
  "isUserDefined": true,               // false = Predefined (IsOriginal, read-only) | true = Custom (read/write)
  "version": "x.y",
  "tadmEnabled": false,                // true = tip-based Advanced Dispense Monitoring capture is on for this class; tadmBands is only populated when this is true
  "validated": true,
  "notes": "",

  "appliesTo": {
    "instrument": "STAR",                        // instrument name, e.g. "ML_STAR"
    "liquid": "Water",                           // liquid name
    "volumeRange": { "min": 0, "max": 1000 },    // uL the tip can hold; minimum is always 0, max is the nominal uL of the tip type
    "tipType": "1000ul-high-volume-tip",         // see JSON_Liquid-Class-Reference-Values.md#tip-types-appliestotiptype for valid values
    "dispenseMode": "surface_empty",             // see JSON_Liquid-Class-Reference-Values.md#dispense-modes-appliestodispensemode for valid values
    "pipettingDevice": "channels_1000ul"         // see JSON_Liquid-Class-Reference-Values.md#pipetting-devices-appliestopipettingdevice for valid values
  },

  "pipettingProperties": {             // numeric min/max for every field below are per-device — see Reference-Values.md#parameter-ranges-by-device
    "aspirate": {
      "flowRate": 250.0,
      "mixFlowRate": 120.0,
      "airTransportVolume": 5.0,
      "blowOutVolume": 0.0,
      "swapSpeed": 2.0,
      "settlingTime": 1.0,
      "overAspirateVolume": 5.0,
      "clotRetractHeight": 0.0     // mm the tip retracts on aspirate to clear a clot/surface film; 0 = not used
    },
    "dispense": {
      "flowRate": 120.0,
      "mixFlowRate": 120.0,
      "airTransportVolume": 5.0,
      "blowOutVolume": 0.0,
      "swapSpeed": 2.0,
      "settlingTime": 0.0,
      "stopFlowRate": 5.0,
      "stopBackVolume": 0.0
    },
    "detection": { "lld": { "pressureSensitivity": 4, "lldMaxHeightDifference": 0 } },
    "correction": [ { "targetedVolume": 0, "correctedVolume": 0 }, { "targetedVolume": 1000, "correctedVolume": 1028.5 } ],  // correctionCurve, any number of points
    "tadmBands": [                 // populated only when tadmEnabled is true; one entry per captured TADM curve
      {
        "id": 0,                                         // band index within this liquid class
        "liquidClassId": 0,                               // internal id linking the band back to its liquid class
        "bandGuid": "C6B2F1B5-ACCF-4039-9F19-66B4B7DA066D", // unique GUID for this band record
        "stepType": 0,                                    // numeric id of the pipetting step the curve was captured on
        "stepTypeName": "Aspirating",                     // human-readable name for stepType
        "volume": 300,                                    // volume (uL) the curve was captured at
        "modifiedDate": "2024-05-20 13:54:52",             // "YYYY-MM-DD HH:MM:SS" timestamp of last save
        "state": "Band saved",                             // status string
        "upperCurve": [ { "timeMs": 0, "pressure": 451 } ], // upper TADM envelope: {timeMs, pressure} points, raw sensor units
        "lowerCurve": [ { "timeMs": 0, "pressure": -501 } ] // lower TADM envelope: {timeMs, pressure} points, raw sensor units
      }
    ],
    "whiPipJson": { "...": "..." }  // OPAQUE. Present only when appliesTo.dispenseMode is "whipip" (channels_magpip liquid classes). See note below — do not hand-author or parse into individual fields.
  },

  "_internal": {                    // VENUS-managed bookkeeping; not hand-authored
    "designHistory": "AQAAAAA=",    // opaque base64 blob tracking edit history in the VENUS editor
    "tipTypeId": 0,                 // internal numeric id for appliesTo.tipType
    "dispenseMode": 3,              // internal numeric id for appliesTo.dispenseMode (e.g. 3 = jet_empty, 5 = surface_empty)
    "liquidDeviceIds": [ 1 ]        // internal numeric device id(s) for appliesTo.pipettingDevice
  }
}
```

Numbers are bare in fixed canonical units (µL, µL/s, mm/s, s), except `timeMs` (milliseconds) and `pressure` (raw sensor units) inside `tadmBands`.

## `whiPipJson` (opaque — do not hand-author)

Present only on MagPip (`channels_magpip`) liquid classes where `appliesTo.dispenseMode` is `"whipip"`. It's a versioned calibration payload — capture metadata (liquid density, tip, template name), the ambient conditions it was calibrated under (temperature, humidity, pressure, datetime), and a `software_data` block of raw plunger motion-curve arrays (acceleration/amplitude/deceleration/plateau speed and timing, one set per calibrated volume point) plus a separate hydrostatic pressure-vs-volume curve. These are Hamilton calibration-tool outputs with no documented physical units at the field level, not a designed/tunable parameter set.

**Treat this object as opaque**: preserve it verbatim when reading and re-writing a `whipip` liquid class (e.g. when only a `correction` point or an unrelated field is being changed), and never derive, interpolate, or hand-generate its contents. New or updated WhiPip calibration data comes from Hamilton's calibration tooling, not from application code. Internal field-level detail is intentionally not enumerated here given its complexity and the lack of stable, documented units.
