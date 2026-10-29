# Device

### HHS (Hamilton Heater Shaker)

#### HHS.createStarDevice
```json
{
  "channel": "action",
  "data": {
    "category": "Device",
    "actionName": "HHS.createStarDevice",
    "parameters": {
      "node": 1
    }
  }
}
```
> `node`: STAR Node ID (1-2)

**Returns:**
```json
{
  "deviceId": 1
}
```

#### HHS.createUsbDevice
```json
{
  "channel": "action",
  "data": {
    "category": "Device",
    "actionName": "HHS.createUsbDevice",
    "parameters": {
      "node": 1
    }
  }
}
```
> `node`: HHS Node ID (1-8)

**Returns:**
```json
{
  "deviceId": 1
}
```

#### HHS.getDeviceIds
```json
{ "channel": "action", "data": { "category": "Device", "actionName": "HHS.getDeviceIds", "parameters": {} } }
```
**Returns:**
```json
{
  "deviceIds": [
    {
      "deviceId": 1,
      "node": 1,
      "connectUsb": false,
      "serialNumber": "0000",
      "firmwareVersion": "0.0S 2008-01-01"
    }
  ]
}
```

#### HHS.getStatus
```json
{ "channel": "action", "data": { "category": "Device", "actionName": "HHS.getStatus", "parameters": {} } }
```
**Returns:**
```json
{
  "deviceIds": [
    {
      "deviceId": 1,
      "shakingSpeed": 0,
      "temperature": 0,
      "tempControlStatus": "No error, temperature was always in the defined range."
    }
  ]
}
```

#### HHS.setPlateLock
```json
{
  "channel": "action",
  "data": {
    "category": "Device",
    "actionName": "HHS.setPlateLock",
    "parameters": {
      "deviceId": 1,
      "lock": true
    }
  }
}
```
> `deviceId`: Device ID of the HHS (optional - if empty, applies to all)  
> `lock`: Lock state (false = unlock, true = lock)

**Returns:**
```json
{
  "plateLockStatus": true
}
```

#### HHS.startShaker
```json
{
  "channel": "action",
  "data": {
    "category": "Device",
    "actionName": "HHS.startShaker",
    "parameters": {
      "deviceId": 1,
      "speed": 1000,
      "time": 0
    }
  }
}
```
> `deviceId`: Device ID of the HHS (optional - if empty, applies to all)  
> `speed`: Shaking speed in RPM (30-2500)  
> `time`: Duration in seconds (0-30000, 0 = indefinite)

**Returns:**
```json
{
  "shakingStarted": "2026-06-26T15:53:56"
}
```

#### HHS.startTempControl
```json
{
  "channel": "action",
  "data": {
    "category": "Device",
    "actionName": "HHS.startTempControl",
    "parameters": {
      "deviceId": 1,
      "temperature": 25.0
    }
  }
}
```
> `deviceId`: Device ID of the HHS (optional - if empty, applies to all)  
> `temperature`: Target temperature in °C

**Returns:**
```json
{
  "tempControlStarted": "2026-06-26T15:56:14"
}
```

#### HHS.stopShaker
```json
{
  "channel": "action",
  "data": {
    "category": "Device",
    "actionName": "HHS.stopShaker",
    "parameters": {
      "deviceId": 1
    }
  }
}
```
> `deviceId`: Device ID of the HHS (optional - if empty, applies to all)

**Returns:**
```json
{
  "shakingStopped": "2026-06-26T15:57:20"
}
```

#### HHS.stopTempControl
```json
{
  "channel": "action",
  "data": {
    "category": "Device",
    "actionName": "HHS.stopTempControl",
    "parameters": {
      "deviceId": 1
    }
  }
}
```
> `deviceId`: Device ID of the HHS (optional - if empty, applies to all)

**Returns:**
```json
{
  "tempControlStopped": "2026-06-26T15:58:17"
}
```

#### HHS.terminate
```json
{ "channel": "action", "data": { "category": "Device", "actionName": "HHS.terminate", "parameters": {} } }
```
**Returns:**
```json
{
  "message": "HHS disconnected"
}
```

#### HHS.waitForShaker
```json
{
  "channel": "action",
  "data": {
    "category": "Device",
    "actionName": "HHS.waitForShaker",
    "parameters": {
      "deviceId": 1
    }
  }
}
```
> `deviceId`: Device ID of the HHS (optional - if empty, waits for all)

**Returns:**
```json
{
  "shakingStopped": "2026-06-26T15:58:35"
}
```

#### HHS.waitForTempControl
```json
{
  "channel": "action",
  "data": {
    "category": "Device",
    "actionName": "HHS.waitForTempControl",
    "parameters": {
      "deviceId": 1
    }
  }
}
```
> `deviceId`: Device ID of the HHS (optional - if empty, waits for all)

