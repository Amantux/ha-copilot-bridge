from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class RepoConsistencyTests(unittest.TestCase):
    def test_manifest_hassio_slug_matches_addon_slug(self) -> None:
        manifest = json.loads(
            (REPO_ROOT / "custom_components/copilot_bridge/manifest.json").read_text()
        )
        hassio_slugs = manifest.get("hassio") or []
        self.assertTrue(hassio_slugs, "manifest hassio list should not be empty")

        addon_config = (REPO_ROOT / "copilot_bridge/config.yaml").read_text()
        slug_match = re.search(r'^\s*slug:\s*"([^"]+)"\s*$', addon_config, re.MULTILINE)
        self.assertIsNotNone(slug_match, "addon config slug must be defined")
        addon_slug = slug_match.group(1)

        self.assertIn(
            addon_slug,
            hassio_slugs,
            "integration manifest hassio slug must include add-on slug",
        )

    def test_server_files_are_kept_in_sync(self) -> None:
        primary = (REPO_ROOT / "copilot_bridge/rootfs/app/server.py").read_text()
        addon_copy = (REPO_ROOT / "addons/copilot_bridge/rootfs/app/server.py").read_text()
        self.assertEqual(
            primary,
            addon_copy,
            "server runtime files drifted; keep both copies identical",
        )

    def test_gh_auth_login_variants_exist(self) -> None:
        server = (REPO_ROOT / "copilot_bridge/rootfs/app/server.py").read_text()
        self.assertIn("def _gh_auth_login_command_variants", server)
        self.assertIn('"--git-protocol"', server)
        self.assertIn('"https"', server)
        self.assertIn("fallback", server)


if __name__ == "__main__":
    unittest.main()
