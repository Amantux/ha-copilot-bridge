# Changelog

## [0.1.12] - 2026-03-27
- Make GitHub CLI auth startup more resilient by retrying with a fallback `gh auth login` command when argument parsing fails.
- Fix Home Assistant Supervisor discovery mapping by aligning the integration `hassio` slug with the add-on slug.
- Add repository consistency tests for add-on discovery slug wiring and mirrored runtime server files.

## [0.1.8] - 2026-03-25
- Accept the “Authenticate Git with your GitHub credentials?” prompt with `Y` and track when it was answered.
- Fall back to sending Enter for the “Login with a web browser” prompt after the Git prompt completes so the device-code flow keeps moving.
