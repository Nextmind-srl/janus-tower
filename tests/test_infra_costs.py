"""Costi fissi dell'infrastruttura (Cloud SQL, Redis, Compute) stimati da risorse e catalogo: dati e risposte inventati.

Prezzi unitari inventati e tondi: i test controllano l'aritmetica (quantita x prezzo x ore), nessun dato di un cliente.
"""

import os
import tempfile
import unittest
from datetime import datetime, timezone

import server

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
REG = ["europe-west8"]


def load_app_namespace() -> dict:
    ns = {"__name__": "janustower_test", "__file__": server.__file__}
    server.load_backend_modules(ns)
    ns["get_billing_settings"] = lambda: {"infraSavingsPct": 0.0}
    ns["get_usd_to_eur_rate"] = lambda: 0.92
    return ns


def sku(desc, unit, price, regions=REG):
    return {"d": desc, "u": unit, "p": price, "r": regions}


SQL_SKUS = [
    sku("Cloud SQL for PostgreSQL: Zonal - Enterprise Plus N vCPU in Milan", "h", 0.05),
    sku("Cloud SQL for PostgreSQL: Zonal - Enterprise Plus N RAM in Milan", "GiBy.h", 0.01),
    sku("Cloud SQL for PostgreSQL: Zonal - Enterprise Plus Standard Storage in Milan", "GiBy.mo", 0.2),
    sku("Cloud SQL for PostgreSQL: Zonal - Enterprise Plus Data Cache Storage in Milan", "GiBy.mo", 0.16),
    sku("Cloud SQL: Backups in Milan", "GiBy.mo", 0.08),
]
REDIS_SKUS = [sku("Redis Capacity Basic M1 Milan", "GiBy.h", 0.05), sku("Redis Capacity Standard M1 Milan", "GiBy.h", 0.1)]
GCE_SKUS = [
    sku("Static Ip Charge", "h", 0.01),
    sku("E2 Instance Core running in Milan", "h", 0.02),
    sku("E2 Instance Ram running in Milan", "GiBy.h", 0.003),
    sku("Balanced PD Capacity in Milan", "GiBy.mo", 0.12),
]

SQL_EXPECTED = 2 * 744 * 0.05 + 16 * 744 * 0.01 + 100 * 0.2 + 375 * 0.16
SQL_INSTANCE = {
    "name": "demo-db", "region": "europe-west8", "databaseVersion": "POSTGRES_17", "createTime": "2026-01-01T00:00:00Z",
    "settings": {"tier": "db-perf-optimized-N-2", "edition": "ENTERPRISE_PLUS", "availabilityType": "ZONAL",
                 "dataDiskSizeGb": "100", "dataDiskType": "PD_SSD", "dataCacheConfig": {"dataCacheEnabled": True}},
}


