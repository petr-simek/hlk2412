"""Integration for HLK-2412 radar sensors."""

import logging
from pathlib import Path

from homeassistant.components import bluetooth
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_MAC, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import CONF_RETRY_COUNT, DEFAULT_RETRY_COUNT, DOMAIN
from .coordinator import ConfigEntryType, DataCoordinator
from .device import HLK2412Device
from .websocket import async_register as async_register_websocket

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
]

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
CARD_URL = "/hlk2412/hlk2412-card.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the Lovelace card and its websocket API."""
    card = Path(__file__).parent / "frontend" / "hlk2412-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(card), cache_headers=False)]
    )
    # File mtime in the URL so browsers pick up a changed card.
    mtime = await hass.async_add_executor_job(lambda: int(card.stat().st_mtime))
    add_extra_js_url(hass, f"{CARD_URL}?v={mtime}")
    async_register_websocket(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntryType) -> bool:
    """Set up HLK-2412 from a config entry."""
    assert entry.unique_id is not None

    if CONF_ADDRESS not in entry.data and CONF_MAC in entry.data:
        mac = entry.data[CONF_MAC]
        if "-" not in mac:
            mac = dr.format_mac(mac)
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_ADDRESS: mac},
        )

    if not entry.options:
        hass.config_entries.async_update_entry(
            entry,
            options={CONF_RETRY_COUNT: DEFAULT_RETRY_COUNT},
        )

    address: str = entry.data[CONF_ADDRESS]

    ble_device = bluetooth.async_ble_device_from_address(
        hass, address.upper(), connectable=True
    )
    if not ble_device:
        raise ConfigEntryNotReady(
            f"Could not find HLK-2412 device with address {address}"
        )

    retry_count = entry.options.get(CONF_RETRY_COUNT, DEFAULT_RETRY_COUNT)
    device = HLK2412Device(ble_device=ble_device, max_attempts=retry_count)

    coordinator = entry.runtime_data = DataCoordinator(
        hass,
        _LOGGER,
        ble_device,
        device,
        entry.unique_id,
        entry.title,
    )

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.unique_id)},
        name=entry.title,
        manufacturer="HiLink",
        model="HLK-LD2412",
        connections={(dr.CONNECTION_BLUETOOTH, address)},
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start connecting only once entities exist, so they see the first data.
    entry.async_on_unload(coordinator.async_start())

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = entry.runtime_data
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Stop the reconnect loop before disconnecting, or it would reconnect.
        coordinator.async_stop()
        await coordinator.device.disconnect()
    return unload_ok
