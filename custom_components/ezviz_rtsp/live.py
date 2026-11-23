"""One cloud live stream per camera, shared by the live camera entity.

EZVIZ refuses a second stream of a camera while one is open, and a peephole that
was just streaming can refuse a new one for minutes. So every reader of a camera
the camera entity's HTTP view, read by go2rtc and Home Assistant's stream worker)
shares one live stream: the first reader opens it and it closes ``LINGER``
seconds after the last one leaves.

The video comes from the EZVIZ VTM cloud relay (the transport the mobile app uses
away from home), read by ``pyezvizapi`` in a worker thread. This is what makes
battery cameras, which expose no local RTSP, playable.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import secrets
from collections.abc import AsyncGenerator, Callable, Mapping
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView

from .cloud_stream import (
    EzvizStreamError,
    LiveSource,
    PackSplitter,
    RtpToPs,
    async_iter_payloads,
    decrypt_packs,
)
from .const import (
    CONF_CODES,
    CONF_INTERNAL_TOKEN,
    CONF_LINGER,
    CONF_MAX_SESSION,
    CONF_STREAM_ENABLED,
    CONF_STREAM_TOKEN,
    CONF_TRANSCODE,
    DATA_LIVE_VIEW,
    DOMAIN,
)
from .recordings import RecordingClipView, async_wait_for_camera

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import EzvizConfigEntry, EzvizDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Keeps the stream open between two quick readers (a card reload, a stream retry)
# so a battery camera is not woken again. Configurable under Configure.
LINGER = 10
# After an open that gave no video, refuse new opens for this long instead of
# waking the camera again for every retry.
COOLDOWN = 60
# A battery camera must never be left streaming: even if a reader misbehaves
# (a browser that forgot to stop), the cloud session is closed after this long.
# It only applies to battery cameras; powered ones may stream as long as asked.
MAX_SESSION = 300

# A reader this far behind (about 30 s of video) is dropped instead of buffered.
_MAX_BACKLOG = 450

# The card's fast path: the cloud stream encoded straight to JPEG for a browser
# <img>. Smaller and slower than the video, but it appears in a few seconds
# instead of waiting for Home Assistant's stream worker to build HLS segments.
_MJPEG_WIDTH = 1280
_MJPEG_FPS = 8
_MJPEG_QUALITY = 6

type _Item = tuple[bytes, bool] | Exception | None


class EzvizCloudCooldownError(EzvizStreamError):
    """The camera failed to stream less than ``COOLDOWN`` seconds ago."""


class LiveStream:
    """The shared cloud live stream of one camera."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: EzvizDataUpdateCoordinator,
        serial: str,
        channel: int,
        code: Callable[[], str | None],
        token: str | None = None,
        internal_token: str | None = None,
        external_enabled: bool = True,
        transcode: bool = False,
        encrypted: bool = False,
        battery: bool = False,
        max_session: float = MAX_SESSION,
        linger: float = LINGER,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self.serial = serial
        self.channel = channel
        self._code = code
        # A verification code only means something when the camera encrypts video.
        self.encrypted = encrypted
        # A battery camera gets a hard cap on how long it may stream (max_session
        # seconds; 0 disables the cap).
        self.battery = battery
        self._max_session = max_session
        # How long the stream is held open after the last reader leaves, so a
        # quick re-open does not wake the camera again.
        self._linger_seconds = linger
        self._readers: set[asyncio.Queue[_Item]] = set()
        self._task: asyncio.Task[None] | None = None
        self._linger: asyncio.TimerHandle | None = None
        self._deadline: asyncio.TimerHandle | None = None
        self._cooldown_until = 0.0
        # Whether the current open has handed a keyframe to its readers.
        self._video = False
        # Whether the copy path may carry audio (an RTP relay with encrypted AAC).
        self.audio_copy = False
        # Whether the open is waiting for a clip download or an SD read to end
        # before it may wake the camera. The card shows this in its status.
        self.waiting = False
        # Called when an open ends without video (the live camera stops HA's stream worker).
        self.on_no_video: Callable[[], None] | None = None
        self.codec = "hevc"
        # Re-encode to H.264 for the browser's sake; costs CPU on the HA host.
        self.transcode = transcode
        # Guards the HTTP view, which go2rtc reads without Home Assistant credentials.
        self.token = token or secrets.token_urlsafe(24)
        # The card's own picture address, so turning the public addresses off does
        # not break the bundled card.
        self.internal_token = internal_token or secrets.token_urlsafe(24)
        # Whether other apps may read the public addresses at all.
        self.external_enabled = external_enabled

    @property
    def active(self) -> bool:
        """Whether the stream is open (or opening)."""
        return self._task is not None

    def allows(self, token: str) -> bool:
        """Whether a request token may read this stream.

        The integration's own token is always accepted (Home Assistant's stream
        worker and the bundled card read the stream with it); the public token is
        accepted only while other apps are allowed to read the addresses.
        """
        if not token:
            return False
        if hmac.compare_digest(token, self.internal_token):
            return True
        return self.external_enabled and hmac.compare_digest(token, self.token)

    def current_code(self) -> str | None:
        """The verification code to decrypt this camera's video, if any."""
        return self._code() if self.encrypted else None

    async def frames(self) -> AsyncGenerator[bytes]:
        """MPEG-PS from the next group of pictures on, for as long as it is read.

        Use it with ``contextlib.aclosing`` so leaving early releases the stream.
        """
        loop = asyncio.get_running_loop()
        if loop.time() < self._cooldown_until:
            raise EzvizCloudCooldownError(
                "The camera did not stream a moment ago; try again later"
            )
        queue: asyncio.Queue[_Item] = asyncio.Queue()
        started = False
        # Everything from the reader's registration on is inside the try: if
        # starting the background task raises (Home Assistant is shutting down),
        # the finally still takes the queue back out of ``_readers``.
        try:
            self._readers.add(queue)
            if self._linger is not None:
                self._linger.cancel()
                self._linger = None
            if self._task is None:
                if self.battery and self._max_session > 0 and self._deadline is None:
                    self._deadline = loop.call_later(
                        self._max_session, self._session_timeout
                    )
                self._task = self._hass.async_create_background_task(
                    self._run(), f"{DOMAIN} live {self.serial}"
                )
            while True:
                item = await queue.get()
                if isinstance(item, Exception):
                    raise item
                if item is None:
                    return
                data, keyframe = item
                started = started or keyframe
                if started:
                    yield data
        finally:
            self._readers.discard(queue)
            if not self._readers and self._task is not None and self._linger is None:
                self._linger = loop.call_later(self._linger_seconds, self._stop)

    def _stop(self) -> None:
        self._linger = None
        if not self._readers and self._task is not None:
            if not self._video:
                # Every reader gave up waiting for a picture.
                self._no_video()
            self._task.cancel()

    def _session_timeout(self) -> None:
        """Close a battery camera's stream after MAX_SESSION, whatever readers do."""
        if self._deadline is not None:
            self._deadline.cancel()
            self._deadline = None
        if self._task is not None:
            _LOGGER.info(
                "Live view of %s hit its %d s battery limit; stopping it now",
                self.serial,
                int(self._max_session),
            )
            self._task.cancel()

    def _no_video(self) -> None:
        self._cooldown_until = asyncio.get_running_loop().time() + COOLDOWN
        if self.on_no_video is not None:
            self.on_no_video()

    async def async_stop(self) -> bool:
        """Close the stream now, without waiting for the release delay.

        The session is normally held open for the linger time, so a quick
        re-open does not wake the camera again. SD-card playback needs the
        camera to itself, so the card asks for the session to go at once.
        """
        if self._linger is not None:
            self._linger.cancel()
            self._linger = None
        if self._deadline is not None:
            self._deadline.cancel()
            self._deadline = None
        if (task := self._task) is None:
            return False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        # A task cancelled before it ran never told its readers. Forget it only
        # if it is still ours: a new reader may have started another task while
        # this one was being awaited, and that one must stay tracked.
        if self._task is task:
            self._task = None
        for queue in self._readers:
            queue.put_nowait(None)
        _LOGGER.info("Live view of %s stopped (the camera is needed elsewhere)", self.serial)
        return True

    async def async_close(self) -> None:
        """Close the stream now (the entry is unloading)."""
        if self._linger is not None:
            self._linger.cancel()
            self._linger = None
        if self._deadline is not None:
            self._deadline.cancel()
            self._deadline = None
        if (task := self._task) is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            # A task cancelled before it ran never told its readers. Forget it
            # only if it is still the one we cancelled.
            if self._task is task:
                self._task = None
            for queue in self._readers:
                queue.put_nowait(None)

    async def _run(self) -> None:
        """Play the VTM stream and hand each pack to every reader."""
        self._video = closed = False
        end: _Item = None
        started = False
        try:
            # A clip download or a day read holds the camera, and EZVIZ refuses a
            # stream while the SD card is being read. Wait for it to finish (the
            # card shows that it is waiting) instead of failing the live view.
            self.waiting = True
            try:
                await async_wait_for_camera(self._hass, self.serial)
            finally:
                self.waiting = False
            client = self._coordinator.ezviz_client
            _LOGGER.debug("Opening the EZVIZ cloud stream of %s", self.serial)
            source = LiveSource(client, self.serial, self.channel)
            # A stored code only decrypts video of an encrypted camera; applying it
            # to a clear stream would garble it.
            code = self._code() if self.encrypted else None
            # Some cameras relay RTP rather than MPEG-PS (the CP3 Pro, for one).
            # The transport is decided from the first body that arrives, because
            # the EZVIZ VTM stream can open with a service packet.
            packs: PackSplitter | RtpToPs | None = None
            async for data in async_iter_payloads(self._hass, source):
                if packs is None:
                    from .pyezvizapi.streaming.cloud.protocol import (
                        StreamTransport,
                        detect_transport,
                    )

                    rtp = detect_transport(data) == StreamTransport.RTP
                    # The first group of a clear MPEG-PS stream doesn't decode and
                    # decrypting it garbles it further; RTP starts at a keyframe by
                    # itself, so readers wait for the first one there.
                    packs = (
                        RtpToPs(code)
                        if rtp
                        else PackSplitter(skip_first_group=bool(code))
                    )
                    self.audio_copy = rtp and code is not None
                    _LOGGER.info(
                        "Live view of %s reads %s from the cloud",
                        self.serial,
                        "RTP" if rtp else "MPEG-PS",
                    )
                if not (batch := packs.feed(data)):
                    continue
                self.codec = packs.codec
                if code and not packs.decrypts:
                    clear = await self._hass.async_add_executor_job(
                        decrypt_packs, [pack for pack, _ in batch], code, packs.codec
                    )
                    batch = [
                        (pack, keyframe)
                        for pack, (_, keyframe) in zip(clear, batch, strict=True)
                    ]
                for pack, keyframe in batch:
                    self._broadcast((pack, keyframe))
                    self._video = self._video or keyframe
                    if keyframe and not started:
                        started = True
                        _LOGGER.info(
                            "Live view of %s is streaming (%s%s)",
                            self.serial,
                            self.codec,
                            ", decrypted" if code else "",
                        )
        except EzvizStreamError as err:
            _LOGGER.warning("Live stream of %s failed: %s", self.serial, err)
            end = err
        except asyncio.CancelledError:
            closed = True  # on purpose; a linger stop without video already cooled down
            raise
        except Exception as err:
            # Anything unexpected (the pack splitter, a decoder) would otherwise
            # leave the readers with a plain end: no error to show and no
            # cooldown, so the camera would be woken again at once.
            _LOGGER.exception("Live stream of %s failed", self.serial)
            end = EzvizStreamError(str(err) or type(err).__name__)
        finally:
            self._task = None
            if self._deadline is not None:
                self._deadline.cancel()
                self._deadline = None
            if started:
                _LOGGER.info("Live view of %s stopped", self.serial)
            if not self._video and not closed:
                self._no_video()
                end = end or EzvizStreamError("The camera sent no video")
            for queue in self._readers:
                queue.put_nowait(end)

    def _broadcast(self, item: _Item) -> None:
        for queue in list(self._readers):
            if queue.qsize() >= _MAX_BACKLOG:
                self._readers.discard(queue)
                queue.put_nowait(EzvizStreamError("Reader fell behind the live stream"))
            else:
                queue.put_nowait(item)


