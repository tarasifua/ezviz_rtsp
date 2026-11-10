"""A camera's SD-card recordings: list them and play one back.

Cameras with an SD card record events (or continuously) on the card, and the
EZVIZ cloud can do two things with that card the mobile app relies on:

* **search** it: ``/v3/streaming/v2/records`` returns the recorded intervals of
  a time window, at most 50 per answer, oldest first, in the camera's local
  time. ``async_list_day`` pages through one local day and caches it.
* **replay** an interval: the VTM relay that carries the live view also serves
  SD playback. ``_download_clip`` reads one interval as MPEG-PS (pyezvizapi),
  and ffmpeg turns it into an MP4 the browser can play: the original HEVC
  copied as is for browsers that play HEVC, or re-encoded to H.264 for the
  rest. Finished clips are kept in a small cache on disk, so seeking (HTTP
  range requests) and a second play don't wake the camera again.

Both go through the camera: a sleeping battery camera is woken for a replay, so
the card only ever fetches a clip when someone taps it.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import shutil
import tempfile
import time
import zlib
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView

from .const import CONF_CODES, DOMAIN

if TYPE_CHECKING:
    from .coordinator import EzvizConfigEntry, EzvizDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# The SD index answers at most this many records per request (asking for more
# changes nothing), oldest first.
PAGE_SIZE = 50
# A busy camera records a few hundred clips a day; this bounds one day's search.
MAX_PAGES = 40
# A past day's list is kept until the card asks for a refresh; today's for this long.
TODAY_TTL = 60.0
# The camera channel recordings are searched and replayed on (0 is refused).
CHANNEL = 1
# A sleeping camera answers its first search with EZVIZ error 2009; retry once after this long.
WAKE_RETRY_SECONDS = 5.0

# Replay: give up if the camera hasn't delivered the whole clip in this time
# (it may first have to wake up), and call a clip finished once no data came
# for IDLE seconds after the first packet.
CLIP_DEADLINE = 90.0
CLIP_IDLE = 4.0
# The socket's own timeout must outlast a camera waking up.
CLIP_SOCKET_TIMEOUT = 30.0
CLIP_MAX_BYTES = 96 * 1024 * 1024
# A recording longer than this is not a clip; refuse it rather than stream an hour.
MAX_CLIP_SECONDS = 15 * 60
# Finished MP4s kept on disk (per Home Assistant instance), oldest dropped first.
CACHE_CLIPS = 16
_FFMPEG_TIMEOUT = 120

FORMATS = ("hevc", "h264")


class RecordingError(Exception):
    """Listing or replaying a recording failed; the message is shown on the card."""


@dataclass
class _Day:
    """One local day's recordings of one camera."""

    recordings: list[tuple[datetime, datetime]]
    fetched: float
    complete: bool


@dataclass
class RecordingStore:
    """Per Home Assistant: the day lists, the clip cache and its locks."""

    root: Path
    days: dict[tuple[str, date], _Day] = field(default_factory=dict)
    clips: OrderedDict[tuple[str, str, str, str], Path] = field(default_factory=OrderedDict)
    pending: dict[tuple[str, str, str, str], asyncio.Future[Path]] = field(default_factory=dict)
    # One SD request per camera at a time: EZVIZ refuses parallel sessions.
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def lock(self, serial: str) -> asyncio.Lock:
        """The lock that serialises SD requests to one camera."""
        return self.locks.setdefault(serial, asyncio.Lock())


DATA_RECORDINGS = f"{DOMAIN}_recordings"


def get_store(hass: HomeAssistant) -> RecordingStore:
    """The recording store, made on first use with a private clip directory."""
    store: RecordingStore | None = hass.data.get(DATA_RECORDINGS)
    if store is None:
        root = Path(tempfile.mkdtemp(prefix=f"{DOMAIN}_clips_"))
        store = RecordingStore(root)
        hass.data[DATA_RECORDINGS] = store
    return store


async def async_close_store(hass: HomeAssistant) -> None:
    """Drop the cache and its directory (the last entry is unloading)."""
    store: RecordingStore | None = hass.data.pop(DATA_RECORDINGS, None)
    if store is not None:
        await hass.async_add_executor_job(shutil.rmtree, store.root, True)


# -- finding a camera ------------------------------------------------------------


@dataclass(frozen=True)
class Camera:
    """The account client and settings a camera's recordings are read with."""

    coordinator: EzvizDataUpdateCoordinator
    serial: str
    code: str | None


