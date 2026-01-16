"""Data update coordinator for HLK-2412."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from bleak_retry_connector import BLEAK_RETRY_EXCEPTIONS

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
        retry_count: int,
        connect_interval: float = 30.0,
    ) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.logger = logger
        self.ble_device = ble_device
        self.device = device
        self.device_name = device_name
        self.base_unique_id = base_unique_id
        self.retry_count = retry_count
        self.connect_interval = connect_interval
        self._unsub: callable | None = None
        self._connect_task: asyncio.Task | None = None

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

        self._connect_task = self.hass.async_create_task(self._connection_loop())

        def _async_stop() -> None:
            if self._connect_task:
                self._connect_task.cancel()
            if self._unsub:
                self._unsub()

        return _async_stop

    async def _connection_loop(self) -> None:
        """Keep the device connected with retries."""
        attempt = 0
        delay = 1.0
        max_delay = 10.0

        while True:
            try:
                if not self.device.is_connected:
                    await self.device.update()
                    attempt = 0
                    delay = 1.0
            except BLEAK_RETRY_EXCEPTIONS as ex:
                attempt += 1
                self.logger.debug("Retryable BLE error: %s", ex)
            except Exception as ex:  # noqa: BLE001
                attempt += 1
                self.logger.warning("Failed to connect to %s: %s", self.device_name, ex)

            if attempt >= self.retry_count:
                attempt = 0
                delay = 1.0
                await asyncio.sleep(self.connect_interval)
            elif attempt > 0:
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)
            else:
                await asyncio.sleep(self.connect_interval)


type ConfigEntryType = ConfigEntry[DataCoordinator]
