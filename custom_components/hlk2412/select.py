"""Select platform for HLK-2412."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ConfigEntryType, DataCoordinator
from .entity import HLK2412Entity

SELECT_TYPES: dict[str, SelectEntityDescription] = {
    "out_pin_polarity": SelectEntityDescription(
        key="out_pin_polarity",
        name="Out pin polarity",
        options=["High when occupied", "Low when occupied"],
        entity_category=EntityCategory.CONFIG,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntryType,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        HLK2412Select(coordinator, description)
        for description in SELECT_TYPES.values()
    )


class HLK2412Select(HLK2412Entity, SelectEntity):
    """Select entity for HLK-2412."""

    def __init__(
        self,
        coordinator: DataCoordinator,
        description: SelectEntityDescription,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.base_unique_id}-{description.key}"

    @property
    def current_option(self) -> str | None:
        """Return the current option."""
        polarity = self.data.get(self.entity_description.key)
        if polarity is None:
            return None
        # 0 = high when occupied, 1 = low when occupied
        return "High when occupied" if polarity == 0 else "Low when occupied"

    async def async_select_option(self, option: str) -> None:
        """Update the option."""
        polarity = 0 if option == "High when occupied" else 1
        self.coordinator.device._data[self.entity_description.key] = polarity
        self.coordinator.device._notify_callbacks()
