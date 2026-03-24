# Architecture

## Overview

`ha-copilot-bridge` uses a split Home Assistant architecture:

1. A custom integration under `custom_components/copilot_bridge`
2. A Home Assistant add-on exposed from `copilot_bridge/`
3. A local bridge API that sits between Home Assistant and future Copilot/MCP runtime behavior

This keeps Home Assistant-specific UX and service wiring separate from bridge runtime, auth, and secret handling.

## Major components

### Custom integration

The integration is responsible for:

- config flow and setup flow
- Home Assistant service registration
- Home Assistant conversation-agent registration
- Assistant text and voice request forwarding
- request-level policy and MCP signaling

### Add-on bridge

The add-on is responsible for:

- local HTTP bridge runtime on port `8099`
- GitHub auth state management
- device flow and manual token handling
- default advisor policy behavior
- optional Home Assistant MCP bridge configuration

## Assistant request flow

### Text path

`Assistant chat -> Home Assistant conversation agent -> bridge -> response text`

### Voice path

`microphone -> STT -> Home Assistant conversation agent -> bridge -> response text -> Assistant UI and optional TTS`

Both paths share the same bridge client and can carry optional MCP request context.

## Security posture

The current default posture is intentionally conservative:

- internal-only bridge access
- no exposed LAN port
- read-only advisor mode by default
- filesystem access disabled
- Home Assistant actions disabled in read-only mode

## Internal networking

The integration defaults to:

`http://home-assistant-copilot-bridge:8099`

That hostname comes from the add-on slug and is intended for Home Assistant internal networking rather than direct network exposure.

## Current implementation status

Implemented:

- HACS integration scaffold
- add-on repository scaffold
- conversation-agent wiring
- GitHub auth plumbing
- MCP request/config plumbing
- advisor policy propagation

Not yet implemented:

- real Copilot backend execution
- production-grade streaming/runtime layer
- full Home Assistant chat panel
- full TTS pipeline
- real MCP client/session management
