"""Button platform for HLK-2412."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ConfigEntryType, DataCoordinator
from .entity import HLK2412Entity

BUTTON_TYPES: dict[str, ButtonEntityDescription] = {
    "enable_engineering": ButtonEntityDescription(
        key="enable_engineering",
        name="Enable engineering mode",
        entity_category=EntityCategory.CONFIG,
    ),
    "disable_engineering": ButtonEntityDescription(
        key="disable_engineering",
        name="Disable engineering mode",
        entity_category=EntityCategory.CONFIG,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntryType,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        HLK2412Button(coordinator, description)
        for description in BUTTON_TYPES.values()
    )


class HLK2412Button(HLK2412Entity, ButtonEntity):
    """Button for HLK-2412."""

    def __init__(
        self,
        coordinator: DataCoordinator,
        description: ButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.base_unique_id}-{description.key}"

    async def async_press(self) -> None:
        """Handle button press."""
        if self.entity_description.key == "enable_engineering":
            await self.coordinator.device.enable_engineering_mode()
        elif self.entity_description.key == "disable_engineering":
            await self.coordinator.device.disable_engineering_mode()
