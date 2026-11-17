"""The shape of a camera's picture, learned from the picture itself.

The card sizes its picture box to the camera's own shape, but it cannot know that
shape until the picture has loaded, so the box used to sit at the default 16:9
and grow a moment later — a small jump the reader sees on every dashboard open.

The integration already fetches the picture for the camera's thumbnail (a
cloud-stored JPEG, so no battery is spent). Reading its size and handing it to
the card lets the box be the right height from the first paint.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_SHAPES = f"{DOMAIN}_picture_shapes"
DATA_SHAPES_STORE = f"{DOMAIN}_picture_shapes_store"
DATA_SHAPES_LOCK = f"{DOMAIN}_picture_shapes_lock"
SHAPES_STORAGE_KEY = f"{DOMAIN}.picture_shapes"
SHAPES_STORAGE_VERSION = 1

# JPEG "start of frame" markers; each carries the frame's height and width.
_SOF_MARKERS = frozenset(
    (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF)
)


def jpeg_size(data: bytes | bytearray) -> tuple[int, int] | None:
    """The (width, height) of a JPEG, read from its header, or None.

    Walks the JPEG markers to the first "start of frame", which holds the size.
    Only the header is read, so no image library is needed.
    """
    if len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
        return None
    i = 2
    end = len(data)
    while i + 9 < end:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        # Markers that carry no length field.
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xD9:  # end of image, no frame seen
            return None
        length = (data[i + 2] << 8) | data[i + 3]
        if length < 2:
            return None
        if marker in _SOF_MARKERS:
            height = (data[i + 5] << 8) | data[i + 6]
            width = (data[i + 7] << 8) | data[i + 8]
            return (width, height) if width and height else None
        i += 2 + length
    return None


async def _cache(hass: HomeAssistant) -> dict[str, Any]:
    """The remembered shapes, loaded from Home Assistant's storage once."""
    if (data := hass.data.get(DATA_SHAPES)) is not None:
        return data
    lock: asyncio.Lock = hass.data.setdefault(DATA_SHAPES_LOCK, asyncio.Lock())
    async with lock:
        if (data := hass.data.get(DATA_SHAPES)) is not None:
            return data
        storage: Store = Store(hass, SHAPES_STORAGE_VERSION, SHAPES_STORAGE_KEY)
        data = await storage.async_load() or {}
        hass.data[DATA_SHAPES] = data
        hass.data[DATA_SHAPES_STORE] = storage
        return data


async def async_load_shapes(hass: HomeAssistant) -> None:
    """Load the remembered picture shapes into memory, before entities read them."""
    await _cache(hass)


def shape_for(hass: HomeAssistant, serial: str) -> tuple[int, int] | None:
    """The last known (width, height) of a camera's picture, or None.

    Synchronous, so an entity's attributes and the websocket device list can
    carry it without waiting.
    """
    data = hass.data.get(DATA_SHAPES) or {}
    shape = data.get(serial)
    if not isinstance(shape, (list, tuple)) or len(shape) != 2:
        return None
    width, height = shape
    if not isinstance(width, int) or not isinstance(height, int):
        return None
    return (width, height) if width > 0 and height > 0 else None


async def async_remember_picture(
    hass: HomeAssistant, serial: str, content: bytes
) -> None:
    """Learn a camera's picture shape from a JPEG the integration just fetched.

    The bytes are the same picture served as the camera's thumbnail, so the card
    can size its box before the picture loads. It is a cloud-stored picture, so
    nothing wakes the camera.
    """
    size = jpeg_size(content)
    if size is None:
        return
    cache = await _cache(hass)
    if cache.get(serial) == [size[0], size[1]]:
        return
    cache[serial] = [size[0], size[1]]
    storage: Store = hass.data[DATA_SHAPES_STORE]
    async with hass.data[DATA_SHAPES_LOCK]:
        await storage.async_save(cache)
