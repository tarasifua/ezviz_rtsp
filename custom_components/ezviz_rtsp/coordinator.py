"""Provides the ezviz DataUpdateCoordinator."""

import asyncio
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .pyezvizapi.client import EzvizClient
from .pyezvizapi.exceptions import (
    EzvizAuthTokenExpired,
    EzvizAuthVerificationCode,
    HTTPError,
    InvalidURL,
    PyEzvizError,
)

if TYPE_CHECKING:
    from .live import LiveStream

_LOGGER = logging.getLogger(__name__)

type EzvizConfigEntry = ConfigEntry[EzvizDataUpdateCoordinator]


class EzvizDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching EZVIZ data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: EzvizConfigEntry,
        *,
        api: EzvizClient,
        api_timeout: int,
    ) -> None:
        """Initialize global EZVIZ data updater."""
        self.ezviz_client = api
        self._api_timeout = api_timeout
        # Cloud live streams per serial, for cameras with no local RTSP.
        self.live_streams: dict[str, LiveStream] = {}
        # capture_picture throttle per serial: (when the last capture started,
        # its picture URL). Shared by the camera service, the Snapshot button
        # and the cards' automatic requests, so a press followed by a dashboard
        # opening does not wake the camera twice.
        self.snapshot_captures: dict[str, tuple[float | None, str | None]] = {}
        update_interval = timedelta(seconds=30)

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=update_interval,
        )

    @override
    async def _async_update_data(self) -> dict:
        """Fetch data from EZVIZ."""
        try:
            async with asyncio.timeout(self._api_timeout):
                return await self.hass.async_add_executor_job(
                    self.ezviz_client.load_cameras
                )

        except (EzvizAuthTokenExpired, EzvizAuthVerificationCode) as error:
            raise ConfigEntryAuthFailed from error

        except (InvalidURL, HTTPError, PyEzvizError) as error:
            raise UpdateFailed(f"Invalid response from API: {error}") from error

        except TimeoutError as error:
            # asyncio.timeout raises a bare TimeoutError; without this it reaches
            # DataUpdateCoordinator as an unexpected error and logs a traceback
            # every interval instead of a clean "update failed".
            raise UpdateFailed(f"The EZVIZ API did not answer in time: {error}") from error
