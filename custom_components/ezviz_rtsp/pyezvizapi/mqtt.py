"""HA compatibility exports; new code should use :mod:`pyezvizapi.push.mqtt`."""

from custom_components.ezviz_rtsp.pyezvizapi.push.mqtt import (
    MQTTClient,
)

__all__ = ["MQTTClient"]
