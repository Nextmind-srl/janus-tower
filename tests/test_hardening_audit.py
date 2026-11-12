"""Hardening da un'analisi esterna: azioni CI fissate a SHA, cooldown Dependabot, button con type, timeout delle fetch,
intestazioni HTTP, niente globals() (nessun dato reale)."""

import glob
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class TestHardening(unittest.TestCase):
    def test_azioni_github_fissate_a_sha(self):
        for line in read(".github/workflows/ci.yml").splitlines():
            m = re.search(r"uses:\s*([^\s#]+)", line)
            if m and not m.group(1).startswith("./"):
                self.assertRegex(m.group(1), r"@[0-9a-f]{40}$", line)

    def test_dependabot_ha_il_cooldown_per_ogni_ecosistema(self):
        txt = read(".github/dependabot.yml")
        self.assertEqual(txt.count("package-ecosystem"), txt.count("cooldown:"))

    def test_dependabot_copre_npm(self):
        self.assertIn("package-ecosystem: npm", read(".github/dependabot.yml"))

    def test_jt_theme_senza_selettori_di_primo_livello_duplicati(self):
        seen, dup = {}, []
        for line in read("Design/jt-theme.css").splitlines():
            if line.rstrip().endswith("{") and not line.startswith((" ", "\t", "@")):
                key = line.strip()
                if key in seen:
                    dup.append(key)
                seen[key] = True
        self.assertEqual(dup, [])

    def test_ogni_button_ha_il_type(self):
        files = glob.glob(str(ROOT / "frontend" / "html" / "*.html")) + glob.glob(str(ROOT / "frontend" / "js" / "*.js"))
        missing = []
        for f in files:
            for m in re.finditer(r"<button\b[^>]*>", Path(f).read_text(encoding="utf-8")):
                if "type=" not in m.group(0):
                    missing.append(f"{Path(f).name}: {m.group(0)[:60]}")
        self.assertEqual(missing, [])

    def test_le_fetch_della_pricing_hanno_un_timeout(self):
        src = read("frontend/js/views_pricing.js")
        self.assertEqual(len(re.findall(r"await fetch\('/api/models-pricing", src)), len(re.findall(r"AbortSignal\.timeout\(", src)))

    def test_intestazioni_http_complete_ovunque(self):
        src = read("backend/http_routes.py")
        n = src.count('"X-Frame-Options"')
        self.assertGreaterEqual(n, 3)
        self.assertEqual(src.count('"Referrer-Policy"'), n)
        self.assertEqual(src.count('"Permissions-Policy"'), n)

    def test_ogni_set_cookie_e_httponly_e_samesite(self):
        for line in read("backend/http_routes.py").splitlines():
            if '"Set-Cookie"' in line:
                self.assertIn("HttpOnly", line, line)
                self.assertIn("SameSite=Lax", line, line)

    def test_nessun_globals_nel_calcolo_infra(self):
        self.assertNotIn("globals()", read("backend/infra_costs.py"))


if __name__ == "__main__":
    unittest.main()
