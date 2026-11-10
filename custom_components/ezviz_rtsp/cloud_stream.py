"""The EZVIZ VTM cloud live stream, for cameras that expose no local RTSP.

Battery cameras (and some others) sleep and have no RTSP server, so the
integration's usual ``rtsp://`` source can't play them. The EZVIZ mobile app
falls back to the cloud relay: it opens a VTM session, the cloud wakes the
camera and relays its MPEG-PS. This module does the same through ``pyezvizapi``,
cuts the stream into frames and decrypts the NAL bodies when video encryption is
on (the camera's verification code is the AES key).

The blocking socket work (``LiveSource``) must run in the executor or a thread;
``async_iter_payloads`` bridges it to asyncio.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncIterator
from typing import Any

_LOGGER = logging.getLogger(__name__)


class EzvizStreamError(Exception):
    """The cloud live stream could not be opened or read."""


class EzvizStreamDecodeError(EzvizStreamError):
    """ffmpeg found no frame it could decode: a wrong verification code, or a broken stream."""


_IMKH_HEADER = 40  # EZVIZ prefixes the MPEG-PS stream with a 40-byte "IMKH" header.
# MPEG-PS stream types in the program stream map.
_CODECS = {0x1B: "h264", 0x24: "hevc"}
_DEFAULT_CODEC = "hevc"
_FFMPEG_TIMEOUT = 15


class LiveSource:
    """One blocking VTM live stream (open, read packets, close)."""

    def __init__(self, client: Any, serial: str, channel: int, timeout: float = 30.0) -> None:
        self._client = client
        self._serial = serial
        self._channel = channel
        self._timeout = timeout
        self._stream: Any | None = None
        self._lock = threading.Lock()

    @property
    def serial(self) -> str:
        """The camera this stream belongs to, for thread names and logs."""
        return self._serial

    def open(self) -> None:
        """Open the VTM session; raises EzvizStreamError when the camera won't stream."""
        from pyezvizapi.exceptions import PyEzvizError
        from pyezvizapi.streaming.cloud.bootstrap import open_cloud_stream

        try:
            stream = open_cloud_stream(
                self._client, self._serial, channel=self._channel, timeout=self._timeout
            )
            stream.start()
        except PyEzvizError as err:
            raise EzvizStreamError(f"Live stream failed: {err}") from err
        except OSError as err:
            raise EzvizStreamError(f"Live stream failed: {err}") from err
        with self._lock:
            self._stream = stream

    def packets(self) -> Any:
        """The VTM packet iterator; only valid between ``open`` and ``close``."""
        with self._lock:
            stream = self._stream
        if stream is None:
            raise EzvizStreamError("The live stream is not open")
        return stream.iter_packets()

    def close(self) -> None:
        """Close the socket; a reader blocked in recv wakes up with an error."""
        with self._lock:
            stream, self._stream = self._stream, None
        if stream is not None:
            with contextlib.suppress(OSError):
                stream.close()


