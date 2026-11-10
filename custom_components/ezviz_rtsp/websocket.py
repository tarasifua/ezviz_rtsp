"""Websocket commands the shipped Lovelace card uses.

The card can be configured with a ``serial`` instead of an entity id, so it
needs a way to map a camera serial to the camera entity of the loaded account.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import probatio as vol
from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import async_response, websocket_command
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import CONF_CODES, DATA_WS, DOMAIN
from .live import CARD_MJPEG_TTL, card_mjpeg_path
from .recordings import (
    FORMATS,
    RecordingError,
    async_get_clip,
    async_list_day,
    clip_path,
    find_camera,
    parse_stamp,
    utc_stamp,
)


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register the card's websocket command once."""
    if hass.data.get(DATA_WS):
        return
    hass.data[DATA_WS] = True
    async_register_command(hass, ws_get_devices)
    async_register_command(hass, ws_recordings)
    async_register_command(hass, ws_recording_clip)


def _loaded_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


def _battery_entity_id(registry: er.EntityRegistry, serial: str) -> str | None:
    """The battery sensor of a camera, so the card can show its charge."""
    suffix = ".battery_level"
    for entity in registry.entities.values():
        unique_id = entity.unique_id or ""
        if entity.platform == DOMAIN and entity.domain == "sensor" and unique_id.startswith(f"{serial}_") and unique_id.endswith(suffix):
            return entity.entity_id
    return None


@websocket_command({vol.Required("type"): f"{DOMAIN}/devices"})
@async_response
async def ws_get_devices(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """List the cloud cameras of every loaded account, for the card and its editor."""
    registry = er.async_get(hass)
    devices: list[dict[str, Any]] = []
    for entry in _loaded_entries(hass):
        codes = entry.options.get(CONF_CODES, {})
        data = getattr(getattr(entry, "runtime_data", None), "data", None) or {}
        for serial, value in data.items():
            devices.append(
                {
                    "entry_id": entry.entry_id,
                    "serial": serial,
                    "name": value.get("name") or serial,
                    "encrypted": bool(value.get("encrypted")),
                    "has_code": serial in codes,
                    "battery": value.get("battery_level") is not None,
                    "battery_level": value.get("battery_level"),
                    "battery_entity_id": _battery_entity_id(registry, serial),
                    "entity_id": registry.async_get_entity_id("camera", DOMAIN, serial),
                    # The card drops this straight into an <img> for a fast start.
                    # It is a short-lived signed URL to the authenticated picture
                    # view, so it cannot be reused after it expires or the user
                    # is removed.
                    "mjpeg_url": async_sign_path(
                        hass, card_mjpeg_path(serial), CARD_MJPEG_TTL
                    ),
                }
            )
    connection.send_result(msg["id"], devices)


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/recordings",
        vol.Required("serial"): str,
        # A local calendar day, YYYY-MM-DD; today when left out.
        vol.Optional("date"): str,
        # Search the camera again instead of answering from the cache.
        vol.Optional("refresh", default=False): bool,
    }
)
@async_response
async def ws_recordings(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """The SD-card recordings of one camera on one local day, newest first."""
    camera = find_camera(hass, msg["serial"])
    if camera is None:
        connection.send_error(msg["id"], "not_found", "Camera not found in a loaded account")
        return
    tz = ZoneInfo(hass.config.time_zone)
    try:
        day = date.fromisoformat(msg["date"]) if msg.get("date") else datetime.now(tz).date()
    except ValueError:
        connection.send_error(msg["id"], "invalid_format", "date must be YYYY-MM-DD")
        return
    try:
        recordings, complete = await async_list_day(hass, camera, day, refresh=msg["refresh"])
    except RecordingError as err:
        connection.send_error(msg["id"], "recordings_failed", str(err))
        return
    connection.send_result(
        msg["id"],
        {
            "serial": camera.serial,
            "date": day.isoformat(),
            "today": datetime.now(tz).date().isoformat(),
            "complete": complete,
            "recordings": [
                {
                    "begin": utc_stamp(begin),
                    "end": utc_stamp(end),
                    "start": begin.isoformat(),
                    "seconds": int((end - begin).total_seconds()),
                }
                for begin, end in reversed(recordings)
            ],
        },
    )


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/recording/clip",
        vol.Required("serial"): str,
        vol.Required("begin"): str,
        vol.Required("end"): str,
        vol.Optional("format", default="h264"): vol.In(FORMATS),
    }
)
@async_response
async def ws_recording_clip(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Fetch one recording from the camera (or the cache) and hand out its address.

    Waits until the MP4 is ready, so the card can show progress and errors; the
    address is a short-lived signed path to the authenticated clip view.
    """
    camera = find_camera(hass, msg["serial"])
    if camera is None:
        connection.send_error(msg["id"], "not_found", "Camera not found in a loaded account")
        return
    try:
        begin, end = parse_stamp(msg["begin"]), parse_stamp(msg["end"])
        await async_get_clip(hass, camera, begin, end, msg["format"])
    except RecordingError as err:
        connection.send_error(msg["id"], "recording_failed", str(err))
        return
    path = clip_path(camera.serial, utc_stamp(begin), utc_stamp(end), msg["format"])
    connection.send_result(
        msg["id"], {"url": async_sign_path(hass, path, CLIP_URL_TTL), "format": msg["format"]}
    )


# How long a clip's signed address stays valid; the player keeps it while open.
CLIP_URL_TTL = timedelta(hours=1)
