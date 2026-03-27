from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import socket
import time
import importlib.util
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


BRIDGE_VERSION = "0.1.11"
API_KEY = os.getenv("BRIDGE_API_KEY", "")
CONFIGURED_GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_OAUTH_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID", "").strip()
GITHUB_OAUTH_SCOPES = os.getenv("GITHUB_OAUTH_SCOPES", "read:user").strip()
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
AUTH_STATE_PATH = Path(
    os.getenv("GITHUB_AUTH_STATE_PATH", "/config/copilot_bridge_github_auth.json")
)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
ENABLE_ZEROCONF_DISCOVERY = (
    os.getenv("ENABLE_ZEROCONF_DISCOVERY", "true").strip().lower() == "true"
)
ZEROCONF_SERVICE_TYPE = "_copilot-bridge._tcp.local."
ZEROCONF_SERVICE_NAME = (
    os.getenv("ZEROCONF_SERVICE_NAME", "Copilot Bridge").strip() or "Copilot Bridge"
)
AUTH_STATE_LOAD_ERROR: str | None = None

COPILOT_API_BASE = "https://api.githubcopilot.com"
COPILOT_TOKEN_EXCHANGE_URL = f"https://api.github.com/copilot_internal/v2/token"
COPILOT_TOKEN_REFRESH_BUFFER = 120  # seconds before expiry to refresh
COPILOT_TOKEN_CACHE: dict[str, Any] = {}
COPILOT_TOKEN_LOCK = threading.Lock()
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


