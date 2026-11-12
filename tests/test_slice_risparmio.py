"""D3 - il ritaglio del periodo conserva lordo e risparmio quando il netto originale e' 0 (dati inventati, nessuna rete)."""

import unittest
from datetime import datetime, timedelta

import server


def load_app_namespace() -> dict:
    ns = {"__name__": "janustower_test", "__file__": server.__file__}
    server.load_backend_modules(ns)
    return ns


DAYS = [(datetime(2026, 10, 30) - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)]


def payload(net: float, sav: float) -> dict:
    """30 giorni, uso uniforme; netto e risparmio totali distribuiti sui giorni."""
    n = len(DAYS)
    daily = {d: {"requests": 10, "inferenceRequests": 10, "tokens": 100, "totalTokens": 100,
                 "invocations": 10, "costUsd": net / n, "otherAiCostUsd": net / n} for d in DAYS}
    return {
        "days": 30, "scannedAt": "2026-10-30T12:00:00Z",
        "projects": [{
            "dailySeries": dict(daily), "totalRequests": 300, "inferenceRequests": 300, "totalTokens": 3000,
            "estimatedCostUsd": net, "otherAiCostUsd": net, "otherAiCacheSavingsUsd": sav,
            "otherAiGrossCostUsd": net + sav,
            "models": [{"dailySeries": dict(daily), "costUsd": net, "cacheSavingsUsd": sav, "grossCostUsd": net + sav}],
            "credentialsUsage": [{"credentialId": "c1", "dailySeries": dict(daily), "estimatedCostUsd": net,
                                  "cacheSavingsUsd": sav, "grossCostUsd": net + sav}],
        }],
    }


class TestSliceRisparmio(unittest.TestCase):
    def setUp(self) -> None:
        self.fn = load_app_namespace()["slice_cached_payload_for_days"]

    def _slice(self, net, sav, days=7, **kw):
        return self.fn(payload(net, sav), days, {}, **kw)["projects"][0]

    def _check(self, p, sav_expected, net_expected):
        for obj, net_k, sav_k, gross_k in (
            (p, "otherAiCostUsd", "otherAiCacheSavingsUsd", "otherAiGrossCostUsd"),
            (p["models"][0], "costUsd", "cacheSavingsUsd", "grossCostUsd"),
            (p["credentialsUsage"][0], "estimatedCostUsd", "cacheSavingsUsd", "grossCostUsd"),
        ):
            self.assertAlmostEqual(obj[net_k], net_expected, places=3)
            self.assertAlmostEqual(obj[sav_k], sav_expected, places=3)
            self.assertAlmostEqual(obj[gross_k], sav_expected + net_expected, places=3)
            self.assertAlmostEqual(obj[gross_k] - obj[sav_k], obj[net_k], places=3)

    def test_netto_zero_proporzionale_ai_giorni(self) -> None:
        self._check(self._slice(0.0, 30.0), 7.0, 0.0)

    def test_netto_positivo_formula_invariata(self) -> None:
        # risparmio 30 * (netto finestra 3.5 / netto originale 15) = 7.0
        self._check(self._slice(15.0, 30.0), 7.0, 3.5)

    def test_finestra_senza_giorni_tutto_zero(self) -> None:
        self._check(self._slice(0.0, 30.0, start_date="2027-01-01", end_date="2027-01-01"), 0.0, 0.0)

    def test_nessun_risparmio_resta_zero(self) -> None:
        self._check(self._slice(0.0, 0.0), 0.0, 0.0)

    def test_netto_zero_con_consumo_non_uniforme_usa_i_token_non_i_giorni(self) -> None:
        # Ultimi 7 giorni: 300 token/giorno (2100); gli altri 23 giorni: 50 token/giorno (1150).
        # Quota di token della finestra = 2100 / 3250; se si usassero i giorni sarebbe 7/30.
        pl = payload(0.0, 30.0)
        for i, d in enumerate(DAYS):
            tok = 300 if i < 7 else 50
            for series in (pl["projects"][0]["dailySeries"], pl["projects"][0]["models"][0]["dailySeries"],
                           pl["projects"][0]["credentialsUsage"][0]["dailySeries"]):
                series[d] = dict(series[d], tokens=tok, totalTokens=tok)
        p = self.fn(pl, 7, {})["projects"][0]
        expected = 30.0 * 2100 / 3250
        self.assertNotAlmostEqual(expected, 7.0, places=1)
        self._check(p, expected, 0.0)


if __name__ == "__main__":
    unittest.main()
