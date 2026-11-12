"""Test automatici per la Global Context & Filter Bar (#jt-filterbar).

Verifica:
- Posizione nel DOM e attributi di accessibilità di #jt-filterbar
- Presenza di tutti i 25 controlli nel sottoalbero DOM di #jt-filterbar
- Assenza di ID HTML duplicati nell'intero HTML assemblato
- Conservazione e collegamento degli handler JS inline sui controlli
- Pulizia di <aside id="jt-sidebar"> (rimozione Analysis Filters e select filtri,
  conservazione delle 11 voci di navigazione e #btn-sidebar-collapse)
- Posizionamento di #toggle-show-charts dentro <section id="view-dashboard">
- Definizione di VIEW_APPLICABLE_FILTERS (con tutte le 11 viste),
  syncFilterbarForView, updateFilterbarUi e clearFilterbarChip in frontend/js/core_and_auth.js
"""

from collections import Counter, defaultdict
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _mod_name in ("urllib3", "urllib3.exceptions", "requests", "requests.adapters"):
    try:
        __import__(_mod_name)
    except ModuleNotFoundError:
        sys.modules[_mod_name] = MagicMock()

import server  # noqa: E402

VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

EXPECTED_FILTERBAR_CONTROL_IDS = [
    "filter-project",
    "days-select",
    "jt-m-projects",
    "jt-project-label",
    "jt-project-count",
    "jt-m-range",
    "jt-range-label",
    "custom-date-controls",
    "period-single-date",
    "period-range-inputs",
    "period-start-date",
    "period-end-date",
    "jt-filterbar-btn",
    "jt-filterbar-count",
    "jt-m-filters",
    "filter-cred-type",
    "filter-cred-id",
    "filter-model",
    "filter-only-active",
    "toggle-show-no-ai",
    "count-hidden-no-ai",
    "toggle-show-no-billing",
    "count-hidden-no-billing",
    "filter-exclude-system",
    "search-input",
    "jt-filterbar-reset-btn",
    "jt-filterbar-chips",
]

EXPECTED_VIEWS = [
    "dashboard",
    "daily",
    "credentials",
    "models",
    "projects",
    "users",
    "ai-tools",
    "features",
    "security",
    "sync",
    "pricing",
]


