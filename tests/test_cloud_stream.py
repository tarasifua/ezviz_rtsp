"""Tests for the EZVIZ cloud live stream added to the official integration."""

from __future__ import annotations

import asyncio
import time
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from pyezvizapi.exceptions import PyEzvizError

from custom_components.ezviz_rtsp import live
from custom_components.ezviz_rtsp.cloud_stream import (
    PackSplitter,
    decrypt_packs,
)
from custom_components.ezviz_rtsp.const import DOMAIN, SIGNAL_PICTURE_CAPTURED
from custom_components.ezviz_rtsp.live import (
    EzvizCloudCooldownError,
    LiveCardMjpegView,
    LiveMjpegView,
    LiveStream,
    LiveStreamView,
    async_close_live_streams,
    async_setup_live_streams,
    card_mjpeg_path,
    stream_source,
    uses_cloud_stream,
)

# --- MPEG-PS building blocks (borrowed shapes from real EZVIZ captures) --------

PACK = b"\x00\x00\x01\xba" + b"\x44\x00\x37\xc6\x84\x01\x00\xf5\xc7\xf8"
IMKH = b"IMKH" + b"\x00" * 36


def _pes(payload: bytes) -> bytes:
    body = b"\x80\x00\x00" + payload
    return b"\x00\x00\x01\xe0" + len(body).to_bytes(2, "big") + body


def _psm(stream_type: int = 0x24) -> bytes:
    entries = bytes([stream_type, 0xE0]) + b"\x00\x00"
    body = b"\x80\x01\x00\x00" + len(entries).to_bytes(2, "big") + entries
    return b"\x00\x00\x01\xbc" + len(body).to_bytes(2, "big") + body


def _gop(frame: bytes, stream_type: int = 0x24) -> bytes:
    return PACK + _psm(stream_type) + _pes(frame)


KEY, FRAME = _gop(b"key"), PACK + _pes(b"p")


# --- helpers ------------------------------------------------------------------


def _hass() -> MagicMock:
    hass = MagicMock()
    hass.async_create_background_task = lambda coro, _name: asyncio.create_task(coro)

    async def run(fn, *args):
        return fn(*args)

    hass.async_add_executor_job = run
    hass.data = {}
    return hass


def _coordinator() -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = {
        "BK1": {
            "name": "Door",
            "mac_address": None,
            "device_sub_category": "DP2",
            "version": "1.0",
            "last_alarm_pic": None,
            "encrypted": False,
        }
    }
    coordinator.live_streams = {}
    coordinator.ezviz_client = MagicMock()
    coordinator.snapshot_captures = {}
    return coordinator


def _stream(code: str | None = None) -> LiveStream:
    return LiveStream(
        _hass(), _coordinator(), "BK1", 1, lambda: code, encrypted=bool(code)
    )


