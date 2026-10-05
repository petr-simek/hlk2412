"""Connection manager for HLK-2412."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time
from typing import TYPE_CHECKING

from bleak.exc import BleakError
from bleak_retry_connector import BLEAK_RETRY_EXCEPTIONS

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .device import OperationError

if TYPE_CHECKING:
    from bleak.backends.device import BLEDevice

    from .device import HLK2412Device

_LOGGER = logging.getLogger(__name__)

MIN_BACKOFF = 2.0
MAX_BACKOFF = 60.0
# How often the connected link is checked.
WATCHDOG_INTERVAL = 5.0
# No report frame for this long: module is probably stuck in config mode.
STALE_RECOVER_AFTER = 10.0
# No report frame for this long: the link is dead even if BLE says connected.
STALE_RECONNECT_AFTER = 30.0
# How long to wait for an advertisement when the device is out of range.
NOT_PRESENT_WAIT = 30.0

CONNECT_ERRORS = (*BLEAK_RETRY_EXCEPTIONS, BleakError, OperationError, TimeoutError)


class DataCoordinator:
    """Keep one HLK-2412 connected and healthy."""

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
        self._task: asyncio.Task | None = None
        self._unsub: Callable[[], None] | None = None
        self._advertised = asyncio.Event()

    @callback
    def async_start(self) -> Callable[[], None]:
        """Start the connection loop."""

        @callback
        def _async_update_ble_device(
            service_info: bluetooth.BluetoothServiceInfoBleak,
            change: bluetooth.BluetoothChange,
        ) -> None:
            """Track the best path (adapter/proxy) to the device."""
            self.ble_device = service_info.device
            self.device.ble_device = service_info.device
            self._advertised.set()

        self._unsub = bluetooth.async_register_callback(
            self.hass,
            _async_update_ble_device,
            bluetooth.BluetoothCallbackMatcher(
                address=self.ble_device.address, connectable=True
            ),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
        self._task = self.hass.async_create_background_task(
            self._run(), name=f"hlk2412-{self.ble_device.address}"
        )
        return self.async_stop

    @callback
    def async_stop(self) -> None:
        """Stop the connection loop."""
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._task:
            self._task.cancel()
            self._task = None

    async def _wait_for_advertisement(self) -> None:
        self._advertised.clear()
        try:
            async with asyncio.timeout(NOT_PRESENT_WAIT):
                await self._advertised.wait()
        except TimeoutError:
            pass

    async def _run(self) -> None:
        """Connect, watch the link and reconnect with backoff."""
        device = self.device
        address = self.ble_device.address
        backoff = MIN_BACKOFF
        failures = 0

        while True:
            if not device.is_connected:
                if not bluetooth.async_address_present(
                    self.hass, address, connectable=True
                ):
                    # Don't burn proxy connection slots on a device nobody hears.
                    await self._wait_for_advertisement()
                    continue
                try:
                    await device.connect()
                except Exception as ex:  # noqa: BLE001 - the loop must survive
                    failures += 1
                    if not isinstance(ex, CONNECT_ERRORS):
                        self.logger.exception(
                            "%s: unexpected error while connecting", self.device_name
                        )
                    else:
                        log = (
                            self.logger.warning if failures == 1 else self.logger.debug
                        )
                        log(
                            "%s: connect failed (%d), retry in %.0fs: %s",
                            self.device_name,
                            failures,
                            backoff,
                            ex,
                        )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF)
                    continue
                if failures > 1:
                    self.logger.info(
                        "%s: connected after %d failed attempts",
                        self.device_name,
                        failures,
                    )
                failures = 0
                backoff = MIN_BACKOFF

            if await device.wait_disconnected(WATCHDOG_INTERVAL):
                # Give the module/proxy a moment before reconnecting.
                await asyncio.sleep(MIN_BACKOFF)
                continue
            await self._check_stale()

    async def _check_stale(self) -> None:
        device = self.device
        if device.busy or not device.is_connected:
            return
        age = time.monotonic() - device.last_frame_time
        if age < STALE_RECOVER_AFTER:
            return
        if age < STALE_RECONNECT_AFTER:
            self.logger.debug(
                "%s: no data for %.0fs, leaving config mode", self.device_name, age
            )
            try:
                await device.end_config_mode()
            except CONNECT_ERRORS as ex:
                self.logger.debug("%s: end config failed: %s", self.device_name, ex)
            return
        self.logger.warning(
            "%s: no data for %.0fs, reconnecting", self.device_name, age
        )
        try:
            await device.disconnect()
        except Exception:  # noqa: BLE001
            self.logger.exception("%s: disconnect failed", self.device_name)


type ConfigEntryType = ConfigEntry[DataCoordinator]