def ffmpeg_binary(hass: HomeAssistant) -> str:
    """The ffmpeg binary HA is configured to use."""
    from homeassistant.components.ffmpeg import get_ffmpeg_manager

    return get_ffmpeg_manager(hass).binary


async def _pipe_frames(
    hass: HomeAssistant,
    request: web.Request,
    frames: AsyncGenerator[bytes],
    first: bytes,
    ffmpeg_args: tuple[str, ...],
    content_type: str,
) -> web.StreamResponse:
    """Feed MPEG-PS frames through ffmpeg and stream its output to the client."""
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_binary(hass),
        *("-hide_banner", "-loglevel", "error", "-fflags", "+genpts"),
        # The parameter sets come with the first keyframe: don't wait 5 s to probe.
        *("-analyzeduration", "1000000"),
        *("-f", "mpeg", "-i", "pipe:0"),
        *ffmpeg_args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    stdin = proc.stdin

    async def _feed() -> None:
        try:
            stdin.write(first)
            async for data in frames:
                stdin.write(data)
                await stdin.drain()
        except (EzvizStreamError, ConnectionError) as err:
            _LOGGER.debug("Live stream ended: %s", err)
        finally:
            with contextlib.suppress(OSError):
                stdin.close()

    feeder = asyncio.create_task(_feed())
    response = web.StreamResponse()
    response.content_type = content_type
    try:
        await response.prepare(request)
        while chunk := await proc.stdout.read(65536):
            await response.write(chunk)
    except ConnectionError:
        pass  # the reader left
    finally:
        # gather never raises: a feeder that already failed on its own must not
        # mask the reason the client left.
        feeder.cancel()
        await asyncio.gather(feeder, return_exceptions=True)
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
    return response


