"""Support ezviz camera devices."""

import asyncio
import logging
import time
from typing import override

import aiohttp
import probatio as vol
from homeassistant.components import ffmpeg
from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.components.stream import CONF_USE_WALLCLOCK_AS_TIMESTAMPS
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    async_get_current_platform,
)

from .const import (
    ATTR_AUTOMATIC,
    ATTR_FORMAT,
    ATTR_LEVEL,
    ATTR_MIN_INTERVAL,
    ATTR_SERIAL,
    ATTR_TYPE,
    CONF_AUTO_SNAPSHOT,
    CONF_FFMPEG_ARGUMENTS,
    CONF_SNAPSHOT_INTERVAL,
    DEFAULT_AUTO_SNAPSHOT,
    DEFAULT_CAMERA_USERNAME,
    DEFAULT_FFMPEG_ARGUMENTS,
    DEFAULT_SNAPSHOT_INTERVAL,
    DOMAIN,
    SERVICE_CAPTURE_PICTURE,
    SERVICE_DETECTION_SENSITIVITY,
    SERVICE_DOWNLOAD_RECORDING,
    SERVICE_WAKE_DEVICE,
    SIGNAL_PICTURE_CAPTURED,
)
from .coordinator import EzvizConfigEntry, EzvizDataUpdateCoordinator
from .entity import EzvizEntity
from .live import LiveStream, is_battery_camera, rtsp_entry, stream_source
from .pyezvizapi.exceptions import HTTPError, InvalidHost, PyEzvizError
from .pyezvizapi.utils import decrypt_image
from .recordings import FORMATS, RecordingError, async_download_latest, find_camera

try:
    # pyezvizapi's own parser for capture responses (used by EzvizClient.save_image); it accepts
    # picUrl, picURL, imageUrl, captureUrl, ... It is private, so keep a fallback in case it moves.
    from .pyezvizapi.client import _first_image_url
except ImportError:  # pragma: no cover

    def _first_image_url(value: object) -> str | None:
        info = value.get("captureInfo") if isinstance(value, dict) else None
        url = info.get("picUrl") if isinstance(info, dict) else None
        return url if isinstance(url, str) and url.startswith(("http://", "https://")) else None


_LOGGER = logging.getLogger(__name__)

# A sleeping battery camera often answers the first capture with EZVIZ meta.code 2009
# ("device network exception") while it wakes; one retry after this long usually succeeds.
CAPTURE_RETRY_DELAY = 5


def _is_wake_timeout(err: Exception) -> bool:
    """Whether a capture failed with EZVIZ meta.code 2009.

    pyezvizapi reports API errors as PyEzvizError with the payload in the message
    (``... Got {'meta': {'code': 2009, ...}}``), so the code is read from there.
    (``max_retries`` on capture_picture only counts 401 re-logins, so it does not
    cover this.)
    """
    return isinstance(err, PyEzvizError) and "'code': 2009" in str(err)


