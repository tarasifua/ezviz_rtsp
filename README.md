# Ezviz Cloud with Video

*Live picture from EZVIZ cameras that don't want to give you one — battery
doorbells, peepholes and other sleepy devices.*

![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-2f6f4e)
![Home Assistant 2026.10+](https://img.shields.io/badge/Home_Assistant-2026.10%2B-3d7ff2)
[![Marketplace validation](https://github.com/tarasifua/ezviz_rtsp/actions/workflows/validate.yml/badge.svg)](https://github.com/tarasifua/ezviz_rtsp/actions/workflows/validate.yml)
[![Hassfest](https://github.com/tarasifua/ezviz_rtsp/actions/workflows/hassfest.yml/badge.svg)](https://github.com/tarasifua/ezviz_rtsp/actions/workflows/hassfest.yml)

Licensed under **[Apache-2.0](LICENSE)**. Requires **Home Assistant 2026.10 or newer**.
See the [changelog](CHANGELOG.md) for what's new.

---

## The short version

If you have an EZVIZ battery camera or peephole, you already know the routine:
it works in the EZVIZ app, but Home Assistant shows you nothing. That's not a
bug you can fix with a setting — those devices sleep and never open an RTSP
port, so the local-address approach every Home Assistant integration uses has
nothing to talk to.

This integration talks to them the way the phone app does when you're on
mobile data. It asks EZVIZ's cloud to wake the camera, pulls the stream down,
and hands it to Home Assistant as a normal camera. You get a live view, a
built-in Lovelace card, and the camera stays awake only while you're actually
looking at it. When a still is enough, it can also have the camera take a
fresh picture on demand, or whenever a dashboard shows it (see
[Fresh pictures on demand](#fresh-pictures-on-demand)).
With an SD card in the camera, it can also list and play back the camera's
recordings (see [Recordings on the SD card](#recordings-on-the-sd-card)).

It is a fork of the **built-in** EZVIZ integration, so everything that one
does still works here. It lives under its own domain, `ezviz_rtsp`, which means
it sits **next to** the built-in one instead of replacing it.

---

## Put it in Marketplace

[![Open Marketplace repository in Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tarasifua&repository=ezviz_rtsp&category=integration)

Or add it by hand:

1. Open **Marketplace**.
2. Top-right menu (**⋮**) → **Custom repositories**.
3. Repository: `https://github.com/tarasifua/ezviz_rtsp` — Category: **Integration**.
4. Find **Ezviz Cloud with Video** in the list, install it, restart Home Assistant.

<details>
<summary>Bleeding edge (the <code>main</code> branch)</summary>

Releases are the stable channel. To always run the latest committed changes,
open the integration in Marketplace → **⋮ → Redownload** and pick **`main`** (the
default branch) instead of a release. Marketplace then offers an update every time the
branch moves — no release needed. Switch back to a release the same way.

</details>

<details>
<summary>No Marketplace? Copy the folder</summary>

Drop `custom_components/ezviz_rtsp/` into `config/custom_components/ezviz_rtsp/`
on your Home Assistant machine (Samba, SSH, or the *File editor* add-on on
HAOS), then restart.

</details>

---

## First run

Add the integration and sign in with the EZVIZ account from your phone:

[![Start setting up Ezviz Cloud with Video](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ezviz_rtsp)

Pick your region, type the e-mail/phone and password, and — if your account has
two-step verification on — the code EZVIZ sends you. That's it. Your battery
cameras appear as normal camera entities and start showing video.

The account session is stored in the config entry and renewed quietly in the
background, so a restart doesn't make you log in again.

Each camera also gets a **Snapshot** image entity
(`image.<camera>_snapshot`), updated whenever a fresh picture is taken, and a
**Request snapshot** button in its **Controls** section
(`button.<camera>_request_snapshot`). See
[Fresh pictures on demand](#fresh-pictures-on-demand).

---

## The card that comes with it

The integration serves its own Lovelace card, so there's no resource to add:
just pick **EZVIZ Video** in the card picker or paste the YAML. It is styled
after **Mushroom cards** — a rounded card, an icon tile, a status line and
small **play/stop chips in the bottom-right corner** of the picture, plus a
**snapshot chip** in the bottom-left that wakes the camera for a fresh picture —
but it needs neither Mushroom nor any other frontend add-on. The card finds a
camera by its serial (or `entity`) and plays the integration's **own fast
picture stream**, falling back to Home Assistant's stream only for a camera the
integration does not stream itself.

A second card, **EZVIZ Snapshot**, shows still pictures instead of video and
can take a new one each time it comes into view; see
[A snapshot whenever the dashboard is opened](#a-snapshot-whenever-the-dashboard-is-opened).
A third, **EZVIZ Recordings**, lists a camera's SD-card recordings by day and
plays the one you tap; see [Recordings on the SD card](#recordings-on-the-sd-card).

```yaml
type: custom:ezviz-video-card
serial: BC1234567
title: Front door      # optional; defaults to the camera's name
icon: mdi:doorbell     # optional
auto_play: false       # optional; off by default — the card waits for a tap
max_seconds: 60        # optional; stop the stream to protect the battery (0 = never)
capture_on_load: false # optional; ask for a fresh snapshot when the card opens
picture: motion        # optional; idle picture: motion, snapshot or newest
hide_play: false       # optional; hide the play chip
hide_stop: false       # optional; hide the stop chip
hide_snapshot: false   # optional; hide the snapshot chip
show_timestamp: false  # optional; show the picture's date and time
```

| Option | Default | What it does |
|---|---|---|
| `serial` | — | The device serial (on the label or in the EZVIZ app). The visual editor lists your cameras. |
| `entity` | — | Use a camera entity directly instead of looking one up by serial. |
| `title` | camera name | The heading in the card. |
| `icon` | `mdi:video` | The icon in the tile. |
| `auto_play` | `false` | Start a clip as soon as the card is on screen. Off (the default) shows the camera's last picture and waits for a tap, so opening a dashboard never wakes a battery camera. A clip stops as soon as the card leaves the screen. |
| `max_seconds` | `60` | How long a clip runs before it is stopped automatically, counted **from the first frame** (a battery camera can take a while to wake). `0` never stops it on its own, but leaving the card still does. |
| `capture_on_load` | `false` | Ask for a fresh snapshot each time the card opens (the dashboard view opens, or the tab/app returns). Off by default, so the card never wakes a battery camera on its own; it follows **Configure → Snapshots** for whether automatic captures may run and how often. |
| `picture` | `motion` | What the card shows while no clip is playing: `motion` (the camera's last alarm picture), `snapshot` (the last picture taken by `capture_picture`; **if no snapshots are available it shows the previous motion frame**), or `newest` (compares both frames and shows the newest one). |
| `hide_play` | `false` | Hide the play chip while a clip is not running. |
| `hide_stop` | `false` | Hide the stop chip while a clip is playing. |
| `hide_snapshot` | `false` | Hide the card's snapshot chip. |
| `show_timestamp` | `false` | Show the date and time of the picture currently on the card (the motion or snapshot image, whichever `picture` selects) in the top-right corner. It disappears while a clip is playing. |

All of these are also in the card's **visual editor**, which lists your cameras
and exposes the picture and button options. By default the card does nothing
until you press play: it shows the camera's **last alarm picture** with a small
Mushroom-style **play chip in the bottom-right corner**. Pressing it starts the
live view, which runs for `max_seconds`; a **Stop** chip in the same corner ends
it early. The **snapshot chip in the bottom-left** asks the camera for a fresh
picture at any time, idle or while a clip is playing, and shows a spinner while
it works. Hide any of the three with `hide_play`, `hide_stop` or
`hide_snapshot`. When `max_seconds` runs out the card quietly returns to the
last picture — press play again to watch another clip; nothing has to be
reloaded.

With **`show_timestamp: true`** the card also puts the date and time of the
still in the top-right corner — when the motion picture or snapshot was taken,
matching whatever `picture` currently shows. It is **off by default**, vanishes
as soon as a clip starts and returns with the last picture when the clip stops.
Turn it on in the visual editor or with the option above.

**Leaving the card stops the stream.** Switching to another dashboard view,
hiding the browser tab, or scrolling the card out of sight all stop it for good,
so a battery camera is never left streaming behind another view; come back and
you get the last picture with the play chip. With `auto_play: true` the card
instead starts a clip by itself when it appears. An idle card never wakes the
camera.

A **battery camera's charge** is shown in the top-right corner, opposite the
camera name, when the integration exposes it.

The card shows the picture through the integration's **own fast picture stream**
(a live MJPEG) so it appears a few seconds after the camera wakes, rather than
waiting for Home Assistant's HLS to build segments. It falls back to HLS for a
camera the integration does not stream itself. While the camera wakes, the card
keeps its **last picture** on screen, so it never looks blank. The picture is
served from an **authenticated** view and the card reads it through a short-lived
**signed URL**, so a link that leaks (or a user you later remove) cannot keep
watching. **hls.js is bundled with the integration** and served from its own
path — the card loads no code from a public CDN.

The card waits up to 45 seconds for the camera to wake and send its first frame
(a battery camera over the cloud relay is not instant); `max_seconds` only starts
counting once the picture is on screen.

**A battery camera can never be left streaming forever.** Any one of these ends
it:

1. The **card** stops the stream when `max_seconds` runs out, and releases the
   reader.
2. The **integration** closes the cloud session shortly after the last reader
   leaves — **10 seconds** by default (changeable under **Configure → Release the
   camera after**; `0` = at once).
3. Even if a client misbehaves entirely, a battery camera is cut off after
   **5 minutes** of one continuous stream (changeable under **Configure →
   Maximum stream duration**); powered cameras are not capped.

Every open and close is written to the Home Assistant log
(`Live view of <serial> is streaming` / `… stopped` / `… hit its N s battery
limit`), so you can confirm in the log that the camera actually went back to
sleep.

The **visual editor** lists your cameras, the idle picture and the three button
toggles, so nothing above has to be typed by hand.

---

## The settings worth knowing

Everything below lives under **Configure** on the integration:

- **Video transcoding** — *on by default.* EZVIZ sends H.265, which most
  desktop browsers refuse to decode; this re-encodes Home Assistant's own stream
  — and the MPEG-TS address other apps read — to H.264 so it just plays. If your
  browser or phone already handles H.265, turn it off to save CPU. The bundled
  card shows its own MJPEG and never needs this.
- **Verification codes** — only matters for cameras with *video encryption*
  enabled. Type the six-letter code from the camera's label; it decrypts the
  stream inside Home Assistant and is never sent to a browser.
- **Maximum stream duration** — how long one battery-camera live stream may run
  before the integration stops it, in seconds (default **300**; `0` removes the
  cap). This is the safety net that keeps a battery camera from being left
  streaming, whatever a client does.
- **Release the camera after** — how long the cloud stream is held open after the
  last viewer leaves, in seconds (default **10**; `0` releases it at once). A
  short hold means a quick re-play does not wake the camera again.
- **Snapshots** — whether the **EZVIZ Snapshot** card and the **EZVIZ Video**
  card's `capture_on_load` may take a new picture when they come into view (*on
  by default*), and the minimum time between those automatic pictures for one
  camera, in seconds (default **300**; `0` takes one on every view), however many
  dashboards ask. Buttons, the card's snapshot chip and scripts that call
  `capture_picture` are not affected. See
  [Fresh pictures on demand](#fresh-pictures-on-demand).
- **General** — request timeout and the ffmpeg arguments for cameras you added
  over local RTSP.
- **Stream address for other apps** — see below.

---

## Fresh pictures on demand

By default the picture shown on a dashboard is the camera's last **alarm**
picture, so a battery camera is never woken just to draw it (the card's
`picture` option can show the last snapshot or whichever is newer instead).
When you want a picture from *now*, call the
**`ezviz_rtsp.capture_picture`** service on a camera:

```yaml
action: ezviz_rtsp.capture_picture
target:
  entity_id: camera.driveway_gate
```

The cloud wakes the camera and it takes a full-resolution picture (a few seconds
on a battery camera; no RTSP needed). It appears in the camera's **Snapshot**
image entity (`image.<camera>_snapshot`), and the service returns its
`picture_url` if you ask for a response. Every camera also gets a **Request
snapshot** button in its **Controls** section, so you can take a picture with
one press without writing a service call. Each call wakes the camera, so use it
on demand rather than on a timer. The snapshot is kept in memory, so it is
empty again after a restart until the next capture. A sleeping camera often
answers the first request with EZVIZ error 2009 ("device network exception")
while it wakes; the service then tries once more after 5 seconds, so such a
call can take a few seconds longer.

| Service data | Default | What it does |
|---|---|---|
| `min_interval` | — | Skip the capture when this camera took a picture less than that many seconds ago; the call then returns the last picture with `skipped: true`. |
| `automatic` | `false` | Marks the call as made by a card rather than a person: it follows **Configure → Snapshots** and uses the configured interval when `min_interval` is left out. |

The throttle is kept per camera in Home Assistant and is shared by the service,
the **Request snapshot** button and the cards, so it holds however many
dashboards or automations ask. A response looks like
`{"picture_url": "https://…", "skipped": false}`; in a script, ask for it with
`response_variable`.

### A snapshot whenever the dashboard is opened

The integration also ships an **EZVIZ Snapshot** card:

```yaml
type: custom:ezviz-snapshot-card
entity: camera.driveway_gate
image: image.driveway_gate_snapshot  # optional; found automatically when left out
title: Driveway gate      # optional
capture_on_load: true     # optional, off by default; take a picture when the card comes into view
min_interval: 600         # optional; overrides Configure → Snapshots for this card
```

| Option | Default | What it does |
|---|---|---|
| `entity` | — | The camera entity to watch (required). |
| `image` | found automatically | The Snapshot image entity to show. Normally resolved from the camera's device; set it only if you want a specific one. |
| `title` | camera name | The heading in the card. |
| `capture_on_load` | `false` | Ask for a new picture each time the card comes into view. |
| `min_interval` | Configure → Snapshots value | Override the minimum time between automatic pictures for this card. |

It shows the camera's Snapshot image. As with the video card's `auto_play` and
`capture_on_load`, this is **off by default**, so showing the card never wakes a
battery camera unless you ask it to. With `capture_on_load: true` it asks for a
new picture each time it comes into view: the dashboard view opens, or the
browser tab or app comes back to the front. The **EZVIZ Video** card has the
same option (see the table above). These automatic requests follow
**Configure → Snapshots**:

- **Take a snapshot when a dashboard shows the camera** — on by default; turn it
  off and the cards only show the last picture (buttons and scripts calling
  `capture_picture` still work).
- **Minimum time between automatic snapshots** — 300 s by default, per camera,
  however many dashboards ask. A card can override it with `min_interval`.

### In automations and scripts

`capture_picture` is a normal action, so any trigger can request a picture:

```yaml
actions:
  - action: ezviz_rtsp.capture_picture
    target:
      entity_id: camera.driveway_gate
```

Ask for a response when you want the picture URL — for example, to send it in a
notification:

```yaml
actions:
  - action: ezviz_rtsp.capture_picture
    target:
      entity_id: camera.driveway_gate
    response_variable: shot
  - action: notify.mobile_app_phone
    data:
      message: "Movement at the driveway gate"
      data:
        image: "{{ shot.picture_url }}"
```

`shot.skipped` is `true` when `min_interval` returned the previous picture
instead of waking the camera. `picture_url` is EZVIZ's own link to the captured
frame; the **Snapshot** image entity (`image.<camera>_snapshot`) is the picture
Home Assistant shows and decrypts locally when the camera uses video encryption.
The camera's **Request snapshot** button can be pressed from an automation too,
without writing a service call:

```yaml
actions:
  - action: button.press
    target:
      entity_id: button.driveway_gate_request_snapshot
```

Do **not** set `automatic: true` in automations: that flag is for the cards and
makes the call follow **Configure → Snapshots**. An ordinary call always takes a
picture. Add `min_interval` when a busy trigger (a motion sensor firing often)
should not wake the camera every time:

```yaml
actions:
  - action: ezviz_rtsp.capture_picture
    target:
      entity_id: camera.driveway_gate
    data:
      min_interval: 120
```

Every `capture_picture` wakes a battery camera, so keep the interval long enough
for the battery.

---

## Recordings on the SD card

A camera with a microSD card keeps its recordings there, and the EZVIZ cloud can
both **list** them and **replay** them — the same way playback works in the
EZVIZ app away from home. The **EZVIZ Recordings** card brings that into Home
Assistant: it lists one day of a camera's recordings and plays the one you tap,
right in the card.

```yaml
type: custom:ezviz-recordings-card
entity: camera.driveway_gate   # or serial: BB1234567
title: Driveway gate           # optional; defaults to "<camera> recordings"
format: auto                   # optional; auto, h264 or hevc
max_height: 360                # optional; height of the list in pixels
```

| Option | Default | What it does |
|---|---|---|
| `entity` | — | The camera entity. Either this or `serial` is required. |
| `serial` | — | The device serial instead of an entity. |
| `title` | "*camera* recordings" | The heading in the card. |
| `format` | `auto` | The video format the card asks for. `auto` asks for the camera's own **HEVC** when the browser says it can play it and for **H.264** otherwise; if HEVC then fails to play, it asks for H.264 once. `hevc` or `h264` force one. |
| `max_height` | `360` | Height of the scrolling list, in pixels. |

### Using it

- The card opens on **today**. The arrows in the header go to earlier days (and
  back, up to today); the refresh button searches the camera again.
- Recordings are listed **newest first, grouped by hour**, each with its start
  time and length. A camera that records motion events typically shows clips of
  8–16 seconds; a busy camera can have a few hundred a day.
- **Tap a recording to play it** in the card's player, with the usual video
  controls (pause, seek, full screen). Tap another to switch, or close the
  player with ✕. The card shows "Fetching the recording from the camera…"
  while the clip is on its way.
- The list is read the first time the card is on screen, not when a dashboard
  merely contains it; a card that leaves the screen pauses its player.

### What it costs, and what to expect

- **Battery.** Both listing and playing go through the camera itself: the SD
  card is in the camera, and the cloud only relays. A sleeping battery camera
  is woken for each (listing a day is a few seconds of work, playing a
  recording about as much as opening the live view), which is why nothing
  happens until the card is on screen or a recording is tapped.
- **Speed.** Listing a day takes 3–12 seconds (the index answers 50 recordings
  at a time). A sleeping camera may not answer its first search in time; the
  integration asks once more after 5 seconds. A short clip takes about
  **15–30 seconds** to arrive — most of it the camera waking up, then a few
  seconds of conversion.
- **Caching.** A fetched recording is kept in Home Assistant (the last 16, as
  MP4 files in a private temporary folder that is removed when the integration
  unloads), so seeking and playing it again don't touch the camera. A past
  day's list is kept until you press refresh; today's for a minute.
- **Format.** The camera records **H.265/HEVC**. Safari (and the iOS/macOS
  Home Assistant apps) and most Chrome and Edge builds on Windows and macOS play
  it as is; the integration only repackages it as MP4. Firefox and browsers
  without HEVC get an **H.264** copy that Home Assistant converts with ffmpeg —
  a few seconds of CPU per clip on a Raspberry Pi 5.
- **One viewer at a time.** EZVIZ serves one cloud session per camera. Stop
  the camera's live view before playing a recording (the card says so if you
  don't), and expect "The camera refused to play the recording" when the
  EZVIZ app is watching the same camera.
- **Time zone.** The SD index is in the camera's local time. The integration
  reads it in Home Assistant's time zone, so the two should match.
- **Encrypted cameras.** A camera with video encryption on needs its
  verification code under **Configure → Verification codes**, as for the live
  view; the recording is decrypted with it.

### How it works

The list comes from the cloud's SD index (`/v3/streaming/v2/records`, the
endpoint behind the app's playback timeline): at most 50 recordings per
answer, oldest first, so the integration pages forward through the day.
Playback asks the VTM relay — the same relay as the live view — to stream the
chosen interval from the SD card; the integration collects it as MPEG-PS,
converts it with ffmpeg to an MP4 with the index at the front, and serves it to
the card from an authenticated view that supports range requests (seeking).
The card reaches the file through a short-lived signed path, handed out by the
websocket command that prepared it.

Two websocket commands carry it, for anyone building their own UI:

| Command | Data | Returns |
|---|---|---|
| `ezviz_rtsp/recordings` | `serial`, optional `date` (`YYYY-MM-DD`, local; today by default), optional `refresh` | `date`, `today`, `complete`, and `recordings`: newest first, each with `begin`/`end` (UTC, `20261110T083702Z`), `start` (local ISO time) and `seconds` |
| `ezviz_rtsp/recording/clip` | `serial`, `begin`, `end`, optional `format` (`h264` default, or `hevc`) | `url`: a signed path to the MP4, valid for an hour; waits until the clip is ready |

Recordings need **pyezvizapi 2.0.0**, the first release with SD playback over
the cloud relay; see the [changelog](CHANGELOG.md).

## Feeding other apps (Frigate, go2rtc, …)

Once you allow it (see below), every camera can be read by other apps as plain
MPEG-TS from a local, token-guarded address:

```
http://<your-ha>:8123/api/ezviz_rtsp/live/<serial>?token=<stream token>
```

The token is generated once and kept across restarts. **Configure → Stream
address for other apps** lists the exact addresses of every camera (both the
MPEG-TS and the MJPEG one), can hand out a **new token** (links shared before
then stop working), and has an **Allow other apps to read the stream** switch —
**off by default**: turn it on to let go2rtc, Frigate and friends read these
addresses. The bundled card keeps working either way, because it uses its own
authenticated picture view. Reading an address wakes the camera, so treat it
like a doorbell:
switch it on for a moment, then let it close.

The same token serves a **live MJPEG picture** too — handy for a plain `<img>` or
a dashboard that wants a small, low-latency view (the bundled card uses its own
authenticated picture view instead):

```
http://<your-ha>:8123/api/ezviz_rtsp/mjpeg/<serial>?token=<stream token>
```

---

## Under the hood

A quick sketch, for the curious:

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

---

## Cameras confirmed working

There is no per-model promise. This uses the same cloud path the EZVIZ app
uses, so **it should work with any camera the app can show** — battery cameras,
peepholes, and cameras with video encryption on. A camera that plays in the app
is expected to play here, but only testing will tell.

These two models have been tested end to end:

| Model | What it is | What was checked |
|---|---|---|
| **DP2** | battery video doorbell | Live view at **2048×1296** (H.265 + AAC) through the cloud relay. Verified by the maintainer while building this. |
| **CB3** | battery camera with solar panel | Live view at **1920×1080** through the cloud relay, and on-demand snapshots (`capture_picture`, 1920×1080) in about **2–5 s**. Tested by **[Riaz Shaik (@riazshaikgp)](https://github.com/riazshaikgp)** on a setup with **eight CB3s**. See [PR #1](https://github.com/tarasifua/ezviz_rtsp/pull/1). |

If you try another model, an issue with the result is welcome.

---

## If something doesn't play

<details>
<summary>The card / camera stays black</summary>

Transcoding is on by default — if you turned it off, switch it back on, or use
a browser/phone that decodes H.265. Check the log for a line like
`Live view of <serial> could not start: …`; that means the camera didn't answer
the cloud (most often it's asleep or was just streaming).

</details>

<details>
<summary>The dashboard shows a still, not video</summary>

A cloud camera's thumbnail is its **last alarm picture**, on purpose — drawing a
camera on a dashboard must not drain its battery. Tap it to open the live view.

</details>

<details>
<summary>“EZVIZ rejected the account or password”</summary>

Double-check the e-mail/phone, the password, and the **region** your account
belongs to.

</details>

<details>
<summary>A stored code garbles the picture</summary>

A verification code is only applied to cameras that actually encrypt video.
Re-check it under **Configure → Verification codes**.

</details>

<details>
<summary>The recordings card says the camera did not answer in time</summary>

The camera was asleep and didn't answer the SD search (EZVIZ error 2009); the
integration already asked twice. Press refresh — it is usually awake by then.

</details>

<details>
<summary>The recordings card reports a problem reading the SD card</summary>

EZVIZ answered the search with a device exception (error 2004). Check the
camera's storage in the EZVIZ app: the card may need formatting, or replacing.

</details>

<details>
<summary>A recording won't play</summary>

"The camera refused to play the recording" means another session has the
camera — its live view in Home Assistant or the EZVIZ app. Stop that and tap
again. If an HEVC recording stays black, set `format: h264` on the card.

</details>

---

## Credits

This project would not exist without two upstream works; their notices are in
[`NOTICE`](NOTICE).

- **The EZVIZ integration in Home Assistant Core** — the foundation this is
  forked from. Written and maintained by
  **[RenierM26](https://github.com/RenierM26)** and the Home Assistant
  contributors, under Apache-2.0.
- **[ezviz-cloud-hass](https://github.com/bvis/ezviz-cloud-hass)** — the
  cloud (VTM) live-view idea and code that this draws on. By
  **[Basilio Vera (@bvis)](https://github.com/bvis)**, under MIT.
- The **`capture_picture` service and Snapshot image** follow
  [RenierM26/ha-ezviz#235](https://github.com/RenierM26/ha-ezviz/pull/235) by
  **[Michael Freund (@ottes)](https://github.com/ottes)**.
- **On-demand snapshots** — the `capture_picture` service, the Snapshot image,
  the EZVIZ Snapshot card and the Snapshots options — were contributed by
  **[Riaz Shaik (@riazshaikgp)](https://github.com/riazshaikgp)** in
  [tarasifua/ezviz_rtsp#1](https://github.com/tarasifua/ezviz_rtsp/pull/1).
- Brand icon: the EZVIZ brand image from
  [home-assistant/brands](https://github.com/home-assistant/brands), with a
  small "video" badge.

Licensed under **[Apache-2.0](LICENSE)**, with the MIT-licensed parts attributed
in [`NOTICE`](NOTICE).

EZVIZ is a trademark of its owner. This is an independent, unofficial project
with no affiliation to or endorsement from EZVIZ.

---

## Support

If this project saved you some time, you can buy me a coffee — it keeps the
battery cameras streaming.

<p><a href="https://ko-fi.com/tarasifua"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Buy Me a Coffee at ko-fi.com" width="320" height="43"></a></p>

[ko-fi.com/tarasifua](https://ko-fi.com/tarasifua)
