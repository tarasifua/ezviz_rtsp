# Ezviz Cloud with Video

*Live picture from EZVIZ cameras that don't want to give you one — battery
doorbells, peepholes and other sleepy devices.*

![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-2f6f4e)
![Home Assistant 2026.10+](https://img.shields.io/badge/Home_Assistant-2026.10%2B-3d7ff2)
[![HACS validation](https://github.com/tarasifua/ezviz_rtsp/actions/workflows/validate.yml/badge.svg)](https://github.com/tarasifua/ezviz_rtsp/actions/workflows/validate.yml)
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

It is a fork of the **built-in** EZVIZ integration, so everything that one
does still works here. It lives under its own domain, `ezviz_rtsp`, which means
it sits **next to** the built-in one instead of replacing it.

---

## Put it in HACS

[![Open HACS repository in Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tarasifua&repository=ezviz_rtsp&category=integration)

Or add it by hand:

1. Open **HACS**.
2. Top-right menu (**⋮**) → **Custom repositories**.
3. Repository: `https://github.com/tarasifua/ezviz_rtsp` — Category: **Integration**.
4. Find **Ezviz Cloud with Video** in the list, install it, restart Home Assistant.

<details>
<summary>Bleeding edge (the <code>main</code> branch)</summary>

Releases are the stable channel. To always run the latest committed changes,
open the integration in HACS → **⋮ → Redownload** and pick **`main`** (the
default branch) instead of a release. HACS then offers an update every time the
branch moves — no release needed. Switch back to a release the same way.

</details>

<details>
<summary>No HACS? Copy the folder</summary>

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

---

## The card that comes with it

The integration serves its own Lovelace card, so there's no resource to add:
just pick **EZVIZ Video** in the card picker or paste the YAML. It is styled
after **Mushroom cards** — a rounded card, an icon tile, a status line and a
small **play/stop chip in the bottom-right corner** of the picture — but it needs
neither Mushroom nor any other frontend add-on. The card finds a camera by its
serial (or `entity`) and plays the integration's **own fast picture stream**,
falling back to Home Assistant's stream only for a camera the integration does
not stream itself.

A second card, **EZVIZ Snapshot**, shows still pictures instead of video and
can take a new one each time it comes into view; see
[A snapshot whenever the dashboard is opened](#a-snapshot-whenever-the-dashboard-is-opened).

```yaml
type: custom:ezviz-video-card
serial: BC1234567
title: Front door      # optional; defaults to the camera's name
icon: mdi:doorbell     # optional
auto_play: false       # optional; off by default — the card waits for a tap
max_seconds: 60        # optional; stop the stream to protect the battery (0 = never)
```

| Option | Default | What it does |
|---|---|---|
| `serial` | — | The device serial (on the label or in the EZVIZ app). The visual editor lists your cameras. |
| `entity` | — | Use a camera entity directly instead of looking one up by serial. |
| `title` | camera name | The heading in the card. |
| `icon` | `mdi:video` | The icon in the tile. |
| `auto_play` | `false` | Start a clip as soon as the card is on screen. Off (the default) shows the camera's last picture and waits for a tap, so opening a dashboard never wakes a battery camera. A clip stops as soon as the card leaves the screen. |
| `max_seconds` | `60` | How long a clip runs before it is stopped automatically, counted **from the first frame** (a battery camera can take a while to wake). `0` never stops it on its own, but leaving the card still does. |

By default the card does nothing until you press play: it shows the camera's
**last alarm picture** with a small Mushroom-style **play chip in the bottom-right
corner**. Pressing it starts the live view, which runs for `max_seconds`; a **Stop**
chip in the same corner ends it early. When `max_seconds` runs out the card
quietly returns to the last picture — press play again to watch another clip;
nothing has to be reloaded.

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

There's also a visual editor: the serial becomes a dropdown of your cameras.

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
- **Snapshots** — whether the **EZVIZ Snapshot** card may take a new picture
  when it comes into view (*on by default*), and the minimum time between those
  automatic pictures for one camera, in seconds (default **300**; `0` takes one
  on every view), however many dashboards ask. Buttons and scripts that call
  `capture_picture` are not affected. See
  [Fresh pictures on demand](#fresh-pictures-on-demand).
- **General** — request timeout and the ffmpeg arguments for cameras you added
  over local RTSP.
- **Stream address for other apps** — see below.

---

## Fresh pictures on demand

The camera picture shown on a dashboard is the last **alarm** picture, so a
battery camera is never woken just to draw it. When you want a picture from
*now*, call the **`ezviz_rtsp.capture_picture`** service on a camera:

```yaml
action: ezviz_rtsp.capture_picture
target:
  entity_id: camera.driveway_gate
```

The cloud wakes the camera and it takes a full-resolution picture (a few seconds
on a battery camera; no RTSP needed). It appears in the camera's **Snapshot**
image entity (`image.<camera>_snapshot`), and the service returns its
`picture_url` if you ask for a response. Each call wakes the camera, so put it
behind a button rather than a timer. The snapshot is kept in memory, so it is
empty again after a restart until the next capture. A sleeping camera often
answers the first request with EZVIZ error 2009 ("device network exception")
while it wakes; the service then tries once more after 5 seconds, so such a
call can take a few seconds longer.

Pass `min_interval: <seconds>` to skip the capture when that camera took a
picture more recently (the call then returns the last picture with
`skipped: true`). The throttle is kept per camera in Home Assistant, so it holds
however many dashboards or automations ask.

### A snapshot whenever the dashboard is opened

The integration also ships an **EZVIZ Snapshot** card:

```yaml
type: custom:ezviz-snapshot-card
entity: camera.driveway_gate
title: Driveway gate      # optional
capture_on_load: true     # optional, off by default; take a picture when the card comes into view
```

It shows the camera's Snapshot image. Like the video card's `auto_play`,
`capture_on_load` is **off by default**, so showing the card never wakes a
battery camera unless you ask it to. With `capture_on_load: true` it asks for a
new picture each time it comes into view: the dashboard view opens, or the
browser tab or app comes back to the front. These automatic requests follow
**Configure → Snapshots**:

- **Take a snapshot when a dashboard shows the camera** — on by default; turn it
  off and the cards only show the last picture (buttons and scripts calling
  `capture_picture` still work).
- **Minimum time between automatic snapshots** — 300 s by default, per camera,
  however many dashboards ask. A card can override it with `min_interval`.

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
separate token. Reading an address wakes the camera, so treat it like a doorbell:
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

## Devices

There is no per-model promise. This uses the same cloud path the EZVIZ app
uses, so **it should work with any camera the app can show** — battery cameras,
peepholes, and cameras with video encryption on. A camera that plays in the app
is expected to play here, but only testing will tell.

Verified while building this: **DP2** (battery video doorbell), 2048×1296 H.265
+ AAC through the cloud relay.

Also reported working: **CB3** (battery camera with solar panel; eight of them),
1920×1080 live view through the cloud relay, and on-demand snapshots
(`capture_picture`, 1920×1080) in about 2–5 s.

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
