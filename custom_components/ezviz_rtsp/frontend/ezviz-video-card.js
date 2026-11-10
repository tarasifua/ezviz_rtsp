// EZVIZ Cloud with Video — live view card, Mushroom-inspired.
// Served and registered by the ezviz_rtsp integration: there is nothing to add
// to your Lovelace resources.
//
//   type: custom:ezviz-video-card
//   serial: BC1234567      # device serial; the visual editor lists your cameras
//   entity: camera.front   # or point at the camera entity directly
//   title: Front door      # optional; defaults to the camera's name
//   icon: mdi:doorbell     # optional
//   auto_play: false       # optional; play while the card is on screen
//   max_seconds: 60        # optional; stop to save battery, 0 = never
//   capture_on_load: false # optional; request a fresh snapshot when the card appears
//   picture: motion        # optional; what the idle picture shows: motion, snapshot or newest
//   hide_play: false       # optional; hide the play chip
//   hide_stop: false       # optional; hide the stop chip
//   hide_snapshot: false   # optional; hide the snapshot chip
//   show_timestamp: false  # optional; show the picture's date and time
//
// The card shows the camera's live picture from the integration's own stream:
// its fast MJPEG path (an <img> that appears a few seconds after the camera
// wakes) with Home Assistant's HLS as the fallback. It is styled after Mushroom
// cards — rounded card, an icon tile, and a small play/stop chip in the corner
// of the picture — but needs neither Mushroom nor any other frontend dependency.
// hls.js is bundled with the integration and served from its own path, so no
// code is ever loaded from a CDN.
//
// To keep a battery camera asleep, the card stops the stream whenever it is not
// on screen (another dashboard view, another browser tab, scrolled away) or
// after max_seconds, and starts it again on return when auto_play is on.

// hls.js is bundled with the integration and served from its own static path,
// next to this card — no third-party code is loaded from a CDN, and it works on
// installations without internet access.
const HLS_SCRIPT = "hls.min.js";

// A battery camera takes a while to wake and send its first frame. max_seconds
// counts from the first frame; this is a separate cap on the wait for it.
const STARTUP_SECONDS = 45;

// The integration appends its version (and a content hash) to the module URL,
// so the card reports which build is running and it can never drift from the
// manifest. The hash changes on every edit, which is what tells a dev build
// apart when the version itself is unchanged.
const CARD_VERSION = (() => {
  try {
    const params = new URL(import.meta.url).searchParams;
    const version = params.get("version") || "?";
    const build = (params.get("v") || "").slice(0, 8);
    return build ? `${version}+${build}` : version;
  } catch {
    return "?";
  }
})();

// hls.js is loaded once per page, only when a browser can't play HLS natively.
// It is served by the integration itself, from the same directory as this card.
let hlsLoading = null;
const loadHls = () => {
  if (window.Hls) return Promise.resolve(window.Hls);
  hlsLoading ||= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    try {
      script.src = new URL(HLS_SCRIPT, import.meta.url).toString();
    } catch {
      reject(new Error("hls.js"));
      return;
    }
    script.onload = () => (window.Hls ? resolve(window.Hls) : reject(new Error("hls.js")));
    script.onerror = () => reject(new Error("hls.js"));
    document.head.appendChild(script);
  });
  return hlsLoading;
};

const STRINGS = /* translations */ {
  "en": {
    "play": "Watch",
    "stop": "Stop",
    "starting": "Waking the camera…",
    "loading": "Loading…",
    "live": "Live",
    "idle": "Tap to watch",
    "no_video": "Stopped after {s} s",
    "no_start": "The camera sent no video. It may still be waking up — try again.",
    "no_entity": "Camera not found in this account",
    "could_not_start": "Couldn't start the video: {msg}",
    "serial": "Camera",
    "title": "Title",
    "icon": "Icon",
    "auto_play": "Play video automatically",
    "max_seconds": "Stop video playback after (seconds, 0 = never)",
    "capture_on_load": "Take a snapshot when the card opens",
    "picture": "Picture while not playing",
    "picture_helper": "If no snapshots are available, the mode shows the previous frame with motion. The \"whichever is newer\" option compares both frames and displays the newest one.",
    "picture_motion": "Last motion photo",
    "picture_snapshot": "Last snapshot (motion photo until one exists)",
    "picture_newest": "Whichever is newer",
    "snapshot": "Snapshot",
    "hide_play": "Hide the play button",
    "hide_stop": "Hide the stop button",
    "hide_snapshot": "Hide the snapshot button",
    "show_timestamp": "Show the picture date and time",
    "rec_title": "{name} recordings",
    "rec_today": "Today",
    "rec_yesterday": "Yesterday",
    "rec_count": "{n} recordings",
    "rec_none": "No recordings on this day",
    "rec_partial": "{n}+ recordings (list cut short)",
    "rec_loading": "Reading the SD card…",
    "rec_fetching": "Fetching the recording from the camera…",
    "rec_failed": "{msg}",
    "rec_prev": "Previous day",
    "rec_next": "Next day",
    "rec_refresh": "Refresh",
    "rec_pick": "Tap a recording to play it",
    "rec_close": "Close player"
  },
  "uk": {
    "play": "Дивитися",
    "stop": "Зупинити",
    "starting": "Прокидаємо камеру…",
    "loading": "Завантаження…",
    "live": "Наживо",
    "idle": "Торкніться, щоб дивитися",
    "no_video": "Зупинено через {s} с",
    "no_start": "Камера не надіслала відео. Можливо, ще прокидається — спробуйте ще раз.",
    "no_entity": "Камеру не знайдено в цьому акаунті",
    "could_not_start": "Не вдалося запустити відео: {msg}",
    "serial": "Камера",
    "title": "Заголовок",
    "icon": "Іконка",
    "auto_play": "Відтворювати відео автоматично",
    "max_seconds": "Зупиняти відтворення відео через (секунд, 0 = ніколи)",
    "capture_on_load": "Робити снапшот при відкритті картки",
    "picture": "Що показувати, коли відео не грає",
    "picture_helper": "Якщо снапшотів немає, режим показує попередній кадр із рухом. А опція «що новіше» порівнює їх між собою та показує найсвіжіший.",
    "picture_motion": "Останнє фото з рухом",
    "picture_snapshot": "Останній снапшот (поки немає — фото з рухом)",
    "picture_newest": "Що новіше",
    "snapshot": "Снапшот",
    "hide_play": "Приховати кнопку відтворення",
    "hide_stop": "Приховати кнопку зупинки",
    "hide_snapshot": "Приховати кнопку снапшота",
    "show_timestamp": "Показувати дату й час знімка",
    "rec_title": "Записи: {name}",
    "rec_today": "Сьогодні",
    "rec_yesterday": "Вчора",
    "rec_count": "Записів: {n}",
    "rec_none": "Цього дня записів немає",
    "rec_partial": "Записів: {n}+ (список неповний)",
    "rec_loading": "Читаємо SD-картку…",
    "rec_fetching": "Завантажуємо запис із камери…",
    "rec_failed": "{msg}",
    "rec_prev": "Попередній день",
    "rec_next": "Наступний день",
    "rec_refresh": "Оновити",
    "rec_pick": "Торкніться запису, щоб відтворити",
    "rec_close": "Закрити плеєр"
  }
} /* end translations */;

const t = (lang, key, vars) => {
  const dict = STRINGS[lang] || STRINGS.en;
  let text = dict[key] || STRINGS.en[key] || key;
  if (vars) for (const [k, v] of Object.entries(vars)) text = text.replace(`{${k}}`, v);
  return text;
};

const pickLang = (hass) => {
  const lang = hass?.locale?.language || hass?.language || "en";
  return STRINGS[lang] ? lang : STRINGS[lang.split("-")[0]] ? lang.split("-")[0] : "en";
};

// The card's defaults, shared with the visual editor so every control shows the
// value the card is actually using (not just the keys present in the YAML).
const CARD_DEFAULTS = {
  max_seconds: 60,
  auto_play: false,
  capture_on_load: false,
  picture: "motion",
  hide_play: false,
  hide_stop: false,
  hide_snapshot: false,
  show_timestamp: false,
};

