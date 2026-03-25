# Integration and API reference

## Home Assistant services

The integration currently exposes:

- `copilot_bridge.ask`
- `copilot_bridge.get_github_auth_status`
- `copilot_bridge.start_github_device_flow`
- `copilot_bridge.poll_github_device_flow`
- `copilot_bridge.set_github_token`
- `copilot_bridge.clear_github_auth`

## `copilot_bridge.ask`

Send a prompt to the bridge.

Supported fields:

- `prompt`
- `session_id`
- `entry_id`
- `user_id`
- `use_home_assistant_mcp`

## Integration setup flow

The setup now explicitly tests the bridge connection after the initial connection settings step.

That bridge test step surfaces a few basic details from `/health`, including:

- bridge service name
- bridge version
- whether the add-on GitHub OAuth client is configured
- whether Home Assistant MCP is configured on the bridge

## Integration setup auth selection

During integration configuration, the user now reaches a dedicated GitHub configuration step after the initial bridge connection step. In that GitHub step, the user can choose:

- `addon_config`
- `device_flow`
- `manual_token`
- `none`

That selected method is stored with the integration entry.

The setup flow now also:

- inspects current bridge auth state
- can reuse an existing authenticated GitHub session
- blocks device flow when the add-on OAuth client is not configured
- resumes an already pending device flow when possible
- presents GitHub setup as an explicit guided action choice instead of a mixed settings form

## Bridge API

The scaffolded add-on currently exposes:

- `GET /health`
- `GET /auth/status`
- `POST /auth/device/start`
- `POST /auth/device/poll`
- `POST /auth/token`
- `POST /auth/logout`
- `POST /api/ask`

## `/api/ask` behavior

`POST /api/ask` is still stubbed.

It currently returns enough structure to validate Home Assistant-side plumbing before a real runtime is added. The stub response includes:

- assistant response text
- session and conversation identifiers
- auth summary
- MCP summary
- `assistant_policy`
- `system_prompt`

For Home Assistant MCP status, the bridge now reports auth metadata in redacted form only:

- whether MCP is configured
- whether the configured URL looks like a secret `/private_...` URL
- whether a bearer token is configured
- which auth mode is being inferred

It does not return the secret URL or token value.

## Assistant behavior notes

Assistant text and voice go through the same bridge path.

This means:

- shared conversation continuity
- shared policy handling
- shared optional MCP request behavior

## Development notes

The repository is meant to grow in layers:

1. stable Home Assistant integration surface
2. stable bridge auth/config surface
3. real Copilot runtime integration
4. richer UI and voice reply capabilities
5. full MCP tooling and action controls

## Recommended next steps

High-value follow-up work:

1. Replace the stub `/api/ask` implementation with real Copilot execution.
2. Add a frontend UI for GitHub device login status and completion.
3. Add a Lovelace chat card or dashboard panel.
4. Add optional TTS output.
5. Implement a real Home Assistant MCP client/session layer in the bridge.
