"""Tests for the SD-card recordings: decoding the index, paging a day, clip helpers."""

from __future__ import annotations

import base64
import json
import zlib
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from pyezvizapi.exceptions import PyEzvizError

from custom_components.ezviz_rtsp import recordings as rec_module
from custom_components.ezviz_rtsp.const import DOMAIN
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


def _rec(begin: datetime, seconds: int = 8) -> dict:
    return {
        "B": begin.strftime("%Y-%m-%dT%H:%M:%S"),
        "E": (begin + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S"),
        "Type": 0,
    }


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
    [("2009", "did not answer in time"), ("2004", "SD card"), ("9999", "Could not read")],
)
def test_search_day_explains_camera_errors(code: str, text: str, monkeypatch) -> None:
    monkeypatch.setattr(rec_module, "WAKE_RETRY_SECONDS", 0)
    index = FakeIndex([], fail=PyEzvizError(f"Could not search v2 records: response code={code}"))
    with pytest.raises(RecordingError, match=text):
        search_day(index, "BB1", date(2026, 11, 9), TZ, datetime(2026, 11, 10, tzinfo=TZ))
    # Only the "camera asleep" answer is retried, and only once.
    assert len(index.calls) == (2 if code == "2009" else 1)


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


# -- on a real hass (needs the HA test harness, so Linux) -------------------------



@pytest.fixture
def _cloud(enable_custom_integrations):
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
        assert download.call_count == 1
        args = download.call_args.args
        assert args[1:5] == ("BK1", newest["begin"], newest["end"], "Africa/Johannesburg")

    url = clip["result"]["url"]
    assert url.startswith(f"/api/{DOMAIN}/recording/BK1/{newest['begin']}/{newest['end']}/hevc.mp4?authSig=")
    client = await hass_client()
    response = await client.get(url, headers={"Range": "bytes=0-3"})
    assert response.status == 206
    assert await response.read() == b"\0\0\0\x18"

    # Unknown cameras and bad input are refused with errors, not exceptions.
    await ws.send_json({"id": 5, "type": "ezviz_rtsp/recordings", "serial": "NOPE"})
    assert (await ws.receive_json())["error"]["code"] == "not_found"
    await ws.send_json(
        {"id": 6, "type": "ezviz_rtsp/recording/clip", "serial": "BK1", "begin": "x", "end": "y"}
    )
    assert (await ws.receive_json())["error"]["code"] == "recording_failed"

    # Unloading the account drops the cache directory.
    root = rec_module.get_store(hass).root
    assert root.exists()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not root.exists()


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
