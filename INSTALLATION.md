# Instalace HLK-2412 Custom Component

## Rychlý start

```bash
# Z root adresáře projektu
cp -r hlk2412 /path/to/homeassistant/config/custom_components/
```

## Detailní postup

### 1. Zkopírování souborů

Máte několik možností:

**Option A: Přímé kopírování**
```bash
cp -r /Users/petr.simek/git/doma/core/hlk2412 /Users/petr.simek/git/doma/core/config/custom_components/
```

**Option B: Vytvoření symbolického linku** (pro vývoj)
```bash
ln -s /Users/petr.simek/git/doma/core/hlk2412 /Users/petr.simek/git/doma/core/config/custom_components/hlk2412
```

### 2. Struktura souborů

Po instalaci by měla být struktura následující:

```
config/
└── custom_components/
    └── hlk2412/
        ├── __init__.py
        ├── binary_sensor.py
        ├── config_flow.py
        ├── const.py
        ├── coordinator.py
        ├── device.py
        ├── entity.py
        ├── manifest.json
        ├── sensor.py
        ├── strings.json
        └── README.md
```

### 3. Restart Home Assistant

```bash
# Přes UI: Nastavení → Systém → Restartovat

# Nebo přes příkazovou řádku:
ha core restart
```

### 4. Přidání integrace

Po restartu:
1. Jděte do **Nastavení → Zařízení a služby**
2. Klikněte na **+ Přidat integraci**
3. Vyhledejte "HLK-2412"
4. Pokud je zařízení v dosahu, mělo by být **automaticky objeveno**

## Verifikace instalace

### Kontrola logů

```bash
# Povolte debug logging v configuration.yaml
logger:
  default: warning
  logs:
    custom_components.hlk2412: debug

# Pak restartujte a sledujte logy
tail -f config/home-assistant.log | grep hlk2412
```

### Očekávaný výstup

```
[custom_components.hlk2412] Connecting to HLK-2412...
[custom_components.hlk2412] Connected to HLK-2412
[custom_components.hlk2412] Sending command: FF000001
[custom_components.hlk2412] Command response: 0000...
[custom_components.hlk2412] HLK-2412: Engineering mode enabled, receiving data...
```

## Troubleshooting

### "Failed to connect to device"
- Zkontrolujte dosah Bluetooth
- Ujistěte se, že zařízení není připojeno jinde
- Zkontrolujte, že máte bluetooth adapter

### "Command timeout"
- Zařízení je mimo dosah
- Bluetooth interference
- Zkuste použít ESPHome Bluetooth Proxy

### "Integration not found"
- Zkontrolujte, že složka je v `custom_components/`
- Ověřte, že `manifest.json` existuje
- Restartujte Home Assistant znovu

## Odinstalace

```bash
# Smazat integraci z UI
# Pak smazat soubory
rm -rf config/custom_components/hlk2412

# Restart Home Assistant
ha core restart
```

## Aktualizace

```bash
# Backup starší verze (optional)
cp -r config/custom_components/hlk2412 config/custom_components/hlk2412.backup

# Zkopírovat novou verzi
cp -r hlk2412 config/custom_components/

# Restart
ha core restart
```
