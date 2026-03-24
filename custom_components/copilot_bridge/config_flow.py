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


class CopilotBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    _entry_data: dict[str, Any]
    _client: CopilotBridgeApiClient | None = None
    _device_flow_details: dict[str, Any] | None = None

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            normalized_url = user_input[CONF_URL].rstrip("/").lower()
            await self.async_set_unique_id(normalized_url)
            self._abort_if_unique_id_configured()

            client = CopilotBridgeApiClient(
                base_url=user_input[CONF_URL],
                api_key=user_input.get(CONF_API_KEY),
                use_home_assistant_mcp=user_input.get(CONF_USE_HOME_ASSISTANT_MCP, False),
                home_assistant_mcp_server_name=user_input.get(
                    CONF_HOME_ASSISTANT_MCP_SERVER_NAME
                ),
                session=async_get_clientsession(self.hass),
            )

            try:
                await client.async_health()
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
                self._client = client

                auth_method = user_input.get(
                    CONF_GITHUB_AUTH_METHOD, DEFAULT_GITHUB_AUTH_METHOD
                )
                if auth_method == AUTH_METHOD_MANUAL_TOKEN:
                    return await self.async_step_manual_token()
                if auth_method == AUTH_METHOD_DEVICE_FLOW:
                    return await self.async_step_github_device_flow()

                return self._async_create_bridge_entry()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=DEFAULT_URL): str,
                    vol.Optional(CONF_API_KEY): str,
                    vol.Required(
                        CONF_GITHUB_AUTH_METHOD,
                        default=DEFAULT_GITHUB_AUTH_METHOD,
                    ): vol.In(
                        [
                            AUTH_METHOD_ADDON_CONFIG,
                            AUTH_METHOD_DEVICE_FLOW,
                            AUTH_METHOD_MANUAL_TOKEN,
                            AUTH_METHOD_NONE,
                        ]
                    ),
                    vol.Optional(CONF_GITHUB_AUTH_SCOPES, default="read:user"): str,
                    vol.Optional(CONF_USE_HOME_ASSISTANT_MCP, default=False): bool,
                    vol.Optional(
                        CONF_HOME_ASSISTANT_MCP_SERVER_NAME,
                        default=DEFAULT_HOME_ASSISTANT_MCP_SERVER_NAME,
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_manual_token(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if self._client is None:
            return await self.async_step_user()

        if user_input is not None:
            try:
                await self._client.async_set_github_token(token=user_input["token"])
            except CopilotBridgeApiError:
                errors["base"] = "invalid_auth"
            else:
                return self._async_create_bridge_entry()

        return self.async_show_form(
            step_id="manual_token",
            data_schema=vol.Schema({vol.Required("token"): str}),
            errors=errors,
        )

    async def async_step_github_device_flow(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if self._client is None:
            return await self.async_step_user()

        status_message = "Open the verification URL and enter the user code."

        if self._device_flow_details is None:
            try:
                self._device_flow_details = (
                    await self._client.async_start_github_device_flow(
                        scopes=self._entry_data.get(CONF_GITHUB_AUTH_SCOPES)
                    )
                )
            except CopilotBridgeApiError:
                errors["base"] = "device_flow_error"

        if not errors and user_input is not None:
            try:
                result = await self._client.async_poll_github_device_flow()
            except CopilotBridgeApiError as err:
                errors["base"] = "device_flow_error"
                status_message = str(err)
            else:
                if result.get("status") == "authorized":
                    return self._async_create_bridge_entry()
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

    def _async_create_bridge_entry(self):
        return self.async_create_entry(
            title="Copilot Bridge",
            data=self._entry_data,
        )

