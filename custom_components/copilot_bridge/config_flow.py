from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CopilotBridgeApiClient, CopilotBridgeApiError
from .const import (
    AUTH_METHOD_ADDON_CONFIG,
    AUTH_METHOD_DEVICE_FLOW,
    AUTH_METHOD_MANUAL_TOKEN,
    AUTH_METHOD_NONE,
    CONF_ALLOW_FILESYSTEM_ACCESS,
    CONF_ALLOW_HOME_ASSISTANT_ACTIONS,
    CONF_ASSISTANT_PROFILE,
    CONF_ENABLE_HACS_DISCOVERY,
    CONF_ENABLE_INTEGRATION_DISCOVERY,
    CONF_ENABLE_TOOLING_DISCOVERY,
    CONF_GITHUB_AUTH_METHOD,
    CONF_GITHUB_AUTH_SCOPES,
    CONF_HOME_ASSISTANT_MCP_SERVER_NAME,
    CONF_READ_ONLY_MODE,
    CONF_USE_HOME_ASSISTANT_MCP,
    DEFAULT_ALLOW_FILESYSTEM_ACCESS,
    DEFAULT_ALLOW_HOME_ASSISTANT_ACTIONS,
    DEFAULT_ASSISTANT_PROFILE,
    DEFAULT_ENABLE_HACS_DISCOVERY,
    DEFAULT_ENABLE_INTEGRATION_DISCOVERY,
    DEFAULT_ENABLE_TOOLING_DISCOVERY,
    DEFAULT_GITHUB_AUTH_METHOD,
    DEFAULT_HOME_ASSISTANT_MCP_SERVER_NAME,
    DEFAULT_READ_ONLY_MODE,
    DEFAULT_URL,
    DOMAIN,
)

CONF_GITHUB_AUTH_ACTION = "github_auth_action"
ACTION_REUSE_EXISTING_AUTH = "reuse_existing_auth"


class CopilotBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    _entry_data: dict[str, Any]
    _client: CopilotBridgeApiClient | None = None
    _bridge_health: dict[str, Any] | None = None
    _device_flow_details: dict[str, Any] | None = None
    _github_auth_status: dict[str, Any] | None = None

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            normalized_url = user_input[CONF_URL].rstrip("/").lower()
            await self.async_set_unique_id(normalized_url)
            self._abort_if_unique_id_configured()

            client = CopilotBridgeApiClient(
                base_url=user_input[CONF_URL],
                api_key=user_input.get(CONF_API_KEY),
                assistant_profile=DEFAULT_ASSISTANT_PROFILE,
                read_only_mode=DEFAULT_READ_ONLY_MODE,
                allow_home_assistant_actions=DEFAULT_ALLOW_HOME_ASSISTANT_ACTIONS,
                allow_filesystem_access=DEFAULT_ALLOW_FILESYSTEM_ACCESS,
                enable_integration_discovery=DEFAULT_ENABLE_INTEGRATION_DISCOVERY,
                enable_hacs_discovery=DEFAULT_ENABLE_HACS_DISCOVERY,
                enable_tooling_discovery=DEFAULT_ENABLE_TOOLING_DISCOVERY,
                use_home_assistant_mcp=False,
                home_assistant_mcp_server_name=DEFAULT_HOME_ASSISTANT_MCP_SERVER_NAME,
                session=async_get_clientsession(self.hass),
            )

            try:
                self._bridge_health = await client.async_health()
            except CopilotBridgeApiError:
                errors["base"] = "cannot_connect"
            else:
                self._entry_data = dict(user_input)
                self._entry_data.setdefault(
                    CONF_ASSISTANT_PROFILE, DEFAULT_ASSISTANT_PROFILE
                )
                self._entry_data.setdefault(CONF_READ_ONLY_MODE, DEFAULT_READ_ONLY_MODE)
                self._entry_data.setdefault(
                    CONF_ALLOW_HOME_ASSISTANT_ACTIONS,
                    DEFAULT_ALLOW_HOME_ASSISTANT_ACTIONS,
                )
                self._entry_data.setdefault(
                    CONF_ALLOW_FILESYSTEM_ACCESS,
                    DEFAULT_ALLOW_FILESYSTEM_ACCESS,
                )
                self._entry_data.setdefault(
                    CONF_ENABLE_INTEGRATION_DISCOVERY,
                    DEFAULT_ENABLE_INTEGRATION_DISCOVERY,
                )
                self._entry_data.setdefault(
                    CONF_ENABLE_HACS_DISCOVERY,
                    DEFAULT_ENABLE_HACS_DISCOVERY,
                )
                self._entry_data.setdefault(
                    CONF_ENABLE_TOOLING_DISCOVERY,
                    DEFAULT_ENABLE_TOOLING_DISCOVERY,
                )
                self._entry_data.setdefault(CONF_USE_HOME_ASSISTANT_MCP, False)
                self._entry_data.setdefault(
                    CONF_HOME_ASSISTANT_MCP_SERVER_NAME,
                    DEFAULT_HOME_ASSISTANT_MCP_SERVER_NAME,
                )
                self._client = client
                return await self.async_step_bridge_connection_test()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=DEFAULT_URL): str,
                    vol.Optional(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )

    async def async_step_bridge_connection_test(self, user_input: dict | None = None):
        if self._client is None:
            return await self.async_step_user()

        if user_input is not None:
            return await self.async_step_github_config()

        health = self._bridge_health or {}
        github_auth = health.get("github_auth") or {}
        mcp = ((health.get("mcp") or {}).get("home_assistant") or {})
        storage = github_auth.get("storage") or {}
        return self.async_show_form(
            step_id="bridge_connection_test",
            data_schema=vol.Schema({}),
            errors={},
            description_placeholders={
                "service": str(health.get("service", "copilot_bridge")),
                "version": str(health.get("version", "unknown")),
                "github_oauth_client_status": (
                    "Configured"
                    if github_auth.get("oauth_client_configured")
                    else "Not configured"
                ),
                "github_token_status": (
                    "Configured"
                    if github_auth.get("configured_token_present")
                    else "Not configured"
                ),
                "github_auth_storage": self._format_auth_storage_status(storage),
                "mcp_status": (
                    "Configured"
                    if mcp.get("configured")
                    else "Not configured"
                ),
            },
        )

    async def async_step_github_config(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if self._client is None:
            return await self.async_step_user()

        self._github_auth_status = await self._async_fetch_github_auth_status()

        if user_input is not None:
            selected_action = user_input[CONF_GITHUB_AUTH_ACTION]
            bridge_has_configured_token = bool(
                self._github_auth_status
                and self._github_auth_status.get("configured_token_present")
            )

            if selected_action == ACTION_REUSE_EXISTING_AUTH:
                self._entry_data[CONF_GITHUB_AUTH_METHOD] = (
                    self._resolve_existing_auth_method()
                )
                return await self.async_step_mcp_config()

            self._entry_data[CONF_GITHUB_AUTH_METHOD] = selected_action

            if selected_action == AUTH_METHOD_ADDON_CONFIG and not bridge_has_configured_token:
                errors["base"] = "bridge_auth_not_configured"

            if (
                selected_action == AUTH_METHOD_DEVICE_FLOW
                and not (
                    self._github_auth_status
                    and self._github_auth_status.get("oauth_client_configured")
                )
            ):
                errors["base"] = "device_flow_not_available"

            if errors:
                return self._show_github_config_form(errors)

            if selected_action == AUTH_METHOD_MANUAL_TOKEN:
                return await self.async_step_manual_token()
            if selected_action == AUTH_METHOD_DEVICE_FLOW:
                return await self.async_step_github_device_flow_options()

            return await self.async_step_mcp_config()

        return self._show_github_config_form(errors)

    async def async_step_github_device_flow_options(
        self, user_input: dict | None = None
    ):
        if self._client is None:
            return await self.async_step_github_config()

        if user_input is not None:
            self._entry_data[CONF_GITHUB_AUTH_SCOPES] = user_input.get(
                CONF_GITHUB_AUTH_SCOPES, "read:user"
            )
            self._device_flow_details = None
            return await self.async_step_github_device_flow()

        return self.async_show_form(
            step_id="github_device_flow_options",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_GITHUB_AUTH_SCOPES,
                        default=self._entry_data.get(
                            CONF_GITHUB_AUTH_SCOPES, "read:user"
                        ),
                    ): str,
                }
            ),
            errors={},
        )

    async def async_step_manual_token(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if self._client is None:
            return await self.async_step_github_config()

        if user_input is not None:
            try:
                await self._client.async_set_github_token(token=user_input["token"])
            except CopilotBridgeApiError:
                errors["base"] = "invalid_auth"
            else:
                return await self.async_step_mcp_config()

        return self.async_show_form(
            step_id="manual_token",
            data_schema=vol.Schema({vol.Required("token"): str}),
            errors=errors,
        )

    async def async_step_github_device_flow(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if self._client is None:
            return await self.async_step_github_config()

        status_message = "Open the verification URL and enter the user code."

        if self._device_flow_details is None:
            pending_device_flow = None
            if self._github_auth_status:
                pending_device_flow = self._github_auth_status.get("pending_device_flow")

            if pending_device_flow:
                self._device_flow_details = pending_device_flow
                status_message = "A GitHub device authorization is already pending."
            else:
                try:
                    self._device_flow_details = (
                        await self._client.async_start_github_device_flow(
                            scopes=self._entry_data.get(CONF_GITHUB_AUTH_SCOPES)
                        )
                    )
                except CopilotBridgeApiError as err:
                    errors["base"] = "device_flow_error"
                    status_message = err.message

        if not errors and user_input is not None:
            try:
                result = await self._client.async_poll_github_device_flow()
            except CopilotBridgeApiError as err:
                errors["base"] = "device_flow_error"
                status_message = err.message
            else:
                if result.get("status") == "authorized":
                    return await self.async_step_mcp_config()
                status_message = str(
                    result.get("message", "Authorization is still pending.")
                )

        if self._device_flow_details is None:
            self._device_flow_details = {
                "verification_uri": "https://github.com/login/device",
                "user_code": "Unavailable",
                "scope": self._entry_data.get(CONF_GITHUB_AUTH_SCOPES, "read:user"),
            }

        return self.async_show_form(
            step_id="github_device_flow",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "verification_uri": str(
                    self._device_flow_details.get("verification_uri", "")
                ),
                "user_code": str(self._device_flow_details.get("user_code", "")),
                "scope": str(self._device_flow_details.get("scope", "")),
                "status_message": status_message,
            },
        )

    async def async_step_mcp_config(self, user_input: dict | None = None):
        if self._client is None:
            return await self.async_step_user()

        if user_input is not None:
            self._entry_data[CONF_USE_HOME_ASSISTANT_MCP] = user_input.get(
                CONF_USE_HOME_ASSISTANT_MCP, False
            )
            self._entry_data[CONF_HOME_ASSISTANT_MCP_SERVER_NAME] = user_input.get(
                CONF_HOME_ASSISTANT_MCP_SERVER_NAME,
                DEFAULT_HOME_ASSISTANT_MCP_SERVER_NAME,
            )
            return self._async_create_bridge_entry()

        return self.async_show_form(
            step_id="mcp_config",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_USE_HOME_ASSISTANT_MCP,
                        default=self._entry_data.get(CONF_USE_HOME_ASSISTANT_MCP, False),
                    ): bool,
                    vol.Optional(
                        CONF_HOME_ASSISTANT_MCP_SERVER_NAME,
                        default=self._entry_data.get(
                            CONF_HOME_ASSISTANT_MCP_SERVER_NAME,
                            DEFAULT_HOME_ASSISTANT_MCP_SERVER_NAME,
                        ),
                    ): str,
                }
            ),
            errors={},
        )

    async def _async_fetch_github_auth_status(self) -> dict[str, Any] | None:
        if self._client is None:
            return None

        try:
            return await self._client.async_auth_status()
        except CopilotBridgeApiError:
            return None

    def _show_github_config_form(self, errors: dict[str, str]):
        github_status = self._github_auth_status or {}
        current_status = self._format_github_auth_status(github_status)
        oauth_client_status = (
            "Configured"
            if github_status.get("oauth_client_configured")
            else "Not configured"
        )
        configured_token_status = (
            "Configured"
            if github_status.get("configured_token_present")
            else "Not configured"
        )
        auth_storage_status = self._format_auth_storage_status(
            github_status.get("storage") or {}
        )

        action_options = [
            (AUTH_METHOD_ADDON_CONFIG, "Use GitHub auth already configured on the bridge"),
            (AUTH_METHOD_DEVICE_FLOW, "Sign in with GitHub in the browser"),
            (AUTH_METHOD_MANUAL_TOKEN, "Paste a GitHub token"),
            (AUTH_METHOD_NONE, "Skip GitHub setup for now"),
        ]
        default_action = self._entry_data.get(
            CONF_GITHUB_AUTH_METHOD, DEFAULT_GITHUB_AUTH_METHOD
        )
        if github_status.get("authenticated"):
            action_options.insert(
                0, (ACTION_REUSE_EXISTING_AUTH, "Reuse existing GitHub sign-in")
            )
            default_action = ACTION_REUSE_EXISTING_AUTH

        return self.async_show_form(
            step_id="github_config",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_GITHUB_AUTH_ACTION,
                        default=default_action,
                    ): vol.In(dict(action_options)),
                }
            ),
            errors=errors,
            description_placeholders={
                "current_status": current_status,
                "oauth_client_status": oauth_client_status,
                "configured_token_status": configured_token_status,
                "auth_storage_status": auth_storage_status,
            },
        )

    def _format_github_auth_status(self, github_status: dict[str, Any]) -> str:
        if not github_status:
            return "Auth status could not be loaded from the bridge."

        if github_status.get("authenticated"):
            user = github_status.get("user") or {}
            if not user.get("login"):
                auth_mode = github_status.get("auth_mode", "unknown")
                return (
                    "GitHub auth is configured on the bridge via "
                    f"{auth_mode}, but the user profile has not been loaded yet."
                )
            login = user.get("login") or "unknown user"
            auth_mode = github_status.get("auth_mode", "unknown")
            scope = github_status.get("scope") or "unknown scopes"
            return f"Already authenticated as {login} via {auth_mode} with {scope}."

        pending = github_status.get("pending_device_flow")
        if pending:
            return (
                "A device flow is already pending. "
                f"Code: {pending.get('user_code', 'Unavailable')}."
            )

        last_error = github_status.get("last_error") or {}
        if last_error.get("message"):
            return f"Not authenticated. Last bridge error: {last_error['message']}"

        if github_status.get("configured_token_present"):
            return "A GitHub token is configured on the bridge and will be used after validation."

        return "Not authenticated yet."

    def _format_auth_storage_status(self, storage: dict[str, Any]) -> str:
        if not storage:
            return "Unknown"

        path = storage.get("path") or "unknown path"
        if storage.get("load_error"):
            return f"Load error for {path}: {storage['load_error']}"
        if storage.get("file_exists"):
            return f"Ready at {path}"
        if storage.get("directory_writable"):
            return f"Will persist to {path}"
        return f"Not writable at {path}"

    def _resolve_existing_auth_method(self) -> str:
        auth_mode = (self._github_auth_status or {}).get("auth_mode")
        if auth_mode == "device_flow":
            return AUTH_METHOD_DEVICE_FLOW
        if auth_mode == "manual_token":
            return AUTH_METHOD_MANUAL_TOKEN
        if auth_mode == "config_token":
            return AUTH_METHOD_ADDON_CONFIG
        return DEFAULT_GITHUB_AUTH_METHOD

    def _async_create_bridge_entry(self):
        return self.async_create_entry(
            title="Copilot Bridge",
            data=self._entry_data,
        )