class _DomTreeParser(HTMLParser):
    """HTMLParser standard che traccia ID, attributi, antenati, discendenti e testo per sottoalbero."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None]] = []
        self.id_counts: Counter[str] = Counter()
        self.attrs_by_id: dict[str, dict[str, str]] = {}
        self.tag_by_id: dict[str, str] = {}
        self.ancestors_by_id: dict[str, set[str]] = {}
        self.descendants_by_id: dict[str, set[str]] = defaultdict(set)
        self.text_by_id: dict[str, list[str]] = defaultdict(list)
        self.all_elements: list[tuple[str, dict[str, str], set[str]]] = []

    def _record_open(self, tag: str, attrs: list[tuple[str, str | None]], is_self_closing: bool):
        tag_l = tag.lower()
        attr_map = {k.lower(): (v if v is not None else "") for k, v in attrs}
        elem_id = attr_map.get("id")
        active_ancestor_ids = {aid for _, aid in self.stack if aid}

        self.all_elements.append((tag_l, attr_map, set(active_ancestor_ids)))

        if elem_id:
            self.id_counts[elem_id] += 1
            self.attrs_by_id[elem_id] = attr_map
            self.tag_by_id[elem_id] = tag_l
            self.ancestors_by_id[elem_id] = set(active_ancestor_ids)
            for anc_id in active_ancestor_ids:
                self.descendants_by_id[anc_id].add(elem_id)

        if not is_self_closing and tag_l not in VOID_ELEMENTS:
            self.stack.append((tag_l, elem_id))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        self._record_open(tag, attrs, is_self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]):
        self._record_open(tag, attrs, is_self_closing=True)

    def handle_endtag(self, tag: str):
        tag_l = tag.lower()
        if tag_l in VOID_ELEMENTS:
            return
        for idx in range(len(self.stack) - 1, -1, -1):
            if self.stack[idx][0] == tag_l:
                del self.stack[idx:]
                break

    def handle_data(self, data: str):
        if not data:
            return
        for _, anc_id in self.stack:
            if anc_id:
                self.text_by_id[anc_id].append(data)


class TestFilterbar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prev_cwd = os.getcwd()
        try:
            os.chdir(ROOT)
            cls.assembled_html = server.assemble_frontend_html(".", write_to_disk=False)
        finally:
            os.chdir(prev_cwd)

        cls.dom = _DomTreeParser()
        cls.dom.feed(cls.assembled_html)
        cls.core_js = (ROOT / "frontend" / "js" / "core_and_auth.js").read_text(encoding="utf-8")

    def test_filterbar_position_and_accessibility(self):
        """#jt-filterbar esiste, ha role='region' e aria-label='Filters', ed è tra </header> e <main id='main-scroll-area'>."""
        self.assertIn("jt-filterbar", self.dom.attrs_by_id, "#jt-filterbar mancante nel DOM")
        fb_attrs = self.dom.attrs_by_id["jt-filterbar"]
        self.assertEqual(fb_attrs.get("role"), "region", "#jt-filterbar deve avere role='region'")
        self.assertEqual(fb_attrs.get("aria-label"), "Filters", "#jt-filterbar deve avere aria-label='Filters'")

        header_close_idx = self.assembled_html.find("</header>")
        filterbar_idx = re.search(r'\bid=["\']jt-filterbar["\']', self.assembled_html)
        main_open_idx = re.search(r'<main\b[^>]*\bid=["\']main-scroll-area["\']', self.assembled_html)

        self.assertNotEqual(header_close_idx, -1, "</header> non trovato nell'HTML assemblato")
        self.assertIsNotNone(filterbar_idx, "#jt-filterbar non trovato nell'HTML assemblato")
        self.assertIsNotNone(main_open_idx, "<main id='main-scroll-area'> non trovato nell'HTML assemblato")

        self.assertGreater(
            filterbar_idx.start(),
            header_close_idx,
            "#jt-filterbar deve comparire dopo </header>",
        )
        self.assertLess(
            filterbar_idx.start(),
            main_open_idx.start(),
            "#jt-filterbar deve comparire prima di <main id='main-scroll-area'>",
        )

    def test_controls_inside_filterbar(self):
        """Tutti i controlli previsti si trovano nel sottoalbero DOM di #jt-filterbar."""
        self.assertIn("jt-filterbar", self.dom.attrs_by_id, "#jt-filterbar mancante nel DOM")
        fb_descendants = self.dom.descendants_by_id["jt-filterbar"]
        missing_in_fb = [cid for cid in EXPECTED_FILTERBAR_CONTROL_IDS if cid not in fb_descendants]
        self.assertEqual(
            missing_in_fb,
            [],
            f"Controlli mancanti dentro il sottoalbero #jt-filterbar: {missing_in_fb}",
        )

    def test_no_duplicate_ids_in_assembled_html(self):
        """Nessun attributo id='...' è duplicato nell'intero HTML assemblato."""
        duplicates = {elem_id: cnt for elem_id, cnt in self.dom.id_counts.items() if cnt > 1}
        self.assertEqual(
            duplicates,
            {},
            f"ID HTML duplicati trovati nell'HTML assemblato: {duplicates}",
        )

    def test_inline_handlers_preserved_and_wired(self):
        """Gli handler JS inline sono presenti e collegati ai rispettivi controlli."""
        expected_control_handlers = {
            "filter-project": ("data-jt-change", "onProjectFilterChanged()"),
            "days-select": ("data-jt-change", "onPeriodDaysChanged(this.value)"),
            "period-single-date": ("data-jt-change", "applyCustomDateFilter()"),
            "filter-cred-type": ("data-jt-change", "onCredTypeFilterChanged()"),
            "filter-cred-id": ("data-jt-change", "onSpecificCredChanged()"),
            "filter-model": ("data-jt-change", "onModelFilterChanged()"),
            "toggle-show-no-ai": ("data-jt-change", "onVisibilityTogglesChanged()"),
            "toggle-show-no-billing": ("data-jt-change", "onVisibilityTogglesChanged()"),
            "filter-exclude-system": ("data-jt-change", "onFiltersChanged()"),
            "jt-filterbar-reset-btn": ("data-jt-click", "resetAllFilters()"),
            "toggle-show-charts": ("data-jt-change", "toggleChartsSection(this.checked)"),
        }
        for ctrl_id, (attr_name, handler_call) in expected_control_handlers.items():
            self.assertIn(ctrl_id, self.dom.attrs_by_id, f"Controllo #{ctrl_id} mancante nel DOM")
            actual_attr = self.dom.attrs_by_id[ctrl_id].get(attr_name, "")
            self.assertIn(
                handler_call,
                actual_attr,
                f"Controllo #{ctrl_id} deve avere {attr_name} contenente {handler_call!r}, trovato {actual_attr!r}",
            )

        # Verifica anche il bottone Apply dentro #period-range-inputs
        apply_buttons = [
            attrs
            for tag, attrs, ancestors in self.dom.all_elements
            if tag == "button"
            and "period-range-inputs" in ancestors
            and "applyCustomDateFilter()" in attrs.get("data-jt-click", "")
        ]
        self.assertTrue(
            len(apply_buttons) >= 1,
            "Bottone Apply con data-jt-click='applyCustomDateFilter()' mancante dentro #period-range-inputs",
        )

    def test_sidebar_cleaned_and_navigation_preserved(self):
        """<aside id='jt-sidebar'> non contiene Analysis Filters né #filter-cred-type/#filter-model, ma conserva le 11 voci nav e #btn-sidebar-collapse."""
        self.assertIn("jt-sidebar", self.dom.attrs_by_id, "<aside id='jt-sidebar'> mancante nel DOM")
        sidebar_descendants = self.dom.descendants_by_id["jt-sidebar"]
        sidebar_text = " ".join(self.dom.text_by_id["jt-sidebar"])

        self.assertNotIn(
            "Analysis Filters",
            sidebar_text,
            "<aside id='jt-sidebar'> non deve più contenere 'Analysis Filters'",
        )
        self.assertNotIn(
            "filter-cred-type",
            sidebar_descendants,
            "#filter-cred-type non deve più trovarsi dentro #jt-sidebar",
        )
        self.assertNotIn(
            "filter-model",
            sidebar_descendants,
            "#filter-model non deve più trovarsi dentro #jt-sidebar",
        )

        for view in EXPECTED_VIEWS:
            has_nav_item = (f"tab-{view}" in sidebar_descendants) or (f"nav-{view}" in sidebar_descendants)
            self.assertTrue(
                has_nav_item,
                f"Voce di navigazione per la vista '{view}' (tab-{view} / nav-{view}) mancante in #jt-sidebar",
            )

        self.assertIn(
            "btn-sidebar-collapse",
            sidebar_descendants,
            "#btn-sidebar-collapse deve restare dentro #jt-sidebar",
        )

    def test_toggle_show_charts_inside_view_dashboard(self):
        """#toggle-show-charts si trova all'interno di <section id='view-dashboard'>."""
        self.assertIn("view-dashboard", self.dom.attrs_by_id, "<section id='view-dashboard'> mancante")
        self.assertIn("toggle-show-charts", self.dom.attrs_by_id, "#toggle-show-charts mancante")
        self.assertIn(
            "toggle-show-charts",
            self.dom.descendants_by_id["view-dashboard"],
            "#toggle-show-charts deve trovarsi all'interno di <section id='view-dashboard'>",
        )

    def test_filterbar_icons_are_project_svg_not_font_awesome(self):
        """Font Awesome non e' caricato: la barra deve usare solo le icone SVG #ico-* del progetto."""
        m = re.search(r'<div[^>]*id="jt-filterbar".*?</header>|id="jt-filterbar".*?<main', self.assembled_html, re.S)
        bar = m.group(0) if m else ""
        self.assertTrue(bar, "barra filtri non trovata")
        self.assertNotRegex(bar, r'class="[^"]*\bfa[srl]?\b')
        for sym in re.findall(r'<use href="#(ico-[a-z-]+)"', bar):
            self.assertIn(f'id="{sym}"', self.assembled_html)

    def test_disabled_filters_are_ignored_in_aggregation(self):
        """getFilteredAggregation usa valori neutri per i controlli disabilitati (non applicabili alla vista)."""
        i = self.core_js.index("function getFilteredAggregation")
        body = self.core_js[i:i + 1200]
        self.assertIn(".disabled", body)

    def test_core_and_auth_js_filterbar_functions_and_views(self):
        """VIEW_APPLICABLE_FILTERS, syncFilterbarForView, updateFilterbarUi e clearFilterbarChip sono definite in core_and_auth.js con tutte le 11 viste."""
        self.assertRegex(
            self.core_js,
            r"\bVIEW_APPLICABLE_FILTERS\b",
            "VIEW_APPLICABLE_FILTERS non definita in frontend/js/core_and_auth.js",
        )
        for fn_name in ("syncFilterbarForView", "updateFilterbarUi", "clearFilterbarChip"):
            defined = bool(
                re.search(rf"\bfunction\s+{re.escape(fn_name)}\s*\(", self.core_js)
                or re.search(rf"\b{re.escape(fn_name)}\s*=\s*(?:async\s*)?(?:function|\()", self.core_js)
            )
            self.assertTrue(
                defined,
                f"Funzione {fn_name} non definita in frontend/js/core_and_auth.js",
            )

        m = re.search(
            r"\bVIEW_APPLICABLE_FILTERS\s*=\s*\{([\s\S]*?)\};",
            self.core_js,
        )
        self.assertIsNotNone(
            m,
            "Oggetto VIEW_APPLICABLE_FILTERS = { ... }; non trovato in frontend/js/core_and_auth.js",
        )
        map_body = m.group(1)
        for view in EXPECTED_VIEWS:
            pattern = rf"(?:['\"]?{re.escape(view)}['\"]?)\s*:"
            self.assertRegex(
                map_body,
                pattern,
                f"Vista {view!r} non censita in VIEW_APPLICABLE_FILTERS",
            )


if __name__ == "__main__":
    unittest.main()