def find_camera(hass: HomeAssistant, serial: str) -> Camera | None:
    """The cloud camera of any loaded entry, with its verification code if encrypted."""
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator: EzvizDataUpdateCoordinator | None = getattr(entry, "runtime_data", None)
        data = getattr(coordinator, "data", None) or {}
        if serial in data and coordinator is not None:
            return Camera(coordinator, serial, _code(entry, data[serial], serial))
    return None


def _code(entry: EzvizConfigEntry, value: Mapping[str, Any], serial: str) -> str | None:
    # A stored code only means something while the camera encrypts its video.
    if not value.get("encrypted"):
        return None
    return entry.options.get(CONF_CODES, {}).get(serial)


# -- listing ---------------------------------------------------------------------


def decode_records(payload: Any) -> tuple[list[Any], bool]:
    """The records of a search answer, and whether the index says there are more.

    The list arrives either plain or as base64 of zlib-compressed JSON (the app's
    format, sometimes zero-padded after the compressed stream).
    """
    if not isinstance(payload, Mapping):
        return [], False
    more = payload.get("isFinished") in (0, False)
    value = payload.get("records")
    if value is None or value == "":
        return [], more
    if isinstance(value, list):
        return value, more
    if isinstance(value, str):
        try:
            decoder = zlib.decompressobj()
            raw = decoder.decompress(base64.b64decode(value, validate=True), 8 * 1024 * 1024)
            records = json.loads(raw)
        except (ValueError, zlib.error) as err:
            raise RecordingError("The camera's recording list could not be read") from err
        if isinstance(records, list):
            return records, more
    raise RecordingError("The camera's recording list could not be read")


def _local(value: Any, tz: ZoneInfo) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=tz)


def search_day(
    client: Any, serial: str, day: date, tz: ZoneInfo, now: datetime
) -> tuple[list[tuple[datetime, datetime]], bool]:
    """All recordings that start on ``day`` (local), oldest first. Blocking.

    The index returns at most 50 records from the window's start, so the next
    request starts one second after the last record seen. The second value says
    whether the whole day was read (False when the page budget ran out).
    """
    from pyezvizapi.exceptions import PyEzvizError

    start = datetime.combine(day, datetime.min.time(), tz)
    end = min(start + timedelta(days=1), now.astimezone(tz).replace(microsecond=0))
    found: dict[tuple[datetime, datetime], None] = {}
    cursor = start
    retried = False
    for _ in range(MAX_PAGES):
        if cursor >= end:
            return list(found), True
        try:
            answer = client.search_records_v2(
                serial,
                CHANNEL,
                cursor.strftime("%Y-%m-%d %H:%M:%S"),
                end.strftime("%Y-%m-%d %H:%M:%S"),
                size=PAGE_SIZE,
            )
        except PyEzvizError as err:
            # A sleeping camera answers the first search with 2009 while it wakes
            # (like capture_picture); ask once more after a moment.
            if "2009" not in str(err) or retried:
                raise RecordingError(_explain(err)) from err
            retried = True
            time.sleep(WAKE_RETRY_SECONDS)
            continue
        records, more = decode_records(answer)
        latest = cursor
        for record in records:
            if not isinstance(record, Mapping):
                continue
            begin = _local(record.get("B"), tz)
            stop = _local(record.get("E"), tz)
            if begin is None or stop is None or stop <= begin:
                continue
            found[(begin, stop)] = None
            latest = max(latest, begin)
        if not more or not records:
            return sorted(found), True
        # Resume one second after the newest start seen (always moving forward);
        # a record seen twice is deduplicated above.
        cursor = max(latest, cursor) + timedelta(seconds=1)
    return sorted(found), False


def _explain(err: Exception) -> str:
    text = str(err)
    if "2009" in text:
        return "The camera did not answer in time; it may be asleep or offline. Try again."
    if "2004" in text:
        return "The camera reported a problem reading its SD card."
    return f"Could not read the camera's recordings: {text}"


async def async_list_day(
    hass: HomeAssistant, camera: Camera, day: date, *, refresh: bool = False
) -> tuple[list[tuple[datetime, datetime]], bool]:
    """A local day's recordings, from the cache unless stale or ``refresh``."""
    store = get_store(hass)
    tz = ZoneInfo(hass.config.time_zone)
    now = datetime.now(tz)
    key = (camera.serial, day)
    cached = store.days.get(key)
    loop_now = time.monotonic()
    if cached is not None and not refresh:
        past = day < now.date()
        if past or loop_now - cached.fetched < TODAY_TTL:
            return cached.recordings, cached.complete
    if day > now.date():
        return [], True
    async with store.lock(camera.serial):
        recordings, complete = await hass.async_add_executor_job(
            search_day, camera.coordinator.ezviz_client, camera.serial, day, tz, now
        )
    store.days[key] = _Day(recordings, time.monotonic(), complete)
    return recordings, complete


