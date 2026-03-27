from __future__ import annotations

import importlib.util
import json
import logging
import os
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error, parse, request

if importlib.util.find_spec("zeroconf") is not None:
    from zeroconf import IPVersion, ServiceInfo, Zeroconf
else:
    IPVersion = None
    ServiceInfo = None
    Zeroconf = None

BRIDGE_VERSION = "0.1.15"
API_KEY = os.getenv("BRIDGE_API_KEY", "")
COPILOT_API_TOKEN = os.getenv("COPILOT_API_TOKEN", "").strip()
PORT = int(os.getenv("BRIDGE_PORT", "8099"))
ALLOWED_PATHS = os.getenv("ALLOWED_PATHS", "/config")
ASSISTANT_PROFILE = os.getenv(
    "ASSISTANT_PROFILE", "home_assistant_read_only_advisor"
).strip() or "home_assistant_read_only_advisor"
READ_ONLY_MODE = os.getenv("READ_ONLY_MODE", "true").strip().lower() == "true"
ALLOW_HOME_ASSISTANT_ACTIONS = (
    os.getenv("ALLOW_HOME_ASSISTANT_ACTIONS", "false").strip().lower() == "true"
)
ALLOW_FILESYSTEM_ACCESS = (
    os.getenv("ALLOW_FILESYSTEM_ACCESS", "false").strip().lower() == "true"
)
ENABLE_INTEGRATION_DISCOVERY = (
    os.getenv("ENABLE_INTEGRATION_DISCOVERY", "true").strip().lower() == "true"
)
ENABLE_HACS_DISCOVERY = (
    os.getenv("ENABLE_HACS_DISCOVERY", "true").strip().lower() == "true"
)
ENABLE_TOOLING_DISCOVERY = (
    os.getenv("ENABLE_TOOLING_DISCOVERY", "true").strip().lower() == "true"
)
ENABLE_HOME_ASSISTANT_MCP = (
    os.getenv("ENABLE_HOME_ASSISTANT_MCP", "false").strip().lower() == "true"
)
HOME_ASSISTANT_MCP_URL = os.getenv("HOME_ASSISTANT_MCP_URL", "").strip()
HOME_ASSISTANT_MCP_BEARER_TOKEN = os.getenv(
    "HOME_ASSISTANT_MCP_BEARER_TOKEN", ""
).strip()
HOME_ASSISTANT_MCP_API_KEY = os.getenv("HOME_ASSISTANT_MCP_API_KEY", "").strip()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
ENABLE_ZEROCONF_DISCOVERY = (
    os.getenv("ENABLE_ZEROCONF_DISCOVERY", "true").strip().lower() == "true"
)
ZEROCONF_SERVICE_TYPE = "_copilot-bridge._tcp.local."
ZEROCONF_SERVICE_NAME = (
    os.getenv("ZEROCONF_SERVICE_NAME", "Copilot Bridge").strip() or "Copilot Bridge"
)

COPILOT_API_BASE = "https://api.githubcopilot.com"
ZEROCONF_RUNTIME: Any = None
ZEROCONF_SERVICE_INFO: Any = None


def _resolve_log_level(level_name: str) -> int:
    normalized = level_name.upper()
    if normalized == "TRACE":
        return logging.DEBUG
    return getattr(logging, normalized, logging.INFO)


logging.basicConfig(
    level=_resolve_log_level(LOG_LEVEL),
    format="%(asctime)s %(levelname)s [copilot_bridge] %(message)s",
)
LOGGER = logging.getLogger("copilot_bridge")