class LiveStreamView(HomeAssistantView):
    """Serves a camera's live stream as MPEG-TS to go2rtc and HA's stream worker.

    Neither can send Home Assistant credentials, so the stream's random token in
    the query guards it. The video is copied, not re-encoded, unless the entry
    asked for H.264 for the browser.
    """

    url = f"/api/{DOMAIN}/live/{{serial}}"
    name = f"api:{DOMAIN}:live"
    requires_auth = False

    async def get(self, request: web.Request, serial: str) -> web.StreamResponse:
        """Stream MPEG-TS while the client stays connected."""
        hass = request.app[KEY_HASS]
        stream = find_stream(hass, serial)
        if stream is None or not stream.allows(request.query.get("token", "")):
            raise web.HTTPNotFound
        async with contextlib.aclosing(stream.frames()) as frames:
            try:
                first = await anext(frames)
            except (EzvizStreamError, StopAsyncIteration) as err:
                _LOGGER.warning("Live view of %s could not start: %s", serial, err)
                raise web.HTTPServiceUnavailable from err
            if stream.transcode:
                codec = (
                    "-map", "0:v:0", "-c:v", "libx264", "-preset", "veryfast",
                    "-tune", "zerolatency", "-pix_fmt", "yuv420p", "-g", "30",
                    "-map", "0:a:0?", "-c:a", "aac", "-b:a", "64k",
                )
            elif stream.audio_copy is True:
                # An RTP relay also carries AAC: copy it next to the video.
                codec = ("-map", "0:v:0", "-map", "0:a:0?", "-c", "copy")
            else:
                codec = ("-map", "0:v:0", "-c", "copy")
            return await _pipe_frames(
                hass, request, frames, first, (*codec, "-f", "mpegts", "pipe:1"), "video/mp2t"
            )