# -- replay ----------------------------------------------------------------------


def utc_stamp(moment: datetime) -> str:
    """A UTC instant in the form pyezvizapi's playback takes (20261110T083702Z)."""
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def parse_stamp(value: str) -> datetime:
    """Read a UTC stamp back; raises RecordingError when malformed."""
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError) as err:
        raise RecordingError(f"Not a recording time: {value!r}") from err


def _download_clip(
    client: Any, serial: str, begin: str, end: str, timezone: str, code: str | None
) -> bytes:
    """One SD interval as MPEG-PS through the cloud relay. Blocking.

    pyezvizapi's own ``save_clip`` refuses a clip whose video falls a fraction
    of a second short of the requested range (the camera often closes the file
    early), so this reads the relay directly and keeps whatever arrived.
    """
    from pyezvizapi.exceptions import EzvizPlaybackNegotiationError, PyEzvizError
    from pyezvizapi.streaming.cloud.playback import open_cloud_playback_stream
    from pyezvizapi.streaming.cloud.protocol import (
        VtmStreamEOF,
        VtmStreamTimeout,
        decrypt_hikvision_ps_video,
    )

    deadline = time.monotonic() + CLIP_DEADLINE
    data = bytearray()
    try:
        stream = open_cloud_playback_stream(
            client,
            serial,
            begin,
            end,
            channel=CHANNEL,
            timezone=timezone,
            timeout=CLIP_SOCKET_TIMEOUT,
            capture_deadline=deadline,
        )
        try:
            info = stream.start(deadline=deadline)
            if info.result not in (None, 0):
                raise EzvizPlaybackNegotiationError(info.result)

            def _take(**limits: Any) -> int:
                taken = 0
                for packet in stream.iter_packets(
                    duration_seconds=max(deadline - time.monotonic(), 1.0),
                    duration_from_start=True,
                    **limits,
                ):
                    if packet.encrypted:
                        raise RecordingError("The camera sent the clip on an encrypted channel")
                    data.extend(packet.body)
                    taken += 1
                    if len(data) > CLIP_MAX_BYTES:
                        raise RecordingError("The recording is too large to play here")
                return taken

            try:
                # A sleeping camera takes a while to send its first packet: wait
                # for it against the whole deadline. pyezvizapi's idle timer runs
                # from the start of iteration, so it only applies afterwards, when
                # IDLE seconds without data mean the clip is over.
                if _take(first_packet_deadline=deadline, max_packets=1):
                    _take(stream_packet_timeout_seconds=CLIP_IDLE)
            except VtmStreamEOF:
                pass
            except VtmStreamTimeout:
                if not data:
                    raise
        finally:
            with contextlib.suppress(OSError):
                stream.close()
    except EzvizPlaybackNegotiationError as err:
        raise RecordingError(
            f"The camera refused to play the recording (code {err.result_code}); "
            "it may be busy with another viewer. Try again."
        ) from err
    except (PyEzvizError, OSError) as err:
        if isinstance(err, RecordingError):
            raise
        raise RecordingError(f"The recording could not be played: {err}") from err
    if not data:
        raise RecordingError("The camera sent no video for this recording")
    clip = bytes(data)
    if code:
        clip = decrypt_hikvision_ps_video(clip, code, nalu_header_size=None)
    return clip


def ffmpeg_args(fmt: str) -> tuple[str, ...]:
    """ffmpeg output options for an MP4 of the chosen video format."""
    if fmt == "hevc":
        # Copy the camera's HEVC; Safari needs the hvc1 tag to play it.
        video = ("-c:v", "copy", "-tag:v", "hvc1")
    else:
        video = (
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-pix_fmt", "yuv420p", "-profile:v", "high",
        )
    return (
        "-map", "0:v:0", *video,
        "-map", "0:a:0?", "-c:a", "aac", "-b:a", "64k",
        "-movflags", "+faststart", "-f", "mp4",
    )


