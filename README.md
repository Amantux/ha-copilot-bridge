# Home Assistant Copilot Bridge

`ha-copilot-bridge` is a Home Assistant-focused project that connects a local Home Assistant integration to a containerized bridge service for GitHub/Copilot-style workflows.

The goal is to make a Copilot-like assistant available inside Home Assistant through:

- Assistant chat / text prompts
- Assist voice workflows after speech-to-text
- service calls and future dashboard UI
- optional Home Assistant MCP integration

This repository currently provides a solid scaffold for that architecture: installable custom integration metadata, a Home Assistant add-on skeleton, conversation-agent wiring, and a bridge-managed GitHub auth flow.

## What this project includes

### Custom integration

The integration lives in `custom_components/copilot_bridge` and is designed to be installed through HACS.

It currently provides:

- a config flow
- a Home Assistant conversation agent
- service registration for prompts and auth actions
- support for Assistant text chat and Assist voice ingress
- optional request-level Home Assistant MCP enablement

### Add-on bridge

The add-on lives in `addons/copilot_bridge`.

It currently provides:

- a lightweight local HTTP API on port `8099`
- GitHub auth state management
- GitHub device flow support
- manual token validation and storage
- stubbed `/api/ask` behavior for end-to-end wiring
- optional Home Assistant MCP configuration fields

## Current status

This is still a **scaffold / foundation repo**, not a finished assistant product.

What is implemented:

- HACS-compatible custom integration layout
- Home Assistant conversation-agent registration
- one shared path for Assistant chat and voice requests
- bridge-side GitHub auth workflow
- optional Home Assistant MCP request signaling

What is not implemented yet:

- real Copilot CLI execution inside the bridge
- a polished Lovelace chat card or panel
- full TTS reply pipeline
- a real MCP client/session manager in the bridge
- full UX for in-app GitHub device login

## Architecture

The repo intentionally uses a split architecture:

1. **Home Assistant custom integration**
   - owns config flow, services, and conversation-agent wiring
   - plugs into Assistant text and voice flows

2. **Home Assistant add-on**
   - runs the local bridge service
   - stores secrets and auth state on the HA config volume
   - becomes the boundary between HA and GitHub/MCP/Copilot execution

This keeps sensitive config and token handling out of frontend/UI state.

## Repository layout

```text
.
├── addons/
│   └── copilot_bridge/
│       ├── config.yaml
│       ├── build.yaml
│       ├── Dockerfile
│       └── rootfs/
├── custom_components/
│   └── copilot_bridge/
│       ├── __init__.py
│       ├── api.py
│       ├── config_flow.py
│       ├── conversation_agent.py
│       ├── manifest.json
│       ├── services.yaml
│       ├── strings.json
│       └── translations/
├── hacs.json
└── repository.yaml
```

## HACS installation

This repository is configured so HACS can install the **custom integration**.

Add it to HACS as a **custom repository** of type **Integration**:

1. Open HACS
2. Add custom repository
3. Use `https://github.com/amantux/ha-copilot-bridge`
4. Select category `Integration`
5. Install `Copilot Bridge`
6. Restart Home Assistant
7. Add the integration from **Settings -> Devices & Services**

### Important note

HACS installs the integration from `custom_components/copilot_bridge`.

The add-on directory remains in the same repository for manual add-on/repository use, but HACS itself is not installing the add-on as part of the integration flow.

## Home Assistant add-on configuration

The scaffolded add-on exposes the following options:

```yaml
bridge_api_key: ""
github_token: ""
github_oauth_client_id: ""
github_oauth_scopes: "read:user"
enable_home_assistant_mcp: false
home_assistant_mcp_url: ""
home_assistant_mcp_api_key: ""
allowed_paths: "/config"
log_level: "info"
```

### Add-on option notes

- `bridge_api_key`: optional shared secret between HA and the bridge
- `github_token`: fallback GitHub token if you want static token auth
- `github_oauth_client_id`: required for GitHub device flow
- `github_oauth_scopes`: default scopes requested during device flow
- `enable_home_assistant_mcp`: enables HA MCP by default for bridge requests
- `home_assistant_mcp_url`: MCP endpoint for Home Assistant
- `home_assistant_mcp_api_key`: optional secret for the MCP endpoint
- `allowed_paths`: future allowlist for local bridge execution scope

