"""Filtri a tendina delle tabelle: ogni valore deve trovare le righe giuste (righe inventate nel formato reale)."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

import server

ROOT = Path(server.__file__).resolve().parent

# Testo visibile (innerText, minuscolo) di righe inventate, nel formato prodotto dai renderer.
ROWS = {
    "projects-tbody": {
        "attivo": "demo project alpha prj-active full (12/12) vertex ai active 120 5k tok $3.20",
        "fermo": "demo project beta prj-idle full (12/12) no ai service inactive 0 0 $0.00",
    },
    "credentials-tbody": {
        "traffico": "demo key apikey:abc cred-traffic api_key demo-project vertex 40 0 1k",
        "fermo": "old key apikey:xyz cred-idle api_key demo-project system calls only ($0) 0 0 0",
    },
    "service-accounts-tbody": {
        "esportata": "runner demo sa-traffic runner@demo.iam.gserviceaccount.com demo-project active custom iam 2 exported keys 1a2b3c4d5e (2025-01-01) 10 1k $0.50",
        "zero": "batch demo sa-dormant batch@demo.iam.gserviceaccount.com demo-project active default gcp 0 keys 0 0 $0.00",
        "dieci": "grande demo sa-traffic grande@demo.iam.gserviceaccount.com demo-project active custom iam 10 exported keys 5 1 $1.00",
    },
    "mcp-registry-tbody": {
        "mcp": "demo tools demo-project global agent_registry_mcp mcp server v1 active",
        "agente": "demo helper demo-project europe-west1 reasoning_engine vertex agent engine v1 active",
        "spento": "old tools demo-project global agent_registry_mcp mcp server v1 cataloged",
    },
    "model-armor-matrix-tbody": {
        "coperta": "demo alpha demo-project · 10 calls europe-west1 floor on 1 templates active (1 templates, floor policy on) 0 op 0 alerts / 0 blocked no remediation required",
        "scoperta": "demo beta demo-project · 5 calls global floor off 0 templates 0 op 0 alerts / 0 blocked not enabled go to remediation in ai security →",
        "solo_api": "demo gamma demo-project · 5 calls us-east1 floor off 0 templates 0 op 0 alerts / 0 blocked api enabled (0 templates) go to remediation in ai security →",
    },
    "models-tbody": {
        "gemini": "demo-project gemini-2.5-pro us-central1 100",
        "claude": "demo-project claude-sonnet-4 europe-west1 100",
        "embedding": "demo-project multimodalembedding@001 us-central1 100",
    },
}

# Marcatori invisibili (data-jt-token): non sono nel testo visibile, ma li legge il filtro.
TOKENS = {
    "mcp-registry-tbody": {"mcp": "mcp-server mcp-active", "agente": "mcp-agent mcp-active", "spento": "mcp-server mcp-inactive"},
    "model-armor-matrix-tbody": {"coperta": "ma-protected", "scoperta": "ma-unprotected", "solo_api": "ma-unprotected"},
}

# (tbody, chiave filtro, valore, righe attese)
CASI = [
    ("projects-tbody", "status", "prj-active", {"attivo"}),
    ("projects-tbody", "status", "prj-idle", {"fermo"}),
    ("credentials-tbody", "risk", "cred-traffic", {"traffico"}),
    ("credentials-tbody", "risk", "cred-idle", {"fermo"}),
    ("service-accounts-tbody", "saKeyFilter", "exported", {"esportata", "dieci"}),
    ("service-accounts-tbody", "saKeyFilter", "0 keys", {"zero"}),
    ("service-accounts-tbody", "saActivity", "sa-traffic", {"esportata", "dieci"}),
    ("service-accounts-tbody", "saActivity", "sa-dormant", {"zero"}),
    ("mcp-registry-tbody", "mcpType", "mcp-server", {"mcp", "spento"}),
    ("mcp-registry-tbody", "mcpType", "mcp-agent", {"agente"}),
    ("mcp-registry-tbody", "mcpType", "mcp-active", {"mcp", "agente"}),
    ("model-armor-matrix-tbody", "armorState", "ma-protected", {"coperta"}),
    ("model-armor-matrix-tbody", "armorState", "ma-unprotected", {"scoperta", "solo_api"}),
    ("models-tbody", "family", "gemini", {"gemini"}),
    ("models-tbody", "family", "claude", {"claude"}),
    ("models-tbody", "family", "embedding", {"embedding"}),
]

JS = r"""
const s=require('fs').readFileSync('frontend/js/views_security_and_modals.js','utf8');
const a=s.indexOf('function _rowTextHasFilterToken');const b=s.indexOf('function _doesCostMatchBand');
const c=s.indexOf('const TABLE_CONTEXTUAL_FILTERS_CONFIG');const d=s.indexOf('function _parseLeadingUsdAmount');
const m={};new Function('m',s.slice(c,d)+s.slice(a,b)+';m.f=_rowTextHasFilterToken;m.cfg=TABLE_CONTEXTUAL_FILTERS_CONFIG;')(m);
const rows=JSON.parse(process.argv[1]);const casi=JSON.parse(process.argv[2]);const tok=JSON.parse(process.argv[3]);
const ft=(tb,r)=>rows[tb][r]+' '+((tok[tb]||{})[r]||'');
const out=casi.map(([tb,key,val])=>Object.keys(rows[tb]).filter(r=>m.f(ft(tb,r),val)).sort());
const cfgOk=casi.map(([tb,key,val])=>(m.cfg[tb]||[]).some(c=>c.key===key&&c.options.some(o=>o.val===val)));
console.log(JSON.stringify({out,cfgOk,f:[m.f('sa inactive / dormant','active'),m.f('sa active','active'),m.f('x unprotected','protected')]}));"""


@unittest.skipUnless(shutil.which("node"), "node non disponibile")
class TestFiltriTabelle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = shutil.which("node")
        res = subprocess.run(  # noqa: S603
            [node, "-e", JS, json.dumps(ROWS), json.dumps([c[:3] for c in CASI]), json.dumps(TOKENS)],
            capture_output=True, text=True, check=True, cwd=ROOT,
        ).stdout.strip()
        cls.res = json.loads(res)

    def test_ogni_valore_trova_le_righe_giuste(self):
        for (tbody, key, val, attese), trovate in zip(CASI, self.res["out"], strict=True):
            self.assertEqual(set(trovate), attese, f"{tbody}/{key}/{val}")

    def test_i_valori_dei_casi_esistono_nella_configurazione(self):
        for (tbody, key, val, _), ok in zip(CASI, self.res["cfgOk"], strict=True):
            self.assertTrue(ok, f"{tbody}/{key}/{val} non e' nel menu a tendina")

    def test_il_testo_visibile_non_contiene_i_marcatori(self):
        for tbody in TOKENS:
            for name, text in ROWS[tbody].items():
                self.assertNotIn("protected", text, f"{tbody}/{name}")
                self.assertNotIn("ma-", text, f"{tbody}/{name}")
                self.assertNotIn("mcp-", text, f"{tbody}/{name}")

    def test_i_marcatori_restano_fuori_da_testo_e_csv(self):
        js = (ROOT / "frontend/js/views_dashboard_and_finops.js").read_text(encoding="utf-8")
        self.assertIn('<span class="hidden" data-jt-token="${escapeHtml(token)}" aria-hidden="true"></span>', js)
        sec = (ROOT / "frontend/js/views_security_and_modals.js").read_text(encoding="utf-8")
        # Il CSV legge solo innerText/textContent delle celle: il marcatore e' un attributo di uno span vuoto.
        # Nel file dei filtri/CSV l'attributo si legge solo in _rowFilterTokens (e in commenti), mai nel testo delle celle.
        uses = [ln for ln in sec.splitlines() if "data-jt-token" in ln and not ln.lstrip().startswith("//")]
        self.assertEqual(len(uses), 1, uses)
        self.assertIn("querySelectorAll('[data-jt-token]')", uses[0])
        for tok in ("ma-protected", "ma-unprotected", "mcp-server", "mcp-agent", "mcp-active", "mcp-inactive"):
            self.assertIn(f"'{tok}'", sec)

    def test_active_non_trova_inactive(self):
        self.assertEqual(self.res["f"], [False, True, False])


if __name__ == "__main__":
    unittest.main()
