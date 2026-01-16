# HLK-LD2412 Protocol Implementation Notes

## Klíčové rozdíly mezi LD2410 a LD2412

### 1. Command Codes (KRITICKÉ!)

**LD2410:**
- Enable Config: `0xFF00` (command word)
- End Config: `0xFE00`

**LD2412:**
- Enable Config: `0x00FF` ✅
- End Config: `0x00FE` ✅
- Read Firmware: `0x00A0` ✅
- Read Basic Params: `0x0012` ✅
- Read Resolution: `0x0011`
- Read Motion Sensitivity: `0x0013`
- Read Motionless Sensitivity: `0x0014`

### 2. Data Frame Payload

**LD2412 Basic Data (type 0x02) - 7 bytů:**
```
Byte 0: target_state
  0x00 = none
  0x01 = moving
  0x02 = stationary
  0x03 = both
Byte 1-2: moving_distance_cm (LE)
Byte 3: moving_energy
Byte 4-5: stationary_distance_cm (LE)
Byte 6: stationary_energy
```

**LD2410 Basic Data - 9 bytů (pravděpodobně):**
- Status + distances + energies + detect_distance

### 3. Engineering Mode

**LD2410:**
- Command: `0x6200` pro enable
- Posílá engineering frames s energiemi pro gates 0-8

**LD2412:**
- **NEMÁ** explicitní enable engineering command
- Basic mode (0x02) posílá data automaticky
- Engineering frames (0x01) zahrnují více gate (0-14)

### 4. Frame Structure (SPOLEČNÉ)

```
Command/ACK Frame:
  Header: FD FC FB FA
  Length: 2B LE
  Command Word: 2B LE
  Value: N bytes
  Footer: 04 03 02 01

Data Report Frame:
  Header: F4 F3 F2 F1
  Length: 2B LE
  Type: 1B (0x02=basic, 0x01=engineering)
  0xAA: 1B (fixed)
  Payload: N bytes
  0x55 0x00: 2B (tail)
  Footer: F8 F7 F6 F5
```

### 5. Read-Only Command Sequence

```python
# Správná sekvence pro čtení z LD2412:
1. Send: Enable Config (0x00FF + 0x0001)
2. Wait: ACK with status
3. Send: Read Firmware (0x00A0)
4. Wait: ACK with FW data
5. Send: End Config (0x00FE)
6. Wait: ACK
7. Listen: Continuous data reports (type 0x02)
```

## Implementované změny

### device.py
- ✅ Opraveny command kódy (byte swap)
- ✅ Odstraněn engineering mode enable
- ✅ Přidáno čtení firmware verze
- ✅ Aktualizován parsing na 7-byte LD2412 payload
- ✅ Ověření data_type (0x01, 0x02)

### README.md
- ✅ Aktualizována dokumentace protokolu
- ✅ Správné command kódy
- ✅ Detailní popis 7-byte payloadu

## Testování

Po instalaci očekávané chování:
1. Připojení přes Bluetooth
2. Odeslání Enable Config + Read FW + End Config
3. Log: "HLK-2412: Connected, receiving basic data..."
4. Příjem continuous data frames typu 0x02
5. Real-time aktualizace sensorů

## Debugging

Pokud nefunguje:
```yaml
# configuration.yaml
logger:
  logs:
    custom_components.hlk2412: debug
```

Očekávané logy:
```
Connecting to HLK-2412...
Connected to HLK-2412
Sending command: 00FF0001
Command response: 0000...
Sending command: 00A0
Command response: 00002412...  # fw_type = 0x2412
HLK-2412: Firmware type: 0x2412
HLK-2412: Connected, receiving basic data...
```
