from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error, parse, request


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
HOME_ASSISTANT_MCP_API_KEY = os.getenv("HOME_ASSISTANT_MCP_API_KEY", "").strip()
AUTH_STATE_PATH = Path(
    os.getenv("GITHUB_AUTH_STATE_PATH", "/config/copilot_bridge_github_auth.json")
)


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
    state = _default_auth_state()
    if AUTH_STATE_PATH.exists():
        try:
            loaded = json.loads(AUTH_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass

    github = state.setdefault("github", {})
    github.setdefault("access_token", None)
    github.setdefault("token_type", None)
    github.setdefault("scope", None)
    github.setdefault("source", "none")
    github.setdefault("user", None)
    github.setdefault("pending_device_flow", None)
    github.setdefault("last_error", None)
    github.setdefault("updated_at", None)

    if CONFIGURED_GITHUB_TOKEN and not github.get("access_token"):
        github["access_token"] = CONFIGURED_GITHUB_TOKEN
        github["token_type"] = "bearer"
        github["source"] = "config_token"
        github["updated_at"] = int(time.time())

    return state


AUTH_LOCK = threading.Lock()
AUTH_STATE = _load_auth_state()


def _persist_auth_state_unlocked() -> None:
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTH_STATE_PATH.write_text(json.dumps(AUTH_STATE, indent=2), encoding="utf-8")


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
    github = _get_github_state()
    pending = github.get("pending_device_flow")
    pending_public = None
    if pending:
        pending_public = {
            "user_code": pending.get("user_code"),
            "verification_uri": pending.get("verification_uri"),
            "expires_at": pending.get("expires_at"),
            "interval": pending.get("interval"),
            "scope": pending.get("scope"),
        }

    return {
        "authenticated": bool(github.get("access_token")),
        "auth_mode": github.get("source") if github.get("access_token") else "none",
        "oauth_client_configured": bool(GITHUB_OAUTH_CLIENT_ID),
        "default_scopes": GITHUB_OAUTH_SCOPES,
        "user": github.get("user"),
        "scope": github.get("scope"),
        "pending_device_flow": pending_public,
        "last_error": github.get("last_error"),
        "mcp": {
            "home_assistant": {
                "enabled_by_default": ENABLE_HOME_ASSISTANT_MCP,
                "configured": bool(HOME_ASSISTANT_MCP_URL),
                "has_api_key": bool(HOME_ASSISTANT_MCP_API_KEY),
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


def _github_post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    encoded = parse.urlencode(data).encode("utf-8")
    req = request.Request(
        url,
        data=encoded,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "ha-copilot-bridge/0.1.0",
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
            "User-Agent": "ha-copilot-bridge/0.1.0",
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


def _fetch_github_user(token: str) -> dict[str, Any]:
    user = _github_get_json("https://api.github.com/user", token)
    return {
        "login": user.get("login"),
        "id": user.get("id"),
        "name": user.get("name"),
        "html_url": user.get("html_url"),
    }


def _start_device_flow(scopes: str | None) -> dict[str, Any]:
    if not GITHUB_OAUTH_CLIENT_ID:
        raise BridgeError(
            HTTPStatus.BAD_REQUEST,
            "missing_oauth_client_id",
            "GitHub OAuth client ID is not configured on the add-on.",
        )

    requested_scopes = (scopes or GITHUB_OAUTH_SCOPES or "read:user").strip()
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
        "user_code": pending["user_code"],
        "verification_uri": pending["verification_uri"],
        "expires_at": pending["expires_at"],
        "interval": pending["interval"],
        "scope": pending["scope"],
    }


def _poll_device_flow() -> dict[str, Any]:
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
            _clear_pending_device_flow({"code": err.code, "message": err.message})
        raise BridgeError(
            HTTPStatus.BAD_GATEWAY,
            err.code,
            err.message,
        ) from err

    access_token = str(result["access_token"])
    token_type = str(result.get("token_type", "bearer"))
    scope = str(result.get("scope", "") or pending.get("scope", ""))
    user = _fetch_github_user(access_token)
    _update_github_state(
        access_token=access_token,
        token_type=token_type,
        scope=scope,
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


def _set_github_token(token: str) -> dict[str, Any]:
    token = token.strip()
    if not token:
        raise BridgeError(
            HTTPStatus.BAD_REQUEST,
            "missing_token",
            "A GitHub token is required.",
        )

    user = _fetch_github_user(token)
    _update_github_state(
        access_token=token,
        token_type="bearer",
        scope=None,
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


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "copilot-bridge/0.1.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "service": "copilot_bridge",
                    "version": "0.1.0",
                    "allowed_paths": ALLOWED_PATHS,
                    "assistant_policy": _default_assistant_policy(),
                    "github_auth": {
                        "oauth_client_configured": bool(GITHUB_OAUTH_CLIENT_ID),
                    },
                    "mcp": {
                        "home_assistant": {
                            "enabled_by_default": ENABLE_HOME_ASSISTANT_MCP,
                            "configured": bool(HOME_ASSISTANT_MCP_URL),
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
            if API_KEY and self.headers.get("X-Bridge-API-Key") != API_KEY:
                raise BridgeError(
                    HTTPStatus.UNAUTHORIZED,
                    "unauthorized",
                    "Missing or invalid bridge API key.",
                )

            if self.path == "/auth/device/start":
                payload = self._read_json()
                self._send_json(
                    HTTPStatus.OK,
                    _start_device_flow(str(payload.get("scopes", "")).strip() or None),
                )
                return

            if self.path == "/auth/device/poll":
                self._read_json()
                self._send_json(HTTPStatus.OK, _poll_device_flow())
                return

            if self.path == "/auth/token":
                payload = self._read_json()
                self._send_json(
                    HTTPStatus.OK,
                    _set_github_token(str(payload.get("token", ""))),
                )
                return

            if self.path == "/auth/logout":
                self._read_json()
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

            self._send_json(
                HTTPStatus.OK,
                {
                    "response": (
                        "Bridge scaffold is running in read-only advisor mode. "
                        "This request came through the "
                        f"{source} path"
                        + (f" in {language}" if language else "")
                        + (
                            " The bridge is configured to recommend official integrations."
                            if assistant_policy["enable_integration_discovery"]
                            else ""
                        )
                        + (
                            " It can also recommend HACS add-ons, integrations, and cards."
                            if assistant_policy["enable_hacs_discovery"]
                            else ""
                        )
                        + (
                            " It can include general Home Assistant tooling suggestions."
                            if assistant_policy["enable_tooling_discovery"]
                            else ""
                        )
                        + (
                            " with the Home Assistant MCP server enabled."
                            if home_assistant_mcp_active
                            else (
                                " Home Assistant MCP was requested but is not configured on the bridge."
                                if requested_home_assistant_mcp
                                else ""
                            )
                        )
                        + (
                            f" GitHub auth is active for {github['user']['login']}."
                            if github.get("user")
                            else (
                                " GitHub auth is configured but the user profile has not been loaded yet."
                                if github.get("access_token")
                                else " GitHub auth is not configured yet."
                            )
                        )
                        + " Filesystem modification is disabled."
                        + (
                            " Home Assistant actions are disabled."
                            if not assistant_policy["allow_home_assistant_actions"]
                            else ""
                        )
                        + " Replace this stub with a real Copilot execution pipeline."
                    ),
                    "session_id": session_id or conversation_id or "default",
                    "conversation_id": conversation_id or session_id or "default",
                    "user_id": user_id,
                    "device_id": device_id,
                    "satellite_id": satellite_id,
                    "authenticated": bool(github.get("access_token")),
                    "auth_mode": github.get("source") if github.get("access_token") else "none",
                    "github_user": github.get("user"),
                    "assistant_policy": assistant_policy,
                    "system_prompt": _build_system_prompt(assistant_policy),
                    "mcp": {
                        "home_assistant": {
                            "requested": requested_home_assistant_mcp,
                            "active": home_assistant_mcp_active,
                            "configured": bool(HOME_ASSISTANT_MCP_URL),
                            "server_name": home_assistant_mcp_server_name,
                        }
                    },
                },
            )
        except BridgeError as err:
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
            raise BridgeError(
                HTTPStatus.BAD_REQUEST,
                "invalid_json",
                "Request body must be valid JSON.",
            ) from err

        if not isinstance(payload, dict):
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
    print(f"copilot_bridge listening on :{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