class _Upstream:
    """Stands in for the VTM socket bridge: yields what the test feeds it."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[bytes | Exception | None] = asyncio.Queue()
        self.opens = 0
        self.closed = 0

    async def __call__(self, _hass: object, _source: object):
        self.opens += 1
        try:
            while (item := await self.queue.get()) is not None:
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            self.closed += 1


@pytest.fixture
def upstream():
    fake = _Upstream()
    with patch.object(live, "async_iter_payloads", fake):
        yield fake


async def _take(frames, n: int) -> list[bytes]:
    return [await anext(frames) for _ in range(n)]


# --- PackSplitter / decrypt ---------------------------------------------------


def test_splitter_skips_the_first_group_and_flags_keyframes() -> None:
    splitter = PackSplitter(skip_first_group=True)
    out = splitter.feed(IMKH + _gop(b"stale") + KEY + FRAME + PACK)
    assert out == [(KEY, True), (FRAME, False)]
    assert splitter.codec == "hevc"


def test_splitter_keeps_everything_without_skip() -> None:
    splitter = PackSplitter(skip_first_group=False)
    out = splitter.feed(IMKH + KEY + FRAME + PACK)
    assert out == [(KEY, True), (FRAME, False)]


def test_decrypt_packs_decrypts_together_and_cuts_back(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "custom_components.ezviz_rtsp.cloud_stream._decrypt",
        lambda ps, code, codec: calls.append((ps, code, codec)) or ps.upper(),
    )
    assert decrypt_packs([b"ab", b"cde"], "KEY", "h264") == [b"AB", b"CDE"]
    assert calls == [(b"abcde", "KEY", "h264")]
    assert decrypt_packs([b"ab"], None, "hevc") == [b"ab"]


# --- LiveStream ---------------------------------------------------------------


async def test_readers_share_one_stream_and_start_at_a_keyframe(upstream) -> None:
    stream = _stream()
    first = stream.frames()
    pending = asyncio.ensure_future(_take(first, 2))
    await asyncio.sleep(0)
    upstream.queue.put_nowait(IMKH + FRAME + KEY + FRAME + PACK)
    assert await pending == [KEY, FRAME]
    assert upstream.opens == 1
    await first.aclose()
    await stream.async_close()


async def test_failed_open_reaches_readers_and_starts_a_cooldown(upstream) -> None:
    stream = _stream()
    upstream.queue.put_nowait(live.EzvizStreamError("5405"))
    stream.on_no_video = MagicMock()
    with pytest.raises(live.EzvizStreamError, match="5405"):
        await anext(stream.frames())
    with pytest.raises(EzvizCloudCooldownError):
        await anext(stream.frames())
    stream.on_no_video.assert_called_once_with()


async def test_code_decrypts_and_skips_the_first_group(upstream) -> None:
    stream = _stream("SECRET")
    calls = []

    def fake_decrypt(packs, code, codec):
        calls.append((code, codec))
        return [p.upper() for p in packs]

    with patch.object(live, "decrypt_packs", fake_decrypt):
        frames = stream.frames()
        pending = asyncio.ensure_future(anext(frames))
        await asyncio.sleep(0)
        upstream.queue.put_nowait(IMKH + _gop(b"stale") + KEY + PACK)
        assert await pending == KEY.upper()
        await frames.aclose()
    assert calls == [("SECRET", "hevc")]
    await stream.async_close()


async def test_close_stops_the_stream(upstream) -> None:
    stream = _stream()
    frames = stream.frames()
    pending = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0)
    await stream.async_close()
    with pytest.raises(StopAsyncIteration):
        await pending
    assert not stream.active


async def test_stored_code_is_ignored_for_a_clear_camera(upstream) -> None:
    # A code on a camera that doesn't encrypt video must not be applied.
    stream = LiveStream(
        _hass(), _coordinator(), "BK1", 1, lambda: "SECRET", encrypted=False
    )
    with patch.object(live, "decrypt_packs") as decrypt:
        frames = stream.frames()
        pending = asyncio.ensure_future(anext(frames))
        await asyncio.sleep(0)
        upstream.queue.put_nowait(IMKH + KEY + PACK)
        assert await pending == KEY
        await frames.aclose()
    decrypt.assert_not_called()
    await stream.async_close()


async def test_battery_stream_has_a_hard_session_limit(upstream) -> None:
    # A battery camera must be closed even if a reader never lets go.
    stream = LiveStream(
        _hass(), _coordinator(), "BK1", 1, lambda: None, battery=True
    )
    frames = stream.frames()
    pending = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0)
    upstream.queue.put_nowait(IMKH + KEY + PACK)
    assert await pending == KEY
    assert stream._deadline is not None
    stream._session_timeout()
    await asyncio.sleep(0)
    with pytest.raises(StopAsyncIteration):
        await anext(frames)
    await frames.aclose()
    await stream.async_close()


async def test_powered_stream_has_no_hard_limit(upstream) -> None:
    stream = _stream()
    frames = stream.frames()
    pending = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0)
    upstream.queue.put_nowait(IMKH + KEY + PACK)
    assert await pending == KEY
    assert stream._deadline is None
    await frames.aclose()
    await stream.async_close()


def test_linger_defaults_and_is_configurable() -> None:
    assert live.LINGER == 10
    assert _stream()._linger_seconds == 10
    stream = LiveStream(_hass(), _coordinator(), "BK1", 1, lambda: None, linger=3)
    assert stream._linger_seconds == 3


async def test_battery_stream_without_a_limit_has_no_deadline(upstream) -> None:
    stream = LiveStream(
        _hass(), _coordinator(), "BK1", 1, lambda: None, battery=True, max_session=0
    )
    frames = stream.frames()
    pending = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0)
    upstream.queue.put_nowait(IMKH + KEY + PACK)
    assert await pending == KEY
    assert stream._deadline is None
    await frames.aclose()
    await stream.async_close()


# --- LiveStreamView -----------------------------------------------------------


class _Proc:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stdin_data = bytearray()
        self._out: asyncio.Queue[bytes] = asyncio.Queue()
        self.killed = False
        proc = self

        class _Stdin:
            def write(self, data: bytes) -> None:
                proc.stdin_data += data
                proc._out.put_nowait(b"ts:" + data)

            async def drain(self) -> None:
                return None

            def close(self) -> None:
                proc._out.put_nowait(b"")

        class _Stdout:
            async def read(self, _n: int) -> bytes:
                return await proc._out.get()

        self.stdin = _Stdin()
        self.stdout = _Stdout()

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode or -9


def _request(hass, token: str) -> MagicMock:
    request = MagicMock()
    request.app = {live.KEY_HASS: hass}
    request.query = {"token": token}
    return request


def _allows(stream):
    """Give a mocked stream the real token check (its attribute is auto-mocked)."""
    if stream is not None:
        stream.allows = types.MethodType(LiveStream.allows, stream)
    return stream


async def _serve(stream, token: str, proc=None):
    _allows(stream)
    hass = MagicMock()
    written: list[bytes] = []
    response = MagicMock()
    response.prepare = AsyncMock()
    response.write = AsyncMock(side_effect=written.append)
    with (
        patch.object(live, "find_stream", return_value=stream),
        patch.object(live, "ffmpeg_binary", return_value="/ffmpeg"),
        patch.object(live.web, "StreamResponse", return_value=response),
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc or _Proc())) as spawn,
    ):
        result = await LiveStreamView().get(_request(hass, token), "BK1")
    return result, written, spawn


async def test_view_remuxes_the_stream_to_mpegts() -> None:
    async def frames():
        yield b"key"
        yield b"next"

    proc = _Proc()
    _, written, spawn = await _serve(MagicMock(token="tok", internal_token="tok", frames=frames, transcode=False), "tok", proc)
    assert written == [b"ts:key", b"ts:next"]
    args = spawn.await_args.args
    assert args[args.index("-c") + 1] == "copy"
    assert args[-2:] == ("mpegts", "pipe:1")
    assert proc.killed


async def _serve_mjpeg(stream, token: str, proc=None):
    hass = MagicMock()
    written: list[bytes] = []
    response = MagicMock()
    response.prepare = AsyncMock()
    response.write = AsyncMock(side_effect=written.append)
    with (
        patch.object(live, "find_stream", return_value=stream),
        patch.object(live, "ffmpeg_binary", return_value="/ffmpeg"),
        patch.object(live.web, "StreamResponse", return_value=response),
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc or _Proc())) as spawn,
    ):
        result = await LiveMjpegView().get(_request(hass, token), "BK1")
    return result, written, spawn, response


async def _serve_card(stream, proc=None):
    """Serve the card's authenticated picture view (no token; HA auth is the gate)."""
    hass = MagicMock()
    written: list[bytes] = []
    response = MagicMock()
    response.prepare = AsyncMock()
    response.write = AsyncMock(side_effect=written.append)
    request = MagicMock()
    request.app = {live.KEY_HASS: hass}
    request.query = {}
    with (
        patch.object(live, "find_stream", return_value=stream),
        patch.object(live, "ffmpeg_binary", return_value="/ffmpeg"),
        patch.object(live.web, "StreamResponse", return_value=response),
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc or _Proc())) as spawn,
    ):
        result = await LiveCardMjpegView().get(request, "BK1")
    return result, written, spawn, response