class GitHubApiError(Exception):
    """Raised when GitHub returns an API error."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.payload = payload or {}


def _default_auth_state() -> dict[str, Any]:
    return {
        "github": {
            "access_token": None,
            "token_type": None,
            "scope": None,
            "source": "none",
            "user": None,
            "pending_device_flow": None,
            "last_error": None,
            "updated_at": None,
        }
    }


def _load_auth_state() -> dict[str, Any]:
    global AUTH_STATE_LOAD_ERROR
    state = _default_auth_state()
    if AUTH_STATE_PATH.exists():
        try:
            loaded = json.loads(AUTH_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state.update(loaded)
            AUTH_STATE_LOAD_ERROR = None
        except (OSError, json.JSONDecodeError) as err:
            AUTH_STATE_LOAD_ERROR = f"Failed to load persisted GitHub auth state: {err}"

    github = state.setdefault("github", {})
    github.setdefault("access_token", None)
    github.setdefault("token_type", None)
    github.setdefault("scope", None)
    github.setdefault("source", "none")
    github.setdefault("user", None)
    github.setdefault("pending_device_flow", None)
    github.setdefault("last_error", None)
    github.setdefault("updated_at", None)

    # Clear stale pending flows that have no user_code — they came from a previous
    # crashed or incomplete auth attempt and can never complete.
    pending = github.get("pending_device_flow")
    if pending is not None and not pending.get("user_code"):
        LOGGER.info(
            "Clearing stale pending device flow on startup (no user_code): backend=%s",
            pending.get("backend"),
        )
        github["pending_device_flow"] = None

    if CONFIGURED_GITHUB_TOKEN and (
        github.get("access_token") != CONFIGURED_GITHUB_TOKEN
        or github.get("source") != "config_token"
    ):
        github["access_token"] = CONFIGURED_GITHUB_TOKEN
        github["token_type"] = "bearer"
        github["scope"] = None
        github["source"] = "config_token"
        github["user"] = None
        github["pending_device_flow"] = None
        github["last_error"] = None
        github["updated_at"] = int(time.time())

    return state


AUTH_LOCK = threading.Lock()
AUTH_STATE = _load_auth_state()


def _device_flow_backend() -> str:
    if GITHUB_OAUTH_CLIENT_ID:
        return "oauth_app"
    return "none"


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError as err:
        LOGGER.warning("Could not enforce 0700 permissions on %s: %s", path, err)


def _ensure_private_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        os.chmod(path, 0o600)
    except OSError as err:
        LOGGER.warning("Could not enforce 0600 permissions on %s: %s", path, err)


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
    service_info = ServiceInfo(
        type_=ZEROCONF_SERVICE_TYPE,
        name=instance_name,
        addresses=[socket.inet_aton(ip) for ip in addresses],
        port=PORT,
        properties={
            b"path": b"/health",
            b"version": BRIDGE_VERSION.encode("utf-8"),
        },
        server=f"{socket.gethostname()}.local.",
    )
    zeroconf_runtime = Zeroconf(ip_version=IPVersion.V4Only)
    zeroconf_runtime.register_service(service_info)
    ZEROCONF_RUNTIME = zeroconf_runtime
    ZEROCONF_SERVICE_INFO = service_info
    LOGGER.info(
        "Registered zeroconf service name=%s type=%s port=%s addresses=%s",
        instance_name,
        ZEROCONF_SERVICE_TYPE,
        PORT,
        addresses,
    )


def _unregister_zeroconf_service() -> None:
    global ZEROCONF_RUNTIME, ZEROCONF_SERVICE_INFO

    if ZEROCONF_RUNTIME is None or ZEROCONF_SERVICE_INFO is None:
        return
    try:
        ZEROCONF_RUNTIME.unregister_service(ZEROCONF_SERVICE_INFO)
    finally:
        ZEROCONF_RUNTIME.close()
        ZEROCONF_RUNTIME = None
        ZEROCONF_SERVICE_INFO = None
        LOGGER.info("Unregistered zeroconf service")


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


def _persist_auth_state_unlocked() -> None:
    try:
        _ensure_private_directory(AUTH_STATE_PATH.parent)
        AUTH_STATE_PATH.write_text(json.dumps(AUTH_STATE, indent=2), encoding="utf-8")
        _ensure_private_file(AUTH_STATE_PATH)
    except OSError as err:
        LOGGER.exception("Failed to persist GitHub auth state to %s", AUTH_STATE_PATH)
        raise BridgeError(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            "auth_state_persist_failed",
            f"Could not persist GitHub auth state to {AUTH_STATE_PATH}: {err}",
        ) from err


def _auth_storage_payload() -> dict[str, Any]:
    directory = AUTH_STATE_PATH.parent
    writable_target = directory
    while not writable_target.exists() and writable_target != writable_target.parent:
        writable_target = writable_target.parent

    return {
        "path": str(AUTH_STATE_PATH),
        "file_exists": AUTH_STATE_PATH.exists(),
        "directory": str(directory),
        "directory_exists": directory.exists(),
        "directory_writable": os.access(writable_target, os.W_OK),
        "load_error": AUTH_STATE_LOAD_ERROR,
    }


def _get_github_state() -> dict[str, Any]:
    with AUTH_LOCK:
        return json.loads(json.dumps(AUTH_STATE["github"]))


def _update_github_state(**updates: Any) -> dict[str, Any]:
    with AUTH_LOCK:
        github = AUTH_STATE["github"]
        github.update(updates)
        github["updated_at"] = int(time.time())
        _persist_auth_state_unlocked()
        return json.loads(json.dumps(github))


def _clear_pending_device_flow(last_error: dict[str, Any] | None = None) -> dict[str, Any]:
    return _update_github_state(pending_device_flow=None, last_error=last_error)


def _auth_status_payload() -> dict[str, Any]:
    github = _enrich_github_state_if_needed()
    pending = github.get("pending_device_flow")
    pending_public = None
    if pending:
        pending_public = _public_pending_device_flow(pending)

    browser_auth_backend = _device_flow_backend()

    return {
        "authenticated": bool(github.get("access_token")),
        "auth_mode": github.get("source") if github.get("access_token") else "none",
        "oauth_client_configured": bool(GITHUB_OAUTH_CLIENT_ID),
        "configured_token_present": bool(CONFIGURED_GITHUB_TOKEN),
        "browser_auth_supported": browser_auth_backend != "none",
        "browser_auth_backend": browser_auth_backend,
        "can_start_device_flow": browser_auth_backend != "none",
        "default_scopes": GITHUB_OAUTH_SCOPES,
        "user": github.get("user"),
        "scope": github.get("scope"),
        "pending_device_flow": pending_public,
        "last_error": github.get("last_error"),
        "storage": _auth_storage_payload(),
        "mcp": {
            "home_assistant": {
                "enabled_by_default": ENABLE_HOME_ASSISTANT_MCP,
                "configured": bool(HOME_ASSISTANT_MCP_URL),
                "auth_mode": _home_assistant_mcp_auth_mode(),
                "uses_private_url": _home_assistant_mcp_uses_private_url(),
                "has_bearer_token": bool(_resolved_home_assistant_mcp_bearer_token()),
            }
        },
        "assistant_policy": _default_assistant_policy(),
    }


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


def _read_json_response_with_headers(
    http_response: Any,
) -> tuple[dict[str, Any], dict[str, str]]:
    return _read_json_response(http_response), {
        str(key).lower(): str(value) for key, value in http_response.headers.items()
    }


def _github_post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    encoded = parse.urlencode(data).encode("utf-8")
    req = request.Request(
        url,
        data=encoded,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": f"ha-copilot-bridge/{BRIDGE_VERSION}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=15) as response:
            return _read_json_response(response)
    except error.HTTPError as err:
        try:
            payload = _read_json_response(err)
        except (ValueError, json.JSONDecodeError):
            payload = {}
        raise GitHubApiError(
            err.code,
            str(payload.get("error", "github_http_error")),
            str(
                payload.get("error_description")
                or payload.get("message")
                or err.reason
            ),
            payload=payload,
        ) from err
    except error.URLError as err:
        raise GitHubApiError(502, "network_error", str(err.reason)) from err


def _github_get_json(url: str, token: str) -> dict[str, Any]:
    req = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": f"ha-copilot-bridge/{BRIDGE_VERSION}",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=15) as response:
            return _read_json_response(response)
    except error.HTTPError as err:
        try:
            payload = _read_json_response(err)
        except (ValueError, json.JSONDecodeError):
            payload = {}
        raise GitHubApiError(
            err.code,
            str(payload.get("error", "github_http_error")),
            str(payload.get("message") or err.reason),
            payload=payload,
        ) from err
    except error.URLError as err:
        raise GitHubApiError(502, "network_error", str(err.reason)) from err


def _github_get_json_with_headers(
    url: str, token: str
) -> tuple[dict[str, Any], dict[str, str]]:
    req = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": f"ha-copilot-bridge/{BRIDGE_VERSION}",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=15) as response:
            return _read_json_response_with_headers(response)
    except error.HTTPError as err:
        try:
            payload = _read_json_response(err)
        except (ValueError, json.JSONDecodeError):
            payload = {}
        raise GitHubApiError(
            err.code,
            str(payload.get("error", "github_http_error")),
            str(payload.get("message") or err.reason),
            payload=payload,
        ) from err
    except error.URLError as err:
        raise GitHubApiError(502, "network_error", str(err.reason)) from err


def _fetch_github_user(token: str) -> tuple[dict[str, Any], str | None]:
    user, headers = _github_get_json_with_headers("https://api.github.com/user", token)
    return (
        {
            "login": user.get("login"),
            "id": user.get("id"),
            "name": user.get("name"),
            "html_url": user.get("html_url"),
        },
        (headers.get("x-oauth-scopes", "").strip() or None),
    )


def _enrich_github_state_if_needed() -> dict[str, Any]:
    github = _get_github_state()
    access_token = github.get("access_token")
    if not access_token:
        return github

    if github.get("user") and github.get("scope") is not None:
        return github

    try:
        user, scope = _fetch_github_user(str(access_token))
    except GitHubApiError as err:
        LOGGER.warning(
            "Failed to enrich GitHub auth state from GitHub API: code=%s message=%s",
            err.code,
            err.message,
        )
        return _update_github_state(
            last_error={"code": err.code, "message": err.message}
        )

    updates: dict[str, Any] = {"last_error": None}
    if not github.get("user"):
        updates["user"] = user
    if github.get("scope") is None:
        updates["scope"] = scope
    return _update_github_state(**updates)


def _start_oauth_device_flow(scopes: str | None) -> dict[str, Any]:
    if not GITHUB_OAUTH_CLIENT_ID:
        raise BridgeError(
            HTTPStatus.BAD_REQUEST,
            "missing_oauth_client_id",
            "GitHub OAuth client ID is not configured on the add-on.",
        )

    requested_scopes = (scopes or GITHUB_OAUTH_SCOPES or "read:user").strip()
    LOGGER.info("Starting GitHub OAuth device flow: scopes=%s", requested_scopes)
    result = _github_post_form(
        "https://github.com/login/device/code",
        {
            "client_id": GITHUB_OAUTH_CLIENT_ID,
            "scope": requested_scopes,
        },
    )
    expires_in = int(result["expires_in"])
    interval = int(result["interval"])
    pending = {
        "client_id": GITHUB_OAUTH_CLIENT_ID,
        "device_code": result["device_code"],
        "user_code": result["user_code"],
        "verification_uri": result["verification_uri"],
        "expires_at": int(time.time()) + expires_in,
        "interval": interval,
        "scope": requested_scopes,
        "last_poll_at": 0,
    }
    _update_github_state(
        pending_device_flow=pending,
        last_error=None,
    )
    return {
        "status": "pending",
        **_public_pending_device_flow(pending),
    }


def _poll_oauth_device_flow() -> dict[str, Any]:
    github = _get_github_state()
    pending = github.get("pending_device_flow")
    if not pending:
        raise BridgeError(
            HTTPStatus.BAD_REQUEST,
            "device_flow_not_started",
            "No GitHub device flow is currently pending.",
        )

    now = int(time.time())
    if now >= int(pending["expires_at"]):
        LOGGER.warning("GitHub OAuth device flow expired before authorization completed")
        _clear_pending_device_flow(
            {"code": "expired_token", "message": "The GitHub device code expired."}
        )
        raise BridgeError(
            HTTPStatus.BAD_REQUEST,
            "expired_token",
            "The GitHub device code expired. Start the device flow again.",
        )

    wait_seconds = int(pending["interval"]) - (now - int(pending["last_poll_at"]))
    if pending["last_poll_at"] and wait_seconds > 0:
        LOGGER.debug("GitHub OAuth device flow polled too quickly: wait_seconds=%s", wait_seconds)
        raise BridgeError(
            HTTPStatus.TOO_MANY_REQUESTS,
            "poll_interval_not_met",
            f"Wait {wait_seconds} more seconds before polling GitHub again.",
            extra={"wait_seconds": wait_seconds},
        )

    with AUTH_LOCK:
        AUTH_STATE["github"]["pending_device_flow"]["last_poll_at"] = now
        _persist_auth_state_unlocked()

    try:
        result = _github_post_form(
            "https://github.com/login/oauth/access_token",
            {
                "client_id": pending["client_id"],
                "device_code": pending["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
    except GitHubApiError as err:
        if err.code == "authorization_pending":
            LOGGER.info("GitHub OAuth device flow still pending authorization")
            _update_github_state(
                last_error={
                    "code": err.code,
                    "message": "Authorization is still pending.",
                }
            )
            return {
                "status": "pending",
                "wait_seconds": pending["interval"],
                "message": "Authorization is still pending.",
            }
        if err.code == "slow_down":
            new_interval = int(pending["interval"]) + 5
            LOGGER.warning(
                "GitHub OAuth device flow requested slow_down; increasing interval to %s",
                new_interval,
            )
            with AUTH_LOCK:
                AUTH_STATE["github"]["pending_device_flow"]["interval"] = new_interval
                AUTH_STATE["github"]["last_error"] = {
                    "code": err.code,
                    "message": err.message,
                }
                _persist_auth_state_unlocked()
            return {
                "status": "pending",
                "wait_seconds": new_interval,
                "message": err.message,
            }
        if err.code in {"access_denied", "expired_token"}:
            LOGGER.warning("GitHub OAuth device flow ended with %s", err.code)
            _clear_pending_device_flow({"code": err.code, "message": err.message})
        raise BridgeError(
            HTTPStatus.BAD_GATEWAY,
            err.code,
            err.message,
        ) from err

    access_token = str(result["access_token"])
    token_type = str(result.get("token_type", "bearer"))
    scope = str(result.get("scope", "") or pending.get("scope", ""))
    user, fetched_scope = _fetch_github_user(access_token)
    LOGGER.info(
        "GitHub OAuth device flow completed successfully for user=%s scope=%s",
        (user or {}).get("login"),
        scope or fetched_scope,
    )
    _update_github_state(
        access_token=access_token,
        token_type=token_type,
        scope=scope or fetched_scope,
        source="device_flow",
        user=user,
        pending_device_flow=None,
        last_error=None,
    )
    return {
        "status": "authorized",
        "authenticated": True,
        "auth_mode": "device_flow",
        "user": user,
        "scope": scope,
    }


def _start_device_flow(scopes: str | None) -> dict[str, Any]:
    backend = _device_flow_backend()
    if backend == "oauth_app":
        return _start_oauth_device_flow(scopes)
    raise BridgeError(
        HTTPStatus.BAD_REQUEST,
        "device_flow_not_available",
        "OAuth device flow is not available because GITHUB_OAUTH_CLIENT_ID is not configured.",
    )


def _restart_device_flow(scopes: str | None) -> dict[str, Any]:
    LOGGER.info("Restarting GitHub OAuth device flow from scratch")
    _update_github_state(pending_device_flow=None, last_error=None)
    return _start_device_flow(scopes)


def _poll_device_flow() -> dict[str, Any]:
    return _poll_oauth_device_flow()


def _set_github_token(token: str) -> dict[str, Any]:
    token = token.strip()
    if not token:
        raise BridgeError(
            HTTPStatus.BAD_REQUEST,
            "missing_token",
            "A GitHub token is required.",
        )

    user, scope = _fetch_github_user(token)
    LOGGER.info(
        "Stored GitHub token from manual token flow for user=%s scope=%s",
        (user or {}).get("login"),
        scope,
    )
    _update_github_state(
        access_token=token,
        token_type="bearer",
        scope=scope,
        source="manual_token",
        user=user,
        pending_device_flow=None,
        last_error=None,
    )
    return {
        "status": "authorized",
        "authenticated": True,
        "auth_mode": "manual_token",
        "user": user,
    }


def _clear_github_auth() -> dict[str, Any]:
    LOGGER.info("Cleared GitHub auth state")
    _update_github_state(
        access_token=CONFIGURED_GITHUB_TOKEN or None,
        token_type="bearer" if CONFIGURED_GITHUB_TOKEN else None,
        scope=None,
        source="config_token" if CONFIGURED_GITHUB_TOKEN else "none",
        user=None,
        pending_device_flow=None,
        last_error=None,
    )
    return {
        "status": "cleared",
        "authenticated": bool(CONFIGURED_GITHUB_TOKEN),
        "auth_mode": "config_token" if CONFIGURED_GITHUB_TOKEN else "none",
    }


def _get_copilot_api_token() -> str:
    """Exchange the stored GitHub OAuth token for a short-lived Copilot API token.

    The Copilot API token (~30 min TTL) is cached and refreshed automatically.
    """
    with COPILOT_TOKEN_LOCK:
        cached_token = COPILOT_TOKEN_CACHE.get("token")
        cached_expires = COPILOT_TOKEN_CACHE.get("expires_at", 0)
        if cached_token and time.time() < cached_expires - COPILOT_TOKEN_REFRESH_BUFFER:
            return str(cached_token)

    github = _get_github_state()
    gh_token = github.get("access_token")
    if not gh_token:
        raise BridgeError(
            HTTPStatus.UNAUTHORIZED,
            "github_not_authenticated",
            "GitHub authentication is required. Sign in via the Home Assistant integration first.",
        )

    LOGGER.debug("Exchanging GitHub token for Copilot API token")
    try:
        result = _github_get_json(COPILOT_TOKEN_EXCHANGE_URL, str(gh_token))
    except GitHubApiError as err:
        LOGGER.error(
            "Copilot token exchange failed: status=%s code=%s message=%s",
            err.status,
            err.code,
            err.message,
        )
        raise BridgeError(
            HTTPStatus.BAD_GATEWAY,
            "copilot_token_unavailable",
            (
                f"Could not obtain a Copilot API token: {err.message}. "
                "Ensure your GitHub account has an active Copilot subscription."
            ),
        ) from err

    token = str(result.get("token", "")).strip()
    expires_at = int(result.get("expires_at", int(time.time()) + 1740))
    if not token:
        raise BridgeError(
            HTTPStatus.BAD_GATEWAY,
            "copilot_token_empty",
            "GitHub returned an empty Copilot API token.",
        )

    with COPILOT_TOKEN_LOCK:
        COPILOT_TOKEN_CACHE["token"] = token
        COPILOT_TOKEN_CACHE["expires_at"] = expires_at
    LOGGER.info("Copilot API token refreshed: expires_at=%s", expires_at)
    return token


def _call_copilot_chat(
    prompt: str,
    system_prompt: str,
    *,
    mcp_url: str | None = None,
    mcp_bearer_token: str | None = None,
) -> str:
    """Call the GitHub Copilot chat completions API and return the response text.

    If an MCP server URL is provided and looks publicly reachable, it is passed
    as a remote tool server. Otherwise it is mentioned in the system prompt so
    the model knows it exists for reference.
    """
    copilot_token = _get_copilot_api_token()

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
            "Authorization": f"Bearer {copilot_token}",
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
                    "github_auth": {
                        "oauth_client_configured": bool(GITHUB_OAUTH_CLIENT_ID),
                        "browser_auth_supported": _device_flow_backend() != "none",
                        "browser_auth_backend": _device_flow_backend(),
                        "configured_token_present": bool(CONFIGURED_GITHUB_TOKEN),
                        "default_scopes": GITHUB_OAUTH_SCOPES,
                        "storage": _auth_storage_payload(),
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

        if self.path == "/auth/status":
            self._send_json(HTTPStatus.OK, _auth_status_payload())
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

            if self.path == "/auth/device/start":
                payload = self._read_json()
                LOGGER.info(
                    "Received GitHub auth start request: scopes=%s",
                    str(payload.get("scopes", "")).strip() or GITHUB_OAUTH_SCOPES,
                )
                self._send_json(
                    HTTPStatus.OK,
                    _start_device_flow(str(payload.get("scopes", "")).strip() or None),
                )
                return

            if self.path == "/auth/device/poll":
                self._read_json()
                LOGGER.debug("Received GitHub auth poll request")
                self._send_json(HTTPStatus.OK, _poll_device_flow())
                return

            if self.path == "/auth/device/restart":
                payload = self._read_json()
                LOGGER.info(
                    "Received GitHub auth restart request: scopes=%s",
                    str(payload.get("scopes", "")).strip() or GITHUB_OAUTH_SCOPES,
                )
                self._send_json(
                    HTTPStatus.OK,
                    _restart_device_flow(str(payload.get("scopes", "")).strip() or None),
                )
                return

            if self.path == "/auth/token":
                payload = self._read_json()
                LOGGER.info("Received manual GitHub token configuration request")
                self._send_json(
                    HTTPStatus.OK,
                    _set_github_token(str(payload.get("token", ""))),
                )
                return

            if self.path == "/auth/logout":
                self._read_json()
                LOGGER.info("Received GitHub auth logout request")
                self._send_json(HTTPStatus.OK, _clear_github_auth())
                return

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
            github = _get_github_state()

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
                    "authenticated": bool(github.get("access_token")),
                    "auth_mode": github.get("source") if github.get("access_token") else "none",
                    "github_user": github.get("user"),
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
        "copilot_bridge listening on :%s version=%s log_level=%s auth_backend=%s oauth_client=%s auth_state_path=%s",
        PORT,
        BRIDGE_VERSION,
        LOG_LEVEL,
        _device_flow_backend(),
        bool(GITHUB_OAUTH_CLIENT_ID),
        AUTH_STATE_PATH,
    )
    try:
        server.serve_forever()
    finally:
        _unregister_zeroconf_service()


if __name__ == "__main__":
    main()
