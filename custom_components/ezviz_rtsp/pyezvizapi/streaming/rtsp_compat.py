"""Compatibility imports for the RTSP authentication probe (not a test suite)."""

from custom_components.ezviz_rtsp.pyezvizapi.streaming.rtsp_auth import (
    RTSPDetails,
    TestRTSPAuth,
    _decode_response,
    genmsg_describe,
)

__test__ = False
__all__ = ["RTSPDetails", "TestRTSPAuth", "_decode_response", "genmsg_describe"]
