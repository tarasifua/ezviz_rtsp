"""Support for EZVIZ sensors."""

from datetime import datetime
from typing import Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import SIGNAL_RECORDING_DOWNLOADED
from .coordinator import EzvizConfigEntry, EzvizDataUpdateCoordinator
from .entity import EzvizEntity

PARALLEL_UPDATES = 1

SENSOR_TYPES: dict[str, SensorEntityDescription] = {
    "battery_level": SensorEntityDescription(
        key="battery_level",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
    ),
    "alarm_sound_mod": SensorEntityDescription(
        key="alarm_sound_mod",
        translation_key="alarm_sound_mod",
        entity_registry_enabled_default=False,
    ),
    "last_alarm_time": SensorEntityDescription(
        key="last_alarm_time",
        translation_key="last_alarm_time",
        entity_registry_enabled_default=False,
    ),
    "Seconds_Last_Trigger": SensorEntityDescription(
        key="Seconds_Last_Trigger",
        translation_key="seconds_last_trigger",
        entity_registry_enabled_default=False,
    ),
    "supported_channels": SensorEntityDescription(
        key="supported_channels",
        translation_key="supported_channels",
    ),
    "local_ip": SensorEntityDescription(
        key="local_ip",
        translation_key="local_ip",
    ),
    "wan_ip": SensorEntityDescription(
        key="wan_ip",
        translation_key="wan_ip",
    ),
    "PIR_Status": SensorEntityDescription(
        key="PIR_Status",
        translation_key="pir_status",
    ),
    "last_alarm_type_code": SensorEntityDescription(
        key="last_alarm_type_code",
        translation_key="last_alarm_type_code",
    ),
    "last_alarm_type_name": SensorEntityDescription(
        key="last_alarm_type_name",
        translation_key="last_alarm_type_name",
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EzvizConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EZVIZ sensors based on a config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        [
            EzvizSensor(coordinator, camera, sensor)
            for camera in coordinator.data
            for sensor, value in coordinator.data[camera].items()
            if sensor in SENSOR_TYPES
            if value is not None
        ]
    )
    async_add_entities(
        EzvizLatestRecording(coordinator, camera) for camera in coordinator.data
    )


class EzvizSensor(EzvizEntity, SensorEntity):
    """Representation of a EZVIZ sensor."""

    def __init__(
        self, coordinator: EzvizDataUpdateCoordinator, serial: str, sensor: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, serial)
        self._sensor_name = sensor
        self._attr_unique_id = f"{serial}_{self._camera_name}.{sensor}"
        self.entity_description = SENSOR_TYPES[sensor]

    @property
    @override
    def native_value(self) -> int | str:
        """Return the state of the sensor."""
        return self.data.get(self._sensor_name)


class EzvizLatestRecording(EzvizEntity, SensorEntity):
    """The last SD-card recording downloaded on demand.

    It changes only when the ``download_recording`` service (or the camera's
    Download latest recording button) runs; the value is kept in memory, so it
    is empty again after a restart until the next download.
    """

    _attr_translation_key = "latest_recording"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:video"

    def __init__(
        self, coordinator: EzvizDataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the latest-recording sensor."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_latest_recording"
        self._recording: dict[str, Any] | None = None

    async def async_added_to_hass(self) -> None:
        """Listen for recordings downloaded by the camera entity."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_RECORDING_DOWNLOADED.format(self._serial),
                self._handle_recording,
            )
        )

    @callback
    def _handle_recording(self, recording: dict[str, Any]) -> None:
        self._recording = recording
        self.async_write_ha_state()

    @property
    @override
    def native_value(self) -> datetime | None:
        """When the newest recording starts; None until one is downloaded."""
        if self._recording is None:
            return None
        return dt_util.parse_datetime(self._recording["start"])

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Where the file is and which interval it covers."""
        if self._recording is None:
            return {}
        return {
            "serial": self._recording["serial"],
            "begin": self._recording["begin"],
            "end": self._recording["end"],
            "seconds": self._recording["seconds"],
            "format": self._recording["format"],
            "path": self._recording["path"],
        }
