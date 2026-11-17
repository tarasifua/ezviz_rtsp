"""Tests for the SD-card recordings: decoding the index, paging a day, clip helpers."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
import time
import zlib
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.ezviz_rtsp import recordings as rec_module
from custom_components.ezviz_rtsp.const import DOMAIN, SIGNAL_RECORDING_DOWNLOADED
from custom_components.ezviz_rtsp.pyezvizapi.exceptions import PyEzvizError
from custom_components.ezviz_rtsp.recordings import (
    MAX_PAGES,
    PAGE_SIZE,
    RecordingError,
    decode_records,
    ffmpeg_args,
    parse_stamp,
    search_day,
    utc_stamp,
)

TZ = ZoneInfo("Africa/Johannesburg")


def _packed(records: list[dict], pad: int = 0) -> str:
    return base64.b64encode(zlib.compress(json.dumps(records).encode()) + b"\0" * pad).decode()


def _mp4_bytes(seconds: float, timescale: int = 1000) -> bytes:
    """A minimal MP4 with just the boxes needed to read its duration."""
    body = (
        b"\x00\x00\x00\x00"  # version 0, flags
        + b"\x00" * 8  # creation and modification
        + timescale.to_bytes(4, "big")
        + int(seconds * timescale).to_bytes(4, "big")
        + b"\x00" * 8
    )
    mvhd = (8 + len(body)).to_bytes(4, "big") + b"mvhd" + body
    moov = (8 + len(mvhd)).to_bytes(4, "big") + b"moov" + mvhd
    ftyp = (16).to_bytes(4, "big") + b"ftyp" + b"isom" + b"\x00" * 4
    return ftyp + moov


def _rec(begin: datetime, seconds: int = 8) -> dict:
    return {
        "B": begin.strftime("%Y-%m-%dT%H:%M:%S"),
        "E": (begin + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S"),
        "Type": 0,
    }


def _ps_video_pes(pts_seconds: float, payload: bytes = b"\x00" * 8) -> bytes:
    """One MPEG-PS video PES packet carrying a clear PTS."""
    pts = int(pts_seconds * 90_000)
    b0 = 0x20 | (((pts >> 30) & 0x07) << 1) | 1
    b1 = (pts >> 22) & 0xFF
    b2 = (((pts >> 15) & 0x7F) << 1) | 1
    b3 = (pts >> 7) & 0xFF
    b4 = ((pts & 0x7F) << 1) | 1
    length = 3 + 5 + len(payload)
    return (
        b"\x00\x00\x01\xe0"
        + length.to_bytes(2, "big")
        + b"\x80\x80\x05"
        + bytes((b0, b1, b2, b3, b4))
        + payload
    )


def test_decode_records_plain_compressed_and_padded() -> None:
    records = [{"B": "2026-11-10T10:00:00", "E": "2026-11-10T10:00:08"}]
    assert decode_records({"records": records, "isFinished": 1}) == (records, False)
    assert decode_records({"records": _packed(records), "isFinished": 0}) == (records, True)
    # The app's payloads can carry zero padding after the compressed stream.
    assert decode_records({"records": _packed(records, pad=31), "isFinished": 1}) == (records, False)
    assert decode_records({"records": None, "isFinished": None}) == ([], False)
    assert decode_records({"records": ""}) == ([], False)


def test_decode_records_rejects_garbage() -> None:
    with pytest.raises(RecordingError):
        decode_records({"records": "not base64!"})


class FakeIndex:
    """Answers like /v3/streaming/v2/records: 50 records from the window start, oldest first."""

    def __init__(self, starts: list[datetime], fail: Exception | None = None) -> None:
        self.records = [_rec(start) for start in sorted(starts)]
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    def search_records_v2(self, serial, channel, start, stop, *, size):
        assert channel == 1
        self.calls.append((start, stop))
        if self.fail:
            raise self.fail
        lo = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
        hi = datetime.strptime(stop, "%Y-%m-%d %H:%M:%S")
        inside = [r for r in self.records if lo <= datetime.fromisoformat(r["B"]) < hi]
        page = inside[: min(size, PAGE_SIZE)]
        return {"records": _packed(page), "isFinished": 0 if len(inside) > len(page) else 1}


def test_search_day_pages_through_a_busy_day() -> None:
    day = date(2026, 11, 9)
    base = datetime(2026, 11, 9, 0, 5)
    starts = [base + timedelta(minutes=5 * i) for i in range(260)]  # ~21 h of clips
    index = FakeIndex(starts)
    now = datetime(2026, 11, 10, 12, 0, tzinfo=TZ)
    found, complete = search_day(index, "BB1", day, TZ, now)
    assert complete
    assert [b.replace(tzinfo=None) for b, _ in found] == starts
    assert all(b.tzinfo == TZ for b, _ in found)
    # 260 clips at 50 per answer: six searches, each starting after the last clip seen.
    assert len(index.calls) == 6
    assert index.calls[0][0] == "2026-11-09 00:00:00"
    assert index.calls[1][0] == (starts[49] + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")


def test_search_day_today_stops_at_now_and_dedupes() -> None:
    now = datetime(2026, 11, 10, 12, 0, 30, tzinfo=TZ)
    starts = [datetime(2026, 11, 10, 11, 0) + timedelta(minutes=i) for i in range(55)]
    index = FakeIndex(starts + starts[:3])  # duplicates in the index are dropped
    found, complete = search_day(index, "BB1", now.date(), TZ, now)
    assert complete
    assert len(found) == 55
    assert index.calls[0][1] == "2026-11-10 12:00:30"


def test_search_day_reports_a_cut_short_list() -> None:
    starts = [datetime(2026, 11, 9, 0, 0) + timedelta(seconds=20 * i) for i in range(4000)]
    found, complete = search_day(
        FakeIndex(starts), "BB1", date(2026, 11, 9), TZ, datetime(2026, 11, 10, tzinfo=TZ)
    )
    assert not complete
    assert len(found) == MAX_PAGES * PAGE_SIZE


@pytest.mark.parametrize(
    ("code", "text"),
    [("2009", "did not answer in time"), ("9999", "Could not read")],
)
def test_search_day_explains_camera_errors(code: str, text: str, monkeypatch) -> None:
    monkeypatch.setattr(rec_module, "WAKE_RETRY_SECONDS", 0)
    index = FakeIndex([], fail=PyEzvizError(f"Could not search v2 records: response code={code}"))
    with pytest.raises(RecordingError, match=text):
        search_day(index, "BB1", date(2026, 11, 9), TZ, datetime(2026, 11, 10, tzinfo=TZ))
    # Only the "camera asleep" answer is retried, and only once.
    assert len(index.calls) == (2 if code == "2009" else 1)


def test_search_day_reads_an_empty_day(monkeypatch) -> None:
    """A new day with no recordings yet answers 2004; that is an empty day."""
    monkeypatch.setattr(rec_module, "WAKE_RETRY_SECONDS", 0)
    index = FakeIndex([], fail=PyEzvizError("Could not search v2 records: response code=2004"))
    found, complete = search_day(
        index, "BB1", date(2026, 11, 9), TZ, datetime(2026, 11, 10, tzinfo=TZ)
    )
    assert found == [] and complete
    assert len(index.calls) == 1, "an empty day is not retried or reported as an error"


def test_search_day_stops_at_a_quiet_stretch() -> None:
    """2004 after the last page means the rest of the day has no clips."""

    class LastPage:
        def __init__(self) -> None:
            self.calls = 0

        def search_records_v2(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    "records": _packed([_rec(datetime(2026, 11, 9, 8, 0))]),
                    "isFinished": 0,
                }
            raise PyEzvizError("Could not search v2 records: response code=2004")

    index = LastPage()
    found, complete = search_day(
        index, "BB1", date(2026, 11, 9), TZ, datetime(2026, 11, 10, tzinfo=TZ)
    )
    assert complete
    assert len(found) == 1
    assert index.calls == 2


def test_day_has_records_reads_an_empty_day(monkeypatch) -> None:
    monkeypatch.setattr(rec_module, "WAKE_RETRY_SECONDS", 0)
    index = FakeIndex([], fail=PyEzvizError("Could not search v2 records: response code=2004"))
    now = datetime(2026, 11, 17, 12, 0, tzinfo=TZ)
    assert rec_module.day_has_records(index, "BB1", date(2026, 11, 16), TZ, now) is False


def test_search_day_retries_once_while_the_camera_wakes(monkeypatch) -> None:
    monkeypatch.setattr(rec_module, "WAKE_RETRY_SECONDS", 0)
    index = FakeIndex([datetime(2026, 11, 9, 8, 0)])
    real = index.search_records_v2

    def waking(*args, **kwargs):
        if not index.calls:
            index.calls.append(("asleep", ""))
            raise PyEzvizError("Could not search v2 records: response code=2009, fields=4")
        return real(*args, **kwargs)

    index.search_records_v2 = waking
    found, complete = search_day(
        index, "BB1", date(2026, 11, 9), TZ, datetime(2026, 11, 10, tzinfo=TZ)
    )
    assert complete
    assert len(found) == 1


def test_utc_stamps_round_trip() -> None:
    local = datetime(2026, 11, 10, 10, 37, 2, tzinfo=TZ)
    assert utc_stamp(local) == "20261110T083702Z"
    assert parse_stamp("20261110T083702Z") == datetime(2026, 11, 10, 8, 37, 2, tzinfo=UTC)
    with pytest.raises(RecordingError):
        parse_stamp("2026-11-10 08:37:02")


def test_ffmpeg_args_copy_hevc_or_encode_h264() -> None:
    hevc = ffmpeg_args("hevc")
    assert hevc[hevc.index("-c:v") + 1] == "copy"
    assert "hvc1" in hevc
    h264 = ffmpeg_args("h264")
    assert h264[h264.index("-c:v") + 1] == "libx264"
    for args in (hevc, h264):
        assert "+faststart" in args
        assert args[-2:] == ("-f", "mp4")


def test_media_root_uses_the_media_dirs_setting() -> None:
    config = SimpleNamespace(
        media_dirs={"local": "/media"}, path=lambda *parts: "/config/" + "/".join(parts)
    )
    hass = SimpleNamespace(config=config)
    assert rec_module.media_root(hass) == Path("/media") / DOMAIN
    # With no media dir configured it falls back to <config>/media.
    config.media_dirs = {}
    assert rec_module.media_root(hass) == Path("/config/media") / DOMAIN


# -- on a real hass (needs the HA test harness, so Linux) -------------------------



@pytest.fixture
def _cloud(enable_custom_integrations, hass, tmp_path):
    # Downloaded clips live under the media folder; point it at a per-test
    # directory so runs don't see each other's files (the HA test config dir is
    # shared).
    hass.config.media_dirs = {"local": str(tmp_path)}
    yield


async def _setup_with_index(hass, starts: list[datetime]):
    from tests.test_integration import _FakeClient, _setup

    index = FakeIndex(starts)
    _FakeClient.search_records_v2 = lambda self, *a, **kw: index.search_records_v2(*a, **kw)
    try:
        entry = await _setup(hass)
    finally:
        del _FakeClient.search_records_v2
    entry.runtime_data.ezviz_client.search_records_v2 = index.search_records_v2
    return entry, index


async def test_websocket_lists_a_day_and_hands_out_a_clip(
    hass, hass_ws_client, hass_client, _cloud, tmp_path
) -> None:
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    tz = ZoneInfo("Africa/Johannesburg")
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    starts = [datetime.combine(yesterday, datetime.min.time()) + timedelta(hours=h) for h in (8, 9, 10)]
    entry, index = await _setup_with_index(hass, starts)
    ws = await hass_ws_client(hass)

    await ws.send_json(
        {"id": 1, "type": "ezviz_rtsp/recordings", "serial": "BK1", "date": yesterday.isoformat()}
    )
    msg = await ws.receive_json()
    assert msg["success"], msg
    result = msg["result"]
    assert result["complete"] is True
    assert [r["start"][11:19] for r in result["recordings"]] == ["10:00:00", "09:00:00", "08:00:00"]
    assert result["recordings"][0]["seconds"] == 8
    # Nothing has been saved to the media folder yet.
    assert [r["local"] for r in result["recordings"]] == [False, False, False]
    calls = len(index.calls)

    # A past day is answered from the cache until a refresh is asked for.
    await ws.send_json(
        {"id": 2, "type": "ezviz_rtsp/recordings", "serial": "BK1", "date": yesterday.isoformat()}
    )
    assert (await ws.receive_json())["success"]
    assert len(index.calls) == calls

    # Fetching a clip: the camera is read once, converted, cached and served with ranges.
    newest = result["recordings"][0]

    async def fake_mp4(_bin, ps, fmt, target):
        target.write_bytes(b"\0\0\0\x18ftypmp42" + ps + fmt.encode())

    with (
        patch.object(rec_module, "_download_clip", return_value=b"PSDATA") as download,
        patch.object(rec_module, "_async_to_mp4", side_effect=fake_mp4),
        patch("custom_components.ezviz_rtsp.live.ffmpeg_binary", return_value="ffmpeg"),
    ):
        for msg_id in (3, 4):
            await ws.send_json(
                {
                    "id": msg_id,
                    "type": "ezviz_rtsp/recording/clip",
                    "serial": "BK1",
                    "begin": newest["begin"],
                    "end": newest["end"],
                    "format": "hevc",
                }
            )
            clip = await ws.receive_json()
            assert clip["success"], clip
            assert clip["result"]["saved"] is True
        assert download.call_count == 1
        args = download.call_args.args
        assert args[1:5] == ("BK1", newest["begin"], newest["end"], "Africa/Johannesburg")

    url = clip["result"]["url"]
    assert url.startswith(f"/api/{DOMAIN}/recording/BK1/{newest['begin']}/{newest['end']}/hevc.mp4?authSig=")
    client = await hass_client()
    response = await client.get(url, headers={"Range": "bytes=0-3"})
    assert response.status == 206
    assert await response.read() == b"\0\0\0\x18"

    # The downloaded clip is now marked local; the others still are not.
    await ws.send_json(
        {"id": 7, "type": "ezviz_rtsp/recordings", "serial": "BK1", "date": yesterday.isoformat()}
    )
    msg = await ws.receive_json()
    assert msg["success"], msg
    assert [r["local"] for r in msg["result"]["recordings"]] == [True, False, False]

    # Unknown cameras and bad input are refused with errors, not exceptions.
    await ws.send_json({"id": 8, "type": "ezviz_rtsp/recordings", "serial": "NOPE"})
    assert (await ws.receive_json())["error"]["code"] == "not_found"
    await ws.send_json(
        {"id": 9, "type": "ezviz_rtsp/recording/clip", "serial": "BK1", "begin": "x", "end": "y"}
    )
    assert (await ws.receive_json())["error"]["code"] == "recording_failed"

    # The clip lives under the media folder, in the folder of its local day, and
    # survives an unload.
    root = (await rec_module.async_get_store(hass)).root
    clip_file = (
        root
        / yesterday.strftime("%Y/%m/%d")
        / f"BK1_{newest['begin']}_{newest['end']}_hevc.mp4"
    )
    assert root == rec_module.media_root(hass)
    assert clip_file.exists()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert clip_file.exists()
    assert rec_module.DATA_RECORDINGS not in hass.data


async def test_list_marks_a_clip_saved_in_either_format_as_local(
    hass, hass_ws_client, _cloud
) -> None:
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    tz = ZoneInfo("Africa/Johannesburg")
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    starts = [
        datetime.combine(yesterday, datetime.min.time()) + timedelta(hours=h)
        for h in (8, 9)
    ]
    await _setup_with_index(hass, starts)
    ws = await hass_ws_client(hass)
    listing = {"id": 1, "type": "ezviz_rtsp/recordings", "serial": "BK1", "date": yesterday.isoformat()}
    await ws.send_json(listing)
    msg = await ws.receive_json()
    assert msg["success"], msg
    newer, older = msg["result"]["recordings"]
    assert [newer["local"], older["local"]] == [False, False]

    # Save only an H.264 copy of the older recording (as the download service
    # does), then let the store index the folder again, as a restart would.
    store = await rec_module.async_get_store(hass)
    saved = rec_module._clip_path(store, ("BK1", older["begin"], older["end"], "h264"))
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"mp4")
    await rec_module.async_close_store(hass)
    await rec_module.async_get_store(hass)

    listing["id"] = 2
    await ws.send_json(listing)
    msg = await ws.receive_json()
    assert msg["success"], msg
    flags = {r["begin"]: r["local"] for r in msg["result"]["recordings"]}
    assert flags[older["begin"]] is True
    assert flags[newer["begin"]] is False


async def test_list_marks_a_short_saved_copy_as_incomplete(
    hass, hass_ws_client, _cloud
) -> None:
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    tz = ZoneInfo("Africa/Johannesburg")
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    start = datetime.combine(yesterday, datetime.min.time()) + timedelta(hours=8)
    await _setup_with_index(hass, [start])
    ws = await hass_ws_client(hass)
    listing = {
        "id": 1,
        "type": "ezviz_rtsp/recordings",
        "serial": "BK1",
        "date": yesterday.isoformat(),
    }
    await ws.send_json(listing)
    saved = (await ws.receive_json())["result"]["recordings"][0]

    # The 8 s recording was left cut off by an old download: 2 s of MP4.
    store = await rec_module.async_get_store(hass)
    key = ("BK1", saved["begin"], saved["end"], "h264")
    path = rec_module._clip_path(store, key)
    path.parent.mkdir(parents=True)
    path.write_bytes(_mp4_bytes(2))
    store.clips[key] = path

    listing["id"] = 2
    await ws.send_json(listing)
    updated = (await ws.receive_json())["result"]["recordings"][0]
    assert updated["local"] is True
    assert updated["incomplete"] is True


async def test_two_reads_of_one_day_share_one_sd_session(hass, _cloud) -> None:
    """Switching days quickly must not queue a camera session per tap."""
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    tz = ZoneInfo("Africa/Johannesburg")
    day = datetime.now(tz).date() - timedelta(days=1)
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=8)
    entry, index = await _setup_with_index(hass, [start])
    camera = rec_module.find_camera(hass, "BK1")

    entered = threading.Event()
    release = threading.Event()

    def gated(serial, channel, begin, end, *, size):
        entered.set()
        assert release.wait(5)
        return index.search_records_v2(serial, channel, begin, end, size=size)

    entry.runtime_data.ezviz_client.search_records_v2 = gated
    first = asyncio.create_task(rec_module.async_list_day(hass, camera, day))
    assert await hass.async_add_executor_job(entered.wait, 5)
    second = asyncio.create_task(rec_module.async_list_day(hass, camera, day))
    await asyncio.sleep(0)
    assert not second.done(), "the second read waits on the one already in flight"
    await hass.async_add_executor_job(release.set)
    one, two = await first, await second

    assert one == two
    assert len(index.calls) == 1, "the camera was asked once, not once per tap"
    assert not (await rec_module.async_get_store(hass)).day_tasks


async def test_a_failed_shared_read_can_be_tried_again(hass, _cloud) -> None:
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    tz = ZoneInfo("Africa/Johannesburg")
    day = datetime.now(tz).date() - timedelta(days=1)
    entry, index = await _setup_with_index(hass, [])
    camera = rec_module.find_camera(hass, "BK1")
    def fail(*args, **kwargs):
        raise PyEzvizError("Could not search v2 records: response code=50000")

    entry.runtime_data.ezviz_client.search_records_v2 = fail
    with pytest.raises(rec_module.RecordingError, match="Could not read"):
        await rec_module.async_list_day(hass, camera, day)
    # The failed read is forgotten, so the next attempt reaches the camera.
    entry.runtime_data.ezviz_client.search_records_v2 = index.search_records_v2
    recordings, complete = await rec_module.async_list_day(hass, camera, day)
    assert recordings == [] and complete


async def test_websocket_keeps_a_watched_clip_out_of_media_when_asked(
    hass, hass_ws_client, hass_client, _cloud, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(rec_module, "temp_root", lambda _hass: tmp_path / "temp")
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    tz = ZoneInfo("Africa/Johannesburg")
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    starts = [
        datetime.combine(yesterday, datetime.min.time()) + timedelta(hours=h)
        for h in (8, 9)
    ]
    await _setup_with_index(hass, starts)
    ws = await hass_ws_client(hass)
    await ws.send_json(
        {"id": 1, "type": "ezviz_rtsp/recordings", "serial": "BK1", "date": yesterday.isoformat()}
    )
    newest = (await ws.receive_json())["result"]["recordings"][0]

    async def fake_mp4(_bin, ps, fmt, target):
        target.write_bytes(b"\0\0\0\x18ftypmp42" + ps + fmt.encode())

    message = {
        "type": "ezviz_rtsp/recording/clip",
        "serial": "BK1",
        "begin": newest["begin"],
        "end": newest["end"],
        "format": "hevc",
        "keep": False,
    }
    with (
        patch.object(rec_module, "_download_clip", return_value=b"PSDATA") as download,
        patch.object(rec_module, "_async_to_mp4", side_effect=fake_mp4),
        patch("custom_components.ezviz_rtsp.live.ffmpeg_binary", return_value="ffmpeg"),
    ):
        await ws.send_json({"id": 2, **message})
        clip = await ws.receive_json()
        assert clip["success"], clip
        assert clip["result"]["saved"] is False

        # Nothing was stored under Media; the temporary copy is what plays.
        store = await rec_module.async_get_store(hass)
        assert not list(store.root.glob("*.mp4"))
        temp_file = tmp_path / "temp" / f"BK1_{newest['begin']}_{newest['end']}_hevc.mp4"
        assert temp_file.exists()
        client = await hass_client()
        response = await client.get(clip["result"]["url"])
        assert response.status == 200
        assert (await response.read()).startswith(b"\0\0\0\x18ftypmp42")

        # Playing it again reuses the temporary copy instead of waking the camera.
        await ws.send_json({"id": 3, **message})
        again = await ws.receive_json()
        assert again["success"], again
        assert again["result"]["saved"] is False
        assert download.call_count == 1


async def test_a_clip_already_saved_is_kept_with_saving_off(
    hass, hass_ws_client, _cloud, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(rec_module, "temp_root", lambda _hass: tmp_path / "temp")
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    tz = ZoneInfo("Africa/Johannesburg")
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    starts = [
        datetime.combine(yesterday, datetime.min.time()) + timedelta(hours=h)
        for h in (8, 9)
    ]
    await _setup_with_index(hass, starts)
    ws = await hass_ws_client(hass)
    await ws.send_json(
        {"id": 1, "type": "ezviz_rtsp/recordings", "serial": "BK1", "date": yesterday.isoformat()}
    )
    newest = (await ws.receive_json())["result"]["recordings"][0]

    async def fake_mp4(_bin, ps, fmt, target):
        target.write_bytes(b"\0\0\0\x18ftypmp42" + ps + fmt.encode())

    message = {
        "type": "ezviz_rtsp/recording/clip",
        "serial": "BK1",
        "begin": newest["begin"],
        "end": newest["end"],
        "format": "hevc",
    }
    with (
        patch.object(rec_module, "_download_clip", return_value=b"PSDATA") as download,
        patch.object(rec_module, "_async_to_mp4", side_effect=fake_mp4),
        patch("custom_components.ezviz_rtsp.live.ffmpeg_binary", return_value="ffmpeg"),
    ):
        # Saved the normal way first...
        await ws.send_json({"id": 2, "keep": True, **message})
        first = await ws.receive_json()
        assert first["success"], first
        assert first["result"]["saved"] is True

        # ...then watched with saving off: the media copy answers, nothing new.
        await ws.send_json({"id": 3, "keep": False, **message})
        second = await ws.receive_json()
        assert second["success"], second
        assert second["result"]["saved"] is True
        assert download.call_count == 1

    temp = tmp_path / "temp"
    assert not temp.exists() or not list(temp.glob("*.mp4"))


def test_temp_clips_are_swept_after_their_short_life(tmp_path) -> None:
    fresh = tmp_path / "BK1_20261110T080000Z_20261110T080008Z_h264.mp4"
    stale = tmp_path / "BK1_20261110T090000Z_20261110T090008Z_h264.mp4"
    fresh.write_bytes(b"mp4")
    stale.write_bytes(b"mp4")
    old = time.time() - rec_module.TEMP_CLIP_SECONDS - 60
    os.utime(stale, (old, old))

    rec_module._sweep_temp(tmp_path)

    assert fresh.exists()
    assert not stale.exists()


def test_an_unreadable_folder_keeps_the_rest_of_the_index(
    tmp_path, monkeypatch
) -> None:
    """One folder that cannot be listed must not leave the whole index empty.

    An empty index makes every saved clip look absent, so each one is fetched
    from the camera again - waking it and reading its SD card for nothing.
    """
    root = tmp_path / "media"
    folder = root / "2026" / "11" / "16"
    folder.mkdir(parents=True)
    good = folder / "BK1_20261116T080000Z_20261116T080008Z_h264.mp4"
    good.write_bytes(b"mp4")

    def walk(_self, _pattern):
        yield good
        raise OSError("a folder that cannot be listed")

    monkeypatch.setattr(Path, "rglob", walk)

    store = rec_module._prepare_store(root, TZ)

    assert ("BK1", "20261116T080000Z", "20261116T080008Z", "h264") in store.clips


async def test_retention_forgets_temp_clips_whose_file_is_gone(
    hass, _cloud, tmp_path, monkeypatch
) -> None:
    """The temp index must not keep an entry for every clip ever watched."""
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    monkeypatch.setattr(rec_module, "temp_root", lambda _hass: tmp_path)
    kept = tmp_path / "kept.mp4"
    kept.write_bytes(b"mp4")
    store.temp[("BK1", "b1", "e1", "h264")] = kept
    store.temp[("BK1", "b2", "e2", "h264")] = tmp_path / "gone.mp4"

    await rec_module.async_prune_recordings(hass)

    assert list(store.temp) == [("BK1", "b1", "e1", "h264")]


async def test_clip_refused_while_the_camera_streams_live(hass, _cloud) -> None:
    entry, _ = await _setup_with_index(hass, [])
    camera = rec_module.find_camera(hass, "BK1")
    assert camera is not None
    stream = entry.runtime_data.live_streams["BK1"]
    with patch.object(type(stream), "active", new=True), patch.object(
        rec_module, "_download_clip", new=AsyncMock()
    ) as download:
        begin = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
        with pytest.raises(rec_module.RecordingError, match="streaming live"):
            await rec_module.async_get_clip(hass, camera, begin, begin + timedelta(seconds=8), "h264")
        download.assert_not_called()


async def test_a_queued_clip_stops_when_live_starts_while_it_waits(
    hass, _cloud
) -> None:
    await _setup_with_index(hass, [])
    camera = rec_module.find_camera(hass, "BK1")
    store = await rec_module.async_get_store(hass)
    begin = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)

    class Gate:
        """A lock that reports when a request has reached it."""

        def __init__(self) -> None:
            self.lock = asyncio.Lock()
            self.waiting = asyncio.Event()

        async def __aenter__(self):
            self.waiting.set()
            await self.lock.acquire()
            return self

        async def __aexit__(self, *exc):
            self.lock.release()

    gate = Gate()
    store.locks["BK1"] = gate
    await gate.lock.acquire()
    live = SimpleNamespace(active=False)
    try:
        with (
            patch("custom_components.ezviz_rtsp.live.find_stream", return_value=live),
            patch.object(rec_module, "_download_clip", new=AsyncMock()) as download,
        ):
            task = asyncio.create_task(
                rec_module.async_get_clip(
                    hass, camera, begin, begin + timedelta(seconds=8), "h264"
                )
            )
            await asyncio.wait_for(gate.waiting.wait(), 2)
            # The live view starts while the request waits behind the lock.
            live.active = True
            gate.lock.release()
            with pytest.raises(rec_module.RecordingError, match="streaming live"):
                await task
            download.assert_not_called()
    finally:
        if gate.lock.locked():
            gate.lock.release()


async def test_websocket_releases_the_live_stream_at_once(
    hass, hass_ws_client, _cloud
) -> None:
    entry, _ = await _setup_with_index(hass, [])
    stream = entry.runtime_data.live_streams["BK1"]
    ws = await hass_ws_client(hass)

    # Nothing is open: the answer says so, and nothing breaks.
    await ws.send_json({"id": 1, "type": "ezviz_rtsp/live/stop", "serial": "BK1"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    assert msg["result"] == {"stopped": False}

    # With a live task open, the card's request releases it now, not after the
    # release delay; otherwise the first SD playback would find the camera busy.
    async def forever() -> None:
        await asyncio.sleep(3600)

    stream._task = asyncio.create_task(forever())
    assert stream.active
    await ws.send_json({"id": 2, "type": "ezviz_rtsp/live/stop", "serial": "BK1"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    assert msg["result"] == {"stopped": True}
    assert not stream.active


async def test_a_clip_saved_in_media_is_served_without_the_camera(hass, _cloud) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    camera = rec_module.find_camera(hass, "BK1")
    begin = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    end = begin + timedelta(seconds=8)
    saved = rec_module._clip_path(
        store, ("BK1", "20261110T080000Z", "20261110T080008Z", "h264")
    )
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"mp4")
    # The index can miss a file that is on disk: a restored backup, a copied
    # clip, or a store built before the file was written.
    store.clips.clear()

    with patch.object(rec_module, "_download_clip", new=AsyncMock()) as download:
        path = await rec_module.async_get_clip(hass, camera, begin, end, "h264")

    assert path == saved
    download.assert_not_called()
    assert store.clips[("BK1", "20261110T080000Z", "20261110T080008Z", "h264")] == saved


async def test_an_h264_copy_answers_an_hevc_request(hass, _cloud) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    camera = rec_module.find_camera(hass, "BK1")
    begin = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    end = begin + timedelta(seconds=8)
    # "Download latest recording" and the browser asking for HEVC must not store
    # the same recording twice: H.264 plays everywhere.
    saved = rec_module._clip_path(
        store, ("BK1", "20261110T080000Z", "20261110T080008Z", "h264")
    )
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"mp4")
    store.clips.clear()

    with patch.object(rec_module, "_download_clip", new=AsyncMock()) as download:
        path = await rec_module.async_get_clip(hass, camera, begin, end, "hevc")

    assert path == saved
    download.assert_not_called()


async def test_an_hevc_only_copy_is_not_used_for_h264(hass, _cloud) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    camera = rec_module.find_camera(hass, "BK1")
    begin = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    end = begin + timedelta(seconds=8)
    hevc = rec_module._clip_path(
        store, ("BK1", "20261110T080000Z", "20261110T080008Z", "hevc")
    )
    hevc.parent.mkdir(parents=True)
    hevc.write_bytes(b"mp4")
    store.clips.clear()

    with (
        patch.object(rec_module, "_download_clip", return_value=b"PSDATA") as download,
        patch.object(
            rec_module,
            "_async_to_mp4",
            side_effect=lambda _bin, _ps, _fmt, target: target.write_bytes(b"mp4"),
        ),
        patch("custom_components.ezviz_rtsp.live.ffmpeg_binary", return_value="ffmpeg"),
    ):
        path = await rec_module.async_get_clip(hass, camera, begin, end, "h264")

    # HEVC does not play everywhere, so an H.264 request still needs its copy.
    download.assert_called_once()
    assert path.name.endswith("_h264.mp4")
    assert path.exists() and path != hevc


async def test_a_clip_removed_from_media_is_fetched_again(hass, _cloud) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    camera = rec_module.find_camera(hass, "BK1")
    begin = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    end = begin + timedelta(seconds=8)
    key = ("BK1", "20261110T080000Z", "20261110T080008Z", "h264")
    gone = rec_module._clip_path(store, key)
    store.clips[key] = gone  # indexed, but the file was deleted by hand

    with (
        patch.object(rec_module, "_download_clip", return_value=b"PSDATA") as download,
        patch.object(
            rec_module,
            "_async_to_mp4",
            side_effect=lambda _bin, _ps, _fmt, target: target.write_bytes(b"mp4"),
        ),
        patch("custom_components.ezviz_rtsp.live.ffmpeg_binary", return_value="ffmpeg"),
    ):
        path = await rec_module.async_get_clip(hass, camera, begin, end, "h264")

    download.assert_called_once()
    assert path == gone and gone.exists()


def _playback_stream(*results) -> MagicMock:
    stream = MagicMock()
    stream.start.side_effect = [SimpleNamespace(result=result) for result in results]
    return stream


def _patch_playback(monkeypatch, stream: MagicMock) -> MagicMock:
    opener = MagicMock(return_value=stream)
    monkeypatch.setattr(
        "custom_components.ezviz_rtsp.pyezvizapi.streaming.cloud.playback.open_cloud_playback_stream", opener
    )
    return opener


def test_playback_negotiation_retries_while_the_camera_is_busy(monkeypatch) -> None:
    stream = _playback_stream(
        rec_module.BUSY_RESULT_CODE, rec_module.BUSY_RESULT_CODE, 0
    )
    opener = _patch_playback(monkeypatch, stream)
    sleeps: list[float] = []
    monkeypatch.setattr(rec_module.time, "sleep", sleeps.append)

    got = rec_module._open_playback(
        MagicMock(),
        "BK1",
        "20261110T080000Z",
        "20261110T080008Z",
        "Africa/Johannesburg",
        time.monotonic() + 60,
    )

    assert got is stream
    assert opener.call_count == 3
    assert sleeps == [rec_module.PLAYBACK_RETRY_SECONDS] * 2
    assert stream.close.call_count == 2


def test_playback_negotiation_does_not_retry_another_refusal(monkeypatch) -> None:
    from custom_components.ezviz_rtsp.pyezvizapi.exceptions import EzvizPlaybackNegotiationError

    stream = _playback_stream(4001)
    opener = _patch_playback(monkeypatch, stream)
    sleeps: list[float] = []
    monkeypatch.setattr(rec_module.time, "sleep", sleeps.append)

    with pytest.raises(EzvizPlaybackNegotiationError):
        rec_module._open_playback(
            MagicMock(),
            "BK1",
            "20261110T080000Z",
            "20261110T080008Z",
            "Africa/Johannesburg",
            time.monotonic() + 60,
        )

    assert opener.call_count == 1
    assert sleeps == []


def test_playback_negotiation_gives_up_when_the_camera_stays_busy(monkeypatch) -> None:
    from custom_components.ezviz_rtsp.pyezvizapi.exceptions import EzvizPlaybackNegotiationError

    stream = _playback_stream(*[rec_module.BUSY_RESULT_CODE] * rec_module.PLAYBACK_ATTEMPTS)
    opener = _patch_playback(monkeypatch, stream)
    sleeps: list[float] = []
    monkeypatch.setattr(rec_module.time, "sleep", sleeps.append)

    with pytest.raises(EzvizPlaybackNegotiationError) as raised:
        rec_module._open_playback(
            MagicMock(),
            "BK1",
            "20261110T080000Z",
            "20261110T080008Z",
            "Africa/Johannesburg",
            time.monotonic() + 60,
        )

    assert raised.value.result_code == rec_module.BUSY_RESULT_CODE
    assert opener.call_count == rec_module.PLAYBACK_ATTEMPTS
    assert len(sleeps) == rec_module.PLAYBACK_ATTEMPTS - 1


def test_transfer_window_grows_with_a_long_recording() -> None:
    # A short clip keeps the minimum, enough for the camera to wake up.
    assert rec_module._transfer_budget(10) == rec_module.CLIP_DEADLINE
    # A minute needs more than the old fixed 90 s window, which used to cut it.
    assert rec_module._transfer_budget(60) > rec_module.CLIP_DEADLINE
    # The longest allowed clip still gets a bounded window.
    assert (
        rec_module._transfer_budget(rec_module.MAX_CLIP_SECONDS)
        == rec_module.MAX_TRANSFER_SECONDS
    )


def test_a_fraction_short_is_not_a_shortfall() -> None:
    # The camera often closes the file a fraction early; that is not a retry.
    assert rec_module._short_by(11.4, 12) == 0
    assert rec_module._short_by(118, 120) == 0
    # A 12-second event often arrives as 11 s of file: still the whole recording.
    assert rec_module._short_by(10.6, 12.9) == 0
    # A real gap is.
    assert rec_module._short_by(9.0, 12) > 0
    assert rec_module._short_by(100, 120) > 0


def test_mp4_duration_is_read_from_the_movie_header(tmp_path) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(_mp4_bytes(12.5))
    assert rec_module._mp4_seconds(clip) == 12.5

    (tmp_path / "bad.mp4").write_bytes(b"not an mp4 at all")
    assert rec_module._mp4_seconds(tmp_path / "bad.mp4") is None


def test_the_mvhd_duration_is_read_once_per_file(monkeypatch, tmp_path) -> None:
    """A saved clip's duration must not be re-read on every open of a day."""
    store = rec_module.RecordingStore(tmp_path, TZ)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(_mp4_bytes(12))
    read = MagicMock(wraps=rec_module._mp4_seconds)
    monkeypatch.setattr(rec_module, "_mp4_seconds", read)

    assert rec_module._clip_seconds(store, clip) == 12.0
    assert rec_module._clip_seconds(store, clip) == 12.0
    assert read.call_count == 1, "the file is read once, then answered from the cache"

    # A re-downloaded file (a new mtime) is read again.
    clip.write_bytes(_mp4_bytes(8))
    stat = clip.stat()
    os.utime(clip, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert rec_module._clip_seconds(store, clip) == 8.0
    assert read.call_count == 2


async def test_a_short_clip_is_not_fetched_again_after_a_restart(
    hass, _cloud, hass_storage
) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    camera = rec_module.find_camera(hass, "BK1")
    begin = datetime(2026, 11, 16, 18, 49, 6, tzinfo=UTC)
    end = begin + timedelta(seconds=13)
    key = ("BK1", "20261116T184906Z", "20261116T184919Z", "h264")
    saved = rec_module._clip_path(store, key)
    saved.parent.mkdir(parents=True)
    # The camera sent 10.6 s of the 13 s interval: it is short, but fetching
    # it again proves the same thing, so the verdict has to survive a restart.
    saved.write_bytes(_mp4_bytes(10.6))
    store.clips[key] = saved
    store.short.add(key)
    await rec_module._save_short(hass, store)
    assert "ezviz_rtsp.short_clips" in hass_storage

    # A restart rebuilds the index from the media folder.
    hass.data.pop(rec_module.DATA_RECORDINGS)
    hass.data.pop(rec_module.DATA_SHORT)
    hass.data.pop(rec_module.DATA_SHORT_STORE)
    again = await rec_module.async_get_store(hass)
    assert key in again.short

    with patch.object(rec_module, "_download_clip", new=AsyncMock()) as download:
        path = await rec_module.async_get_clip(hass, camera, begin, end, "h264")

    download.assert_not_called()
    assert path == saved


async def test_a_short_marker_is_dropped_with_its_file(hass, _cloud, hass_storage) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    key = ("BK1", "20261116T184906Z", "20261116T184919Z", "h264")
    saved = rec_module._clip_path(store, key)
    saved.parent.mkdir(parents=True)
    saved.write_bytes(_mp4_bytes(10.6))
    store.clips[key] = saved
    store.short.add(key)
    await rec_module._save_short(hass, store)

    # Retention or a hand delete removes the clip: the marker goes with it.
    store.clips.pop(key)
    await rec_module._save_short(hass, store)
    assert hass_storage["ezviz_rtsp.short_clips"]["data"]["clips"] == []

    hass.data.pop(rec_module.DATA_RECORDINGS)
    hass.data.pop(rec_module.DATA_SHORT)
    hass.data.pop(rec_module.DATA_SHORT_STORE)
    again = await rec_module.async_get_store(hass)
    assert key not in again.short


async def test_a_cached_clip_shorter_than_its_interval_is_fetched_again(
    hass, _cloud
) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    camera = rec_module.find_camera(hass, "BK1")
    begin = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    end = begin + timedelta(seconds=8)
    key = ("BK1", "20261110T080000Z", "20261110T080008Z", "h264")
    saved = rec_module._clip_path(store, key)
    saved.parent.mkdir(parents=True)
    # What the fixed 90 s window used to leave behind: a file much shorter than
    # the interval in its name.
    saved.write_bytes(_mp4_bytes(2))
    store.clips.clear()

    async def full_mp4(_bin, _ps, _fmt, target):
        target.write_bytes(_mp4_bytes(8))

    with (
        patch.object(rec_module, "_download_clip", return_value=b"PSDATA") as download,
        patch.object(rec_module, "_async_to_mp4", side_effect=full_mp4),
        patch("custom_components.ezviz_rtsp.live.ffmpeg_binary", return_value="ffmpeg"),
    ):
        path = await rec_module.async_get_clip(hass, camera, begin, end, "h264")

    download.assert_called_once()
    assert path == saved
    assert rec_module._mp4_seconds(path) == 8.0
    assert key not in store.short


async def test_a_recording_the_camera_sends_short_is_kept_and_served(
    hass, _cloud
) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    camera = rec_module.find_camera(hass, "BK1")
    begin = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    end = begin + timedelta(seconds=8)
    key = ("BK1", "20261110T080000Z", "20261110T080008Z", "h264")
    saved = rec_module._clip_path(store, key)

    async def short_mp4(_bin, _ps, _fmt, target):
        target.write_bytes(_mp4_bytes(4))  # the camera itself sends 4 of 8 s

    with (
        patch.object(rec_module, "_download_clip", return_value=b"PSDATA"),
        patch.object(rec_module, "_async_to_mp4", side_effect=short_mp4),
        patch("custom_components.ezviz_rtsp.live.ffmpeg_binary", return_value="ffmpeg"),
    ):
        path = await rec_module.async_get_clip(hass, camera, begin, end, "h264")

    # Kept, and marked: a second play must not wake the camera again.
    assert path == saved and path.exists()
    assert key in store.short
    with patch.object(rec_module, "_download_clip", new=AsyncMock()) as download:
        again = await rec_module.async_get_clip(hass, camera, begin, end, "h264")
    download.assert_not_called()
    assert again == path


async def test_a_cached_clip_of_the_right_length_is_not_fetched_again(
    hass, _cloud
) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    camera = rec_module.find_camera(hass, "BK1")
    begin = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    end = begin + timedelta(seconds=8)
    key = ("BK1", "20261110T080000Z", "20261110T080008Z", "h264")
    saved = rec_module._clip_path(store, key)
    saved.parent.mkdir(parents=True)
    saved.write_bytes(_mp4_bytes(8))
    store.clips.clear()

    with patch.object(rec_module, "_download_clip", new=AsyncMock()) as download:
        path = await rec_module.async_get_clip(hass, camera, begin, end, "h264")

    assert path == saved
    download.assert_not_called()


def test_a_short_download_is_fetched_once_more(monkeypatch) -> None:
    opener = MagicMock(side_effect=[MagicMock(), MagicMock()])
    monkeypatch.setattr(rec_module, "_open_playback", opener)
    monkeypatch.setattr(
        rec_module,
        "_read_playback",
        MagicMock(side_effect=[bytearray(b"PS1"), bytearray(b"PS2")]),
    )
    spans = MagicMock(side_effect=[5.0, 12.0])
    monkeypatch.setattr(rec_module, "_delivered_seconds", spans)

    clip = rec_module._download_clip(
        MagicMock(),
        "BK1",
        "20261110T080000Z",
        "20261110T080012Z",
        "Africa/Johannesburg",
        None,
    )

    assert clip == b"PS2"
    assert opener.call_count == 2
    assert spans.call_count == 2
    first_deadline = opener.call_args_list[0].args[-1]
    second_deadline = opener.call_args_list[1].args[-1]
    assert second_deadline > first_deadline


def test_a_failed_retry_keeps_the_first_read(monkeypatch) -> None:
    """A short first read must survive a retry that then fails."""
    from custom_components.ezviz_rtsp.pyezvizapi.exceptions import PyEzvizError

    opener = MagicMock(side_effect=[MagicMock(), PyEzvizError("the relay dropped")])
    monkeypatch.setattr(rec_module, "_open_playback", opener)
    monkeypatch.setattr(
        rec_module, "_read_playback", MagicMock(return_value=bytearray(b"PS1"))
    )
    monkeypatch.setattr(rec_module, "_delivered_seconds", MagicMock(return_value=8.0))

    clip = rec_module._download_clip(
        MagicMock(),
        "BK1",
        "20261110T080000Z",
        "20261110T080012Z",
        "Africa/Johannesburg",
        None,
    )

    assert clip == b"PS1"
    assert opener.call_count == 2


def test_a_shorter_retry_does_not_replace_a_longer_read(monkeypatch) -> None:
    opener = MagicMock(side_effect=[MagicMock(), MagicMock()])
    monkeypatch.setattr(rec_module, "_open_playback", opener)
    monkeypatch.setattr(
        rec_module,
        "_read_playback",
        MagicMock(side_effect=[bytearray(b"PS1"), bytearray(b"PS2")]),
    )
    monkeypatch.setattr(
        rec_module, "_delivered_seconds", MagicMock(side_effect=[8.0, 6.0])
    )

    clip = rec_module._download_clip(
        MagicMock(),
        "BK1",
        "20261110T080000Z",
        "20261110T080012Z",
        "Africa/Johannesburg",
        None,
    )

    assert clip == b"PS1"
    assert opener.call_count == 2


def test_two_failed_reads_raise(monkeypatch) -> None:
    from custom_components.ezviz_rtsp.pyezvizapi.exceptions import PyEzvizError

    monkeypatch.setattr(rec_module, "_open_playback", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(
        rec_module, "_read_playback", MagicMock(side_effect=PyEzvizError("gone"))
    )

    with pytest.raises(rec_module.RecordingError):
        rec_module._download_clip(
            MagicMock(),
            "BK1",
            "20261110T080000Z",
            "20261110T080012Z",
            "Africa/Johannesburg",
            None,
        )


def test_a_whole_download_is_not_fetched_twice(monkeypatch) -> None:
    opener = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(rec_module, "_open_playback", opener)
    monkeypatch.setattr(
        rec_module, "_read_playback", MagicMock(return_value=bytearray(b"PS"))
    )
    monkeypatch.setattr(rec_module, "_delivered_seconds", MagicMock(return_value=12.0))

    clip = rec_module._download_clip(
        MagicMock(),
        "BK1",
        "20261110T080000Z",
        "20261110T080012Z",
        "Africa/Johannesburg",
        None,
    )

    assert clip == b"PS"
    assert opener.call_count == 1


class _PacketStream:
    """A relay stream that continues where the previous call stopped."""

    def __init__(self, bodies: list[bytes]) -> None:
        self._bodies = bodies
        self._next = 0

    def iter_packets(self, *, max_packets=None, **kwargs):
        taken = 0
        while self._next < len(self._bodies) and (
            max_packets is None or taken < max_packets
        ):
            body = self._bodies[self._next]
            self._next += 1
            taken += 1
            yield SimpleNamespace(body=body, encrypted=False)


def test_read_playback_reports_the_delivered_seconds() -> None:
    bodies = [_ps_video_pes(seconds) for seconds in (0, 4, 8)]
    seen: list[float | None] = []

    data = rec_module._read_playback(_PacketStream(bodies), time.monotonic() + 5, seen.append)

    assert len(data) == sum(len(body) for body in bodies)
    assert seen[0] == 0.0
    assert seen[-1] == 8.0


def test_video_pts_survives_a_header_split_across_packets() -> None:
    packet = _ps_video_pes(10.0)
    bodies = [packet[:11], packet[11:], _ps_video_pes(20.0)]
    seen: list[float | None] = []

    rec_module._read_playback(_PacketStream(bodies), time.monotonic() + 5, seen.append)

    assert seen[-1] == 10.0, "10 s and 20 s give a ten-second span"


async def test_a_fetch_publishes_progress_and_clears_it(hass, _cloud) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    camera = rec_module.find_camera(hass, "BK1")
    begin = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    end = begin + timedelta(seconds=8)
    key = ("BK1", "20261110T080000Z", "20261110T080008Z", "h264")
    seen: list[dict] = []
    converting: list[dict] = []

    def fake_download(client, serial, begin_stamp, end_stamp, timezone, code, report):
        seen.append(dict(store.progress[key]))
        report(4.0, 8.0, 1)
        seen.append(dict(store.progress[key]))
        return b"PSDATA"

    def fake_mp4(_bin, _ps, _fmt, target):
        converting.append(dict(store.progress[key]))
        target.write_bytes(b"mp4")

    with (
        patch.object(rec_module, "_download_clip", side_effect=fake_download),
        patch.object(rec_module, "_async_to_mp4", side_effect=fake_mp4),
        patch("custom_components.ezviz_rtsp.live.ffmpeg_binary", return_value="ffmpeg"),
    ):
        path = await rec_module.async_get_clip(hass, camera, begin, end, "h264")

    assert seen[0]["stage"] == "downloading"
    assert seen[0]["total"] == 8.0
    assert seen[1]["delivered"] == 4.0
    assert converting[0]["stage"] == "converting"
    assert converting[0]["delivered"] == 8.0
    assert key not in store.progress, "the report goes away when the clip is ready"
    assert path.exists()


async def test_today_is_reused_for_a_minute_and_refresh_forces(hass, _cloud) -> None:
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    tz = ZoneInfo("Africa/Johannesburg")
    now = datetime.now(tz)
    today = now.date()
    start = datetime.combine(today, datetime.min.time(), tz) + timedelta(minutes=1)
    _entry, index = await _setup_with_index(hass, [start])
    camera = rec_module.find_camera(hass, "BK1")

    await rec_module.async_list_day(hass, camera, today)
    assert len(index.calls) == 1
    # Nothing but the refresh button may read today's list again this soon.
    await rec_module.async_list_day(hass, camera, today)
    assert len(index.calls) == 1, "a list under a minute old is reused"

    await rec_module.async_list_day(hass, camera, today, refresh=True)
    assert len(index.calls) == 2, "the refresh button forces a read"


async def test_a_finished_past_day_survives_a_restart(
    hass, _cloud, hass_storage
) -> None:
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    tz = ZoneInfo("Africa/Johannesburg")
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    start = datetime.combine(yesterday, datetime.min.time()) + timedelta(hours=8)
    _entry, index = await _setup_with_index(hass, [start])
    camera = rec_module.find_camera(hass, "BK1")

    first, complete = await rec_module.async_list_day(hass, camera, yesterday)
    assert complete and len(first) == 1
    assert "ezviz_rtsp.day_lists" in hass_storage
    assert len(index.calls) == 1

    # A restart forgets the in-memory cache; the stored list answers instead.
    hass.data.pop(rec_module.DATA_RECORDINGS)
    hass.data.pop(rec_module.DATA_LISTS)
    hass.data.pop(rec_module.DATA_LISTS_STORE)
    again, complete = await rec_module.async_list_day(hass, camera, yesterday)

    assert again == first and complete
    assert len(index.calls) == 1, "the finished day is not read from the camera again"


async def test_a_persisted_day_is_parsed_only_when_it_is_opened(
    hass, _cloud, hass_storage
) -> None:
    """A restart must not parse every stored day up front."""
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    tz = ZoneInfo("Africa/Johannesburg")
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    start = datetime.combine(yesterday, datetime.min.time()) + timedelta(hours=8)
    _entry, index = await _setup_with_index(hass, [start])
    camera = rec_module.find_camera(hass, "BK1")
    await rec_module.async_list_day(hass, camera, yesterday)

    # A restart rebuilds the store, but the stored day is left unparsed.
    hass.data.pop(rec_module.DATA_RECORDINGS)
    hass.data.pop(rec_module.DATA_LISTS)
    hass.data.pop(rec_module.DATA_LISTS_STORE)
    store = await rec_module.async_get_store(hass)
    assert ("BK1", yesterday) not in store.days

    # Opening it lifts just that day into the cache, without the camera.
    listed, complete = await rec_module.async_list_day(hass, camera, yesterday)
    assert complete and len(listed) == 1
    assert ("BK1", yesterday) in store.days
    assert len(index.calls) == 1


async def test_seen_days_survive_a_restart(hass, _cloud, hass_storage) -> None:
    """The calendar's blue dots must come back after a restart, without reopening."""
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    tz = ZoneInfo("Africa/Johannesburg")
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    start = datetime.combine(yesterday, datetime.min.time()) + timedelta(hours=8)
    _entry, index = await _setup_with_index(hass, [start])
    camera = rec_module.find_camera(hass, "BK1")
    await rec_module.async_list_day(hass, camera, yesterday)
    assert "ezviz_rtsp.sd_days" in hass_storage, "the day is written to storage"

    # A restart forgets the in-memory set; the stored days bring the dot back.
    hass.data.pop(rec_module.DATA_RECORDINGS)
    hass.data.pop(rec_module.DATA_SEEN)
    hass.data.pop(rec_module.DATA_SEEN_STORE)
    hass.data.pop(rec_module.DATA_LISTS)
    hass.data.pop(rec_module.DATA_LISTS_STORE)
    store = await rec_module.async_get_store(hass)
    assert ("BK1", yesterday) in store.seen

    days = await rec_module.async_month_days(
        hass, camera, yesterday.year, yesterday.month, scan=False
    )
    assert yesterday.isoformat() in days["card"]
    assert len(index.calls) == 1, "the dot comes from storage, not a camera read"


async def test_an_empty_finished_day_is_not_read_again(
    hass, _cloud, hass_storage
) -> None:
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    tz = ZoneInfo("Africa/Johannesburg")
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    _entry, index = await _setup_with_index(hass, [])
    camera = rec_module.find_camera(hass, "BK1")

    assert await rec_module.async_list_day(hass, camera, yesterday) == ([], True)
    hass.data.pop(rec_module.DATA_RECORDINGS)
    hass.data.pop(rec_module.DATA_LISTS)
    hass.data.pop(rec_module.DATA_LISTS_STORE)

    assert await rec_module.async_list_day(hass, camera, yesterday) == ([], True)
    assert len(index.calls) == 1, "even an empty finished day is not read again"


async def test_a_day_read_before_it_ended_is_read_again(hass, _cloud) -> None:
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    tz = ZoneInfo("Africa/Johannesburg")
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    start = datetime.combine(yesterday, datetime.min.time()) + timedelta(hours=8)
    _entry, index = await _setup_with_index(hass, [start])
    camera = rec_module.find_camera(hass, "BK1")
    store = await rec_module.async_get_store(hass)
    # The list was read while the day was still running: it may miss its end.
    store.days[("BK1", yesterday)] = rec_module._Day(
        [], time.monotonic(), True, False
    )

    recordings, complete = await rec_module.async_list_day(hass, camera, yesterday)

    assert complete and len(recordings) == 1
    assert len(index.calls) == 1, "the day is read once it is over"
    assert store.days[("BK1", yesterday)].final is True
    # Now it is settled: another open reads the cache.
    await rec_module.async_list_day(hass, camera, yesterday)
    assert len(index.calls) == 1


async def test_refresh_reads_a_finished_past_day_again(hass, _cloud) -> None:
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    tz = ZoneInfo("Africa/Johannesburg")
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    start = datetime.combine(yesterday, datetime.min.time()) + timedelta(hours=8)
    _entry, index = await _setup_with_index(hass, [start])
    camera = rec_module.find_camera(hass, "BK1")

    await rec_module.async_list_day(hass, camera, yesterday)
    await rec_module.async_list_day(hass, camera, yesterday, refresh=True)

    assert len(index.calls) == 2, "⟳ still asks the camera again"


def test_day_has_records_asks_for_one_record() -> None:
    day = date(2026, 10, 3)
    index = FakeIndex([datetime(2026, 10, 3, 8, 0)])
    now = datetime(2026, 11, 17, 12, 0, tzinfo=TZ)

    assert rec_module.day_has_records(index, "BB1", day, TZ, now) is True
    assert rec_module.day_has_records(index, "BB1", date(2026, 10, 4), TZ, now) is False


async def test_month_days_lists_the_days_with_saved_clips(hass, _cloud) -> None:
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    camera = rec_module.find_camera(hass, "BK1")
    key = ("BK1", "20261003T080000Z", "20261003T080008Z", "h264")
    saved = rec_module._clip_path(store, key)
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"mp4")
    rec_module._index_clip(store, key, saved)

    result = await rec_module.async_month_days(hass, camera, 2026, 10, scan=False)

    assert result["local"] == ["2026-10-03"]
    assert result["card"] == []
    assert result["scanned"] is None


async def test_two_cameras_keep_their_recordings_apart(hass, _cloud) -> None:
    """A second camera's clips must not show on the first camera's calendar."""
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    door = ("BK1", "20261003T080000Z", "20261003T080008Z", "h264")
    yard = ("BK2", "20261005T080000Z", "20261005T080008Z", "h264")
    for key in (door, yard):
        path = rec_module._clip_path(store, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_mp4_bytes(8))
        rec_module._index_clip(store, key, path)

    assert rec_module._local_days(store, "BK1", 2026, 10) == {date(2026, 10, 3)}
    assert rec_module._local_days(store, "BK2", 2026, 10) == {date(2026, 10, 5)}

    # Removing one camera's clip leaves the other camera's day alone.
    rec_module._drop_clip(store, door)
    assert rec_module._local_days(store, "BK1", 2026, 10) == set()
    assert rec_module._local_days(store, "BK2", 2026, 10) == {date(2026, 10, 5)}


async def test_month_scan_marks_days_and_persists(
    hass, _cloud, hass_storage
) -> None:
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    starts = [datetime(2026, 10, 3, 8, 0), datetime(2026, 10, 20, 9, 0)]
    await _setup_with_index(hass, starts)
    camera = rec_module.find_camera(hass, "BK1")

    result = await rec_module.async_month_days(hass, camera, 2026, 10, scan=True)

    assert result["local"] == []
    assert result["card"] == ["2026-10-03", "2026-10-20"]
    assert result["complete"] is True
    assert result["scanned"] is not None
    assert "ezviz_rtsp.recording_days" in hass_storage

    # A restart forgets the in-memory cache; the stored scan answers again
    # without asking the camera (no FakeIndex records would be needed).
    hass.data.pop(rec_module.DATA_DAYS)
    hass.data.pop(rec_module.DATA_DAYS_STORE)
    again = await rec_module.async_month_days(hass, camera, 2026, 10, scan=False)
    assert again["card"] == ["2026-10-03", "2026-10-20"]


async def test_websocket_lists_days_for_the_calendar(
    hass, hass_ws_client, _cloud
) -> None:
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    await _setup_with_index(hass, [datetime(2026, 10, 3, 8, 0)])
    ws = await hass_ws_client(hass)

    await ws.send_json(
        {"id": 1, "type": "ezviz_rtsp/recording/days", "serial": "BK1", "month": "2026-10"}
    )
    msg = await ws.receive_json()
    assert msg["success"], msg
    assert msg["result"]["card"] == []
    assert msg["result"]["local"] == []

    await ws.send_json(
        {
            "id": 2,
            "type": "ezviz_rtsp/recording/days",
            "serial": "BK1",
            "month": "2026-10",
            "scan": True,
        }
    )
    msg = await ws.receive_json()
    assert msg["success"], msg
    assert msg["result"]["card"] == ["2026-10-03"]
    assert msg["result"]["complete"] is True

    await ws.send_json(
        {"id": 3, "type": "ezviz_rtsp/recording/days", "serial": "BK1", "month": "nope"}
    )
    assert (await ws.receive_json())["error"]["code"] == "invalid_format"
    await ws.send_json(
        {"id": 4, "type": "ezviz_rtsp/recording/days", "serial": "BK1", "month": "2999-01"}
    )
    assert (await ws.receive_json())["error"]["code"] == "invalid_format"


async def test_websocket_reports_download_progress(hass, hass_ws_client, _cloud) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    key = ("BK1", "20261116T080000Z", "20261116T080008Z", "h264")
    store.progress[key] = {
        "stage": "downloading",
        "delivered": 3.5,
        "total": 8.0,
        "started": time.monotonic(),
        "attempt": 1,
    }
    ws = await hass_ws_client(hass)

    await ws.send_json(
        {
            "id": 1,
            "type": "ezviz_rtsp/recording/progress",
            "serial": "BK1",
            "begin": key[1],
            "end": key[2],
        }
    )
    msg = await ws.receive_json()
    assert msg["success"], msg
    assert msg["result"]["active"] is True
    assert msg["result"]["stage"] == "downloading"
    assert msg["result"]["delivered"] == 3.5
    assert msg["result"]["total"] == 8.0
    assert msg["result"]["attempt"] == 1

    await ws.send_json(
        {
            "id": 2,
            "type": "ezviz_rtsp/recording/progress",
            "serial": "BK1",
            "begin": "20260101T000000Z",
            "end": "20260101T000008Z",
        }
    )
    msg = await ws.receive_json()
    assert msg["result"] == {"active": False}


async def test_websocket_says_when_a_live_start_is_waiting_for_a_download(
    hass, hass_ws_client, _cloud
) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    ws = await hass_ws_client(hass)

    await ws.send_json({"id": 1, "type": "ezviz_rtsp/live/status", "serial": "BK1"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    assert msg["result"] == {"waiting": False}

    store.progress[("BK1", "20261116T080000Z", "20261116T080008Z", "h264")] = {
        "stage": "downloading"
    }
    await ws.send_json({"id": 2, "type": "ezviz_rtsp/live/status", "serial": "BK1"})
    msg = await ws.receive_json()
    assert msg["result"] == {"waiting": True}

    # Another camera's download does not hold this one back.
    await ws.send_json({"id": 3, "type": "ezviz_rtsp/live/status", "serial": "OTHER"})
    msg = await ws.receive_json()
    assert msg["result"] == {"waiting": False}


async def test_flat_clips_are_migrated_into_day_folders(hass, _cloud) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    # A clip saved flat by a version without the year/month/day folders.
    clip = store.root / "BK1_20261110T080000Z_20261110T080008Z_h264.mp4"
    clip.write_bytes(b"mp4")

    # A restart forgets the store; the next use rebuilds the index from the
    # folder and files the old clip away under its day.
    key = ("BK1", "20261110T080000Z", "20261110T080008Z", "h264")
    await rec_module.async_close_store(hass)
    assert rec_module.DATA_RECORDINGS not in hass.data
    again = await rec_module.async_get_store(hass)
    moved = rec_module._clip_path(again, key)
    assert not clip.exists()
    assert moved.exists()
    assert again.clips[key] == moved


async def test_downloaded_clips_are_pruned_by_retention(hass, _cloud) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    fresh = store.root / "BK1_20261110T080000Z_20261110T080008Z_h264.mp4"
    stale = store.root / "BK1_20261101T080000Z_20261101T080008Z_h264.mp4"
    fresh.write_bytes(b"fresh")
    stale.write_bytes(b"stale")
    ten_days_ago = time.time() - 10 * 86400
    os.utime(stale, (ten_days_ago, ten_days_ago))

    # The default keeps a week: the ten-day-old clip is swept, the new one stays.
    assert await rec_module.async_prune_recordings(hass) == 1
    assert fresh.exists() and not stale.exists()

    # 0 keeps them until they are removed by hand.
    stale.write_bytes(b"stale")
    os.utime(stale, (ten_days_ago, ten_days_ago))
    with patch.object(rec_module, "_keep_days", return_value=0):
        assert await rec_module.async_prune_recordings(hass) == 0
    assert stale.exists()


def test_each_account_sets_its_own_retention() -> None:
    """Retention comes from the account a camera belongs to, not the first one."""
    from homeassistant.const import CONF_TYPE

    from custom_components.ezviz_rtsp.const import (
        ATTR_TYPE_CLOUD,
        CONF_RECORDINGS_KEEP_DAYS,
    )

    def entry(keep, serials, kind=ATTR_TYPE_CLOUD):
        options = {} if keep is None else {CONF_RECORDINGS_KEEP_DAYS: keep}
        return SimpleNamespace(
            data={CONF_TYPE: kind},
            options=options,
            runtime_data=SimpleNamespace(data={s: {} for s in serials}),
        )

    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            # The sweep runs during setup, when no entry is LOADED yet, so it
            # must read every entry (with a coordinator), not the loaded ones.
            async_loaded_entries=lambda _domain: [],
            async_entries=lambda _domain: [
                entry(30, ["BK1"]),
                entry(7, ["BK2", "BK3"]),
                entry(None, ["BK4"]),  # no option set: the default applies
                entry(1, ["BK5"], kind="CAMERA_ACCOUNT"),  # not a cloud account
                entry(1, []),  # a cloud account that is not set up: no cameras
            ],
        )
    )

    assert rec_module._retention_by_serial(hass) == {
        "BK1": 30,
        "BK2": 7,
        "BK3": 7,
        "BK4": rec_module.DEFAULT_RECORDINGS_KEEP_DAYS,
    }


def test_prune_follows_each_cameras_retention(tmp_path) -> None:
    """A clip is kept or swept by its own camera's account window."""
    root = tmp_path / "media"
    folder = root / "2026/11/01"
    folder.mkdir(parents=True)
    old = time.time() - 10 * 86400
    clips = {
        name: folder / rec_module._clip_name(("BK" + name, "20261101T080000Z", "20261101T080008Z", "h264"))
        for name in ("1", "2", "9")
    }
    for path in clips.values():
        path.write_bytes(b"mp4")
        os.utime(path, (old, old))

    removed = rec_module._prune(root, {"BK1": 30, "BK2": 7, "BK3": 0})

    assert removed == [clips["2"].name]
    assert clips["1"].exists(), "30 days: a ten-day-old clip stays"
    assert not clips["2"].exists(), "7 days: swept"
    assert clips["9"].exists(), "a camera in no loaded account is left alone"


async def test_a_downloaded_clip_is_filed_under_its_local_day(hass, _cloud) -> None:
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    await _setup_with_index(hass, [])
    camera = rec_module.find_camera(hass, "BK1")
    # 22:30 UTC is already the next day in Johannesburg (UTC+2).
    begin = datetime(2026, 11, 10, 22, 30, tzinfo=UTC)
    end = begin + timedelta(seconds=8)

    with (
        patch.object(rec_module, "_download_clip", return_value=b"PSDATA"),
        patch.object(
            rec_module,
            "_async_to_mp4",
            side_effect=lambda _bin, _ps, _fmt, target: target.write_bytes(b"mp4"),
        ),
        patch("custom_components.ezviz_rtsp.live.ffmpeg_binary", return_value="ffmpeg"),
    ):
        path = await rec_module.async_get_clip(hass, camera, begin, end, "h264")

    assert path == (
        rec_module.media_root(hass)
        / "2026/11/11"
        / "BK1_20261110T223000Z_20261110T223008Z_h264.mp4"
    )
    assert path.exists()


async def test_retention_removes_empty_day_folders(hass, _cloud) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    folder = store.root / "2026/10/01"
    folder.mkdir(parents=True)
    stale = folder / "BK1_20261001T080000Z_20261001T080008Z_h264.mp4"
    stale.write_bytes(b"stale")
    ten_days_ago = time.time() - 10 * 86400
    os.utime(stale, (ten_days_ago, ten_days_ago))

    assert await rec_module.async_prune_recordings(hass) == 1
    assert not stale.exists()
    # The empty year/month/day folders go with it.
    assert not (store.root / "2026").exists()


async def test_recordings_sweep_is_scheduled_and_stopped(hass, _cloud) -> None:
    entry, _ = await _setup_with_index(hass, [])
    assert rec_module.DATA_RECORDINGS_TIMER in hass.data
    # The last account unloading stops the daily sweep.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert rec_module.DATA_RECORDINGS_TIMER not in hass.data


async def test_daily_sweep_prunes_old_clips(hass, _cloud) -> None:
    await _setup_with_index(hass, [])
    store = await rec_module.async_get_store(hass)
    stale = store.root / "BK1_20261101T080000Z_20261101T080008Z_h264.mp4"
    stale.write_bytes(b"stale")
    ten_days_ago = time.time() - 10 * 86400
    os.utime(stale, (ten_days_ago, ten_days_ago))

    # A day later the timer fires and sweeps the clip that has aged out.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(days=1))
    await hass.async_block_till_done()

    assert not stale.exists()


# -- the latest recording: service, button and sensor ----------------------------


@contextmanager
def _clip_available():
    """Enter the patchers that stand in for the camera read and the ffmpeg conversion."""
    with (
        patch.object(rec_module, "_download_clip", return_value=b"PSDATA"),
        patch.object(
            rec_module,
            "_async_to_mp4",
            side_effect=lambda _bin, ps, fmt, target: target.write_bytes(b"mp4"),
        ),
        patch("custom_components.ezviz_rtsp.live.ffmpeg_binary", return_value="ffmpeg"),
    ):
        yield


def _bare_camera() -> rec_module.Camera:
    return rec_module.Camera(coordinator=MagicMock(), serial="BK1", code=None)


def _bare_hass() -> MagicMock:
    hass = MagicMock()
    hass.config.time_zone = "Africa/Johannesburg"
    return hass


async def test_latest_recording_prefers_today() -> None:
    tz = ZoneInfo("Africa/Johannesburg")
    today = datetime.now(tz).date()
    newest = (
        datetime(2026, 11, 10, 9, 0, tzinfo=tz),
        datetime(2026, 11, 10, 9, 0, 8, tzinfo=tz),
    )
    seen: list[date] = []

    async def fake_list(_hass, _camera, day, *, refresh=False):
        seen.append(day)
        return ([newest], True) if day == today else ([], True)

    with (
        patch.object(rec_module, "async_list_day", fake_list),
        patch.object(rec_module, "async_get_clip", return_value=Path("/media/today.mp4")),
    ):
        begin, end, path = await rec_module.async_latest_recording(_bare_hass(), _bare_camera())

    assert seen == [today]
    assert (begin, end) == newest
    assert path == Path("/media/today.mp4")


async def test_latest_recording_falls_back_to_yesterday() -> None:
    tz = ZoneInfo("Africa/Johannesburg")
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)
    older = (
        datetime(2026, 11, 9, 9, 0, tzinfo=tz),
        datetime(2026, 11, 9, 9, 0, 8, tzinfo=tz),
    )
    seen: list[date] = []

    async def fake_list(_hass, _camera, day, *, refresh=False):
        seen.append(day)
        return ([older], True) if day == yesterday else ([], True)

    with (
        patch.object(rec_module, "async_list_day", fake_list),
        patch.object(rec_module, "async_get_clip", return_value=Path("/media/yesterday.mp4")),
    ):
        begin, _end, path = await rec_module.async_latest_recording(_bare_hass(), _bare_camera())

    assert seen == [today, yesterday]
    assert begin == older[0]
    assert path == Path("/media/yesterday.mp4")


