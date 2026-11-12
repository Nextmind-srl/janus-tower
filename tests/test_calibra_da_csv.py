"""Tests for tools/calibra_da_csv.py using a synthetic CSV (invented model, invented numbers)."""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("calibra_da_csv", ROOT / "tools" / "calibra_da_csv.py")
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

HEADER = (
    "Descrizione servizio,ID servizio,Descrizione SKU,ID SKU,Quantità di utilizzo,Unità di utilizzo,"
    "Costo di listino (€),Risparmi negoziati (€),Programmi di risparmio (€),Altri risparmi (€),"
    "Subtotale non arrotondato (€),Subtotale (€),Variazione percentuale del totale parziale rispetto al periodo precedente"
)
ROWS = [
    ("Vertex AI", "Gemini 9 Test Global Text Input - Online Predictions", "10.000.000", "20,00", "-8,00"),
    ("Vertex AI", "Gemini 9 Test Regional Text Input - Online Predictions", "10.000.000", "24,00", "-9,60"),
    ("Vertex AI", "Gemini 9 Test Global Text Output - Online Predictions", "1.000.000", "10,00", "-4,00"),
    ("Vertex AI", "Gemini 9 Test Regional Text Output - Online Predictions", "1.000.000", "12,00", "-4,80"),
    ("Vertex AI", "Gemini 9 Test Regional Text Input Caching Online", "50.000.000", "12,00", "-4,80"),
    ("Gemini API", "Generate content input token count gemini 9 test text", "10.000.000", "25,00", "-2,50"),
    ("Gemini API", "Generate content cached input token count gemini 9 test text", "90.000.000", "9,00", "-0,90"),
    ("Cloud SQL", "Cloud SQL for PostgreSQL: Zonal - RAM", "744", "50,00", "0,00"),
]


