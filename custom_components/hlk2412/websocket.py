"""Websocket API used by the hlk2412 Lovelace card."""

from __future__ import annotations

import time
from typing import Any

from bleak.exc import BleakError
import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import DataCoordinator
from .device import GATES, RESOLUTIONS, STATE_KEYS, OperationError

# Live frames are pushed at most this often per subscription (presence
# changes are pushed immediately).
LIVE_INTERVAL = 0.2
PRESENCE_KEYS = ("moving", "stationary", "occupancy")

_SENSITIVITY = vol.All([vol.All(int, vol.Range(min=0, max=100))], vol.Length(GATES, GATES))


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register websocket commands."""
    websocket_api.async_register_command(hass, ws_devices)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_write_config)
    websocket_api.async_register_command(hass, ws_reload_config)
    websocket_api.async_register_command(hass, ws_engineering)
    websocket_api.async_register_command(hass, ws_calibrate)


def _coordinator(hass: HomeAssistant, entry_id: str) -> DataCoordinator:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise OperationError("Unknown HLK-2412 entry")
    if entry.state is not ConfigEntryState.LOADED:
        raise OperationError(f"{entry.title} is not loaded")
    return entry.runtime_data


def _name(hass: HomeAssistant, unique_id: str | None, fallback: str) -> str:
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, unique_id)})
    if device is None:
        return fallback
    return device.name_by_user or device.name or fallback


def _state(hass: HomeAssistant, coordinator: DataCoordinator) -> dict[str, Any]:
    device = coordinator.device
    data = device.data
    state = {key: data.get(key) for key in STATE_KEYS}
    state["connected"] = device.is_connected
    state["title"] = _name(hass, coordinator.base_unique_id, coordinator.device_name)
    state["gates"] = GATES
    state["gate_size"] = RESOLUTIONS.get(data.get("resolution"), 0.75)
    return state


@websocket_api.websocket_command({vol.Required("type"): "hlk2412/devices"})
@callback
def ws_devices(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """List configured radars."""
    result = [
        {
            "entry_id": entry.entry_id,
            "title": _name(hass, entry.unique_id, entry.title),
            "address": entry.unique_id,
            "loaded": entry.state is ConfigEntryState.LOADED,
        }
        for entry in hass.config_entries.async_entries(DOMAIN)
    ]
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {vol.Required("type"): "hlk2412/subscribe", vol.Required("entry_id"): str}
)
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Stream live report frames and config/connection changes."""
    try:
        coordinator = _coordinator(hass, msg["entry_id"])
    except OperationError as ex:
        connection.send_error(msg["id"], "not_found", str(ex))
        return
    device = coordinator.device
    msg_id = msg["id"]
    last_sent = 0.0
    last_presence: tuple = ()

    @callback
    def on_frame(frame: dict[str, Any]) -> None:
        nonlocal last_sent, last_presence
        now = time.monotonic()
        presence = tuple(frame.get(key) for key in PRESENCE_KEYS)
        if presence == last_presence and now - last_sent < LIVE_INTERVAL:
            return
        last_sent = now
        last_presence = presence
        connection.send_message(
            websocket_api.event_message(msg_id, {"live": frame})
        )

    @callback
    def on_state() -> None:
        connection.send_message(
            websocket_api.event_message(msg_id, {"state": _state(hass, coordinator)})
        )

    unsub_frames = device.subscribe_frames(on_frame)
    unsub_state = device.subscribe_state(on_state)

    @callback
    def unsubscribe() -> None:
        unsub_frames()
        unsub_state()

    connection.subscriptions[msg_id] = unsubscribe
    connection.send_result(msg_id)
    on_state()


async def _run(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
    action,
) -> None:
    try:
        coordinator = _coordinator(hass, msg["entry_id"])
        await action(coordinator.device)
    except (OperationError, BleakError, TimeoutError) as ex:
        connection.send_error(msg["id"], "failed", str(ex) or type(ex).__name__)
        return
    connection.send_result(msg["id"], _state(hass, coordinator))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "hlk2412/write_config",
        vol.Required("entry_id"): str,
        vol.Required("min_gate"): vol.All(int, vol.Range(min=0, max=GATES - 1)),
        # max_gate is a gate count on the radar (14 = up to gate 13).
        vol.Required("max_gate"): vol.All(int, vol.Range(min=1, max=GATES)),
        vol.Required("unmanned_duration"): vol.All(int, vol.Range(min=0, max=65535)),
        vol.Required("out_pin_polarity"): vol.In([0, 1]),
        vol.Required("motion"): _SENSITIVITY,
        vol.Required("motionless"): _SENSITIVITY,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_write_config(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Write gates, timeout, polarity and all sensitivities."""
    if msg["min_gate"] >= msg["max_gate"]:
        connection.send_error(msg["id"], "invalid", "min_gate >= max_gate")
        return
    await _run(
        hass,
        connection,
        msg,
        lambda device: device.write_config(
            msg["min_gate"],
            msg["max_gate"],
            msg["unmanned_duration"],
            msg["out_pin_polarity"],
            msg["motion"],
            msg["motionless"],
        ),
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "hlk2412/reload_config", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def ws_reload_config(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Read configuration from the module again."""
    await _run(hass, connection, msg, lambda device: device.reload_config())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "hlk2412/engineering",
        vol.Required("entry_id"): str,
        vol.Required("enable"): cv.boolean,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_engineering(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Switch engineering mode."""
    await _run(
        hass, connection, msg, lambda device: device.set_engineering_mode(msg["enable"])
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "hlk2412/calibrate", vol.Required("entry_id"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_calibrate(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Start background calibration."""

    async def start(device) -> None:
        if not await device.start_calibration():
            raise OperationError("Calibration failed to start")

    await _run(hass, connection, msg, start)
