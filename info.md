## HLK-2412 mmWave Radar Integration

> ⚠️ **Work in Progress** - This integration is actively being developed.

Integration for **HLK-2412** Bluetooth Low Energy (BLE) mmWave radar sensors with full UART protocol support and configuration.

### Main Features

- ✅ **Motion and presence detection** in real-time
- ✅ **Engineering mode** with 26 gate energy sensors
- ✅ **Light level** (0-255) in engineering mode
- ✅ **Full configuration** - gates, sensitivity, polarity
- ✅ **Background calibration** - dynamic calibration
- ✅ **Factory reset** - restore factory settings

### Entities

**4 Binary Sensors:**
- Occupancy (presence)
- Motion
- Static (stationary presence)
- Calibration active

**33+ Sensors:**
- 5 runtime sensors (distances, energy levels)
- 26 gate energy sensors (engineering mode)
- Light level (engineering mode)
- Diagnostic sensors

**5 Buttons:**
- Toggle engineering mode
- Start calibration
- Restart module
- Factory reset
- Apply configuration

**31 Number entities:**
- Min/max gate (0-13)
- Unmanned duration (0-65535s)
- 14 motion sensitivity values (0-255)
- 14 motionless sensitivity values (0-255)

**1 Select entity:**
- Out pin polarity

### Configuration

1. Change values in number/select entities
2. Click **Apply configuration**
3. All settings are written to device at once

### Requirements

- Home Assistant with Bluetooth support
- Recommended: ESPHome Bluetooth Proxy for better range
