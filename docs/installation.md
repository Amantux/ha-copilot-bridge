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

## Installation order

Recommended sequence:

1. Install the add-on.
2. Start and configure the add-on.
3. Install the integration through HACS.
4. Add the integration in Home Assistant.
5. Configure GitHub auth and optional MCP settings.
