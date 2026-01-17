"""Sensor platform for HLK-2412."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ConfigEntryType
from .entity import HLK2412Entity

SENSOR_TYPES: dict[str, SensorEntityDescription] = {
    "move_distance": SensorEntityDescription(
        key="move_distance_cm",
        name="Moving distance",
        icon="mdi:arrow-expand-horizontal",
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "still_distance": SensorEntityDescription(
        key="still_distance_cm",
        name="Still distance",
        icon="mdi:ruler",
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "move_energy": SensorEntityDescription(
        key="move_energy",
        name="Moving energy",
        icon="mdi:lightning-bolt",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "still_energy": SensorEntityDescription(
        key="still_energy",
        name="Still energy",
        icon="mdi:battery",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "firmware_version": SensorEntityDescription(
        key="firmware_version",
        name="Firmware version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "min_gate": SensorEntityDescription(
        key="min_gate",
        name="Minimum gate",
        icon="mdi:gate-arrow-right",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "max_gate": SensorEntityDescription(
        key="max_gate",
        name="Maximum gate",
        icon="mdi:gate-arrow-right",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "data_mode": SensorEntityDescription(
        key="data_type",
        name="Data mode",
        icon="mdi:view-dashboard",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "light_level": SensorEntityDescription(
        key="light_level",
        name="Light level",
        icon="mdi:brightness-7",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
    ),
}

# Add gate energy sensors for engineering mode (13 gates)
for gate_num in range(14):
    SENSOR_TYPES[f"move_gate_{gate_num}"] = SensorEntityDescription(
        key=f"move_gate_{gate_num}_energy",
        name=f"Move gate {gate_num} energy",
        icon="mdi:pulse",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    SENSOR_TYPES[f"static_gate_{gate_num}"] = SensorEntityDescription(
        key=f"static_gate_{gate_num}_energy",
        name=f"Static gate {gate_num} energy",
        icon="mdi:signal-variant",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntryType,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        HLK2412Sensor(coordinator, description)
        for description in SENSOR_TYPES.values()
    )


class HLK2412Sensor(HLK2412Entity, SensorEntity):
    """Sensor for HLK-2412."""

    def __init__(
        self,
        coordinator,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.base_unique_id}-{description.key}"

    @property
    def native_value(self) -> int | str | None:
        """Return the state of the sensor."""
        return self.data.get(self.entity_description.key)
