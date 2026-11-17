"""Integration test: a battery camera streams through the cloud on a real hass."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.components.camera import CameraEntityFeature
from homeassistant.const import CONF_TYPE, CONF_URL, Platform
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ezviz_rtsp.const import (
    ATTR_TYPE_CLOUD,
    CONF_RFSESSION_ID,
    CONF_SESSION_ID,
    DATA_CARD,
    DATA_LIVE_VIEW,
    DOMAIN,
)

CAM_DATA = {
    "BK1": {
        "name": "Door",
        "mac_address": None,
        "device_sub_category": "DP2",
        "version": "1.0",
        "status": 1,
        "alarm_notify": False,
        "local_ip": "192.168.1.50",
        "local_rtsp_port": 554,
        "battery_level": 52,
        "battery_camera_work_mode": 5,
        "supported_channels": 1,
        "encrypted": False,
        "supportExt": {},
    }
}


class _FakeClient:
    """Stands in for pyezvizapi's EzvizClient: a logged-in client with one camera."""

    def __init__(self, *_args, **_kwargs) -> None:
        self.login_calls = 0

    def login(self, sms_code=None) -> dict:
        self.login_calls += 1
        return {}

    def load_cameras(self, refresh: bool = True) -> dict:
        return CAM_DATA

    def export_token(self) -> dict:
        return {}

    def get_detection_sensibility(self, _serial) -> None:
        return None

    def capture_picture(self, _serial, _channel) -> dict:
        return {}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def _setup(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_TYPE: ATTR_TYPE_CLOUD,
            CONF_SESSION_ID: "session",
            CONF_RFSESSION_ID: "refresh",
            CONF_URL: "apiieu.ezvizlife.com",
        },
        options={
            "ffmpeg_arguments": "/Streaming/Channels/102",
            "timeout": 25,
            "max_session": 30,
            "linger": 5,
        },
        unique_id="owner@example.com",
    )
    entry.add_to_hass(hass)
    # Only the platforms this fork adds to: the camera, its button, images, sensors.
    with (
        patch("custom_components.ezviz_rtsp.EzvizClient", _FakeClient),
        patch.dict(
            "custom_components.ezviz_rtsp.PLATFORMS_BY_TYPE",
            {
                ATTR_TYPE_CLOUD: [
                    Platform.CAMERA,
                    Platform.BUTTON,
                    Platform.IMAGE,
                    Platform.SENSOR,
                ]
            },
        ),
        patch("custom_components.ezviz_rtsp.camera.get_ffmpeg_manager"),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_battery_camera_sets_up_and_offers_a_cloud_stream(hass) -> None:
    entry = await _setup(hass)

    # The camera entity exists and advertises streaming.
    camera_ids = [s for s in hass.states.async_entity_ids("camera")]
    assert camera_ids, "no camera entity was created"
    state = hass.states.get(camera_ids[0])
    assert state is not None
    assert state.attributes["supported_features"] & CameraEntityFeature.STREAM

    # The cloud stream was built for the camera, and the view registered.
    assert set(entry.runtime_data.live_streams) == {"BK1"}
    # A battery camera's stream carries a hard session cap (never left streaming).
    assert entry.runtime_data.live_streams["BK1"].battery is True
    # The cap comes from the options ("Maximum stream duration").
    assert entry.runtime_data.live_streams["BK1"]._max_session == 30
    # The release delay comes from the options ("Release the camera after").
    assert entry.runtime_data.live_streams["BK1"]._linger_seconds == 5
    # Other apps are blocked by default; the card reads an authenticated view.
    assert entry.runtime_data.live_streams["BK1"].external_enabled is False
    assert entry.options["internal_token"]
    assert hass.data[DATA_LIVE_VIEW] is True

    # The camera gets a Request snapshot and a Download latest recording button
    # in Controls, even without PTZ.
    button_ids = hass.states.async_entity_ids("button")
    assert len(button_ids) == 2, button_ids
    assert any(entity.endswith("_request_snapshot") for entity in button_ids)
    assert any(entity.endswith("_download_latest_recording") for entity in button_ids)

    # A battery camera must not trigger the RTSP discovery flow.
    assert hass.config_entries.flow.async_progress() == []

    # The entity's stream source is the loopback MPEG-TS address of our view.
    component = hass.data["entity_components"][Platform.CAMERA]
    entity = component.get_entity(camera_ids[0])
    assert entity is not None
    source = await entity.stream_source()
    assert source is not None
    assert source.startswith("http://127.0.0.1:")
    assert f"/api/{DOMAIN}/live/BK1?token=" in source
    # The stream source carries the integration's own token (never the public one).
    assert entry.options["internal_token"] in source

    # The Lovelace card is served and registered for the frontend.
    assert hass.data[DATA_CARD] is True
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL

    module_urls = hass.data[DATA_EXTRA_MODULE_URL].urls
    assert any(
        "/ezviz_rtsp/ezviz-video-card.js" in url for url in module_urls
    ), module_urls
    # The URL carries the integration version, so the card can log it.
    assert any("version=" in url for url in module_urls), module_urls

    # Both integration services are registered (wake + detection sensitivity).
    assert hass.services.has_service(DOMAIN, "wake_device")
    assert hass.services.has_service(DOMAIN, "set_alarm_detection_sensibility")


async def test_card_registration_retries_after_a_failure(hass) -> None:
    """A failure while shipping the card must not block a later retry."""
    from custom_components.ezviz_rtsp import _async_register_card

    await _setup(hass)
    # Pretend the card still has to be registered (as after a failed attempt).
    hass.data.pop(DATA_CARD)

    with (
        patch(
            "custom_components.ezviz_rtsp.async_get_integration",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(RuntimeError),
    ):
        await _async_register_card(hass)

    assert hass.data.get(DATA_CARD) is not True

    # The static paths were added before the failure, so the retry must not add
    # them again (aiohttp refuses a route registered twice) - it still finishes.
    await _async_register_card(hass)
    assert hass.data[DATA_CARD] is True


async def test_an_entity_goes_unavailable_when_its_camera_leaves(hass) -> None:
    """A camera that leaves the account must not raise on every poll.

    The entity stays loaded, so ``data`` and ``available`` are read on each
    coordinator update; a missing camera used to raise ``KeyError`` there.
    """
    entry = await _setup(hass)
    camera_id = hass.states.async_entity_ids("camera")[0]
    entity = hass.data["entity_components"][Platform.CAMERA].get_entity(camera_id)
    coordinator = entry.runtime_data

    assert entity.available is True
    assert entity.data["name"] == "Door"

    # The camera is gone from the next poll: reads are empty, not a KeyError.
    coordinator.data = {}
    assert entity.data == {}
    assert entity.available is False

    # A failed poll makes the entity unavailable even with data present.
    coordinator.data = CAM_DATA
    coordinator.last_update_success = False
    assert entity.available is False


async def test_request_snapshot_button_updates_the_snapshot_image(hass) -> None:
    await _setup(hass)
    snapshot_id = next(
        entity for entity in hass.states.async_entity_ids("image") if entity.endswith("_snapshot")
    )
    assert hass.states.get(snapshot_id).state == "unknown"
    button_id = next(
        entity
        for entity in hass.states.async_entity_ids("button")
        if entity.endswith("_request_snapshot")
    )

    with patch.object(
        _FakeClient,
        "capture_picture",
        return_value={"captureInfo": {"picUrl": "https://ezviz/pic.jpg"}},
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": button_id}, blocking=True
        )
        await hass.async_block_till_done()

    state = hass.states.get(snapshot_id)
    assert state.state != "unknown"
    assert state.attributes.get("entity_picture")


async def test_card_file_is_served(hass, hass_client) -> None:
    await _setup(hass)
    client = await hass_client()
    resp = await client.get("/ezviz_rtsp/ezviz-video-card.js")
    assert resp.status == 200
    assert "text/javascript" in resp.headers["Content-Type"]
    body = await resp.text()
    # The file defines and announces the card.
    assert "custom:ezviz-video-card" in body or "ezviz-video-card" in body
    assert "window.customCards.push" in body
    # hls.js is bundled, never fetched from a CDN.
    assert "cdn.jsdelivr.net" not in body
    assert "hls.min.js" in body


async def test_bundled_hls_is_served(hass, hass_client) -> None:
    await _setup(hass)
    client = await hass_client()
    resp = await client.get("/ezviz_rtsp/hls.min.js")
    assert resp.status == 200
    assert "javascript" in resp.headers["Content-Type"]
    assert "Hls" in await resp.text()


async def test_card_devices_websocket_lists_the_camera(hass, hass_ws_client) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 7, "type": f"{DOMAIN}/devices"})
    msg = await client.receive_json()
    assert msg["success"]
    (device,) = msg["result"]
    assert device["serial"] == "BK1"
    assert device["name"] == "Door"
    assert device["battery"] is True
    assert device["battery_level"] == 52
    assert "battery_entity_id" in device
    assert device["mjpeg_url"].startswith(f"/api/{DOMAIN}/card/BK1?authSig=")
    assert device["entity_id"]
