"""Servizi minori (Artifact Registry, Secret Manager, BigQuery, Cloud Storage, Cloud Run): dati e risposte inventati.

Prezzi unitari inventati e tondi: i test controllano l'aritmetica, nessun dato di un cliente.
"""

import unittest
from datetime import datetime, timezone

import server

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
GIB = 2 ** 30
TIB = 2 ** 40


def load_app_namespace() -> dict:
    ns = {"__name__": "janustower_test", "__file__": server.__file__}
    server.load_backend_modules(ns)
    ns["get_billing_settings"] = lambda: {"infraSavingsPct": 0.0}
    ns["get_usd_to_eur_rate"] = lambda: 0.92
    return ns


def sku(desc, unit, price, regions=("europe-west8",)):
    return {"d": desc, "u": unit, "p": price, "r": list(regions)}


def series(value, **labels):
    return {"resource": {"labels": labels}, "metric": {"labels": labels},
            "points": [{"value": {"doubleValue": value}}]}


class TestMinorInfra(unittest.TestCase):
    def setUp(self):
        self.ns = load_app_namespace()

    def test_artifact_registry_calcola_storage(self):
        skus = [sku("Artifact Registry Storage", "GiBy.mo", 0.1), sku("Artifact Registry Network Internet Egress", "GiBy", 0.1)]
        repos = {"projects/p/locations/europe-west8": [{"name": "projects/p/locations/europe-west8/repositories/docker", "sizeBytes": str(13 * GIB)},
                                                       {"name": "projects/p/locations/europe-west8/repositories/vuoto", "sizeBytes": "0"}]}

        def fetch(url):
            if url.split("?")[0].endswith("/locations"):
                return 200, {"locations": [{"locationId": "europe-west8"}, {"locationId": "us-east1"}]}
            return 200, {"repositories": next((v for k, v in repos.items() if k in url), [])}
        line = self.ns["build_artifactregistry_line"]("p", "t", 31, skus, fetch=fetch, now=NOW)
        self.assertAlmostEqual(line["grossCostUsd"], 13 * 0.1, delta=0.001)
        self.assertEqual(line["instances"], ["docker"])

    def test_artifact_registry_senza_repository_nessuna_riga(self):
        self.assertIsNone(self.ns["build_artifactregistry_line"]("p", "t", 31, [], fetch=lambda u: (200, {"locations": [{"locationId": "europe-west8"}]}), now=NOW))

    def test_artifact_registry_tutte_le_posizioni_in_errore_non_e_zero(self):
        def fetch(u):
            return (200, {"locations": [{"locationId": "europe-west8"}]}) if u.split("?")[0].endswith("/locations") else (403, {})
        line = self.ns["build_artifactregistry_line"]("p", "t", 31, [], fetch=fetch, now=NOW)
        self.assertEqual(line["estimateStatus"], "unavailable")

    def test_secret_manager_conta_versioni_attive_e_repliche(self):
        skus = [sku("Secret version replica storage", "mo", 0.052)]

        def fetch(url):
            if "/versions" in url:
                return 200, {"versions": [{}, {}, {}]}  # 3 versioni attive per secret
            return 200, {"secrets": [{"name": "projects/p/secrets/a", "replication": {"automatic": {}}},
                                     {"name": "projects/p/secrets/b", "replication": {"userManaged": {"replicas": [{}, {}]}}}]}
        line = self.ns["build_secretmanager_line"]("p", "t", 31, skus, fetch=fetch, now=NOW)
        self.assertAlmostEqual(line["grossCostUsd"], (3 * 1 + 3 * 2) * 0.052, delta=0.001)

    def test_bigquery_analisi_e_storage(self):
        skus = [sku("Analysis", "TiBy", 6.0, ["eu"]), sku("Active Logical Storage", "GiBy.mo", 0.02, ["eu"])]

        def mon(metric, group_by, aligner):
            if "scanned_bytes_billed" in metric:
                return [series(0.01 * TIB, location="EU")]
            return [series(50 * GIB, location="EU")]
        line = self.ns["build_bigquery_line"]("p", "t", 31, skus, mon_fetch=mon, now=NOW)
        self.assertAlmostEqual(line["grossCostUsd"], 0.01 * 6.0 + 50 * 0.02, delta=0.001)

    def test_storage_multi_region_e_regione(self):
        skus = [sku("Standard Storage Europe Multi-region", "GiBy.mo", 0.026, ["eu"]), sku("Standard Storage Milan", "GiBy.mo", 0.023),
                sku("Standard Class A Operations", "count", 0.1)]
        mon = lambda m, g, a: [series(10 * GIB, location="EU", storage_class="STANDARD"),  # noqa: E731
                               series(20 * GIB, location="europe-west8", storage_class="STANDARD")]
        line = self.ns["build_storage_line"]("p", "t", 31, skus, mon_fetch=mon, now=NOW)
        self.assertAlmostEqual(line["grossCostUsd"], 10 * 0.026 + 20 * 0.023, delta=0.001)

    def test_storage_senza_prezzo_non_diventa_zero(self):
        mon = lambda m, g, a: [series(10 * GIB, location="europe-west8", storage_class="COLDLINE")]  # noqa: E731
        line = self.ns["build_storage_line"]("p", "t", 31, [], mon_fetch=mon, now=NOW)
        self.assertEqual(line["estimateStatus"], "not_estimable")
        self.assertIn("price", line["estimateNote"])

    def test_cloud_run_cpu_memoria_richieste(self):
        skus = [sku("Services CPU (Request-based billing)", "s", 0.000024), sku("Services Memory (Request-based billing)", "GiBy.s", 0.0000025),
                sku("Requests", "count", 0.0000004)]
        vals = {"cpu/allocation_time": 1000.0, "memory/allocation_time": 2000.0, "request_count": 5000.0}
        mon = lambda m, g, a: [series(next(v for k, v in vals.items() if k in m), location="europe-west8")]  # noqa: E731
        line = self.ns["build_run_line"]("p", "t", 31, skus, mon_fetch=mon, now=NOW, desc_fetch=lambda m: "GiBy.s" if "memory" in m else "s")
        self.assertAlmostEqual(line["grossCostUsd"], 1000 * 0.000024 + 2000 * 0.0000025 + 5000 * 0.0000004, delta=1e-6)
        self.assertEqual(line["estimateNote"], "")

    def _run_cost(self, mem_unit, mem_value=2.0 * GIB, cpu_unit="s"):
        skus = [sku("Services CPU (Request-based billing)", "s", 0.5), sku("Services Memory (Request-based billing)", "GiBy.s", 1.0)]
        mon = lambda m, g, a: [] if "request_count" in m else [series(mem_value if "memory" in m else 10.0, location="europe-west8")]  # noqa: E731
        desc = lambda m: cpu_unit if "cpu" in m else mem_unit  # noqa: E731
        return self.ns["build_run_line"]("p", "t", 31, skus, mon_fetch=mon, now=NOW, desc_fetch=desc)

    def test_cloud_run_unita_memoria_convertite_in_gib_secondi(self):
        cases = [("GiBy.s", 2.0 * GIB, 2.0 * GIB), ("By.s", 2.0 * GIB, 2.0), ("GBy.s", 3.0, 3e9 / 2 ** 30),
                 ("MiBy.s", 2048.0, 2.0), ("KiBy.s", 2.0 * 2 ** 20, 2.0)]
        for unit, value, gib_s in cases:
            line = self._run_cost(unit, value)
            self.assertAlmostEqual(line["grossCostUsd"], 10 * 0.5 + gib_s * 1.0, delta=1e-3, msg=unit)
            self.assertEqual(line["estimateNote"], "", unit)

    def test_cloud_run_unita_cpu_con_annotazione(self):
        line = self._run_cost("GiBy.s", 0.0, cpu_unit="s{CPU}")
        self.assertAlmostEqual(line["grossCostUsd"], 10 * 0.5, delta=1e-6)
        self.assertEqual(line["estimateNote"], "")

    def test_cloud_run_unita_sconosciuta_o_lettura_fallita_fattore_uno_con_nota(self):
        line = self._run_cost("furlong", 7.0)
        self.assertAlmostEqual(line["grossCostUsd"], 10 * 0.5 + 7.0, delta=1e-6)
        self.assertIn("metric unit not verified", line["estimateNote"])

        def broken(m):
            raise RuntimeError("down")
        skus = [sku("Services Memory (Request-based billing)", "GiBy.s", 1.0)]
        mon = lambda m, g, a: [series(5.0, location="europe-west8")] if "memory" in m else []  # noqa: E731
        for d in (broken, lambda m: None):
            line = self.ns["build_run_line"]("p", "t", 31, skus, mon_fetch=mon, now=NOW, desc_fetch=d)
            self.assertAlmostEqual(line["grossCostUsd"], 5.0, delta=1e-6)
            self.assertIn("not verified", line["estimateNote"])

    def test_storage_e_bigquery_usano_la_media_non_il_picco(self):
        def spike(value_small, **labels):
            pts = [{"value": {"doubleValue": 10 * 1024.0 * GIB}}] + [{"value": {"doubleValue": value_small}} for _ in range(719)]
            return {"resource": {"labels": labels}, "metric": {"labels": labels}, "points": pts}
        mean_gib = (10 * 1024.0 + 719 * 1.0) / 720
        skus = [sku("Standard Storage Milan", "GiBy.mo", 0.02), sku("Active Logical Storage", "GiBy.mo", 0.02, ["eu"])]
        st = self.ns["build_storage_line"]("p", "t", 30, skus, now=NOW,
                                           mon_fetch=lambda m, g, a: [spike(GIB, location="europe-west8", storage_class="STANDARD")])
        bq = self.ns["build_bigquery_line"]("p", "t", 30, skus, now=NOW,
                                            mon_fetch=lambda m, g, a: [] if "scanned" in m else [spike(GIB, location="EU")])
        for line in (st, bq):
            self.assertAlmostEqual(line["grossCostUsd"], mean_gib * 0.02, delta=0.01)
            self.assertLess(line["grossCostUsd"], 10 * 1024 * 0.02 / 10)

    def test_artifact_registry_posizioni_in_cache_una_sola_chiamata(self):
        calls = []

        def fetch(url):
            calls.append(url)
            if url.split("?")[0].endswith("/locations"):
                return 200, {"locations": [{"locationId": "europe-west8"}]}
            return 200, {"repositories": []}
        for pid in ("p1", "p2", "p3"):
            self.ns["build_artifactregistry_line"](pid, "t", 31, [], fetch=fetch, now=NOW)
        self.assertEqual(sum(1 for u in calls if u.split("?")[0].endswith("/locations")), 1)

    def test_artifact_registry_errore_posizioni_non_viene_messo_in_cache(self):
        state = {"n": 0}

        def fetch(url):
            if url.split("?")[0].endswith("/locations"):
                state["n"] += 1
                return (500, {}) if state["n"] == 1 else (200, {"locations": [{"locationId": "x1"}]})
            return 200, {"repositories": []}
        self.assertEqual(self.ns["build_artifactregistry_line"]("p", "t", 31, [], fetch=fetch, now=NOW)["estimateStatus"], "unavailable")
        self.assertIsNone(self.ns["build_artifactregistry_line"]("p", "t", 31, [], fetch=fetch, now=NOW))

    def test_secret_manager_parallelo_rispetta_limite_50_e_note_errori(self):
        import threading
        lock, seen = threading.Lock(), []
        secrets = [{"name": f"projects/p/secrets/s{i}", "replication": {"automatic": {}}} for i in range(60)]

        def fetch(url):
            if "/versions" not in url:
                return 200, {"secrets": secrets}
            with lock:
                seen.append(url)
            return (403, {}) if "/s7/" in url else (200, {"versions": [{}]})
        line = self.ns["build_secretmanager_line"]("p", "t", 31, [sku("Secret version replica storage", "mo", 1.0)], fetch=fetch, now=NOW)
        self.assertEqual(len(seen), 50)
        self.assertAlmostEqual(line["grossCostUsd"], 49 * self.ns["_infra_month_fraction"](31 * 24.0), delta=1e-6)
        self.assertEqual(line["estimateStatus"], "partial")
        self.assertIn("s7", line["estimateNote"])
        self.assertIn("50", line["estimateNote"])

    def test_nessun_uso_nessuna_riga(self):
        empty = lambda m, g, a: []  # noqa: E731
        for fn in ("build_bigquery_line", "build_storage_line", "build_run_line"):
            self.assertIsNone(self.ns[fn]("p", "t", 31, [], mon_fetch=empty, now=NOW), fn)

    def test_permesso_negato_diventa_non_disponibile(self):
        line = self.ns["build_artifactregistry_line"]("p", "t", 31, [], fetch=lambda u: (403, {}), now=NOW)
        self.assertEqual(line["estimateStatus"], "unavailable")

    def test_entry_point_include_i_servizi_minori_e_salta_i_vuoti(self):
        skus = {k: [sku("Artifact Registry Storage", "GiBy.mo", 0.1)] for k in self.ns["INFRA_CATALOG_SERVICE_IDS"]}
        def fetch(u):
            if "artifactregistry" not in u:
                return 200, {}
            if u.split("?")[0].endswith("/locations"):
                return 200, {"locations": [{"locationId": "europe-west8"}]}
            return 200, {"repositories": [{"name": "projects/p/locations/europe-west8/repositories/r", "sizeBytes": str(GIB)}]}
        out = self.ns["build_infra_services_breakdown"]("p", "t", 31, {"artifactregistry.googleapis.com", "secretmanager.googleapis.com"},
                                                        fetch=fetch,
                                                        skus=skus, now=NOW)
        self.assertEqual([x["service"] for x in out], ["artifactregistry.googleapis.com"])

    def test_cache_catalogo_incompleta_viene_riscaricata(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            ns = self.ns
            ns["INFRA_CATALOG_CACHE_FILE"] = os.path.join(d, "c.json")
            import json
            with open(ns["INFRA_CATALOG_CACHE_FILE"], "w", encoding="utf-8") as f:
                json.dump({"fetchedAt": NOW.timestamp() + 10 ** 9, "skus": {"sql": [], "redis": [], "compute": []}}, f)
            ns["_infra_catalog_mem"]["skus"] = None
            calls = []

            def fetch(url):
                calls.append(url)
                return 200, {"skus": []}
            ns["get_infra_catalog"]("t", fetch=fetch)
            self.assertTrue(calls, "la cache vecchia (senza i servizi minori) doveva essere riscaricata")


if __name__ == "__main__":
    unittest.main()
