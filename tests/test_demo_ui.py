"""Demo-mode UI: login invitation, OAuth help message and the fixed DEMO DATA banner."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import server

ROOT = Path(server.__file__).resolve().parent
NODE = shutil.which("node")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def ui_state(status):
    src = read("frontend/js/core_and_auth.js")
    m = re.search(r"// JT-AUTH-UI-STATE-BEGIN.*?\n(.*?)// JT-AUTH-UI-STATE-END", src, re.S)
    assert m, "jtAuthUiState markers missing"
    js = (
        "const f = new Function(process.argv[2] + '; return jtAuthUiState;')();"
        "console.log(JSON.stringify(f(JSON.parse(process.argv[1]))));"
    )
    res = subprocess.run(  # noqa: S603
        [NODE, "-e", js, json.dumps(status), m.group(1)], capture_output=True, text=True, check=True,
    )
    return json.loads(res.stdout.strip().splitlines()[-1])


class TestDemoMarkup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read("frontend/html/shell_and_views.html")

    def test_ids_present(self):
        for i in ("demo-banner", "btn-demo-enter", "login-demo-invite", "login-google-wrap", "login-oauth-help"):
            self.assertIn(f'id="{i}"', self.html)

    def test_texts(self):
        for t in (
            "Explore the demo",
            "Demo data only. Configure your Google OAuth client to use your own data.",
            "DEMO DATA — fictional company, no connection to Google Cloud",
            "Google OAuth client not configured. Set GCP_OAUTH_CLIENT_ID and GCP_OAUTH_CLIENT_SECRET in .env",
        ):
            self.assertIn(t, self.html)

    def test_banner_and_help_hidden_by_default(self):
        for i in ("demo-banner", "login-demo-invite", "login-oauth-help"):
            tag = re.search(rf'<div[^>]*id="{i}"[^>]*>', self.html).group(0)
            self.assertRegex(tag, r'class="[^"]*\bhidden\b')

    def test_readme_link_is_safe(self):
        links = re.findall(r"<a [^>]*janus-tower#readme[^>]*>", self.html)
        self.assertTrue(links)
        for a in links:
            self.assertIn('target="_blank"', a)
            self.assertIn('rel="noopener noreferrer"', a)

    def test_env_names_match_config(self):
        cfg = read("backend/config.py")
        self.assertIn("GCP_OAUTH_CLIENT_ID", cfg)
        self.assertIn("GCP_OAUTH_CLIENT_SECRET", cfg)

    def test_enter_demo_action_registered(self):
        self.assertIn('data-jt-click="enterDemo()"', self.html)
        self.assertIn("'enterDemo'", read("frontend/js/ui_actions.js"))
        self.assertRegex(read("frontend/js/core_and_auth.js"), r"async function enterDemo\(")

    def test_banner_css(self):
        self.assertIn(".jt-demo-banner", read("Design/jt-theme.css"))


@unittest.skipUnless(NODE, "node not available")
class TestAuthUiState(unittest.TestCase):
    def test_demo_on(self):
        for oauth in (True, False):
            s = ui_state({"demo": True, "oauthConfigured": oauth, "needsLogin": False})
            self.assertTrue(s["showDemoBanner"])
            self.assertTrue(s["showDemoInvite"])
            self.assertFalse(s["showGoogleButton"])
            self.assertFalse(s["showOauthHelp"])

    def test_demo_off_oauth_configured(self):
        s = ui_state({"demo": False, "oauthConfigured": True, "needsLogin": True})
        self.assertEqual(
            s, {"showDemoBanner": False, "showDemoInvite": False, "showGoogleButton": True, "showOauthHelp": False},
        )

    def test_demo_off_oauth_missing(self):
        s = ui_state({"demo": False, "oauthConfigured": False, "needsLogin": True})
        self.assertEqual(
            s, {"showDemoBanner": False, "showDemoInvite": False, "showGoogleButton": False, "showOauthHelp": True},
        )

    def test_old_backend_without_flags(self):
        s = ui_state({})
        self.assertFalse(s["showDemoBanner"])
        self.assertTrue(s["showGoogleButton"])
        self.assertFalse(s["showOauthHelp"])


if __name__ == "__main__":
    unittest.main()
