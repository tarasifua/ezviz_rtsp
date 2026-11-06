"""Config flow for EZVIZ."""

import logging
import secrets
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, override

import probatio
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_CUSTOMIZE,
    CONF_IP_ADDRESS,
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_TYPE,
    CONF_URL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from pyezvizapi.client import EzvizClient
from pyezvizapi.exceptions import (
    AuthTestResultFailed,
    EzvizAuthVerificationCode,
    InvalidHost,
    InvalidURL,
    PyEzvizError,
)
from pyezvizapi.test_cam_rtsp import TestRTSPAuth

from .const import (
    ATTR_SERIAL,
    ATTR_TYPE_CAMERA,
    ATTR_TYPE_CLOUD,
    CONF_AUTO_SNAPSHOT,
    CONF_CODE,
    CONF_CODES,
    CONF_FFMPEG_ARGUMENTS,
    CONF_LINGER,
    CONF_MAX_SESSION,
    CONF_MFA,
    CONF_RFSESSION_ID,
    CONF_SERIAL,
    CONF_SESSION_ID,
    CONF_SNAPSHOT_INTERVAL,
    CONF_STREAM_ENABLED,
    CONF_STREAM_TOKEN,
    CONF_TRANSCODE,
    DEFAULT_AUTO_SNAPSHOT,
    DEFAULT_CAMERA_USERNAME,
    DEFAULT_FFMPEG_ARGUMENTS,
    DEFAULT_SNAPSHOT_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    EU_URL,
    RUSSIA_URL,
)
from .coordinator import EzvizConfigEntry
from .live import LINGER, MAX_SESSION, uses_cloud_stream

# A form-only field: it is not stored, it just asks for a new token on save.
CONF_ROTATE_TOKEN = "rotate_token"

_LOGGER = logging.getLogger(__name__)
DEFAULT_OPTIONS = {
    CONF_FFMPEG_ARGUMENTS: DEFAULT_FFMPEG_ARGUMENTS,
    CONF_TIMEOUT: DEFAULT_TIMEOUT,
}


def _validate_and_create_auth(data: dict, sms_code: int | None = None) -> dict[str, Any]:
    """Try to login to EZVIZ cloud account and return token.

    ``sms_code`` is the verification code EZVIZ sent when the account has
    two-step verification on; ``None`` on the first attempt.
    """
    # Verify cloud credentials by attempting a login request with username and password.
    # Return login token.

    ezviz_client = EzvizClient(
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        data[CONF_URL],
        data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
    )

    ezviz_token = ezviz_client.login(sms_code=sms_code)

    return {
        CONF_SESSION_ID: ezviz_token[CONF_SESSION_ID],
        CONF_RFSESSION_ID: ezviz_token[CONF_RFSESSION_ID],
        CONF_URL: ezviz_token["api_url"],
        CONF_TYPE: ATTR_TYPE_CLOUD,
    }


def _test_camera_rtsp_creds(data: dict) -> None:
    """Try DESCRIBE on RTSP camera with credentials."""

    test_rtsp = TestRTSPAuth(
        data[CONF_IP_ADDRESS], data[CONF_USERNAME], data[CONF_PASSWORD]
    )

    test_rtsp.main()


class EzvizConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EZVIZ."""

    VERSION = 1

    ip_address: str
    username: str | None
    password: str | None
    unique_id: str
    # The sign-in waiting for the MFA code EZVIZ sent, if any.
    _mfa_data: dict[str, Any] | None = None
    _mfa_action: str = "create"

    async def _validate_and_create_camera_rtsp(self, data: dict) -> ConfigFlowResult:
        """Try DESCRIBE on RTSP camera with credentials."""

        # Get EZVIZ cloud credentials from config entry
        ezviz_token = {
            CONF_SESSION_ID: None,
            CONF_RFSESSION_ID: None,
            "api_url": None,
        }
        ezviz_timeout = DEFAULT_TIMEOUT

        for item in self._async_current_entries():
            if item.data.get(CONF_TYPE) == ATTR_TYPE_CLOUD:
                ezviz_token = {
                    CONF_SESSION_ID: item.data.get(CONF_SESSION_ID),
                    CONF_RFSESSION_ID: item.data.get(CONF_RFSESSION_ID),
                    "api_url": item.data.get(CONF_URL),
                }
                ezviz_timeout = item.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)

        # Abort flow if user removed cloud account before adding camera.
        if ezviz_token.get(CONF_SESSION_ID) is None:
            return self.async_abort(reason="ezviz_cloud_account_missing")

        ezviz_client = EzvizClient(token=ezviz_token, timeout=ezviz_timeout)

        def _login_wake_and_test() -> None:
            # Login to create EZVIZ API instance.
            ezviz_client.login()
            # Wake hibernating camera.
            ezviz_client.get_detection_sensibility(data[ATTR_SERIAL])
            # Attempt an authenticated RTSP DESCRIBE request.
            _test_camera_rtsp_creds(data)

        await self.hass.async_add_executor_job(_login_wake_and_test)

        return self.async_create_entry(
            title=data[ATTR_SERIAL],
            data={
                CONF_USERNAME: data[CONF_USERNAME],
                CONF_PASSWORD: data[CONF_PASSWORD],
                CONF_TYPE: ATTR_TYPE_CAMERA,
            },
            options=DEFAULT_OPTIONS,
        )

    @staticmethod
    @callback
    @override
    def async_get_options_flow(
        config_entry: EzvizConfigEntry,
    ) -> EzvizOptionsFlowHandler:
        """Get the options flow for this handler."""
        return EzvizOptionsFlowHandler()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by the user."""

        # Check if EZVIZ cloud account is present in entry config,
        # abort if already configured.
        for item in self._async_current_entries():
            if item.data.get(CONF_TYPE) == ATTR_TYPE_CLOUD:
                return self.async_abort(reason="already_configured_account")

        errors = {}
        auth_data = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            if user_input[CONF_URL] == CONF_CUSTOMIZE:
                self.username = user_input[CONF_USERNAME]
                self.password = user_input[CONF_PASSWORD]
                return await self.async_step_user_custom_url()

            try:
                auth_data = await self.hass.async_add_executor_job(
                    _validate_and_create_auth, user_input
                )

            except InvalidURL:
                errors["base"] = "invalid_host"

            except InvalidHost:
                errors["base"] = "cannot_connect"

            except EzvizAuthVerificationCode:
                self._mfa_data = dict(user_input)
                self._mfa_action = "create"
                return await self.async_step_mfa()

            except PyEzvizError:
                errors["base"] = "invalid_auth"

            except Exception:
                _LOGGER.exception("Unexpected exception")
                return self.async_abort(reason="unknown")

            else:
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME],
                    data=auth_data,
                    options=DEFAULT_OPTIONS,
                )

        data_schema = probatio.Schema(
            {
                probatio.Required(CONF_USERNAME): str,
                probatio.Required(CONF_PASSWORD): str,
                probatio.Required(CONF_URL, default=EU_URL): probatio.In(
                    [EU_URL, RUSSIA_URL, CONF_CUSTOMIZE]
                ),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_user_custom_url(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by the user for custom region url."""
        errors = {}
        auth_data = {}

        if user_input is not None:
            user_input[CONF_USERNAME] = self.username
            user_input[CONF_PASSWORD] = self.password

            try:
                auth_data = await self.hass.async_add_executor_job(
                    _validate_and_create_auth, user_input
                )

            except InvalidURL:
                errors["base"] = "invalid_host"

            except InvalidHost:
                errors["base"] = "cannot_connect"

            except EzvizAuthVerificationCode:
                self._mfa_data = dict(user_input)
                self._mfa_action = "create"
                return await self.async_step_mfa()

            except PyEzvizError:
                errors["base"] = "invalid_auth"

            except Exception:
                _LOGGER.exception("Unexpected exception")
                return self.async_abort(reason="unknown")

            else:
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME],
                    data=auth_data,
                    options=DEFAULT_OPTIONS,
                )

        data_schema_custom_url = probatio.Schema(
            {
                probatio.Required(CONF_URL, default=EU_URL): str,
            }
        )

        return self.async_show_form(
            step_id="user_custom_url", data_schema=data_schema_custom_url, errors=errors
        )

    @override
    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle a flow for discovered camera without rtsp config entry."""

        await self.async_set_unique_id(discovery_info[ATTR_SERIAL])
        self._abort_if_unique_id_configured()

        if TYPE_CHECKING:
            # A unique ID is passed in via the discovery info
            assert self.unique_id is not None
        self.context["title_placeholders"] = {ATTR_SERIAL: self.unique_id}
        self.ip_address = discovery_info[CONF_IP_ADDRESS]

        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm and create entry from discovery step."""
        errors = {}

        if user_input is not None:
            user_input[ATTR_SERIAL] = self.unique_id
            user_input[CONF_IP_ADDRESS] = self.ip_address
            try:
                return await self._validate_and_create_camera_rtsp(user_input)

            except InvalidHost, InvalidURL:
                errors["base"] = "invalid_host"

            except EzvizAuthVerificationCode:
                self._mfa_data = dict(user_input)
                self._mfa_action = "reauth"
                return await self.async_step_mfa()

            except PyEzvizError, AuthTestResultFailed:
                errors["base"] = "invalid_auth"

            except Exception:
                _LOGGER.exception("Unexpected exception")
                return self.async_abort(reason="unknown")

        discovered_camera_schema = probatio.Schema(
            {
                probatio.Required(CONF_USERNAME, default=DEFAULT_CAMERA_USERNAME): str,
                probatio.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="confirm",
            data_schema=discovered_camera_schema,
            errors=errors,
            description_placeholders={
                ATTR_SERIAL: self.unique_id,
                CONF_IP_ADDRESS: self.ip_address,
            },
        )

    async def _async_cloud_entry(self) -> ConfigEntry | None:
        """The configured cloud account entry, if any."""
        for item in self._async_current_entries():
            if item.data.get(CONF_TYPE) == ATTR_TYPE_CLOUD:
                return item
        return None

    async def async_step_mfa(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the code EZVIZ sent by e-mail or SMS to finish signing in."""
        if self._mfa_data is None:
            return self.async_abort(reason="unknown")

        errors: dict[str, str] = {}
        if user_input is not None:
            code = str(user_input.get(CONF_MFA, "")).strip()
            sms_code = int(code) if code.isdigit() else None
            try:
                auth_data = await self.hass.async_add_executor_job(
                    _validate_and_create_auth, self._mfa_data, sms_code
                )
            except EzvizAuthVerificationCode:
                errors["base"] = "invalid_mfa"
            except PyEzvizError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                return self.async_abort(reason="unknown")
            else:
                action, data = self._mfa_action, self._mfa_data
                self._mfa_data = None
                if action == "reauth":
                    if (entry := await self._async_cloud_entry()) is None:
                        return self.async_abort(reason="ezviz_cloud_account_missing")
                    return self.async_update_reload_and_abort(entry, data=auth_data)
                return self.async_create_entry(
                    title=data[CONF_USERNAME], data=auth_data, options=DEFAULT_OPTIONS
                )

        return self.async_show_form(
            step_id="mfa",
            data_schema=probatio.Schema({probatio.Required(CONF_MFA): str}),
            description_placeholders={"username": self._mfa_data.get(CONF_USERNAME, "")},
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a flow for reauthentication with password."""

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a Confirm flow for reauthentication with password."""
        auth_data = {}
        errors = {}
        entry = None

        for item in self._async_current_entries():
            if item.data.get(CONF_TYPE) == ATTR_TYPE_CLOUD:
                self.context["title_placeholders"] = {ATTR_SERIAL: item.title}
                entry = await self.async_set_unique_id(item.title)

        if not entry:
            return self.async_abort(reason="ezviz_cloud_account_missing")

        if user_input is not None:
            user_input[CONF_URL] = entry.data[CONF_URL]

            try:
                auth_data = await self.hass.async_add_executor_job(
                    _validate_and_create_auth, user_input
                )

            except InvalidHost, InvalidURL:
                errors["base"] = "invalid_host"

            except EzvizAuthVerificationCode:
                self._mfa_data = dict(user_input)
                self._mfa_action = "reauth"
                return await self.async_step_mfa()

            except PyEzvizError, AuthTestResultFailed:
                errors["base"] = "invalid_auth"

            except Exception:
                _LOGGER.exception("Unexpected exception")
                return self.async_abort(reason="unknown")

            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data=auth_data,
                )

        data_schema = probatio.Schema(
            {
                probatio.Required(CONF_USERNAME, default=entry.title): probatio.In(
                    [entry.title]
                ),
                probatio.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=data_schema,
            errors=errors,
        )


class EzvizOptionsFlowHandler(OptionsFlowWithReload):
    """Handle EZVIZ client options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu; each part saves on its own."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "general",
                "stream",
                "release",
                "snapshots",
                "stream_address",
                "video",
                "codes",
            ],
        )

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Request timeout and ffmpeg arguments."""
        if user_input is not None:
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input}
            )

        options = probatio.Schema(
            {
                probatio.Optional(
                    CONF_TIMEOUT,
                    default=self.config_entry.options.get(
                        CONF_TIMEOUT, DEFAULT_TIMEOUT
                    ),
                ): int,
                probatio.Optional(
                    CONF_FFMPEG_ARGUMENTS,
                    default=self.config_entry.options.get(
                        CONF_FFMPEG_ARGUMENTS, DEFAULT_FFMPEG_ARGUMENTS
                    ),
                ): str,
            }
        )

        return self.async_show_form(step_id="general", data_schema=options)

    async def async_step_codes(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set the verification code of a cloud camera, for encrypted video.

        Only cameras with video encryption turned on need one; the code decrypts
        the cloud live stream inside Home Assistant and never reaches a browser.
        """
        options = self.config_entry.options
        codes: dict[str, str] = dict(options.get(CONF_CODES, {}))

        if user_input is not None:
            serial = user_input[CONF_SERIAL]
            code = user_input.get(CONF_CODE, "").strip().upper()
            if code:
                codes[serial] = code
            else:
                codes.pop(serial, None)
            return self.async_create_entry(title="", data={**options, CONF_CODES: codes})

        cameras = self._async_cloud_cameras()
        if not cameras:
            return self.async_abort(reason="no_cameras")
        device_options = [
            SelectOptionDict(
                value=serial,
                label=f"{name} ({serial})" + (" ✓" if serial in codes else ""),
            )
            for serial, name in cameras
        ]
        return self.async_show_form(
            step_id="codes",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        CONF_SERIAL,
                        default=(user_input or {}).get(
                            CONF_SERIAL, device_options[0]["value"]
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=device_options, mode=SelectSelectorMode.DROPDOWN
                        )
                    ),
                    probatio.Optional(CONF_CODE): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
        )

    def _async_cloud_cameras(self) -> list[tuple[str, str]]:
        """The cloud-streamed cameras of the account, as (serial, name)."""
        data = getattr(getattr(self.config_entry, "runtime_data", None), "data", None) or {}
        return [
            (serial, value.get("name") or serial)
            for serial, value in data.items()
            if uses_cloud_stream(self.hass, serial)
        ]

    async def async_step_stream(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Cap how long one battery-camera live stream may run.

        The stream is stopped after this many seconds even if something is still
        watching, so a battery camera can never be left streaming. ``0`` removes
        the cap.
        """
        options = self.config_entry.options
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    **options,
                    CONF_MAX_SESSION: int(user_input[CONF_MAX_SESSION]),
                },
            )
        return self.async_show_form(
            step_id="stream",
            data_schema=probatio.Schema(
                {
                    probatio.Optional(
                        CONF_MAX_SESSION,
                        default=options.get(CONF_MAX_SESSION, MAX_SESSION),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=3600,
                            step=30,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    )
                }
            ),
        )

    async def async_step_release(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """How long to hold the stream open after the last viewer leaves.

        Holding it briefly means a quick re-play does not wake a battery camera
        again; ``0`` closes the camera at once.
        """
        options = self.config_entry.options
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    **options,
                    CONF_LINGER: int(user_input[CONF_LINGER]),
                },
            )
        return self.async_show_form(
            step_id="release",
            data_schema=probatio.Schema(
                {
                    probatio.Optional(
                        CONF_LINGER,
                        default=options.get(CONF_LINGER, LINGER),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=300,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    )
                }
            ),
        )

    async def async_step_snapshots(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Automatic snapshots: whether the snapshot card may take a picture when
        it comes into view, and how often per camera at most.

        Explicit capture_picture calls (a button, a script) are not affected.
        """
        options = self.config_entry.options
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    **options,
                    CONF_AUTO_SNAPSHOT: bool(user_input[CONF_AUTO_SNAPSHOT]),
                    CONF_SNAPSHOT_INTERVAL: int(user_input[CONF_SNAPSHOT_INTERVAL]),
                },
            )
        return self.async_show_form(
            step_id="snapshots",
            data_schema=probatio.Schema(
                {
                    probatio.Optional(
                        CONF_AUTO_SNAPSHOT,
                        default=options.get(CONF_AUTO_SNAPSHOT, DEFAULT_AUTO_SNAPSHOT),
                    ): BooleanSelector(),
                    probatio.Optional(
                        CONF_SNAPSHOT_INTERVAL,
                        default=options.get(
                            CONF_SNAPSHOT_INTERVAL, DEFAULT_SNAPSHOT_INTERVAL
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=86400,
                            step=30,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                }
            ),
        )

    async def async_step_stream_address(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the token-guarded addresses other apps can read, and let the
        token be replaced.

        go2rtc, Frigate and friends read each cloud camera from these addresses.
        Reading one wakes the camera, so they are meant to be opened briefly.
        """
        options = self.config_entry.options
        if user_input is not None:
            data = dict(options)
            data[CONF_STREAM_ENABLED] = bool(user_input.get(CONF_STREAM_ENABLED, False))
            if user_input.get(CONF_ROTATE_TOKEN):
                data[CONF_STREAM_TOKEN] = secrets.token_urlsafe(24)
            return self.async_create_entry(title="", data=data)

        cameras = self._async_cloud_cameras()
        if not cameras:
            return self.async_abort(reason="no_cameras")
        token = options.get(CONF_STREAM_TOKEN) or ""
        enabled = bool(options.get(CONF_STREAM_ENABLED, False))
        base = (
            self.hass.config.internal_url
            or self.hass.config.external_url
            or "http://homeassistant:8123"
        ).rstrip("/")
        lines: list[str] = []
        for serial, name in cameras:
            lines.append(f"{name} ({serial})")
            lines.append(f"{base}/api/{DOMAIN}/live/{serial}?token={token}")
            lines.append(f"{base}/api/{DOMAIN}/mjpeg/{serial}?token={token}")
            lines.append("")
        return self.async_show_form(
            step_id="stream_address",
            data_schema=probatio.Schema(
                {
                    probatio.Optional(
                        CONF_STREAM_ENABLED, default=enabled
                    ): BooleanSelector(),
                    probatio.Optional(
                        CONF_ROTATE_TOKEN, default=False
                    ): BooleanSelector(),
                }
            ),
            description_placeholders={"addresses": "\n".join(lines).strip()},
        )

    async def async_step_video(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-encode the cloud live stream to H.264 for browsers without HEVC."""
        options = self.config_entry.options
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**options, CONF_TRANSCODE: bool(user_input[CONF_TRANSCODE])},
            )
        return self.async_show_form(
            step_id="video",
            data_schema=probatio.Schema(
                {
                    probatio.Optional(
                        CONF_TRANSCODE, default=options.get(CONF_TRANSCODE, True)
                    ): BooleanSelector()
                }
            ),
        )
