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
from homeassistant.config_entries import SOURCE_IGNORE, SOURCE_INTEGRATION_DISCOVERY
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
from pyezvizapi.exceptions import HTTPError, InvalidHost, PyEzvizError
from pyezvizapi.utils import decrypt_image

from .const import (
    ATTR_AUTOMATIC,
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
    SERVICE_WAKE_DEVICE,
    SIGNAL_PICTURE_CAPTURED,
)
from .coordinator import EzvizConfigEntry, EzvizDataUpdateCoordinator
from .entity import EzvizEntity
from .live import LiveStream, stream_source

try:
    # pyezvizapi's own parser for capture responses (used by EzvizClient.save_image); it accepts
    # picUrl, picURL, imageUrl, captureUrl, ... It is private, so keep a fallback in case it moves.
    from pyezvizapi.client import _first_image_url
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


def _is_battery_camera(data: dict) -> bool:
    """Whether a camera runs on battery (no local RTSP, sleeps between wakes).

    EZVIZ reports a battery level or a battery work mode for these; they expose
    no RTSP server, so the local ``rtsp://`` source can never play them.
    """
    return (
        data.get("battery_level") is not None
        or data.get("battery_camera_work_mode") is not None
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EzvizConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EZVIZ cameras based on a config entry."""

    coordinator = entry.runtime_data

    camera_entities = []

    for camera, value in coordinator.data.items():
        camera_rtsp_entry = [
            item
            for item in hass.config_entries.async_entries(DOMAIN)
            if item.unique_id == camera and item.source != SOURCE_IGNORE
        ]

        if camera_rtsp_entry:
            ffmpeg_arguments = camera_rtsp_entry[0].options[CONF_FFMPEG_ARGUMENTS]
            camera_username = camera_rtsp_entry[0].data[CONF_USERNAME]
            camera_password = camera_rtsp_entry[0].data[CONF_PASSWORD]

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
            if not _is_battery_camera(value):
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
                use_cloud=not camera_rtsp_entry,
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
        # capture_picture throttle: when the last capture started (monotonic) and its picture
        self._capture_started: float | None = None
        self._capture_url: str | None = None
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
        return bool(self.data["status"])

    @property
    @override
    def is_recording(self) -> bool:
        """Return true if the device is recording."""
        return self.data["alarm_notify"]

    @property
    @override
    def motion_detection_enabled(self) -> bool:
        """Camera Motion Detection Status."""
        return self.data["alarm_notify"]

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
        local_ip = self.data["local_ip"]
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
                return {"picture_url": self._capture_url, "skipped": True}
            if min_interval is None:
                min_interval = int(
                    options.get(CONF_SNAPSHOT_INTERVAL, DEFAULT_SNAPSHOT_INTERVAL)
                )
        min_interval = min_interval or 0
        now = time.monotonic()
        if (
            min_interval
            and self._capture_started is not None
            and now - self._capture_started < min_interval
        ):
            return {"picture_url": self._capture_url, "skipped": True}
        started = self._capture_started
        self._capture_started = now
        client = self.coordinator.ezviz_client
        try:
            try:
                result = await self.hass.async_add_executor_job(
                    client.capture_picture, self._serial, 1
                )
            except PyEzvizError as err:
                if not _is_wake_timeout(err):
                    raise
                _LOGGER.debug(
                    "%s was still waking (EZVIZ 2009); retrying the capture in %s s",
                    self._serial,
                    CAPTURE_RETRY_DELAY,
                )
                await asyncio.sleep(CAPTURE_RETRY_DELAY)
                result = await self.hass.async_add_executor_job(
                    client.capture_picture, self._serial, 1
                )
        except (HTTPError, PyEzvizError) as err:
            # a failed capture must not hold off the next try
            self._capture_started = started
            raise HomeAssistantError(f"Cannot capture picture: {err}") from err

        pic_url = _first_image_url(result)
        if not pic_url:
            self._capture_started = started
            raise HomeAssistantError("EZVIZ returned no picture url")

        self._capture_url = pic_url
        async_dispatcher_send(
            self.hass, SIGNAL_PICTURE_CAPTURED.format(self._serial), pic_url
        )
        return {"picture_url": pic_url, "skipped": False}

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
