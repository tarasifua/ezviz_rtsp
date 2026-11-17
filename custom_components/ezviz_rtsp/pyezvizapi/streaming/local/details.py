"""Public read-only camera discovery exports; implementation lives with HCNetSDK."""

from custom_components.ezviz_rtsp.pyezvizapi.streaming.local.hcnetsdk.api import (
    HcNetSdkStreamDetails,
    discover_hcnetsdk_stream_details,
    discover_hcnetsdk_stream_details_for_login,
)

__all__ = [
    "HcNetSdkStreamDetails",
    "discover_hcnetsdk_stream_details",
    "discover_hcnetsdk_stream_details_for_login",
]
