# Home Assistant Copilot Bridge

`ha-copilot-bridge` is a starter repository for a Home Assistant-native GitHub Copilot experience.

The repository is split into two main pieces:

- `addons/copilot_bridge`: a Home Assistant add-on container that hosts a local bridge API
- `custom_components/copilot_bridge`: a Home Assistant custom integration that talks to the bridge and exposes HA services

## HACS compatibility

This repo is set up so **HACS can install the custom integration** from `custom_components/copilot_bridge`.

Use it in HACS as a **custom repository** of type **Integration**:

1. Open HACS
2. Add custom repository
3. Repository: `https://github.com/amantux/ha-copilot-bridge`
4. Category: `Integration`
5. Install `Copilot Bridge`

Notes:

- HACS will install the **integration** portion of this repo
- the `addons/copilot_bridge` directory remains in the repo for manual add-on/repository work, but HACS itself is focused on the integration install path
- after installation, restart Home Assistant and add the integration through **Settings -> Devices & Services**

## Current status

This is an initial scaffold. It gives you:

- Home Assistant-friendly naming and repo layout
- a minimal add-on with health/auth/ask endpoints
- a custom integration with config flow, an `ask` service, and a Home Assistant conversation agent
- an optional workflow for including a Home Assistant MCP server in bridge requests

It does **not** yet embed a full Copilot CLI runtime, device auth flow, or TTS/STT engines. The conversation plumbing is in place so Assistant chat and voice can both target the same bridge once those pieces are added.

## Repository layout

```text
.
├── addons/
│   └── copilot_bridge/
├── custom_components/
│   └── copilot_bridge/
├── hacs.json
└── repository.yaml
```

## Planned capabilities

- GitHub authentication via device flow or PAT
- Home Assistant UI chat panel
- Assist/Conversation integration for both Assistant text chat and voice
- STT -> Copilot -> TTS voice loop
- safety controls and permission modes

## Add-on notes

The scaffolded add-on exposes a local HTTP API on port `8099`:

- `GET /health`
- `GET /auth/status`
- `POST /auth/device/start`
- `POST /auth/device/poll`
- `POST /auth/token`
- `POST /auth/logout`
- `POST /api/ask`

Right now, `POST /api/ask` returns a stubbed response so the Home Assistant integration has something stable to target while the real bridge is built out.

## Integration notes

The scaffolded integration:

- supports a config flow for `url` and optional API key
- supports an optional config flag to request Home Assistant MCP usage
- validates connectivity against `/health`
- registers `copilot_bridge.ask`
- registers GitHub auth services for device flow, token set, status, and logout
- registers a custom Home Assistant conversation agent on the config entry

## GitHub auth workflow

The scaffold now includes a bridge-managed GitHub auth flow with two supported paths:

- **device flow** using a configured GitHub OAuth app client ID
- **manual token** entry for PAT or pre-issued OAuth tokens

### Add-on configuration

The add-on now supports:

- `github_token`
- `github_oauth_client_id`
- `github_oauth_scopes`

`github_token` acts as a fallback configured token.

For device flow, set `github_oauth_client_id` to an OAuth app client ID with device flow enabled in GitHub.

### Home Assistant services

The integration now exposes:

- `copilot_bridge.get_github_auth_status`
- `copilot_bridge.start_github_device_flow`
- `copilot_bridge.poll_github_device_flow`
- `copilot_bridge.set_github_token`
- `copilot_bridge.clear_github_auth`

### Device flow sequence

1. Call `copilot_bridge.start_github_device_flow`
2. Open the returned `verification_uri`
3. Enter the returned `user_code`
4. Call `copilot_bridge.poll_github_device_flow` until it returns `authorized`

The bridge persists auth state to the Home Assistant config volume so restart-safe auth can work without storing secrets in the frontend.

## Optional Home Assistant MCP workflow

The repo now includes a basic workflow for optionally adding a **Home Assistant MCP server** into bridge requests.

The split is intentional:

- the **integration config flow** can opt requests into using Home Assistant MCP
- the **add-on config** holds the actual MCP endpoint details and secret material

This keeps endpoint credentials out of the normal Home Assistant conversation flow while still letting the integration say, "for this bridge, use the Home Assistant MCP server when available."

### Integration-side options

The config flow now supports:

- `use_home_assistant_mcp`
- `home_assistant_mcp_server_name`

These values are applied to Assistant chat, Assist voice, and service-based asks through the shared bridge client.

### Add-on-side options

The add-on now supports:

- `enable_home_assistant_mcp`
- `home_assistant_mcp_url`
- `home_assistant_mcp_api_key`

If the integration requests Home Assistant MCP but the add-on has not been configured with an MCP endpoint, the bridge surfaces that mismatch in the stub response and status payload.

## Assistant chat and voice support

The current scaffold is built so **both** of these go through the same bridge API:

- **Assistant text / IM chat** in Home Assistant
- **Voice** through Assist after Home Assistant speech-to-text converts speech into text

The integration registers a Home Assistant conversation agent, which means:

- Home Assistant Assistant chat can send messages to the bridge
- Assist voice requests can hit the same agent after STT
- both modes share conversation IDs and session continuity
- both modes can optionally request Home Assistant MCP through the same bridge client

In practice, the flow is:

`microphone -> STT -> Home Assistant conversation agent -> copilot bridge -> response text -> Assistant UI and optional TTS`

and for chat:

`Assistant text chat -> Home Assistant conversation agent -> copilot bridge -> response text`

## Next recommended steps

1. Replace the stub bridge response with a real Copilot execution service.
2. Add frontend UI for the GitHub device login workflow.
3. Replace the MCP stub signaling with a real MCP client/session manager in the bridge.
4. Add a Lovelace chat card or panel.
5. Add optional TTS output for spoken replies.

