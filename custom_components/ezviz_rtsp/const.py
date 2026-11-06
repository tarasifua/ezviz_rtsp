"""Constants for the ezviz integration."""

DOMAIN = "ezviz_rtsp"
MANUFACTURER = "EZVIZ"

# Configuration
ATTR_SERIAL = "serial"
CONF_FFMPEG_ARGUMENTS = "ffmpeg_arguments"
ATTR_TYPE_CLOUD = "EZVIZ_CLOUD_ACCOUNT"
ATTR_TYPE_CAMERA = "CAMERA_ACCOUNT"
CONF_SESSION_ID = "session_id"
CONF_RFSESSION_ID = "rf_session_id"
CONF_EZVIZ_ACCOUNT = "ezviz_account"
CONF_MFA = "mfa_code"  # only kept long enough to finish a login

# Cloud streaming (cameras with no local RTSP: battery cameras and peepholes)
CONF_CODES = "codes"  # verification code per serial, for encrypted video
CONF_SERIAL = "serial"
CONF_CODE = "code"
CONF_TRANSCODE = "transcode"  # re-encode the live stream to H.264 for the browser
CONF_MAX_SESSION = "max_session"  # cap a battery camera's stream, in seconds
CONF_LINGER = "linger"  # how long the stream is held open after the last viewer
CONF_AUTO_SNAPSHOT = "auto_snapshot"  # honour the snapshot card's automatic capture requests
CONF_SNAPSHOT_INTERVAL = "snapshot_interval"  # minimum seconds between automatic captures of one camera
CONF_STREAM_TOKEN = "stream_token"  # guards the live address other apps read
CONF_STREAM_ENABLED = "stream_enabled"  # whether other apps may read those addresses
CONF_INTERNAL_TOKEN = "internal_token"  # guards the card's own picture address
DATA_LIVE_VIEW = f"{DOMAIN}_live_view_registered"
DATA_CARD = f"{DOMAIN}_card_registered"
DATA_WS = f"{DOMAIN}_ws_registered"

# The Lovelace card the integration ships and serves.
CARD_FILENAME = "ezviz-video-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILENAME}"
# hls.js is bundled with the integration and served from its own static path,
# so the card never loads third-party code from a public CDN at runtime.
HLS_FILENAME = "hls.min.js"
HLS_URL = f"/{DOMAIN}/{HLS_FILENAME}"

# Services data
DIR_UP = "up"
DIR_DOWN = "down"
DIR_LEFT = "left"
DIR_RIGHT = "right"
ATTR_ENABLE = "enable"
ATTR_DIRECTION = "direction"
ATTR_SPEED = "speed"
ATTR_LEVEL = "level"
ATTR_TYPE = "type_value"
ATTR_MIN_INTERVAL = "min_interval"
ATTR_AUTOMATIC = "automatic"

# Service names
SERVICE_WAKE_DEVICE = "wake_device"
# Take a picture through the cloud on demand (shown by the camera's Snapshot image)
SERVICE_CAPTURE_PICTURE = "capture_picture"
SIGNAL_PICTURE_CAPTURED = "ezviz_rtsp_picture_captured_{}"
DEFAULT_AUTO_SNAPSHOT = True
DEFAULT_SNAPSHOT_INTERVAL = 300
SERVICE_DETECTION_SENSITIVITY = "set_alarm_detection_sensibility"

# Defaults
EU_URL = "apiieu.ezvizlife.com"
RUSSIA_URL = "apirus.ezvizru.com"
DEFAULT_CAMERA_USERNAME = "admin"
DEFAULT_TIMEOUT = 25
DEFAULT_FFMPEG_ARGUMENTS = "/Streaming/Channels/102"