async def test_mjpeg_view_encodes_the_stream_to_jpeg() -> None:
    async def frames():
        yield b"key"
        yield b"next"

    proc = _Proc()
    _, written, spawn, response = await _serve_mjpeg(
        MagicMock(token="tok", external_enabled=True, frames=frames), "tok", proc
    )
    assert written == [b"ts:key", b"ts:next"]
    args = spawn.await_args.args
    assert args[args.index("-c:v") + 1] == "mjpeg"
    assert args[-2:] == ("mpjpeg", "pipe:1")
    # The browser needs the muxer's own boundary in the content type.
    assert response.content_type == "multipart/x-mixed-replace;boundary=ffmpeg"
    assert proc.killed


async def test_card_view_is_authenticated_while_the_public_view_is_not() -> None:
    # The card reads a view HA authenticates (via a signed URL); the token view
    # for other apps keeps working without HA credentials.
    assert LiveCardMjpegView.requires_auth is True
    assert LiveMjpegView.requires_auth is False


async def test_card_view_serves_jpeg_without_a_token() -> None:
    async def frames():
        yield b"key"

    _, written, _, response = await _serve_card(MagicMock(serial="BK1", frames=frames), _Proc())
    assert written == [b"ts:key"]
    assert response.content_type == "multipart/x-mixed-replace;boundary=ffmpeg"


async def test_mjpeg_view_rejects_a_bad_or_internal_token() -> None:
    stream = MagicMock(
        token="pub", internal_token="internal", external_enabled=True, frames=MagicMock()
    )
    with (
        patch.object(live, "find_stream", return_value=stream),
        pytest.raises(live.web.HTTPNotFound),
    ):
        await LiveMjpegView().get(_request(MagicMock(), "wrong"), "BK1")
    # The never-rotating internal token no longer opens the public view.
    with (
        patch.object(live, "find_stream", return_value=stream),
        pytest.raises(live.web.HTTPNotFound),
    ):
        await LiveMjpegView().get(_request(MagicMock(), "internal"), "BK1")