const style = /* css */ `
  :host { display: block; }
  ha-card { overflow: hidden; }
  .wrap { display: flex; flex-direction: column; gap: 12px; padding: 12px; }

  .header { display: flex; align-items: center; gap: 12px; }
  .tile {
    flex: 0 0 auto;
    width: 40px; height: 40px;
    border-radius: var(--mushroom-icon-shape, 12px);
    display: flex; align-items: center; justify-content: center;
    color: var(--primary-color);
    background: color-mix(in srgb, var(--primary-color) 16%, transparent);
    --mdc-icon-size: 22px;
  }
  .tile.error { color: var(--error-color, #db4437); background: color-mix(in srgb, var(--error-color, #db4437) 16%, transparent); }
  .info { min-width: 0; flex: 1 1 auto; }
  .primary {
    font-size: 14px; font-weight: 500; line-height: 20px;
    color: var(--primary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .secondary {
    font-size: 12px; line-height: 16px; margin-top: 2px;
    color: var(--secondary-text-color);
    display: flex; align-items: center; gap: 6px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .battery {
    flex: 0 0 auto; display: flex; align-items: center; gap: 3px;
    font-size: 13px; font-weight: 500; line-height: 1;
    color: var(--secondary-text-color); --mdc-icon-size: 20px;
  }
  .battery.low { color: var(--error-color, #db4437); }
  .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--secondary-text-color); flex: 0 0 auto;
  }
  .dot.on { background: var(--success-color, #43a047); box-shadow: 0 0 0 0 currentColor; animation: pulse 2s infinite; }
  @keyframes pulse {
    0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--success-color, #43a047) 60%, transparent); }
    70% { box-shadow: 0 0 0 8px transparent; }
    100% { box-shadow: 0 0 0 0 transparent; }
  }

  .media {
    position: relative; aspect-ratio: 16 / 9; width: 100%;
    border-radius: var(--mushroom-media-radius, 12px);
    overflow: hidden;
    background: var(--secondary-background-color, #111);
  }
  .media video, .media .live {
    position: absolute; inset: 0; width: 100%; height: 100%;
    object-fit: contain; background: #000; display: block;
  }
  .poster {
    position: absolute; inset: 0;
    background-size: cover; background-position: center;
    background-color: #000;
  }

  .message {
    position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    text-align: center; padding: 0 14px; color: #eee; font-size: 13px;
    background: linear-gradient(0deg, rgba(0,0,0,.25), rgba(0,0,0,.25));
    pointer-events: none; /* never block the controls underneath */
  }

  .chip {
    position: absolute; z-index: 2;
    font: inherit; font-size: 12px; line-height: 1;
    display: inline-flex; align-items: center; gap: 6px;
    padding: 7px 12px; border: 0; border-radius: 999px; cursor: pointer;
    background: color-mix(in srgb, #000 55%, transparent); color: #fff;
    backdrop-filter: blur(4px);
  }
  .chip.play, .chip.stop { right: 8px; bottom: 8px; }
  .chip.snapshot { left: 8px; bottom: 8px; }
  .chip.play { color: #fff; background: color-mix(in srgb, var(--primary-color) 85%, #000); }
  .chip.play:hover { background: var(--primary-color); }
  .chip:hover { background: color-mix(in srgb, #000 70%, transparent); }
  .chip.busy { cursor: progress; opacity: 0.75; }
  .chip.busy ha-icon { display: none; }
  .chip.busy::before {
    content: ""; width: 12px; height: 12px; border-radius: 50%;
    border: 2px solid rgba(255, 255, 255, 0.35); border-top-color: #fff;
    animation: chipspin 900ms linear infinite;
  }
  @keyframes chipspin { to { transform: rotate(360deg); } }
  .when {
    position: absolute; top: 8px; right: 8px; z-index: 2;
    font-size: 11px; line-height: 1; padding: 5px 8px; border-radius: 999px;
    color: #fff; background: color-mix(in srgb, #000 55%, transparent);
    backdrop-filter: blur(4px); pointer-events: none;
  }

  .spinner {
    position: absolute; right: 10px; bottom: 10px; z-index: 2;
    width: 26px; height: 26px; border-radius: 50%;
    border: 3px solid color-mix(in srgb, #fff 30%, transparent);
    border-top-color: #fff;
    background: color-mix(in srgb, #000 45%, transparent);
    animation: spin 900ms linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
`;

class EzvizVideoCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._lang = "en";
    this._state = "idle"; // idle | loading | playing
    this._message = "";
    // Bumped on every stop so a stream that is still opening cannot finish
    // after the card was hidden or reloaded.
    this._gen = 0;
    // Whether the first frame has reached the screen (max_seconds counts from it).
    this._started = false;
    this._startupTimer = null;
    // A pause the user asked for (video controls) must not be auto-undone.
    this._userPaused = false;
    // An automatic snapshot request is in flight; don't stack them up.
    this._capturing = false;
    // A press on the card's own snapshot chip is in flight.
    this._snapshotting = false;
    this._snapshotChipEl = null;
    // Idle-picture entities (motion and snapshot) resolved from the registry.
    this._images = {};
    this._imagesFrom = undefined;
    this._imagesCam = undefined;
    this._posterShown = undefined;
    this._posterEl = null;
    this._whenEl = null;
  }

  static getStubConfig() {
    return { serial: "" };
  }

  static getConfigElement() {
    return document.createElement("ezviz-video-card-editor");
  }

  setConfig(config) {
    if (!config || (!config.serial && !config.entity)) {
      throw new Error("ezviz-video-card: 'serial' (or 'entity') is required");
    }
    // Play, snapshots and waking the camera are all off by default: the card
    // shows the camera's last picture and waits for a tap, so opening the
    // dashboard never wakes a battery camera.
    this._config = { ...CARD_DEFAULTS, ...config };
    this._device = undefined;
    this._images = {};
    this._imagesFrom = undefined;
    this._imagesCam = undefined;
    this._posterShown = undefined;
    this._stop();
    this._state = "idle";
    this._message = "";
    this._render();
    this._maybeAutoPlay();
    if (this._visible) this._maybeCapture();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const lang = pickLang(hass);
    if (first && lang !== this._lang && !this._video) this._lang = lang;
    if (!this._devices) this._loadDevices();
    if (first || lang !== this._lang) {
      this._lang = lang;
      if (!this._video && this._state !== "loading") this._render();
    }
    this._syncBattery();
    this._syncPoster();
    this._syncWhen();
  }

  getCardSize() {
    return 6;
  }

  connectedCallback() {
    this._watchVisibility();
    this._maybeAutoPlay();
  }

  disconnectedCallback() {
    // A Lovelace view switch removes the card from the DOM (and puts it back on
    // return); stop the stream for good, so it never keeps a battery camera
    // awake behind another view.
    queueMicrotask(() => {
      if (this.isConnected) return;
      this._unwatchVisibility();
      this._visible = false;
      this._stop(true);
    });
  }

  // -- visibility ----------------------------------------------------------
  //
  // A battery camera must not sit awake with nobody looking. Lovelace may keep
  // an inactive view in the DOM (and removes it when it does not), so
  // IntersectionObserver alone is not reliable; the card polls its own geometry
  // and reacts at once to a hidden browser tab. Leaving the screen stops the
  // stream for good - a clip never keeps a camera awake behind another view.

  _watchVisibility() {
    if (!this._visTimer) {
      this._visTimer = setInterval(() => this._syncVisibility(), 1000);
    }
    if (!this._io && "IntersectionObserver" in window) {
      // A second signal for the card scrolled off screen (Lovelace may keep an
      // inactive view laid out, just out of sight).
      this._io = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) this._intersecting = entry.isIntersecting;
          this._syncVisibility();
        },
        { threshold: 0 }
      );
      this._io.observe(this);
    }
    if (!this._onDocVisibility) {
      this._onDocVisibility = () => this._syncVisibility();
      document.addEventListener("visibilitychange", this._onDocVisibility);
    }
    this._syncVisibility();
  }

  _unwatchVisibility() {
    clearInterval(this._visTimer);
    this._visTimer = null;
    this._io?.disconnect();
    this._io = null;
    if (this._onDocVisibility) {
      document.removeEventListener("visibilitychange", this._onDocVisibility);
      this._onDocVisibility = null;
    }
  }

  _isVisible() {
    if (!this.isConnected || document.hidden) return false;
    if (this._intersecting === false) return false;
    const rect = this.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    const style = getComputedStyle(this);
    return style.display !== "none" && style.visibility !== "hidden";
  }

  _syncVisibility() {
    if (!this._config) return;
    const visible = this._isVisible();
    if (visible !== this._visible) {
      this._visible = visible;
      if (visible) this._onShown();
      else this._onHidden();
      return;
    }
    if (visible) this._ensurePlaying();
  }

  _onHidden() {
    // Off screen means nobody is watching: stop the stream for good (a battery
    // camera must not be left streaming).
    if (this._state !== "playing" && this._state !== "loading") return;
    this._stop(true);
  }

  _onShown() {
    this._maybeCapture();
    this._ensurePlaying();
  }

  // A fresh snapshot on open, for the idle picture. The service is marked
  // automatic, so Configure → Snapshots decides whether it may run and the
  // server keeps the minimum time between pictures per camera — several open
  // dashboards still wake a camera only once per interval.
  async _maybeCapture() {
    if (!this._config?.capture_on_load || this._capturing || !this._hass) return;
    const entity = this._entityId();
    if (!entity) return;
    const cam = this._hass.states[entity];
    if (!cam || cam.state === "unavailable" || cam.state === "unknown") return;
    this._capturing = true;
    try {
      await this._hass.callService(
        "ezviz_rtsp",
        "capture_picture",
        { automatic: true },
        { entity_id: entity }
      );
    } catch (err) {
      console.debug(`[ezviz-video-card] ${entity}: ${err?.message || err}`);
    } finally {
      this._capturing = false;
    }
  }

  _ensurePlaying() {
    if (this._userPaused || this._state !== "playing" || !this._started) return;
    const video = this._video;
    if (video && video.paused) video.play().catch(() => {});
  }

  // -- data ----------------------------------------------------------------

  async _loadDevices(force = false) {
    if (!this._hass) return;
    if (this._devices && !force) return;
    try {
      this._devices = await this._hass.callWS({ type: "ezviz_rtsp/devices" });
    } catch {
      this._devices = [];
    }
    // The picture URL from this call is a short-lived signed URL, so forget the
    // resolved device and pick it up fresh.
    this._device = undefined;
    // Re-fill the header name/icon now that devices are known.
    if (this._state === "idle" && !this._video) this._render();
    this._syncBattery();
  }

  _findDevice() {
    if (this._device !== undefined) return this._device;
    if (!this._devices) return null;
    const { serial, entity } = this._config || {};
    this._device =
      this._devices.find((d) => (serial && d.serial === serial) || (entity && d.entity_id === entity)) ||
      null;
    return this._device;
  }

  _entityId() {
    return this._config?.entity || this._findDevice()?.entity_id || null;
  }

  _name() {
    const id = this._entityId();
    const state = id ? this._hass?.states?.[id] : null;
    return (
      this._config.title ||
      state?.attributes?.friendly_name ||
      this._findDevice()?.name ||
      this._config.serial ||
      "EZVIZ"
    );
  }

  // The image entity the integration made for a camera: "last_motion_image"
  // (the camera's own picture) or "snapshot" (capture_picture). The scan over
  // the entity registry runs only when the registry object or camera changes.
  _imageId(kind) {
    const entities = this._hass?.entities;
    const camId = this._entityId();
    if (!entities || !camId) return undefined;
    if (entities !== this._imagesFrom || camId !== this._imagesCam) {
      this._imagesFrom = entities;
      this._imagesCam = camId;
      this._images = {};
    }
    if (kind in this._images) return this._images[kind];
    const cam = entities[camId];
    const match = cam?.device_id && Object.values(entities).find(
      (e) => e.device_id === cam.device_id && e.entity_id.startsWith("image.") &&
        (e.translation_key === kind || e.entity_id.endsWith(`_${kind}`))
    );
    this._images[kind] = match ? match.entity_id : undefined;
    return this._images[kind];
  }

  _timeOf(state) {
    const parsed = Date.parse(state?.state);
    if (!Number.isNaN(parsed)) return parsed;
    const updated = Date.parse(state?.last_updated);
    return Number.isNaN(updated) ? 0 : updated;
  }

  _picture(kind) {
    const id = this._imageId(kind);
    const state = id ? this._hass?.states?.[id] : undefined;
    const pic = state?.attributes?.entity_picture;
    // An image entity exposes its proxy URL even when it holds no picture yet
    // (state "unknown"/"unavailable"). Using it would paint a broken/black
    // frame instead of falling back to the camera's last motion picture.
    const hasPicture = state && state.state !== "unknown" && state.state !== "unavailable";
    if (pic && hasPicture) {
      return {
        url: new URL(pic, window.location.origin).toString(),
        ts: this._timeOf(state),
        stamp: state.state,
        entity: id,
      };
    }
    // The camera's own picture is its last motion photo; it is still there when
    // no separate motion image entity was created.
    if (kind === "last_motion_image") {
      const cam = this._hass?.states?.[this._entityId()];
      const camPic = cam?.attributes?.entity_picture;
      if (camPic) {
        return {
          url: new URL(camPic, window.location.origin).toString(),
          ts: 0,
          stamp: "",
          entity: this._entityId(),
        };
      }
    }
    return undefined;
  }

  // The idle picture: the last motion photo (default), the last snapshot, or
  // whichever of the two is newer.
  _poster() {
    const mode = this._config?.picture || "motion";
    const motion = this._picture("last_motion_image");
    const snapshot = this._picture("snapshot");
    // With no snapshot yet, fall back to the last motion photo rather than a
    // blank card; the editor says so next to the option.
    if (mode === "snapshot") return snapshot || motion;
    if (mode === "newest") {
      if (!snapshot) return motion;
      if (!motion) return snapshot;
      return snapshot.ts > motion.ts ? snapshot : motion;
    }
    return motion || snapshot;
  }

  _posterUrl() {
    const picture = this._poster();
    if (!picture?.url) return "";
    // The image proxy URL can stay the same between pictures; add the picture's
    // timestamp so a fresh one is never served from the browser cache.
    const sep = picture.url.includes("?") ? "&" : "?";
    return picture.stamp
      ? `${picture.url}${sep}s=${encodeURIComponent(picture.stamp)}`
      : picture.url;
  }

  // Update the picture in place, without re-rendering the card (a capture can
  // land while the card is idle, and the whole card must not blink).
  _syncPoster() {
    if (!this._config) return;
    const url = this._posterUrl();
    if (url === this._posterShown) return;
    this._posterShown = url;
    if (!this._media) return;
    if (!url) {
      this._posterEl?.remove();
      this._posterEl = null;
      return;
    }
    if (!this._posterEl) {
      this._posterEl = document.createElement("div");
      this._posterEl.className = "poster";
      this._media.prepend(this._posterEl);
    }
    this._posterEl.style.backgroundImage = `url("${url}")`;
  }

  // The date and time of the picture currently on the card (motion or
  // snapshot, whichever _poster picked). Empty when the source has no timestamp.
  _whenText() {
    if (!this._config?.show_timestamp) return "";
    const picture = this._poster();
    if (!picture?.ts) return "";
    return new Date(picture.ts).toLocaleString([], {
      dateStyle: "short",
      timeStyle: "short",
    });
  }

  _syncWhen() {
    if (!this._config) return;
    const text = this._state === "playing" ? "" : this._whenText();
    if (this._whenEl) {
      this._whenEl.textContent = text;
      this._whenEl.hidden = !text;
      return;
    }
    if (text && this._media && this._state !== "playing") {
      this._whenEl = document.createElement("div");
      this._whenEl.className = "when";
      this._whenEl.textContent = text;
      this._media.appendChild(this._whenEl);
    }
  }

  _batteryEntity() {
    return this._findDevice()?.battery_entity_id || null;
  }

  _batteryLevel() {
    const id = this._batteryEntity();
    const state = id ? this._hass?.states?.[id] : null;
    const level = state ? Number(state.state) : NaN;
    return Number.isFinite(level) ? level : null;
  }

  _batteryIcon(level) {
    if (level === null) return "mdi:battery-unknown";
    if (level >= 95) return "mdi:battery";
    if (level <= 5) return "mdi:battery-alert";
    const step = Math.min(90, Math.max(10, Math.round(level / 10) * 10));
    return `mdi:battery-${step}`;
  }

  _syncBattery() {
    const el = this._header?.battery;
    if (!el) return;
    const level = this._batteryLevel();
    if (level === null) {
      el.replaceChildren();
      el.hidden = true;
      return;
    }
    el.hidden = false;
    el.classList.toggle("low", level <= 20);
    const icon = document.createElement("ha-icon");
    icon.setAttribute("icon", this._batteryIcon(level));
    const text = document.createElement("span");
    text.textContent = `${Math.round(level)}%`;
    el.replaceChildren(icon, text);
  }

  // -- rendering -----------------------------------------------------------

  _render() {
    if (!this._config) return;
    const root = this.shadowRoot;
    if (!root) return;

    const card = document.createElement("ha-card");
    const wrap = document.createElement("div");
    wrap.className = "wrap";

    // Header
    const header = document.createElement("div");
    header.className = "header";

    const tile = document.createElement("div");
    tile.className = "tile" + (this._state === "idle" && this._message ? " error" : "");
    const icon = document.createElement("ha-icon");
    icon.setAttribute("icon", this._config.icon || "mdi:video");
    tile.appendChild(icon);

    const info = document.createElement("div");
    info.className = "info";
    const primary = document.createElement("div");
    primary.className = "primary";
    primary.textContent = this._name();
    const secondary = document.createElement("div");
    secondary.className = "secondary";
    const dot = document.createElement("span");
    dot.className = "dot" + (this._started ? " on" : "");
    const status = document.createElement("span");
    status.textContent = this._statusText();
    secondary.append(dot, status);
    info.append(primary, secondary);

    // Charge of a battery camera / peephole, opposite the name.
    const battery = document.createElement("div");
    battery.className = "battery";
    header.append(tile, info, battery);

    // Media
    const media = document.createElement("div");
    media.className = "media";
    this._media = media;

    this._posterEl = null;
    const poster = this._posterUrl();
    if (poster) {
      const layer = document.createElement("div");
      layer.className = "poster";
      layer.style.backgroundImage = `url("${poster}")`;
      media.appendChild(layer);
      this._posterEl = layer;
    }
    this._posterShown = poster;

    this._snapshotChipEl = null;
    this._whenEl = null;
    if (this._state === "playing" && this._video) {
      media.appendChild(this._video); // re-attach the running element
      if (!this._config.hide_stop) media.appendChild(this._stopChip());
      if (!this._config.hide_snapshot) media.appendChild(this._snapshotChip());
    } else if (this._state === "loading") {
      // Show the last picture right away, with a small spinner in the corner -
      // the camera can take a few seconds to wake, and a blank card looks broken.
      const spinner = document.createElement("div");
      spinner.className = "spinner";
      media.appendChild(spinner);
    } else {
      // Small Mushroom-style chips in the corners, not big circles over the
      // picture: the card stays a picture with clear controls.
      if (!this._config.hide_play) media.appendChild(this._playChip());
      if (!this._config.hide_snapshot) media.appendChild(this._snapshotChip());
      if (this._message) {
        const message = document.createElement("div");
        message.className = "message";
        message.textContent = this._message;
        media.appendChild(message);
      }
    }

    // The picture's own date and time, over the top-right corner. Hidden while
    // a clip is playing (the live view is now, not a still).
    const when = this._state === "playing" ? "" : this._whenText();
    if (when) {
      this._whenEl = document.createElement("div");
      this._whenEl.className = "when";
      this._whenEl.textContent = when;
      media.appendChild(this._whenEl);
    }

    wrap.append(header, media);
    card.appendChild(wrap);
    root.replaceChildren(createStyle(style), card);
    this._header = { tile, primary, secondary, dot, status, battery };
    this._syncBattery();
  }

  _statusText() {
    if (this._started) return t(this._lang, "live");
    if (this._state === "playing" || this._state === "loading") {
      return t(this._lang, "starting");
    }
    if (this._message) return this._message;
    return t(this._lang, "idle");
  }

  _stopChip() {
    const stop = document.createElement("button");
    stop.className = "chip stop";
    const stopIcon = document.createElement("ha-icon");
    stopIcon.setAttribute("icon", "mdi:stop");
    stopIcon.style.setProperty("--mdc-icon-size", "14px");
    const label = document.createElement("span");
    label.textContent = t(this._lang, "stop");
    stop.append(stopIcon, label);
    stop.addEventListener("click", (event) => {
      event.stopPropagation();
      this._stop(true);
    });
    return stop;
  }

  _playChip() {
    const play = document.createElement("button");
    play.className = "chip play";
    play.title = t(this._lang, "play");
    const icon = document.createElement("ha-icon");
    icon.setAttribute("icon", "mdi:play");
    icon.style.setProperty("--mdc-icon-size", "14px");
    const label = document.createElement("span");
    label.textContent = t(this._lang, "play");
    play.append(icon, label);
    play.addEventListener("click", (event) => {
      event.stopPropagation();
      this._play();
    });
    return play;
  }

  _snapshotChip() {
    const chip = document.createElement("button");
    chip.className = "chip snapshot" + (this._snapshotting ? " busy" : "");
    chip.title = t(this._lang, "snapshot");
    // A serial-only card knows its camera entity once the device list loads;
    // until then there is nothing to call the service on.
    chip.disabled = this._snapshotting || !this._entityId();
    const icon = document.createElement("ha-icon");
    icon.setAttribute("icon", "mdi:camera");
    icon.style.setProperty("--mdc-icon-size", "14px");
    const label = document.createElement("span");
    label.textContent = t(this._lang, "snapshot");
    chip.append(icon, label);
    chip.addEventListener("click", (event) => {
      event.stopPropagation();
      this._requestSnapshot();
    });
    this._snapshotChipEl = chip;
    return chip;
  }

  // The card's own snapshot button: an explicit request, so the Snapshots
  // master switch does not apply, but a press still starts the per-camera
  // throttle window (see async_request_snapshot in the integration).
  async _requestSnapshot() {
    if (this._snapshotting || !this._hass) return;
    const entity = this._entityId();
    if (!entity) return;
    this._snapshotting = true;
    this._snapshotChipEl?.classList.add("busy");
    if (this._snapshotChipEl) this._snapshotChipEl.disabled = true;
    try {
      await this._hass.callService(
        "ezviz_rtsp",
        "capture_picture",
        {},
        { entity_id: entity }
      );
    } catch (err) {
      console.debug(`[ezviz-video-card] ${entity}: ${err?.message || err}`);
    } finally {
      this._snapshotting = false;
      if (this._snapshotChipEl?.isConnected) {
        this._snapshotChipEl.classList.remove("busy");
        this._snapshotChipEl.disabled = false;
      }
    }
  }

  // -- playback ------------------------------------------------------------

  _maybeAutoPlay() {
    if (
      this._config &&
      this._config.auto_play &&
      this.isConnected &&
      this._state === "idle" &&
      !this._video
    ) {
      this._play();
    }
  }

  async _play() {
    if (this._state === "loading" || this._state === "playing") return;
    const gen = ++this._gen;
    this._state = "loading";
    this._message = "";
    this._render();

    const lang = this._lang;
    // Refresh the device list on every play: it carries the serial -> entity map
    // and a freshly signed picture URL (the previous one may have expired).
    await this._loadDevices(true);
    if (gen !== this._gen) return;
    let entity = this._entityId();
    if (!entity) entity = this._findDevice()?.entity_id || null;
    if (!entity) {
      this._fail(t(lang, "no_entity"));
      return;
    }

    // Prefer the integration's own MJPEG: it appears a few seconds after the
    // camera wakes, while Home Assistant's HLS waits for its stream worker to
    // build segments (a much longer first start). HLS stays the fallback.
    const mjpeg = this._findDevice()?.mjpeg_url;
    if (mjpeg) {
      this._startMjpeg(gen, lang, entity, new URL(mjpeg, window.location.origin).toString());
    } else {
      await this._startHls(gen, lang, entity);
    }
  }

  _startMjpeg(gen, lang, entity, url) {
    const img = document.createElement("img");
    img.className = "live";
    img.alt = "";
    // 'load' fires when the first frame of the multipart stream is in; the open
    // connection then keeps replacing the picture as the camera sends more.
    img.addEventListener("load", () => this._onStarted(gen, lang));
    img.addEventListener("error", () => {
      if (gen === this._gen) this._fail(t(lang, "could_not_start", { msg: "MJPEG" }));
    });
    this._video = img;
    this._state = "playing";
    this._render();
    img.src = url;
    this._startupTimer = setTimeout(() => {
      if (gen !== this._gen || this._started) return;
      this._fail(t(lang, "no_start"));
    }, STARTUP_SECONDS * 1000);
  }

  async _startHls(gen, lang, entity) {
    let stream;
    try {
      stream = await this._hass.callWS({
        type: "camera/stream",
        entity_id: entity,
        format: "hls",
      });
    } catch (err) {
      if (gen !== this._gen) return;
      this._fail(t(lang, "could_not_start", { msg: err.message || err.code || err }));
      return;
    }
    if (gen !== this._gen || !this.isConnected) return;

    const video = document.createElement("video");
    video.muted = true;
    video.autoplay = true;
    video.playsInline = true;
    video.controls = true;
    // A pause while the card is on screen is the user's (video controls); a
    // pause while it is off screen is the browser's and must be undone.
    video.addEventListener("pause", () => {
      if (this._video === video && this._started && this._state === "playing" && this._isVisible()) {
        this._userPaused = true;
      }
    });
    video.addEventListener("play", () => {
      this._userPaused = false;
    });
    video.addEventListener("canplay", () => {
      if (this._video === video) video.play().catch(() => {});
    });
    this._video = video;
    this._state = "playing";
    this._render();

    const url = new URL(stream.url, window.location.origin).toString();
    // Prefer hls.js whenever Media Source Extensions are available, exactly as
    // Home Assistant's own ha-hls-player does. Chromium browsers (Brave among
    // them) answer canPlayType("application/vnd.apple.mpegurl") with "maybe"
    // yet cannot demux the stream (DEMUXER_ERROR_COULD_NOT_PARSE), so the
    // browser's native HLS must be the fallback, never the first choice.
    let useNative = false;
    try {
      const Hls = await loadHls();
      if (gen !== this._gen) return;
      if (Hls.isSupported()) {
        // The same settings Home Assistant's own player uses, which start the
        // picture as soon as the first fragment is buffered.
        const hls = new Hls({
          backBufferLength: 60,
          fragLoadingTimeOut: 30000,
          manifestLoadingTimeOut: 30000,
          levelLoadingTimeOut: 30000,
          maxLiveSyncPlaybackRate: 2,
          liveSyncDurationCount: 2,
          lowLatencyMode: true,
        });
        let started = false;
        hls.on(Hls.Events.ERROR, (_event, data) => {
          if (data.fatal && !started && gen === this._gen) {
            this._fail(t(lang, "could_not_start", { msg: data.details }));
          }
        });
        hls.on(Hls.Events.FRAG_LOADED, () => {
          started = true;
        });
        hls.loadSource(url);
        hls.attachMedia(video);
        this._hls = hls;
      } else {
        useNative = true;
      }
    } catch {
      // hls.js could not be fetched; fall back to the browser's own player.
      useNative = true;
    }
    if (useNative) video.src = url;

    // The first frame can take a while on a battery camera; only then does the
    // max_seconds countdown start, so a short limit never cuts off the wake-up.
    const onStarted = () => this._onStarted(gen, lang);
    video.addEventListener("playing", onStarted);
    video.addEventListener("loadeddata", onStarted);
    video.play().catch(() => {});
    this._startupTimer = setTimeout(() => {
      if (gen !== this._gen || this._started) return;
      this._fail(t(lang, "no_start"));
    }, STARTUP_SECONDS * 1000);
  }

  _onStarted(gen, lang) {
    if (gen !== this._gen || this._started) return;
    this._started = true;
    clearTimeout(this._startupTimer);
    this._startupTimer = null;
    console.info(`[ezviz-video-card] v${CARD_VERSION} streaming`, this._entityId() || this._config.serial);
    if (this._header) {
      this._header.dot.classList.add("on");
      this._header.status.textContent = t(lang, "live");
    }
    const configured = Number(this._config.max_seconds) || 0;
    if (configured > 0) {
      // Back to the last picture and the play button, quietly - an auto-stop is
      // expected, not an error, so nothing is written over the card.
      this._timer = setTimeout(() => this._stop(true), configured * 1000);
    }
  }

  _fail(message) {
    console.warn(`[ezviz-video-card] v${CARD_VERSION}`, message);
    this._stop();
    this._state = "idle";
    this._message = message;
    this._render();
  }

  _stop(render = false, message = "") {
    this._gen += 1; // abandon any open that is still in flight
    clearTimeout(this._timer);
    this._timer = null;
    clearTimeout(this._startupTimer);
    this._startupTimer = null;
    this._started = false;
    this._hls?.destroy();
    this._hls = null;
    if (this._video) {
      try {
        if (typeof this._video.pause === "function") this._video.pause();
        this._video.removeAttribute("src");
        if (typeof this._video.load === "function") this._video.load();
      } catch {
        /* ignore */
      }
      this._video.remove();
      this._video = null;
    }
    if (render && this._config) {
      this._state = "idle";
      this._message = message;
      this._render();
    }
  }
}

