"""HLK-2412 device implementation with UART-over-BLE protocol."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
import logging
import time
from typing import Any

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)

_LOGGER = logging.getLogger(__name__)

CHARACTERISTIC_NOTIFY = "0000fff1-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_WRITE = "0000fff2-0000-1000-8000-00805f9b34fb"

TX_HEADER = bytes.fromhex("FDFCFBFA")
TX_FOOTER = bytes.fromhex("04030201")
RX_HEADER = bytes.fromhex("F4F3F2F1")
RX_FOOTER = bytes.fromhex("F8F7F6F5")
HEADER_LEN = 4
# Longest valid frame is an engineering report (~45 B); anything above is garbage.
MAX_FRAME_PAYLOAD = 128
MAX_BUFFER = 512

CMD_ENABLE_CFG = 0x00FF
CMD_END_CFG = 0x00FE
CMD_READ_FIRMWARE = 0x00A0
CMD_READ_RESOLUTION = 0x0011
CMD_READ_BASIC_PARAMS = 0x0012
CMD_WRITE_BASIC_PARAMS = 0x0002
CMD_WRITE_MOTION_SENSITIVITY = 0x0003
CMD_WRITE_MOTIONLESS_SENSITIVITY = 0x0004
CMD_READ_MOTION_SENSITIVITY = 0x0013
CMD_READ_MOTIONLESS_SENSITIVITY = 0x0014
CMD_READ_MAC = 0x00A5
CMD_ENABLE_ENGINEERING = 0x0062
CMD_DISABLE_ENGINEERING = 0x0063
CMD_START_CALIBRATION = 0x000B
CMD_QUERY_CALIBRATION = 0x001B
CMD_FACTORY_RESET = 0x00A2
CMD_RESTART_MODULE = 0x00A3

FRAME_TYPE_ENGINEERING = 0x01
FRAME_TYPE_BASIC = 0x02

GATES = 14
GATE_ENERGY_KEYS = tuple(
    [f"move_gate_{i}_energy" for i in range(GATES)]
    + [f"static_gate_{i}_energy" for i in range(GATES)]
)
# Values read from the module in config mode; cleared after a factory reset.
CONFIG_KEYS = (
    "firmware_version",
    "firmware_type",
    "resolution",
    "min_gate",
    "max_gate",
    "unmanned_duration",
    "out_pin_polarity",
    *(f"motion_sensitivity_gate_{i}" for i in range(GATES)),
    *(f"motionless_sensitivity_gate_{i}" for i in range(GATES)),
)

# Keys sent to state listeners (config editor) when they change.
STATE_KEYS = frozenset((*CONFIG_KEYS, "calibration_active", "engineering_mode"))
# Report values that change on almost every frame; throttled for entities.
SLOW_KEYS = frozenset(
    (
        "move_distance_cm",
        "move_energy",
        "still_distance_cm",
        "still_energy",
        "light_level",
        *GATE_ENERGY_KEYS,
    )
)
# Distance resolution code -> metres per gate.
RESOLUTIONS = {0: 0.75, 1: 0.5, 3: 0.2}

# Whole connect (all establish_connection attempts + start_notify) must finish
# within this time, otherwise a hung BlueZ/proxy connect would stall forever.
CONNECT_TIMEOUT = 75.0
DISCONNECT_TIMEOUT = 10.0
COMMAND_TIMEOUT = 3.0
ENABLE_CFG_ATTEMPTS = 3

_MISSING = object()


class OperationError(Exception):
    """Raised when an operation fails."""


class HLK2412Device:
    """Representation of HLK-2412 device with UART protocol over BLE."""

    def __init__(self, ble_device: BLEDevice, max_attempts: int = 3) -> None:
        """Initialize the device."""
        self.ble_device = ble_device
        self._max_attempts = max(1, max_attempts)
        self._client: BleakClientWithServiceCache | None = None
        self._data: dict[str, Any] = {"sensor_update_interval": 1.0}
        self._listeners: dict[str, list[Callable[[], None]]] = {}
        # Unthrottled parsed report frames (live view in the card).
        self._frame_listeners: list[Callable[[dict[str, Any]], None]] = []
        # Connection and config changes (config editor in the card).
        self._state_listeners: list[Callable[[], None]] = []
        self._connect_lock = asyncio.Lock()
        # Serializes whole config sessions (enable cfg ... end cfg).
        self._session_lock = asyncio.Lock()
        self._rx_buffer = bytearray()
        self._pending_ack: tuple[bytes, asyncio.Future[bytes]] | None = None
        self._disconnected = asyncio.Event()
        self._disconnected.set()
        self._expected_disconnect = False
        self._last_sensor_update = 0.0
        self._calibration_poll_task: asyncio.Task | None = None
        self.last_frame_time = 0.0

    # ------------------------------------------------------------------ state

    @property
    def address(self) -> str:
        """Return BLE address."""
        return self.ble_device.address

    @property
    def is_connected(self) -> bool:
        """Return if device is connected."""
        return self._client is not None and self._client.is_connected

    @property
    def busy(self) -> bool:
        """Return True while a config session is running (no data frames)."""
        return self._session_lock.locked()

    @property
    def data(self) -> dict[str, Any]:
        """Return device data."""
        return self._data

    def subscribe(self, key: str, callback: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to changes of one data key (and to availability changes)."""
        listeners = self._listeners.setdefault(key, [])
        listeners.append(callback)

        def unsubscribe() -> None:
            with suppress(ValueError):
                listeners.remove(callback)

        return unsubscribe

    def subscribe_frames(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Subscribe to every parsed report frame."""
        return self._add(self._frame_listeners, callback)

    def subscribe_state(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to connection and configuration changes."""
        return self._add(self._state_listeners, callback)

    @staticmethod
    def _add(listeners: list, callback: Callable) -> Callable[[], None]:
        listeners.append(callback)

        def unsubscribe() -> None:
            with suppress(ValueError):
                listeners.remove(callback)

        return unsubscribe

    def set_local_value(self, key: str, value: Any) -> None:
        """Set a value locally (applied to the module by 'Apply configuration')."""
        self._update({key: value})

    def _update(self, values: dict[str, Any]) -> None:
        """Store values and notify listeners of the keys that changed."""
        data = self._data
        changed = [
            key for key, value in values.items() if data.get(key, _MISSING) != value
        ]
        if not changed:
            return
        for key in changed:
            data[key] = values[key]
        listeners = self._listeners
        for key in changed:
            for callback in listeners.get(key, ()):
                callback()
        if not STATE_KEYS.isdisjoint(changed):
            for callback in tuple(self._state_listeners):
                callback()

    def _notify_all(self) -> None:
        """Notify every listener (availability changed)."""
        for listeners in self._listeners.values():
            for callback in listeners:
                callback()
        for callback in tuple(self._state_listeners):
            callback()

    # ------------------------------------------------------------- connection

    async def connect(self) -> None:
        """Connect, subscribe to notifications and read initial info."""
        async with self._connect_lock:
            if self.is_connected:
                return
            _LOGGER.debug("[%s] Connecting", self.address)
            self._rx_buffer.clear()
            client: BleakClientWithServiceCache | None = None
            try:
                async with asyncio.timeout(CONNECT_TIMEOUT):
                    client = await establish_connection(
                        BleakClientWithServiceCache,
                        self.ble_device,
                        f"HLK-2412 ({self.address})",
                        self._on_disconnect,
                        max_attempts=self._max_attempts,
                        use_services_cache=True,
                        ble_device_callback=lambda: self.ble_device,
                    )
                    # Set before start_notify so the very first frames are accepted
                    # and a drop during start_notify is reported.
                    self._client = client
                    self._disconnected.clear()
                    await client.start_notify(
                        CHARACTERISTIC_NOTIFY, self._notification_handler
                    )
            except BaseException:
                self._client = None
                self._disconnected.set()
                if client is not None:
                    await self._safe_disconnect(client)
                raise

            self._expected_disconnect = False
            self.last_frame_time = time.monotonic()
            _LOGGER.info("[%s] Connected", self.address)

        self._notify_all()

        if "firmware_version" not in self._data:
            try:
                await self.read_device_info()
            except (OperationError, BleakError, TimeoutError) as ex:
                _LOGGER.warning(
                    "[%s] Failed to read device info: %s", self.address, ex
                )

    async def wait_disconnected(self, timeout: float) -> bool:
        """Wait until the device disconnects; return True if it did."""
        with suppress(TimeoutError):
            async with asyncio.timeout(timeout):
                await self._disconnected.wait()
        return self._disconnected.is_set()

    def _on_disconnect(self, client: BleakClientWithServiceCache) -> None:
        """Handle disconnection."""
        # establish_connection reports disconnects of its failed attempts too;
        # only the client we actually use matters.
        if client is not self._client:
            return
        self._client = None
        self._rx_buffer.clear()
        self._fail_pending(OperationError("Disconnected"))
        self._disconnected.set()
        if self._expected_disconnect:
            _LOGGER.debug("[%s] Disconnected", self.address)
        else:
            _LOGGER.warning("[%s] Unexpected disconnection", self.address)
        self._notify_all()

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        if self._calibration_poll_task:
            self._calibration_poll_task.cancel()
        self._expected_disconnect = True
        client = self._client
        self._client = None
        self._fail_pending(OperationError("Disconnected"))
        self._disconnected.set()
        if client is not None:
            await self._safe_disconnect(client)
            self._notify_all()

    async def _safe_disconnect(self, client: BleakClientWithServiceCache) -> None:
        try:
            async with asyncio.timeout(DISCONNECT_TIMEOUT):
                await client.disconnect()
        except Exception as ex:  # noqa: BLE001
            _LOGGER.debug("[%s] Error disconnecting: %s", self.address, ex)

    # --------------------------------------------------------------- receive

    def _notification_handler(self, _sender: Any, data: bytearray) -> None:
        """Reassemble frames from (possibly fragmented) notifications."""
        buf = self._rx_buffer
        buf += data
        while True:
            rx = buf.find(RX_HEADER)
            tx = buf.find(TX_HEADER)
            if rx < 0 and tx < 0:
                # Keep a possible partial header at the end.
                del buf[: max(0, len(buf) - (HEADER_LEN - 1))]
                return
            start = tx if rx < 0 or (0 <= tx < rx) else rx
            if start:
                del buf[:start]
            if len(buf) < HEADER_LEN + 2:
                return
            length = int.from_bytes(buf[4:6], "little")
            if length > MAX_FRAME_PAYLOAD:
                del buf[:HEADER_LEN]
                continue
            end = HEADER_LEN + 2 + length + HEADER_LEN
            if len(buf) < end:
                if len(buf) > MAX_BUFFER:
                    buf.clear()
                return
            is_report = buf[:HEADER_LEN] == RX_HEADER
            footer = buf[end - HEADER_LEN : end]
            payload = bytes(buf[HEADER_LEN + 2 : end - HEADER_LEN])
            del buf[:end]
            if footer != (RX_FOOTER if is_report else TX_FOOTER):
                _LOGGER.debug("[%s] Dropping frame with bad footer", self.address)
                continue
            if is_report:
                self._handle_report(payload)
            else:
                self._handle_ack(payload)

    def _handle_ack(self, payload: bytes) -> None:
        pending = self._pending_ack
        if pending and payload[:2] == pending[0] and not pending[1].done():
            pending[1].set_result(payload[2:])
        else:
            _LOGGER.debug("[%s] Unsolicited ACK: %s", self.address, payload.hex())

    def _handle_report(self, payload: bytes) -> None:
        self.last_frame_time = now = time.monotonic()
        try:
            parsed = self._parse_report(payload)
        except (IndexError, ValueError) as ex:
            _LOGGER.debug("[%s] Failed to parse report: %s", self.address, ex)
            return
        if not parsed:
            return
        for callback in tuple(self._frame_listeners):
            callback(parsed)
        # Distances/energies change on almost every frame; throttle them.
        interval = self._data.get("sensor_update_interval", 1.0)
        if now - self._last_sensor_update >= interval:
            self._last_sensor_update = now
            self._update(parsed)
        else:
            self._update({k: v for k, v in parsed.items() if k not in SLOW_KEYS})

    def _parse_report(self, payload: bytes) -> dict[str, Any] | None:
        """Parse a report frame payload: type, 0xAA, content..., 0x55, check."""
        if len(payload) < 11 or payload[1] != 0xAA or payload[-2] != 0x55:
            _LOGGER.debug("[%s] Invalid report: %s", self.address, payload.hex())
            return None
        frame_type = payload[0]
        if frame_type not in (FRAME_TYPE_BASIC, FRAME_TYPE_ENGINEERING):
            _LOGGER.debug("[%s] Unknown report type %s", self.address, frame_type)
            return None
        engineering = frame_type == FRAME_TYPE_ENGINEERING
        content = payload[2:-2]

        status = content[0]
        moving = status in (0x01, 0x03)
        stationary = status in (0x02, 0x03)
        result: dict[str, Any] = {
            "moving": moving,
            "stationary": stationary,
            "occupancy": moving or stationary,
            "engineering_mode": engineering,
            "data_type": "engineering" if engineering else "basic",
        }

        result["move_distance_cm"] = int.from_bytes(content[1:3], "little")
        result["move_energy"] = content[3]
        result["still_distance_cm"] = int.from_bytes(content[4:6], "little")
        result["still_energy"] = content[6]

        # Engineering: 7 basic + 2 max gates + 14 move + 14 static + light
        if engineering and len(content) >= 9 + 2 * GATES:
            gates = content[9 : 9 + 2 * GATES]
            for i in range(GATES):
                result[f"move_gate_{i}_energy"] = gates[i]
                result[f"static_gate_{i}_energy"] = gates[GATES + i]
            if len(content) > 9 + 2 * GATES:
                result["light_level"] = content[9 + 2 * GATES]
        elif not engineering:
            for key in GATE_ENERGY_KEYS:
                result[key] = None

        return result

    # -------------------------------------------------------------- commands

    def _fail_pending(self, ex: Exception) -> None:
        pending = self._pending_ack
        if pending and not pending[1].done():
            pending[1].set_exception(ex)
            # Mark retrieved so an unawaited failure is not logged by asyncio.
            pending[1].exception()

    async def _command(self, cmd: int, value: bytes = b"") -> bytes:
        """Send a command, return ACK data after the status word."""
        client = self._client
        if client is None or not client.is_connected:
            raise OperationError("Not connected")
        contents = cmd.to_bytes(2, "little") + value
        frame = (
            TX_HEADER + len(contents).to_bytes(2, "little") + contents + TX_FOOTER
        )
        future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self._pending_ack = ((cmd | 0x0100).to_bytes(2, "little"), future)
        try:
            await client.write_gatt_char(CHARACTERISTIC_WRITE, frame, False)
            async with asyncio.timeout(COMMAND_TIMEOUT):
                response = await future
        except TimeoutError:
            raise OperationError(f"Timeout waiting for ACK of 0x{cmd:04x}") from None
        finally:
            self._pending_ack = None
        if len(response) < 2:
            raise OperationError(f"Short ACK for 0x{cmd:04x}")
        status = int.from_bytes(response[:2], "little")
        if status != 0:
            raise OperationError(f"Command 0x{cmd:04x} failed with status {status}")
        return response[2:]

    @asynccontextmanager
    async def _config_session(self, end: bool = True) -> AsyncIterator[None]:
        """Run commands inside enable/end config; always leave config mode."""
        async with self._session_lock:
            for attempt in range(ENABLE_CFG_ATTEMPTS):
                try:
                    await self._command(CMD_ENABLE_CFG, b"\x01\x00")
                    break
                except OperationError:
                    if attempt == ENABLE_CFG_ATTEMPTS - 1 or not self.is_connected:
                        raise
                    await asyncio.sleep(0.3)
            try:
                yield
            finally:
                if end:
                    try:
                        await self._command(CMD_END_CFG)
                    except (OperationError, BleakError) as ex:
                        _LOGGER.debug("[%s] End config failed: %s", self.address, ex)

    async def end_config_mode(self) -> None:
        """Leave config mode (recovery if a previous session got stuck)."""
        async with self._session_lock:
            await self._command(CMD_END_CFG)

    async def _run(self, name: str, coro_fn: Callable[[], Any]) -> bool:
        """Run an operation and log failures; return success."""
        try:
            await coro_fn()
        except (OperationError, BleakError, TimeoutError) as ex:
            _LOGGER.error("[%s] %s failed: %s", self.address, name, ex)
            return False
        return True

    async def read_device_info(self) -> None:
        """Read firmware version and configuration from the module."""
        async with self._config_session():
            values: dict[str, Any] = {}
            fw = await self._command(CMD_READ_FIRMWARE)
            if len(fw) >= 8:
                fw_type = int.from_bytes(fw[0:2], "little")
                minor = "".join(f"{b:02x}" for b in reversed(fw[4:8]))
                values["firmware_version"] = f"V{fw[3]}.{fw[2]:02x}.{minor}"
                values["firmware_type"] = fw_type

            values.update(await self._read_config_values())
        self._update(values)
        _LOGGER.info(
            "[%s] Firmware %s", self.address, values.get("firmware_version")
        )

    async def _read_config_values(self) -> dict[str, Any]:
        """Read gates, timeout, polarity, resolution and sensitivities.

        Must run inside a config session.
        """
        values: dict[str, Any] = {}
        params = await self._command(CMD_READ_BASIC_PARAMS)
        if len(params) >= 4:
            values["min_gate"] = params[0]
            values["max_gate"] = params[1]
            values["unmanned_duration"] = int.from_bytes(params[2:4], "little")
            if len(params) >= 5:
                values["out_pin_polarity"] = params[4]
        try:
            resolution = await self._command(CMD_READ_RESOLUTION)
            if resolution:
                values["resolution"] = resolution[0]
        except OperationError as ex:
            _LOGGER.debug("[%s] Read resolution failed: %s", self.address, ex)
        for cmd, prefix in (
            (CMD_READ_MOTION_SENSITIVITY, "motion_sensitivity_gate_"),
            (CMD_READ_MOTIONLESS_SENSITIVITY, "motionless_sensitivity_gate_"),
        ):
            sens = await self._command(cmd)
            if len(sens) >= GATES:
                for i in range(GATES):
                    values[f"{prefix}{i}"] = sens[i]
        return values

    async def reload_config(self) -> None:
        """Read the configuration from the module again."""
        async with self._config_session():
            values = await self._read_config_values()
        self._update(values)

    async def write_config(
        self,
        min_gate: int,
        max_gate: int,
        unmanned_duration: int,
        out_pin_polarity: int,
        motion: list[int],
        motionless: list[int],
    ) -> None:
        """Write the whole configuration in one session and read it back."""
        if len(motion) != GATES or len(motionless) != GATES:
            raise OperationError(f"Sensitivity must have exactly {GATES} values")
        basic = (
            bytes([min_gate, max_gate])
            + unmanned_duration.to_bytes(2, "little")
            + bytes([out_pin_polarity])
        )
        async with self._config_session():
            await self._command(CMD_WRITE_BASIC_PARAMS, basic)
            await self._command(CMD_WRITE_MOTION_SENSITIVITY, bytes(motion))
            await self._command(CMD_WRITE_MOTIONLESS_SENSITIVITY, bytes(motionless))
            values = await self._read_config_values()
        self._update(values)
        _LOGGER.info("[%s] Configuration written", self.address)

    async def read_configuration(self) -> dict[str, Any]:
        """Read resolution and MAC (diagnostics, on demand)."""
        config: dict[str, Any] = {}
        async with self._config_session():
            resolution = await self._command(CMD_READ_RESOLUTION)
            if resolution:
                config["resolution"] = resolution[0]
            mac = await self._command(CMD_READ_MAC, b"\x01\x00")
            if len(mac) >= 6:
                config["mac_address"] = ":".join(f"{b:02X}" for b in mac[:6])
        return config

    async def set_engineering_mode(self, enable: bool) -> None:
        """Switch engineering (per-gate energy) reporting on or off."""
        async with self._config_session():
            await self._command(
                CMD_ENABLE_ENGINEERING if enable else CMD_DISABLE_ENGINEERING
            )

    async def enable_engineering_mode(self) -> bool:
        """Enable engineering mode."""
        return await self._run(
            "Enable engineering mode", lambda: self.set_engineering_mode(True)
        )

    async def disable_engineering_mode(self) -> bool:
        """Disable engineering mode."""
        return await self._run(
            "Disable engineering mode", lambda: self.set_engineering_mode(False)
        )

    async def query_calibration_status(self) -> bool:
        """Query if background calibration is running."""
        async with self._config_session():
            response = await self._command(CMD_QUERY_CALIBRATION)
        active = len(response) >= 2 and int.from_bytes(response[:2], "little") == 1
        self._update({"calibration_active": active})
        return active

    async def _poll_calibration_status(self) -> None:
        """Poll calibration status until it finishes (max ~30 s)."""
        try:
            for _ in range(15):
                await asyncio.sleep(2)
                try:
                    if not await self.query_calibration_status():
                        _LOGGER.info("[%s] Calibration completed", self.address)
                        break
                except (OperationError, BleakError, TimeoutError) as ex:
                    _LOGGER.debug("[%s] Calibration query failed: %s", self.address, ex)
        finally:
            self._calibration_poll_task = None
            self._update({"calibration_active": False})

    async def start_calibration(self) -> bool:
        """Start dynamic background correction."""

        async def _start() -> None:
            async with self._config_session():
                await self._command(CMD_START_CALIBRATION)

        if not await self._run("Start calibration", _start):
            return False
        _LOGGER.info("[%s] Calibration started", self.address)
        self._update({"calibration_active": True})
        if self._calibration_poll_task:
            self._calibration_poll_task.cancel()
        self._calibration_poll_task = asyncio.create_task(
            self._poll_calibration_status()
        )
        return True

    async def _restart(self) -> None:
        # Restart leaves config mode by itself; the module drops the BLE link.
        async with self._config_session(end=False):
            await self._command(CMD_RESTART_MODULE)

    async def restart_module(self) -> bool:
        """Restart the module."""
        return await self._run("Restart module", self._restart)

    async def factory_reset(self) -> bool:
        """Restore factory settings and restart module."""

        async def _reset() -> None:
            async with self._config_session():
                await self._command(CMD_FACTORY_RESET)
            for key in CONFIG_KEYS:
                self._data.pop(key, None)
            await self._restart()

        # Config is read again automatically after reconnect.
        return await self._run("Factory reset", _reset)

    async def write_basic_params(
        self, min_gate: int, max_gate: int, unmanned_duration: int, out_pin_polarity: int
    ) -> bool:
        """Write basic parameters to device."""
        value = (
            bytes([min_gate, max_gate])
            + unmanned_duration.to_bytes(2, "little")
            + bytes([out_pin_polarity])
        )

        async def _write() -> None:
            async with self._config_session():
                await self._command(CMD_WRITE_BASIC_PARAMS, value)

        return await self._run("Write basic params", _write)

    async def _write_sensitivity(self, cmd: int, sensitivities: list[int]) -> None:
        if len(sensitivities) != GATES:
            raise OperationError(f"Sensitivity must have exactly {GATES} values")
        async with self._config_session():
            await self._command(cmd, bytes(sensitivities))

    async def write_motion_sensitivity(self, sensitivities: list[int]) -> bool:
        """Write motion sensitivity for all 14 gates."""
        return await self._run(
            "Write motion sensitivity",
            lambda: self._write_sensitivity(
                CMD_WRITE_MOTION_SENSITIVITY, sensitivities
            ),
        )

    async def write_motionless_sensitivity(self, sensitivities: list[int]) -> bool:
        """Write motionless sensitivity for all 14 gates."""
        return await self._run(
            "Write motionless sensitivity",
            lambda: self._write_sensitivity(
                CMD_WRITE_MOTIONLESS_SENSITIVITY, sensitivities
            ),
        )
