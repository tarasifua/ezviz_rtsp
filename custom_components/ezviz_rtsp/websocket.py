"""Websocket commands the shipped Lovelace card uses.

The card can be configured with a ``serial`` instead of an entity id, so it
needs a way to map a camera serial to the camera entity of the loaded account.
"""

from __future__ import annotations

import time
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
from .live import CARD_MJPEG_TTL, card_mjpeg_path, find_stream
from .picture import shape_for
from .recordings import (
    DATA_RECORDINGS,
    FORMATS,
    RecordingError,
    async_clip_states,
    async_get_clip,
    async_get_store,
    async_get_temp_clip,
    async_list_day,
    async_month_days,
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
    async_register_command(hass, ws_live_stop)
    async_register_command(hass, ws_live_status)
    async_register_command(hass, ws_recordings)
    async_register_command(hass, ws_recording_days)
    async_register_command(hass, ws_recording_progress)
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
            shape = shape_for(hass, serial)
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
                    # The picture's shape, so the card sizes its box before the
                    # picture loads instead of growing a moment later.
                    "picture_width": shape[0] if shape else None,
                    "picture_height": shape[1] if shape else None,
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
        vol.Required("type"): f"{DOMAIN}/live/stop",
        vol.Required("serial"): str,
    }
)
@async_response
async def ws_live_stop(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Release a camera's live stream at once, for another use of the camera.

    The card drops its own picture when the recordings view opens, but the
    integration holds the cloud session open for the configured release delay so
    a quick re-open does not wake the camera again. SD playback needs the camera
    to itself, so the card asks for the session to go now, not after that delay.
    """
    stream = find_stream(hass, msg["serial"])
    stopped = await stream.async_stop() if stream is not None else False
    connection.send_result(msg["id"], {"stopped": stopped})


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/live/status",
        vol.Required("serial"): str,
    }
)
@async_response
async def ws_live_status(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Whether a live start of this camera is waiting for the SD card.

    The card shows "Waiting for the download to finish…" before "Waking the
    camera…" while a recording is still coming off the card, so it asks here
    rather than starting a stream that would only sit in the queue.
    """
    serial = msg["serial"]
    stream = find_stream(hass, serial)
    store = hass.data.get(DATA_RECORDINGS)
    waiting = bool(stream is not None and stream.waiting)
    if store is not None and store.downloading(serial):
        waiting = True
    connection.send_result(msg["id"], {"waiting": waiting})


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
    states = await async_clip_states(hass, camera.serial, recordings)
    rows = [
        {
            "begin": utc_stamp(begin),
            "end": utc_stamp(end),
            "start": begin.isoformat(),
            "seconds": int((end - begin).total_seconds()),
            "local": local,
            "incomplete": incomplete,
        }
        for (begin, end), (local, incomplete) in zip(recordings, states)
    ]
    rows.reverse()
    connection.send_result(
        msg["id"],
        {
            "serial": camera.serial,
            "date": day.isoformat(),
            "today": datetime.now(tz).date().isoformat(),
            "complete": complete,
            "recordings": rows,
        },
    )


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/recording/days",
        vol.Required("serial"): str,
        vol.Required("month"): str,  # YYYY-MM
        # Ask the camera about every day; without it only local and cached days
        # (and days already looked at this run) are returned.
        vol.Optional("scan", default=False): bool,
    }
)
@async_response
async def ws_recording_days(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Which days of a month have recordings, for the card's calendar."""
    camera = find_camera(hass, msg["serial"])
    if camera is None:
        connection.send_error(msg["id"], "not_found", "Camera not found in a loaded account")
        return
    try:
        parts = msg["month"].split("-")
        if len(parts) != 2:
            raise ValueError
        year, month = (int(part) for part in parts)
        date(year, month, 1)
    except (TypeError, ValueError):
        connection.send_error(msg["id"], "invalid_format", "month must be YYYY-MM")
        return
    now = datetime.now(ZoneInfo(hass.config.time_zone))
    if (year, month) > (now.year, now.month):
        connection.send_error(msg["id"], "invalid_format", "The month is in the future")
        return
    try:
        result = await async_month_days(hass, camera, year, month, scan=msg["scan"])
    except RecordingError as err:
        connection.send_error(msg["id"], "days_failed", str(err))
        return
    connection.send_result(
        msg["id"],
        {"serial": camera.serial, "month": msg["month"], **result},
    )


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/recording/progress",
        vol.Required("serial"): str,
        vol.Required("begin"): str,
        vol.Required("end"): str,
        vol.Optional("format", default="h264"): vol.In(FORMATS),
    }
)
@async_response
async def ws_recording_progress(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """How far a clip that is being fetched from the camera has got."""
    store = await async_get_store(hass)
    state = store.progress.get((msg["serial"], msg["begin"], msg["end"], msg["format"]))
    if state is None:
        connection.send_result(msg["id"], {"active": False})
        return
    started = float(state.get("started") or time.monotonic())
    connection.send_result(
        msg["id"],
        {
            "active": True,
            "stage": state.get("stage", "downloading"),
            "delivered": round(float(state.get("delivered") or 0.0), 1),
            "total": round(float(state.get("total") or 0.0), 1),
            "attempt": int(state.get("attempt") or 1),
            "elapsed": round(time.monotonic() - started, 1),
        },
    )


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/recording/clip",
        vol.Required("serial"): str,
        vol.Required("begin"): str,
        vol.Required("end"): str,
        vol.Optional("format", default="h264"): vol.In(FORMATS),
        # Keep the clip in the media folder (default), or fetch a temporary copy
        # that is deleted after a couple of hours and never shows under Media.
        vol.Optional("keep", default=True): bool,
    }
)
@async_response
async def ws_recording_clip(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Fetch one recording from the camera (or the cache) and hand out its address.

    Waits until the MP4 is ready, so the card can show progress and errors; the
    address is a short-lived signed path to the authenticated clip view. With
    ``keep`` off the clip is not stored in the media folder; ``saved`` in the
    answer says whether a permanent copy exists (now or from an earlier play).
    """
    camera = find_camera(hass, msg["serial"])
    if camera is None:
        connection.send_error(msg["id"], "not_found", "Camera not found in a loaded account")
        return
    saved = True
    try:
        begin, end = parse_stamp(msg["begin"]), parse_stamp(msg["end"])
        if msg["keep"]:
            await async_get_clip(hass, camera, begin, end, msg["format"])
        else:
            _, saved = await async_get_temp_clip(hass, camera, begin, end, msg["format"])
    except RecordingError as err:
        connection.send_error(msg["id"], "recording_failed", str(err))
        return
    path = clip_path(camera.serial, utc_stamp(begin), utc_stamp(end), msg["format"])
    connection.send_result(
        msg["id"],
        {
            "url": async_sign_path(hass, path, CLIP_URL_TTL),
            "format": msg["format"],
            "saved": saved,
        },
    )


# How long a clip's signed address stays valid; the player keeps it while open.
CLIP_URL_TTL = timedelta(hours=1)
