"""The camera picture's shape, which the integration hands to the card."""

from __future__ import annotations

import struct

import pytest

from custom_components.ezviz_rtsp.picture import (
    DATA_SHAPES,
    DATA_SHAPES_STORE,
    async_load_shapes,
    async_remember_picture,
    jpeg_size,
    shape_for,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def _jpeg(width: int, height: int, *, sof: int = 0xC0) -> bytes:
    """A JPEG that carries just enough of a header to read its size."""
    frame = bytes([0x08]) + struct.pack(">HH", height, width) + bytes(
        [0x03, 0x01, 0x22, 0x00, 0x02, 0x11, 0x01, 0x03, 0x11, 0x01]
    )
    return (
        b"\xff\xd8"
        + bytes([0xFF, sof])
        + struct.pack(">H", len(frame) + 2)
        + frame
        + b"\xff\xd9"
    )


def test_jpeg_size_reads_the_frame() -> None:
    assert jpeg_size(_jpeg(2048, 1296)) == (2048, 1296)
    # A progressive JPEG's frame marker carries the size too.
    assert jpeg_size(_jpeg(640, 480, sof=0xC2)) == (640, 480)


def test_jpeg_size_skips_segments_before_the_frame() -> None:
    app0 = (
        b"\xff\xe0"
        + struct.pack(">H", 16)
        + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    )
    data = b"\xff\xd8" + app0 + _jpeg(1024, 768)[2:]
    assert jpeg_size(data) == (1024, 768)


def test_jpeg_size_rejects_anything_else() -> None:
    assert jpeg_size(b"") is None
    assert jpeg_size(b"not a jpeg at all") is None
    assert jpeg_size(b"\xff\xd8\xff\xc0\x00\x11\x08") is None  # cut off mid-header
    assert jpeg_size(b"\xff\xd8\xff\xd9") is None  # no frame at all


async def test_a_shape_is_remembered_and_persisted(hass) -> None:
    await async_load_shapes(hass)
    assert shape_for(hass, "BK1") is None

    await async_remember_picture(hass, "BK1", _jpeg(2048, 1296))
    assert shape_for(hass, "BK1") == (2048, 1296)

    # Persisted: dropping the in-memory copy and reloading finds it again.
    hass.data.pop(DATA_SHAPES)
    hass.data.pop(DATA_SHAPES_STORE)
    await async_load_shapes(hass)
    assert shape_for(hass, "BK1") == (2048, 1296)


async def test_pictures_that_are_not_jpegs_are_ignored(hass) -> None:
    await async_load_shapes(hass)
    await async_remember_picture(hass, "BK1", b"nope")
    assert shape_for(hass, "BK1") is None


async def test_a_stored_shape_reaches_the_camera_from_its_first_state(hass) -> None:
    from tests.test_integration import _setup

    await async_load_shapes(hass)
    await async_remember_picture(hass, "BK1", _jpeg(1024, 768))

    await _setup(hass)

    camera_id = next(iter(hass.states.async_entity_ids("camera")))
    attributes = hass.states.get(camera_id).attributes
    assert attributes["serial"] == "BK1"
    assert attributes["picture_width"] == 1024
    assert attributes["picture_height"] == 768


async def test_the_devices_list_carries_the_shape(hass, hass_ws_client) -> None:
    from tests.test_integration import _setup

    await _setup(hass)
    await async_remember_picture(hass, "BK1", _jpeg(2048, 1296))

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "ezviz_rtsp/devices"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    device = next(d for d in msg["result"] if d["serial"] == "BK1")
    assert device["picture_width"] == 2048
    assert device["picture_height"] == 1296
