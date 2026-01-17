"""Button platform for HLK-2412."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ConfigEntryType, DataCoordinator
from .entity import HLK2412Entity

BUTTON_TYPES: dict[str, ButtonEntityDescription] = {
    "toggle_engineering": ButtonEntityDescription(
        key="toggle_engineering",
        name="Toggle engineering mode",
        entity_category=EntityCategory.CONFIG,
    ),
    "start_calibration": ButtonEntityDescription(
        key="start_calibration",
        name="Start background calibration",
        entity_category=EntityCategory.CONFIG,
    ),
    "restart_module": ButtonEntityDescription(
        key="restart_module",
        name="Restart module",
        entity_category=EntityCategory.CONFIG,
    ),
    "factory_reset": ButtonEntityDescription(
        key="factory_reset",
        name="Factory reset",
        entity_category=EntityCategory.CONFIG,
    ),
    "apply_config": ButtonEntityDescription(
        key="apply_config",
        name="Apply configuration",
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
        if self.entity_description.key == "toggle_engineering":
            current_mode = self.coordinator.device.data.get("engineering_mode", False)
            if current_mode:
                await self.coordinator.device.disable_engineering_mode()
            else:
                await self.coordinator.device.enable_engineering_mode()
        elif self.entity_description.key == "start_calibration":
            await self.coordinator.device.start_calibration()
        elif self.entity_description.key == "restart_module":
            await self.coordinator.device.restart_module()
        elif self.entity_description.key == "factory_reset":
            await self.coordinator.device.factory_reset()
        elif self.entity_description.key == "apply_config":
            device = self.coordinator.device
            
            # Write basic parameters
            min_gate = device.data.get("min_gate", 0)
            max_gate = device.data.get("max_gate", 13)
            unmanned_duration = device.data.get("unmanned_duration", 5)
            out_pin_polarity = device.data.get("out_pin_polarity", 0)
            await device.write_basic_params(
                min_gate, max_gate, unmanned_duration, out_pin_polarity
            )
            
            # Write motion sensitivity for all gates
            motion_sensitivities = [
                device.data.get(f"motion_sensitivity_gate_{i}", 50) for i in range(14)
            ]
            await device.write_motion_sensitivity(motion_sensitivities)
            
            # Write motionless sensitivity for all gates
            motionless_sensitivities = [
                device.data.get(f"motionless_sensitivity_gate_{i}", 50) for i in range(14)
            ]
            await device.write_motionless_sensitivity(motionless_sensitivities)