**Returns:**
```json
{
  "tempControlStopped": "2026-06-26T15:58:54"
}
```

### WXS (Precision Balance)

#### WXS.initializeBalance
```json
{
  "channel": "action",
  "data": {
    "category": "Device",
    "actionName": "WXS.initializeBalance",
    "parameters": {
      "port": 1,
      "timeOutSeconds": 10,
      "trials": 2
    }
  }
}
```
> `port`: COM port number the device is connected to  
> `timeOutSeconds`: Time in seconds before a timeout occurs (optional) [0-60]  
> `trials`: Number of trials to establish a connection (optional) [1-10]

#### WXS.resetScale
```json
{ "channel": "action", "data": { "category": "Device", "actionName": "WXS.resetScale", "parameters": {} } }
```

#### WXS.setZero
```json
{
  "channel": "action",
  "data": {
    "category": "Device",
    "actionName": "WXS.setZero",
    "parameters": {
      "zeroImmidiately": true
    }
  }
}
```
> `zeroImmidiately`: Set a new zero immediately, regardless of balance stability (optional)

Note: The tare memory is cleared after zero setting. All weight values (including the tare weight) are measured relative to this zero.

#### WXS.tare
```json
{
  "channel": "action",
  "data": {
    "category": "Device",
    "actionName": "WXS.tare",
    "parameters": {
      "tareImmidiately": true
    }
  }
}
```
> `tareImmidiately`: Tare the balance immediately and independently of balance stability (optional)

Note: Call `WXS.setZero` before using this function. Negative weight on the scale may lead to an error.

**Returns:**
```json
{
  "tareWeight": 5.00000
}
```
> `tareWeight`: The tare weight value, corresponding to the weight change on the balance

#### WXS.internalCalibration
```json
{ "channel": "action", "data": { "category": "Device", "actionName": "WXS.internalCalibration", "parameters": {} } }
```
Starts an internal adjustment procedure of the scale.

#### WXS.getWeight
```json
{
  "channel": "action",
  "data": {
    "category": "Device",
    "actionName": "WXS.getWeight",
    "parameters": {
      "weighImmidiately": true
    }
  }
}
```
> `weighImmidiately`: Immediately get the current weight value (optional)

**Returns:**
```json
{
  "weightGramm": 5.00000,
  "weightStable": true,
  "measuredWeight": "",
  "measuredUnit": ""
}
```
> `weightGramm`: Measured weight value in grams  
> `weightStable`: Whether the measured value was stable or dynamic  
> `measuredWeight`: Measured weight from the scale, for individual measurements other than grams  
> `measuredUnit`: Measured unit from the scale, for individual measurements other than grams

#### WXS.setScaleParameters
```json
{
  "channel": "action",
  "data": {
    "category": "Device",
    "actionName": "WXS.setScaleParameters",
    "parameters": {
      "weighingMode": 0,
      "vibration": 3,
      "stability": 1,
      "weightUnit": 0,
      "autoZero": false
    }
  }
}
```
> `weighingMode`: Weighing mode (optional) — 0=Normal, 1=Dosing  
> `vibration`: Weight value release speed (optional) — 0=Very fast, 1=Fast, 2=Reliable and fast, 3=Reliable, 4=Very reliable  
> `stability`: Ambient-condition optimization (optional) — 0=Very stable, 1=Stable, 2=Standard, 3=Unstable, 4=Very unstable, 5=Automatic  
> `weightUnit`: Output weighing unit (optional) — 0=Gram [g], 1=Kilogram [kg], 2=Ton [t], 3=Milligram [mg], 4=Microgram [µg], 5=Carat [ct], 6=Newton [N], 7=Pound avdp [lb], 8=Ounce avdp [oz], 9=Ounce troy [ozt], 10=Grain [GN], 11=Pennyweight [dwt], 12=Momme [mom], 13=Mesghal [msg], 14=Tael Hongkong [tlh], 15=Tael Singapore [tls], 16=Tael Taiwan [tlt], 17=Tical [tcl], 18=Tola [tola], 19=Baht [baht], 20=lb [oz], 21=Ton (short ton = 2000lb) [ton], 25=no unit, 26=Piece [PCS], 27=Percent [%], 28=Custom unit 1 [cu1], 29=Custom unit 2 [cu2], 30=Currency unit 1, 31=Currency unit 2  
> `autoZero`: Switch the auto-zero function on or off (optional)

#### WXS.terminateBalance
```json
{ "channel": "action", "data": { "category": "Device", "actionName": "WXS.terminateBalance", "parameters": {} } }
```
Terminates the connection to the balance.
