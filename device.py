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
CMD_READ_MOTION_SENSITIVITY = "0013"
CMD_READ_MOTIONLESS_SENSITIVITY = "0014"
CMD_READ_LIGHT_SENSE = "001C"
CMD_READ_MAC = "00A5"
CMD_ENABLE_ENGINEERING = "0062"
CMD_DISABLE_ENGINEERING = "0063"

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
        contents = bytearray.fromhex(command_word + value)
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
        expected_ack = (int(raw_command[:4], 16) ^ 0x0001).to_bytes(2, "big")
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
        response = await self._send_command(CMD_ENABLE_CFG + "0001")
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
                _LOGGER.info("HLK-2412: Firmware type: 0x%04x", fw_type)
                if len(fw_response) >= 8:
                    major = int.from_bytes(fw_response[4:6], "little")
                    minor = int.from_bytes(fw_response[6:10], "little")
                    self._data["firmware_version"] = f"{major}.{minor}"
                    self._data["firmware_type"] = fw_type

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

        response = await self._send_command(CMD_END_CFG)
        if not response or len(response) < 2:
            raise OperationError("Failed to end configuration")

    async def read_configuration(self) -> dict[str, Any]:
        """Read full configuration from device (call on demand)."""
        config = {}

        response = await self._send_command(CMD_ENABLE_CFG + "0001")
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

        mac_response = await self._send_command(CMD_READ_MAC + "0001")
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
                    response = await self._send_command(CMD_ENABLE_CFG + "0001")
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
                    response = await self._send_command(CMD_ENABLE_CFG + "0001")
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