async def async_iter_payloads(hass: Any, source: LiveSource) -> AsyncIterator[bytes]:
    """Yield MPEG-PS chunks of a VTM stream as they arrive, without blocking HA.

    The socket work runs in a thread; closing the generator (or leaving it early)
    closes the socket and stops the thread.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=64)
    stop = threading.Event()

    def _put(item: tuple[str, Any]) -> bool:
        if stop.is_set():
            return False
        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(queue.put(item), loop).result(timeout=10)
            return True
        return False

    def _run() -> None:
        try:
            source.open()
            for packet in source.packets():
                if stop.is_set():
                    break
                if getattr(packet, "encrypted", False):
                    raise EzvizStreamError(
                        "The camera sent video on an encrypted cloud channel"
                    )
                if packet.body and not _put(("data", packet.body)):
                    break
        except Exception as err:  # noqa: BLE001 - handed to the reader as-is
            _put(("error", err))
        finally:
            source.close()
            _put(("end", None))

    thread = threading.Thread(target=_run, name=f"ezviz-vtm-{source.serial}", daemon=True)
    thread.start()
    try:
        while True:
            kind, value = await queue.get()
            if kind == "data":
                yield value
            elif kind == "error":
                raise EzvizStreamError(str(value)) from value
            else:
                return
    finally:
        stop.set()
        source.close()


class PackSplitter:
    """Cuts the live MPEG-PS into packs, one frame each, as its bytes arrive.

    A pack is complete once the next one starts; a pack carrying a program stream
    map (0xBC) opens a group of pictures, so it holds a keyframe, and the map
    names the codec. Packet lengths are trusted, so payload bytes are never
    mistaken for headers; unknown bytes are skipped up to the next pack.
    """

    def __init__(self, *, skip_first_group: bool) -> None:
        self._buf = bytearray()
        self._header = True
        self._groups = 0
        self._skip = skip_first_group
        self._keyframe = False
        self.codec = _DEFAULT_CODEC

    def feed(self, data: bytes) -> list[tuple[bytes, bool]]:
        """Add ``data``; return the packs it completed, each with whether it is a keyframe."""
        self._buf += data
        if self._header:
            if len(self._buf) < 4:
                return []
            if self._buf[:4] == b"IMKH":
                if len(self._buf) < _IMKH_HEADER:
                    return []
                del self._buf[:_IMKH_HEADER]
            self._header = False
        ps = self._buf
        done: list[tuple[bytes, bool]] = []
        i, start = 0, None
        while i + 6 <= len(ps):
            if ps[i : i + 3] != b"\x00\x00\x01":
                i = ps.find(b"\x00\x00\x01\xba", i + 1)
                if i < 0:
                    i = max(len(ps) - 3, 0)
                    start = None
                    break
                start = None
                continue
            stream_id = ps[i + 3]
            if stream_id == 0xBA:  # pack header: fixed 14 bytes plus stuffing
                if i + 14 > len(ps) or i + 14 + (ps[i + 13] & 7) > len(ps):
                    break
                if start is not None:
                    self._complete(bytes(ps[start:i]), done)
                start, self._keyframe = i, False
                i += 14 + (ps[i + 13] & 7)
                continue
            end = i + 6 + int.from_bytes(ps[i + 4 : i + 6], "big")
            if end > len(ps):
                break
            if stream_id == 0xBC:
                self.codec = _psm_video_codec(bytes(ps[i + 6 : end])) or self.codec
                self._keyframe = True
            i = end
        # Keep the unfinished pack (or the unparsed tail) for the next call.
        del ps[: start if start is not None else i]
        return done

    def _complete(self, pack: bytes, done: list[tuple[bytes, bool]]) -> None:
        if self._keyframe:
            self._groups += 1
        if self._skip and self._groups < 2:
            return
        done.append((pack, self._keyframe))


def decrypt_packs(packs: list[bytes], code: str | None, codec: str) -> list[bytes]:
    """Decrypt whole packs in one go, then cut them back apart. Blocking (CPU-bound).

    Decryption keeps every byte in place, and no NAL unit spans two packs, so
    this equals decrypting each pack on its own.
    """
    if not code:
        return packs
    clear = _decrypt(b"".join(packs), code, codec)
    out, pos = [], 0
    for pack in packs:
        out.append(clear[pos : pos + len(pack)])
        pos += len(pack)
    return out


async def async_ps_to_jpeg(ps: bytes, ffmpeg_bin: str) -> bytes:
    """Decode the first frame of an MPEG-PS stream into a JPEG."""
    jpeg, err = await _ffmpeg(
        ffmpeg_bin, ps, "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "pipe:1"
    )
    if not jpeg.startswith(b"\xff\xd8"):
        raise EzvizStreamDecodeError(f"Could not decode a keyframe: {err or 'no frame decoded'}")
    return jpeg


async def _ffmpeg(ffmpeg_bin: str, ps: bytes, *output: str) -> tuple[bytes, str]:
    """Run ffmpeg on an MPEG-PS fed through stdin; returns stdout and stderr."""
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "mpeg",
        "-i",
        "pipe:0",
        "-map",
        "0:v:0",
        *output,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(_FFMPEG_TIMEOUT):
            out, err = await proc.communicate(ps)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise EzvizStreamError("ffmpeg did not finish in time") from exc
    return out, err.decode(errors="replace").strip()


def _decrypt(ps: bytes, code: str, codec: str) -> bytes:
    """Decrypt the encrypted NAL bodies with the verification code (pyezvizapi).

    The NAL header stays in the clear: two bytes in H.265, one in H.264.
    """
    from pyezvizapi.streaming.cloud.protocol import decrypt_hikvision_ps_video

    return decrypt_hikvision_ps_video(ps, code, nalu_header_size=1 if codec == "h264" else 2)


def _psm_video_codec(psm: bytes) -> str | None:
    """The codec of the video stream (0xE0) listed in a program stream map."""
    j = 4 + int.from_bytes(psm[2:4], "big")  # skip the program stream info
    end = j + 2 + int.from_bytes(psm[j : j + 2], "big")
    j += 2
    while j + 4 <= min(end, len(psm)):
        stream_type, stream_id = psm[j], psm[j + 1]
        if stream_id == 0xE0:
            return _CODECS.get(stream_type)
        j += 4 + int.from_bytes(psm[j + 2 : j + 4], "big")
    return None
