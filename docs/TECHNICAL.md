# Technical notes

How **Ezviz Cloud with Video** works inside, for anyone reading the code,
building their own UI on top of it, or wondering why it behaves the way it
does. The [README](../README.md) is the user-facing guide; this is the
implementation side of it.

---

## How the live view works

A cloud camera sleeps and never opens an RTSP port, so nothing local can reach
it. The integration does what the phone app does on mobile data: it asks the
EZVIZ cloud to wake the camera and relays the stream.

```
 camera ──(sleeps)──┐
                    │  EZVIZ cloud wakes it on demand
                    ▼
        EZVIZ VTM relay ──► LiveSource (worker thread, pyezvizapi)
                                    │
                    MPEG-PS frames  │  pack-split, optional H.265/AES decrypt
                                    ▼
                              LiveStream (one per camera, shared)
                                    │
                ┌───────────────────┴────────────────────┐
     LiveStreamView (MPEG-TS)                  MJPEG views (live JPEG)
      ├─ HA stream worker ──► HLS (H.264)      ├─ the bundled card (signed URL)
      └─ other apps (go2rtc, Frigate …)        └─ a <img> (stream token, opt-in)
```

The whole stream is opened lazily — the first thing that asks for it starts it,
and it closes a few seconds after the last reader leaves. Nothing polls a
sleeping camera in the background.

The bundled card reads the integration's **own MJPEG picture view** through a
short-lived **signed URL**, so a link that leaks (or a user you later remove)
cannot keep watching, and the card loads no code from a public CDN — **hls.js
is bundled with the integration** and served from its own path. For a camera
the integration does not stream itself, the card falls back to Home Assistant's
HLS.

**A battery camera can never be left streaming forever.** Any one of these ends
it:

1. The **card** stops the stream when `max_seconds` runs out, and releases the
   reader.
2. The **integration** closes the cloud session shortly after the last reader
   leaves — **10 seconds** by default (changeable under **Configure → Release
   the camera after**; `0` = at once).
3. Even if a client misbehaves entirely, a battery camera is cut off after
   **5 minutes** of one continuous stream (changeable under **Configure →
   Maximum stream duration**); powered cameras are not capped.

Every open and close is written to the Home Assistant log
(`Live view of <serial> is streaming` / `… stopped` / `… hit its N s battery
limit`), so you can confirm in the log that the camera actually went back to
sleep.

---

## How SD-card playback works

The list comes from the cloud's SD index (`/v3/streaming/v2/records`, the
endpoint behind the app's playback timeline): at most 50 recordings per answer,
oldest first, so the integration pages forward through the day. Playback asks
the VTM relay — the same relay as the live view — to stream the chosen interval
from the SD card; the integration collects it as MPEG-PS, converts it with
ffmpeg to an MP4 with the index at the front, and serves it to the card from an
authenticated view that supports range requests (seeking).

The MP4 is kept under `media/ezviz_rtsp/<year>/<month>/<day>/`, so a second play
doesn't wake the camera again. The card reaches the file through a short-lived
signed path, handed out by the websocket command that prepared it.

The camera records **H.265/HEVC**. Safari (and the iOS/macOS Home Assistant
apps) and most Chrome and Edge builds on Windows and macOS play it as is; the
integration only repackages it as MP4. Firefox and browsers without HEVC get an
**H.264** copy that Home Assistant converts with ffmpeg — a few seconds of CPU
per clip on a Raspberry Pi 5.

The SD index is in the camera's local time; the integration reads it in Home
Assistant's time zone, so the two should match. A camera with video encryption
on needs its verification code under **Configure → Verification codes**, as for
the live view; the recording is decrypted with it.

### Cache and storage

The integration owns the cache, so the card never decides on its own whether to
touch the camera:

- **Today's list** is reused while it is under a minute old (a page reload
  included) and read from the camera only once that minute is over. Only **⟳**
  forces a read.
- A **finished past day** is stored in Home Assistant's `.storage`
  (`ezviz_rtsp.day_lists`) the first time it is read after it ended, so it is
  never read again — even after a restart — and an empty day is kept too. A day
  read only while it was still running is read once more after midnight, since
  its list could still have grown.
