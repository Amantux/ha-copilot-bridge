from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


class CopilotBridgeApiError(Exception):
    """Raised when the Copilot bridge API request fails."""


class CopilotBridgeApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        use_home_assistant_mcp: bool = False,
        home_assistant_mcp_server_name: str | None = None,
        session: aiohttp.ClientSession,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._use_home_assistant_mcp = use_home_assistant_mcp
        self._home_assistant_mcp_server_name = home_assistant_mcp_server_name
        self._session = session

    async def async_health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def async_auth_status(self) -> dict[str, Any]:
        return await self._request("GET", "/auth/status")

    async def async_start_github_device_flow(
        self, *, scopes: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if scopes:
            payload["scopes"] = scopes
        return await self._request("POST", "/auth/device/start", json_payload=payload)

    async def async_poll_github_device_flow(self) -> dict[str, Any]:
        return await self._request("POST", "/auth/device/poll", json_payload={})

    async def async_set_github_token(self, *, token: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/auth/token",
            json_payload={"token": token},
        )

    async def async_clear_github_auth(self) -> dict[str, Any]:
        return await self._request("POST", "/auth/logout", json_payload={})

    async def async_ask(
        self,
        *,
        prompt: str,
        session_id: str | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
        language: str | None = None,
        device_id: str | None = None,
        satellite_id: str | None = None,
        source: str | None = None,
        use_home_assistant_mcp: bool | None = None,
        home_assistant_mcp_server_name: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"prompt": prompt}
        if session_id:
            payload["session_id"] = session_id
        if user_id:
            payload["user_id"] = user_id
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if language:
            payload["language"] = language
        if device_id:
            payload["device_id"] = device_id
        if satellite_id:
            payload["satellite_id"] = satellite_id
        if source:
            payload["source"] = source
        resolved_use_home_assistant_mcp = (
            self._use_home_assistant_mcp
            if use_home_assistant_mcp is None
            else use_home_assistant_mcp
        )
        if resolved_use_home_assistant_mcp:
            payload["use_home_assistant_mcp"] = True
        resolved_home_assistant_mcp_server_name = (
            home_assistant_mcp_server_name or self._home_assistant_mcp_server_name
        )
        if resolved_home_assistant_mcp_server_name:
            payload["home_assistant_mcp_server_name"] = (
                resolved_home_assistant_mcp_server_name
            )

        return await self._request("POST", "/api/ask", json_payload=payload)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["X-Bridge-API-Key"] = self._api_key

        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                json=json_payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                data = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise CopilotBridgeApiError(str(err)) from err

        if response.status >= 400:
            message = data.get("error", f"HTTP {response.status}")
            raise CopilotBridgeApiError(str(message))

        return data