class BridgeError(Exception):
    """Raised for bridge-specific errors."""

    def __init__(
        self,
        status: HTTPStatus,
        code: str,
        message: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra or {}


def _resolved_home_assistant_mcp_bearer_token() -> str:
    return HOME_ASSISTANT_MCP_BEARER_TOKEN or HOME_ASSISTANT_MCP_API_KEY


def _local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    hostname = socket.gethostname()

    for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
        ip = info[4][0]
        if not ip.startswith("127."):
            addresses.add(ip)

    if not addresses:
        try:
            fallback_ip = socket.gethostbyname(hostname)
        except OSError:
            fallback_ip = ""
        if fallback_ip and not fallback_ip.startswith("127."):
            addresses.add(fallback_ip)

    return sorted(addresses)


def _register_zeroconf_service() -> None:
    global ZEROCONF_RUNTIME, ZEROCONF_SERVICE_INFO

    if not ENABLE_ZEROCONF_DISCOVERY:
        LOGGER.info("Zeroconf discovery disabled by configuration")
        return
    if Zeroconf is None or ServiceInfo is None or IPVersion is None:
        LOGGER.info("zeroconf dependency not installed; discovery advertisement disabled")
        return

    addresses = _local_ipv4_addresses()
    if not addresses:
        LOGGER.warning("No non-loopback IPv4 address found; zeroconf advertisement skipped")
        return

    instance_name = f"{ZEROCONF_SERVICE_NAME}.{ZEROCONF_SERVICE_TYPE}"
    props = {
        b"service": b"copilot_bridge",
        b"version": BRIDGE_VERSION.encode("utf-8"),
        b"api_path": b"/api/ask",
        b"health_path": b"/health",
    }

    try:
        zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        info = ServiceInfo(
            type_=ZEROCONF_SERVICE_TYPE,
            name=instance_name,
            addresses=[socket.inet_aton(addresses[0])],
            port=PORT,
            properties=props,
            server=f"{socket.gethostname()}.local.",
        )
        zeroconf.register_service(info)
        ZEROCONF_RUNTIME = zeroconf
        ZEROCONF_SERVICE_INFO = info
        LOGGER.info(
            "Registered zeroconf service %s at %s:%s",
            instance_name,
            addresses[0],
            PORT,
        )
    except Exception:
        LOGGER.exception("Failed to register zeroconf service")
        ZEROCONF_RUNTIME = None
        ZEROCONF_SERVICE_INFO = None


def _unregister_zeroconf_service() -> None:
    global ZEROCONF_RUNTIME, ZEROCONF_SERVICE_INFO
    if ZEROCONF_RUNTIME is None or ZEROCONF_SERVICE_INFO is None:
        return

    try:
        ZEROCONF_RUNTIME.unregister_service(ZEROCONF_SERVICE_INFO)
        LOGGER.info("Unregistered zeroconf service %s", ZEROCONF_SERVICE_INFO.name)
    except Exception:
        LOGGER.exception("Failed to unregister zeroconf service")
    finally:
        ZEROCONF_RUNTIME.close()
        ZEROCONF_RUNTIME = None
        ZEROCONF_SERVICE_INFO = None


def _home_assistant_mcp_uses_private_url() -> bool:
    if not HOME_ASSISTANT_MCP_URL:
        return False
    try:
        return "/private_" in parse.urlparse(HOME_ASSISTANT_MCP_URL).path
    except ValueError:
        return "/private_" in HOME_ASSISTANT_MCP_URL


def _home_assistant_mcp_auth_mode() -> str:
    if _home_assistant_mcp_uses_private_url():
        return "secret_url"
    if _resolved_home_assistant_mcp_bearer_token():
        return "bearer_token"
    if HOME_ASSISTANT_MCP_URL:
        return "url_only"
    return "none"


def _default_assistant_policy() -> dict[str, Any]:
    return {
        "assistant_profile": ASSISTANT_PROFILE,
        "read_only_mode": READ_ONLY_MODE,
        "allow_home_assistant_actions": ALLOW_HOME_ASSISTANT_ACTIONS,
        "allow_filesystem_access": ALLOW_FILESYSTEM_ACCESS,
        "enable_integration_discovery": ENABLE_INTEGRATION_DISCOVERY,
        "enable_hacs_discovery": ENABLE_HACS_DISCOVERY,
        "enable_tooling_discovery": ENABLE_TOOLING_DISCOVERY,
    }


def _effective_assistant_policy(requested_policy: dict[str, Any] | None) -> dict[str, Any]:
    policy = _default_assistant_policy()
    if isinstance(requested_policy, dict):
        for key in (
            "assistant_profile",
            "read_only_mode",
            "allow_home_assistant_actions",
            "allow_filesystem_access",
            "enable_integration_discovery",
            "enable_hacs_discovery",
            "enable_tooling_discovery",
        ):
            if key in requested_policy:
                policy[key] = requested_policy[key]

    if policy.get("read_only_mode", True):
        policy["allow_home_assistant_actions"] = False
        policy["allow_filesystem_access"] = False

    policy["allow_filesystem_access"] = False
    return policy


def _build_system_prompt(policy: dict[str, Any]) -> str:
    capabilities: list[str] = []
    if policy.get("enable_integration_discovery"):
        capabilities.append("official Home Assistant integrations")
    if policy.get("enable_hacs_discovery"):
        capabilities.append("HACS integrations, add-ons, and cards")
    if policy.get("enable_tooling_discovery"):
        capabilities.append("general Home Assistant tooling and operational guidance")

    capability_text = ", ".join(capabilities) if capabilities else "general guidance"
    return (
        "You are a Home Assistant advisor focused on intent understanding and read-only guidance. "
        f"You may recommend {capability_text}. "
        "Do not modify the filesystem, do not execute host commands, and do not claim to perform actions you cannot verify. "
        "Prefer recommendations, configuration guidance, setup steps, and safe next actions."
    )


def _read_json_response(http_response: Any) -> dict[str, Any]:
    body = http_response.read()
    if not body:
        return {}
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object")
    return data


def _call_copilot_chat(
    prompt: str,
    system_prompt: str,
    *,
    mcp_url: str | None = None,
    mcp_bearer_token: str | None = None,
) -> str:
    if not COPILOT_API_TOKEN:
        raise BridgeError(
            HTTPStatus.UNAUTHORIZED,
            "copilot_not_configured",
            "COPILOT_API_TOKEN is not configured.",
        )

    effective_system = system_prompt
    if mcp_url:
        effective_system += (
            f"\n\nThe user's Home Assistant instance exposes an MCP server at: {mcp_url}. "
            "You may reference this when suggesting configuration or automation steps."
        )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": effective_system},
        {"role": "user", "content": prompt},
    ]

    request_body: dict[str, Any] = {
        "model": "gpt-4o",
        "messages": messages,
        "stream": False,
        "max_tokens": 4096,
        "temperature": 0,
    }

    payload = json.dumps(request_body).encode("utf-8")
    req = request.Request(
        f"{COPILOT_API_BASE}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {COPILOT_API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Copilot-Integration-Id": "vscode-chat",
            "Editor-Version": "vscode/1.90.0",
            "Editor-Plugin-Version": "copilot-chat/0.17.1",
            "User-Agent": f"ha-copilot-bridge/{BRIDGE_VERSION}",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=90) as response:
            result = _read_json_response(response)
    except error.HTTPError as err:
        try:
            err_payload = _read_json_response(err)
        except (ValueError, json.JSONDecodeError):
            err_payload = {}
        message = str(
            err_payload.get("message") or err_payload.get("error") or err.reason
        )
        LOGGER.error("Copilot API call failed: status=%s message=%s", err.code, message)
        raise BridgeError(
            HTTPStatus.BAD_GATEWAY,
            "copilot_api_error",
            f"Copilot API error ({err.code}): {message}",
        ) from err
    except error.URLError as err:
        raise BridgeError(
            HTTPStatus.BAD_GATEWAY,
            "copilot_network_error",
            f"Network error calling Copilot API: {err.reason}",
        ) from err

    choices = result.get("choices")
    if not choices:
        LOGGER.error("Copilot API returned no choices: response=%s", result)
        raise BridgeError(
            HTTPStatus.BAD_GATEWAY,
            "copilot_no_choices",
            "Copilot API returned no response choices.",
        )

    content = str(choices[0].get("message", {}).get("content") or "").strip()
    if not content:
        raise BridgeError(
            HTTPStatus.BAD_GATEWAY,
            "copilot_empty_response",
            "Copilot API returned an empty response.",
        )

    usage = result.get("usage") or {}
    LOGGER.info(
        "Copilot API response received: prompt_tokens=%s completion_tokens=%s",
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
    )
    return content


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = f"copilot-bridge/{BRIDGE_VERSION}"

    def do_GET(self) -> None:
        LOGGER.debug("Handling GET %s", self.path)
        if self.path == "/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "service": "copilot_bridge",
                    "version": BRIDGE_VERSION,
                    "allowed_paths": ALLOWED_PATHS,
                    "assistant_policy": _default_assistant_policy(),
                    "copilot_auth": {
                        "configured": bool(COPILOT_API_TOKEN),
                        "mode": "api_token" if COPILOT_API_TOKEN else "none",
                    },
                    "mcp": {
                        "home_assistant": {
                            "enabled_by_default": ENABLE_HOME_ASSISTANT_MCP,
                            "configured": bool(HOME_ASSISTANT_MCP_URL),
                            "auth_mode": _home_assistant_mcp_auth_mode(),
                            "uses_private_url": _home_assistant_mcp_uses_private_url(),
                        }
                    },
                },
            )
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        try:
            LOGGER.debug("Handling POST %s", self.path)
            if API_KEY and self.headers.get("X-Bridge-API-Key") != API_KEY:
                LOGGER.warning("Rejected request with invalid or missing bridge API key")
                raise BridgeError(
                    HTTPStatus.UNAUTHORIZED,
                    "unauthorized",
                    "Missing or invalid bridge API key.",
                )

            if self.path != "/api/ask":
                raise BridgeError(
                    HTTPStatus.NOT_FOUND,
                    "not_found",
                    "Unknown API path.",
                )

            payload = self._read_json()
            prompt = str(payload.get("prompt", "")).strip()
            session_id = payload.get("session_id")
            conversation_id = payload.get("conversation_id")
            user_id = payload.get("user_id")
            language = payload.get("language")
            device_id = payload.get("device_id")
            satellite_id = payload.get("satellite_id")
            source = payload.get("source", "unknown")
            requested_home_assistant_mcp = bool(
                payload.get("use_home_assistant_mcp", ENABLE_HOME_ASSISTANT_MCP)
            )
            assistant_policy = _effective_assistant_policy(
                payload.get("assistant_policy")
            )
            home_assistant_mcp_server_name = str(
                payload.get("home_assistant_mcp_server_name", "home_assistant")
            ).strip() or "home_assistant"
            home_assistant_mcp_active = bool(
                requested_home_assistant_mcp and HOME_ASSISTANT_MCP_URL
            )

            if not prompt:
                raise BridgeError(
                    HTTPStatus.BAD_REQUEST,
                    "missing_prompt",
                    "Prompt is required.",
                )

            system_prompt = _build_system_prompt(assistant_policy)
            mcp_url = HOME_ASSISTANT_MCP_URL if home_assistant_mcp_active else None
            mcp_token = (
                _resolved_home_assistant_mcp_bearer_token()
                if home_assistant_mcp_active
                else None
            )

            LOGGER.info(
                "Calling Copilot API: source=%s language=%s mcp_active=%s",
                source,
                language,
                home_assistant_mcp_active,
            )
            response_text = _call_copilot_chat(
                prompt,
                system_prompt,
                mcp_url=mcp_url,
                mcp_bearer_token=mcp_token,
            )

            self._send_json(
                HTTPStatus.OK,
                {
                    "response": response_text,
                    "session_id": session_id or conversation_id or "default",
                    "conversation_id": conversation_id or session_id or "default",
                    "user_id": user_id,
                    "device_id": device_id,
                    "satellite_id": satellite_id,
                    "authenticated": bool(COPILOT_API_TOKEN),
                    "auth_mode": "api_token" if COPILOT_API_TOKEN else "none",
                    "assistant_policy": assistant_policy,
                    "system_prompt": system_prompt,
                    "mcp": {
                        "home_assistant": {
                            "requested": requested_home_assistant_mcp,
                            "active": home_assistant_mcp_active,
                            "configured": bool(HOME_ASSISTANT_MCP_URL),
                            "auth_mode": _home_assistant_mcp_auth_mode(),
                            "uses_private_url": _home_assistant_mcp_uses_private_url(),
                            "has_bearer_token": bool(
                                _resolved_home_assistant_mcp_bearer_token()
                            ),
                            "server_name": home_assistant_mcp_server_name,
                        }
                    },
                },
            )
        except BridgeError as err:
            LOGGER.warning(
                "Bridge request failed: path=%s status=%s code=%s message=%s",
                self.path,
                err.status,
                err.code,
                err.message,
            )
            payload = {"error": err.code, "message": err.message}
            payload.update(err.extra)
            self._send_json(err.status, payload)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}

        raw = self.rfile.read(content_length)
        if not raw:
            return {}

        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as err:
            LOGGER.warning("Rejected invalid JSON payload for path=%s", self.path)
            raise BridgeError(
                HTTPStatus.BAD_REQUEST,
                "invalid_json",
                "Request body must be valid JSON.",
            ) from err

        if not isinstance(payload, dict):
            LOGGER.warning("Rejected non-object JSON payload for path=%s", self.path)
            raise BridgeError(
                HTTPStatus.BAD_REQUEST,
                "invalid_json",
                "Request body must be a JSON object.",
            )
        return payload

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), BridgeHandler)
    _register_zeroconf_service()
    LOGGER.info(
        "copilot_bridge listening on :%s version=%s log_level=%s copilot_auth_configured=%s",
        PORT,
        BRIDGE_VERSION,
        LOG_LEVEL,
        bool(COPILOT_API_TOKEN),
    )
    try:
        server.serve_forever()
    finally:
        _unregister_zeroconf_service()


if __name__ == "__main__":
    main()