def _write_csv(path: Path) -> None:
    lines = [HEADER]
    for service, sku, qty, lst, other in ROWS:
        lines.append(f'{service},ID,{sku},SKU-ID,"{qty}",count,"{lst}","0,00","0,00","{other}","0,00","0,00",Nuova')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestCalibraDaCsv(unittest.TestCase):
    def test_parse_number_italian_format(self) -> None:
        self.assertEqual(tool.parse_number("1.850,70"), 1850.70)
        self.assertEqual(tool.parse_number("115.946.171"), 115946171.0)
        self.assertEqual(tool.parse_number("-0,01"), -0.01)
        self.assertEqual(tool.parse_number("Nuova"), 0.0)
        self.assertEqual(tool.parse_number("263%"), 0.0)
        self.assertEqual(tool.parse_number(""), 0.0)

    def test_model_label_and_sku_classification(self) -> None:
        self.assertEqual(tool.model_label_from_sku("Gemini 4 Argon Regional Text Input - Online Predictions"), "gemini-4-argon")
        self.assertEqual(tool.model_label_from_sku("Generate content input token count gemini 3.8 flash text"), "gemini-3.8-flash")
        self.assertIsNone(tool.model_label_from_sku("Cloud SQL for PostgreSQL: Zonal - RAM"))
        self.assertEqual(tool.classify_sku("Gemini 9 Test Regional Text Input Caching Online"),
                         {"kind": "cache", "modality": "text", "scope": "regional"})
        self.assertEqual(tool.classify_sku("Gemini 9 Test Global Image Input - Online Predictions"),
                         {"kind": "input", "modality": "image", "scope": "global"})

    def test_proposal_from_synthetic_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "report.csv"
            pricing_path = Path(tmp) / "pricing.json"
            out_path = Path(tmp) / "proposal.json"
            _write_csv(csv_path)
            pricing = {"models": {"gemini-9-test": {"input": 2.5, "output": 12.5, "geminiApiRates": {"input": 3.125}}}}
            pricing_path.write_text(json.dumps(pricing), encoding="utf-8")
            before = pricing_path.read_text(encoding="utf-8")

            with contextlib.redirect_stdout(io.StringIO()):
                rc = tool.main([str(csv_path), "--pricing", str(pricing_path), "--out", str(out_path)])
            self.assertEqual(rc, 0)
            proposal = json.loads(out_path.read_text(encoding="utf-8"))
            bs = proposal["billingSettings"]
            self.assertEqual(bs["vertexBillingCreditDiscountPct"], 40.0)
            self.assertEqual(bs["geminiApiBillingCreditDiscountPct"], 10.0)
            self.assertAlmostEqual(bs["vertexImplicitCacheHitRatioPct"], 71.4, places=1)
            self.assertEqual(bs["geminiApiImplicitCacheHitRatioPct"], 90.0)
            self.assertEqual(bs["regionalMultiplierDefault"], 1.2)
            self.assertEqual(bs["usdToEurRate"], 0.8)
            self.assertEqual(proposal["geminiApiCacheHitRatioByModelPct"], {"gemini-9-test": 90.0})
            self.assertFalse(proposal["applied"])
            # read-only: the pricing file must be untouched
            self.assertEqual(pricing_path.read_text(encoding="utf-8"), before)

    def test_eur_rate_ignores_tiny_rows_and_follows_last_file(self) -> None:
        pricing = {"models": {"gemini-9-test": {"input": 2.5, "output": 12.5}}}
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "a.csv", Path(tmp) / "b.csv"
            _write_csv(first)
            lines = [HEADER]
            for service, sku, qty, lst, other in ROWS:
                if service == "Vertex AI" and "Regional" not in sku and "Caching" not in sku:
                    # same SKU one month later at a different exchange rate (0.9 instead of 0.8)
                    new_list = f"{float(lst.replace(',', '.')) * 1.125:.2f}".replace(".", ",")
                    lines.append(f'{service},ID,{sku},SKU-ID,"{qty}",count,"{new_list}","0,00","0,00","{other}","0,00","0,00",Nuova')
            # a tiny row with a wildly different unit price must be ignored (list below the threshold)
            lines.append('Vertex AI,ID,Gemini 9 Test Global Text Input - Tiny,SKU-ID,"100",count,"0,01","0,00","0,00","0,00","0,00","0,00",Nuova')
            second.write_text("\n".join(lines) + "\n", encoding="utf-8")
            rows = tool.load_rows([first, second])
            eur = tool.compute_eur_rate(rows, pricing, 1.0)
            self.assertEqual(eur["bySource"]["a.csv"]["rate"], 0.8)
            self.assertEqual(eur["bySource"]["b.csv"]["rate"], 0.9)
            self.assertEqual(eur["rate"], 0.9)

    def test_storage_and_non_text_skus_are_ignored(self) -> None:
        self.assertIsNone(tool.classify_sku("Gemini 9 Test Context Caching Storage"))
        self.assertIsNone(tool.classify_sku("Gemini 9 Test Token hours cached content"))
        self.assertEqual(tool.classify_sku("Gemini 9 Test Global Audio Input - Online")["modality"], "other")

    def test_regional_multiplier_aggregates_several_skus(self) -> None:
        def row(scope: str, lst: float, qty: float) -> dict:
            return {"service": "Vertex AI", "model": "gemini-9-test", "modality": "text", "kind": "input",
                    "scope": scope, "list": lst, "qty": qty}
        rows = [row("global", 10.0, 5e6), row("global", 30.0, 5e6), row("regional", 22.0, 5e6), row("regional", 66.0, 5e6)]
        # global: 40 EUR / 10M = 4/M ; regional: 88 EUR / 10M = 8.8/M -> 2.2 (the old "last row wins" gave 2.2 too only by luck)
        self.assertEqual(tool.compute_regional_multiplier(rows)["multiplier"], 2.2)
        rows2 = [row("global", 10.0, 5e6), row("global", 30.0, 5e6), row("regional", 66.0, 5e6), row("regional", 22.0, 5e6)]
        self.assertEqual(tool.compute_regional_multiplier(rows2)["multiplier"], 2.2)

    def test_regional_multiplier_ignores_cent_level_groups(self) -> None:
        def row(scope: str, lst: float, qty: float) -> dict:
            return {"service": "Vertex AI", "model": "gemini-9-test", "modality": "text", "kind": "input",
                    "scope": scope, "list": lst, "qty": qty}
        tiny = [row("global", 0.03, 141480), row("regional", 0.35, 1222156)]
        self.assertIsNone(tool.compute_regional_multiplier(tiny)["multiplier"])

    def test_english_number_warning_and_out_safety(self) -> None:
        self.assertTrue(tool.looks_like_english_number("12.34"))
        self.assertFalse(tool.looks_like_english_number("1.850,70"))
        self.assertFalse(tool.looks_like_english_number("115.946.171"))
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "report.csv"
            _write_csv(csv_path)
            pricing = Path(tmp) / "pricing.json"
            pricing.write_text("{}", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(tool.main([str(csv_path), "--pricing", str(pricing), "--out", str(pricing)]), 2)
                self.assertEqual(tool.main([str(csv_path), "--pricing", str(pricing), "--out", str(csv_path)]), 2)
            self.assertEqual(pricing.read_text(encoding="utf-8"), "{}")

    def test_missing_file_and_empty_csv(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(tool.main(["/nonexistent/file.csv"]), 2)
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty.csv"
            empty.write_text(HEADER + "\n", encoding="utf-8")
            out_path = Path(tmp) / "p.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(tool.main([str(empty), "--pricing", str(Path(tmp) / "none.json"), "--out", str(out_path)]), 0)
            proposal = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(proposal["billingSettings"], {})
            self.assertTrue(proposal["notes"])


if __name__ == "__main__":
    unittest.main()
