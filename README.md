# HLK-2412 for Home Assistant

Integrace pro **HLK-2412** Bluetooth Low Energy (BLE) mmWave radarové senzory s plnou podporou UART protokolu.

## Vlastnosti

- **Detekce pohybu a přítomnosti v reálném čase** pomocí mmWave radaru
- **UART Command Protocol** - komunikace přes Bluetooth s podporou příkazů
- **Engineering Mode** - automatické zapnutí režimu s detailními daty
- **Měření vzdálenosti** pro pohybující se a statické cíle
- **Měření energie detekce** pro analýzu kvality signálu
- **Automatické přepojení** při výpadku spojení

## Implementace

Integrace je postavena na **HLK-LD2412** UART protokolu (podobný LD2410, ale s rozdíly):
- **Frame Header**: `FDFCFBFA` (TX), `F4F3F2F1` (RX)
- **Frame Footer**: `04030201` (TX), `F8F7F6F5` (RX)
- **Command Codes** (LD2412 specifické):
  - Enable Config: `0x00FF`
  - End Config: `0x00FE`
  - Read Firmware: `0x00A0`
  - Read Basic Params: `0x0012`
- **Data Payload**: 7 bytes (target_state + distances + energies)
- **Bluetooth Characteristics**:
  - Notify: `0000fff1-0000-1000-8000-00805f9b34fb`
  - Write: `0000fff2-0000-1000-8000-00805f9b34fb`

## Entity (Binary Sensors)

🏠 **Occupancy** – celková přítomnost kombinující pohyb a statická data  
🏃 **Motion** – zapíná se při detekci pohybu  
🧍 **Static** – indikuje statickou přítomnost

## Entity (Sensors)

### Runtime Data
📏 **Moving distance** – vzdálenost k nejbližšímu pohybujícímu se cíli (cm)  
📍 **Still distance** – vzdálenost k nejbližšímu statickému cíli (cm)  
⚡ **Moving energy** – úroveň energie pohybujícího se cíle  
🔋 **Still energy** – úroveň energie statického cíle  
📏 **Detection distance** – vzdálenost detekce (cm)

### Diagnostic (Configuration)
🔧 **Firmware version** – verze firmware zařízení  
🚪 **Minimum gate** – minimální detekční brána  
🚪 **Maximum gate** – maximální detekční brána  
⏱️ **Unmanned duration** – doba do přepnutí na "unmanned" (sekundy)

## Instalace

```bash
# Zkopírujte složku do custom_components
cp -r hlk2412 /path/to/homeassistant/config/custom_components/

# Restartujte Home Assistant
```

### Krok za krokem:

1. Zkopírujte složku `hlk2412` do `config/custom_components/`
2. Restartujte Home Assistant
3. Přejděte na **Nastavení → Zařízení a služby**
4. Zařízení by mělo být **automaticky objeveno**
5. Nebo klikněte na **Přidat integraci** a vyhledejte "HLK-2412"

## Technické detaily

### UART Command Protocol

Integrace používá **LD2412** UART příkazy přes Bluetooth:

```python
# Command sekvence pro read-only operace
CMD_ENABLE_CFG = "00FF"      # 0x00FF - Zapnout konfigurační režim
CMD_READ_FIRMWARE = "00A0"   # 0x00A0 - Přečíst firmware verzi
CMD_READ_BASIC_PARAMS = "0012"  # 0x0012 - Min/max gate + unmanned duration
CMD_END_CFG = "00FE"         # 0x00FE - Ukončit konfigurační režim
```

**Poznámka**: LD2412 nepoužívá engineering mode command jako LD2410. Data přijímá automaticky v basic mode (type 0x02).

### Parsování dat (LD2412 Basic Payload - 7 bytů)

Data jsou přijímána v uplink framech typu 0x02 (basic target data):

```python
# Po F4 F3 F2 F1 (header) + length + 0x02 (type) + 0xAA:
target_state (1B)           # 0x00=none, 0x01=moving, 0x02=stationary, 0x03=both
moving_distance_cm (2B LE)  # Vzdálenost pohybujícího se cíle
moving_energy (1B)          # Energie pohybu
stationary_distance_cm (2B LE)  # Vzdálenost statického cíle
stationary_energy (1B)      # Energie statického cíle
# Footer: 0x55 0x00 + F8 F7 F6 F5
```

### Connection Management

- **Automatické přepojení** při ztrátě spojení
- **Disconnect Timer**: 8.5s pro úsporu baterie
- **Command Timeout**: 5s pro UART příkazy

## Řešení problémů

### Zařízení se nepřipojí
- Zkontrolujte, že je zařízení v dosahu Bluetooth
- Ujistěte se, že není připojeno k jinému zařízení
- Restartujte Home Assistant

### Žádná data
- Integrace automaticky povoluje Engineering Mode
- Zkontrolujte logy: `config/home-assistant.log`
- Povolte debug logging:

```yaml
logger:
  default: warning
  logs:
    custom_components.hlk2412: debug
```

### Pomalá odezva
- Použijte [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html)
- Přesuňte proxy blíž k senzoru

## Poznámky

- Integrace je **read-only** - nepodporuje změnu nastavení zařízení
- Založeno na LD2410 protokolu a struktuře
- Vyžaduje `bleak-retry-connector>=3.5.0`

## Dependencies

- `homeassistant.components.bluetooth`
- `homeassistant.components.bluetooth_adapters`
- `bleak-retry-connector>=3.5.0`

## Doporučené nastavení

Pro nejlepší výsledky:
- Použijte [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html)
- Umístěte proxy max 10m od senzoru
- Vyhněte se překážkám mezi proxy a senzorem
