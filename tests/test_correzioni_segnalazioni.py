"""Correzioni da revisione esterna: Docker/tema, importi di fattura fuori dal codice, traduttore e filtri tabella (dati inventati)."""

import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import server

ROOT = Path(server.__file__).resolve().parent


def load_app_namespace() -> dict:
    ns = {"__name__": "janustower_test", "__file__": server.__file__}
    server.load_backend_modules(ns)
    return ns


class TestDockerTema(unittest.TestCase):
    def test_dockerfile_copia_tutti_i_css_del_tema(self):
        docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        for rel in server.FRONTEND_CSS_MODULES:
            if rel.startswith("Design/"):
                self.assertIn(os.path.basename(rel), docker, f"Dockerfile non copia {rel}")


class TestFatturaNonNelCodice(unittest.TestCase):
    def test_nessun_importo_ne_nome_istanza_nel_sorgente(self):
        for rel in ("backend/project_inspector.py",):
            src = (ROOT / rel).read_text(encoding="utf-8")
            for needle in ("agentspace-pgvector", "agentspace-redis", "BILLING_30D_INFRA_SERVICES_SPEC", "infra_billing_spec"):
                self.assertNotIn(needle, src, rel)
            self.assertIsNone(re.search(r'"gross30d":\s*\d', src), f"importi di fattura in {rel}")
        # the infrastructure cost modules were removed: only AI costs are estimated
        for rel in ("backend/infra_costs.py", "backend/infra_costs_minor.py"):
            self.assertFalse((ROOT / rel).exists(), rel)


@unittest.skipUnless(shutil.which("node"), "node non disponibile")
class TestJsComportamento(unittest.TestCase):
    def _run(self, js: str) -> str:
        node = shutil.which("node")
        return subprocess.run([node, "-e", js], capture_output=True, text=True, check=True, cwd=ROOT).stdout.strip()  # noqa: S603

    def test_numeri_in_formato_inglese_si_ordinano_come_numeri(self):
        js = r"""
const s=require('fs').readFileSync('frontend/js/views_security_and_modals.js','utf8');
const a=s.indexOf('function _parsePlainNumericCell');const b=s.indexOf('function parseSmartCellSortValue');
const m={};new Function('m',s.slice(a,b)+';m.f=_parsePlainNumericCell;')(m);
const c=require('fs').readFileSync('frontend/js/core_and_auth.js','utf8');
const k=c.indexOf('function fmtNum');const e=c.indexOf('function fmtTok');
new Function('m',c.slice(k,e)+';m.n=fmtNum;')(m);
console.log(JSON.stringify([m.f('12,450'),m.f('1,234.5'),m.f('85.5'),m.f('12.450'),m.f('1,5'),m.f('1,2345'),m.f('abc'),m.n(110506)]));"""
        self.assertEqual(json.loads(self._run(js)), [12450, 1234.5, 85.5, 12.45, 1.5, 1.2345, None, "110,506"])

    def test_filtro_tabella_non_confonde_active_con_inactive(self):
        js = r"""
const s=require('fs').readFileSync('frontend/js/views_security_and_modals.js','utf8');
const a=s.indexOf('function _rowTextHasFilterToken');const b=s.indexOf('function _doesCostMatchBand');
const m={};new Function('m',s.slice(a,b)+';m.f=_rowTextHasFilterToken;')(m);
console.log(JSON.stringify([m.f('sa inactive / dormant','active'),m.f('sa active traffic','active'),
 m.f('x unprotected','protected'),m.f('gemini-2.5-pro','gemini-2.5'),m.f('multimodalembedding@001','embedding')]));"""
        self.assertEqual(json.loads(self._run(js)), [False, True, False, True, True])


if __name__ == "__main__":
    unittest.main()
