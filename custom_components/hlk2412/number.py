"""Number platform for HLK-2412."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ConfigEntryType, DataCoordinator
from .entity import HLK2412Entity

NUMBER_TYPES: dict[str, NumberEntityDescription] = {
    "min_gate": NumberEntityDescription(
        key="min_gate",
        name="Minimum gate",
        icon="mdi:gate",
        native_min_value=1,
        native_max_value=14,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
    ),
    "max_gate": NumberEntityDescription(
        key="max_gate",
        name="Maximum gate",
        icon="mdi:gate",
        native_min_value=1,
        native_max_value=14,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
    ),
    "unmanned_duration": NumberEntityDescription(
        key="unmanned_duration",
        name="Unmanned duration",
        icon="mdi:timer",
        native_min_value=0,
        native_max_value=65535,
        native_step=1,
        native_unit_of_measurement="s",
        entity_category=EntityCategory.CONFIG,
    ),
}

# Add motion sensitivity for each of the 14 gates (0-13)
for gate in range(14):
    NUMBER_TYPES[f"motion_sensitivity_gate_{gate}"] = NumberEntityDescription(
        key=f"motion_sensitivity_gate_{gate}",
        name=f"Motion sensitivity gate {gate}",
        icon="mdi:sine-wave",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
    )

# Add motionless sensitivity for each of the 14 gates (0-13)
for gate in range(14):
    NUMBER_TYPES[f"motionless_sensitivity_gate_{gate}"] = NumberEntityDescription(
        key=f"motionless_sensitivity_gate_{gate}",
        name=f"Motionless sensitivity gate {gate}",
        icon="mdi:sine-wave",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntryType,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        HLK2412Number(coordinator, description)
        for description in NUMBER_TYPES.values()
    )


class HLK2412Number(HLK2412Entity, NumberEntity):
    """Number entity for HLK-2412."""

    def __init__(
        self,
        coordinator: DataCoordinator,
        description: NumberEntityDescription,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.base_unique_id}-{description.key}"

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.data.get(self.entity_description.key)

    async def async_set_native_value(self, value: float) -> None:
        """Update the value."""
        self.coordinator.device._data[self.entity_description.key] = int(value)
        self.coordinator.device._notify_callbacks()