async def test_view_transcodes_to_h264_when_asked() -> None:
    async def frames():
        yield b"key"

    _, _, spawn = await _serve(MagicMock(token="tok", internal_token="tok", frames=frames, transcode=True), "tok")
    args = spawn.await_args.args
    assert args[args.index("-c:v") + 1] == "libx264"


async def test_view_hides_unknown_cameras_and_bad_tokens() -> None:
    from aiohttp import web

    for stream, token in ((None, "tok"), (MagicMock(token="pub", internal_token="int"), "wrong")):
        with pytest.raises(web.HTTPNotFound):
            await _serve(stream, token)


# --- setup / discovery --------------------------------------------------------


def test_uses_cloud_stream_checks_for_an_rtsp_entry() -> None:
    hass = MagicMock()
    rtsp = MagicMock(unique_id="BK1", source="user")
    hass.config_entries.async_entries.return_value = [rtsp]
    assert uses_cloud_stream(hass, "BK1") is False
    assert uses_cloud_stream(hass, "BK2") is True


def test_setup_live_streams_registers_view_and_builds_a_stream_per_camera() -> None:
    hass = _hass()
    coordinator = _coordinator()
    coordinator.data = {"BK1": {"name": "Door"}, "BK2": {"name": "Yard"}}
    entry = MagicMock(options={})
    async_setup_live_streams(hass, entry, coordinator)
    assert set(coordinator.live_streams) == {"BK1", "BK2"}
    # The MPEG-TS view, the public MJPEG view, the card's authenticated view and
    # the recordings card's clip view.
    assert hass.http.register_view.call_count == 4
    views = {type(call.args[0]).__name__ for call in hass.http.register_view.call_args_list}
    assert "RecordingClipView" in views
    # A random token is persisted so other apps' addresses survive a restart.
    stored = hass.config_entries.async_update_entry.call_args.kwargs["options"]["stream_token"]
    assert {s.token for s in coordinator.live_streams.values()} == {stored}
    # The card's own token is persisted too.
    internal = hass.config_entries.async_update_entry.call_args.kwargs["options"]["internal_token"]
    assert {s.internal_token for s in coordinator.live_streams.values()} == {internal}
    # A second entry registers no view again.
    hass.data[DOMAIN + "_live_view_registered"] = True
    hass.http.register_view.reset_mock()
    async_setup_live_streams(hass, MagicMock(options={"stream_token": "kept"}), coordinator)
    hass.http.register_view.assert_not_called()


def test_stream_source_uses_the_ha_port_and_token() -> None:
    hass = MagicMock()
    hass.config.api.use_ssl = False
    hass.config.api.port = 8123
    stream = MagicMock(serial="BK1", internal_token="tok")
    assert stream_source(hass, stream) == (
        "http://127.0.0.1:8123/api/ezviz_rtsp/live/BK1?token=tok"
    )


def test_card_mjpeg_path_is_the_authenticated_view() -> None:
    assert card_mjpeg_path("BK1") == "/api/ezviz_rtsp/card/BK1"


async def test_live_view_blocked_when_other_apps_are_off() -> None:
    async def frames():
        yield b"key"

    # The public token is refused...
    stream = _allows(MagicMock(
        token="pub", internal_token="int", external_enabled=False,
        frames=frames, transcode=False,
    ))
    with (
        patch.object(live, "find_stream", return_value=stream),
        pytest.raises(live.web.HTTPNotFound),
    ):
        await LiveStreamView().get(_request(MagicMock(), "pub"), "BK1")
    # ...but the integration's own token (HA's stream worker) still works.
    _, written, _ = await _serve(stream, "int")
    assert written == [b"ts:key"]


async def test_mjpeg_view_needs_external_enabled_and_the_public_token() -> None:
    async def frames():
        yield b"key"

    stream = MagicMock(
        token="pub", internal_token="int", external_enabled=False, frames=frames
    )
    # With other apps turned off, even the public token is refused.
    with (
        patch.object(live, "find_stream", return_value=stream),
        pytest.raises(live.web.HTTPNotFound),
    ):
        await LiveMjpegView().get(_request(MagicMock(), "pub"), "BK1")
    # Turned on, the public token reads the picture for other apps.
    stream.external_enabled = True
    _, written, _, _ = await _serve_mjpeg(stream, "pub", _Proc())
    assert written == [b"ts:key"]