async def async_request_snapshot(
    hass: HomeAssistant,
    coordinator: EzvizDataUpdateCoordinator,
    serial: str,
    *,
    min_interval: int = 0,
) -> ServiceResponse:
    """Take a picture through the EZVIZ cloud and announce it to the image entities.

    Shared by the ``capture_picture`` camera service and the Snapshot button.
    ``min_interval`` (seconds) skips the call when this camera took a picture
    that recently; the throttle is kept on the coordinator, so both entry points
    share it. A sleeping camera that answers with EZVIZ 2009 is retried once.
    """
    started, last_url = coordinator.snapshot_captures.get(serial, (None, None))
    now = time.monotonic()
    if min_interval and started is not None and now - started < min_interval:
        return {"picture_url": last_url, "skipped": True}

    coordinator.snapshot_captures[serial] = (now, last_url)
    client = coordinator.ezviz_client
    try:
        try:
            result = await hass.async_add_executor_job(
                client.capture_picture, serial, 1
            )
        except PyEzvizError as err:
            if not _is_wake_timeout(err):
                raise
            _LOGGER.debug(
                "%s was still waking (EZVIZ 2009); retrying the capture in %s s",
                serial,
                CAPTURE_RETRY_DELAY,
            )
            await asyncio.sleep(CAPTURE_RETRY_DELAY)
            result = await hass.async_add_executor_job(
                client.capture_picture, serial, 1
            )
    except (HTTPError, PyEzvizError) as err:
        # a failed capture must not hold off the next try
        coordinator.snapshot_captures[serial] = (started, last_url)
        raise HomeAssistantError(f"Cannot capture picture: {err}") from err

    pic_url = _first_image_url(result)
    if not pic_url:
        coordinator.snapshot_captures[serial] = (started, last_url)
        raise HomeAssistantError("EZVIZ returned no picture url")

    coordinator.snapshot_captures[serial] = (now, pic_url)
    async_dispatcher_send(hass, SIGNAL_PICTURE_CAPTURED.format(serial), pic_url)
    return {"picture_url": pic_url, "skipped": False}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EzvizConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EZVIZ cameras based on a config entry."""

    coordinator = entry.runtime_data

    camera_entities = []

    for camera, value in coordinator.data.items():
        camera_rtsp_entry = rtsp_entry(hass, camera)

        if camera_rtsp_entry is not None:
            ffmpeg_arguments = camera_rtsp_entry.options[CONF_FFMPEG_ARGUMENTS]
            camera_username = camera_rtsp_entry.data[CONF_USERNAME]
            camera_password = camera_rtsp_entry.data[CONF_PASSWORD]

            camera_rtsp_stream = f"rtsp://{camera_username}:{camera_password}@{value['local_ip']}:{value['local_rtsp_port']}{ffmpeg_arguments}"
            _LOGGER.debug(
                "Configuring Camera %s with ip: %s rtsp port: %s ffmpeg arguments: %s",
                camera,
                value["local_ip"],
                value["local_rtsp_port"],
                ffmpeg_arguments,
            )

        else:
            # No local RTSP: play the camera through the EZVIZ cloud instead.
            # Battery cameras never answer RTSP, so don't ask for credentials.
            if not is_battery_camera(value):
                discovery_flow.async_create_flow(
                    hass,
                    DOMAIN,
                    context={"source": SOURCE_INTEGRATION_DISCOVERY},
                    data={
                        ATTR_SERIAL: camera,
                        CONF_IP_ADDRESS: value["local_ip"],
                    },
                )

                _LOGGER.warning(
                    (
                        "Found camera with serial %s without configuration. Please go to"
                        " integration to complete setup"
                    ),
                    camera,
                )

            ffmpeg_arguments = DEFAULT_FFMPEG_ARGUMENTS
            camera_username = DEFAULT_CAMERA_USERNAME
            camera_password = None
            camera_rtsp_stream = ""

        camera_entities.append(
            EzvizCamera(
                hass,
                coordinator,
                camera,
                camera_username,
                camera_password,
                camera_rtsp_stream,
                value["local_rtsp_port"],
                ffmpeg_arguments,
                use_cloud=camera_rtsp_entry is None,
            )
        )

    async_add_entities(camera_entities)

    platform = async_get_current_platform()

    platform.async_register_entity_service(
        SERVICE_WAKE_DEVICE, None, "perform_wake_device"
    )
    platform.async_register_entity_service(
        SERVICE_CAPTURE_PICTURE,
        {
            vol.Optional(ATTR_MIN_INTERVAL): cv.positive_int,
            vol.Optional(ATTR_AUTOMATIC, default=False): cv.boolean,
        },
        "async_capture_picture",
        supports_response=SupportsResponse.OPTIONAL,
    )
    platform.async_register_entity_service(
        SERVICE_DOWNLOAD_RECORDING,
        {vol.Optional(ATTR_FORMAT, default="h264"): vol.In(FORMATS)},
        "async_download_recording",
        supports_response=SupportsResponse.OPTIONAL,
    )
    platform.async_register_entity_service(
        SERVICE_DETECTION_SENSITIVITY,
        {
            vol.Required(ATTR_LEVEL): cv.positive_int,
            vol.Optional(ATTR_TYPE, default=0): vol.All(
                vol.Coerce(int), vol.In([0, 3])
            ),
        },
        "set_alarm_detection_sensibility",
    )


class EzvizCamera(EzvizEntity, Camera):
    """An implementation of a EZVIZ security camera."""

    _attr_name = None

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: EzvizDataUpdateCoordinator,
        serial: str,
        camera_username: str,
        camera_password: str | None,
        camera_rtsp_stream: str | None,
        local_rtsp_port: int,
        ffmpeg_arguments: str | None,
        *,
        use_cloud: bool = False,
    ) -> None:
        """Initialize a EZVIZ security camera."""
        super().__init__(coordinator, serial)
        Camera.__init__(self)
        self.stream_options[CONF_USE_WALLCLOCK_AS_TIMESTAMPS] = True
        self._username = camera_username
        self._password = camera_password
        self._rtsp_stream = camera_rtsp_stream
        self._local_rtsp_port = local_rtsp_port
        self._ffmpeg_arguments = ffmpeg_arguments
        self._ffmpeg = get_ffmpeg_manager(hass)
        self._use_cloud = use_cloud
        self._live: LiveStream | None = coordinator.live_streams.get(serial)
        self._attr_unique_id = serial
        if camera_password or use_cloud:
            self._attr_supported_features = CameraEntityFeature.STREAM

    async def async_added_to_hass(self) -> None:
        """Stop HA's stream worker when a cloud open gives no video (#24)."""
        await super().async_added_to_hass()
        if self._use_cloud and self._live is not None:
            self._live.on_no_video = self._stop_stream_worker

    async def async_will_remove_from_hass(self) -> None:
        """Drop the no-video hook."""
        if self._use_cloud and self._live is not None:
            self._live.on_no_video = None
        await super().async_will_remove_from_hass()

    @callback
    def _stop_stream_worker(self) -> None:
        # HA's stream worker retries a source that never gave a segment until HA
        # restarts, even with nobody watching: stop it. Opening the camera again
        # starts it anew.
        if self.stream is not None:
            self.hass.async_create_task(self.stream.stop())

    @property
    @override
    def is_on(self) -> bool:
        """Return true if on."""
        return bool(self.data.get("status"))

    @property
    @override
    def is_recording(self) -> bool:
        """Return true if the device is recording."""
        return bool(self.data.get("alarm_notify"))

    @property
    @override
    def motion_detection_enabled(self) -> bool:
        """Camera Motion Detection Status."""
        return bool(self.data.get("alarm_notify"))

    @override
    def enable_motion_detection(self) -> None:
        """Enable motion detection in camera."""
        try:
            self.coordinator.ezviz_client.set_camera_defence(self._serial, 1)

        except InvalidHost as err:
            raise InvalidHost("Error enabling motion detection") from err

    @override
    def disable_motion_detection(self) -> None:
        """Disable motion detection."""
        try:
            self.coordinator.ezviz_client.set_camera_defence(self._serial, 0)

        except InvalidHost as err:
            raise InvalidHost("Error disabling motion detection") from err

    @override
    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a frame for the dashboard.

        A cloud camera is never woken for a thumbnail: the last alarm picture is
        shown instead, so drawing the camera on a dashboard costs no battery.
        """
        if self._use_cloud:
            return await self._async_cloud_still()
        if self._rtsp_stream is None:
            return None
        return await ffmpeg.async_get_image(
            self.hass, self._rtsp_stream, width=width, height=height
        )

    async def _async_cloud_still(self) -> bytes | None:
        """The camera's last alarm picture, decrypted if the camera encrypts it."""
        url = self.data.get("last_alarm_pic")
        if not isinstance(url, str) or not url:
            return None
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                content = await resp.read()
        except aiohttp.ClientError as err:
            _LOGGER.debug("No alarm picture for %s: %s", self._serial, err)
            return None
        if (
            self.data.get("encrypted")
            and self._live is not None
            and (code := self._live.current_code()) is not None
        ):
            try:
                content = decrypt_image(content, code)
            except PyEzvizError as err:
                _LOGGER.debug("Could not decrypt the alarm picture of %s: %s", self._serial, err)
        return content

    @override
    async def stream_source(self) -> str | None:
        """Return the stream source."""
        if self._use_cloud:
            if self._live is None:
                return None
            return stream_source(self.hass, self._live)
        if self._password is None:
            return None
        if (local_ip := self.data.get("local_ip")) is None:
            return None
        self._rtsp_stream = (
            f"rtsp://{self._username}:{self._password}@"
            f"{local_ip}:{self._local_rtsp_port}{self._ffmpeg_arguments}"
        )
        _LOGGER.debug(
            "Configuring Camera %s with ip: %s rtsp port: %s ffmpeg arguments: %s",
            self._serial,
            local_ip,
            self._local_rtsp_port,
            self._ffmpeg_arguments,
        )

        return self._rtsp_stream

    def perform_wake_device(self) -> None:
        """Basically wakes the camera by querying the device."""
        try:
            self.coordinator.ezviz_client.get_detection_sensibility(self._serial)
        except (HTTPError, PyEzvizError) as err:
            raise PyEzvizError("Cannot wake device") from err

    async def async_capture_picture(
        self, min_interval: int | None = None, automatic: bool = False
    ) -> ServiceResponse:
        """Take a new picture through the EZVIZ cloud.

        Works without RTSP and wakes battery cameras from standby. The picture is
        shown by the camera's Snapshot image entity.

        With ``min_interval`` (seconds), a call within that time of the last
        capture of this camera (or while one is running) is skipped, so several
        dashboards opening at once wake the camera only once. The skipped call
        returns the last picture with ``skipped: true``.

        ``automatic`` marks a request nobody explicitly asked for (the snapshot
        card coming into view). It follows the entry's Snapshots options: it is
        skipped when automatic snapshots are off, and without its own
        ``min_interval`` it uses the configured one.
        """
        if automatic:
            options = self.coordinator.config_entry.options
            if not options.get(CONF_AUTO_SNAPSHOT, DEFAULT_AUTO_SNAPSHOT):
                last_url = self.coordinator.snapshot_captures.get(
                    self._serial, (None, None)
                )[1]
                return {"picture_url": last_url, "skipped": True}
            if min_interval is None:
                min_interval = int(
                    options.get(CONF_SNAPSHOT_INTERVAL, DEFAULT_SNAPSHOT_INTERVAL)
                )
        return await async_request_snapshot(
            self.hass, self.coordinator, self._serial, min_interval=min_interval or 0
        )

    async def async_download_recording(self, format: str = "h264") -> ServiceResponse:
        """Download the camera's latest SD-card recording into the media folder.

        Finds the newest recording of today (or yesterday, when today has none),
        fetches it through the EZVIZ cloud and saves it as an MP4 under
        ``media/ezviz_rtsp``. Its details are also announced to the camera's
        Latest recording sensor.
        """
        camera = find_camera(self.hass, self._serial)
        if camera is None:
            raise HomeAssistantError("The camera is not available")
        try:
            return await async_download_latest(self.hass, camera, fmt=format)
        except RecordingError as err:
            raise HomeAssistantError(str(err)) from err

    def set_alarm_detection_sensibility(
        self, level: int, type_value: int = 0
    ) -> None:
        """Set the motion-detection sensitivity of the camera."""
        try:
            self.coordinator.ezviz_client.detection_sensibility(
                self._serial, level, type_value
            )
        except (HTTPError, PyEzvizError) as err:
            raise PyEzvizError(
                f"Cannot set detection sensitivity level on {self.name}"
            ) from err
