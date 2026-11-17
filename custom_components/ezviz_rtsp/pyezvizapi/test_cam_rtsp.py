"""HA compatibility exports; new code should use :mod:`pyezvizapi.streaming.rtsp_compat`."""

from custom_components.ezviz_rtsp.pyezvizapi.streaming.rtsp_compat import (
    TestRTSPAuth,
)

__all__ = ["TestRTSPAuth"]