async def _stream_mjpeg(request: web.Request, stream: LiveStream) -> web.StreamResponse:
    """Encode the shared stream to multipart JPEG while the client stays."""
    hass = request.app[KEY_HASS]
    async with contextlib.aclosing(stream.frames()) as frames:
        try:
            first = await anext(frames)
        except (EzvizStreamError, StopAsyncIteration) as err:
            _LOGGER.warning("Live view of %s could not start: %s", stream.serial, err)
            raise web.HTTPServiceUnavailable from err
        args = (
            "-map", "0:v:0", "-c:v", "mjpeg", "-q:v", str(_MJPEG_QUALITY),
            "-vf", f"scale={_MJPEG_WIDTH}:-2", "-r", str(_MJPEG_FPS),
            "-f", "mpjpeg", "pipe:1",
        )
        # ffmpeg's mpjpeg muxer writes its own '--ffmpeg' boundary.
        return await _pipe_frames(
            hass, request, frames, first, args,
            "multipart/x-mixed-replace;boundary=ffmpeg",
        )


class LiveMjpegView(HomeAssistantView):
    """A camera's live picture as MJPEG for other apps, guarded by the stream token.

    go2rtc, a dashboard ``<img>`` and friends read this while "Allow other apps
    to read the stream" is on. They cannot send Home Assistant credentials, so
    the random token in the query guards it, and the switch turns it off
    entirely. The bundled card does not use this view: it reads the
    authenticated one below.
    """

    url = f"/api/{DOMAIN}/mjpeg/{{serial}}"
    name = f"api:{DOMAIN}:mjpeg"
    requires_auth = False

    async def get(self, request: web.Request, serial: str) -> web.StreamResponse:
        """Stream multipart JPEG while the client stays connected."""
        hass = request.app[KEY_HASS]
        stream = find_stream(hass, serial)
        if (
            stream is None
            or not stream.external_enabled
            or not hmac.compare_digest(request.query.get("token", ""), stream.token)
        ):
            raise web.HTTPNotFound
        return await _stream_mjpeg(request, stream)