- **Switching days quickly** shares the read already on its way (also across
  cards) instead of queueing a camera session per tap, and a failed read is not
  cached, so the next attempt may reach the camera again. A read that was on its
  way when the view was closed is kept when it arrives.
- The calendar's **month dots** come from the cache and the media folder until
  **Check the SD card for this month** is pressed, which is the only part that
  asks the camera. A day opened with recordings is marked and the mark saved in
  `.storage` (`ezviz_rtsp.sd_days`), so its dot is back after a restart.
- A saved MP4's real duration is read from its `mvhd` box to spot a copy the
  camera cut short. A file clearly shorter than the interval in its name (more
  than about two and a half seconds, or 5% of a long clip, which covers the
  camera closing an event file a little early) is fetched again automatically;
  the verdict is remembered in `.storage`, so a restart does not fetch it again.
  The transfer window grows with the recording, so a long clip is not cut off
  while it is still arriving. The integration log
  (`custom_components.ezviz_rtsp.recordings`) says how many seconds it received
  and how many the index listed.

### Error codes and retries

- **2009** ("device network exception"): a sleeping camera often answers the
  first SD search or snapshot this way while it wakes. The integration asks
  once more after 5 seconds.
- **2004** (no recordings in the window): read as an empty day, not an SD-card
  failure.
- **5405** (another viewer, or a session the relay is still releasing): retried
  twice, two seconds apart, before the card reports that the camera refused to
  play the recording.

A camera serves **one cloud session at a time**, so the integration holds the
live start and the downloads on the same per-camera lock. A clip that had to
wait behind another download checks for a live view again once it gets its turn,
so it refuses with the same message instead of fighting a stream someone started
meanwhile.

### Websocket API

Two websocket commands carry the recordings view, for anyone building their own
UI:

| Command | Data | Returns |
|---|---|---|
| `ezviz_rtsp/recordings` | `serial`, optional `date` (`YYYY-MM-DD`, local; today by default), optional `refresh` | `date`, `today`, `complete`, and `recordings`: newest first, each with `begin`/`end` (UTC, `20261110T083702Z`), `start` (local ISO time) and `seconds` |
| `ezviz_rtsp/recording/clip` | `serial`, `begin`, `end`, optional `format` (`h264` default, or `hevc`) | `url`: a signed path to the MP4, valid for an hour; waits until the clip is ready |

---

## The bundled pyezvizapi

This integration needs a **2.x `pyezvizapi`** for SD-card playback over the
cloud relay, while Home Assistant's built-in EZVIZ integration pins 1.x. Home
Assistant installs every integration's Python requirements into one environment,
so it can hold only one version of a package — and a custom integration that
requires a version the built-in one rules out is exactly what hassfest flags:

```
[REQUIREMENTS] Requirement pyezvizapi==2.5.1 is incompatible with
pyezvizapi==1.0.5.0, which Home Assistant depends on.
```

To avoid that, this integration **ships its own copy** of `pyezvizapi` 2.5.1
inside `custom_components/ezviz_rtsp/pyezvizapi/` and imports it from there. It
does **not** list `pyezvizapi` in its `requirements`, so Home Assistant never
installs or replaces it, and this integration can run next to the built-in
EZVIZ integration — or any other integration that uses `pyezvizapi` — without a
version conflict.

The bundled copy is the upstream package **unchanged**, except that its internal
imports point at the bundled location (only the import lines are rewritten;
logger names, docstrings and thread names are left alone). Its own runtime
dependencies (`paho-mqtt`, `pycryptodome`, `tzdata`, `xmltodict`) are listed in
the manifest and installed normally; `requests` and `cryptography` come with
Home Assistant.

To update the library, run **`scripts/vendor_pyezvizapi.sh <version>`**: it
fetches that release from PyPI, drops it in, and rewrites its import root (pass
a path to an already-unpacked folder instead of a version to copy that). After
running it, review the diff, bump the version named in `CHANGELOG.md`, and run
`ruff check .` and the tests. The script reproduces the committed tree
byte-for-byte when run against the same release.
