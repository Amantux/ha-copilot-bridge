# Home Assistant Copilot Bridge

`ha-copilot-bridge` is a Home Assistant-focused scaffold that connects a custom integration to a local add-on bridge for Copilot-style assistant workflows.

It is designed around:

- Assistant chat and Assist voice entry points
- a Home Assistant custom integration installed through HACS
- a local Home Assistant add-on that owns auth and bridge runtime concerns
- optional Home Assistant MCP usage
- a read-only advisor posture for integration, HACS, and tooling recommendations

## Current state

This repository is a strong foundation, not a finished runtime.

Implemented today:

- HACS-compatible custom integration layout
- Home Assistant conversation-agent wiring
- shared path for Assistant text and voice requests
- GitHub auth plumbing in the bridge
- optional MCP request/config plumbing
- internal-only add-on networking
- read-only advisor policy defaults

Still pending:

- real Copilot execution behind `/api/ask`
- polished Lovelace or dashboard chat UI
- richer GitHub auth UX in Home Assistant
- full MCP client/session handling in the bridge

## Repository layout

```text
.
├── addons/
│   └── copilot_bridge/
├── copilot_bridge/
├── custom_components/
│   └── copilot_bridge/
├── docs/
├── hacs.json
└── repository.yaml
```

## Quick start

For the integration:

1. Add `https://github.com/amantux/ha-copilot-bridge` to HACS as an **Integration** repository.
2. Install `Copilot Bridge`.
3. Restart Home Assistant.
4. Add the integration from **Settings -> Devices & Services**.

For the add-on:

1. Add `https://github.com/amantux/ha-copilot-bridge` as a custom add-on repository.
2. Install **Copilot Bridge** from the Add-on Store.
3. Start the add-on.
4. Keep the integration pointed at `http://home-assistant-copilot-bridge:8099`.

For a standalone container:

```bash
docker run --name copilot-bridge \
  -p 8099:8099 \
  -e BRIDGE_API_KEY=change-me \
  -e GITHUB_OAUTH_CLIENT_ID=your_github_oauth_app_client_id \
  -e GITHUB_OAUTH_SCOPES=read:user \
  -e GITHUB_AUTH_STATE_PATH=/data/github-auth.json \
  -v copilot-bridge-data:/data \
  your-built-image-tag
```

Then point the Home Assistant integration at that bridge URL and complete GitHub setup through the integration flow or the exposed auth endpoints.

## Documentation

Detailed documentation now lives under `docs/`:

- [Documentation index](docs/README.md)
- [Architecture](docs/architecture.md)
- [Installation](docs/installation.md)
- [Configuration and auth](docs/configuration.md)
- [Integration and API reference](docs/reference.md)

## Add-on note

The repository includes both:

- `copilot_bridge/` for Home Assistant add-on repository discovery
- `addons/copilot_bridge/` as the development copy of the same add-on scaffold

## Disclaimer

This project currently contains scaffolded integration and bridge plumbing, not a production-ready Copilot runtime.