function createStyle(css) {
  const el = document.createElement("style");
  el.textContent = css;
  return el;
}

class EzvizVideoCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._loadDevices();
  }

  async _loadDevices() {
    if (this._devices || !this._hass) return;
    try {
      this._devices = await this._hass.callWS({ type: "ezviz_rtsp/devices" });
    } catch {
      this._devices = [];
    }
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    const lang = pickLang(this._hass);
    const options = (this._devices || []).map((d) => ({
      value: d.serial,
      label: `${d.name} (${d.serial})${d.battery ? " 🔋" : ""}`,
    }));
    const schema = [
      { name: "serial", selector: { select: { options, mode: "dropdown" } } },
      { name: "title", selector: { text: {} } },
      { name: "icon", selector: { icon: {} } },
      { name: "auto_play", selector: { boolean: {} } },
      { name: "capture_on_load", selector: { boolean: {} } },
      {
        name: "max_seconds",
        selector: { number: { min: 0, max: 600, mode: "box", unit_of_measurement: "s" } },
      },
      {
        name: "picture",
        selector: {
          select: {
            mode: "dropdown",
            options: [
              { value: "motion", label: t(lang, "picture_motion") },
              { value: "snapshot", label: t(lang, "picture_snapshot") },
              { value: "newest", label: t(lang, "picture_newest") },
            ],
          },
        },
      },
      { name: "hide_play", selector: { boolean: {} } },
      { name: "hide_stop", selector: { boolean: {} } },
      { name: "hide_snapshot", selector: { boolean: {} } },
      { name: "show_timestamp", selector: { boolean: {} } },
    ];
    // Reuse the same <ha-form>. Lovelace calls setConfig() after every change;
    // replacing the form then would collapse the dialog and jump its scroll
    // position back to the top.
    let form = this._form;
    if (!form) {
      form = document.createElement("ha-form");
      this._form = form;
      form.addEventListener("value-changed", (event) => {
        this._config = event.detail.value;
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: this._config },
            bubbles: true,
            composed: true,
          })
        );
      });
      this.replaceChildren(form);
    }
    form.hass = this._hass;
    // Rebuild the fields only when the camera list or language changes; a new
    // schema on every keystroke would re-render them and steal the focus.
    const schemaKey = `${lang}|${(this._devices || []).map((d) => d.serial).join(",")}`;
    if (this._schemaKey !== schemaKey) {
      form.schema = schema;
      form.computeLabel = (field) => t(lang, field.name);
      form.computeHelper = (field) =>
        field.name === "picture" ? t(lang, "picture_helper") : "";
      this._schemaKey = schemaKey;
    }
    form.data = { ...CARD_DEFAULTS, ...this._config };
  }
}

