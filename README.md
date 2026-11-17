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
does still works here. It lives under its own domain, `ezviz_rtsp`, so it sits
**next to** the built-in one instead of replacing it — you can keep both
installed, and no extra setup is needed for them to coexist.

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
camera by its serial (or `entity`).

A **filmstrip button next to the battery level** opens the camera's SD-card
recordings in the same card; see [Recordings on the SD card](#recordings-on-the-sd-card).

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
show_battery: true     # optional; false hides the battery level
hide_recordings: false # optional; hide the recordings button
format: auto           # optional; recordings format: auto, h264 or hevc
max_height: 360        # optional; height of the recordings list in pixels
save_recordings: true  # optional; false keeps watched clips out of media
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
| `show_battery` | `true` | Show the camera's charge next to the name, when the integration exposes it. `false` hides it. |
| `hide_recordings` | `false` | Hide the recordings button (and with it the SD-card view) from this card. |
| `format` | `auto` | The recording format the card asks for. `auto` asks for the camera's own **HEVC** when the browser says it can play it and for **H.264** otherwise; if HEVC then fails to play, it asks for H.264 once. `hevc` or `h264` force one. |
| `max_height` | `360` | Height of the scrolling recordings list, in pixels. |
| `save_recordings` | `true` | Keep the recordings you watch in the media folder. With `false`, a watched clip is fetched into a temporary folder, deleted after about two hours, and never appears under **Media**; one already saved earlier still plays from its permanent copy. |

All of these are also in the card's **visual editor**, grouped into **Camera**,
**Playback**, **Picture and snapshots**, **Buttons and battery** and
**Recordings** sections with your cameras listed. By default the card does
nothing until you press play: it shows the camera's **last alarm picture** with
a small Mushroom-style **play chip in the bottom-right corner**. Pressing it
starts the live view, which runs for `max_seconds`; a **Stop** chip in the same
corner ends it early. The **snapshot chip in the bottom-left** asks the camera
for a fresh picture at any time, idle or while a clip is playing, and shows a
spinner while it works. Hide any of the three with `hide_play`, `hide_stop` or
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
camera name, when the integration exposes it; `show_battery: false` hides it.
Directly to its left is the **filmstrip button**, which switches the card to the
camera's SD-card recordings (see
[Recordings on the SD card](#recordings-on-the-sd-card)); `hide_recordings:
true` removes it.

While the camera wakes, the card keeps its **last picture** on screen, so it
never looks blank. It waits up to 45 seconds for the first frame (a battery
camera over the cloud relay is not instant); `max_seconds` only starts counting
once the picture is on screen.

**A battery camera is never left streaming forever.** The card stops the stream
when `max_seconds` runs out; the integration releases the cloud session shortly
after the last viewer leaves (10 seconds by default); and even if a client
misbehaves entirely, a battery camera is cut off after 5 minutes of one
continuous stream. Both limits are configurable (see
[The settings worth knowing](#the-settings-worth-knowing)).

The **visual editor** lists your cameras and groups the options into **Camera**,
**Playback**, **Picture and snapshots**, **Buttons and battery** and
**Recordings** sections, so nothing above has to be typed by hand.

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
- **Snapshots** — whether the **EZVIZ Video** card's `capture_on_load` may take
  a new picture when it comes into view (*on by default*), and the minimum time
  between those automatic pictures for one camera, in seconds (default **300**;
  `0` takes one on every view), however many dashboards ask. Buttons, the card's
  snapshot chip and scripts that call `capture_picture` are not affected. See
  [Fresh pictures on demand](#fresh-pictures-on-demand).
- **Downloaded recordings** — how many days the recordings you have watched are
  kept, in days (default **7**; `0` keeps them until you delete them). The
  setting is per EZVIZ account. See
  [Recordings on the SD card](#recordings-on-the-sd-card).
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
answers the first request late while it wakes, so such a call can take a few
seconds longer.

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

The **EZVIZ Video** card's `capture_on_load` option asks for a fresh picture
each time the card comes into view:

```yaml
type: custom:ezviz-video-card
serial: BC1234567
capture_on_load: true     # optional, off by default; take a picture when the card comes into view
```

As with `auto_play`, this is **off by default**, so showing the card never wakes
a battery camera unless you ask it to. With `capture_on_load: true` it asks for
a new picture each time it comes into view: the dashboard view opens, or the
browser tab or app comes back to the front. These automatic requests follow
**Configure → Snapshots**:

- **Take a snapshot when a dashboard shows the camera** — on by default; turn it
  off and the card only shows the last picture (buttons and scripts calling
  `capture_picture` still work).
- **Minimum time between automatic snapshots** — 300 s by default, per camera,
  however many dashboards ask.

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
EZVIZ app away from home. The **EZVIZ Video** card has that list built in: press
the **filmstrip button next to the battery level** to switch it into the
recordings view, and press it again to go back to the live view. It lists one
day of a camera's recordings and plays the one you tap, right in the card.

- The **picture stays on screen** until a recording is picked: the camera's last
  motion picture or snapshot, exactly as the idle card shows it. Picking a
  recording plays it in the same media area, with the usual video controls and a
  **✕** in the corner to go back to the picture. The recording **stays** in the
  card until you pick another, close it or leave the mode.
- **Live video stops** as soon as the mode opens, and the camera is released at
  once rather than after the configured *Release the camera after* delay, so the
  first tap works immediately. The camera cannot stream and read its SD card at
  the same time, so this is what keeps playback from failing; going back to the
  live view starts the stream again when `auto_play` is on.
- The calendar, hour grouping and the ✕ player are the card's own; the
  recording format follows the browser (HEVC when it plays it, H.264
  otherwise), and a failed HEVC clip is retried in H.264. The `format` and
  `max_height` options are in the table above.

### Using it

- The card opens on **today**. The **calendar button** in the header opens a
  month grid: tap a day to see its recordings, and use the arrows inside the
  picker to go to another month. Future days cannot be picked. The refresh
  button searches the camera again.
- Recordings are listed **newest first, grouped by hour**, each with its start
  time and length. A camera that records motion events typically shows clips of
  8–16 seconds; a busy camera can have a few hundred a day. A day with nothing
  recorded yet — today just after midnight, for instance — simply says **"No
  recordings on this day"**.
- **Tap a recording to play it** in the card's player, with the usual video
  controls (pause, seek, full screen). Tap another to switch, or close the
  player with ✕. When it arrives the player replaces the progress bar in place:
  the list, the page and the row you clicked stay where they were. The picture
  box takes the recording's own shape (a 4:3 doorbell clip fills the card's
  width instead of showing black bands at the sides), and the live picture does
  the same. While the clip is on its way the card shows a **progress bar** with
  the seconds received out of the recording's length, followed by "Converting
  the recording…".
- **Tapping several recordings in a row** while one is still being fetched only
  remembers the newest: the ones in between are not downloaded, so the camera is
  not woken for clips you skipped. The waiting view says "Waiting for the
  current recording to finish…". A recording already saved in the media folder
  still plays at once, without waiting for that download to finish.
- **A recording already saved in the media folder is never fetched again** —
  unless its file is clearly shorter than the interval in its name, which means
  the download was cut off; then the card fetches it once more. It otherwise
  plays straight from `media/ezviz_rtsp/`, without waking the camera. An
  **H.264** copy also answers a request for HEVC, since H.264 plays in every
  browser.
- **The calendar marks the days that have a recording.** A **green dot** means
  clips from that day are already saved in the media folder — those days are
  known without touching the camera and survive every restart. Days with
  recordings only on the camera's SD card get a **blue dot**. Opening such a day
  marks it, and the mark survives a restart too. To see a whole month's dots
  without opening each day, press **Check the SD card for this month** in the
  picker; it searches each day of that month once, shows progress, and remembers
  the result across restarts. A scan that runs out of time keeps the days it
  found and can be run again. The camera is never asked about a month just by
  opening the picker.
- At the right of each row, a small icon says where the clip is: a **cloud** for
  one that still has to be fetched from the camera, a green **check** for one
  already saved under `media/ezviz_rtsp/` (in either format), and an orange
  **alert cloud** for a saved copy that is shorter than its interval and will be
  replaced on the next play.
- **Live waits for a download that is still running.** Pressing live (or opening
  a card with auto-play) while a recording is coming off the card first says
  **"Waiting for the download to finish…"** and only then **"Waking the
  camera…"**. The download is not cancelled: it completes and is saved, and the
  stream starts as soon as the camera is free.
- **Watching a clip saves it by default.** Turn **Save watched recordings**
  (`save_recordings: false`) off in the card's settings to keep the media folder
  clean: a watched recording is then fetched into a temporary folder, plays the
  same, is deleted after about two hours and never appears under **Media**. It
  does not get a green check, and the retention setting does not apply to it.
- **Opening the view does not force a read from the camera; only ⟳ does.**
  Today's list is reused while it is under a minute old, and a finished past day
  is remembered so it is never read again — even after a restart. Switching days
  quickly shares one read instead of queueing a camera session per tap.

### Getting the latest recording on demand

Just like a fresh picture, the newest recording can be fetched without opening
the card. Call the **`ezviz_rtsp.download_recording`** service on a camera:

```yaml
action: ezviz_rtsp.download_recording
target:
  entity_id: camera.driveway_gate
data:
  format: h264          # optional; h264 (default) or hevc
```

It finds the newest recording of **today** (or **yesterday**, when the camera
has not recorded anything yet today), downloads it through the EZVIZ cloud and
saves it as an MP4 under `media/ezviz_rtsp/<year>/<month>/<day>/` — the same
place the card keeps its clips, so the retention setting applies. The camera is
woken, so expect the same 15–30 seconds as playing a recording in the card, and
the same "one viewer at a time" rule (stop the live view first).

Every camera also gets a **Download latest recording** button in its
**Controls** section, so it can be pressed by hand. Both the service and the
button update the camera's **Latest recording** sensor
(`sensor.<camera>_latest_recording`): its state is the recording's start time and
its attributes carry the file path, the interval and the format. The sensor is
kept in memory, so it is empty again after a restart until the next download.

| Service data | Default | What it does |
|---|---|---|
| `format` | `h264` | `h264` is converted by Home Assistant and plays in every browser and player; `hevc` keeps the camera's own stream and is only repackaged, so it is quicker but plays on fewer players. |

Ask for a response when you want the file, for example to send it or hand it to
another tool:

```yaml
actions:
  - action: ezviz_rtsp.download_recording
    target:
      entity_id: camera.driveway_gate
    response_variable: clip
  - action: notify.mobile_app_phone
    data:
      message: "Latest recording at the driveway gate"
      data:
        video: "{{ clip.path }}"
```

The response carries `serial`, `begin`/`end` (UTC), `start` (local time),
`seconds`, `format` and `path` (the file's path on the Home Assistant host). The
recording is also readable from the **Media** browser under `ezviz_rtsp`.

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
- **Where the clips go.** A fetched recording is saved as an MP4 under Home
  Assistant's **media** folder, filed by the day it was recorded:
  `media/ezviz_rtsp/<year>/<month>/<day>/`, using Home Assistant's local time.
  Seeking and playing it again don't touch the camera, and the files survive a
  restart. Browse and download them from **Media → My media → ezviz_rtsp**,
  where the years, months and days are the folders.
- **How long they stay.** Under **Configure → Downloaded recordings** you choose
  how many days those MP4s are kept (default **7**); older files are deleted,
  the rest left alone. `0` keeps them until you delete them yourself. **The
  setting is per account:** each EZVIZ account has its own value, and a clip is
  swept by the setting of the account its camera belongs to, so two accounts can
  keep their recordings for different lengths. The folder is swept at start-up,
  once a day while Home Assistant runs, and whenever a new clip is downloaded;
  day folders left empty are removed. Clips saved flat by an older version are
  moved into their day folders on the next start.
- **Format.** The camera records **H.265/HEVC**. Safari (and the iOS/macOS
  Home Assistant apps) and most Chrome and Edge builds on Windows and macOS play
  it as is; Firefox and browsers without HEVC get an **H.264** copy that Home
  Assistant converts with ffmpeg.
- **One viewer at a time.** EZVIZ serves one cloud session per camera. Stop
  the camera's live view before playing a recording (the card says so if you
  don't). A camera that is busy is retried a couple of times before the card
  reports that it refused to play; if it still fails, close the EZVIZ app or the
  other live view.
- **Time zone.** The SD index is in the camera's local time. The integration
  reads it in Home Assistant's time zone, so the two should match.
- **Encrypted cameras.** A camera with video encryption on needs its
  verification code under **Configure → Verification codes**, as for the live
  view; the recording is decrypted with it.

---

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
<summary>The recordings view says the camera did not answer in time</summary>

The camera was asleep and didn't answer the SD search; the integration already
asked twice. Press refresh — it is usually awake by then.

</details>

<details>
<summary>A recording is shorter than the length shown next to it</summary>

The length in the list comes from the camera's SD index. A file saved by an
older version may have been cut off by the fixed transfer window: the card reads
the MP4's real duration, and if it is clearly shorter than the interval it
fetches the recording again automatically. A clip the camera itself sends short
is kept as it is, and that verdict is remembered across restarts. Such a row
shows an orange alert cloud, and while it is fetched again the card says **"The
saved recording is incomplete — downloading it again…"**.

</details>

<details>
<summary>A recording won't play</summary>

"The camera refused to play the recording" means another session still has the
camera — its live view in Home Assistant or the EZVIZ app. The integration
already retries a couple of times; if it still fails, stop that session and tap
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
- **On-demand snapshots** — the `capture_picture` service, the Snapshot image
  and the Snapshots options — were contributed by
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

## For developers

How the live and playback streams are built, the websocket API, the cache and
storage keys, the EZVIZ error codes it retries, and how the bundled `pyezvizapi`
is refreshed: see **[docs/TECHNICAL.md](docs/TECHNICAL.md)**.

---

## Support

If this project saved you some time, you can buy me a coffee — it keeps the
battery cameras streaming.

<p><a href="https://ko-fi.com/tarasifua"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Buy Me a Coffee at ko-fi.com" width="320" height="43"></a></p>

[ko-fi.com/tarasifua](https://ko-fi.com/tarasifua)
