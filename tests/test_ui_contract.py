"""Test automatici del Contratto UI (Fase 0 del Piano Restyling).

Verifica che nessun elemento strutturale censito in `Design/contratto_ui.json`
(id HTML, id letti via getElementById, funzioni handler inline, attributi data-*,
classi fe-tbl-*, tabelle e relative intestazioni <th>, etichette di KPI e badge)
sparisca da `frontend/` o da `index.html`.
"""

import glob
import html
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "Design" / "contratto_ui.json"


def _strip_decorative_emoji(text: str) -> str:
    """Rimuove eventuali emoji decorative lasciando intatto il testo."""
    cleaned = re.sub(
        r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+",
        "",
        text,
    )
    cleaned = re.sub(r"\(\s*=\s*", "(", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


class TestUiContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        html_paths = sorted(glob.glob(str(ROOT / "frontend" / "html" / "*.html")))
        js_paths = sorted(glob.glob(str(ROOT / "frontend" / "js" / "*.js")))
        cls.html_by_rel = {
            Path(p).relative_to(ROOT).as_posix(): Path(p).read_text(encoding="utf-8")
            for p in html_paths
        }
        cls.js_by_rel = {
            Path(p).relative_to(ROOT).as_posix(): Path(p).read_text(encoding="utf-8")
            for p in js_paths
        }
        cls.html_text = "\n".join(cls.html_by_rel.values())
        cls.js_text = "\n".join(cls.js_by_rel.values())
        cls.all_text = cls.html_text + "\n" + cls.js_text
        cls.all_unescaped = html.unescape(cls.all_text)
        cls.all_unescaped_no_emoji = _strip_decorative_emoji(cls.all_unescaped)
        cls.index_text = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_contract_file_exists_and_valid(self):
        self.assertTrue(CONTRACT_PATH.is_file(), "Design/contratto_ui.json mancante")
        required_keys = {
            "views",
            "html_ids",
            "js_get_element_by_id",
            "inline_handlers",
            "data_attributes",
            "fe_table_classes",
            "tables",
            "kpi_labels",
            "badge_labels",
        }
        self.assertTrue(required_keys.issubset(self.contract.keys()))
        self.assertEqual(len(self.contract["views"]), 11)
        self.assertGreaterEqual(len(self.contract["html_ids"]), 200)
        self.assertGreaterEqual(len(self.contract["js_get_element_by_id"]), 150)
        self.assertEqual(len(self.contract["tables"]), 35)

    def test_all_views_and_html_ids_present(self):
        current_html_ids = set(re.findall(r'\bid=["\']([^"\'${}]+)["\']', self.html_text))
        index_ids = set(re.findall(r'\bid=["\']([^"\'${}]+)["\']', self.index_text))
        for view_id in self.contract["views"]:
            self.assertIn(view_id, current_html_ids, f"Vista {view_id} sparita dall'HTML")
            self.assertIn(view_id, index_ids, f"Vista {view_id} sparita da index.html")
        missing_html = sorted(set(self.contract["html_ids"]) - current_html_ids)
        self.assertEqual(
            missing_html,
            [],
            f"ID HTML rimossi rispetto al contratto: {missing_html}",
        )

    def test_js_get_element_by_id_targets_exist(self):
        defined_ids = set(re.findall(r'\bid=\\?["\']([^"\'\\${}]+)\\?["\']', self.all_text))
        referenced_ids = set(
            re.findall(r'getElementById\(\s*[\'"]([^\'"{}$]+)[\'"]\s*\)', self.all_text)
        )
        missing_refs = sorted(set(self.contract["js_get_element_by_id"]) - (defined_ids | referenced_ids))
        self.assertEqual(
            missing_refs,
            [],
            f"ID getElementById spariti sia dall'HTML sia dal JS: {missing_refs}",
        )
        # Ogni ID statico che era nel DOM HTML deve continuare a esistere nel DOM
        html_Backed = set(self.contract["js_get_element_by_id"]) & set(self.contract["html_ids"])
        missing_dom = sorted(html_Backed - defined_ids)
        self.assertEqual(
            missing_dom,
            [],
            f"ID DOM letti da getElementById ma rimossi dall'HTML: {missing_dom}",
        )

    def test_inline_handlers_present_and_defined(self):
        missing_handlers = []
        for fn in self.contract["inline_handlers"]:
            defined = bool(
                re.search(rf"\bfunction\s+{re.escape(fn)}\s*\(", self.js_text)
                or re.search(rf"\b{re.escape(fn)}\s*=\s*(?:async\s*)?(?:function|\()", self.js_text)
            )
            invoked = bool(re.search(rf"\b{re.escape(fn)}\s*\(", self.all_text))
            if not (defined and invoked):
                missing_handlers.append(fn)
        self.assertEqual(
            missing_handlers,
            [],
            f"Funzioni handler inline mancanti o non più definite: {missing_handlers}",
        )

    def test_data_attributes_and_fe_table_classes_preserved(self):
        for attr in self.contract["data_attributes"]:
            self.assertRegex(
                self.all_text,
                rf"\b{re.escape(attr)}\b",
                f"Attributo {attr} sparito da frontend/",
            )
        for cls_name in self.contract["fe_table_classes"]:
            self.assertRegex(
                self.all_text,
                rf"\b{re.escape(cls_name)}\b",
                f"Classe tabella {cls_name} sparita da frontend/",
            )

    def test_tables_and_column_headers_preserved(self):
        all_sources = {**self.html_by_rel, **self.js_by_rel}
        for tbl in self.contract["tables"]:
            src = tbl["source"]
            self.assertIn(src, all_sources, f"File sorgente {src} mancante")
            src_text = all_sources[src]
            if tbl["table_id"]:
                self.assertIn(
                    f'id="{tbl["table_id"]}"',
                    src_text,
                    f"Tabella #{tbl['table_id']} mancante in {src}",
                )
            if tbl["tbody_id"]:
                self.assertIn(
                    f'id="{tbl["tbody_id"]}"',
                    src_text,
                    f"Tbody #{tbl['tbody_id']} mancante in {src}",
                )
            # Estrai tutti i <th> del file sorgente
            th_texts = []
            for th_m in re.finditer(r"<th\b[^>]*>([\s\S]*?)</th>", src_text):
                raw_th = th_m.group(1)
                clean = re.sub(r"\$\{[\s\S]*?\}", "", raw_th)
                clean = re.sub(r"<[^>]+>", " ", clean)
                clean = html.unescape(clean)
                clean = re.sub(r"\s+", " ", clean).strip()
                if clean:
                    th_texts.append(clean)
            th_texts_no_emoji = [_strip_decorative_emoji(t) for t in th_texts]
            for expected_hdr in tbl["headers"]:
                expected_core = _strip_decorative_emoji(expected_hdr)
                found = (
                    expected_hdr in th_texts
                    or expected_core in th_texts_no_emoji
                )
                self.assertTrue(
                    found,
                    f"Intestazione colonna {expected_hdr!r} mancante in {src} "
                    f"(tabella {tbl['table_id'] or tbl['tbody_id'] or tbl['index_in_file']})",
                )

    def test_kpi_and_badge_labels_preserved(self):
        for lbl in self.contract["kpi_labels"]:
            core = _strip_decorative_emoji(lbl)
            found = (lbl in self.all_unescaped) or (core in self.all_unescaped_no_emoji)
            self.assertTrue(found, f"Etichetta KPI {lbl!r} sparita da frontend/")
        for badge in self.contract["badge_labels"]:
            core = _strip_decorative_emoji(badge)
            found = (badge in self.all_unescaped) or (core in self.all_unescaped_no_emoji)
            self.assertTrue(found, f"Etichetta badge {badge!r} sparita da frontend/")

    def test_pricing_and_rates_view_contract(self):
        """Verifica dedicata alla vista Pricing & Rates (Fase D)."""
        shell_html = self.html_by_rel["frontend/html/shell_and_views.html"]
        modals_html = self.html_by_rel["frontend/html/view_security_and_modals.html"]
        pricing_js = self.js_by_rel["frontend/js/views_pricing.js"]

        # 1. Sidebar entry inside FinOps with #tab-pricing and #tab-count-pricing
        self.assertIn('id="tab-pricing"', shell_html)
        self.assertIn('id="tab-count-pricing"', shell_html)
        self.assertIn("switchTab('pricing')", shell_html)
        self.assertIn("Pricing &amp; Rates", shell_html)

        # 2. Extract #view-pricing section and verify <= 3 top-level blocks (Rule D7)
        m = re.search(
            r'<section id="view-pricing"[^>]*>([\s\S]*?)</section>',
            shell_html,
        )
        self.assertIsNotNone(m, "Sezione #view-pricing non trovata in shell_and_views.html")
        view_pricing_body = m.group(1)
        top_level_block_ids = re.findall(
            r'^\s{8}<div id="([^"]+)"',
            view_pricing_body,
            flags=re.MULTILINE,
        )
        self.assertEqual(
            top_level_block_ids,
            ["pricing-kpi-grid", "pricing-status-banner", "pricing-tabbed-panel"],
            f"#view-pricing deve avere esattamente 3 blocchi top-level, trovati: {top_level_block_ids}",
        )
        self.assertLessEqual(len(top_level_block_ids), 3)

        # 3. Every <th> inside #view-pricing must have scope="col"
        th_tags = re.findall(r"<th\b[^>]*>", view_pricing_body)
        self.assertEqual(len(th_tags), 19)
        for th_tag in th_tags:
            self.assertIn(
                'scope="col"',
                th_tag,
                f"Intestazione <th> priva di scope=\"col\" in #view-pricing: {th_tag}",
            )

        # 4. Zero font sizes below 12px (no text-[8px..11px]) in #view-pricing, modal and views_pricing.js
        modal_match = re.search(
            r'<div id="pricing-model-modal"[\s\S]*$',
            modals_html,
        )
        self.assertIsNotNone(modal_match, "#pricing-model-modal non trovato")
        pricing_bundle = view_pricing_body + "\n" + modal_match.group(0) + "\n" + pricing_js
        tiny_fonts = re.findall(r"text-\[(?:8|9|10|11)px\]", pricing_bundle)
        self.assertEqual(
            tiny_fonts,
            [],
            f"Trovati font sotto 12px nella vista Pricing & Rates: {tiny_fonts}",
        )

        # 5. Standardized rate source badges present
        for badge_label in ("Catalog", "Publisher", "Estimated", "Built-in", "Manual"):
            self.assertIn(badge_label, pricing_js)


if __name__ == "__main__":
    unittest.main()
