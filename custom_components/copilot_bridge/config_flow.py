from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CopilotBridgeApiClient, CopilotBridgeApiError
from .const import (
    CONF_HOME_ASSISTANT_MCP_SERVER_NAME,
    CONF_USE_HOME_ASSISTANT_MCP,
    DEFAULT_HOME_ASSISTANT_MCP_SERVER_NAME,
    DEFAULT_URL,
    DOMAIN,
)


class CopilotBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

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
                return self.async_create_entry(
                    title="Copilot Bridge",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=DEFAULT_URL): str,
                    vol.Optional(CONF_API_KEY): str,
                    vol.Optional(CONF_USE_HOME_ASSISTANT_MCP, default=False): bool,
                    vol.Optional(
                        CONF_HOME_ASSISTANT_MCP_SERVER_NAME,
                        default=DEFAULT_HOME_ASSISTANT_MCP_SERVER_NAME,
                    ): str,
                }
            ),
            errors=errors,
        )

