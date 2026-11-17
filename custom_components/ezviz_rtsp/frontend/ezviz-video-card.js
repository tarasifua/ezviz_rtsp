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
//   show_battery: true     # optional; false hides the battery level
//   hide_recordings: false # optional; hide the recordings button
//   save_recordings: true  # optional; false keeps watched clips out of media
//
// The card shows the camera's live picture from the integration's own stream:
// its fast MJPEG path (an <img> that appears a few seconds after the camera
// wakes) with Home Assistant's HLS as the fallback. It is styled after Mushroom
// cards — rounded card, an icon tile, and a small play/stop chip in the corner
// of the picture — but needs neither Mushroom nor any other frontend dependency.
// hls.js is bundled with the integration and served from its own path, so no
// code is ever loaded from a CDN.
//
// The filmstrip button next to the battery level switches the card to the
// camera's SD-card recordings: the current picture stays on screen until a
// recording is picked, then plays it in the same media area. The list is read
// only when the mode is opened (listing wakes a battery camera), and the live
// view is stopped first — the camera cannot stream and read its SD card at the
// same time. Press the button again to go back to the live view.
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
    "waiting_download": "Waiting for the download to finish…",
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
    "show_battery": "Show the battery level",
    "hide_recordings": "Hide the recordings button",
    "save_recordings": "Save watched recordings",
    "save_recordings_helper": "Keep the clips you play in the media folder. When off, a watched recording is downloaded to a temporary folder, deleted after about two hours, and never appears under Media.",
    "section_camera": "Camera",
    "section_playback": "Playback",
    "section_picture": "Picture and snapshots",
    "section_buttons": "Buttons and battery",
    "section_recordings": "Recordings",
    "recordings": "Recordings",
    "recordings_show": "Show the camera's recordings",
    "recordings_hide": "Back to the live view",
    "rec_today": "Today",
    "rec_yesterday": "Yesterday",
    "rec_count": "{n} recordings",
    "rec_none": "No recordings on this day",
    "rec_partial": "{n}+ recordings (list cut short)",
    "rec_loading": "Reading the SD card…",
    "rec_fetching": "Fetching the recording from the camera…",
    "rec_redownloading": "The saved recording is incomplete — downloading it again…",
    "rec_queued": "Waiting for the current recording to finish…",
    "rec_waiting_camera": "Waiting for the camera to send it…",
    "rec_converting": "Converting the recording…",
    "rec_progress": "{have} / {total} s",
    "rec_failed": "{msg}",
    "rec_refresh": "Refresh",
    "rec_close": "Close player",
    "rec_cloud": "On the camera's SD card (not saved locally)",
    "rec_local": "Saved in the media folder",
    "rec_incomplete": "The saved copy is incomplete; it will be downloaded again",
    "rec_calendar": "Pick a day",
    "rec_prev_month": "Previous month",
    "rec_next_month": "Next month",
    "rec_scan": "Check the SD card for this month",
    "rec_scanning": "Checking the SD card…",
    "rec_scanned": "SD card checked {when}",
    "rec_scan_partial": "SD card checked partly {when} — check again for the rest",
    "rec_scan_never": "SD-card days are unknown until the month is checked",
    "rec_legend_local": "Green: saved in the media folder",
    "rec_legend_card": "Blue: on the camera's SD card",
    "rec_scan_failed": "Could not check the SD card: {msg}"
  },
  "uk": {
    "play": "Дивитися",
    "stop": "Зупинити",
    "starting": "Прокидаємо камеру…",
    "waiting_download": "Очікування завершення завантаження…",
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
    "show_battery": "Показувати заряд батареї",
    "hide_recordings": "Приховати кнопку записів",
    "save_recordings": "Зберігати переглянуті записи",
    "save_recordings_helper": "Зберігати відтворені кліпи в media. Якщо вимкнено, запис тимчасово завантажується, видаляється приблизно через дві години й не зʼявляється в Media.",
    "section_camera": "Камера",
    "section_playback": "Відтворення",
    "section_picture": "Знімок і снапшоти",
    "section_buttons": "Кнопки та батарея",
    "section_recordings": "Записи",
    "recordings": "Записи",
    "recordings_show": "Показати записи камери",
    "recordings_hide": "Повернутися до живого відео",
    "rec_today": "Сьогодні",
    "rec_yesterday": "Вчора",
    "rec_count": "Записів: {n}",
    "rec_none": "Цього дня записів немає",
    "rec_partial": "Записів: {n}+ (список неповний)",
    "rec_loading": "Читаємо SD-картку…",
    "rec_fetching": "Завантажуємо запис із камери…",
    "rec_redownloading": "Збережений запис неповний — завантажуємо його повторно…",
    "rec_queued": "Чекаємо, поки завершиться поточне завантаження…",
    "rec_waiting_camera": "Чекаємо, поки камера надішле запис…",
    "rec_converting": "Перетворюємо запис…",
    "rec_progress": "{have} / {total} с",
    "rec_failed": "{msg}",
    "rec_refresh": "Оновити",
    "rec_close": "Закрити плеєр",
    "rec_cloud": "На SD-картці камери (не збережено локально)",
    "rec_local": "Збережено в media",
    "rec_incomplete": "Збережена копія неповна; запис буде завантажено повторно",
    "rec_calendar": "Вибрати день",
    "rec_prev_month": "Попередній місяць",
    "rec_next_month": "Наступний місяць",
    "rec_scan": "Перевірити SD-картку за цей місяць",
    "rec_scanning": "Перевіряємо SD-картку…",
    "rec_scanned": "SD-картку перевірено {when}",
    "rec_scan_partial": "SD-картку перевірено частково {when} — перевір ще раз",
    "rec_scan_never": "Дні на SD-картці невідомі, поки місяць не перевірено",
    "rec_legend_local": "Зелений: збережено в media",
    "rec_legend_card": "Синій: на SD-картці камери",
    "rec_scan_failed": "Не вдалося перевірити SD-картку: {msg}"
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
  show_battery: true,
  hide_recordings: false,
  save_recordings: true,
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
  .tools { flex: 0 0 auto; display: flex; align-items: center; gap: 2px; }
  .toggle {
    flex: 0 0 auto;
    width: 34px; height: 34px; padding: 0; border: 0; border-radius: 50%;
    display: inline-flex; align-items: center; justify-content: center;
    color: var(--secondary-text-color); background: none; cursor: pointer;
    --mdc-icon-size: 20px;
  }
  .toggle:hover { background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); }
  .toggle.on {
    color: var(--primary-color);
    background: color-mix(in srgb, var(--primary-color) 16%, transparent);
  }
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

  /* SD-card recordings, shown under the picture while the mode is on. */
  .rec { display: flex; flex-direction: column; gap: 8px; }
  .recBar { display: flex; align-items: center; gap: 8px; }
  .recDay {
    flex: 1 1 auto; min-width: 0;
    font-size: 12px; line-height: 16px; color: var(--secondary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .days { flex: 0 0 auto; display: flex; align-items: center; gap: 2px; }
  /* The day picker: a month grid with a dot on every day that has a clip. */
  .calendar {
    border-radius: 12px; padding: 8px 10px 10px;
    border: 1px solid var(--divider-color, rgba(127,127,127,.25));
    display: flex; flex-direction: column; gap: 6px;
  }
  .calHead { display: flex; align-items: center; gap: 4px; }
  .calMonth {
    flex: 1 1 auto; min-width: 0; text-align: center;
    font-size: 13px; font-weight: 500; color: var(--primary-text-color);
  }
  .calGrid {
    display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px;
  }
  .calDow {
    text-align: center; font-size: 10px; line-height: 20px;
    letter-spacing: .04em; text-transform: uppercase;
    color: var(--secondary-text-color);
  }
  .calBlank { height: 30px; }
  .calDay {
    position: relative; height: 30px; padding: 0; border: 0; border-radius: 8px;
    font: inherit; font-size: 12px; cursor: pointer;
    color: var(--primary-text-color); background: none;
  }
  .calDay:hover:not([disabled]) {
    background: color-mix(in srgb, var(--primary-text-color) 8%, transparent);
  }
  .calDay[disabled] { opacity: 0.3; cursor: default; }
  .calDay.today { font-weight: 700; }
  .calDay.on {
    color: var(--text-primary-color, #fff);
    background: var(--primary-color, #03a9f4);
  }
  .calDay .dot {
    position: absolute; left: 50%; bottom: 3px; width: 4px; height: 4px;
    margin-left: -2px; border-radius: 50%;
    /* A thin ring in the card's own colour keeps the dot clear of the day's
       fill when that day is selected (its background is the primary colour), so
       a blue SD dot no longer has to turn pale to stay visible. On an unselected
       day the ring matches the cell's background and is not seen. */
    box-shadow: 0 0 0 1.5px var(--card-background-color, var(--ha-card-background, #fff));
  }
  .calDay .dot.local { background: var(--success-color, #43a047); }
  .calDay .dot.card { background: var(--primary-color, #03a9f4); }
  .calFoot {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    font-size: 11px; line-height: 16px; color: var(--secondary-text-color);
  }
  .calText { flex: 1 1 120px; min-width: 0; }
  .calText.error { color: var(--error-color, #db4437); }
  .calLegend { display: flex; align-items: center; gap: 4px; }
  .calLegend .dot {
    width: 4px; height: 4px; border-radius: 50%; display: inline-block;
  }
  .calLegend .dot.local { background: var(--success-color, #43a047); }
  .calLegend .dot.card { background: var(--primary-color, #03a9f4); }
  .calScan {
    font: inherit; font-size: 11px; padding: 4px 8px; border-radius: 999px;
    border: 1px solid var(--divider-color, rgba(127,127,127,.35));
    background: none; color: var(--primary-color, #03a9f4); cursor: pointer;
  }
  .calScan[disabled] { opacity: 0.5; cursor: default; }
  .iconbtn {
    width: 32px; height: 32px; padding: 0; border: 0; border-radius: 50%;
    display: inline-flex; align-items: center; justify-content: center;
    color: var(--secondary-text-color); background: none; cursor: pointer;
    --mdc-icon-size: 20px;
  }
  .iconbtn:hover:not([disabled]) {
    background: color-mix(in srgb, var(--primary-text-color) 8%, transparent);
  }
  .iconbtn[disabled] { opacity: 0.35; cursor: default; }
  .iconbtn.spinning ha-icon { animation: spin 900ms linear infinite; }
  .iconbtn.on {
    color: var(--primary-color, #03a9f4);
    background: color-mix(in srgb, var(--primary-color, #03a9f4) 12%, transparent);
  }
  .media .recClose {
    position: absolute; top: 8px; right: 8px; z-index: 3;
    width: 30px; height: 30px; color: #fff;
    background: color-mix(in srgb, #000 55%, transparent);
  }
  .recList {
    overflow-y: auto; border-radius: 12px;
    border: 1px solid var(--divider-color, rgba(127,127,127,.25));
  }
  .recHour {
    position: sticky; top: 0; z-index: 1;
    font-size: 11px; font-weight: 500; letter-spacing: .04em;
    padding: 4px 12px; color: var(--secondary-text-color);
    background: var(--ha-card-background, var(--card-background-color, #fff));
    border-bottom: 1px solid var(--divider-color, rgba(127,127,127,.2));
  }
  .recRow {
    display: flex; align-items: center; gap: 10px; width: 100%;
    padding: 8px 12px; border: 0; background: none; cursor: pointer;
    font: inherit; font-size: 14px; color: var(--primary-text-color); text-align: left;
  }
  .recRow + .recRow { border-top: 1px solid var(--divider-color, rgba(127,127,127,.12)); }
  .recRow:hover { background: color-mix(in srgb, var(--primary-color) 8%, transparent); }
  .recRow.on { background: color-mix(in srgb, var(--primary-color) 16%, transparent); }
  .recRow ha-icon { --mdc-icon-size: 18px; color: var(--primary-color); flex: 0 0 auto; }
  .recRow .time { font-variant-numeric: tabular-nums; flex: 1 1 auto; }
  .recRow .len { font-size: 12px; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .recRow .where { --mdc-icon-size: 16px; flex: 0 0 auto; color: var(--secondary-text-color); }
  .recRow .where.local { color: var(--success-color, #43a047); }
  .recRow .where.short { color: var(--warning-color, #ff9800); }
  .recNote { padding: 16px 12px; text-align: center; font-size: 13px; color: var(--secondary-text-color); }
  .recNote.error { color: var(--error-color, #db4437); }

  .spinner {
    position: absolute; right: 10px; bottom: 10px; z-index: 2;
    width: 26px; height: 26px; border-radius: 50%;
    border: 3px solid color-mix(in srgb, #fff 30%, transparent);
    border-top-color: #fff;
    background: color-mix(in srgb, #000 45%, transparent);
    animation: spin 900ms linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Download progress, in the middle of the picture while a clip is fetched. */
  .message .progress {
    display: flex; flex-direction: column; align-items: center; gap: 8px;
    width: min(280px, 82%);
  }
  .message .progress .bar {
    position: relative; width: 100%; height: 6px; border-radius: 999px;
    overflow: hidden; background: color-mix(in srgb, #fff 28%, transparent);
  }
  .message .progress .barFill {
    height: 100%; width: 0; border-radius: 999px; background: #fff;
    transition: width 300ms linear;
  }
  .message .progress .bar.indeterminate .barFill {
    width: 35%; animation: slide 1.2s ease-in-out infinite;
  }
  @keyframes slide {
    0% { margin-left: -35%; }
    100% { margin-left: 100%; }
  }
  .message .progress .hint {
    font-size: 11px; line-height: 14px; opacity: .8;
    font-variant-numeric: tabular-nums; min-height: 14px;
  }
`;

const sameRecording = (a, b) => Boolean(a && b) && a.begin === b.begin && a.end === b.end;

// Two day lists that would paint the same rows. A background check that changes
// nothing must not rebuild the card: doing so while a clip is downloading looks
// like the card reloading itself.
const sameList = (a, b) => {
  if (a === b) return true;
  if (!a || !b) return false;
  if (a.date !== b.date || a.today !== b.today || a.complete !== b.complete) return false;
  const x = a.recordings || [];
  const y = b.recordings || [];
  if (x.length !== y.length) return false;
  for (let i = 0; i < x.length; i++) {
    const p = x[i];
    const q = y[i];
    if (
      p.begin !== q.begin ||
      p.end !== q.end ||
      p.seconds !== q.seconds ||
      Boolean(p.local) !== Boolean(q.local) ||
      Boolean(p.incomplete) !== Boolean(q.incomplete)
    ) {
      return false;
    }
  }
  return true;
};

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
    // The picture box's shape, learned from the camera's own picture before the
    // first clip plays, so the card never changes height under the reader. It
    // also survives a rebuild, so switching a day does not resize the card.
    this._mediaRatio = null; // the applied "w / h" (or "1 / 1" when portrait)
    this._ratioProbe = null; // the poster URL whose size has been measured

    // SD-card recordings mode: the list replaces the live view until the button
    // is pressed again. It is read only when the mode is opened (listing wakes
    // a battery camera), and the live stream is stopped first.
    this._recordings = false;
    this._day = null; // YYYY-MM-DD; null = today (as the server sees it)
    this._today = null;
    this._list = null; // { recordings, complete, date }
    this._listing = false;
    this._listError = "";
    this._listGen = 0;
    this._reads = new Map(); // day reads on their way, shared by quick switches
    this._listScroll = 0; // where the recordings list was scrolled to
    this._listScrollReset = false; // a day change or refresh starts at the top
    this._calendarOpen = false; // the day picker under the bar
    this._calendarMonth = null; // YYYY-MM shown in it; null = the selected day's
    this._days = {}; // YYYY-MM -> { local: [], card: [], scanned, complete }
    this._daysGen = 0;
    this._daysError = "";
    this._scanningDays = false;
    this._selected = null; // the recording in the media area
    this._clipState = "idle"; // idle | fetching | playing | error
    this._clipIncomplete = false; // the saved copy is short: say it is re-fetched
    this._clipFetching = null; // the camera download in flight, if any
    this._queuedClip = null; // the newest tap waiting for that download
    this._clipQueued = false; // the view is waiting, not fetching yet
    this._waitingDownload = false; // live is held back by a clip download
    this._progress = null; // the latest report on the clip being fetched
    this._progressTimer = null;
    this._progressDom = null; // the bar in the media area, updated in place
    this._clipError = "";
    this._clipFormat = "";
    this._clipGen = 0;
    this._clipVideo = null;
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
    const previous = this._config;
    // Play, snapshots and waking the camera are all off by default: the card
    // shows the camera's last picture and waits for a tap, so opening the
    // dashboard never wakes a battery camera.
    this._config = { ...CARD_DEFAULTS, ...config };
    // Hiding the button while the recordings view is open would leave no way
    // back to the live view, so the mode ends with it.
    if (this._config.hide_recordings && this._recordings) {
      this._closeClip();
      this._recordings = false;
    }
    this._device = undefined;
    this._images = {};
    this._imagesFrom = undefined;
    this._imagesCam = undefined;
    this._posterShown = undefined;
    // Another camera means another SD card: forget the list and the clip.
    const was = `${previous?.serial || ""}|${previous?.entity || ""}`;
    const now = `${this._config.serial || ""}|${this._config.entity || ""}`;
    if (previous && was !== now) {
      this._closeClip();
      this._list = null;
      this._listScroll = 0;
      this._listScrollReset = true;
      this._day = null;
      this._today = null;
      this._listError = "";
      this._reads.clear(); // another camera: its reads are not ours
      this._calendarOpen = false;
      this._calendarMonth = null;
      this._days = {};
      this._daysError = "";
      // Another camera may have another shape: measure its picture again.
      this._mediaRatio = null;
      this._ratioProbe = null;
    }
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
      this._clipVideo?.pause();
      this._stopProgress();
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
    // camera must not be left streaming). A SD-card clip is only paused; it
    // never wakes the camera by itself.
    this._clipVideo?.pause();
    if (this._recordings) return;
    if (this._state !== "playing" && this._state !== "loading") return;
    this._stop(true);
  }

  _onShown() {
    if (this._recordings) return;
    this._maybeCapture();
    this._ensurePlaying();
  }

  // A fresh snapshot on open, for the idle picture. The service is marked
  // automatic, so Configure → Snapshots decides whether it may run and the
  // server keeps the minimum time between pictures per camera — several open
  // dashboards still wake a camera only once per interval.
  async _maybeCapture() {
    if (this._recordings || !this._config?.capture_on_load || this._capturing || !this._hass) return;
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
    if (this._recordings || this._userPaused || this._state !== "playing" || !this._started) return;
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
    this._probePosterRatio(url);
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

  // Whether the media area is showing video (the live stream or an SD-card
  // clip) rather than a still picture.
  _showingVideo() {
    return this._recordings ? this._clipState === "playing" : this._state === "playing";
  }

  _syncWhen() {
    if (!this._config) return;
    const text = this._showingVideo() ? "" : this._whenText();
    if (this._whenEl) {
      this._whenEl.textContent = text;
      this._whenEl.hidden = !text;
      return;
    }
    if (text && this._media && !this._showingVideo()) {
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
    if (!this._config?.show_battery) {
      el.replaceChildren();
      el.hidden = true;
      return;
    }
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
    // WebKit (Safari, the Home Assistant apps) can scroll the page to the top
    // when the focused element is removed together with its tree. Let go first;
    // the card is about to be rebuilt anyway.
    try {
      const active = root.activeElement;
      if (active && typeof active.blur === "function") active.blur();
    } catch {
      /* activeElement is not available in every embedded browser */
    }
    // Replacing the card's subtree can also make the browser lose its scroll
    // anchor and jump the page to the top (Home Assistant scrolls the window),
    // so remember where the reader was and put it back.
    const keepPlace = this._keepPagePlace();

    // Rebuilding the card replaces the list, which would otherwise bounce it to
    // the top: a clip tapped near the bottom must stay where it was while it is
    // fetched and played. The position comes from the list's own scroll events,
    // not from reading a freshly built list (which has no layout yet).
    if (this._listScrollReset) {
      this._listScroll = 0;
      this._listScrollReset = false;
    }

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
    dot.className = "dot" + (this._started && !this._recordings ? " on" : "");
    // The dot says "the camera is streaming"; the recordings mode is not live.
    if (this._recordings) dot.hidden = true;
    const status = document.createElement("span");
    status.textContent = this._recordings ? t(this._lang, "recordings") : this._statusText();
    secondary.append(dot, status);
    info.append(primary, secondary);

    // The recordings toggle sits next to the battery level, opposite the name.
    const battery = document.createElement("div");
    battery.className = "battery";
    const tools = document.createElement("div");
    tools.className = "tools";
    if (!this._config.hide_recordings) tools.append(this._recordingsButton());
    tools.append(battery);
    header.append(tile, info, tools);

    // Media
    const media = document.createElement("div");
    media.className = "media";
    // A card rebuilt after the shape was learned starts at the right height, so
    // switching a day (or live and the recordings) never resizes the picture.
    if (this._mediaRatio) media.style.aspectRatio = this._mediaRatio;
    this._media = media;
    // The day bar is updated in place when only its label changes.
    this._recDayEl = null;
    this._recRefreshEl = null;

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
    if (poster) this._probePosterRatio(poster);

    this._snapshotChipEl = null;
    this._whenEl = null;
    if (this._recordings) {
      // The picture above stays until a recording is picked; then it plays in
      // the same place, with a ✕ to go back to the picture.
      this._renderRecordingMedia(media);
    } else if (this._state === "playing" && this._video) {
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
    const when = this._showingVideo() ? "" : this._whenText();
    if (when) {
      this._whenEl = document.createElement("div");
      this._whenEl.className = "when";
      this._whenEl.textContent = when;
      media.appendChild(this._whenEl);
    }

    wrap.append(header, media);
    if (this._recordings) wrap.append(this._recordingsView());
    card.appendChild(wrap);
    root.replaceChildren(createStyle(style), card);
    if (this._recordings) {
      // Restore now and again after the browser has had a chance to lay the new
      // list out: the first assignment is clamped when it has no scroll height
      // yet. setTimeout keeps this working without a rAF-only code path.
      const restore = () => {
        const list = root.querySelector(".recList");
        if (list) list.scrollTop = this._listScroll;
      };
      restore();
      setTimeout(() => {
        restore();
        setTimeout(restore, 0);
      }, 0);
    }
    this._header = { tile, primary, secondary, dot, status, battery };
    this._syncBattery();
    keepPlace();
    setTimeout(keepPlace, 0);
  }

  _statusText() {
    if (this._started) return t(this._lang, "live");
    if (this._waitingDownload) return t(this._lang, "waiting_download");
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

  // -- SD-card recordings --------------------------------------------------
  //
  // The button next to the battery level switches the card between the live
  // view and the camera's SD-card recordings. The picture stays on screen until
  // a recording is picked; the list is read only when the mode is opened (a
  // listing wakes a battery camera), and the live stream is stopped first,
  // because the camera cannot stream and read its SD card at the same time.

  _recordingsButton() {
    const button = document.createElement("button");
    button.className = "toggle" + (this._recordings ? " on" : "");
    const title = t(this._lang, this._recordings ? "recordings_hide" : "recordings_show");
    button.title = title;
    button.setAttribute("aria-label", title);
    button.setAttribute("aria-pressed", this._recordings ? "true" : "false");
    const icon = document.createElement("ha-icon");
    icon.setAttribute("icon", "mdi:filmstrip-box-multiple");
    button.appendChild(icon);
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      this._toggleRecordings();
    });
    return button;
  }

  _toggleRecordings() {
    if (this._recordings) {
      // Back to the live view: drop the clip and let auto_play take over.
      this._closeClip();
      this._recordings = false;
      this._calendarOpen = false;
      this._calendarMonth = null;
      this._daysGen++; // a scan still in flight no longer owns the panel
      this._scanningDays = false;
      this._state = "idle";
      this._message = "";
      this._render();
      this._maybeAutoPlay();
      return;
    }
    // One viewer at a time: reading the SD card while a live stream is open
    // makes EZVIZ fail both, so stop the stream before the list is requested.
    this._stop();
    this._recordings = true;
    this._state = "idle";
    this._message = "";
    this._render();
    this._openRecordings();
  }

  async _openRecordings() {
    // The serial comes from the camera entity when the card was configured with
    // one, so wait for the device list before releasing the camera.
    await this._loadDevices();
    if (!this._recordings) return;
    await this._stopLive();
    if (!this._recordings) return;
    // Ask the server each time the view opens, but never force a read. It
    // answers from its cache while today's list is under a minute old, from the
    // stored list of a day that is over, and reads the camera only when it has
    // nothing fresh. The ⟳ button is the only thing that bypasses the cache.
    this._loadRecordings(false, true);
  }

  // The card dropping its picture is not enough: the integration keeps the
  // camera's cloud session open for the configured release delay, and SD
  // playback then finds the camera busy. Ask it to let go at once.
  async _stopLive() {
    const serial = this._serial();
    if (!serial || !this._hass) return;
    try {
      await this._hass.callWS({ type: "ezviz_rtsp/live/stop", serial });
    } catch (err) {
      console.debug(`[ezviz-video-card] live stop ${serial}: ${err?.message || err}`);
    }
  }

  _serial() {
    return this._config?.serial || this._findDevice()?.serial || null;
  }

  async _loadRecordings(refresh = false, check = false) {
    if (!this._recordings || !this._hass) return;
    // The list is cached while the card lives; the refresh button re-reads it,
    // and opening the view asks the server whether its copy is still fresh.
    if (this._list && !refresh && !check) return;
    // The ⟳ button is above the list: a fresh read starts at the top.
    if (refresh) {
      this._listScrollReset = true;
      this._queuedClip = null;
      this._clipQueued = false;
    }
    await this._loadDevices();
    if (!this._recordings) return;
    const serial = this._serial();
    if (!serial) {
      this._list = null;
      this._listError = t(this._lang, "no_entity");
      this._render();
      return;
    }
    const gen = ++this._listGen;
    const shown = this._list; // what is on screen right now
    this._listing = true;
    this._listError = "";
    if (shown) this._syncRecordingsBar();
    else this._render();
    // One SD read per camera and day at a time. Tapping today, another day and
    // today again used to queue a camera session for every tap; a repeat now
    // joins the read already on its way. The day the server will use stands in
    // for "today" until it tells us.
    const readDay = this._day || this._today || localDay(new Date());
    const readKey = `${serial}|${readDay}`;
    let read = this._reads.get(readKey);
    if (!read) {
      const msg = { type: "ezviz_rtsp/recordings", serial, refresh };
      if (this._day) msg.date = this._day;
      read = this._hass.callWS(msg);
      this._reads.set(readKey, read);
      read
        .catch(() => {}) // the awaiters below report the error
        .finally(() => {
          if (this._reads.get(readKey) === read) this._reads.delete(readKey);
        });
    }
    try {
      const result = await read;
      if (gen !== this._listGen) return;
      // The view may have been closed (and reopened) while the read was on its
      // way. Keep the list anyway: reopening once it is here must not wake the
      // camera for the same day again.
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
        // Rebuilding the card for an answer that paints the same rows makes it
        // flash (and bounce the list) for nothing - most checks land on the same
        // list. Only the bar says that the read happened.
        if (!this._listError && sameList(shown, this._list)) {
          // Nothing to paint, so nothing to scroll either.
          this._listScrollReset = false;
          this._syncRecordingsBar();
        } else {
          this._render();
        }
      }
    }
  }

  _syncRecordingsBar() {
    if (this._recDayEl) this._recDayEl.textContent = this._recordingsLabel();
    this._recRefreshEl?.classList.toggle("spinning", this._listing);
  }

  // -- the day picker ------------------------------------------------------

  _toggleCalendar() {
    this._calendarOpen = !this._calendarOpen;
    if (!this._calendarOpen) {
      this._calendarMonth = null;
      this._render();
      return;
    }
    if (!this._calendarMonth) {
      this._calendarMonth = (this._day || this._today || localDay(new Date())).slice(0, 7);
    }
    this._render();
    // The month's dots are cheap: local days are free and the SD days come from
    // the server's cache. Only the scan button asks the camera.
    this._loadDays();
  }

  _shiftCalendarMonth(months) {
    if (!this._calendarMonth) return;
    const [y, m] = this._calendarMonth.split("-").map(Number);
    this._calendarMonth = localDay(new Date(y, m - 1 + months, 1)).slice(0, 7);
    this._daysError = "";
    this._render();
    this._loadDays();
  }

  _pickDay(day) {
    if (this._today && day > this._today) return;
    this._calendarOpen = false;
    this._calendarMonth = null;
    if (this._selected) this._closeClip();
    const same = this._day === day && this._list && !this._listError;
    this._day = day;
    if (same) {
      this._render();
      return;
    }
    this._list = null;
    this._listScrollReset = true; // another day: start its list at the top
    this._render();
    this._loadRecordings();
  }

  async _loadDays(scan = false) {
    if (!this._recordings || !this._hass) return;
    const serial = this._serial();
    const month = this._calendarMonth;
    if (!serial || !month) return;
    if (scan) {
      this._scanningDays = true;
      this._daysError = "";
      this._render();
    }
    const gen = ++this._daysGen;
    try {
      const result = await this._hass.callWS({
        type: "ezviz_rtsp/recording/days",
        serial,
        month,
        scan,
      });
      if (gen !== this._daysGen || !this._recordings) return;
      this._days[month] = result;
      if (scan) this._daysError = "";
    } catch (err) {
      if (gen !== this._daysGen || !this._recordings) return;
      this._daysError = err?.message || String(err);
    } finally {
      if (gen === this._daysGen) {
        this._scanningDays = false;
        this._render();
      }
    }
  }

  _atMonth() {
    return this._calendarMonth >= localDay(new Date()).slice(0, 7);
  }

  _calendarPanel() {
    const lang = this._lang;
    const month = this._calendarMonth || localDay(new Date()).slice(0, 7);
    const [year, mon] = month.split("-").map(Number);
    const locale = this._hass?.locale?.language || undefined;
    const days = this._days[month] || { local: [], card: [], scanned: null, complete: false };
    const localDays = new Set(days.local || []);
    const cardDays = new Set(days.card || []);
    const selected = this._day || this._today || localDay(new Date());
    const today = this._today || localDay(new Date());

    const panel = document.createElement("div");
    panel.className = "calendar";

    const head = document.createElement("div");
    head.className = "calHead";
    const title = document.createElement("div");
    title.className = "calMonth";
    title.textContent = new Date(year, mon - 1, 1).toLocaleDateString(locale, {
      month: "long",
      year: "numeric",
    });
    head.append(
      this._recButton(
        "mdi:chevron-left",
        t(lang, "rec_prev_month"),
        () => this._shiftCalendarMonth(-1)
      ),
      title,
      this._recButton(
        "mdi:chevron-right",
        t(lang, "rec_next_month"),
        () => this._shiftCalendarMonth(1),
        this._scanningDays || this._atMonth()
      )
    );
    panel.append(head);

    const grid = document.createElement("div");
    grid.className = "calGrid";
    // Monday first: the week starts on Monday in Ukraine and most of Europe.
    for (let i = 0; i < 7; i++) {
      const dow = document.createElement("div");
      dow.className = "calDow";
      dow.textContent = new Date(2024, 0, 1 + i).toLocaleDateString(locale, {
        weekday: "short",
      });
      grid.append(dow);
    }
    const first = new Date(year, mon - 1, 1);
    const lead = (first.getDay() + 6) % 7;
    for (let i = 0; i < lead; i++) {
      const blank = document.createElement("div");
      blank.className = "calBlank";
      grid.append(blank);
    }
    const last = new Date(year, mon, 0).getDate();
    for (let d = 1; d <= last; d++) {
      const day = `${month}-${String(d).padStart(2, "0")}`;
      const button = document.createElement("button");
      button.className =
        "calDay" + (day === selected ? " on" : "") + (day === today ? " today" : "");
      button.textContent = String(d);
      // The month scan holds the camera: picking a day would wait for it.
      button.disabled = day > today || this._scanningDays;
      const local = localDays.has(day);
      const card = cardDays.has(day);
      if (local || card) {
        const dot = document.createElement("span");
        dot.className = "dot " + (local ? "local" : "card");
        button.append(dot);
      }
      button.title = local
        ? t(lang, "rec_local")
        : card
          ? t(lang, "rec_cloud")
          : String(d);
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        this._pickDay(day);
      });
      grid.append(button);
    }
    panel.append(grid);

    const foot = document.createElement("div");
    foot.className = "calFoot";
    const text = document.createElement("div");
    text.className = "calText" + (this._daysError ? " error" : "");
    if (this._scanningDays) {
      text.textContent = t(lang, "rec_scanning");
    } else if (this._daysError) {
      text.textContent = t(lang, "rec_scan_failed", { msg: this._daysError });
    } else if (days.scanned) {
      const when = new Date(days.scanned).toLocaleString(locale, {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
      text.textContent = t(lang, days.complete ? "rec_scanned" : "rec_scan_partial", { when });
    } else {
      text.textContent = t(lang, "rec_scan_never");
    }
    const scan = document.createElement("button");
    scan.className = "calScan";
    scan.textContent = this._scanningDays ? t(lang, "rec_scanning") : t(lang, "rec_scan");
    scan.disabled =
      this._scanningDays || this._listing || Boolean(this._clipFetching);
    scan.title = t(lang, "rec_scan");
    scan.addEventListener("click", (event) => {
      event.stopPropagation();
      this._loadDays(true);
    });
    const legend = document.createElement("div");
    legend.className = "calLegend";
    for (const [cls, key] of [
      ["local", "rec_legend_local"],
      ["card", "rec_legend_card"],
    ]) {
      const dot = document.createElement("span");
      dot.className = "dot " + cls;
      const label = document.createElement("span");
      label.textContent = t(lang, key);
      legend.append(dot, label);
    }
    foot.append(text, scan, legend);
    panel.append(foot);
    return panel;
  }

  _dayLabel() {
    const day = this._day || this._today;
    if (!day) return "";
    if (day === this._today) return t(this._lang, "rec_today");
    const [y, m, d] = day.split("-").map(Number);
    const date = new Date(y, m - 1, d);
    const [ty, tm, td] = (this._today || localDay(new Date())).split("-").map(Number);
    if (new Date(ty, tm - 1, td - 1).getTime() === date.getTime()) {
      return t(this._lang, "rec_yesterday");
    }
    return date.toLocaleDateString(this._hass?.locale?.language || undefined, {
      weekday: "short", day: "numeric", month: "short",
    });
  }

  _recordingsLabel() {
    const lang = this._lang;
    const day = this._dayLabel();
    if (this._listError) return day;
    if (!this._list) {
      return day ? `${day} · ${t(lang, "rec_loading")}` : t(lang, "rec_loading");
    }
    const count = this._list.recordings.length;
    const text = t(lang, this._list.complete ? "rec_count" : "rec_partial", { n: count });
    return day ? `${day} · ${text}` : text;
  }

  _recordingsView() {
    const lang = this._lang;
    const view = document.createElement("div");
    view.className = "rec";

    const bar = document.createElement("div");
    bar.className = "recBar";
    const day = document.createElement("div");
    day.className = "recDay";
    day.textContent = this._recordingsLabel();
    const days = document.createElement("div");
    days.className = "days";
    const pick = this._recButton(
      "mdi:calendar-month",
      t(lang, "rec_calendar"),
      () => this._toggleCalendar()
    );
    pick.classList.add("calendarbtn");
    if (this._calendarOpen) pick.classList.add("on");
    const refresh = this._recButton(
      "mdi:refresh",
      t(lang, "rec_refresh"),
      () => this._loadRecordings(true),
      false,
      this._listing
    );
    days.append(pick, refresh);
    bar.append(day, days);
    view.append(bar);
    this._recDayEl = day;
    this._recRefreshEl = refresh;
    if (this._calendarOpen) view.append(this._calendarPanel());

    const list = document.createElement("div");
    list.className = "recList";
    list.style.maxHeight = "360px";
    list.append(this._recordingsBody());
    view.append(list);
    // Remember where the user is in the list; a render must not lose it.
    list.addEventListener(
      "scroll",
      () => {
        this._listScroll = list.scrollTop;
      },
      { passive: true }
    );
    return view;
  }

  _recButton(icon, title, onClick, disabled = false, spinning = false) {
    const button = document.createElement("button");
    button.className = "iconbtn" + (spinning ? " spinning" : "");
    button.title = title;
    button.setAttribute("aria-label", title);
    button.disabled = disabled;
    const el = document.createElement("ha-icon");
    el.setAttribute("icon", icon);
    button.append(el);
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      onClick();
    });
    return button;
  }

  _recordingsBody() {
    const lang = this._lang;
    const frag = document.createDocumentFragment();
    let note;
    if (this._listError) {
      note = document.createElement("div");
      note.className = "recNote error";
      note.textContent = t(lang, "rec_failed", { msg: this._listError });
      frag.append(note);
      return frag;
    }
    if (!this._list) {
      note = document.createElement("div");
      note.className = "recNote";
      note.textContent = t(lang, "rec_loading");
      frag.append(note);
      return frag;
    }
    if (!this._list.recordings.length) {
      note = document.createElement("div");
      note.className = "recNote";
      note.textContent = t(lang, "rec_none");
      frag.append(note);
      return frag;
    }
    let hour = null;
    for (const rec of this._list.recordings) {
      const start = new Date(rec.start);
      if (start.getHours() !== hour) {
        hour = start.getHours();
        const header = document.createElement("div");
        header.className = "recHour";
        header.textContent = `${String(hour).padStart(2, "0")}:00`;
        frag.append(header);
      }
      const on =
        this._selected && this._selected.begin === rec.begin && this._selected.end === rec.end;
      const row = document.createElement("button");
      row.className = "recRow" + (on ? " on" : "");
      // Lets the finished download update this row without a full render.
      row.dataset.begin = rec.begin;
      row.dataset.end = rec.end;
      const icon = document.createElement("ha-icon");
      icon.setAttribute("icon", on ? "mdi:play-circle" : "mdi:play-circle-outline");
      const time = document.createElement("span");
      time.className = "time";
      time.textContent = start.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
      const len = document.createElement("span");
      len.className = "len";
      len.textContent = `${rec.seconds} s`;
      // Cloud-only clips have to be fetched; the check says one is saved, and a
      // warning says the saved copy is short and will be fetched again.
      const where = document.createElement("ha-icon");
      where.className = "where" + (rec.incomplete ? " short" : rec.local ? " local" : "");
      where.setAttribute(
        "icon",
        rec.incomplete
          ? "mdi:cloud-alert"
          : rec.local
            ? "mdi:check-circle"
            : "mdi:cloud-outline"
      );
      where.title = t(
        this._lang,
        rec.incomplete ? "rec_incomplete" : rec.local ? "rec_local" : "rec_cloud"
      );
      row.append(icon, time, len, where);
      row.addEventListener("click", () => this._playRecording(rec));
      frag.append(row);
    }
    return frag;
  }

  // The camera records HEVC; ask for it as is when this browser can play it and
  // for an H.264 copy otherwise. A failed HEVC playback retries once in H.264.
  _recFormat(fallback = false) {
    if (fallback) return "h264";
    return playsHevc() ? "hevc" : "h264";
  }

  _playRecording(rec, fallback = false) {
    if (!rec) return;
    const serial = this._serial();
    if (!serial || !this._hass) return;

    // A complete copy in the media folder needs no camera: play it now, even
    // while another clip is still coming off the SD card. It also supersedes
    // anything waiting in the queue.
    if (rec.local && !rec.incomplete) {
      this._queuedClip = null;
      this._clipQueued = false;
      this._startClip(rec, fallback, false);
      return;
    }

    // One camera download at a time. A tap while one is in flight only
    // remembers the newest recording; the intermediate ones are never fetched.
    if (this._clipFetching) {
      const fetching = this._clipFetching;
      // Coming back to the clip that is downloading is not a queued tap: the
      // viewer wants the bar again, and the clip plays itself when it lands.
      const same = fetching.rec && sameRecording(fetching.rec, rec);
      if (!same) this._clipGen++; // the download in flight no longer owns the view
      this._clipVideo?.pause();
      this._selected = rec;
      this._clipState = "fetching";
      this._clipError = "";
      this._clipQueued = !same;
      this._clipIncomplete = Boolean(rec.incomplete);
      // Selecting the row that is already downloading needs no queue: the fetch
      // plays it as soon as it lands. Another row is remembered to be started
      // then, so the intermediate ones are never fetched.
      this._queuedClip = same ? null : { rec, fallback };
      this._stopProgress();
      // In place: a rebuild would drop the row the reader just clicked and can
      // scroll the page, which is very visible near the bottom of the list.
      this._syncRows();
      this._repaintClipMedia();
      if (same) {
        this._startProgress(
          serial,
          rec,
          fetching.format || this._recFormat(fallback),
          this._clipGen
        );
      }
      return;
    }
    this._startClip(rec, fallback, true);
  }

  async _startClip(rec, fallback = false, cloud = false) {
    const serial = this._serial();
    if (!serial || !this._hass) return;
    const gen = ++this._clipGen;
    // A detached <video> keeps playing its sound: stop the old clip first.
    this._clipVideo?.pause();
    this._selected = rec;
    this._clipState = "fetching";
    this._clipError = "";
    this._clipQueued = false;
    this._clipIncomplete = Boolean(rec.incomplete);
    const format = this._recFormat(fallback);
    // The ticket remembers which recording it is fetching, so tapping that row
    // again can bring the progress bar back instead of queueing it.
    const ticket = cloud ? { rec, format } : null;
    if (ticket) this._clipFetching = ticket;
    this._stopProgress();
    this._syncRows();
    this._repaintClipMedia();
    if (ticket) this._startProgress(serial, rec, format, gen);
    try {
      // Another view (or another browser) may have started the live stream
      // since the list was read; release it again so the camera is free.
      await this._stopLive();
      if (!this._recordings || !sameRecording(this._selected, rec)) return;
      const result = await this._hass.callWS({
        type: "ezviz_rtsp/recording/clip",
        serial,
        begin: rec.begin,
        end: rec.end,
        format,
        keep: this._config.save_recordings !== false,
      });
      if (!this._recordings || !sameRecording(this._selected, rec)) return;
      this._stopProgress();
      // Only a clip the server kept (or already had) is local. A saved copy
      // that was short has just been replaced, so the warning goes too.
      rec.local = Boolean(result.saved);
      rec.incomplete = false;
      this._clipIncomplete = false;
      this._clipState = "playing";
      this._clipFormat = format;
      // Some browsers scroll the page when a video starts playing (or when the
      // focused row disappears). Put the reader's place back around it.
      const keepPlace = this._keepPagePlace();
      this._syncRows();
      this._repaintClipMedia();
      const video = this._ensureClipVideo();
      video.src = result.url;
      video.onloadedmetadata = () => {
        // The camera's index can be a second or two off the file it sends;
        // once the player knows the real length, show that in the row.
        if (this._selected !== rec) return;
        // _fitMediaTo follows its own height change with the scroll.
        this._fitMediaTo(video);
        const seconds = Math.round(video.duration);
        if (!Number.isFinite(seconds) || seconds <= 0) return;
        const listed = rec.seconds;
        rec.seconds = seconds;
        const len = this.shadowRoot.querySelector(".recRow.on .len");
        if (!len) return;
        len.textContent = `${seconds} s`;
        if (seconds !== listed) {
          len.title = `The camera sent ${seconds} s of the ${listed} s listed`;
        }
      };
      video.onerror = () => {
        if (this._clipFormat === "hevc" && this._selected === rec) {
          this._playRecording(rec, true);
        }
      };
      video.addEventListener("playing", keepPlace, { once: true });
      video.play().catch(() => {});
      keepPlace();
      setTimeout(keepPlace, 0);
    } catch (err) {
      if (gen !== this._clipGen) return;
      this._stopProgress();
      this._clipState = "error";
      this._clipError = err?.message || String(err);
      this._repaintClipMedia();
    } finally {
      if (ticket && this._clipFetching === ticket) {
        this._clipFetching = null;
        this._startQueued();
      }
    }
  }

  _startQueued() {
    const queued = this._queuedClip;
    this._queuedClip = null;
    if (!queued || !this._recordings || !this._hass) return;
    this._startClip(queued.rec, queued.fallback, true);
  }

  // The clip comes off the camera's SD card through the relay, so the only
  // honest progress is how much of the interval's video time has arrived. The
  // integration reads it from the PS timestamps and the card asks twice a
  // second; conversion has no meaningful fraction and shows a full bar.
  _startProgress(serial, rec, format, gen) {
    this._stopProgress();
    const ask = async () => {
      if (!this._hass || this._clipState !== "fetching" || gen !== this._clipGen) return;
      try {
        const result = await this._hass.callWS({
          type: "ezviz_rtsp/recording/progress",
          serial,
          begin: rec.begin,
          end: rec.end,
          format,
        });
        if (gen !== this._clipGen || this._clipState !== "fetching") return;
        if (result?.active) {
          this._progress = result;
          this._paintProgress();
        }
      } catch {
        /* a progress report is optional; the clip request reports real errors */
      }
    };
    this._progressTimer = setInterval(ask, 600);
    ask();
  }

  _stopProgress() {
    if (this._progressTimer) {
      clearInterval(this._progressTimer);
      this._progressTimer = null;
    }
    this._progress = null;
  }

  _paintProgress() {
    const dom = this._progressDom;
    if (!dom) return;
    const lang = this._lang;
    const info = this._progress;
    const stage = this._clipQueued ? "queued" : info?.stage || "downloading";
    const total = Number(info?.total) || Number(this._selected?.seconds) || 0;
    const delivered = Math.max(
      0,
      Math.min(Number(info?.delivered) || 0, total || Number.MAX_SAFE_INTEGER)
    );
    let percent = null;
    if (stage === "converting" || stage === "saving") {
      percent = 100;
    } else if (delivered > 0 && total > 0) {
      percent = Math.min(99, Math.max(1, Math.round((delivered / total) * 100)));
    }
    dom.text.textContent =
      stage === "queued"
        ? t(lang, "rec_queued")
        : stage === "converting" || stage === "saving"
          ? t(lang, "rec_converting")
          : t(lang, this._clipIncomplete ? "rec_redownloading" : "rec_fetching");
    if (percent === null) {
      dom.bar.classList.add("indeterminate");
      dom.fill.style.width = "";
      dom.hint.textContent =
        stage === "downloading" ? t(lang, "rec_waiting_camera") : "";
    } else {
      dom.bar.classList.remove("indeterminate");
      dom.fill.style.width = `${percent}%`;
      dom.hint.textContent =
        percent >= 100
          ? ""
          : t(lang, "rec_progress", {
              have: Math.floor(delivered),
              total: Math.round(total),
            });
    }
  }

  _closeClip() {
    this._clipGen++;
    this._stopProgress();
    const video = this._clipVideo;
    if (video) {
      video.pause();
      video.removeAttribute("src");
      try {
        video.load();
      } catch {
        /* ignore */
      }
    }
    this._selected = null;
    this._clipState = "idle";
    this._clipError = "";
    this._clipFormat = "";
    this._clipIncomplete = false;
    this._clipQueued = false;
    this._queuedClip = null;
  }

  // The thing that actually scrolls: the card's nearest scrollable ancestor,
  // or null when the page itself does (Home Assistant scrolls the window).
  _pageScroller() {
    let scroller = this.parentElement;
    while (
      scroller &&
      scroller !== document.body &&
      scroller !== document.documentElement
    ) {
      const style = getComputedStyle(scroller);
      if (
        /(auto|scroll)/.test(style.overflowY) &&
        scroller.scrollHeight > scroller.clientHeight + 1
      ) {
        return scroller;
      }
      scroller = scroller.parentElement;
    }
    return null;
  }

  // Move the reader's view by ``delta`` pixels.
  _scrollBy(delta) {
    if (!delta) return;
    try {
      const scroller = this._pageScroller();
      if (scroller) scroller.scrollTop += delta;
      else window.scrollTo(window.scrollX, window.scrollY + delta);
      // A deliberate move is the new "where the reader is", so a keeper still
      // waiting (the video's first playing event) does not undo it.
      if (this._place && this._place.scroller === scroller) {
        this._place.top += delta;
      }
    } catch {
      /* an embedded browser without scrollTo */
    }
  }

  _keepPagePlace() {
    const scroller = this._pageScroller();
    const place = {
      scroller,
      top: scroller ? scroller.scrollTop : window.scrollY,
      left: scroller ? scroller.scrollLeft : window.scrollX,
    };
    this._place = place;
    return () => {
      // Not cleared here: _scrollBy may still bump ``place.top`` (the media box
      // growing to the camera's shape) and the next call (the video's playing
      // event) must land on the moved position, not the original one.
      try {
        if (!scroller) {
          if (Math.abs(window.scrollY - place.top) > 1) {
            window.scrollTo(place.left, place.top);
          }
        } else if (Math.abs(scroller.scrollTop - place.top) > 1) {
          scroller.scrollTop = place.top;
          scroller.scrollLeft = place.left;
        }
      } catch {
        /* an embedded browser without scrollTo */
      }
    };
  }

  // The idle picture is the camera's own frame, so its shape is the camera's:
  // measuring it once tells the card how tall the picture box should be before
  // any clip or live stream loads. Without this the box sat at the 16:9 default
  // until the first clip, and its growth then nudged the list - and on a screen
  // large enough that the dashboard has slack and does not scroll at all, there
  // is no scroll range to compensate with.
  _probePosterRatio(url) {
    if (!url || url === this._ratioProbe) return;
    this._ratioProbe = url;
    // createElement rather than ``new Image()``: the same thing, and it works
    // in the test environment too.
    const probe = document.createElement("img");
    probe.onload = () => {
      if (this._ratioProbe !== url) return; // a newer picture replaced it
      // A running stream (or a clip) owns the box; leave its shape alone.
      if (this._media?.querySelector("video, img")) return;
      // No scroll compensation: this runs while the page is settling, usually
      // with the reader at the top, and there is no place to preserve yet.
      this._setMediaRatio(probe.naturalWidth, probe.naturalHeight, null, false);
    };
    probe.src = url;
  }

  // The picture box takes the source's own shape: no letterboxing, and the
  // card's height is right before anything starts playing. Returns whether the
  // shape is portrait (whose object-fit is "cover", not "contain").
  _setMediaRatio(width, height, element, compensate = true) {
    const media = this._media;
    const portrait = Boolean(width && height && height > width);
    if (element) element.style.objectFit = portrait ? "cover" : "contain";
    if (!media || !width || !height) return portrait;
    const ratio = portrait ? "1 / 1" : `${width} / ${height}`;
    if (this._mediaRatio === ratio) return portrait;
    this._mediaRatio = ratio;
    // Growing (or shrinking) the picture pushes whatever is below it down (up).
    // If any of that is on screen the reader sees it move - the list jumping
    // when the first clip of a session takes the camera's own shape instead of
    // the card's fixed 16:9. Follow the change with the scroll so what is on
    // screen stays put. The condition is "something below the picture is
    // visible", true both when the picture has scrolled above the viewport and
    // when only its lower edge is off the bottom of a large screen.
    const box = media.getBoundingClientRect();
    const before = box.height;
    const below = box.bottom < (window.innerHeight || 0) + 1;
    media.style.aspectRatio = ratio;
    const grown = media.getBoundingClientRect().height - before;
    if (compensate && below && Math.abs(grown) > 1) this._scrollBy(grown);
    return portrait;
  }

  // The card's picture box starts at 16:9, but a camera often records in 4:3
  // (many doorbells do), so object-fit: contain left black bands at the sides.
  // Take the source's own shape instead, and the picture fills the card's width.
  _fitMediaTo(element) {
    const media = this._media;
    if (!media || !media.contains(element)) return;
    const width = Number(element.videoWidth || element.naturalWidth);
    const height = Number(element.videoHeight || element.naturalHeight);
    if (!width || !height) return;
    this._setMediaRatio(width, height, element);
  }

  // Repaint the picture area for the clip's current state. Rebuilding the card
  // would throw away the list, the row that was just clicked, its focus and the
  // page's place - very visible when the row is near the bottom of the list.
  _repaintClipMedia() {
    const media = this._media;
    if (!media) {
      this._render();
      return;
    }
    media.replaceChildren();
    // The overlays went with the old children; _syncWhen adds one back if it
    // still applies.
    this._whenEl = null;
    if (this._posterEl) media.appendChild(this._posterEl);
    this._renderRecordingMedia(media);
    this._syncWhen();
  }

  // The list's rows follow the selection and each clip's saved state, without
  // rebuilding the list.
  _syncRows() {
    const root = this.shadowRoot;
    if (!root) return;
    const byKey = new Map();
    for (const rec of this._list?.recordings || []) {
      byKey.set(`${rec.begin}|${rec.end}`, rec);
    }
    for (const row of root.querySelectorAll(".recRow")) {
      const rec = byKey.get(`${row.dataset.begin}|${row.dataset.end}`);
      const on = Boolean(rec && this._selected && sameRecording(rec, this._selected));
      row.classList.toggle("on", on);
      const play = row.firstElementChild;
      if (play) {
        play.setAttribute("icon", on ? "mdi:play-circle" : "mdi:play-circle-outline");
      }
      if (!rec) continue;
      const where = row.querySelector(".where");
      if (where) {
        where.className =
          "where" + (rec.incomplete ? " short" : rec.local ? " local" : "");
        where.setAttribute(
          "icon",
          rec.incomplete
            ? "mdi:cloud-alert"
            : rec.local
              ? "mdi:check-circle"
              : "mdi:cloud-outline"
        );
        where.title = t(
          this._lang,
          rec.incomplete ? "rec_incomplete" : rec.local ? "rec_local" : "rec_cloud"
        );
      }
      const len = row.querySelector(".len");
      if (len) len.textContent = `${rec.seconds} s`;
    }
  }

  _ensureClipVideo() {
    if (!this._clipVideo) {
      const video = document.createElement("video");
      video.controls = true;
      video.playsInline = true;
      video.setAttribute("playsinline", "");
      this._clipVideo = video;
    }
    return this._clipVideo;
  }

  _renderRecordingMedia(media) {
    this._progressDom = null;
    if (this._clipState === "playing") {
      media.appendChild(this._ensureClipVideo());
      media.appendChild(this._closeClipButton());
      return;
    }
    if (this._clipState === "fetching") {
      const message = document.createElement("div");
      message.className = "message";
      const progress = document.createElement("div");
      progress.className = "progress";
      const text = document.createElement("div");
      text.className = "text";
      const bar = document.createElement("div");
      bar.className = "bar";
      const fill = document.createElement("div");
      fill.className = "barFill";
      bar.append(fill);
      const hint = document.createElement("div");
      hint.className = "hint";
      progress.append(text, bar, hint);
      message.append(progress);
      media.appendChild(message);
      this._progressDom = { text, bar, fill, hint };
      this._paintProgress();
      return;
    }
    if (this._clipState === "error") {
      const message = document.createElement("div");
      message.className = "message";
      message.textContent = this._clipError;
      media.appendChild(message);
      media.appendChild(this._closeClipButton());
    }
  }

  _closeClipButton() {
    const button = document.createElement("button");
    button.className = "iconbtn recClose";
    button.title = t(this._lang, "rec_close");
    button.setAttribute("aria-label", button.title);
    const icon = document.createElement("ha-icon");
    icon.setAttribute("icon", "mdi:close");
    button.append(icon);
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      this._closeClip();
      this._syncRows();
      this._repaintClipMedia();
    });
    return button;
  }

  // -- playback ------------------------------------------------------------

  _maybeAutoPlay() {
    if (
      this._config &&
      !this._recordings &&
      this._config.auto_play &&
      this.isConnected &&
      this._state === "idle" &&
      !this._video
    ) {
      this._play();
    }
  }

  async _play() {
    if (this._recordings || this._state === "loading" || this._state === "playing") return;
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

    // A clip still coming off the SD card owns the camera: the live stream
    // would only sit in the queue behind it. Say so, wait for the download to
    // end, then wake the camera as usual.
    await this._awaitDownload(gen);
    if (gen !== this._gen) return;

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

  // The card does not know about a download another card (or the download
  // service) started, so it asks the integration. One answer without a
  // download means there is nothing to wait for; otherwise the status says
  // "Waiting for the download to finish…" until the camera is free.
  async _awaitDownload(gen) {
    const serial = this._serial();
    if (!serial || !this._hass) return;
    const ask = async () => {
      const result = await this._hass.callWS({
        type: "ezviz_rtsp/live/status",
        serial,
      });
      return Boolean(result?.waiting);
    };
    let waiting;
    try {
      waiting = await ask();
    } catch {
      return; // the status is a hint; the stream request is the real test
    }
    if (!waiting || gen !== this._gen) return;
    this._waitingDownload = true;
    this._render();
    try {
      while (gen === this._gen) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        if (gen !== this._gen) return;
        try {
          if (!(await ask())) break;
        } catch {
          break;
        }
      }
    } finally {
      if (gen === this._gen) {
        this._waitingDownload = false;
        this._render();
      }
    }
  }

  _startMjpeg(gen, lang, entity, url) {
    const img = document.createElement("img");
    img.className = "live";
    img.alt = "";
    // 'load' fires when the first frame of the multipart stream is in; the open
    // connection then keeps replacing the picture as the camera sends more.
    img.addEventListener("load", () => {
      this._fitMediaTo(img);
      this._onStarted(gen, lang);
    });
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
    video.addEventListener("loadedmetadata", () => {
      if (this._video === video) this._fitMediaTo(video);
    });
    video.play().catch(() => {});
    this._startupTimer = setTimeout(() => {
      if (gen !== this._gen || this._started) return;
      this._fail(t(lang, "no_start"));
    }, STARTUP_SECONDS * 1000);
  }

  _onStarted(gen, lang) {
    if (gen !== this._gen || this._started) return;
    this._started = true;
    this._waitingDownload = false;
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
    this._waitingDownload = false;
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
    const section = (name, icon, fields) => ({
      // A collapsible block of related options. `flatten` keeps the form's
      // data flat, so every field stays a top-level card option.
      type: "expandable",
      name,
      flatten: true,
      expanded: true,
      icon,
      title: t(lang, name),
      schema: fields,
    });
    const schema = [
      section("section_camera", "mdi:video-outline", [
        { name: "serial", selector: { select: { options, mode: "dropdown" } } },
        { name: "title", selector: { text: {} } },
        { name: "icon", selector: { icon: {} } },
      ]),
      section("section_playback", "mdi:play-circle-outline", [
        { name: "auto_play", selector: { boolean: {} } },
        {
          name: "max_seconds",
          selector: { number: { min: 0, max: 600, mode: "box", unit_of_measurement: "s" } },
        },
      ]),
      section("section_picture", "mdi:image-outline", [
        { name: "capture_on_load", selector: { boolean: {} } },
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
        { name: "show_timestamp", selector: { boolean: {} } },
      ]),
      section("section_buttons", "mdi:tune-variant", [
        { name: "hide_play", selector: { boolean: {} } },
        { name: "hide_stop", selector: { boolean: {} } },
        { name: "hide_snapshot", selector: { boolean: {} } },
        { name: "show_battery", selector: { boolean: {} } },
      ]),
      section("section_recordings", "mdi:filmstrip-box-multiple", [
        { name: "hide_recordings", selector: { boolean: {} } },
        { name: "save_recordings", selector: { boolean: {} } },
      ]),
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
      form.computeHelper = (field) => {
        if (field.name === "picture") return t(lang, "picture_helper");
        if (field.name === "save_recordings") return t(lang, "save_recordings_helper");
        return "";
      };
      this._schemaKey = schemaKey;
    }
    form.data = { ...CARD_DEFAULTS, ...this._config };
  }
}

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

// Announce the card to the picker. The frontend may replace window.customCards
// while it boots, so register defensively and re-register if it goes missing.
const CARD_INFO = {
  type: "ezviz-video-card",
  name: "EZVIZ Video",
  description: "Live view of an EZVIZ camera through the EZVIZ cloud",
  preview: true,
};

const registerCard = () => {
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c && c.type === CARD_INFO.type)) {
    window.customCards.push(CARD_INFO);
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
};
define();
console.info(`[ezviz-video-card] loaded v${CARD_VERSION} (custom:ezviz-video-card)`);
const watchRegistry = setInterval(define, 100);
setTimeout(() => clearInterval(watchRegistry), 30000);