async def test_close_live_streams_closes_everyone() -> None:
    coordinator = _coordinator()
    a, b = MagicMock(async_close=AsyncMock()), MagicMock(async_close=AsyncMock())
    coordinator.live_streams = {"BK1": a, "BK2": b}
    await async_close_live_streams(coordinator)
    a.async_close.assert_awaited_once()
    b.async_close.assert_awaited_once()


# --- camera -------------------------------------------------------------------


def test_camera_uses_the_cloud_stream_without_rtsp() -> None:
    from custom_components.ezviz_rtsp.camera import EzvizCamera

    hass = MagicMock()
    hass.config.api.use_ssl = False
    hass.config.api.port = 8123
    coordinator = _coordinator()
    coordinator.live_streams = {"BK1": LiveStream(hass, coordinator, "BK1", 1, lambda: None)}
    with patch("custom_components.ezviz_rtsp.camera.get_ffmpeg_manager"):
        camera = EzvizCamera(
            hass,
            coordinator,
            "BK1",
            "admin",
            None,
            "",
            554,
            "/Streaming/Channels/102",
            use_cloud=True,
        )
    assert camera._attr_supported_features is not None
    camera.hass = hass
    camera.entity_id = "camera.door"
    assert asyncio.run(camera.stream_source()) == (
        "http://127.0.0.1:8123/api/ezviz_rtsp/live/BK1?token="
        + coordinator.live_streams["BK1"].internal_token
    )


def test_battery_camera_is_detected() -> None:
    from custom_components.ezviz_rtsp.camera import _is_battery_camera

    assert _is_battery_camera({"battery_level": 52})
    assert _is_battery_camera({"battery_camera_work_mode": 5})
    assert not _is_battery_camera({"local_ip": "1.2.3.4"})


def _cloud_camera(coordinator, hass) -> object:
    from custom_components.ezviz_rtsp.camera import EzvizCamera

    with patch("custom_components.ezviz_rtsp.camera.get_ffmpeg_manager"):
        camera = EzvizCamera(
            hass, coordinator, "BK1", "admin", None, "", 554, "/x", use_cloud=True
        )
    camera.hass = hass
    return camera


async def test_cloud_still_is_none_without_an_alarm_picture() -> None:
    hass = MagicMock()
    coordinator = _coordinator()
    coordinator.live_streams = {"BK1": LiveStream(hass, coordinator, "BK1", 1, lambda: None)}
    camera = _cloud_camera(coordinator, hass)
    assert await camera._async_cloud_still() is None


async def test_cloud_still_fetches_the_alarm_picture() -> None:
    hass = MagicMock()
    coordinator = _coordinator()
    coordinator.data["BK1"]["last_alarm_pic"] = "https://ezviz/pic"
    coordinator.live_streams = {"BK1": LiveStream(hass, coordinator, "BK1", 1, lambda: None)}
    camera = _cloud_camera(coordinator, hass)

    response = MagicMock(status=200)
    response.read = AsyncMock(return_value=b"\xff\xd8pic")
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=ctx)
    with patch(
        "custom_components.ezviz_rtsp.camera.async_get_clientsession", return_value=session
    ):
        assert await camera._async_cloud_still() == b"\xff\xd8pic"


# --- options flow -------------------------------------------------------------


def _options_flow(data: dict) -> MagicMock:
    from custom_components.ezviz_rtsp.config_flow import EzvizOptionsFlowHandler

    flow = EzvizOptionsFlowHandler()
    entry = MagicMock(options={}, data={"type_value": "EZVIZ_CLOUD_ACCOUNT"})
    coordinator = MagicMock()
    coordinator.data = {"BK1": {"name": "Door"}, "BK2": {"name": "Yard"}}
    entry.runtime_data = coordinator
    flow.__dict__["_config_entry"] = entry
    flow.hass = MagicMock()
    return flow, entry


@pytest.fixture(autouse=True)
def _config_entry_property():
    from custom_components.ezviz_rtsp.config_flow import EzvizOptionsFlowHandler

    with patch.object(
        EzvizOptionsFlowHandler,
        "config_entry",
        property(lambda self: self.__dict__["_config_entry"]),
    ):
        yield


async def test_options_codes_step_lists_cloud_cameras() -> None:
    flow, entry = _options_flow({})
    entry.runtime_data.data = {"BK1": {"name": "Door"}}
    with patch("custom_components.ezviz_rtsp.config_flow.uses_cloud_stream", return_value=True):
        result = await flow.async_step_codes()
    assert result["type"] == "form"
    options = result["data_schema"].schema["serial"].config["options"]
    assert [o["value"] for o in options] == ["BK1"]


