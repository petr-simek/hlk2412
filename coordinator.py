"""Data update coordinator for HLK-2412."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

if TYPE_CHECKING:
    from bleak.backends.device import BLEDevice
    from .device import HLK2412Device

_LOGGER = logging.getLogger(__name__)


class DataCoordinator:
    """Class to manage HLK-2412 data updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        ble_device: BLEDevice,
        device: HLK2412Device,
        base_unique_id: str,
        device_name: str,
    ) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.logger = logger
        self.ble_device = ble_device
        self.device = device
        self.device_name = device_name
        self.base_unique_id = base_unique_id
        self._unsub = None

    def async_start(self) -> callable:
        """Start the coordinator."""
        
        @callback
        def _async_update_ble_device(
            service_info: bluetooth.BluetoothServiceInfoBleak,
            change: bluetooth.BluetoothChange,
        ) -> None:
            """Update BLE device from bluetooth scanner."""
            self.ble_device = service_info.device
            self.device.ble_device = service_info.device
        
        self._unsub = bluetooth.async_register_callback(
            self.hass,
            _async_update_ble_device,
            bluetooth.BluetoothCallbackMatcher(address=self.ble_device.address),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        
        return self._unsub


type ConfigEntryType = ConfigEntry[DataCoordinator]
