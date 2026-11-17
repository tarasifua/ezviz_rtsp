"""Support for EZVIZ button controls."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .camera import async_request_snapshot
from .coordinator import EzvizConfigEntry, EzvizDataUpdateCoordinator
from .entity import EzvizEntity
from .pyezvizapi import EzvizClient
from .pyezvizapi.constants import SupportExt
from .pyezvizapi.exceptions import HTTPError, PyEzvizError
from .recordings import RecordingError, async_download_latest, find_camera

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class EzvizButtonEntityDescription(ButtonEntityDescription):
    """Describe a EZVIZ Button."""

    method: Callable[[EzvizClient, str, str], Any]
    supported_ext: str


BUTTON_ENTITIES = (
    EzvizButtonEntityDescription(
        key="ptz_up",
        translation_key="ptz_up",
        method=lambda pyezviz_client, serial, run: pyezviz_client.ptz_control(
            "UP", serial, run
        ),
        supported_ext=str(SupportExt.SupportPtz.value),
    ),
    EzvizButtonEntityDescription(
        key="ptz_down",
        translation_key="ptz_down",
        method=lambda pyezviz_client, serial, run: pyezviz_client.ptz_control(
            "DOWN", serial, run
        ),
        supported_ext=str(SupportExt.SupportPtz.value),
    ),
    EzvizButtonEntityDescription(
        key="ptz_left",
        translation_key="ptz_left",
        method=lambda pyezviz_client, serial, run: pyezviz_client.ptz_control(
            "LEFT", serial, run
        ),
        supported_ext=str(SupportExt.SupportPtz.value),
    ),
    EzvizButtonEntityDescription(
        key="ptz_right",
        translation_key="ptz_right",
        method=lambda pyezviz_client, serial, run: pyezviz_client.ptz_control(
            "RIGHT", serial, run
        ),
        supported_ext=str(SupportExt.SupportPtz.value),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EzvizConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EZVIZ button based on a config entry."""
    coordinator = entry.runtime_data

    # Add button entities if supportExt value indicates PTZ capbility.
    # Could be missing or "0" for unsupported.
    # If present with value of "1" then add button entity.

    async_add_entities(
        EzvizButtonEntity(coordinator, camera, entity_description)
        for camera in coordinator.data
        for capability, value in coordinator.data[camera]["supportExt"].items()
        for entity_description in BUTTON_ENTITIES
        if capability == entity_description.supported_ext
        if value == "1"
    )
    # Every cloud camera can take a picture on demand, whatever its PTZ support.
    async_add_entities(
        EzvizSnapshotButton(coordinator, camera) for camera in coordinator.data
    )
    # ... and can download its latest SD-card recording into the media folder.
    async_add_entities(
        EzvizRecordingButton(coordinator, camera) for camera in coordinator.data
    )


class EzvizButtonEntity(EzvizEntity, ButtonEntity):
    """Representation of a EZVIZ button entity."""

    entity_description: EzvizButtonEntityDescription

    def __init__(
        self,
        coordinator: EzvizDataUpdateCoordinator,
        serial: str,
        description: EzvizButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_{description.key}"
        self.entity_description = description

    @override
    def press(self) -> None:
        """Execute the button action."""
        try:
            self.entity_description.method(
                self.coordinator.ezviz_client, self._serial, "START"
            )
            self.entity_description.method(
                self.coordinator.ezviz_client, self._serial, "STOP"
            )
        except (HTTPError, PyEzvizError) as err:
            raise HomeAssistantError(
                f"Cannot perform PTZ action on {self.name}"
            ) from err


class EzvizSnapshotButton(EzvizEntity, ButtonEntity):
    """Ask the camera for a new picture, shown by its Snapshot image entity."""

    _attr_translation_key = "request_snapshot"
    _attr_icon = "mdi:camera"

    def __init__(
        self,
        coordinator: EzvizDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the snapshot button."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_request_snapshot"

    @override
    async def async_press(self) -> None:
        """Waking the camera can take a while; the service retries a 2009 once."""
        await async_request_snapshot(self.hass, self.coordinator, self._serial)


class EzvizRecordingButton(EzvizEntity, ButtonEntity):
    """Download the camera's latest SD-card recording into the media folder."""

    _attr_translation_key = "download_recording"
    _attr_icon = "mdi:download"

    def __init__(
        self,
        coordinator: EzvizDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the latest-recording button."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_download_recording"

    @override
    async def async_press(self) -> None:
        """Fetching a recording wakes the camera and can take a while."""
        camera = find_camera(self.hass, self._serial)
        if camera is None:
            raise HomeAssistantError(f"The camera {self._serial} is not available")
        try:
            await async_download_latest(self.hass, camera)
        except RecordingError as err:
            raise HomeAssistantError(str(err)) from err