async def test_options_codes_step_saves_and_removes() -> None:
    flow, entry = _options_flow({})
    result = await flow.async_step_codes({"serial": "BK1", "code": " abcdef "})
    assert result["type"] == "create_entry"
    assert result["data"]["codes"] == {"BK1": "ABCDEF"}

    flow, entry = _options_flow({})
    entry.options = {"codes": {"BK1": "OLDOLD"}}
    result = await flow.async_step_codes({"serial": "BK1", "code": ""})
    assert result["data"]["codes"] == {}


async def test_options_menu_and_video_step() -> None:
    flow, _ = _options_flow({})
    menu = await flow.async_step_init()
    assert menu["type"] == "menu"
    assert menu["menu_options"] == [
        "general",
        "stream",
        "release",
        "snapshots",
        "stream_address",
        "video",
        "codes",
    ]
    result = await flow.async_step_video({"transcode": True})
    assert result["data"]["transcode"] is True


async def test_options_stream_address_step_shows_addresses_and_rotates() -> None:
    flow, entry = _options_flow({})
    entry.options = {"stream_token": "tok123"}
    flow.hass.config.internal_url = "http://ha.local:8123"
    flow.hass.config.external_url = None
    with patch("custom_components.ezviz_rtsp.config_flow.uses_cloud_stream", return_value=True):
        result = await flow.async_step_stream_address()
    assert result["type"] == "form"
    addresses = result["description_placeholders"]["addresses"]
    assert "/api/ezviz_rtsp/live/BK1?token=tok123" in addresses
    assert "/api/ezviz_rtsp/mjpeg/BK1?token=tok123" in addresses

    with patch("custom_components.ezviz_rtsp.config_flow.uses_cloud_stream", return_value=True):
        rotated = await flow.async_step_stream_address({"rotate_token": True})
    assert rotated["data"]["stream_token"] != "tok123"
    # Not rotating keeps the token.
    with patch("custom_components.ezviz_rtsp.config_flow.uses_cloud_stream", return_value=True):
        kept = await flow.async_step_stream_address({"rotate_token": False})
    assert kept["data"]["stream_token"] == "tok123"


async def test_options_stream_address_step_toggles_external_access() -> None:
    flow, entry = _options_flow({})
    entry.options = {"stream_token": "tok123", "stream_enabled": True}
    with patch("custom_components.ezviz_rtsp.config_flow.uses_cloud_stream", return_value=True):
        off = await flow.async_step_stream_address({"stream_enabled": False})
    assert off["data"]["stream_enabled"] is False
    with patch("custom_components.ezviz_rtsp.config_flow.uses_cloud_stream", return_value=True):
        on = await flow.async_step_stream_address({"stream_enabled": True})
    assert on["data"]["stream_enabled"] is True


async def test_options_release_step_saves_the_linger() -> None:
    flow, entry = _options_flow({})
    entry.options = {"transcode": True}
    result = await flow.async_step_release({"linger": 5})
    assert result["data"]["linger"] == 5
    # The other options are kept.
    assert result["data"]["transcode"] is True


async def test_options_stream_step_saves_the_limit() -> None:
    flow, entry = _options_flow({})
    entry.options = {"transcode": True}
    result = await flow.async_step_stream({"max_session": 120})
    assert result["data"]["max_session"] == 120
    # The other options are kept.
    assert result["data"]["transcode"] is True


# --- snapshots: capture_picture service, Snapshot image and options ----------


def _capture_camera(options: dict | None = None):
    """A cloud camera whose coordinator carries the given Snapshots options."""
    hass = _hass()
    coordinator = _coordinator()
    coordinator.config_entry.options = options or {}
    return _cloud_camera(coordinator, hass), coordinator


async def test_capture_picture_returns_the_url_and_notifies_the_snapshot() -> None:
    camera, coordinator = _capture_camera()
    coordinator.ezviz_client.capture_picture.return_value = {
        "captureInfo": {"picUrl": "https://ezviz/pic.jpg"}
    }
    with patch(
        "custom_components.ezviz_rtsp.camera.async_dispatcher_send"
    ) as send:
        result = await camera.async_capture_picture()

    assert result == {"picture_url": "https://ezviz/pic.jpg", "skipped": False}
    coordinator.ezviz_client.capture_picture.assert_called_once_with("BK1", 1)
    send.assert_called_once()
    assert send.call_args.args[1] == SIGNAL_PICTURE_CAPTURED.format("BK1")
    assert send.call_args.args[2] == "https://ezviz/pic.jpg"
    started, url = coordinator.snapshot_captures["BK1"]
    assert started is not None
    assert url == "https://ezviz/pic.jpg"


async def test_capture_picture_is_skipped_inside_min_interval() -> None:
    camera, coordinator = _capture_camera()
    coordinator.snapshot_captures["BK1"] = (
        time.monotonic(),
        "https://ezviz/old.jpg",
    )

    result = await camera.async_capture_picture(min_interval=300)

    assert result == {"picture_url": "https://ezviz/old.jpg", "skipped": True}
    coordinator.ezviz_client.capture_picture.assert_not_called()


