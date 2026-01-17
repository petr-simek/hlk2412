"""Base entity for HLK-2412."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.entity import Entity
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER
from .coordinator import DataCoordinator


class HLK2412Entity(Entity):
    """Base entity for HLK-2412 devices."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: DataCoordinator) -> None:
        """Initialize the entity."""
        self.coordinator = coordinator
        self._address = coordinator.ble_device.address
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.base_unique_id)},
            connections={(dr.CONNECTION_BLUETOOTH, self._address)},
            manufacturer=MANUFACTURER,
            model="HLK-LD2412",
            name=coordinator.device_name,
        )

    @property
    def data(self) -> dict[str, Any]:
        """Return device data."""
        return self.coordinator.device.data

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.device.is_connected

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self.async_on_remove(
            self.coordinator.device.subscribe(self._handle_coordinator_update)
        )
        await super().async_added_to_hass()

    def _handle_coordinator_update(self) -> None:
        """Handle data update."""
        self.async_write_ha_state()
