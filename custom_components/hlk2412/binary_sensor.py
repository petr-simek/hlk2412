"""Binary sensor platform for HLK-2412."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ConfigEntryType
from .entity import HLK2412Entity

BINARY_SENSOR_TYPES: dict[str, BinarySensorEntityDescription] = {
    "occupancy": BinarySensorEntityDescription(
        key="occupancy",
        name="Occupancy",
        icon="mdi:motion-sensor",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
    ),
    "motion": BinarySensorEntityDescription(
        key="moving",
        name="Motion",
        icon="mdi:run",
        device_class=BinarySensorDeviceClass.MOVING,
    ),
    "static": BinarySensorEntityDescription(
        key="stationary",
        name="Static",
        icon="mdi:human",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
    ),
    "calibration_active": BinarySensorEntityDescription(
        key="calibration_active",
        name="Calibration active",
        icon="mdi:target",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntryType,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        HLK2412BinarySensor(coordinator, description)
        for description in BINARY_SENSOR_TYPES.values()
    )


class HLK2412BinarySensor(HLK2412Entity, BinarySensorEntity):
    """Binary sensor for HLK-2412."""

    def __init__(
        self,
        coordinator,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.base_unique_id}-{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        return self.data.get(self.entity_description.key)