## Bridge API

The scaffolded add-on currently exposes:

- `GET /health`
- `GET /auth/status`
- `POST /auth/device/start`
- `POST /auth/device/poll`
- `POST /auth/token`
- `POST /auth/logout`
- `POST /api/ask`

### API behavior today

`POST /api/ask` is still stubbed. It returns a structured response so Home Assistant-side plumbing can be tested before real Copilot execution is integrated.

## Home Assistant services

The integration currently exposes these services:

- `copilot_bridge.ask`
- `copilot_bridge.get_github_auth_status`
- `copilot_bridge.start_github_device_flow`
- `copilot_bridge.poll_github_device_flow`
- `copilot_bridge.set_github_token`
- `copilot_bridge.clear_github_auth`

### `copilot_bridge.ask`

Send a prompt to the bridge.

Supported fields:

- `prompt`
- `session_id`
- `entry_id`
- `user_id`
- `use_home_assistant_mcp`

### GitHub auth services

Use these to manage auth from Home Assistant:

- `copilot_bridge.get_github_auth_status`
- `copilot_bridge.start_github_device_flow`
- `copilot_bridge.poll_github_device_flow`
- `copilot_bridge.set_github_token`
- `copilot_bridge.clear_github_auth`

## GitHub authentication workflow

The project currently supports two auth paths:

### Option 1: Device flow

Best when you want a browser-assisted login from a headless/local device.

Requirements:

- configure `github_oauth_client_id` in the add-on
- ensure device flow is enabled for that GitHub OAuth app

Sequence:

1. Call `copilot_bridge.start_github_device_flow`
2. Open the returned `verification_uri`
3. Enter the returned `user_code`
4. Call `copilot_bridge.poll_github_device_flow` until it returns `authorized`

### Option 2: Manual token

Best when you already have a PAT or other GitHub token.

Sequence:

1. Call `copilot_bridge.set_github_token`
2. The bridge validates it against `https://api.github.com/user`
3. If valid, the token is stored in the bridge auth state

### Persistence

The bridge stores auth state on the Home Assistant config volume so it can survive restarts without depending on frontend-only state.

## Assistant chat and voice support

The integration is wired so both text and voice go through the same path.

### Text path

`Assistant chat -> Home Assistant conversation agent -> copilot bridge -> response text`

### Voice path

`microphone -> STT -> Home Assistant conversation agent -> copilot bridge -> response text -> Assistant UI and optional TTS`

This means:

- Assistant text and voice share conversation continuity
- both use the same bridge client
- both can optionally request Home Assistant MCP usage

## Optional Home Assistant MCP workflow

This repository includes an optional workflow for using a Home Assistant MCP server.

The split is intentional:

- the **integration** decides whether to request MCP for a given bridge/request
- the **add-on** stores the MCP endpoint and any secret material

This keeps credentials and endpoint configuration on the bridge side while still letting the Home Assistant integration opt into MCP-aware requests.

### Integration-side MCP options

The config flow currently supports:

- `use_home_assistant_mcp`
- `home_assistant_mcp_server_name`

These values flow through Assistant chat, voice, and service-based prompt calls.

### Add-on-side MCP options

The add-on currently supports:

- `enable_home_assistant_mcp`
- `home_assistant_mcp_url`
- `home_assistant_mcp_api_key`

If MCP is requested but not configured in the add-on, the stub response reports that mismatch clearly.

## Development notes

This repo is designed to grow in layers:

1. stable HA integration surface
2. stable bridge auth/config surface
3. real Copilot runtime integration
4. richer UI and voice reply capabilities
5. full MCP tooling and action controls

## Recommended next steps

If you’re continuing development, the highest-value next tasks are:

1. Replace the stub `/api/ask` implementation with real Copilot execution
2. Add a frontend UI for GitHub device login status and completion
3. Add a Lovelace chat card or dashboard panel
4. Add optional TTS output
5. Implement a real Home Assistant MCP client/session layer in the bridge

## Disclaimer

This project currently contains **scaffolded integration and auth plumbing**, not a complete production-ready Copilot runtime. Treat it as a strong starting point for a Home Assistant-native assistant bridge.
