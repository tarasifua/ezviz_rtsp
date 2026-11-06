"""Support EZVIZ last motion image."""

import logging
from datetime import datetime
from typing import override

from homeassistant.components.image import Image, ImageEntity, ImageEntityDescription
from homeassistant.config_entries import SOURCE_IGNORE
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util
from propcache.api import cached_property
from pyezvizapi.exceptions import PyEzvizError
from pyezvizapi.utils import decrypt_image

from .const import DOMAIN, SIGNAL_PICTURE_CAPTURED
from .coordinator import EzvizConfigEntry, EzvizDataUpdateCoordinator
from .entity import EzvizEntity

_LOGGER = logging.getLogger(__name__)

IMAGE_TYPE = ImageEntityDescription(
    key="last_motion_image",
    translation_key="last_motion_image",
)
# The picture taken on demand by the capture_picture camera service
SNAPSHOT_TYPE = ImageEntityDescription(
    key="snapshot",
    translation_key="snapshot",
)


def _parse_last_alarm_time(last_alarm_time: object) -> datetime | None:
    """Parse the last alarm time from the coordinator payload."""
    if not isinstance(last_alarm_time, str):
        return None
    return dt_util.parse_datetime(last_alarm_time)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EzvizConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EZVIZ image entities based on a config entry."""

    coordinator = entry.runtime_data

    async_add_entities(
        EzvizLastMotion(hass, coordinator, camera) for camera in coordinator.data
    )
    async_add_entities(
        EzvizSnapshot(hass, coordinator, camera) for camera in coordinator.data
    )


class EzvizLastMotion(EzvizEntity, ImageEntity):
    """Return Last Motion Image from Ezviz Camera."""

    def __init__(
        self, hass: HomeAssistant, coordinator: EzvizDataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize a image entity."""
        EzvizEntity.__init__(self, coordinator, serial)
        ImageEntity.__init__(self, hass)
        self._attr_unique_id = f"{serial}_{IMAGE_TYPE.key}"
        self.entity_description = IMAGE_TYPE
        last_alarm_pic = self.data.get("last_alarm_pic")
        self._attr_image_url = (
            last_alarm_pic if isinstance(last_alarm_pic, str) else None
        )
        self._attr_image_last_updated = _parse_last_alarm_time(
            self.data.get("last_alarm_time")
        )
        camera = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, serial)
        self.alarm_image_password = (
            camera.data[CONF_PASSWORD]
            if camera and camera.source != SOURCE_IGNORE
            else None
        )

    @cached_property
    @override
    def available(self) -> bool:
        """Entity gets data from ezviz API so always available."""
        return True

    @override
    async def _async_load_image_from_url(self, url: str) -> Image | None:
        """Load an image by url."""
        if not url:
            return None
        if response := await self._fetch_url(url):
            image_data = response.content
            if self.data["encrypted"] and self.alarm_image_password is not None:
                try:
                    image_data = decrypt_image(
                        response.content, self.alarm_image_password
                    )
                except PyEzvizError:
                    _LOGGER.warning(
                        "%s: Can't decrypt last alarm picture,"
                        " looks like it was encrypted"
                        " with other password",
                        self.entity_id,
                    )
                    image_data = response.content
            return Image(
                content=image_data,
                content_type="image/jpeg",  # Actually returns binary/octet-stream
            )
        return None

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        last_alarm_pic = self.data.get("last_alarm_pic")
        if last_alarm_pic and last_alarm_pic != self._attr_image_url:
            _LOGGER.debug("Image url changed to %s", last_alarm_pic)

            self._attr_image_url = last_alarm_pic
            self._cached_image = None
            self._attr_image_last_updated = _parse_last_alarm_time(
                self.data.get("last_alarm_time")
            )

        super()._handle_coordinator_update()


class EzvizSnapshot(EzvizLastMotion):
    """Picture taken on demand with the camera's capture_picture service.

    It changes only when capture_picture runs; the coordinator's last alarm picture is ignored. The
    picture is kept in memory only, so it is empty again after a restart or reload until the next capture.
    """

    def __init__(
        self, hass: HomeAssistant, coordinator: EzvizDataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the snapshot image entity."""
        super().__init__(hass, coordinator, serial)
        self.entity_description = SNAPSHOT_TYPE
        self._attr_unique_id = f"{serial}_{SNAPSHOT_TYPE.key}"
        self._attr_image_url = None
        self._attr_image_last_updated = None

    async def async_added_to_hass(self) -> None:
        """Listen for pictures captured by the camera entity."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_PICTURE_CAPTURED.format(self._serial),
                self._handle_picture_captured,
            )
        )

    @callback
    def _handle_picture_captured(self, pic_url: str) -> None:
        self._attr_image_url = pic_url
        self._cached_image = None
        self._attr_image_last_updated = dt_util.utcnow()
        self.async_write_ha_state()

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Skip the last-alarm-picture sync of the parent; just refresh the state."""
        super(EzvizLastMotion, self)._handle_coordinator_update()
