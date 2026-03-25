from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CopilotBridgeApiClient, CopilotBridgeApiError
from .config_flow import _create_bridge_client
from .const import (
    CONF_ALLOW_FILESYSTEM_ACCESS,
    CONF_ALLOW_HOME_ASSISTANT_ACTIONS,
    CONF_ASSISTANT_PROFILE,
    CONF_ENABLE_HACS_DISCOVERY,
    CONF_ENABLE_INTEGRATION_DISCOVERY,
    CONF_ENABLE_TOOLING_DISCOVERY,
    CONF_HOME_ASSISTANT_MCP_SERVER_NAME,
    CONF_READ_ONLY_MODE,
    CONF_USE_HOME_ASSISTANT_MCP,
    DATA_AGENT,
    DATA_CLIENT,
    DEFAULT_ALLOW_FILESYSTEM_ACCESS,
    DEFAULT_ALLOW_HOME_ASSISTANT_ACTIONS,
    DEFAULT_ASSISTANT_PROFILE,
    DEFAULT_ENABLE_HACS_DISCOVERY,
    DEFAULT_ENABLE_INTEGRATION_DISCOVERY,
    DEFAULT_ENABLE_TOOLING_DISCOVERY,
    DEFAULT_READ_ONLY_MODE,
    DEFAULT_URL,
    DOMAIN,
    SERVICE_CLEAR_GITHUB_AUTH,
    SERVICE_ASK,
    SERVICE_GET_GITHUB_AUTH_STATUS,
    SERVICE_POLL_GITHUB_DEVICE_FLOW,
    SERVICE_SET_GITHUB_TOKEN,
    SERVICE_START_GITHUB_DEVICE_FLOW,
)
from .conversation_agent import CopilotBridgeConversationAgent

ASK_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("prompt"): str,
        vol.Optional("session_id"): str,
        vol.Optional("entry_id"): str,
        vol.Optional("user_id"): str,
        vol.Optional("use_home_assistant_mcp"): bool,
    }
)

ENTRY_ONLY_SCHEMA = vol.Schema({vol.Optional("entry_id"): str})

START_GITHUB_DEVICE_FLOW_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("scopes"): str,
    }
)

SET_GITHUB_TOKEN_SCHEMA = vol.Schema(
    {
        vol.Required("token"): str,
        vol.Optional("entry_id"): str,
    }
)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    async def handle_ask(call: ServiceCall) -> ServiceResponse:
        client = _resolve_client(hass, call.data.get("entry_id"))
        return await client.async_ask(
            prompt=call.data["prompt"],
            session_id=call.data.get("session_id"),
            user_id=call.data.get("user_id"),
            conversation_id=call.data.get("session_id"),
            source="service",
            use_home_assistant_mcp=call.data.get("use_home_assistant_mcp"),
        )

    async def handle_get_github_auth_status(call: ServiceCall) -> ServiceResponse:
        client = _resolve_client(hass, call.data.get("entry_id"))
        return await client.async_auth_status()

    async def handle_start_github_device_flow(call: ServiceCall) -> ServiceResponse:
        client = _resolve_client(hass, call.data.get("entry_id"))
        return await client.async_start_github_device_flow(
            scopes=call.data.get("scopes")
        )

    async def handle_poll_github_device_flow(call: ServiceCall) -> ServiceResponse:
        client = _resolve_client(hass, call.data.get("entry_id"))
        return await client.async_poll_github_device_flow()

    async def handle_set_github_token(call: ServiceCall) -> ServiceResponse:
        client = _resolve_client(hass, call.data.get("entry_id"))
        return await client.async_set_github_token(token=call.data["token"])

    async def handle_clear_github_auth(call: ServiceCall) -> ServiceResponse:
        client = _resolve_client(hass, call.data.get("entry_id"))
        return await client.async_clear_github_auth()

    hass.services.async_register(
        DOMAIN,
        SERVICE_ASK,
        handle_ask,
        schema=ASK_SERVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_GITHUB_AUTH_STATUS,
        handle_get_github_auth_status,
        schema=ENTRY_ONLY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_GITHUB_DEVICE_FLOW,
        handle_start_github_device_flow,
        schema=START_GITHUB_DEVICE_FLOW_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_POLL_GITHUB_DEVICE_FLOW,
        handle_poll_github_device_flow,
        schema=ENTRY_ONLY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_GITHUB_TOKEN,
        handle_set_github_token,
        schema=SET_GITHUB_TOKEN_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_GITHUB_AUTH,
        handle_clear_github_auth,
        schema=ENTRY_ONLY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = _create_bridge_client(hass, entry.data, entry.options)

    try:
        await client.async_health()
    except CopilotBridgeApiError as err:
        raise ConfigEntryNotReady(f"Unable to connect to bridge: {err}") from err

    agent = CopilotBridgeConversationAgent(client=client)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_CLIENT: client,
        DATA_AGENT: agent,
    }
    conversation.async_set_agent(hass, entry, agent)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    conversation.async_unset_agent(hass, entry)
    return True


def _resolve_client(hass: HomeAssistant, entry_id: str | None) -> CopilotBridgeApiClient:
    entries: dict[str, dict[str, Any]] = hass.data.get(DOMAIN, {})
    if not entries:
        raise HomeAssistantError("No Copilot Bridge config entry is loaded")

    if entry_id:
        entry_data = entries.get(entry_id)
        if entry_data is None:
            raise HomeAssistantError(f"Unknown config entry: {entry_id}")
        return entry_data[DATA_CLIENT]

    return next(iter(entries.values()))[DATA_CLIENT]

