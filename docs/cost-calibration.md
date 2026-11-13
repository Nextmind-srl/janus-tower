# Cost estimation and calibration

> **Costs are estimates.** They are Cloud Monitoring token metrics multiplied by the rate table (see [Pricing & Rates](pricing-and-rates.md)). Check them against your Cloud Billing reports before taking financial decisions.

## Out-of-the-box defaults

Negotiated discount, committed-use credit and implicit cache hit all default to `0%`, so a fresh install never understates list cost. Non-global regional endpoints (`europe-*`, `asia-*`, ...) apply a `1.10x` multiplier unless the model defines explicit regional rates. The defaults live in `DEFAULT_BILLING_SETTINGS` (`backend/config.py`).

## Calibrating against your invoice

Open **FinOps > Pricing & Rates > Billing settings** to set your discount, cache-hit ratios, regional multiplier and per-model manual overrides. Overrides survive catalog syncs.

## Calibrating from the app (BigQuery or CSV)

In **Pricing & Rates > Billing settings > Cost calibration** there are three paths:

1. **BigQuery Billing Export.** Click *Detect & Calibrate from BigQuery*. The app looks for a `gcp_billing_export_v1_*` table in the projects you can read (or uses the table you type) and runs one `SELECT` over the last 30 days. It derives credit discounts, cache ratios and the regional multiplier and saves them locally.
   - **Cost:** a BigQuery query job is billed by Google like any query (usually a few cents, the query is filtered on the last 30 days). It needs permission to run query jobs on a project.
   - **Automatic runs:** *off by default*. If you tick *Also run it automatically during scans and syncs* and save, the same query runs during scans and price syncs, at most once a day. Without the option, scans and syncs never touch BigQuery and the calibration is only as fresh as your last manual run.
   - Values you edit by hand are not overwritten by automatic runs; clicking the button, or *Reset to defaults*, overrides them.
2. **Billing CSV upload.** Parsed in memory (English or Italian locale), never written to disk and no Google call.
3. **Manual parameters.** The fields below, as before.

After any of them the cached costs are recalculated at once, without a new scan.

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
