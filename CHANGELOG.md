# Changelog

## [0.1.14] - 2026-03-27

### Changed
- Bumped bridge runtime, add-on, and integration version metadata to `0.1.14`.

## [0.1.13] - 2026-03-27

### Added
- Added an explicit `copilot_bridge` Home Assistant Supervisor discovery identifier to the integration manifest so discovery can surface through the Integrations **Discovered** flow.

### Changed
- Bumped integration and add-on version metadata to `0.1.13`.

## [0.1.12] - 2026-03-27
- Simplify GitHub auth flow to focus on OAuth device flow and token-based auth.
- Fix Home Assistant Supervisor discovery mapping by aligning the integration `hassio` slug with the add-on slug.
- Add repository consistency tests for add-on discovery slug wiring and mirrored runtime server files.

## [0.1.8] - 2026-03-25
- Accept the “Authenticate Git with your GitHub credentials?” prompt with `Y` and track when it was answered.
- Fall back to sending Enter for the “Login with a web browser” prompt after the Git prompt completes so the device-code flow keeps moving.
