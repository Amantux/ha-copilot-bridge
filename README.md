# Home Assistant Copilot Bridge

`ha-copilot-bridge` is a Home Assistant-focused scaffold that connects a custom integration to a local add-on bridge for Copilot-style assistant workflows.

Its primary goal is to let a GitHub Copilot-backed assistant use Home Assistant MCP context during problem-solving.

It is designed around:

- Assistant chat and Assist voice entry points
- a Home Assistant custom integration installed through HACS
- a local Home Assistant add-on that owns auth and bridge runtime concerns
- optional Home Assistant MCP usage
- MCP-aware prompt plumbing between the integration and bridge
- a read-only advisor posture for integration, HACS, and tooling recommendations

GitHub sign-in is designed to prefer a browser/device-code style flow through the bridge so Home Assistant can show a code, let you approve access in the browser, and then continue setup.

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
4. Add the integration from **Settings -> Devices & Services** (or use the auto-discovered prompt when the bridge is announced via zeroconf).

For the add-on:

1. Add `https://github.com/amantux/ha-copilot-bridge` as a custom add-on repository.
2. Install **Copilot Bridge** from the Add-on Store.
3. Start the add-on.
4. Prefer the discovered add-on flow in Home Assistant when it appears; otherwise configure the integration with the actual stable bridge URL reachable from Home Assistant.

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

Use a stable hostname or Docker service name for that URL so container replacement or image updates do not change what the integration connects to.

### Container + integration auth workflow (recommended)

If your goal is to run the bridge as a container and connect it from Home Assistant:

1. Start the container with a persistent volume (`-v copilot-bridge-data:/data`) and set:
   - `GITHUB_AUTH_STATE_PATH=/data/github-auth.json`
   - `GITHUB_OAUTH_SCOPES=read:user`
2. In Home Assistant, add the **Copilot Bridge** integration and set the container URL (for example `http://copilot-bridge:8099` on a shared Docker network).
3. In the integration flow, choose **Sign in with GitHub in the browser**.
4. Open the shown verification URL, enter the code, approve access, then submit the flow again to poll for completion.
5. After setup, open integration options any time to rotate credentials, clear auth, or re-run sign-in.

This flow does not require a static GitHub token. A static token (`GITHUB_TOKEN`) is still supported when you prefer operator-managed credentials.

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
