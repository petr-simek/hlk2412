"""HLK-2412 device implementation with UART protocol."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import (
    BLEAK_RETRY_EXCEPTIONS,
    BleakClientWithServiceCache,
    establish_connection,
)

_LOGGER = logging.getLogger(__name__)

CHARACTERISTIC_NOTIFY = "0000fff1-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_WRITE = "0000fff2-0000-1000-8000-00805f9b34fb"

TX_HEADER = "FDFCFBFA"
TX_FOOTER = "04030201"
RX_HEADER = "F4F3F2F1"
RX_FOOTER = "F8F7F6F5"

CMD_ENABLE_CFG = "00FF"
CMD_END_CFG = "00FE"
CMD_READ_FIRMWARE = "00A0"
CMD_READ_RESOLUTION = "0011"
CMD_READ_BASIC_PARAMS = "0012"
CMD_WRITE_BASIC_PARAMS = "0002"
CMD_WRITE_MOTION_SENSITIVITY = "0003"
CMD_WRITE_MOTIONLESS_SENSITIVITY = "0004"
CMD_READ_MOTION_SENSITIVITY = "0013"
CMD_READ_MOTIONLESS_SENSITIVITY = "0014"
CMD_READ_LIGHT_SENSE = "001C"
CMD_READ_MAC = "00A5"
CMD_ENABLE_ENGINEERING = "0062"
CMD_DISABLE_ENGINEERING = "0063"
CMD_START_CALIBRATION = "000B"
CMD_QUERY_CALIBRATION = "001B"
CMD_FACTORY_RESET = "00A2"
CMD_RESTART_MODULE = "00A3"

DISCONNECT_DELAY = 8.5
COMMAND_TIMEOUT = 5


class OperationError(Exception):
    """Raised when an operation fails."""


def _unwrap_frame(data: bytes, header: str, footer: str) -> bytes:
    """Remove header and footer from a framed message."""
    hdr = bytearray.fromhex(header)
    ftr = bytearray.fromhex(footer)
    if data.startswith(hdr) and data.endswith(ftr):
        length = int.from_bytes(data[len(hdr) : len(hdr) + 2], "little")
        return data[len(hdr) + 2 : len(hdr) + 2 + length]
    return data


class HLK2412Device:
    """Representation of HLK-2412 device with UART protocol."""

    def __init__(self, ble_device: BLEDevice, password: str | None = None) -> None:
        """Initialize the device."""
        self.ble_device = ble_device
        self._password = password or "HiLink"
        self._client: BleakClientWithServiceCache | None = None
        self._data: dict[str, Any] = {}
        self._callbacks: list = []
        self._lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._notify_future: asyncio.Future[bytearray] | None = None
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._expected_disconnect = False
        self.loop = asyncio.get_event_loop()
        self._last_full_update: float = -3600
        self._calibration_poll_task: asyncio.Task | None = None

    @property
    def is_connected(self) -> bool:
        """Return if device is connected."""
        return self._client is not None and self._client.is_connected

    @property
    def data(self) -> dict[str, Any]:
        """Return device data."""
        return self._data

    def subscribe(self, callback) -> callable:
        """Subscribe to device updates."""
        self._callbacks.append(callback)

        def unsubscribe():
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return unsubscribe

    def _notify_callbacks(self) -> None:
        """Notify all callbacks of data update."""
        for callback in self._callbacks:
            callback()

    def _reset_disconnect_timer(self):
        """Reset disconnect timer."""
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
        self._expected_disconnect = False
        self._disconnect_timer = self.loop.call_later(
            DISCONNECT_DELAY, self._disconnect_from_timer
        )

    def _disconnect_from_timer(self):
        """Disconnect from device."""
        if self._operation_lock.locked():
            self._reset_disconnect_timer()
            return
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
            self._disconnect_timer = None
        asyncio.create_task(self._execute_disconnect())

    async def _ensure_connected(self) -> None:
        """Ensure connection to device is established."""
        if self._client and self._client.is_connected:
            self._reset_disconnect_timer()
            return

        async with self._lock:
            if self._client and self._client.is_connected:
                self._reset_disconnect_timer()
                return

            _LOGGER.info("[%s] Connecting to HLK-2412...", self.ble_device.address)
            try:
                client: BleakClientWithServiceCache = await establish_connection(
                    BleakClientWithServiceCache,
                    self.ble_device,
                    f"HLK-2412 ({self.ble_device.address})",
                    self._on_disconnect,
                    use_services_cache=True,
                    ble_device_callback=lambda: self.ble_device,
                )
                self._client = client
                _LOGGER.info("Starting notifications on %s", CHARACTERISTIC_NOTIFY)
                await client.start_notify(
                    CHARACTERISTIC_NOTIFY, self._notification_handler
                )
                _LOGGER.info("Notifications started successfully")
                self._reset_disconnect_timer()
                _LOGGER.info("[%s] Connected to HLK-2412", self.ble_device.address)

                await self._on_connect()
            except Exception as ex:
                _LOGGER.error("[%s] Failed to connect: %s", self.ble_device.address, ex)
                self._client = None
                raise

    async def _on_connect(self) -> None:
        """Run after connection to initialize device."""
        _LOGGER.info("[%s] Connected, listening for data frames...", self.ble_device.address)
        await asyncio.sleep(0.5)
        
        # Read firmware and configuration once on first connect
        if "firmware_version" not in self._data:
            try:
                await self._read_firmware_version()
            except Exception as ex:
                _LOGGER.warning("[%s] Failed to read firmware info: %s", self.ble_device.address, ex)

    def _on_disconnect(self, client: BleakClientWithServiceCache) -> None:
        """Handle disconnection."""
        if self._expected_disconnect:
            _LOGGER.info("[%s] Disconnected", self.ble_device.address)
        else:
            _LOGGER.warning("[%s] Unexpected disconnection", self.ble_device.address)
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
            self._disconnect_timer = None

    async def _execute_disconnect(self) -> None:
        """Execute disconnection."""
        async with self._lock:
            if self._disconnect_timer:
                return
            self._expected_disconnect = True
            client = self._client
            self._client = None
            if client and client.is_connected:
                try:
                    await client.disconnect()
                except Exception as ex:
                    _LOGGER.warning("Error disconnecting: %s", ex)

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
            self._disconnect_timer = None
        await self._execute_disconnect()

    def _notification_handler(self, _sender: int, data: bytearray) -> None:
        """Handle notification responses."""
        # _LOGGER.debug("[%s] RX: %s", self.ble_device.address, data.hex())
        self._reset_disconnect_timer()

        if data.startswith(bytearray.fromhex(TX_HEADER)):
            _LOGGER.debug("[%s] Command ACK detected: %s", self.ble_device.address, data.hex())
            if self._notify_future and not self._notify_future.done():
                self._notify_future.set_result(data)
            else:
                _LOGGER.warning("[%s] Received ACK but no future waiting: %s", self.ble_device.address, data.hex())
            return

        if data.startswith(bytearray.fromhex(RX_HEADER)):
            # _LOGGER.debug("[%s] Data frame detected", self.ble_device.address)
            payload = _unwrap_frame(data, RX_HEADER, RX_FOOTER)
            try:
                parsed = self._parse_uplink_frame(payload)
                if parsed:
                    self._data.update(parsed)
                    self._last_full_update = time.monotonic()
                    self._notify_callbacks()
            except Exception as ex:
                _LOGGER.debug("[%s] Failed to parse uplink frame: %s", self.ble_device.address, ex)
        else:
            _LOGGER.warning("[%s] Unknown frame header: %s", self.ble_device.address, data[:4].hex() if len(data) >= 4 else data.hex())

    def _modify_command(self, raw_command: str) -> bytes:
        """Wrap command in protocol framing."""
        command_word = raw_command[:4]
        value = raw_command[4:]
        command_bytes = int(command_word, 16).to_bytes(2, "little")
        value_bytes = bytearray.fromhex(value)
        contents = bytearray(command_bytes + value_bytes)
        length = len(contents).to_bytes(2, "little")
        return (
            bytearray.fromhex(TX_HEADER)
            + length
            + contents
            + bytearray.fromhex(TX_FOOTER)
        )

    def _parse_response(self, raw_command: str, data: bytes) -> bytes:
        """Parse command response."""
        payload = _unwrap_frame(data, TX_HEADER, TX_FOOTER)
        if len(payload) < 2:
            raise OperationError("Response too short")
        expected_ack = (int(raw_command[:4], 16) | 0x0100).to_bytes(2, "little")
        command = payload[:2]
        if command != expected_ack:
            raise OperationError(
                f"Unexpected response command {command.hex()} for {raw_command[:4]}"
            )
        return payload[2:]

    async def _send_command(
        self, raw_command: str, wait_for_response: bool = True
    ) -> bytes | None:
        """Send command to device and read response."""
        await self._ensure_connected()

        async with self._operation_lock:
            command = self._modify_command(raw_command)
            _LOGGER.debug("[%s] TX command: %s -> %s", self.ble_device.address, raw_command, command.hex())

            if wait_for_response:
                self._notify_future = self.loop.create_future()

            await self._client.write_gatt_char(
                CHARACTERISTIC_WRITE, command, False
            )
            _LOGGER.debug("[%s] Command written to %s", self.ble_device.address, CHARACTERISTIC_WRITE)

            if not wait_for_response:
                return None

            try:
                notify_msg_raw = await asyncio.wait_for(
                    self._notify_future, timeout=COMMAND_TIMEOUT
                )
                _LOGGER.debug("Got response: %s", notify_msg_raw.hex())
            except asyncio.TimeoutError:
                _LOGGER.error("[%s] Command timeout for %s after %ds", self.ble_device.address, raw_command, COMMAND_TIMEOUT)
                raise OperationError("Command timeout")
            finally:
                self._notify_future = None

            notify_msg = self._parse_response(raw_command, notify_msg_raw)
            _LOGGER.debug("Command response: %s", notify_msg.hex())
            return notify_msg

    async def _read_firmware_version(self) -> None:
        """Read firmware version and basic configuration from device."""
        response = await self._send_command(CMD_ENABLE_CFG + "0100")
        if not response or len(response) < 2:
            raise OperationError("Failed to enable configuration")

        status = int.from_bytes(response[:2], "little")
        if status != 0:
            raise OperationError(f"Enable config failed with status {status}")

        fw_response = await self._send_command(CMD_READ_FIRMWARE)
        if fw_response and len(fw_response) >= 2:
            fw_status = int.from_bytes(fw_response[:2], "little")
            if fw_status == 0 and len(fw_response) >= 4:
                fw_type = int.from_bytes(fw_response[2:4], "little")
                if len(fw_response) >= 10:
                    # Major version: 2 bytes [patch, major] e.g. [0x10, 0x01] -> V1.10
                    major_part = fw_response[5]
                    patch_part = fw_response[4]
                    # Minor version: 4 bytes reversed e.g. [0x10, 0x18, 0x04, 0x24] -> 24041810
                    minor_bytes = fw_response[6:10]
                    minor_str = "".join(f"{b:02x}" for b in reversed(minor_bytes))
                    self._data["firmware_version"] = f"V{major_part}.{patch_part:02x}.{minor_str}"
                    self._data["firmware_type"] = fw_type
                    _LOGGER.info(
                        "[%s] Firmware: %s (type: 0x%04x)",
                        self.ble_device.address,
                        self._data["firmware_version"],
                        fw_type,
                    )

        params_response = await self._send_command(CMD_READ_BASIC_PARAMS)
        if params_response and len(params_response) >= 2:
            params_status = int.from_bytes(params_response[:2], "little")
            if params_status == 0 and len(params_response) >= 7:
                min_gate = params_response[2]
                max_gate = params_response[3]
                unmanned_duration = int.from_bytes(params_response[4:6], "little")
                self._data["min_gate"] = min_gate
                self._data["max_gate"] = max_gate
                self._data["unmanned_duration"] = unmanned_duration
                _LOGGER.debug(
                    "HLK-2412: Gates %d-%d, Unmanned: %ds",
                    min_gate,
                    max_gate,
                    unmanned_duration,
                )

        # Read motion sensitivity for all gates
        motion_sens_response = await self._send_command(CMD_READ_MOTION_SENSITIVITY)
        if motion_sens_response and len(motion_sens_response) >= 2:
            sens_status = int.from_bytes(motion_sens_response[:2], "little")
            if sens_status == 0 and len(motion_sens_response) >= 16:
                for i in range(14):
                    self._data[f"motion_sensitivity_gate_{i}"] = motion_sens_response[2 + i]
                _LOGGER.debug("[%s] Motion sensitivity loaded", self.ble_device.address)

        # Read motionless sensitivity for all gates
        motionless_sens_response = await self._send_command(CMD_READ_MOTIONLESS_SENSITIVITY)
        if motionless_sens_response and len(motionless_sens_response) >= 2:
            sens_status = int.from_bytes(motionless_sens_response[:2], "little")
            if sens_status == 0 and len(motionless_sens_response) >= 16:
                for i in range(14):
                    self._data[f"motionless_sensitivity_gate_{i}"] = motionless_sens_response[2 + i]
                _LOGGER.debug("[%s] Motionless sensitivity loaded", self.ble_device.address)

        response = await self._send_command(CMD_END_CFG)
        if not response or len(response) < 2:
            raise OperationError("Failed to end configuration")

    async def read_configuration(self) -> dict[str, Any]:
        """Read full configuration from device (call on demand)."""
        config = {}

        response = await self._send_command(CMD_ENABLE_CFG + "0100")
        if not response or len(response) < 2:
            raise OperationError("Failed to enable configuration")

        status = int.from_bytes(response[:2], "little")
        if status != 0:
            raise OperationError(f"Enable config failed with status {status}")

        resolution_response = await self._send_command(CMD_READ_RESOLUTION)
        if resolution_response and len(resolution_response) >= 3:
            res_status = int.from_bytes(resolution_response[:2], "little")
            if res_status == 0:
                config["resolution"] = resolution_response[2]

        motion_sens_response = await self._send_command(CMD_READ_MOTION_SENSITIVITY)
        if motion_sens_response and len(motion_sens_response) >= 16:
            sens_status = int.from_bytes(motion_sens_response[:2], "little")
            if sens_status == 0:
                config["motion_sensitivity"] = list(motion_sens_response[2:16])

        motionless_sens_response = await self._send_command(
            CMD_READ_MOTIONLESS_SENSITIVITY
        )
        if motionless_sens_response and len(motionless_sens_response) >= 16:
            sens_status = int.from_bytes(motionless_sens_response[:2], "little")
            if sens_status == 0:
                config["motionless_sensitivity"] = list(motionless_sens_response[2:16])

        mac_response = await self._send_command(CMD_READ_MAC + "0100")
        if mac_response and len(mac_response) >= 8:
            mac_status = int.from_bytes(mac_response[:2], "little")
            if mac_status == 0:
                mac_bytes = mac_response[2:8]
                config["mac_address"] = ":".join(f"{b:02X}" for b in mac_bytes)

        response = await self._send_command(CMD_END_CFG)

        return config

    async def enable_engineering_mode(self) -> bool:
        """Enable engineering mode."""
        try:
            await self._ensure_connected()
            
            # Retry enable config command - device may be busy streaming data
            response = None
            for attempt in range(3):
                try:
                    response = await self._send_command(CMD_ENABLE_CFG + "0100")
                    if response and len(response) >= 2:
                        break
                    _LOGGER.warning("[%s] Enable config attempt %d failed, retrying...", self.ble_device.address, attempt + 1)
                    await asyncio.sleep(0.5)
                except OperationError:
                    if attempt < 2:
                        _LOGGER.warning("[%s] Enable config timeout, attempt %d/3", self.ble_device.address, attempt + 1)
                        await asyncio.sleep(0.5)
                    else:
                        raise
            
            if not response or len(response) < 2:
                raise OperationError("Failed to enable configuration after retries")
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                raise OperationError(f"Enable config failed with status {status}")
            
            response = await self._send_command(CMD_ENABLE_ENGINEERING)
            if not response or len(response) < 2:
                raise OperationError("Failed to enable engineering mode")
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                _LOGGER.error("[%s] Enable engineering mode failed with status %d", self.ble_device.address, status)
                await self._send_command(CMD_END_CFG)
                return False
            
            await self._send_command(CMD_END_CFG)
            _LOGGER.info("[%s] Engineering mode enabled", self.ble_device.address)
            return True
        except Exception as ex:
            _LOGGER.error("[%s] Failed to enable engineering mode: %s", self.ble_device.address, ex)
            return False

    async def disable_engineering_mode(self) -> bool:
        """Disable engineering mode."""
        try:
            await self._ensure_connected()
            
            # Retry enable config command - device may be busy streaming data
            response = None
            for attempt in range(3):
                try:
                    response = await self._send_command(CMD_ENABLE_CFG + "0100")
                    if response and len(response) >= 2:
                        break
                    _LOGGER.warning("[%s] Enable config attempt %d failed, retrying...", self.ble_device.address, attempt + 1)
                    await asyncio.sleep(0.5)
                except OperationError:
                    if attempt < 2:
                        _LOGGER.warning("[%s] Enable config timeout, attempt %d/3", self.ble_device.address, attempt + 1)
                        await asyncio.sleep(0.5)
                    else:
                        raise
            
            if not response or len(response) < 2:
                _LOGGER.error("[%s] Failed to enable configuration after retries", self.ble_device.address)
                raise OperationError("Failed to enable configuration after retries")
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                _LOGGER.error("[%s] Enable config failed with status %d", self.ble_device.address, status)
                raise OperationError(f"Enable config failed with status {status}")
            
            response = await self._send_command(CMD_DISABLE_ENGINEERING)
            if not response or len(response) < 2:
                _LOGGER.error("[%s] Failed to disable engineering mode", self.ble_device.address)
                raise OperationError("Failed to disable engineering mode")
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                _LOGGER.error("[%s] Disable engineering mode failed with status %d", self.ble_device.address, status)
                await self._send_command(CMD_END_CFG)
                return False
            
            await self._send_command(CMD_END_CFG)
            _LOGGER.info("[%s] Engineering mode disabled", self.ble_device.address)
            return True
        except Exception as ex:
            _LOGGER.error("[%s] Failed to disable engineering mode: %s", self.ble_device.address, ex)
            return False

    async def query_calibration_status(self) -> bool:
        """Query if calibration is currently running."""
        try:
            await self._ensure_connected()
            
            response = await self._send_command(CMD_QUERY_CALIBRATION)
            if not response or len(response) < 2:
                return False
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                return False
            
            # Check status value: 0x0001 = executing, 0x0000 = not executing
            if len(response) >= 4:
                calibration_status = int.from_bytes(response[2:4], "little")
                is_calibrating = calibration_status == 0x0001
                self._data["calibration_active"] = is_calibrating
                self._notify_callbacks()
                return is_calibrating
            
            return False
        except Exception as ex:
            _LOGGER.debug("[%s] Failed to query calibration status: %s", self.ble_device.address, ex)
            return False

    async def _poll_calibration_status(self) -> None:
        """Poll calibration status every 2 seconds until it's done."""
        try:
            for _ in range(15):  # Poll for max 30 seconds
                await asyncio.sleep(2)
                is_active = await self.query_calibration_status()
                if not is_active:
                    _LOGGER.info("[%s] Calibration completed", self.ble_device.address)
                    break
        except asyncio.CancelledError:
            _LOGGER.debug("[%s] Calibration polling cancelled", self.ble_device.address)
        except Exception as ex:
            _LOGGER.warning("[%s] Error polling calibration status: %s", self.ble_device.address, ex)
        finally:
            self._calibration_poll_task = None
            self._data["calibration_active"] = False
            self._notify_callbacks()

    async def start_calibration(self) -> bool:
        """Start dynamic background correction mode."""
        try:
            await self._ensure_connected()
            
            response = await self._send_command(CMD_START_CALIBRATION)
            if not response or len(response) < 2:
                raise OperationError("Failed to start calibration")
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                _LOGGER.error("[%s] Start calibration failed with status %d", self.ble_device.address, status)
                return False
            
            _LOGGER.info("[%s] Calibration started, will complete in ~10 seconds", self.ble_device.address)
            
            # Start polling calibration status
            self._data["calibration_active"] = True
            self._notify_callbacks()
            
            if self._calibration_poll_task:
                self._calibration_poll_task.cancel()
            
            self._calibration_poll_task = asyncio.create_task(self._poll_calibration_status())
            
            return True
        except Exception as ex:
            _LOGGER.error("[%s] Failed to start calibration: %s", self.ble_device.address, ex)
            return False

    async def factory_reset(self) -> bool:
        """Restore factory settings and restart module."""
        try:
            await self._ensure_connected()
            
            # Enable config mode
            response = await self._send_command(CMD_ENABLE_CFG + "0100")
            if not response or len(response) < 2:
                raise OperationError("Failed to enable configuration")
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                raise OperationError(f"Enable config failed with status {status}")
            
            # Send factory reset command
            response = await self._send_command(CMD_FACTORY_RESET)
            if not response or len(response) < 2:
                await self._send_command(CMD_END_CFG)
                raise OperationError("Failed to factory reset")
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                _LOGGER.error("[%s] Factory reset failed with status %d", self.ble_device.address, status)
                await self._send_command(CMD_END_CFG)
                return False
            
            await self._send_command(CMD_END_CFG)
            _LOGGER.info("[%s] Factory reset successful, module will restart automatically", self.ble_device.address)
            
            # Module restarts automatically after factory reset
            # Wait for module to restart and reconnect (takes ~5-10 seconds)
            _LOGGER.info("[%s] Waiting 10 seconds for module to restart...", self.ble_device.address)
            await asyncio.sleep(10)

            await self.restart_module()
            await asyncio.sleep(10)
            # Reload configuration from device after restart
            try:
                await self._read_firmware_version()
                _LOGGER.info("[%s] Configuration reloaded after factory reset", self.ble_device.address)
            except Exception as ex:
                _LOGGER.warning("[%s] Failed to reload config after reset: %s", self.ble_device.address, ex)
            
            return True
        except Exception as ex:
            _LOGGER.error("[%s] Failed to factory reset: %s", self.ble_device.address, ex)
            return False

    async def restart_module(self) -> bool:
        """Restart the module."""
        try:
            await self._ensure_connected()
            
            response = await self._send_command(CMD_RESTART_MODULE)
            if not response or len(response) < 2:
                raise OperationError("Failed to restart module")
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                _LOGGER.error("[%s] Restart module failed with status %d", self.ble_device.address, status)
                return False
            
            _LOGGER.info("[%s] Module restart initiated", self.ble_device.address)
            return True
        except Exception as ex:
            _LOGGER.error("[%s] Failed to restart module: %s", self.ble_device.address, ex)
            return False

    async def write_basic_params(
        self, min_gate: int, max_gate: int, unmanned_duration: int, out_pin_polarity: int
    ) -> bool:
        """Write basic parameters to device."""
        try:
            await self._ensure_connected()
            
            # Build command value: 1 byte min + 1 byte max + 2 bytes duration + 1 byte polarity
            value_bytes = bytes([
                min_gate,
                max_gate,
            ]) + unmanned_duration.to_bytes(2, "little") + bytes([out_pin_polarity])
            value_hex = value_bytes.hex()
            
            response = await self._send_command(CMD_ENABLE_CFG + "0100")
            if not response or len(response) < 2:
                raise OperationError("Failed to enable configuration")
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                raise OperationError(f"Enable config failed with status {status}")
            
            response = await self._send_command(CMD_WRITE_BASIC_PARAMS + value_hex)
            if not response or len(response) < 2:
                await self._send_command(CMD_END_CFG)
                raise OperationError("Failed to write basic parameters")
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                _LOGGER.error("[%s] Write basic params failed with status %d", self.ble_device.address, status)
                await self._send_command(CMD_END_CFG)
                return False
            
            await self._send_command(CMD_END_CFG)
            
            # Update local data
            self._data["min_gate"] = min_gate
            self._data["max_gate"] = max_gate
            self._data["unmanned_duration"] = unmanned_duration
            self._data["out_pin_polarity"] = out_pin_polarity
            self._notify_callbacks()
            
            _LOGGER.info(
                "[%s] Basic params updated: gates %d-%d, unmanned %ds, polarity %d",
                self.ble_device.address,
                min_gate,
                max_gate,
                unmanned_duration,
                out_pin_polarity,
            )
            return True
        except Exception as ex:
            _LOGGER.error("[%s] Failed to write basic params: %s", self.ble_device.address, ex)
            return False

    async def write_motion_sensitivity(self, sensitivities: list[int]) -> bool:
        """Write motion sensitivity for all 14 gates."""
        try:
            await self._ensure_connected()
            
            if len(sensitivities) != 14:
                raise OperationError("Motion sensitivity must have exactly 14 values")
            
            # Build command value: 14 bytes, one for each gate
            value_hex = "".join(f"{s:02x}" for s in sensitivities)
            
            response = await self._send_command(CMD_ENABLE_CFG + "0100")
            if not response or len(response) < 2:
                raise OperationError("Failed to enable configuration")
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                raise OperationError(f"Enable config failed with status {status}")
            
            response = await self._send_command(CMD_WRITE_MOTION_SENSITIVITY + value_hex)
            if not response or len(response) < 2:
                await self._send_command(CMD_END_CFG)
                raise OperationError("Failed to write motion sensitivity")
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                _LOGGER.error("[%s] Write motion sensitivity failed with status %d", self.ble_device.address, status)
                await self._send_command(CMD_END_CFG)
                return False
            
            await self._send_command(CMD_END_CFG)
            
            # Update local data
            for i, sens in enumerate(sensitivities):
                self._data[f"motion_sensitivity_gate_{i}"] = sens
            self._notify_callbacks()
            
            _LOGGER.info("[%s] Motion sensitivity updated for all gates", self.ble_device.address)
            return True
        except Exception as ex:
            _LOGGER.error("[%s] Failed to write motion sensitivity: %s", self.ble_device.address, ex)
            return False

    async def write_motionless_sensitivity(self, sensitivities: list[int]) -> bool:
        """Write motionless sensitivity for all 14 gates."""
        try:
            await self._ensure_connected()
            
            if len(sensitivities) != 14:
                raise OperationError("Motionless sensitivity must have exactly 14 values")
            
            # Build command value: 14 bytes, one for each gate
            value_hex = "".join(f"{s:02x}" for s in sensitivities)
            
            response = await self._send_command(CMD_ENABLE_CFG + "0100")
            if not response or len(response) < 2:
                raise OperationError("Failed to enable configuration")
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                raise OperationError(f"Enable config failed with status {status}")
            
            response = await self._send_command(CMD_WRITE_MOTIONLESS_SENSITIVITY + value_hex)
            if not response or len(response) < 2:
                await self._send_command(CMD_END_CFG)
                raise OperationError("Failed to write motionless sensitivity")
            
            status = int.from_bytes(response[:2], "little")
            if status != 0:
                _LOGGER.error("[%s] Write motionless sensitivity failed with status %d", self.ble_device.address, status)
                await self._send_command(CMD_END_CFG)
                return False
            
            await self._send_command(CMD_END_CFG)
            
            # Update local data
            for i, sens in enumerate(sensitivities):
                self._data[f"motionless_sensitivity_gate_{i}"] = sens
            self._notify_callbacks()
            
            _LOGGER.info("[%s] Motionless sensitivity updated for all gates", self.ble_device.address)
            return True
        except Exception as ex:
            _LOGGER.error("[%s] Failed to write motionless sensitivity: %s", self.ble_device.address, ex)
            return False

    def _parse_uplink_frame(self, data: bytes) -> dict[str, Any] | None:
        """Parse uplink data frame from device."""
        if len(data) < 2 or data[1] != 0xAA:
            _LOGGER.error("payload too short for 1 basic data %s", self.ble_device.address)
            return None
        UPLINK_TYPE_ENGINEERING = "01"  # per-gate energies appended to basic target info (+ light_value, out_state)
        UPLINK_TYPE_BASIC = "02"  # basic target info only (default).
        frame_type = data[:1].hex()
        if frame_type == UPLINK_TYPE_ENGINEERING:
            ftype = "engineering"
        elif frame_type == UPLINK_TYPE_BASIC:
            ftype = "basic"
        else:
            _LOGGER.error("unknown frame type %s", frame_type)
            return None

        # Check for end marker 0x55 (checksum byte after it can be any value)
        if len(data) < 10 or data[-2] != 0x55:
            _LOGGER.error("Invalid frame format %s: %s", self.ble_device.address, data.hex())
            return None

        # Extract content between header (2 bytes) and footer (0x55 + checksum)
        content = data[2:-2]

        if len(content) < 7:
            _LOGGER.error("payload too short for 3 basic data %s", self.ble_device.address)
            return None

        status_raw = content[0]
        move_distance_cm = int.from_bytes(content[1:3], "little")
        move_energy = content[3]
        still_distance_cm = int.from_bytes(content[4:6], "little")
        still_energy = content[6]

        moving = status_raw in (0x01, 0x03)
        stationary = status_raw in (0x02, 0x03)
        occupancy = moving or stationary

        result = {
            "moving": moving,
            "stationary": stationary,
            "occupancy": occupancy,
            "move_distance_cm": move_distance_cm,
            "move_energy": move_energy,
            "still_distance_cm": still_distance_cm,
            "still_energy": still_energy,
            "data_type": ftype,
            "engineering_mode": frame_type == UPLINK_TYPE_ENGINEERING,
        }

        # Parse gate energies in engineering mode
        # Structure: 7 basic + 2 max gates + 13 move gates + 13 static gates
        if frame_type == UPLINK_TYPE_ENGINEERING and len(content) >= 35:
            # Skip basic 7 bytes and 2 max gate bytes
            gate_data = content[9:]
            
            # 13 movement gate energies
            if len(gate_data) >= 13:
                for i in range(13):
                    result[f"move_gate_{i}_energy"] = gate_data[i]
            
            # 13 static gate energies (after movement gates)
            if len(gate_data) >= 26:
                for i in range(13):
                    result[f"static_gate_{i}_energy"] = gate_data[13 + i]
            
            # Light level (1 byte after gate energies, 0-255)
            if len(data) >= 39:
                result["light_level"] = data[39]
                # _LOGGER.debug("[%s] Light level: %d", self.ble_device.address, data[39])
            
            # _LOGGER.debug("Engineering mode: parsed %d gate energies", len([k for k in result if "gate" in k]))
        else:
            # In basic mode, set all gate energies to None (unavailable)
            for i in range(13):
                result[f"move_gate_{i}_energy"] = None
                result[f"static_gate_{i}_energy"] = None

        # _LOGGER.debug("[%s] Parsed: moving=%s, stationary=%s, occupancy=%s", self.ble_device.address, moving, stationary, occupancy)

        return result

    async def update(self) -> None:
        """Update device data."""
        if not self.is_connected:
            await self._ensure_connected()