async def _async_to_mp4(ffmpeg_bin: str, ps: bytes, fmt: str, target: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_bin,
        "-hide_banner", "-loglevel", "error", "-y",
        "-fflags", "+genpts", "-f", "mpeg", "-i", "pipe:0",
        *ffmpeg_args(fmt), str(target),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(_FFMPEG_TIMEOUT):
            _, err = await proc.communicate(ps)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise RecordingError("Converting the recording took too long") from exc
    if proc.returncode != 0:
        message = err.decode(errors="replace").strip().splitlines()
        raise RecordingError(
            f"The recording could not be converted: {message[-1] if message else proc.returncode}"
        )


async def async_get_clip(
    hass: HomeAssistant, camera: Camera, begin: datetime, end: datetime, fmt: str
) -> Path:
    """The MP4 of one recording, from the cache or fetched from the camera now."""
    if fmt not in FORMATS:
        raise RecordingError(f"Unknown format {fmt!r}")
    if end <= begin:
        raise RecordingError("A recording must end after it begins")
    if (end - begin).total_seconds() > MAX_CLIP_SECONDS:
        raise RecordingError("The recording is too long to play here")
    store = get_store(hass)
    key = (camera.serial, utc_stamp(begin), utc_stamp(end), fmt)
    if (path := store.clips.get(key)) is not None:
        store.clips.move_to_end(key)
        return path
    if (pending := store.pending.get(key)) is not None:
        return await asyncio.shield(pending)
    future: asyncio.Future[Path] = asyncio.get_running_loop().create_future()
    store.pending[key] = future
    try:
        path = await _async_fetch(hass, store, camera, key, fmt)
    except BaseException as err:
        future.set_exception(err if isinstance(err, Exception) else RecordingError("Cancelled"))
        future.exception()  # mark retrieved: nobody else may be waiting
        raise
    finally:
        store.pending.pop(key, None)
    future.set_result(path)
    return path


async def _async_fetch(
    hass: HomeAssistant,
    store: RecordingStore,
    camera: Camera,
    key: tuple[str, str, str, str],
    fmt: str,
) -> Path:
    from .live import ffmpeg_binary, find_stream

    serial, begin, end, _ = key
    live = find_stream(hass, serial)
    if live is not None and live.active:
        raise RecordingError("The camera is streaming live; stop the live view first")
    started = time.monotonic()
    async with store.lock(serial):
        ps = await hass.async_add_executor_job(
            _download_clip,
            camera.coordinator.ezviz_client,
            serial,
            begin,
            end,
            hass.config.time_zone,
            camera.code,
        )
    fetched = time.monotonic()
    target = store.root / f"{serial}_{begin}_{end}_{fmt}.mp4"
    await _async_to_mp4(ffmpeg_binary(hass), ps, fmt, target)
    _LOGGER.debug(
        "Recording %s %s-%s: %d bytes from the camera in %.1f s, %s MP4 in %.1f s",
        serial, begin, end, len(ps), fetched - started, fmt, time.monotonic() - fetched,
    )
    store.clips[key] = target
    store.clips.move_to_end(key)
    while len(store.clips) > CACHE_CLIPS:
        _, old = store.clips.popitem(last=False)
        await hass.async_add_executor_job(old.unlink, True)
    return target


def clip_path(serial: str, begin: str, end: str, fmt: str) -> str:
    """The clip view's path, before it is signed for the card."""
    return f"/api/{DOMAIN}/recording/{serial}/{begin}/{end}/{fmt}.mp4"


class RecordingClipView(HomeAssistantView):
    """Serves a cached recording as MP4, with range requests for seeking.

    Behind Home Assistant authentication; the card reaches it through a short
    signed path that the ``recording/clip`` websocket command hands out once
    the clip is ready, so a request here never waits on the camera.
    """

    url = f"/api/{DOMAIN}/recording/{{serial}}/{{begin}}/{{end}}/{{fmt}}.mp4"
    name = f"api:{DOMAIN}:recording"
    requires_auth = True

    async def get(
        self, request: web.Request, serial: str, begin: str, end: str, fmt: str
    ) -> web.StreamResponse:
        """The clip's file, or 404 once it has left the cache."""
        hass = request.app[KEY_HASS]
        store: RecordingStore | None = hass.data.get(DATA_RECORDINGS)
        path = store.clips.get((serial, begin, end, fmt)) if store is not None else None
        if path is None:
            raise web.HTTPNotFound
        return web.FileResponse(
            path, headers={"Content-Type": "video/mp4", "Cache-Control": "private, max-age=3600"}
        )
