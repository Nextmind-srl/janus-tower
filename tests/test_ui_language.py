"""The UI is English only: no Italian text in user-visible strings (frontend and backend messages)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import server

ROOT = Path(server.__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))
import find_italian  # noqa: E402


class TestUiLanguage(unittest.TestCase):
    def test_nessun_testo_italiano_visibile(self):
        result = find_italian.scan_repo()
        lines = [f"{f}:{line}: [{','.join(h[:3])}] {txt[:90]}" for f, items in result.items() for line, h, txt in items]
        self.assertEqual(lines, [], "Italian text found in user-visible strings:\n" + "\n".join(lines[:20]))

    def test_il_rilevatore_trova_italiano_e_non_inglese(self):
        self.assertTrue(find_italian.italian_hits("Nessun progetto trovato nel periodo"))
        self.assertTrue(find_italian.italian_hits("Connessione non riuscita: è scaduta"))
        self.assertFalse(find_italian.italian_hits("No project found in the selected period"))
        self.assertFalse(find_italian.italian_hits("<!-- RIGA KPI --> Total Invoice (AI + INFRA)"))

    def test_il_traduttore_a_runtime_non_esiste_piu(self):
        for f in (ROOT / "frontend" / "js").glob("*.js"):
            src = f.read_text(encoding="utf-8")
            self.assertNotIn("IT_TO_EN", src, f.name)
            self.assertNotIn("translateStrItToEn", src, f.name)
            self.assertNotIn("translateDomTreeItToEn", src, f.name)


class TestLegacyReasons(unittest.TestCase):
    def test_motivi_italiani_salvati_si_leggono_in_inglese(self):
        ns = {"__name__": "janustower_test", "__file__": server.__file__}
        server.load_backend_modules(ns)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reg.json"
            path.write_text(json.dumps({"accounts": {"a@x.it": {"projects": {
                "p1": {"dataReason": "Nessuna API AI abilitata"},
                "p2": {"dataReason": "2 APIs enabled"},
            }}}}), encoding="utf-8")
            ns["SYNC_REGISTRY_FILE"] = str(path)
            ns["DATA_DIR"] = tmp
            reg = ns["load_sync_registry"]()
        projects = reg["accounts"]["a@x.it"]["projects"]
        self.assertEqual(projects["p1"]["dataReason"], "No AI APIs enabled")
        self.assertEqual(projects["p2"]["dataReason"], "2 APIs enabled")


if __name__ == "__main__":
    unittest.main()
