# Copilot Bridge Add-on

This folder is the **Home Assistant add-on repository entry** for Copilot Bridge.

It exists at the repository root so Home Assistant can discover it when you add:

`https://github.com/amantux/ha-copilot-bridge`

as a custom add-on repository in the Add-ons area.

## What this add-on does

The add-on runs a local bridge service that:

- exposes a local API on port `8099`
- stores GitHub auth state on the HA config volume
- supports GitHub device flow and manual token auth
- accepts prompt requests from the Home Assistant integration
- defaults to a read-only advisor profile for Home Assistant guidance
- optionally carries Home Assistant MCP configuration
- is intended to be reached over Home Assistant internal networking and ingress, not a LAN-exposed host port

## Basic add-on setup

Configure these fields as needed:

- `bridge_api_key`
- `github_token`
- `github_oauth_client_id`
- `github_oauth_scopes`
- `assistant_profile`
- `read_only_mode`
- `allow_home_assistant_actions`
- `allow_filesystem_access`
- `enable_integration_discovery`
- `enable_hacs_discovery`
- `enable_tooling_discovery`
- `enable_home_assistant_mcp`
- `home_assistant_mcp_url`
- `home_assistant_mcp_api_key`

## Typical install flow

1. Add this repo as a custom repository in **Settings -> Add-ons -> Add-on Store -> Repositories**
2. Install **Copilot Bridge**
3. Start the add-on
4. Optionally configure GitHub auth settings in the add-on options
5. Install the `Copilot Bridge` integration through HACS
6. Add the integration in **Settings -> Devices & Services**

## Networking

This add-on is configured for **internal-only access**:

- no published host port
- Home Assistant **Ingress** is enabled
- the integration is expected to use the internal hostname `copilot-bridge`

That keeps the bridge reachable from the Home Assistant server environment while avoiding direct network exposure to other devices on your LAN.

## Notes

The bridge is currently scaffolded: auth and request plumbing are present, but the final Copilot runtime execution layer is still to be implemented.

The default posture is intentionally read-only:

- filesystem access is disabled
- Home Assistant action execution is disabled in read-only mode
- recommendation scope is aimed at official integrations, HACS content, and general HA tooling

