"""Support for EZVIZ light entity."""

from typing import Any, override

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .coordinator import EzvizConfigEntry, EzvizDataUpdateCoordinator
from .entity import EzvizEntity
from .pyezvizapi.constants import DeviceCatagories, DeviceSwitchType, SupportExt
from .pyezvizapi.exceptions import HTTPError, PyEzvizError

PARALLEL_UPDATES = 1
BRIGHTNESS_RANGE = (1, 255)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EzvizConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EZVIZ lights based on a config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        EzvizLight(coordinator, camera)
        for camera in coordinator.data
        for capability, value in coordinator.data[camera]["supportExt"].items()
        if capability == str(SupportExt.SupportAlarmLight.value)
        if value == "1"
    )


class EzvizLight(EzvizEntity, LightEntity):
    """Representation of a EZVIZ light."""

    _attr_translation_key = "light"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = frozenset({ColorMode.BRIGHTNESS})

    def __init__(
        self,
        coordinator: EzvizDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator, serial)
        self.battery_cam_type = bool(
            self.data.get("device_category")
            == DeviceCatagories.BATTERY_CAMERA_DEVICE_CATEGORY.value
        )
        self._attr_unique_id = f"{serial}_Light"
        self._attr_is_on = self.data.get("switches", {}).get(
            DeviceSwitchType.ALARM_LIGHT.value
        )
        self._attr_brightness = round(
            percentage_to_ranged_value(
                BRIGHTNESS_RANGE,
                self.data.get("alarm_light_luminance") or 0,
            )
        )

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on light."""
        try:
            if ATTR_BRIGHTNESS in kwargs:
                data = ranged_value_to_percentage(
                    BRIGHTNESS_RANGE, kwargs[ATTR_BRIGHTNESS]
                )

                if await self.hass.async_add_executor_job(
                    self.coordinator.ezviz_client.set_floodlight_brightness,
                    self._serial,
                    data,
                ):
                    self._attr_brightness = kwargs[ATTR_BRIGHTNESS]

            if await self.hass.async_add_executor_job(
                self.coordinator.ezviz_client.switch_status,
                self._serial,
                DeviceSwitchType.ALARM_LIGHT.value,
                1,
            ):
                self._attr_is_on = True
                self.async_write_ha_state()

        except (HTTPError, PyEzvizError) as err:
            raise HomeAssistantError(
                f"Failed to turn on light {self.name}"
            ) from err

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off light."""
        try:
            if await self.hass.async_add_executor_job(
                self.coordinator.ezviz_client.switch_status,
                self._serial,
                DeviceSwitchType.ALARM_LIGHT.value,
                0,
            ):
                self._attr_is_on = False
                self.async_write_ha_state()

        except (HTTPError, PyEzvizError) as err:
            raise HomeAssistantError(
                f"Failed to turn off light {self.name}"
            ) from err

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        data = self.data
        # A camera that left the account has no data: keep the last known state
        # and let ``available`` mark the entity unavailable, rather than raising.
        if data:
            self._attr_is_on = data.get("switches", {}).get(
                DeviceSwitchType.ALARM_LIGHT.value
            )
            if isinstance(data.get("alarm_light_luminance"), int):
                self._attr_brightness = round(
                    percentage_to_ranged_value(
                        BRIGHTNESS_RANGE,
                        data["alarm_light_luminance"],
                    )
                )

        super()._handle_coordinator_update()