class LiveCardMjpegView(HomeAssistantView):
    """The bundled card's live picture, behind Home Assistant authentication.

    Home Assistant's own camera view is HLS, which only shows its first frame
    once the stream worker has built segments — a slow first start. This encodes
    the cloud stream straight to JPEG, so the picture appears a few seconds after
    the camera wakes, the same fast path the EZVIZ app uses.

    The card reaches it through a short-lived signed path (``authSig``) that the
    websocket command hands out, so a leaked URL — or a user who is later
    removed — cannot keep watching the camera.
    """

    url = f"/api/{DOMAIN}/card/{{serial}}"
    name = f"api:{DOMAIN}:card"
    requires_auth = True

    async def get(self, request: web.Request, serial: str) -> web.StreamResponse:
        """Stream multipart JPEG while the client stays connected."""
        hass = request.app[KEY_HASS]
        stream = find_stream(hass, serial)
        if stream is None:
            raise web.HTTPNotFound
        return await _stream_mjpeg(request, stream)


def find_stream(hass: HomeAssistant, serial: str) -> LiveStream | None:
    """The cloud live stream of a camera of any loaded entry."""
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        streams: dict[str, LiveStream] = getattr(entry.runtime_data, "live_streams", {})
        if (stream := streams.get(serial)) is not None:
            return stream
    return None


def stream_source(hass: HomeAssistant, stream: LiveStream) -> str:
    """The local MPEG-TS address Home Assistant's stream worker reads.

    Uses the integration's own token, so Home Assistant's camera stream keeps
    working even when the public addresses are turned off for other apps.

    ponytail: loopback to HA's own port; behind HA's TLS, go2rtc and the stream
    worker must accept its certificate for 127.0.0.1.
    """
    api = hass.config.api
    scheme = "https" if api is not None and api.use_ssl else "http"
    port = api.port if api is not None else 8123
    return f"{scheme}://127.0.0.1:{port}/api/{DOMAIN}/live/{stream.serial}?token={stream.internal_token}"


# How long the card's signed picture URL stays valid. It is short because the
# card asks for a fresh one on every play, and a leaked link should not last.
CARD_MJPEG_TTL = timedelta(seconds=300)


def card_mjpeg_path(serial: str) -> str:
    """The card's picture path (its authenticated view), before it is signed."""
    return f"/api/{DOMAIN}/card/{serial}"