async def test_capture_picture_runs_again_after_min_interval() -> None:
    camera, coordinator = _capture_camera()
    coordinator.ezviz_client.capture_picture.return_value = {
        "captureInfo": {"picUrl": "https://ezviz/new.jpg"}
    }
    coordinator.snapshot_captures["BK1"] = (
        time.monotonic() - 400,
        "https://ezviz/old.jpg",
    )

    result = await camera.async_capture_picture(min_interval=300)

    assert result == {"picture_url": "https://ezviz/new.jpg", "skipped": False}
    coordinator.ezviz_client.capture_picture.assert_called_once_with("BK1", 1)


async def test_capture_picture_retries_once_when_the_camera_is_still_waking() -> None:
    camera, coordinator = _capture_camera()
    coordinator.ezviz_client.capture_picture.side_effect = [
        PyEzvizError("Error: Got {'meta': {'code': 2009, 'message': 'waking'}}"),
        {"captureInfo": {"picUrl": "https://ezviz/pic.jpg"}},
    ]

    with patch("asyncio.sleep", AsyncMock()) as sleep:
        result = await camera.async_capture_picture()

    assert result == {"picture_url": "https://ezviz/pic.jpg", "skipped": False}
    assert coordinator.ezviz_client.capture_picture.call_count == 2
    sleep.assert_awaited_once_with(5)


async def test_capture_picture_other_errors_raise_and_release_the_throttle() -> None:
    camera, coordinator = _capture_camera()
    coordinator.ezviz_client.capture_picture.side_effect = PyEzvizError(
        "Error: Got {'meta': {'code': 4001, 'message': 'nope'}}"
    )

    with pytest.raises(HomeAssistantError, match="Cannot capture picture"):
        await camera.async_capture_picture()

    assert coordinator.ezviz_client.capture_picture.call_count == 1
    # A failed capture must not hold off the next try.
    assert coordinator.snapshot_captures.get("BK1", (None, None))[0] is None


async def test_capture_picture_without_a_url_raises() -> None:
    camera, coordinator = _capture_camera()
    coordinator.ezviz_client.capture_picture.return_value = {"captureInfo": {}}

    with pytest.raises(HomeAssistantError, match="no picture url"):
        await camera.async_capture_picture()

    assert coordinator.snapshot_captures.get("BK1", (None, None))[0] is None


async def test_capture_picture_automatic_obeys_the_master_switch() -> None:
    camera, coordinator = _capture_camera({"auto_snapshot": False})
    coordinator.snapshot_captures["BK1"] = (None, "https://ezviz/last.jpg")

    result = await camera.async_capture_picture(automatic=True)

    assert result == {"picture_url": "https://ezviz/last.jpg", "skipped": True}
    coordinator.ezviz_client.capture_picture.assert_not_called()


async def test_capture_picture_automatic_uses_the_configured_interval() -> None:
    camera, coordinator = _capture_camera(
        {"auto_snapshot": True, "snapshot_interval": 300}
    )
    coordinator.snapshot_captures["BK1"] = (
        time.monotonic() - 100,
        "https://ezviz/recent.jpg",
    )

    result = await camera.async_capture_picture(automatic=True)

    assert result == {"picture_url": "https://ezviz/recent.jpg", "skipped": True}
    coordinator.ezviz_client.capture_picture.assert_not_called()


async def test_capture_picture_explicit_call_ignores_the_master_switch() -> None:
    camera, coordinator = _capture_camera({"auto_snapshot": False})
    coordinator.ezviz_client.capture_picture.return_value = {
        "captureInfo": {"picUrl": "https://ezviz/pic.jpg"}
    }

    result = await camera.async_capture_picture()

    assert result["skipped"] is False
    coordinator.ezviz_client.capture_picture.assert_called_once_with("BK1", 1)


async def test_snapshot_button_takes_a_picture_and_updates_the_state() -> None:
    from custom_components.ezviz_rtsp.button import EzvizSnapshotButton

    hass = _hass()
    coordinator = _coordinator()
    coordinator.ezviz_client.capture_picture.return_value = {
        "captureInfo": {"picUrl": "https://ezviz/pic.jpg"}
    }
    button = EzvizSnapshotButton(coordinator, "BK1")
    button.hass = hass

    with patch("custom_components.ezviz_rtsp.camera.async_dispatcher_send") as send:
        await button.async_press()

    coordinator.ezviz_client.capture_picture.assert_called_once_with("BK1", 1)
    assert coordinator.snapshot_captures["BK1"][1] == "https://ezviz/pic.jpg"
    send.assert_called_once_with(
        hass, SIGNAL_PICTURE_CAPTURED.format("BK1"), "https://ezviz/pic.jpg"
    )


