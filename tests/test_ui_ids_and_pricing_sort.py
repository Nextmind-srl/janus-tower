"""Ogni getElementById('...') del frontend punta a un elemento che esiste; ordinamento delle colonne della Pricing."""

import glob
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestUiIds(unittest.TestCase):
    def test_ogni_id_letto_dal_js_esiste(self):
        js = "".join(Path(f).read_text(encoding="utf-8") for f in glob.glob(str(ROOT / "frontend" / "js" / "*.js")))
        html = "".join(Path(f).read_text(encoding="utf-8") for f in glob.glob(str(ROOT / "frontend" / "html" / "*.html")))
        used = set(re.findall(r"getElementById\('([A-Za-z0-9_\-]+)'\)", js))
        defined = set(re.findall(r'id="([A-Za-z0-9_\-]+)"', html + js)) | set(re.findall(r"\.id\s*=\s*'([A-Za-z0-9_\-]+)'", js))
        self.assertEqual(sorted(i for i in used if i not in defined), [])


@unittest.skipUnless(shutil.which("node"), "node non disponibile")
class TestPricingSort(unittest.TestCase):
    def test_confronto_numerico_e_testuale(self):
        js = r"""
const s=require('fs').readFileSync('frontend/js/views_pricing.js','utf8');
const a=s.indexOf('function _pricingSortCompare');const b=s.indexOf('function _applyPricingSort');
const m={};new Function('m',s.slice(a,b)+';m.f=_pricingSortCompare;')(m);
const asc=(arr)=>arr.slice().sort(m.f);
console.log(JSON.stringify([asc(['10','9','100','1.5']), asc(['gemini-2.5-pro','gemini-2.5-flash','claude-opus-4']), asc(['','2','1'])]));"""
        out = subprocess.run([shutil.which("node"), "-e", js], capture_output=True, text=True, check=True, cwd=ROOT).stdout  # noqa: S603
        nums, txt, mixed = json.loads(out)
        self.assertEqual(nums, ["1.5", "9", "10", "100"])
        self.assertEqual(txt, ["claude-opus-4", "gemini-2.5-flash", "gemini-2.5-pro"])
        self.assertEqual(sorted(mixed), ["", "1", "2"])

    def test_le_tre_tabelle_pricing_hanno_intestazioni_ordinabili(self):
        src = (ROOT / "frontend" / "js" / "views_pricing.js").read_text(encoding="utf-8")
        html = (ROOT / "frontend" / "html" / "shell_and_views.html").read_text(encoding="utf-8")
        for tid in ("pricing-rates-table", "pricing-unpriced-table", "pricing-unused-table"):
            self.assertIn(f"'{tid}'", src)
            self.assertIn(f'id="{tid}"', html)
        self.assertIn("_applyAllPricingSorts();", src)


if __name__ == "__main__":
    unittest.main()