// -- snapshot card ----------------------------------------------------------
//
//   type: custom:ezviz-snapshot-card
//   entity: camera.front     # the camera (required)
//   image: image.front_snap  # optional; found from the camera's device when left out
//   title: Front door        # optional; defaults to the camera's name
//   capture_on_load: false   # optional; true = take a new picture when the card comes into view
//   min_interval: 600        # optional; seconds — overrides the integration's Snapshots setting
//
// Shows the camera's Snapshot image (the picture taken by capture_picture). Like
// the video card's auto_play, capture_on_load is off by default, so showing the
// card never wakes a battery camera unless asked to. With capture_on_load on, it
// calls capture_picture each time the card comes into view:
// the dashboard view opens, the browser tab returns, the app comes back to the
// front. The call is marked automatic, so it follows the integration's
// Configure → Snapshots options: it is skipped when automatic snapshots are off,
// and the server keeps the minimum time between pictures per camera (min_interval
// in the card overrides it), so several open dashboards still wake a camera only
// once per interval. A camera slow to wake (EZVIZ 2009) is retried by the
// service itself. Tapping the picture opens the image's more-info dialog.

const snapshotStyle = /* css */ `
  :host { display: block; }
  ha-card { overflow: hidden; position: relative; cursor: pointer; }
  .pic { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: cover; background: var(--secondary-background-color, #222); }
  .empty { display: flex; align-items: center; justify-content: center; width: 100%; aspect-ratio: 16 / 9;
    color: var(--secondary-text-color); background: var(--secondary-background-color, #222); font-size: 0.9em; }
  .bar { position: absolute; left: 0; right: 0; bottom: 0; display: flex; align-items: center; gap: 8px;
    padding: 8px 12px; color: #fff; background: rgba(0, 0, 0, 0.45); font-size: 14px; }
  .bar .name { flex: 1 1 auto; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 500; }
  .bar .when { flex: 0 0 auto; opacity: 0.85; font-size: 12px; }
  .spin { flex: 0 0 auto; width: 14px; height: 14px; border-radius: 50%; border: 2px solid rgba(255, 255, 255, 0.35);
    border-top-color: #fff; animation: spin 900ms linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
`;

class EzvizSnapshotCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._capturing = false;
    this._visible = false;
    // The resolved Snapshot image entity, and the hass.entities object it was
    // resolved from (the frontend replaces that object when the registry changes).
    this._image = undefined;
    this._imageFrom = undefined;
  }

  static getStubConfig() {
    return { entity: "", capture_on_load: false };
  }

  setConfig(config) {
    if (!config || !config.entity || !String(config.entity).startsWith("camera.")) {
      throw new Error("ezviz-snapshot-card: 'entity' (a camera.* entity) is required");
    }
    this._config = { capture_on_load: false, ...config };
    this._imageFrom = undefined; // the camera may have changed: resolve again
    this._render();
  }

  set hass(hass) {
    const old = this._hass;
    this._hass = hass;
    if (!this._config) return;
    const image = this._imageEntity();
    if (!old || !image || old.states[image] !== hass.states[image] ||
        old.states[this._config.entity] !== hass.states[this._config.entity]) {
      this._render();
    }
  }

  getCardSize() {
    return 4;
  }

  connectedCallback() {
    if (!this._visTimer) this._visTimer = setInterval(() => this._syncVisibility(), 1000);
    if (!this._io && "IntersectionObserver" in window) {
      // Scrolled-off cards must not count as "the dashboard shows the camera".
      this._io = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) this._intersecting = entry.isIntersecting;
          this._syncVisibility();
        },
        { threshold: 0 }
      );
      this._io.observe(this);
    }
    if (!this._onDocVisibility) {
      this._onDocVisibility = () => this._syncVisibility();
      document.addEventListener("visibilitychange", this._onDocVisibility);
    }
    this._syncVisibility();
  }

  disconnectedCallback() {
    queueMicrotask(() => {
      if (this.isConnected) return;
      clearInterval(this._visTimer);
      this._visTimer = null;
      this._io?.disconnect();
      this._io = null;
      if (this._onDocVisibility) {
        document.removeEventListener("visibilitychange", this._onDocVisibility);
        this._onDocVisibility = null;
      }
      this._visible = false;
    });
  }

  // The Snapshot image on the camera's device, unless the config names one. The
  // scan over the entity registry runs only when the registry object changes, not
  // on every state update.
  _imageEntity() {
    if (this._config?.image) return this._config.image;
    const entities = this._hass?.entities;
    if (!entities) return undefined;
    if (entities === this._imageFrom) return this._image;
    this._imageFrom = entities;
    const cam = entities[this._config?.entity];
    const match = cam?.device_id && Object.values(entities).find(
      (e) => e.device_id === cam.device_id && e.entity_id.startsWith("image.") &&
        (e.translation_key === "snapshot" || e.entity_id.endsWith("_snapshot"))
    );
    this._image = match ? match.entity_id : undefined;
    return this._image;
  }

  // Shown on screen: a hidden tab, another dashboard view (removed or kept laid
  // out at zero size) and display:none all count as not visible. Scrolling does
  // not: the card's view being open is what "loaded" means here.
  _isVisible() {
    if (!this.isConnected || document.hidden) return false;
    if (this._intersecting === false) return false;
    const rect = this.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    const style = getComputedStyle(this);
    return style.display !== "none" && style.visibility !== "hidden";
  }

  _syncVisibility() {
    if (!this._config) return;
    const visible = this._isVisible();
    if (visible === this._visible) return;
    this._visible = visible;
    if (visible && this._config.capture_on_load) this._capture();
  }

  _serviceData() {
    const data = { automatic: true };
    const own = this._config.min_interval;
    if (own !== undefined && own !== null && own !== "") data.min_interval = Number(own) || 0;
    return data;
  }

  async _capture() {
    if (this._capturing || !this._hass) return;
    const cam = this._hass.states[this._config.entity];
    if (!cam || cam.state === "unavailable" || cam.state === "unknown") return;
    this._capturing = true;
    this._render();
    try {
      await this._hass.callService(
        "ezviz_rtsp",
        "capture_picture",
        this._serviceData(),
        { entity_id: this._config.entity }
      );
    } catch (err) {
      console.debug(`[ezviz-snapshot-card] ${this._config.entity}: ${err?.message || err}`);
    } finally {
      this._capturing = false;
      this._render();
    }
  }

  _render() {
    if (!this._config) return;
    const hass = this._hass;
    const image = this._imageEntity();
    const img = image && hass?.states[image];
    const cam = hass?.states[this._config.entity];
    const name = this._config.title || cam?.attributes?.friendly_name || this._config.entity;
    // The proxy URL exists even when the image entity is still empty after a
    // restart; show "No snapshot yet" instead of a broken/black frame.
    const hasPicture = img && img.state !== "unknown" && img.state !== "unavailable";
    const picture = hasPicture ? img.attributes?.entity_picture : undefined;
    const when = img && !["unknown", "unavailable"].includes(img.state)
      ? new Date(img.state).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : "";
    // The image proxy URL keeps its token between pictures; add the state so a
    // new picture is never served from the browser cache.
    const src = picture ? `${picture}${picture.includes("?") ? "&" : "?"}s=${encodeURIComponent(img.state)}` : "";
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
    this.shadowRoot.innerHTML = `
      <style>${snapshotStyle}</style>
      <ha-card>
        ${src ? `<img class="pic" src="${esc(src)}" alt="${esc(name)}">` : `<div class="empty">No snapshot yet</div>`}
        <div class="bar">
          <span class="name">${esc(name)}</span>
          ${this._capturing ? `<span class="spin" title="Taking a picture"></span>` : ""}
          <span class="when">${esc(when)}</span>
        </div>
      </ha-card>`;
    this.shadowRoot.querySelector("ha-card").onclick = () => {
      if (!image) return;
      this.dispatchEvent(new CustomEvent("hass-more-info", {
        bubbles: true, composed: true, detail: { entityId: image },
      }));
    };
  }
}