async def test_latest_recording_raises_when_there_are_none() -> None:
    async def fake_list(*_args, **_kwargs):
        return [], True

    with (
        patch.object(rec_module, "async_list_day", fake_list),
        pytest.raises(RecordingError, match="No recordings"),
    ):
        await rec_module.async_latest_recording(_bare_hass(), _bare_camera())


async def test_download_latest_announces_the_recording() -> None:
    tz = ZoneInfo("Africa/Johannesburg")
    begin = datetime(2026, 11, 10, 9, 0, tzinfo=tz)
    end = begin + timedelta(seconds=8)

    with (
        patch.object(
            rec_module,
            "async_latest_recording",
            return_value=(begin, end, Path("/media/BK1_x.mp4")),
        ),
        patch.object(rec_module, "async_dispatcher_send") as send,
    ):
        result = await rec_module.async_download_latest(_bare_hass(), _bare_camera())

    assert result["serial"] == "BK1"
    assert result["format"] == "h264"
    assert result["seconds"] == 8
    assert result["path"] == "/media/BK1_x.mp4"
    send.assert_called_once()
    assert send.call_args.args[1] == SIGNAL_RECORDING_DOWNLOADED.format("BK1")
    assert send.call_args.args[2] == result


async def _yesterday_camera(hass) -> None:
    tz = ZoneInfo("Africa/Johannesburg")
    await hass.config.async_set_time_zone("Africa/Johannesburg")
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    starts = [
        datetime.combine(yesterday, datetime.min.time()) + timedelta(hours=h) for h in (8, 9)
    ]
    await _setup_with_index(hass, starts)


