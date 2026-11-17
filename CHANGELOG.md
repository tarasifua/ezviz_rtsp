# Changelog

All notable changes to **Ezviz Cloud with Video** (`ezviz_rtsp`) are listed here.
This project follows [Semantic Versioning](https://semver.org/).

## [1.7.0] — unreleased

### Added
- **SD-card recordings.** The **filmstrip button next to the battery level**
  switches the **EZVIZ Video** card between the live view and one day of a
  camera's SD-card recordings, newest first, with a month calendar for picking
  the day and the one you tap playing in the same media area. Behind it are
  three websocket commands (`ezviz_rtsp/recordings`,
  `ezviz_rtsp/recording/days`, `ezviz_rtsp/recording/clip`) and an
  authenticated MP4 view with range requests. A recording is fetched from the
  camera through the EZVIZ cloud only when it is tapped, saved as an MP4 under
  Home Assistant's media folder (`media/ezviz_rtsp/`, browsable under **Media →
  My media**), and served as the camera's own HEVC to browsers that play it or
  as H.264 converted by Home Assistant to the rest. The current picture stays on
  screen until a recording is picked, and live video is stopped first, so the
  camera never streams and reads its SD card at the same time. A sleeping
  camera's first SD search is retried once after 5 s (EZVIZ error 2009, as for
  `capture_picture`). See
  [Recordings on the SD card](README.md#recordings-on-the-sd-card).
- **A retention setting for downloaded recordings.** Under **Configure →
  Downloaded recordings** you choose how many days those MP4s are kept
  (default 7, `0` keeps them). Older files are swept at start-up, once a day
  while Home Assistant runs, and whenever a new clip is downloaded.
- **Recordings are filed by day.** Downloads are saved under
  `media/ezviz_rtsp/<year>/<month>/<day>/` (Home Assistant's local time), so the
  Media browser reads like a calendar. Retention removes the day folders it
  empties, and clips saved flat by an earlier version are moved into their day
  folders at start-up.
- **The latest recording on demand.** The **Download latest recording** button
  and the `ezviz_rtsp.download_recording` service fetch a camera's newest SD-card
  recording (today, or yesterday when today has none) into the media folder —
  the recording counterpart of `capture_picture`. A **Latest recording** sensor
  (`sensor.<camera>_latest_recording`) shows the file's start time, path,
  interval and format.
- **`show_battery`** on the video card (default `true`): set it to `false` to
  hide the camera's charge, and the filmstrip button then sits alone in the
  corner.
- **`hide_recordings`** on the video card (default `false`): hide the filmstrip
  button for a dashboard that should not offer the SD-card view.
- **`save_recordings`** on the video card (default `true`): with `false`, a
  recording you watch is fetched into a temporary folder, deleted after about two
  hours and kept out of **Media** (no green check, no retention); a clip saved
  earlier still plays from its permanent copy.
- **A progress bar while a recording is fetched.** The card asks the
  integration how much of the interval has arrived and shows a bar with
  "4 / 16 s"; the integration reads the video timestamps inside the camera's
  MPEG-PS stream as it arrives, so the bar reflects the real transfer (one
  report serves every card waiting for the same clip). Conversion has no
  meaningful fraction: the bar fills and the card says "Converting the
  recording…". The old spinner is gone.
- **A calendar for picking the day of the recordings.** The card's day arrows
  are gone: a calendar button opens a Monday-first month grid, and tapping a day
  loads its recordings. Future days are disabled and today is emphasised.
- **Dots on the days that have a recording.** A green dot marks a day whose
  clips are already saved in the media folder — free to know and kept across
  restarts. **Check the SD card for this month** asks the camera about the month
  one day at a time and adds blue dots for days whose clips exist only on the
  card; the answer is cached in Home Assistant's `.storage` (key
  `ezviz_rtsp.recording_days`, about a kilobyte per camera and month), so the
  dots survive a restart without waking the camera. A scan that reaches its time
  budget keeps the days found so far and can be run again; the picker says when
  the month was last checked and whether the check was complete.

### Fixed
- **The card's `format` and `max_height` options now do something.** Both were
  documented but never read: the recordings format was always chosen from the
  browser, and the list height was always 360 px. The card now honours both, and
  both are in the **Recordings** section of the visual editor.
- **A handful of integration internals are fixed.** Turning a light on or off no
  longer fails with a confusing `AttributeError` when the call itself fails (the
  message used an attribute Home Assistant never sets). A live stream that fails
  in the middle now hands the error to the card and sets the cooldown, instead
  of looking like a normal end (which re-woke the camera at once), and a stream
  that fails to open closes the session it had already started, so the camera
  does not keep one that EZVIZ then refuses to hand out again. A slow EZVIZ API
  is a clean "update failed" instead of a full traceback every 30 s, a restored
  siren's auto-off timer can be cancelled again, and the sensitivity number
  reloads the entry from a safe thread after a token expiry.
- **Entities go unavailable instead of showing stale data, and a camera that
  leaves the account no longer floods the log.** Every entity now reports
  unavailable while a poll has failed, and reads its camera's data through a
  mapping that is empty when the camera is gone, so a removed camera no longer
  raises `KeyError` on every coordinator update. The light and switch entities,
  which refresh on every poll, are guarded the same way.
- **A short recording is kept even when the retry fails.** A clip that arrived
  clearly shorter than its interval is fetched once more; if that second read
  fails, or comes back even shorter, the card now plays the longer of the two
  instead of showing an error, so a nearly complete recording is never thrown
  away.
- **A live stream cannot leak a reader if Home Assistant is shutting down, and a
  failed ffmpeg feeder no longer hides why a reader left.** The reader's queue is
  registered inside the stream's own cleanup, so a failure while starting the
  background task still takes it back out; a feeder that failed on its own is
  awaited without re-raising.
- **Shipping the camera card is retried if it ever fails.** The "card is
  registered" flag was set before the card was actually read and served, so a
  failure left the card and its websocket commands missing until Home Assistant
  restarted. The flag is now set only once everything is in place, and the static
  paths are remembered separately so a retry cannot add a route twice.
- **The downloaded-clip index no longer empties when the media folder cannot be
  read.** One folder that could not be listed — or a file that vanished while the
  folder was being walked — used to leave the whole index empty, so every saved
  clip looked absent and was fetched from the camera again, waking it and reading
  its SD card for nothing. The walk now keeps everything it found before the
  trouble. The list of temporary clips watched with saving off is also cleared as
  its files age out, instead of growing for the whole run.
- **The picture box takes the camera's own shape before the first clip, so
  nothing moves at any screen size.** A recording's box used to change from the
  card's fixed 16:9 to the camera's shape only once the player had read the
  file, and near the bottom of a freshly loaded page the grown box pushed the
  list down under the reader. On a large screen the dashboard also has vertical
  slack, so the growth did not even add scroll range and there was nothing to
  compensate with. The card now measures the camera's own idle picture — the
  same frame the poster already shows, so no extra request — and sizes the box
  to it up front; a clip or the live view then fills a box that is already the
  right height. The shape is remembered across rebuilds, so switching a day does
  not resize the card either. Should a picture ever be missing, the box falls
  back to 16:9 and the scroll follows the growth, so the list still stays put.
- **Opening a recording no longer scrolls the page (or the list).** Clicking a
  row rebuilt the whole card. That put the picture box back from the clip's own
  shape to the fixed 16:9, so the card got shorter — and a page scrolled to its
  bottom was clamped upwards, which is exactly what it looked like from a row
  near the end of the list. The list was re-created too. Selecting a row, its
  progress, the player, an error and closing the clip now all repaint the
  existing media area and update the rows in place; nothing about the card is
  built again until the mode or the day changes. When the card is rebuilt after
  all (switching between live and the recordings, or picking another day) the
  page's scroll position is put back, because replacing the card's subtree makes
  the browser drop its scroll anchor and jump to the top of the dashboard.
- **Playing a recording (and the live picture) fills the card's width.** The
  picture box was fixed at 16:9 with `object-fit: contain`, so a 4:3 camera —
  every EZVIZ doorbell records 4:3 — sat between two black bands. The box now
  takes the source's own aspect ratio as soon as the player knows it, so the
  picture reaches both edges with nothing cropped. A portrait stream (a
  peephole, a rotated phone) is capped at a square and cropped rather than
  making the card very tall.
- **The page no longer jumps to the top when a download finishes and starts
  playing.** The player used to replace the whole card, which threw away the
  list, the row that had just been clicked, and its focus — WebKit (Safari and
  the Home Assistant apps) scrolls the page to the top when a focused element
  disappears with its tree, and scroll anchoring can move the view too. The
  media area now swaps the progress bar for the player in place, the row's
  cloud icon and length are updated in place, and the reader's scroll position
  is put back around the first `playing` event for browsers that scroll a
  starting video into view.
- **The card no longer rebuilds itself while a clip is downloading.** Opening the
  view asks the server whether its list is still fresh; when that answer arrived
  (a second or two later) the card threw away and re-created its whole shadow
  tree even though it painted the same rows, which looked like the card
  reloading mid-download and could bounce the list to the top. An answer that
  paints the same list now only updates the day label and the refresh spinner in
  place; the card is rebuilt only when the rows really changed. The finished
  download also plays straight from its own result instead of asking for the
  clip once more, so returning to the downloading row no longer flashes the
  fetching view a second time.
- **Coming back to a clip that is downloading shows its progress bar again.**
  Tapping another recording while one was being fetched is a queued tap, and
  tapping the fetching one again was treated the same way, so the card kept
  saying "Waiting for the current recording to finish…" instead of returning to
  the bar. The fetch now remembers which recording it belongs to: selecting
  that row brings the progress bar back (with an immediate report rather than
  waiting for the next poll) and the clip plays as soon as it lands, while a
  row tapped in the meantime keeps the queued message.
- **Live view waits for a clip download instead of failing it.** Pressing live
  while a recording was still coming off the SD card used to start a second
  EZVIZ session that the camera refuses, so both the clip and the live view
  could fail. The live start now waits on the same per-camera lock the
  downloads use and opens the stream once the download has finished; the
  download is left to complete. The card shows **"Waiting for the download to
  finish…"** before **"Waking the camera…"**, asking a new
  `ezviz_rtsp/live/status` command, so a download started by another card (or
  by the download service) is waited for too.
- **Opening the recordings view no longer forces a camera read.** The card used
  to send "refresh" whenever it reopened with a list it thought old, bypassing
  the integration's cache. It now simply asks, and the integration decides:
  today's list is reused while it is under a minute old (even on a page reload),
  a finished day comes from `.storage`, and the camera is read only when the
  cache cannot answer. Only the ⟳ button bypasses the cache. Rapid switching
  between a read and an unread day joins the read already in flight rather than
  queueing another camera session, and a failed read is not cached, so the next
  attempt is allowed.
- **Closing and reopening the recordings view does not read the day twice.**
  A list that was on its way when the view was closed was thrown away, so the
  next open asked the camera for it again (with the cache bypassed). The card
  now keeps that answer; reopening it within the minute uses it without waking
  the camera. Toggling between live and recordings is otherwise cache-only.
- **A finished day is read from the SD card only once, even across restarts.**
  Past-day lists lived only in memory, so after every restart opening yesterday,
  the day before, and so on, woke the camera again for each day. A day read
  after it ended (its index cannot change any more) is now saved in Home
  Assistant's `.storage` (`ezviz_rtsp.day_lists`) and restored with the media
  index, so opening it is instant and silent. An empty day is saved too. A day
  read only while it was still running is read once more after midnight, because
  its list could still have grown; ⟳ still asks the camera again.
- **Playing a recording right after watching live no longer fails.** The card
  used to drop its own picture but leave the integration's cloud session open
  for the configured *Release the camera after* delay, so the first SD-card
  playback found the camera busy ("The camera is streaming live; stop the live
  view first"). The card now releases the session through a new
  `ezviz_rtsp/live/stop` websocket command as soon as the recordings view opens
  (and again before each clip), so playback starts immediately.
- **A recording already in the media folder is never downloaded twice.** The
  clip lookup now checks the folder itself, not only the in-memory index, so a
  file saved earlier is played straight from `media/ezviz_rtsp/` even after a
  restart, a restored backup or a copy made by hand; a stale index entry whose
  file was deleted is dropped and fetched again. The one exception is a file
  whose MP4 duration is clearly shorter than the interval in its name (a
  download cut off before this fix): that one is replaced by a fresh download
  once, then kept. An **H.264** copy also answers an HEVC request (H.264 plays
  everywhere), so the same recording is not stored twice just because another
  browser or the download service asked for it.
- **The recordings list says which clips are already local.** Each row carries a
  cloud icon while the recording still has to come from the camera's SD card and
  a green check once it is saved in `media/ezviz_rtsp/`; the icon flips as soon
  as the clip is played. The recordings view of the **EZVIZ Video** card shows
  it.
- **The list is read again when it should be.** Opening the recordings view on a
  freshly loaded page (a new card) now asks the camera for the day instead of
  taking the server's cache, and today's list is read again when it is more than
  a minute old. Reopening the view sooner still uses the cached list, and ⟳
  always re-reads.
- **A long recording is no longer cut short.** The transfer from the relay used
  to give up after a fixed 90 seconds, so a recording that took longer to arrive
  was converted and played only up to that point — a video shorter than the
  length in the list. The window now grows with the recording (with a minimum
  that still covers a camera waking up), a pause between packets is tolerated
  longer, and a clip that arrives clearly shorter than its interval is fetched
  once more before it is served. A clip saved by an older version is checked too:
  its MP4 duration is read from the file, and a file shorter than its interval is
  replaced by a fresh download instead of being replayed forever. Files are
  written beside their target and moved into place, so a half-written MP4 is
  never served. The row's length also follows the file once it plays, with the
  listed length in its tooltip when they differ.
- **The recordings list no longer jumps to the top.** Picking a clip near the
  bottom of the list used to re-render the card and scroll the list back to the
  first recording while the clip was fetched and played. The list now keeps its
  position; the ⟳ button and a day change still start at the top.
- **The card says when it re-downloads an incomplete saved clip.** A saved copy
  whose MP4 is clearly shorter than its interval gets an orange alert cloud in
  the list, and while it is replaced the card shows "The saved recording is
  incomplete — downloading it again…" instead of the usual fetching message.
  The row turns back into a green check once the fresh copy is in place.
- **A camera busy with another viewer (EZVIZ 5405) gets a few seconds.** Playback
  is retried twice, two seconds apart, before the card shows the error — enough
  for the relay to release a live session the card just stopped. The message now
  says to close the EZVIZ app or the other live view.
- **Switching days quickly no longer queues a camera session per tap.** Tapping
  today, another day and today again while the first read was still on its way
  put one SD-card read behind another. The card now joins the read already in
  flight for a day instead of sending another, and the integration shares one
  per-day read between every waiting request (also across two cards or
  browsers), so rapid switching costs one camera session per day, not one per
  tap. A failed shared read is forgotten, and the next attempt reaches the
  camera again.
- **A new day with no recordings yet is no longer an error.** EZVIZ answers a
  record search with error **2004** when the window holds no recordings at all —
  yesterday just after midnight, or a quiet hour between events. The integration
  took that for a failed SD card and showed "The camera reported a problem
  reading its SD card." instead of an empty day. It is now read as an empty
  result, so today's list simply says there are no recordings yet (and the
  calendar month scan also treats such a day as empty).
- **A recording the camera itself sends short is not fetched again after a
  restart.** The "is this saved file shorter than its interval?" check is a
  heuristic, and its verdict for a short clip was only kept in memory: every
  restart brought the orange alert cloud back and fetched the clip once more,
  forever. The verdict is now saved in Home Assistant's `.storage`
  (`ezviz_rtsp.short_clips`) and restored with the media index; a marker is
  dropped when its file is gone. The tolerance also grew to 2.5 s (or 5% of a
  long clip), because the camera often closes an event file one or two seconds
  early — a 12-second event arriving as 11 s of video is no longer treated as a
  cut-off download.
- **The calendar's blue dots survive a restart.** A day was marked with a blue
  dot as soon as its SD list was seen to hold recordings, but that set lived only
  in memory: after every Home Assistant restart the blue dots were gone and came
  back only when each day was opened again. The days are now saved in Home
  Assistant's `.storage` (`ezviz_rtsp.sd_days`) and restored with the media
  index, so the dots are there as soon as the calendar is opened, and old days
  are dropped as the entry is rewritten.
- **The selected day's dot keeps its colour.** A day's dot used to be lightened
  when that day was the selected one, so it would not vanish into the day's
  primary-coloured fill — a blue SD dot then read as a pale, greenish dot. The
  dot now keeps its real colour and carries a thin ring in the card's background
  colour, which separates it from the selected day's fill without changing what
  the dot means.

### Changed
- **The README is user-facing only.** The implementation notes — the stream
  architecture, the websocket API, the cache and storage keys, the EZVIZ error
  codes it retries, and how the bundled `pyezvizapi` is refreshed — moved to
  [docs/TECHNICAL.md](docs/TECHNICAL.md), leaving the README with what a user
  needs: what it does, how to install and set it up, and what each setting and
  card option means.
- **Downloaded recordings are kept per account.** The retention setting under
  **Configure → Downloaded recordings** now applies to the cameras of the
  account it is set on, not to the whole media folder, so two EZVIZ accounts can
  keep their recordings for different lengths: a clip is swept by the setting of
  the account its camera belongs to. A clip whose camera is no longer in a
  set-up account is left alone, because its retention is unknown.
- **Opening a day or the calendar does far less work.** A saved MP4's duration
  (read from its `mvhd` box, to spot a copy the camera cut short) is now read
  once and remembered against the file's size and mtime; the calendar's green
  dots come from an index kept as clips are added and removed instead of a scan
  of the whole media folder on every open; and the finished days' lists are
  lifted from storage one at a time as they are opened, so a restart no longer
  parses hundreds of days of intervals into memory up front.
- **Dead code is gone, and duplicated rules live in one place.** The unused
  "snapshot from the live stream" helpers (`async_read`, `async_grab_jpeg`,
  `async_ps_to_jpeg`, `_ffmpeg`) are removed, and the battery-camera and
  RTSP-entry predicates that `camera.py` and `live.py` each spelled out are now
  single helpers.
- **`pyezvizapi` 2.5.1 is now bundled, not installed.** SD-card playback needs a
  2.x `pyezvizapi`, but Home Assistant's built-in EZVIZ integration pins 1.x, and
  one environment can hold only one version — a clash that hassfest reports. The
  integration now ships its own copy of `pyezvizapi` 2.5.1 under
  `custom_components/ezviz_rtsp/pyezvizapi/` and imports it from there, so it no
  longer lists `pyezvizapi` in `requirements` and runs happily next to the
  built-in EZVIZ integration (or any other integration that uses `pyezvizapi`).
  The copy is the upstream package unchanged except for its import root; its own
  runtime dependencies (`paho-mqtt`, `pycryptodome`, `tzdata`, `xmltodict`) are
  declared in the manifest. The live view follows the 2.x module layout
  (`pyezvizapi.streaming.cloud`; 2.0.0 removed `pyezvizapi.cloud_stream`).
- **Taps that come faster than the camera now favour the newest recording.**
  While one clip is being fetched, tapping another only remembers the latest:
  the recordings in between are not downloaded at all, so the camera is not
  woken for clips you skipped, and the waiting view says "Waiting for the
  current recording to finish…". A recording already in the media folder still
  plays at once, past the queue. A queued clip checks for a live view again once
  it gets its turn and refuses rather than fighting a stream started meanwhile.
- **The video card's editor is grouped into sections** — **Camera**,
  **Playback**, **Picture and snapshots**, **Buttons and battery** and
  **Recordings** — instead of one long list of every option.

### Removed
- **The separate EZVIZ Snapshot and EZVIZ Recordings cards.** Both are folded
  into the **EZVIZ Video** card: `capture_on_load` takes the snapshot on view,
  and the filmstrip button opens the SD-card recordings. The
  `custom:ezviz-snapshot-card` and `custom:ezviz-recordings-card` types no longer
  exist; a dashboard using one should point that card at
  `custom:ezviz-video-card` (with `serial` or `entity`) and use
  `capture_on_load` or the filmstrip button instead.

## [1.6.0] — 2026-11-07

### Added
- The EZVIZ Video card can show the date and time of the picture it is showing
  (the motion or snapshot image, whichever `picture` selects) in the top-right
  corner. `show_timestamp` turns it on (off by default); it is hidden while a
  clip plays.

### Fixed
- The video card's visual editor no longer jumps back to the top (and no longer
  loses the field focus) after changing an option.