def rtsp_entry(hass: HomeAssistant, serial: str) -> ConfigEntry | None:
    """The camera's own (non-ignored) RTSP config entry, if it has one.

    One camera's serial can appear in more than one entry (a cloud entry and a
    local RTSP one); only the non-ignored entry means the camera has local RTSP.
    """
    from homeassistant.config_entries import SOURCE_IGNORE

    return next(
        (
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.unique_id == serial and entry.source != SOURCE_IGNORE
        ),
        None,
    )


def uses_cloud_stream(hass: HomeAssistant, serial: str) -> bool:
    """Whether a camera plays through the cloud (it has no local RTSP entry)."""
    return rtsp_entry(hass, serial) is None


def is_battery_camera(data: Mapping[str, Any]) -> bool:
    """Whether a camera runs on battery (no local RTSP, sleeps between wakes).

    EZVIZ reports a battery level or a battery work mode for these; they expose
    no RTSP server, so the local ``rtsp://`` source can never play them.
    """
    return (
        data.get("battery_level") is not None
        or data.get("battery_camera_work_mode") is not None
    )


def async_setup_live_streams(
    hass: HomeAssistant, entry: EzvizConfigEntry, coordinator: EzvizDataUpdateCoordinator
) -> None:
    """Register the live view and build one cloud stream per camera.

    A camera with no local RTSP (battery cameras, peepholes) plays through these
    streams; the camera entity uses them only when it has no RTSP credentials.
    The stream does nothing until it is read, so building one per camera is free.
    """
    if not hass.data.get(DATA_LIVE_VIEW):
        hass.data[DATA_LIVE_VIEW] = True
        hass.http.register_view(LiveStreamView())
        hass.http.register_view(LiveMjpegView())
        hass.http.register_view(LiveCardMjpegView())
        hass.http.register_view(RecordingClipView())

    options = dict(entry.options)
    token = options.get(CONF_STREAM_TOKEN)
    internal_token = options.get(CONF_INTERNAL_TOKEN)
    changed = False
    if not token:
        # Persist a random token so the addresses other apps hold survive a restart.
        token = secrets.token_urlsafe(24)
        changed = True
    if not internal_token:
        # A separate token for the card's own picture address.
        internal_token = secrets.token_urlsafe(24)
        changed = True
    if changed:
        hass.config_entries.async_update_entry(
            entry,
            options={
                **options,
                CONF_STREAM_TOKEN: token,
                CONF_INTERNAL_TOKEN: internal_token,
            },
        )
    # Whether other apps may read the public addresses at all (the card always can).
    # Off by default: the addresses are opt-in.
    stream_enabled = bool(entry.options.get(CONF_STREAM_ENABLED, False))
    # Transcode by default: the cloud stream is HEVC, which most browsers can't
    # play, and the whole point of this fork is to make battery cameras visible.
    transcode = bool(entry.options.get(CONF_TRANSCODE, True))
    # How long one battery-camera stream may run before it is cut off (0 = never).
    max_session = float(entry.options.get(CONF_MAX_SESSION, MAX_SESSION))
    # How long the stream is held open after the last viewer leaves, so a quick
    # re-open does not wake the camera again (0 closes it at once).
    linger = float(entry.options.get(CONF_LINGER, LINGER))
    for serial, value in coordinator.data.items():
        def _code(serial: str = serial) -> str | None:
            return entry.options.get(CONF_CODES, {}).get(serial)

        # A battery camera gets a hard session cap, so it can never be left
        # streaming and draining (see LiveStream.battery / max_session).
        battery = is_battery_camera(value)
        coordinator.live_streams[serial] = LiveStream(
            hass,
            coordinator,
            serial,
            1,
            _code,
            token=token,
            internal_token=internal_token,
            external_enabled=stream_enabled,
            transcode=transcode,
            encrypted=bool(value.get("encrypted")),
            battery=battery,
            max_session=max_session,
            linger=linger,
        )


async def async_close_live_streams(coordinator: EzvizDataUpdateCoordinator) -> None:
    """Close every cloud stream of an entry (it is unloading)."""
    for stream in coordinator.live_streams.values():
        await stream.async_close()
