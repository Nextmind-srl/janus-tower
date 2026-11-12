# Cost estimation and calibration

> **Costs are estimates.** They are Cloud Monitoring token metrics multiplied by the rate table (see [Pricing & Rates](pricing-and-rates.md)). Check them against your Cloud Billing reports before taking financial decisions.

## Out-of-the-box defaults

Negotiated discount, committed-use credit and implicit cache hit all default to `0%`, so a fresh install never understates list cost. Non-global regional endpoints (`europe-*`, `asia-*`, ...) apply a `1.10x` multiplier unless the model defines explicit regional rates. The defaults live in `DEFAULT_BILLING_SETTINGS` (`backend/config.py`).

## Calibrating against your invoice

Open **FinOps > Pricing & Rates > Billing settings** to set your discount, cache-hit ratios, regional multiplier and per-model manual overrides. Overrides survive catalog syncs.

## Helper: `tools/calibra_da_csv.py`

1. Export the Cloud Billing report grouped by SKU as CSV (Italian locale: decimal comma, dot as thousands separator). Keep the file in `data/`, which is ignored by Git.
2. Run:

```bash
python tools/calibra_da_csv.py data/report.csv
# several months: pass the files in chronological order
python tools/calibra_da_csv.py data/oct.csv data/nov.csv
```

Options: `--pricing` (pricing file, default the local one), `--out` (default `data/calibration_proposal.json`), `--min-list-eur`.

The tool is read-only and plain arithmetic (no AI). It derives:

- credit discount per service (Vertex AI, Gemini API);
- cache-hit ratio per model;
- regional multiplier (regional vs. global unit price);
- USD to EUR rate (EUR unit price in the invoice vs. USD catalog price).

It prints a **proposal** to enter by hand in Billing settings; it never changes a setting. Because Google does not report cached tokens, re-run it when your workload changes. Only aggregated numbers are printed.