async def test_snapshot_button_marks_the_throttle_for_automatic_requests() -> None:
    from custom_components.ezviz_rtsp.button import EzvizSnapshotButton

    hass = _hass()
    coordinator = _coordinator()
    coordinator.config_entry.options = {
        "auto_snapshot": True,
        "snapshot_interval": 300,
    }
    coordinator.ezviz_client.capture_picture.return_value = {
        "captureInfo": {"picUrl": "https://ezviz/pic.jpg"}
    }
    button = EzvizSnapshotButton(coordinator, "BK1")
    button.hass = hass
    await button.async_press()

    # A dashboard opening right after the button must not wake the camera again.
    camera = _cloud_camera(coordinator, hass)
    result = await camera.async_capture_picture(automatic=True)

    assert result == {"picture_url": "https://ezviz/pic.jpg", "skipped": True}
    coordinator.ezviz_client.capture_picture.assert_called_once_with("BK1", 1)


def test_snapshot_button_is_present_for_every_camera() -> None:
    from custom_components.ezviz_rtsp.button import EzvizSnapshotButton

    coordinator = _coordinator()
    button = EzvizSnapshotButton(coordinator, "BK1")
    assert button.unique_id == "BK1_request_snapshot"
    assert button.translation_key == "request_snapshot"


def test_first_image_url_accepts_the_known_keys() -> None:
    from custom_components.ezviz_rtsp.camera import _first_image_url

    assert (
        _first_image_url({"captureInfo": {"picUrl": "https://e/a.jpg"}})
        == "https://e/a.jpg"
    )
    assert (
        _first_image_url({"captureInfo": {"imageUrl": "https://e/b.jpg"}})
        == "https://e/b.jpg"
    )
    assert _first_image_url({"captureInfo": {}}) is None
    assert _first_image_url(None) is None


def test_is_wake_timeout_only_matches_the_2009_code() -> None:
    from custom_components.ezviz_rtsp.camera import _is_wake_timeout

    assert _is_wake_timeout(PyEzvizError("Got {'meta': {'code': 2009}}")) is True
    assert _is_wake_timeout(PyEzvizError("Got {'meta': {'code': 4001}}")) is False
    assert _is_wake_timeout(ValueError("'code': 2009")) is False


def _snapshot(hass, coordinator):
    from custom_components.ezviz_rtsp.image import EzvizSnapshot

    entity = EzvizSnapshot(hass, coordinator, "BK1")
    entity.entity_id = "image.door_snapshot"
    entity.async_write_ha_state = MagicMock()
    return entity


def test_snapshot_image_updates_when_a_picture_is_captured() -> None:
    hass = MagicMock()
    coordinator = _coordinator()
    coordinator.data["BK1"]["last_alarm_pic"] = "https://ezviz/alarm.jpg"
    entity = _snapshot(hass, coordinator)
    # Starts empty: the capture service fills it, not the coordinator.
    assert entity._attr_image_url is None
    assert entity._attr_image_last_updated is None
    entity._cached_image = object()

    entity._handle_picture_captured("https://ezviz/pic.jpg")

    assert entity._attr_image_url == "https://ezviz/pic.jpg"
    assert entity._cached_image is None
    assert entity._attr_image_last_updated is not None
    entity.async_write_ha_state.assert_called_once()


def test_snapshot_image_ignores_the_last_alarm_picture() -> None:
    hass = MagicMock()
    coordinator = _coordinator()
    entity = _snapshot(hass, coordinator)
    entity._attr_image_url = "https://ezviz/mine.jpg"
    coordinator.data["BK1"]["last_alarm_pic"] = "https://ezviz/alarm.jpg"

    entity._handle_coordinator_update()

    assert entity._attr_image_url == "https://ezviz/mine.jpg"
    entity.async_write_ha_state.assert_called_once()


async def test_options_snapshots_step_saves_the_options() -> None:
    flow, entry = _options_flow({})
    entry.options = {"transcode": True}
    result = await flow.async_step_snapshots(
        {"auto_snapshot": False, "snapshot_interval": 120}
    )
    assert result["data"]["auto_snapshot"] is False
    assert result["data"]["snapshot_interval"] == 120
    assert result["data"]["transcode"] is True


async def test_options_snapshots_form_shows_the_current_options() -> None:
    flow, entry = _options_flow({})
    entry.options = {"auto_snapshot": False, "snapshot_interval": 60}
    result = await flow.async_step_snapshots()
    assert result["type"] == "form"
    assert result["step_id"] == "snapshots"
