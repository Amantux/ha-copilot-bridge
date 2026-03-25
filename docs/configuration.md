# Configuration and auth

## Add-on options

The scaffolded add-on currently exposes:

```yaml
bridge_api_key: ""
github_token: ""
github_oauth_client_id: ""
github_oauth_scopes: "read:user"
assistant_profile: "home_assistant_read_only_advisor"
read_only_mode: true
allow_home_assistant_actions: false
allow_filesystem_access: false
enable_integration_discovery: true
enable_hacs_discovery: true
enable_tooling_discovery: true
enable_home_assistant_mcp: false
home_assistant_mcp_url: ""
home_assistant_mcp_bearer_token: ""
home_assistant_mcp_api_key: ""
allowed_paths: "/config"
log_level: "info"
```

## Option notes

- `bridge_api_key`: optional shared secret between Home Assistant and the bridge
- `github_token`: optional static GitHub token
- `github_oauth_client_id`: required for GitHub device flow
- `github_oauth_scopes`: default scopes requested during device flow
- `assistant_profile`: assistant profile identifier used by the bridge
- `read_only_mode`: keeps the bridge in advisor mode
- `allow_home_assistant_actions`: currently forced off when read-only mode is on
- `allow_filesystem_access`: forced off in the current design
- `enable_integration_discovery`: allow recommendations for official Home Assistant integrations
- `enable_hacs_discovery`: allow recommendations for HACS integrations, cards, and add-ons
- `enable_tooling_discovery`: allow recommendations for Home Assistant tooling and operational guidance
- `enable_home_assistant_mcp`: enable MCP by default for bridge requests
- `home_assistant_mcp_url`: MCP endpoint URL; for the Home Assistant MCP add-on this should usually be the full secret URL including the `/private_...` path
- `home_assistant_mcp_bearer_token`: optional bearer token for non-add-on or custom MCP deployments that require an Authorization header
- `home_assistant_mcp_api_key`: legacy compatibility field; retained as a fallback alias for older bridge configs
- `allowed_paths`: reserved future allowlist for local execution scope

## Read-only advisor mode

The current bridge behavior is intentionally focused on:

- understanding user intent
- recommending official integrations
- recommending HACS content
- suggesting Home Assistant tooling and setup approaches

It is intentionally not focused on:

- modifying the host filesystem
- running host commands
- claiming actions were completed without verification

## GitHub authentication workflow

The project currently supports two auth paths.

Inside the Home Assistant integration, GitHub configuration is now handled as its own config-flow step after the bridge connection step. That keeps bridge connectivity separate from GitHub auth selection.

The integration also checks current bridge auth state during setup so it can guide setup more like an initialization flow. It can:

- show whether the bridge is already authenticated
- show whether the add-on OAuth client is configured for device flow
- reuse an existing bridge GitHub session when appropriate
- resume a pending device flow instead of starting a duplicate one

### Device flow

Best when you want a browser-assisted login from a headless or appliance-style Home Assistant install.

Requirements:

- configure `github_oauth_client_id` in the add-on
- ensure device flow is enabled for that GitHub OAuth app

Typical flow:

1. Call `copilot_bridge.start_github_device_flow`.
2. Open the returned `verification_uri`.
3. Enter the returned `user_code`.
4. Call `copilot_bridge.poll_github_device_flow` until authorization completes.

### Manual token

Best when you already have a GitHub token available.

Typical flow:

1. Call `copilot_bridge.set_github_token`.
2. The bridge validates the token against `https://api.github.com/user`.
3. If valid, the token is stored in persisted bridge auth state.

### Persistence

The bridge stores auth state on the Home Assistant config volume so it survives add-on restarts.

### Standalone container auth

For a standalone container deployment, the same bridge auth workflow is available through environment variables and the bridge auth endpoints.

Recommended environment variables:

- `BRIDGE_API_KEY`: optional shared secret for the integration
- `GITHUB_TOKEN`: static GitHub token to use at startup
- `GITHUB_OAUTH_CLIENT_ID`: enables GitHub device flow without requiring a client secret
- `GITHUB_OAUTH_SCOPES`: default requested scopes for device flow
- `GITHUB_AUTH_STATE_PATH`: file path where device-flow or pasted-token auth state is persisted

Container recommendations:

- mount a persistent volume and place `GITHUB_AUTH_STATE_PATH` inside it
- use `GITHUB_TOKEN` when you want immutable operator-managed credentials
- use `GITHUB_OAUTH_CLIENT_ID` plus `GITHUB_AUTH_STATE_PATH` when you want browser-assisted login from the Home Assistant integration

Startup precedence:

- if `GITHUB_TOKEN` is set, the bridge now treats that configured token as the active auth source on startup
- if `GITHUB_TOKEN` is not set, the bridge falls back to persisted auth state from `GITHUB_AUTH_STATE_PATH`

The bridge now exposes redacted auth-storage metadata in `/health` and `/auth/status` so you can confirm:

- whether a configured GitHub token is present
- whether device flow can start
- where auth state is expected to persist
- whether the auth-state file already exists
- whether persisted auth failed to load

## MCP configuration split

The MCP configuration split is intentional:

- the integration decides whether to request MCP for a prompt
- the add-on stores MCP endpoint details and secret material

This keeps secret configuration on the bridge side while still allowing the integration to opt into MCP-aware behavior.

### Home Assistant MCP add-on compatibility

The official Home Assistant MCP add-on is documented as:

- using a full secret MCP URL shown in the add-on logs
- relying on Home Assistant-side authentication automatically
- typically not requiring a separate token field when you use that secret URL

For that setup, configure:

- `home_assistant_mcp_url` with the full URL from the HA MCP add-on logs, including the `/private_...` path
- leave `home_assistant_mcp_bearer_token` empty

Only use `home_assistant_mcp_bearer_token` for custom or non-standard MCP deployments that explicitly require bearer-token auth.
