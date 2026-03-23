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
- optionally carries Home Assistant MCP configuration

## Basic add-on setup

Configure these fields as needed:

- `bridge_api_key`
- `github_token`
- `github_oauth_client_id`
- `github_oauth_scopes`
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

## Notes

The bridge is currently scaffolded: auth and request plumbing are present, but the final Copilot runtime execution layer is still to be implemented.

