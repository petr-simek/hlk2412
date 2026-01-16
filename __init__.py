"""Integration for HLK-2412 radar sensors."""

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_MAC, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import CONF_RETRY_COUNT, DEFAULT_RETRY_COUNT, DOMAIN
from .coordinator import ConfigEntryType, DataCoordinator
from .device import HLK2412Device

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]

_LOGGER = logging.getLogger(__name__)


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

    device = HLK2412Device(ble_device=ble_device)

    retry_count = entry.options.get(CONF_RETRY_COUNT, DEFAULT_RETRY_COUNT)

    coordinator = entry.runtime_data = DataCoordinator(
        hass,
        _LOGGER,
        ble_device,
        device,
        entry.unique_id,
        entry.title,
        retry_count,
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

    entry.async_on_unload(coordinator.async_start())

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    try:
        await device.update()
    except Exception as ex:
        _LOGGER.warning("Initial connection failed, will retry: %s", ex)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    device = entry.runtime_data.device
    await device.disconnect()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
