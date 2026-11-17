"""An abstract class common to all EZVIZ entities."""

from typing import Any, override

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import EzvizDataUpdateCoordinator


class EzvizEntity(CoordinatorEntity[EzvizDataUpdateCoordinator], Entity):
    """Generic entity encapsulating common features of EZVIZ device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EzvizDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._serial = serial
        camera = self.data
        self._camera_name = camera.get("name")

        connections = set()
        if mac_address := camera.get("mac_address"):
            connections.add((CONNECTION_NETWORK_MAC, mac_address))

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            connections=connections,
            manufacturer=MANUFACTURER,
            model=camera.get("device_sub_category"),
            name=camera.get("name"),
            sw_version=camera.get("version"),
        )

    @property
    def data(self) -> dict[str, Any]:
        """The coordinator's data for this camera, empty if it left the account.

        An entity is not removed when its camera disappears between two polls,
        so an empty mapping keeps every later read from raising a ``KeyError``
        on each coordinator update.
        """
        return (self.coordinator.data or {}).get(self._serial) or {}

    @property
    @override
    def available(self) -> bool:
        """Return True while the camera is in the account, online and fresh."""
        camera = self.data
        if not camera or not self.coordinator.last_update_success:
            return False
        return camera.get("status") != 2


class EzvizBaseEntity(Entity):
    """Generic entity for EZVIZ individual poll entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EzvizDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the entity."""
        self._serial = serial
        self.coordinator = coordinator
        camera = self.data
        self._camera_name = camera.get("name")

        connections = set()
        if mac_address := camera.get("mac_address"):
            connections.add((CONNECTION_NETWORK_MAC, mac_address))

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            connections=connections,
            manufacturer=MANUFACTURER,
            model=camera.get("device_sub_category"),
            name=camera.get("name"),
            sw_version=camera.get("version"),
        )

    @property
    def data(self) -> dict[str, Any]:
        """The coordinator's data for this camera, empty if it left the account."""
        return (self.coordinator.data or {}).get(self._serial) or {}

    @property
    @override
    def available(self) -> bool:
        """Return True while the camera is in the account, online and fresh."""
        camera = self.data
        if not camera or not self.coordinator.last_update_success:
            return False
        return camera.get("status") != 2