// -- recordings card -----------------------------------------------------------
//
//   type: custom:ezviz-recordings-card
//   entity: camera.driveway_gate  # or serial: BB1234567
//   title: Driveway gate          # optional; defaults to "<camera> recordings"
//   format: auto                  # optional; auto, h264 or hevc (see below)
//   max_height: 360               # optional; height of the list in pixels
//
// Lists one day of the camera's SD-card recordings (newest first, today by
// default, with buttons for earlier days) and plays the one you tap in the
// card's own player. Listing only reads the SD index; a recording is fetched
// from the camera — waking a battery camera — only when it is tapped.
//
// The camera records HEVC. "auto" asks for it as is when the browser can play
// HEVC (Safari, most Chrome/Edge on Windows and macOS) and for an H.264 copy
// converted by Home Assistant otherwise; if the HEVC copy fails to play the
// card asks for H.264 once.

const recordingsStyle = /* css */ `
  .days { display: flex; align-items: center; gap: 2px; flex: 0 0 auto; }
  .iconbtn {
    border: 0; background: none; color: var(--secondary-text-color);
    width: 34px; height: 34px; border-radius: 50%; cursor: pointer;
    display: inline-flex; align-items: center; justify-content: center;
    --mdc-icon-size: 20px; padding: 0;
  }
  .iconbtn:hover:not([disabled]) { background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); }
  .iconbtn[disabled] { opacity: 0.35; cursor: default; }
  .iconbtn.spinning ha-icon { animation: spin 900ms linear infinite; }
  .media .close { position: absolute; top: 8px; right: 8px; z-index: 3; }
  .media .close.iconbtn { color: #fff; background: color-mix(in srgb, #000 55%, transparent); width: 30px; height: 30px; }
  .list {
    overflow-y: auto; border-radius: 12px;
    border: 1px solid var(--divider-color, rgba(127,127,127,.25));
  }
  .hour {
    position: sticky; top: 0; z-index: 1;
    font-size: 11px; font-weight: 500; letter-spacing: .04em;
    padding: 4px 12px; color: var(--secondary-text-color);
    background: var(--ha-card-background, var(--card-background-color, #fff));
    border-bottom: 1px solid var(--divider-color, rgba(127,127,127,.2));
  }
  .row {
    display: flex; align-items: center; gap: 10px; width: 100%;
    padding: 8px 12px; border: 0; background: none; cursor: pointer;
    font: inherit; font-size: 14px; color: var(--primary-text-color); text-align: left;
  }
  .row + .row { border-top: 1px solid var(--divider-color, rgba(127,127,127,.12)); }
  .row:hover { background: color-mix(in srgb, var(--primary-color) 8%, transparent); }
  .row.on { background: color-mix(in srgb, var(--primary-color) 16%, transparent); }
  .row ha-icon { --mdc-icon-size: 18px; color: var(--primary-color); flex: 0 0 auto; }
  .row .time { font-variant-numeric: tabular-nums; flex: 1 1 auto; }
  .row .len { font-size: 12px; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .note { padding: 16px 12px; text-align: center; font-size: 13px; color: var(--secondary-text-color); }
  .note.error { color: var(--error-color, #db4437); }
`;

// Whether this browser plays HEVC in MP4 (the camera's own format).
const playsHevc = () => {
  try {
    const video = document.createElement("video");
    return ["hvc1.1.6.L120.90", "hev1.1.6.L120.90"].some(
      (codec) => video.canPlayType(`video/mp4; codecs="${codec}"`) !== ""
    );
  } catch {
    return false;
  }
};

const localDay = (date) => {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
};

class EzvizRecordingsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._lang = "en";
    this._day = null; // YYYY-MM-DD; null = today (as the server sees it)
    this._today = null;
    this._list = null; // { recordings, complete, date }
    this._listing = false;
    this._listError = "";
    this._selected = null; // the recording being played
    this._clipState = "idle"; // idle | fetching | playing | error
    this._clipError = "";
    // Bumped so a stale answer never lands after a newer request.
    this._listGen = 0;
    this._clipGen = 0;
    this._shown = false;
  }

  static getStubConfig() {
    return { entity: "" };
  }

  setConfig(config) {
    if (!config || (!config.serial && !config.entity)) {
      throw new Error("ezviz-recordings-card: 'entity' (or 'serial') is required");
    }
    this._config = { format: "auto", max_height: 360, ...config };
    this._device = undefined;
    this._list = null;
    this._day = null;
    this._closePlayer();
    this._render();
    if (this._shown) this._load();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const lang = pickLang(hass);
    if (!this._devices) this._loadDevices();
    if (first || lang !== this._lang) {
      this._lang = lang;
      this._render();
    }
  }

  getCardSize() {
    return 8;
  }

  connectedCallback() {
    if (!this._visTimer) this._visTimer = setInterval(() => this._syncVisibility(), 1000);
    this._syncVisibility();
  }

  disconnectedCallback() {
    queueMicrotask(() => {
      if (this.isConnected) return;
      clearInterval(this._visTimer);
      this._visTimer = null;
      this._shown = false;
      this._video()?.pause();
    });
  }

  // The list is read the first time the card is on screen, never for a card
  // sitting on a view nobody opened. A hidden card pauses its player.
  _syncVisibility() {
    if (!this._config) return;
    const rect = this.getBoundingClientRect();
    const visible = this.isConnected && !document.hidden && rect.width > 0 && rect.height > 0;
    if (visible && !this._shown) {
      this._shown = true;
      if (!this._list && !this._listing) this._load();
    } else if (!visible && this._shown) {
      this._shown = false;
      this._video()?.pause();
    }
  }

  async _loadDevices() {
    if (!this._hass || this._devicesLoading) return;
    this._devicesLoading = true;
    try {
      this._devices = await this._hass.callWS({ type: "ezviz_rtsp/devices" });
    } catch {
      this._devices = [];
    } finally {
      this._devicesLoading = false;
    }
    this._device = undefined;
    this._render();
    if (this._shown && !this._list && !this._listing) this._load();
  }

  _resolveDevice() {
    if (this._device !== undefined) return this._device;
    if (!this._devices) return undefined;
    const { serial, entity } = this._config;
    this._device =
      this._devices.find((d) => (serial && d.serial === serial) || (entity && d.entity_id === entity)) ||
      null;
    return this._device;
  }

  _serial() {
    return this._config.serial || this._resolveDevice()?.serial;
  }

  _name() {
    const cam = this._config.entity && this._hass?.states[this._config.entity];
    return this._resolveDevice()?.name || cam?.attributes?.friendly_name || this._serial() || "";
  }

  async _load(refresh = false) {
    const serial = this._serial();
    if (!serial || !this._hass) return;
    const gen = ++this._listGen;
    this._listing = true;
    this._listError = "";
    this._render();
    try {
      const msg = { type: "ezviz_rtsp/recordings", serial, refresh };
      if (this._day) msg.date = this._day;
      const result = await this._hass.callWS(msg);
      if (gen !== this._listGen) return;
      this._list = result;
      this._today = result.today;
      this._day = result.date;
    } catch (err) {
      if (gen !== this._listGen) return;
      this._list = null;
      this._listError = err?.message || String(err);
    } finally {
      if (gen === this._listGen) {
        this._listing = false;
        this._render();
      }
    }
  }

  _shiftDay(days) {
    const base = this._day || this._today || localDay(new Date());
    const [y, m, d] = base.split("-").map(Number);
    const next = localDay(new Date(y, m - 1, d + days));
    if (this._today && next > this._today) return;
    this._day = next;
    this._list = null;
    this._load();
  }

  _format(fallback = false) {
    const wanted = this._config.format;
    if (fallback || wanted === "h264") return "h264";
    if (wanted === "hevc") return "hevc";
    return playsHevc() ? "hevc" : "h264";
  }

  async _play(rec, fallback = false) {
    const serial = this._serial();
    if (!serial || !rec) return;
    const gen = ++this._clipGen;
    // A detached <video> keeps playing its sound: stop the old clip first.
    this._video()?.pause();
    this._selected = rec;
    this._clipState = "fetching";
    this._clipError = "";
    this._render();
    const format = this._format(fallback);
    try {
      const result = await this._hass.callWS({
        type: "ezviz_rtsp/recording/clip",
        serial,
        begin: rec.begin,
        end: rec.end,
        format,
      });
      if (gen !== this._clipGen) return;
      this._clipState = "playing";
      this._clipFormat = format;
      this._render();
      const video = this._video();
      if (video) {
        video.src = result.url;
        video.onerror = () => {
          // A browser that claimed HEVC but can't decode it gets the H.264 copy.
          if (this._clipFormat === "hevc" && this._selected === rec) this._play(rec, true);
        };
        video.play().catch(() => {});
      }
    } catch (err) {
      if (gen !== this._clipGen) return;
      this._clipState = "error";
      this._clipError = err?.message || String(err);
      this._render();
    }
  }

  _closePlayer() {
    this._clipGen++;
    const video = this._video();
    if (video) {
      video.pause();
      video.removeAttribute("src");
      video.load();
    }
    this._selected = null;
    this._clipState = "idle";
    this._clipError = "";
  }

  _video() {
    return this.shadowRoot?.querySelector("video");
  }

  _dayLabel() {
    const lang = this._lang;
    const day = this._day || this._today;
    if (!day) return "";
    if (day === this._today) return t(lang, "rec_today");
    const [y, m, d] = day.split("-").map(Number);
    const date = new Date(y, m - 1, d);
    const [ty, tm, td] = (this._today || localDay(new Date())).split("-").map(Number);
    if (new Date(ty, tm - 1, td - 1).getTime() === date.getTime()) return t(lang, "rec_yesterday");
    return date.toLocaleDateString(this._hass?.locale?.language || undefined, {
      weekday: "short", day: "numeric", month: "short",
    });
  }

  _render() {
    if (!this._config || !this.shadowRoot) return;
    const lang = this._lang;
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
    const name = this._config.title || t(lang, "rec_title", { name: this._name() });
    const list = this._list;
    const count = list ? list.recordings.length : 0;
    let secondary = this._dayLabel();
    if (list) {
      secondary += ` · ${t(lang, list.complete ? "rec_count" : "rec_partial", { n: count })}`;
    }
    const atToday = !this._today || (this._day || this._today) >= this._today;

    // Keep a playing <video> element (and its position) across re-renders.
    const keep = this._clipState === "playing" ? this._video() : null;
    const media = this._selected
      ? `<div class="media">
          ${this._clipState === "playing" ? `<span class="slot"></span>` : `<div class="poster"></div>`}
          ${this._clipState === "fetching" ? `<div class="message">${esc(t(lang, "rec_fetching"))}</div><div class="spinner"></div>` : ""}
          ${this._clipState === "error" ? `<div class="message">${esc(this._clipError)}</div>` : ""}
          <button class="iconbtn close" title="${esc(t(lang, "rec_close"))}"><ha-icon icon="mdi:close"></ha-icon></button>
        </div>`
      : "";

    let body;
    if (this._listError) {
      body = `<div class="note error">${esc(t(lang, "rec_failed", { msg: this._listError }))}</div>`;
    } else if (!list) {
      body = `<div class="note">${esc(t(lang, "rec_loading"))}</div>`;
    } else if (!count) {
      body = `<div class="note">${esc(t(lang, "rec_none"))}</div>`;
    } else {
      let hour = null;
      const rows = [];
      list.recordings.forEach((rec, i) => {
        const start = new Date(rec.start);
        const h = start.getHours();
        if (h !== hour) {
          hour = h;
          rows.push(`<div class="hour">${String(h).padStart(2, "0")}:00</div>`);
        }
        const time = start.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        const on = this._selected && this._selected.begin === rec.begin && this._selected.end === rec.end;
        rows.push(`<button class="row${on ? " on" : ""}" data-i="${i}">
          <ha-icon icon="${on ? "mdi:play-circle" : "mdi:play-circle-outline"}"></ha-icon>
          <span class="time">${esc(time)}</span><span class="len">${rec.seconds} s</span>
        </button>`);
      });
      body = rows.join("");
    }

    this.shadowRoot.innerHTML = `
      <style>${style}${recordingsStyle}</style>
      <ha-card>
        <div class="wrap">
          <div class="header">
            <div class="tile${this._listError ? " error" : ""}"><ha-icon icon="mdi:filmstrip-box-multiple"></ha-icon></div>
            <div class="info">
              <div class="primary">${esc(name)}</div>
              <div class="secondary">${esc(secondary)}</div>
            </div>
            <div class="days">
              <button class="iconbtn prev" title="${esc(t(lang, "rec_prev"))}"><ha-icon icon="mdi:chevron-left"></ha-icon></button>
              <button class="iconbtn next" title="${esc(t(lang, "rec_next"))}" ${atToday ? "disabled" : ""}><ha-icon icon="mdi:chevron-right"></ha-icon></button>
              <button class="iconbtn refresh${this._listing ? " spinning" : ""}" title="${esc(t(lang, "rec_refresh"))}"><ha-icon icon="mdi:refresh"></ha-icon></button>
            </div>
          </div>
          ${media}
          <div class="list" style="max-height:${Number(this._config.max_height) || 360}px">${body}</div>
        </div>
      </ha-card>`;

    const slot = this.shadowRoot.querySelector(".slot");
    if (slot) {
      const video = keep || document.createElement("video");
      video.controls = true;
      video.playsInline = true;
      video.setAttribute("playsinline", "");
      video.className = "live";
      slot.replaceWith(video);
    }
    const root = this.shadowRoot;
    root.querySelector(".prev").onclick = () => this._shiftDay(-1);
    root.querySelector(".next").onclick = () => this._shiftDay(1);
    root.querySelector(".refresh").onclick = () => this._load(true);
    const close = root.querySelector(".close");
    if (close) close.onclick = () => { this._closePlayer(); this._render(); };
    root.querySelectorAll(".row").forEach((row) => {
      row.onclick = () => this._play(list.recordings[Number(row.dataset.i)]);
    });
  }
}

// Announce the cards to the picker. The frontend may replace window.customCards
// while it boots, so register defensively and re-register if it goes missing.
const CARD_INFO = {
  type: "ezviz-video-card",
  name: "EZVIZ Video",
  description: "Live view of an EZVIZ camera through the EZVIZ cloud",
  preview: true,
};
const SNAPSHOT_CARD_INFO = {
  type: "ezviz-snapshot-card",
  name: "EZVIZ Snapshot",
  description: "An EZVIZ camera's on-demand snapshot, optionally taken when the card comes into view",
  preview: false,
};

const RECORDINGS_CARD_INFO = {
  type: "ezviz-recordings-card",
  name: "EZVIZ Recordings",
  description: "An EZVIZ camera's SD-card recordings by day, played in the card",
  preview: false,
};

const registerCard = () => {
  window.customCards = window.customCards || [];
  for (const info of [CARD_INFO, SNAPSHOT_CARD_INFO, RECORDINGS_CARD_INFO]) {
    if (!window.customCards.some((c) => c && c.type === info.type)) {
      window.customCards.push(info);
    }
  }
};

// The integration loads this file from the page head, so it often runs before
// the frontend swaps window.customElements for its scoped-registry polyfill.
// Define on the current registry now and again on any registry that replaces it
// while the page boots; the frontend re-renders the card once it is defined.
const define = () => {
  registerCard();
  if (!window.customElements.get("ezviz-video-card")) {
    window.customElements.define("ezviz-video-card", EzvizVideoCard);
  }
  if (!window.customElements.get("ezviz-video-card-editor")) {
    window.customElements.define("ezviz-video-card-editor", EzvizVideoCardEditor);
  }
  if (!window.customElements.get("ezviz-snapshot-card")) {
    window.customElements.define("ezviz-snapshot-card", EzvizSnapshotCard);
  }
  if (!window.customElements.get("ezviz-recordings-card")) {
    window.customElements.define("ezviz-recordings-card", EzvizRecordingsCard);
  }
};
define();
console.info(`[ezviz-video-card] loaded v${CARD_VERSION} (custom:ezviz-video-card)`);
const watchRegistry = setInterval(define, 100);
setTimeout(() => clearInterval(watchRegistry), 30000);
