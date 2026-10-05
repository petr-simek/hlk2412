"""Button platform for HLK-2412."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ConfigEntryType, DataCoordinator
from .entity import HLK2412Entity

BUTTON_TYPES: dict[str, ButtonEntityDescription] = {
    "toggle_engineering": ButtonEntityDescription(
        key="toggle_engineering",
        name="Toggle engineering mode",
        icon="mdi:tune",
        entity_category=EntityCategory.CONFIG,
    ),
    "start_calibration": ButtonEntityDescription(
        key="start_calibration",
        name="Start background calibration",
        icon="mdi:target",
        entity_category=EntityCategory.CONFIG,
    ),
    "restart_module": ButtonEntityDescription(
        key="restart_module",
        name="Restart module",
        icon="mdi:restart",
        entity_category=EntityCategory.CONFIG,
    ),
    "factory_reset": ButtonEntityDescription(
        key="factory_reset",
        name="Factory reset",
        icon="mdi:factory",
        entity_category=EntityCategory.CONFIG,
    ),
    "apply_config": ButtonEntityDescription(
        key="apply_config",
        name="Apply configuration",
        icon="mdi:content-save",
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
        device = self.coordinator.device
        key = self.entity_description.key
        if key == "toggle_engineering":
            if device.data.get("engineering_mode", False):
                ok = await device.disable_engineering_mode()
            else:
                ok = await device.enable_engineering_mode()
        elif key == "start_calibration":
            ok = await device.start_calibration()
        elif key == "restart_module":
            ok = await device.restart_module()
        elif key == "factory_reset":
            ok = await device.factory_reset()
        elif key == "apply_config":
            data = device.data
            ok = await device.write_basic_params(
                data.get("min_gate", 1),
                data.get("max_gate", 13),
                data.get("unmanned_duration", 5),
                data.get("out_pin_polarity", 0),
            )
            ok &= await device.write_motion_sensitivity(
                [data.get(f"motion_sensitivity_gate_{i}", 50) for i in range(14)]
            )
            ok &= await device.write_motionless_sensitivity(
                [data.get(f"motionless_sensitivity_gate_{i}", 50) for i in range(14)]
            )
        else:
            return
        if not ok:
            raise HomeAssistantError(
                f"{self.entity_description.name} failed, see the log for details"
            )
