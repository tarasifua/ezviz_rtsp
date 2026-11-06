# Changelog

All notable changes to **Ezviz Cloud with Video** (`ezviz_rtsp`) are listed here.
This project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **`ezviz_rtsp.capture_picture`** camera service: the cloud wakes the camera
  and it takes a new full-resolution picture, shown by a new per-camera
  **Snapshot** image entity (`image.<camera>_snapshot`); the service can return
  the `picture_url`. Gives battery cameras a current picture on demand without
  RTSP. Follows RenierM26/ha-ezviz#235 by @ottes (Michael Freund).
- `capture_picture` takes an optional **`min_interval`** (a call within that
  time of the camera's last capture is skipped) and an **`automatic`** flag.
- **`custom:ezviz-snapshot-card`**: shows the Snapshot image and, with
  `capture_on_load: true` (off by default, like the video card's `auto_play`),
  takes a new picture whenever it comes into view.
- **Configure → Snapshots**: turn those automatic snapshots on or off, and set
  the minimum time between them per camera (default 300 s).
- A capture that a sleeping camera answers with EZVIZ 2009 (still waking) is
  retried once by the service after 5 s.

## [1.3.0] — 2026-11-04

Fixes from the HACS review: the card no longer loads code from a CDN, its live
picture sits behind Home Assistant authentication, and two smaller bugs are gone.

### Added
- **hls.js is bundled** with the integration and served from its own static
  path (with its license in `frontend/hls.min.js.LICENSE.txt`), so the card
  works without internet access and never fetches code from a public CDN.

### Changed
- The card's live picture is served from an **authenticated view**, reached
  through a short-lived **signed URL** (`async_sign_path`) that the websocket
  command hands out. A link that leaks — or a user you later remove — can no
  longer keep watching a camera. The opt-in token addresses for go2rtc, Frigate
  and friends are unchanged.

### Fixed
- The siren now **awaits** its turn-on call, so a failed command is reported
  instead of the siren showing as on while nothing happened.
- The `set_alarm_detection_sensibility` service is **registered** (it was
  declared but did nothing), and the service target picker points at
  `ezviz_rtsp` instead of the core `ezviz` domain.

## [1.2.1] — 2026-11-04

A housekeeping release that gets the repository ready for the HACS store.

### Added
- **Integration categories** in the manifest (`security_safety.cameras`,
  `security_safety.doorbells_intercoms`) so the integration is listed correctly
  in the HACS Marketplace.
- The repository is now validated by the **HACS Action** and **hassfest** on
  every push and pull request (and daily), so it keeps meeting the HACS
  requirements.

### Changed
- The `pyezvizapi` requirement is no longer pinned (`>=1.0.5.0`), so it can
  follow the version Home Assistant itself ships.

### Docs
- README corrections: the card is a corner play/stop chip that plays its own
  fast MJPEG stream, transcoding applies to Home Assistant's stream and other
  apps, and the other-apps addresses are opt-in. Plus a larger Ko-fi button.

## [1.2.0] — 2026-11-01

Two new Configure options put the streaming addresses and the post-view release
delay under your control, and a switch decides who may read the addresses.

### Fixed
- Turning the stream addresses for other apps **off** no longer breaks Home
  Assistant's own camera stream: the integration reads the stream with its own
  token, so the HLS path and the camera entity keep working while go2rtc,
  Frigate and friends are blocked.

### Added
- **Stream address for other apps** option (Configure → Stream address for other
  apps): lists each cloud camera's token-guarded MPEG-TS and MJPEG addresses,
  can hand out a **new token** (links shared before then stop working), and has
  an **Allow other apps to read the stream** switch — **off by default** — that
  turns those addresses on. The bundled card keeps working either way: it carries
  its own separate token.
- **Release the camera after** option (Configure → Release the camera after):
  how long the cloud stream is held open after the last viewer leaves, in seconds
  (default **10**; `0` releases the camera at once). A short hold keeps a quick
  re-play from waking a battery camera again.

## [1.1.0] — 2026-11-01

The live view is fast now, the card looks and behaves like a Mushroom card, and a
battery camera can never be left streaming.

### Added
- **Fast live view.** The integration encodes the cloud stream straight to JPEG
  and serves it as live MJPEG (`/api/ezviz_rtsp/mjpeg/<serial>`), so the card's
  picture appears a few seconds after the camera wakes instead of waiting for
  Home Assistant's HLS worker to build segments. HLS stays as the fallback.
- **Battery charge** of a battery camera shown in the card's header, opposite the
  camera name (red below 20 %).
- The card logs its version **and build hash** to the browser console
  (`[ezviz-video-card] loaded v…+hash`) so a running build is easy to confirm.

### Changed
- **The card is a Mushroom-style picture**: a small **play chip in the
  bottom-right corner** replaces the big round button over the middle; the
  **Stop** chip sits in the same corner while watching.
- `auto_play` now defaults to **off**: the card shows the camera's last alarm
  picture and waits for you to press play, so opening a dashboard never wakes a
  battery camera.
- **Leaving the card stops the stream for good** — switching to another dashboard
  view, hiding the tab, or scrolling away. Coming back shows the last picture
  with the play chip (or starts again when `auto_play` is on).
- While the stream wakes, the card keeps the **last picture** on screen with a
  small corner spinner instead of a dark overlay.
- Configure → **General**: the FFmpeg arguments field is relabelled and explained
  (it only applies to cameras added over local RTSP; cloud cameras ignore it).

### Fixed
- **Video actually plays** in Chromium browsers (Brave, Chrome): the card now
  prefers hls.js, like Home Assistant's own player, instead of the browser's
  native HLS path (which answered "maybe" and then failed to demux).
- The card **starts a new clip** after `max_seconds` runs out; previously a
  "stopped after N s" overlay swallowed the tap and a page reload was needed.
- Switching views no longer leaves a **"Stop" button with no picture**: the card
  is removed from the DOM by Lovelace, and it now stops cleanly on a real removal.

### Safety
- A battery camera is stopped when the card leaves the screen, **20 s** after the
  last reader leaves the cloud session (`LINGER`), and at the latest after
  **Maximum stream duration** (`Configure`, default 300 s) — and every open/close
  is written to the log.

## [1.0.9] — 2026-10-31
- The card prints its version in the browser console (read from the module URL,
  so it can never drift from the manifest).

## [1.0.8] — 2026-10-31
- New **Maximum stream duration** option (Configure): how long one battery-camera
  live stream may run before it is stopped, in seconds (default 300; `0` = no cap).

## [1.0.7] — 2026-10-31
- Battery safety: the card stops the stream reliably (leaving the view, a hidden
  tab), the integration closes the cloud session shortly after the last reader,
  and a battery camera is cut off after a hard session cap.

## [1.0.6] — 2026-10-31
- Fix the config-flow option labels that showed raw translation keys.

## [1.0.5] — 2026-10-31
- Cards and fixes on top of the first releases.

## [1.0.0] – [1.0.4] — 2026-10-31
- First releases: EZVIZ cloud (VTM) relay for battery cameras and peepholes that
  expose no local RTSP, a bundled Mushroom-styled Lovelace card, and a
  token-guarded MPEG-TS address for go2rtc, Frigate and friends.

[1.3.0]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.3.0
[1.2.1]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.2.1
[1.2.0]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.2.0
[1.1.0]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.1.0
[1.0.9]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.0.9
[1.0.8]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.0.8
[1.0.7]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.0.7