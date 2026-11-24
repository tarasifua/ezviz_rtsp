"""The EZVIZ VTM cloud live stream, for cameras that expose no local RTSP.

Battery cameras (and some others) sleep and have no RTSP server, so the
integration's usual ``rtsp://`` source can't play them. The EZVIZ mobile app
falls back to the cloud relay: it opens a VTM session, the cloud wakes the
camera and relays its video. This module does the same through ``pyezvizapi``,
cuts the stream into MPEG-PS packs and decrypts the NAL bodies when video
encryption is on (the camera's verification code is the AES key).

Most cameras relay MPEG-PS (``PackSplitter``). Some relays RTP instead (the CP3
Pro, for one) with HEVC video and AAC audio; ``RtpToPs`` depacketizes that with
the RTP helpers the vendored ``pyezvizapi`` already carries and muxes it back
into MPEG-PS, so the rest of the live view stays unchanged.

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


_IMKH_HEADER = 40  # EZVIZ prefixes the MPEG-PS stream with a 40-byte "IMKH" header.
# MPEG-PS stream types in the program stream map.
_CODECS = {0x1B: "h264", 0x24: "hevc"}
_DEFAULT_CODEC = "hevc"
# RTP video NAL types that can open a decodable group of pictures.
_KEYFRAMES = {"hevc": frozenset({16, 17, 18, 19, 20, 21}), "h264": frozenset({5})}
_ANNEX_B = b"\x00\x00\x00\x01"


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
        from .pyezvizapi.exceptions import PyEzvizError
        from .pyezvizapi.streaming.cloud.bootstrap import open_cloud_stream

        try:
            stream = open_cloud_stream(
                self._client, self._serial, channel=self._channel, timeout=self._timeout
            )
        except PyEzvizError as err:
            raise EzvizStreamError(f"Live stream failed: {err}") from err
        except OSError as err:
            raise EzvizStreamError(f"Live stream failed: {err}") from err
        try:
            stream.start()
        except (PyEzvizError, OSError) as err:
            # The session is open by now: close it, or the camera keeps a session
            # it will not hand out again (EZVIZ refuses parallel ones).
            with contextlib.suppress(Exception):
                stream.close()
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

    #: MPEG-PS packs are decrypted by the live view, not here.
    decrypts = False

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


class RtpToPs:
    """Cuts an RTP relay into MPEG-PS packs, one frame each, like ``PackSplitter``.

    A few cameras (the CP3 Pro, for one) relay RTP instead of MPEG-PS: HEVC
    video, AAC audio and Hikvision metadata packets, with the video NAL body
    encrypted by the camera's verification code. The vendored ``pyezvizapi``
    already carries every piece this needs — the depacketizer, the decryption
    and an incremental MPEG-PS muxer — so this class only wires them together
    and keeps the interface the live view expects.

    ``feed`` takes one VTM packet body, which is one RTP packet. Decryption
    happens here (the NAL body, not the whole stream), so the live view must not
    decrypt again; that is what ``decrypts`` tells it.
    """

    #: The stream is already decrypted here.
    decrypts = True

    def __init__(self, code: str | None) -> None:
        self._code = code
        self._loaded = False
        self.codec = _DEFAULT_CODEC
        # TEMPORARY diagnostics for issue #3 (CP3 Pro payload type); remove with
        # ``_diagnose`` once the camera's route is understood.
        self._diag_packets = 0
        self._diag_types: dict[int, int] = {}
        self._diag_descriptors: tuple[Any, ...] = ()
        self._diag_unknown: set[int] = set()

    def feed(self, data: bytes) -> list[tuple[bytes, bool]]:
        """Add one RTP packet; return the packs it completed, each with its keyframe flag."""
        if not self._loaded:
            self._load()
        try:
            packet = self._parse(data, idmx=True)
        except self._errors:
            return []
        try:
            self._route.absorb(packet)
        except self._errors as err:
            # A descriptor that contradicts an already-dispatched route must not
            # stop a live view; keep routing the media with what we already know.
            _LOGGER.debug("Ignoring an inconsistent RTP route: %s", err)
        kind = self._route.media_kind(packet)
        self._diagnose(packet, data, kind)
        if kind == "unknown" and packet.payload_type in self._video_types:
            # The CP3 Pro info packet advertises payload type 15 for the video,
            # but the camera sends it as payload type 96. Trust the well-known
            # type when the route cannot classify the packet.
            kind = "video"
        if kind == "video":
            return self._video(packet)
        if kind == "audio":
            return self._audio(packet)
        return []

    def _diagnose(self, packet: Any, data: bytes, kind: str) -> None:
        """TEMPORARY: log routing details for issue #3 (CP3 Pro payload type).

        The CP3 Pro advertises its video under payload type 15 in the info packet
        while sending it as 96. These lines show the raw descriptor bytes and how
        the route classifies each packet, so the fix can target the real cause.
        """
        self._diag_packets += 1
        self._diag_types[packet.payload_type] = self._diag_types.get(packet.payload_type, 0) + 1
        descriptors = self._route.descriptors
        if descriptors != self._diag_descriptors:
            _LOGGER.info("RTP diagnostics: descriptors %s", descriptors)
            self._diag_descriptors = descriptors
        if self._diag_packets <= 12:
            _LOGGER.info(
                "RTP diagnostics: packet %d pt=%d seq=%d ts=%d len=%d kind=%s ext=%s",
                self._diag_packets,
                packet.payload_type,
                packet.sequence,
                packet.timestamp,
                len(packet.payload),
                kind,
                data[:96].hex(" ") or "-",
            )
        if (
            kind == "unknown"
            and packet.payload_type in self._video_types
            and packet.payload_type not in self._diag_unknown
        ):
            self._diag_unknown.add(packet.payload_type)
            _LOGGER.info(
                "RTP diagnostics: pt %d looks like video but is routed as unknown; video types %s",
                packet.payload_type,
                sorted(self._types(self.codec, self._video_types)),
            )
        if self._diag_packets in {12, 1000} or self._diag_packets % 5000 == 0:
            _LOGGER.info(
                "RTP diagnostics: %d packets, payload types %s",
                self._diag_packets,
                self._diag_types,
            )

    def _load(self) -> None:
        from .pyezvizapi.exceptions import PyEzvizError
        from .pyezvizapi.streaming.media.rtp import (
            DEFAULT_AAC_PAYLOAD_TYPES,
            DEFAULT_VIDEO_PAYLOAD_TYPES,
            RtpRouteProfile,
            RtpVideoDepacketizer,
            decrypt_idmx_aac_packets,
            detect_rtp_video_codec,
            parse_rtp_packet,
            rtp_codec_payload_types,
        )
        from .pyezvizapi.streaming.media.rtp_timing import NativeRtpPsMuxer

        self._errors = PyEzvizError
        self._parse = parse_rtp_packet
        self._protocol = None
        self._route = RtpRouteProfile()
        self._depacketizer = RtpVideoDepacketizer
        self._muxer = None
        self._muxer_cls = NativeRtpPsMuxer
        self._detect = detect_rtp_video_codec
        self._aac = decrypt_idmx_aac_packets
        self._codec_types = rtp_codec_payload_types
        self._video_types = DEFAULT_VIDEO_PAYLOAD_TYPES
        self._aac_types = DEFAULT_AAC_PAYLOAD_TYPES
        self._loaded = True

    def _video(self, packet: Any) -> list[tuple[bytes, bool]]:
        if self._protocol is None:
            self.codec = self._video_codec(packet)
            self._protocol = self._depacketizer(
                self.codec, allow_ezviz_headerless_hevc_fu=True
            )
            # Audio is only decrypted when the camera encrypts; declare it in the
            # program stream map only then, or an empty track would be advertised.
            self._muxer = self._muxer_cls(
                self.codec, audio=bool(self._code), allow_audio_clock_jitter=True
            )
        if packet.payload_type not in self._types(self.codec, self._video_types):
            return []
        self._route.mark_media(packet, absorb=False)
        done: list[tuple[bytes, bool]] = []
        for nal in self._protocol.push(packet):
            if not nal:
                continue
            if self._code:
                nal = self._decrypt_nal(nal)
            keyframe = _is_keyframe(nal, self.codec)
            done.extend((pack, keyframe) for pack in self._muxer.video(packet.timestamp, nal))
        return done

    def _audio(self, packet: Any) -> list[tuple[bytes, bool]]:
        if self._code is None or self._muxer is None:
            return []
        types = self._types("aac", self._aac_types)
        if packet.payload_type not in types:
            return []
        audio = self._aac(
            (packet,),
            self._code,
            audio_metadata=self._route.audio_metadata,
            audio_payload_types=types,
            require_contiguous=False,
            allow_timestamp_jitter=True,
        )
        if audio is None:
            return []
        self._route.mark_media(packet, absorb=False)
        return [(pack, False) for pack in self._muxer.audio(packet.timestamp, audio)]

    def _types(self, codec: str, fallback: frozenset[int]) -> frozenset[int]:
        # The descriptor route wins for its own payload types, but a camera may
        # announce a type it never sends (the CP3 Pro announces 15 for PT 96).
        # Keep the well-known types so those packets still reach the consumer.
        return (
            self._codec_types(
                self._route.descriptors, codec, fallback_payload_types=fallback
            )
            | fallback
        )

    def _video_codec(self, packet: Any) -> str:
        try:
            codec = self._detect(
                [packet],
                stream_descriptors=self._route.descriptors,
                allow_ezviz_headerless_hevc_fu=True,
            )
        except self._errors:
            return _DEFAULT_CODEC
        return "h264" if codec == "h264" else "hevc"

    def _decrypt_nal(self, nal: bytes) -> bytes:
        """Decrypt the reassembled NAL with the verification code.

        Only the body is encrypted, in whole 16-byte blocks; the codec header
        stays clear. pyezvizapi wants the NAL as a PES payload, so it is wrapped
        and unwrapped around the call.
        """
        from .pyezvizapi.streaming.cloud.protocol import decrypt_hikvision_ps_video

        header_size = 1 if self.codec == "h264" else 2
        pes = b"\x00\x00\x01\xe0\x00\x00\x80\x00\x00" + _ANNEX_B + nal
        clear = decrypt_hikvision_ps_video(pes, self._code, nalu_header_size=header_size)
        return clear[9:][len(_ANNEX_B) :]


def _is_keyframe(nal: bytes, codec: str) -> bool:
    """Whether a clear NAL header marks a keyframe (an IDR or the groups before one)."""
    if not nal:
        return False
    if codec == "h264":
        return (nal[0] & 0x1F) in _KEYFRAMES["h264"]
    return ((nal[0] >> 1) & 0x3F) in _KEYFRAMES["hevc"]


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


def _decrypt(ps: bytes, code: str, codec: str) -> bytes:
    """Decrypt the encrypted NAL bodies with the verification code (pyezvizapi).

    The NAL header stays in the clear: two bytes in H.265, one in H.264.
    """
    from .pyezvizapi.streaming.cloud.protocol import decrypt_hikvision_ps_video

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
