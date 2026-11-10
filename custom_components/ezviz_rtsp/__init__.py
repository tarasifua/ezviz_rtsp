"""Support for EZVIZ camera."""

import hashlib
import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http.server import StaticPathConfig
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import CONF_TIMEOUT, CONF_TYPE, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration
from pyezvizapi.client import EzvizClient
from pyezvizapi.exceptions import (
    EzvizAuthTokenExpired,
    EzvizAuthVerificationCode,
    HTTPError,
    InvalidURL,
    PyEzvizError,
)

from .const import (
    ATTR_TYPE_CAMERA,
    ATTR_TYPE_CLOUD,
    CARD_FILENAME,
    CARD_URL,
    CONF_FFMPEG_ARGUMENTS,
    CONF_RFSESSION_ID,
    CONF_SESSION_ID,
    DATA_CARD,
    DEFAULT_FFMPEG_ARGUMENTS,
    DEFAULT_TIMEOUT,
    DOMAIN,
    HLS_FILENAME,
    HLS_URL,
)
from .coordinator import EzvizConfigEntry, EzvizDataUpdateCoordinator
from .live import async_close_live_streams, async_setup_live_streams
from .recordings import async_close_store

_LOGGER = logging.getLogger(__name__)

PLATFORMS_BY_TYPE: dict[str, list] = {
    ATTR_TYPE_CAMERA: [],
    ATTR_TYPE_CLOUD: [
        Platform.ALARM_CONTROL_PANEL,
        Platform.BINARY_SENSOR,
        Platform.BUTTON,
        Platform.CAMERA,
        Platform.IMAGE,
        Platform.LIGHT,
        Platform.NUMBER,
        Platform.SELECT,
        Platform.SENSOR,
        Platform.SIREN,
        Platform.SWITCH,
        Platform.UPDATE,
    ],
}


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the Lovelace card and register its websocket command, once."""
    if hass.data.get(DATA_CARD):
        return
    hass.data[DATA_CARD] = True

    frontend = Path(__file__).parent / "frontend"
    card = frontend / CARD_FILENAME
    hls = frontend / HLS_FILENAME
    content = await hass.async_add_executor_job(card.read_bytes)
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(CARD_URL, str(card), True),
            StaticPathConfig(HLS_URL, str(hls), True),
        ]
    )
    # The file is served with a long cache, so the URL carries a hash of its
    # content: any change to the card reaches browsers on the next page load.
    # The integration version rides along, so the card can print it in the
    # console and it can never drift from the manifest.
    integration = await async_get_integration(hass, DOMAIN)
    version = integration.version or "?"
    query = f"v={hashlib.sha256(content).hexdigest()[:12]}&version={version}"
    add_extra_js_url(hass, f"{CARD_URL}?{query}")

    from .websocket import async_register_commands

    async_register_commands(hass)


async def async_setup_entry(hass: HomeAssistant, entry: EzvizConfigEntry) -> bool:
    """Set up EZVIZ from a config entry."""
    sensor_type: str = entry.data[CONF_TYPE]
    ezviz_client = None

    if not entry.options:
        options = {
            CONF_FFMPEG_ARGUMENTS: DEFAULT_FFMPEG_ARGUMENTS,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
        }

        hass.config_entries.async_update_entry(entry, options=options)

    # Initialize EZVIZ cloud entities
    if PLATFORMS_BY_TYPE[sensor_type]:
        # Initiate reauth config flow if account token if not present.
        if not entry.data.get(CONF_SESSION_ID):
            raise ConfigEntryAuthFailed

        ezviz_client = EzvizClient(
            token={
                CONF_SESSION_ID: entry.data.get(CONF_SESSION_ID),
                CONF_RFSESSION_ID: entry.data.get(CONF_RFSESSION_ID),
                "api_url": entry.data.get(CONF_URL),
            },
            timeout=entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
        )

        try:
            await hass.async_add_executor_job(ezviz_client.login)

        except (EzvizAuthTokenExpired, EzvizAuthVerificationCode) as error:
            raise ConfigEntryAuthFailed from error

        except (InvalidURL, HTTPError, PyEzvizError) as error:
            _LOGGER.error("Unable to connect to Ezviz service: %s", str(error))
            raise ConfigEntryNotReady from error

        coordinator = EzvizDataUpdateCoordinator(
            hass, entry, api=ezviz_client, api_timeout=entry.options[CONF_TIMEOUT]
        )

        await coordinator.async_config_entry_first_refresh()

        entry.runtime_data = coordinator
        # One cloud live stream per camera, for cameras that expose no local RTSP.
        async_setup_live_streams(hass, entry, coordinator)
        # Ship the card that plays those streams.
        await _async_register_card(hass)

    # Check EZVIZ cloud account entity is present, reload
    # cloud account entities for camera entity change
    # to take effect.
    # Cameras are accessed via local RTSP stream with unique credentials per camera.
    # Separate camera entities allow for credential changes per camera.
    if sensor_type == ATTR_TYPE_CAMERA:
        for item in hass.config_entries.async_loaded_entries(domain=DOMAIN):
            if item.data.get(CONF_TYPE) == ATTR_TYPE_CLOUD:
                _LOGGER.debug("Reload Ezviz main account with camera entry")
                await hass.config_entries.async_reload(item.entry_id)
                return True

    await hass.config_entries.async_forward_entry_setups(
        entry, PLATFORMS_BY_TYPE[sensor_type]
    )

    # Remove any existing last_alarm_pic sensor entities that were migrated away.
    if sensor_type == ATTR_TYPE_CLOUD:
        entity_registry = er.async_get(hass)
        entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        for entity_entry in entries:
            unique_id = entity_entry.unique_id
            if (
                entity_entry.domain == SENSOR_DOMAIN
                and unique_id is not None
                and unique_id.endswith(".last_alarm_pic")
            ):
                entity_registry.async_remove(entity_entry.entity_id)
                _LOGGER.debug(
                    "Removed legacy last_alarm_pic sensor entity: %s",
                    entity_entry.entity_id,
                )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: EzvizConfigEntry) -> bool:
    """Unload a config entry."""
    sensor_type = entry.data[CONF_TYPE]

    if sensor_type == ATTR_TYPE_CLOUD:
        await async_close_live_streams(entry.runtime_data)

    unloaded = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS_BY_TYPE[sensor_type]
    )
    if unloaded and sensor_type == ATTR_TYPE_CLOUD and not any(
        other.entry_id != entry.entry_id and other.data.get(CONF_TYPE) == ATTR_TYPE_CLOUD
        for other in hass.config_entries.async_loaded_entries(DOMAIN)
    ):
        # The last account is going: drop the cached recordings and their files.
        await async_close_store(hass)
    return unloaded