class TestInfraCosts(unittest.TestCase):
    def setUp(self):
        self.ns = load_app_namespace()

    def test_cloud_sql_ritrova_il_listino_dell_export(self):
        cost, why = self.ns["estimate_sql_instance"](SQL_INSTANCE, SQL_SKUS, 31, NOW, cache_gib=375.0)
        self.assertEqual(why, "")
        self.assertAlmostEqual(cost, SQL_EXPECTED, delta=0.01)

    def test_cloud_sql_senza_prezzo_non_e_stimabile_e_non_zero(self):
        cost, why = self.ns["estimate_sql_instance"](SQL_INSTANCE, [s for s in SQL_SKUS if "RAM" not in s["d"]], 31, NOW)
        self.assertIsNone(cost)
        self.assertIn("RAM", why)

    def test_cloud_sql_tier_condiviso_non_supportato(self):
        inst = dict(SQL_INSTANCE, settings={"tier": "db-f1-micro"})
        cost, why = self.ns["estimate_sql_instance"](inst, SQL_SKUS, 31, NOW)
        self.assertIsNone(cost)
        self.assertIn("unsupported", why)

    def test_cloud_sql_istanza_spenta_paga_solo_disco(self):
        inst = {**SQL_INSTANCE, "settings": {**SQL_INSTANCE["settings"], "activationPolicy": "NEVER", "dataCacheConfig": {}}}
        cost, _ = self.ns["estimate_sql_instance"](inst, SQL_SKUS, 31, NOW)
        self.assertAlmostEqual(cost, 100 * 0.2, delta=0.01)

    def test_data_cache_reale_dalla_metrica_quota(self):
        series = [{"resource": {"labels": {"database_id": "demo:demo-db"}},
                   "points": [{"value": {"int64Value": str(375 * 2 ** 30)}}, {"value": {"int64Value": str(375 * 2 ** 30)}}]}]
        q = self.ns["fetch_sql_data_cache_quota_gib"]("demo", "tok", 31, fetch=lambda: series, now=NOW)
        self.assertEqual(q, {"demo-db": 375.0})
        body = {"items": [SQL_INSTANCE]}
        line = self.ns["build_sql_line"]("demo", "tok", 31, SQL_SKUS, fetch=lambda u: (200, body), now=NOW,
                                         cache_fetch=lambda: series)
        self.assertAlmostEqual(line["grossCostUsd"], SQL_EXPECTED, delta=0.01)
        self.assertNotIn("stimata", line["note"])

    def test_data_cache_senza_metrica_usa_stima_dichiarata(self):
        body = {"items": [SQL_INSTANCE]}
        line = self.ns["build_sql_line"]("demo", "tok", 31, SQL_SKUS, fetch=lambda u: (200, body), now=NOW,
                                         cache_fetch=lambda: [])
        self.assertIn("Data Cache size estimated", line["note"])
        self.assertGreater(line["grossCostUsd"], 0)

    def test_data_cache_metrica_in_errore_non_rompe(self):
        def boom():
            raise RuntimeError("x")
        self.assertEqual(self.ns["fetch_sql_data_cache_quota_gib"]("d", "t", 31, fetch=boom, now=NOW), {})

    def test_ip_globale_senza_regione_trova_il_prezzo(self):
        addr = {"name": "ip-globale", "addressType": "EXTERNAL", "status": "RESERVED", "creationTimestamp": "2026-01-01T00:00:00Z"}
        cost, why = self.ns["_gce_address_cost"](addr, GCE_SKUS, 31, NOW)
        self.assertEqual(why, "")
        self.assertAlmostEqual(cost, 744 * 0.01, delta=0.01)

    def test_motivo_non_stimabile_resta_nella_riga(self):
        inst = dict(SQL_INSTANCE, settings={"tier": "db-g1-small"})
        line = self.ns["build_sql_line"]("demo", "tok", 31, SQL_SKUS, fetch=lambda u: (200, {"items": [inst]}), now=NOW)
        self.assertEqual(line["estimateStatus"], "not_estimable")
        self.assertIn("db-g1-small", line["estimateNote"])
        self.assertIn("db-g1-small", line["details"])

    def test_vm_e2_condivise_e_n1_custom_e_legacy(self):
        skus = GCE_SKUS + [sku("Custom Instance Core running in Milan", "h", 0.04), sku("Custom Instance Ram running in Milan", "GiBy.h", 0.005),
                           sku("N2 Custom Instance Core running in Milan", "h", 0.09), sku("Micro Instance with burstable CPU running in Milan", "h", 0.01)]
        base = {"zone": "x/europe-west8-a", "creationTimestamp": "2026-01-01T00:00:00Z"}
        cost, why = self.ns["_gce_instance_cost"](dict(base, machineType="x/e2-medium"), skus, 31, NOW)
        self.assertEqual(why, "")
        self.assertAlmostEqual(cost, (1.0 * 0.02 + 4.0 * 0.003) * 744, delta=0.01)
        cost, _ = self.ns["_gce_instance_cost"](dict(base, machineType="x/n1-custom-4-8192"), skus, 31, NOW)
        self.assertAlmostEqual(cost, (4 * 0.04 + 8 * 0.005) * 744, delta=0.01)  # non prende lo SKU N2 custom
        cost, _ = self.ns["_gce_instance_cost"](dict(base, machineType="x/f1-micro"), skus, 31, NOW)
        self.assertAlmostEqual(cost, 0.01 * 744, delta=0.01)

    def test_un_builder_che_solleva_non_ferma_il_progetto(self):
        bad = {"items": [{"name": "x", "region": "europe-west8", "databaseVersion": "POSTGRES_17",
                          "settings": {"tier": "db-perf-optimized-N-2", "edition": "ENTERPRISE_PLUS", "dataDiskSizeGb": "non-un-numero"}}]}
        out = self.ns["build_infra_services_breakdown"]("p", "t", 30, {"sqladmin.googleapis.com"},
                                                        fetch=lambda u: (200, bad), skus={"sql": SQL_SKUS}, now=NOW)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["estimateStatus"], "unavailable")
        self.assertIn("ValueError", out[0]["note"])

    def test_redis_basic_1gb(self):
        inst = {"name": "projects/p/locations/europe-west8/instances/cache", "tier": "BASIC", "memorySizeGb": 1,
                "createTime": "2026-01-01T00:00:00Z"}
        cost, why = self.ns["estimate_redis_instance"](inst, REDIS_SKUS, 31, NOW)
        self.assertEqual(why, "")
        self.assertAlmostEqual(cost, 744 * 0.05, delta=0.01)

    def test_compute_ip_statico_e_disco(self):
        responses = {
            "instances": {"items": {}},
            "disks": {"items": {"zones/europe-west8-a": {"disks": [
                {"name": "d1", "zone": "x/europe-west8-a", "type": "x/pd-balanced", "sizeGb": "100", "creationTimestamp": "2026-01-01T00:00:00Z"}]}}},
            "addresses": {"items": {"regions/europe-west8": {"addresses": [
                {"name": "ip1", "addressType": "EXTERNAL", "status": "RESERVED", "region": "x/europe-west8",
                 "creationTimestamp": "2026-01-01T00:00:00Z"}]}}},
        }
        fetch = lambda url: (200, next(v for k, v in responses.items() if f"/{k}?" in url))  # noqa: E731
        line = self.ns["build_compute_line"]("demo", "tok", 31, GCE_SKUS, fetch=fetch, now=NOW)
        self.assertEqual(line["estimateStatus"], "ok")
        self.assertAlmostEqual(line["grossCostUsd"], 744 * 0.01 + 100 * 0.12, delta=0.01)

    def test_compute_vm_e2_standard(self):
        vm = {"name": "vm1", "status": "RUNNING", "zone": "x/europe-west8-a", "machineType": "x/e2-standard-2",
              "creationTimestamp": "2026-01-01T00:00:00Z"}
        cost, why = self.ns["_gce_instance_cost"](vm, GCE_SKUS, 31, NOW)
        self.assertEqual(why, "")
        self.assertAlmostEqual(cost, (2 * 0.02 + 8 * 0.003) * 744, delta=0.05)

    def test_permesso_negato_diventa_non_disponibile(self):
        line = self.ns["build_sql_line"]("demo", "tok", 31, SQL_SKUS, fetch=lambda url: (403, {}), now=NOW)
        self.assertEqual(line["estimateStatus"], "unavailable")
        self.assertEqual(line["costUsd"], 0.0)
        self.assertIn("permission", line["note"])

    def test_sconto_percentuale_locale(self):
        self.ns["get_billing_settings"] = lambda: {"infraSavingsPct": 40.0}
        body = {"items": [SQL_INSTANCE]}
        line = self.ns["build_sql_line"]("demo", "tok", 31, SQL_SKUS, fetch=lambda url: (200, body), now=NOW)
        self.assertAlmostEqual(line["costUsd"], line["grossCostUsd"] * 0.6, delta=0.01)
        self.assertAlmostEqual(line["savingsUsd"], line["grossCostUsd"] * 0.4, delta=0.01)

    def test_senza_servizi_abilitati_nessuna_riga_e_nessuna_chiamata(self):
        calls = []
        out = self.ns["build_infra_services_breakdown"]("demo", "tok", 30, {"aiplatform.googleapis.com"},
                                                        fetch=lambda u: calls.append(u), skus={"sql": SQL_SKUS})
        self.assertEqual(out, [])
        self.assertEqual(calls, [])

    def test_catalogo_assente_non_diventa_zero(self):
        out = self.ns["build_infra_services_breakdown"]("demo", "tok", 30, {"redis.googleapis.com"}, skus={})
        self.assertEqual(out[0]["estimateStatus"], "unavailable")

    def test_catalogo_usa_la_cache_su_disco_se_l_api_fallisce(self):
        with tempfile.TemporaryDirectory() as d:
            self.ns["INFRA_CATALOG_CACHE_FILE"] = os.path.join(d, "c.json")
            self.ns["_infra_catalog_mem"]["skus"] = None
            raw = {"skus": [{"description": "Redis Capacity Basic M1 Milan", "serviceRegions": REG,
                             "pricingInfo": [{"pricingExpression": {"usageUnit": "GiBy.h", "tieredRates": [{"unitPrice": {"units": "0", "nanos": 50000000}}]}}]}]}
            ok = self.ns["get_infra_catalog"]("tok", fetch=lambda url: (200, raw))
            self.assertEqual(len(ok["redis"]), 1)
            self.ns["_infra_catalog_mem"]["skus"] = None  # la cache in memoria e' vuota: legge il file
            again = self.ns["get_infra_catalog"]("tok", fetch=lambda url: (500, {}))
            self.assertEqual(again["redis"][0]["d"], "Redis Capacity Basic M1 Milan")


if __name__ == "__main__":
    unittest.main()
