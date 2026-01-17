# HLK-2412 for Home Assistant

> ⚠️ **Work in Progress** - This integration is actively being developed. Some features may be incomplete or subject to change.

Integration for **HLK-2412** Bluetooth Low Energy (BLE) mmWave radar sensors with full UART protocol support.

## Features

- **Real-time motion and presence detection** using mmWave radar
- **UART Command Protocol** - Bluetooth communication with command support
- **Engineering Mode** - toggle between basic and engineering mode
- **Distance measurement** for moving and static targets (cm)
- **Detection energy measurement** for each gate (0-255)
- **26 gate energy sensors** - 13 for motion + 13 for static detection
- **Light level sensor** - ambient light level (0-255) in engineering mode
- **Device configuration** - configure gates, sensitivity, polarity
- **Background calibration** - dynamic detection calibration
- **Factory reset** - restore factory settings
- **Automatic reconnection** on connection loss

## Entity

### Binary Sensors

🏠 **Occupancy** – overall presence combining motion and static data  
🏃 **Motion** – turns on when motion is detected  
🧍 **Static** – indicates static presence  
🔄 **Calibration active** – indicates ongoing background calibration

### Sensors

#### Runtime Data
📏 **Moving distance** – distance to nearest moving target (cm)  
📍 **Still distance** – distance to nearest static target (cm)  
⚡ **Moving energy** – energy level of moving target  
🔋 **Still energy** – energy level of static target  
📏 **Detection distance** – detection distance (cm)  
💡 **Light level** – ambient light level 0-255 (engineering mode only)

#### Engineering Mode - Gate Energies (0-13)
📊 **Move gate 0-13 energy** – motion energy for each gate (0-255)  
📊 **Static gate 0-13 energy** – static detection energy for each gate (0-255)

#### Diagnostic
🔧 **Firmware version** – device firmware version  
🚪 **Minimum gate** – minimum detection gate  
🚪 **Maximum gate** – maximum detection gate  
📊 **Data mode** – current mode (Basic/Engineering)

### Buttons

🔘 **Toggle engineering mode** – switch between basic and engineering mode  
🔘 **Start background calibration** – start dynamic background calibration (~10s)  
🔘 **Restart module** – restart the module  
🔘 **Factory reset** – restore factory settings and restart module  
🔘 **Apply configuration** – write all settings to device

### Number Entities (Configuration)

📏 **Minimum gate** (0-13) – minimum gate for detection  
📏 **Maximum gate** (0-13) – maximum gate for detection  
⏱️ **Unmanned duration** (0-65535s) – time before switching to "unmanned"  
📊 **Motion sensitivity gate 0-13** (0-255) – motion sensitivity for each gate  
📊 **Motionless sensitivity gate 0-13** (0-255) – static detection sensitivity for each gate


## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Click on **Integrations**
3. Click the **⋮** button in the top right corner
4. Select **Custom repositories**
5. Enter URL: `https://github.com/petr-simek/hlk2412`
6. Category: **Integration**
7. Click **Add**
8. Search for "HLK-2412 mmWave Radar" and click **Download**
9. Restart Home Assistant

### Manual Installation

```bash
# Copy the folder to custom_components
cp -r custom_components/hlk2412 /path/to/homeassistant/config/custom_components/

# Restart Home Assistant
```

### After Installation:

1. Go to **Settings → Devices & Services**
2. Device should be **automatically discovered** via Bluetooth
3. Or click **Add Integration** and search for "HLK-2412"
4. Select device from the list and complete configuration

## Technical Details

The integration is based on **HLK-LD2412** UART protocol over Bluetooth:
- Frame headers: `FDFCFBFA` (TX), `F4F3F2F1` (RX)
- Frame footers: `04030201` (TX), `F8F7F6F5` (RX)
- Supports both basic (0x02) and engineering (0x01) data modes
- Automatic connection management with 8.5s disconnect timer
- Command timeout: 5s for UART commands

## Troubleshooting

### Device Won't Connect
- Check that device is within Bluetooth range
- Make sure it's not connected to another device
- Restart Home Assistant

### No Data
- Integration automatically enables Engineering Mode
- Check logs: `config/home-assistant.log`
- Enable debug logging:

```yaml
logger:
  default: warning
  logs:
    custom_components.hlk2412: debug
```

### Slow Response
- Use [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html)
- Move proxy closer to sensor

## Device Configuration

The integration allows complete device configuration:

1. **Change values** in number/select entities as needed
2. **Click "Apply configuration"** - writes all settings at once:
   - Basic parameters (min/max gate, unmanned duration, polarity)
   - Motion sensitivity for all 14 gates
   - Motionless sensitivity for all 14 gates

Settings are stored in the device and preserved after restart.

## Dependencies

- `homeassistant.components.bluetooth`
- `homeassistant.components.bluetooth_adapters`
- `bleak-retry-connector>=3.5.0`

## Recommended Setup

For best results:
- Use [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html)
- Place proxy within 10m of sensor
- Avoid obstacles between proxy and sensor