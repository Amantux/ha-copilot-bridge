# Installation

## HACS installation

This repository is configured so HACS can install the custom integration from:

`custom_components/copilot_bridge`

Steps:

1. Open HACS.
2. Add a custom repository.
3. Use `https://github.com/amantux/ha-copilot-bridge`.
4. Select category `Integration`.
5. Install `Copilot Bridge`.
6. Restart Home Assistant.
7. Add the integration from **Settings -> Devices & Services**.

## Add-on Store installation

This repository also exposes a root-level add-on entry at:

`copilot_bridge/`

Steps:

1. Open **Settings -> Add-ons**.
2. Open the **Add-on Store**.
3. Open **Repositories**.
4. Add `https://github.com/amantux/ha-copilot-bridge`.
5. Refresh if needed.
6. Install **Copilot Bridge**.
7. Start the add-on.

## Networking behavior

The add-on is configured for internal-only access:

- no published host port
- Home Assistant Ingress enabled
- integration traffic sent to `http://home-assistant-copilot-bridge:8099`

That means the bridge is intended to be reachable from the Home Assistant host/container environment, not directly from other devices on your LAN.

## Standalone container installation

The bridge can also run as a plain container outside the Home Assistant add-on system.

Example:

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

Notes:

- publish port `8099` only if Home Assistant needs to reach the container over your Docker network or host
- mount a persistent volume and point `GITHUB_AUTH_STATE_PATH` into it so device-flow and pasted-token auth survive restarts
- if you prefer a static token, set `GITHUB_TOKEN` instead of using device flow
- if Home Assistant runs in Docker too, use a shared Docker network and configure the integration with the container hostname instead of `localhost`

## Installation order

Recommended sequence:

1. Install the add-on.
2. Start and configure the add-on.
3. Install the integration through HACS.
4. Add the integration in Home Assistant and use the bridge connection test step to verify the local bridge responds.
5. Complete the dedicated GitHub auth step.
6. Complete the separate MCP configuration step if you want MCP enabled.