async def test_download_recording_service_updates_the_sensor(hass, _cloud) -> None:
    await _yesterday_camera(hass)
    sensor_id = next(
        entity
        for entity in hass.states.async_entity_ids("sensor")
        if entity.endswith("_latest_recording")
    )
    assert hass.states.get(sensor_id).state == "unknown"
    camera_id = next(iter(hass.states.async_entity_ids("camera")))

    with _clip_available():
        response = await hass.services.async_call(
            DOMAIN,
            "download_recording",
            {"entity_id": camera_id},
            blocking=True,
            return_response=True,
        )

    recording = response[camera_id]
    assert recording["serial"] == "BK1"
    assert recording["format"] == "h264"
    assert recording["seconds"] == 8
    state = hass.states.get(sensor_id)
    assert state.state != "unknown"
    assert state.attributes["path"].endswith(".mp4")
    assert state.attributes["format"] == "h264"


async def test_download_recording_button_updates_the_sensor(hass, _cloud) -> None:
    await _yesterday_camera(hass)
    sensor_id = next(
        entity
        for entity in hass.states.async_entity_ids("sensor")
        if entity.endswith("_latest_recording")
    )
    button_id = next(
        entity
        for entity in hass.states.async_entity_ids("button")
        if entity.endswith("_download_latest_recording")
    )

    with _clip_available():
        await hass.services.async_call(
            "button", "press", {"entity_id": button_id}, blocking=True
        )
        await hass.async_block_till_done()

    assert hass.states.get(sensor_id).state != "unknown"
