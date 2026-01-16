"""Config flow for HLK-2412 integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def format_unique_id(address: str) -> str:
    """Format the unique ID for a device."""
    return address.replace(":", "").lower()


def short_address(address: str) -> str:
    """Convert a Bluetooth address to a short address."""
    results = address.replace("-", ":").split(":")
    return f"{results[-2].upper()}{results[-1].upper()}"[-4:]


class HLK2412ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HLK-2412."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}
        self._discovered_device: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the bluetooth discovery step."""
        _LOGGER.debug("Discovered bluetooth device: %s", discovery_info.as_dict())
        await self.async_set_unique_id(format_unique_id(discovery_info.address))
        self._abort_if_unique_id_configured()
        
        self._discovered_device = discovery_info
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovery."""
        assert self._discovered_device is not None
        
        if user_input is not None:
            return self._create_entry_from_device(self._discovered_device)

        self._set_confirm_only()
        placeholders = {
            "name": f"HLK-2412_{short_address(self._discovered_device.address)}"
        }
        self.context["title_placeholders"] = placeholders
        
        return self.async_show_form(
            step_id="confirm",
            description_placeholders=placeholders,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step to pick discovered device."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            discovery_info = self._discovered_devices[address]
            await self.async_set_unique_id(
                format_unique_id(address), raise_on_progress=False
            )
            self._abort_if_unique_id_configured()
            return self._create_entry_from_device(discovery_info)

        current_addresses = self._async_current_ids()
        for discovery_info in async_discovered_service_info(self.hass, connectable=True):
            address = discovery_info.address
            if format_unique_id(address) in current_addresses:
                continue
            if discovery_info.name and "HLK" in discovery_info.name.upper():
                self._discovered_devices[address] = discovery_info

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: f"{info.name or 'HLK-2412'}_{short_address(address)}"
                            for address, info in self._discovered_devices.items()
                        }
                    ),
                }
            ),
        )

    def _create_entry_from_device(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Create a config entry from a discovered device."""
        name = f"HLK-2412_{short_address(discovery_info.address)}"
        return self.async_create_entry(
            title=name,
            data={
                CONF_ADDRESS: discovery_info.address,
            },
        )