## [1.5.1] — 2026-11-06

### Fixed
- After a Home Assistant restart an empty Snapshot image no longer paints the
  card black: `picture: snapshot` falls back to the last motion picture, and the
  Snapshot card shows "No snapshot yet" until a capture arrives.

## [1.5.0] — 2026-11-06

### Added
- A **Request snapshot** button in every camera's **Controls** section, and a
  **snapshot chip** on the **EZVIZ Video** card — a fresh picture with one press.
- The video card's visual editor now covers the snapshot on open
  (`capture_on_load`), the idle picture (`picture`: last motion, last snapshot or
  whichever is newer) and hiding each chip (`hide_play`, `hide_stop`,
  `hide_snapshot`).

### Changed
- The `capture_picture` throttle is shared by the service, the button and the
  cards, so a button press followed by a dashboard opening wakes the camera only
  once.

### Fixed
- The EZVIZ Snapshot card no longer counts a scrolled-off card as visible, so
  `capture_on_load` cannot wake a camera behind another part of a long
  dashboard.
- The video card's `picture: snapshot` option is now labelled (and explained in
  the editor) to show the previous motion frame when no snapshot is available,
  and `newest` compares both frames.

## [1.4.0] — 2026-11-06

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

[1.6.0]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.6.0
[1.5.1]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.5.1
[1.5.0]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.5.0
[1.4.0]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.4.0
[1.3.0]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.3.0
[1.2.1]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.2.1
[1.2.0]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.2.0
[1.1.0]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.1.0
[1.0.9]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.0.9
[1.0.8]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.0.8
[1.0.7]: https://github.com/tarasifua/ezviz_rtsp/releases/tag/v1.0.7