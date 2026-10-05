"""Connection manager for HLK-2412."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
import logging
import time
from typing import TYPE_CHECKING

from bleak.exc import BleakError
from bleak_retry_connector import BLEAK_RETRY_EXCEPTIONS

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

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
# Retry reading firmware/config if it failed right after connecting.
INFO_RETRY_INTERVAL = 30.0
# Engineering mode (per-gate energies) is on only while a card is open: it adds
# 28 sensor updates per frame. Switched off this long after the last viewer left.
VIEWER_GRACE = 60.0

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
        entry_id: str,
    ) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.logger = logger
        self.ble_device = ble_device
        self.device = device
        self.device_name = device_name
        self.base_unique_id = base_unique_id
        self.entry_id = entry_id
        self._task: asyncio.Task | None = None
        self._unsub: Callable[[], None] | None = None
        self._advertised = asyncio.Event()
        self._last_info_attempt = 0.0
        self._scanner_names: dict[str, str] = {}
        self._viewers = 0
        # Engineering mode is ours to switch off (also left on from a previous run).
        self._auto_engineering = True
        # The user switched it off while watching; respected until all viewers leave.
        self._user_disabled = False
        self._engineering_task: asyncio.Task | None = None

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
        if self._engineering_task:
            self._engineering_task.cancel()
            self._engineering_task = None

    @callback
    def async_add_viewer(self) -> Callable[[], None]:
        """Register an open card; returns the callback to unregister it."""
        self._viewers += 1
        self._schedule_engineering()
        removed = False

        @callback
        def remove() -> None:
            nonlocal removed
            if removed:
                return
            removed = True
            self._viewers -= 1
            self._schedule_engineering()

        return remove

    @callback
    def async_engineering_set_by_user(self, enable: bool) -> None:
        """Engineering mode was switched explicitly; stop managing it."""
        self._auto_engineering = False
        self._user_disabled = not enable

    @callback
    def _schedule_engineering(self) -> None:
        if self._engineering_task:
            self._engineering_task.cancel()
        self._engineering_task = self.hass.async_create_background_task(
            self._apply_engineering(), name=f"hlk2412-eng-{self.ble_device.address}"
        )

    async def _apply_engineering(self) -> None:
        """Engineering on while somebody watches, off after VIEWER_GRACE."""
        want = self._viewers > 0
        if not want:
            await asyncio.sleep(VIEWER_GRACE)
            self._user_disabled = False
        device = self.device
        if not device.is_connected:
            return  # applied again after reconnecting
        if want == bool(device.data.get("engineering_mode")):
            return
        if want and self._user_disabled:
            return
        if not want and not self._auto_engineering:
            return
        self._auto_engineering = want
        try:
            # A viewer change must not abort a running config session.
            await asyncio.shield(device.set_engineering_mode(want))
        except CONNECT_ERRORS as ex:
            self.logger.debug(
                "%s: switching engineering mode failed: %s", self.device_name, ex
            )
            return
        self.logger.debug(
            "%s: engineering mode %s (%d viewers)",
            self.device_name,
            "on" if want else "off",
            self._viewers,
        )

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
                self._last_info_attempt = time.monotonic()
                self._update_connection_path()
                self._schedule_engineering()

            if await device.wait_disconnected(WATCHDOG_INTERVAL):
                # Give the module/proxy a moment before reconnecting.
                await asyncio.sleep(MIN_BACKOFF)
                continue
            await self._check_stale()
            self._update_connection_path()
            await self._retry_device_info()

    def _update_connection_path(self) -> None:
        """Publish which adapter/proxy carries the connection and its RSSI."""
        device = self.device
        address = self.ble_device.address
        # habluetooth's client wrapper keeps the scanner it connected through.
        scanner = getattr(device.client, "_connected_scanner", None)
        if scanner is None:
            device.set_connection_path(None)
            return
        source = scanner.source
        rssi = None
        with suppress(Exception):  # private API, best effort
            if found := scanner.get_discovered_device_advertisement_data(address):
                rssi = found[1].rssi
        previous = device.data.get("connection_path") or {}
        if previous.get("source") != source:
            self.logger.info(
                "%s: connected via %s (%s)",
                self.device_name,
                self._scanner_names.get(source)
                or self._scanner_names.setdefault(
                    source, self._scanner_name(source, scanner.name)
                ),
                source,
            )
        device.set_connection_path(
            {
                "source": source,
                "name": self._scanner_names.get(source)
                or self._scanner_names.setdefault(
                    source, self._scanner_name(source, scanner.name)
                ),
                "rssi": rssi,
            }
        )

    def _scanner_name(self, source: str, fallback: str) -> str:
        """Friendly name of the adapter/proxy with this Bluetooth address."""
        registry = dr.async_get(self.hass)
        connection = (dr.CONNECTION_BLUETOOTH, source)
        if hasattr(registry, "async_get_devices"):  # HA 2026.9+
            devices = registry.async_get_devices(connections={connection})
            device = devices[0] if devices else None
        else:
            device = registry.async_get_device(connections={connection})
        if device is None:
            # ESPHome proxies store their Bluetooth MAC in the config entry.
            for entry in self.hass.config_entries.async_entries():
                if str(entry.data.get("bluetooth_mac_address", "")).upper() == source:
                    devices = dr.async_entries_for_config_entry(
                        registry, entry.entry_id
                    )
                    device = devices[0] if devices else None
                    break
        name = (device and (device.name_by_user or device.name)) or fallback
        # Local adapters are named like "hci0 (MAC)"; the MAC is shown separately.
        return name.removesuffix(f" ({source})")

    async def _retry_device_info(self) -> None:
        device = self.device
        if (
            "firmware_version" in device.data
            or device.busy
            or not device.is_connected
            or time.monotonic() - self._last_info_attempt < INFO_RETRY_INTERVAL
        ):
            return
        self._last_info_attempt = time.monotonic()
        try:
            await device.read_device_info()
        except CONNECT_ERRORS as ex:
            self.logger.debug("%s: device info retry failed: %s", self.device_name, ex)

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
