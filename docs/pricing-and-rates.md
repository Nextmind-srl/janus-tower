# Pricing & Rates

The **FinOps > Pricing & Rates** view shows the rate catalog JanusTower uses to turn token counts into **estimated** cost. Rates are in USD per 1M tokens. The catalog is stored locally in `data/models_pricing_config.json`; the built-in fallback table is `MODEL_PRICING_PER_1M` in `backend/config.py` (its values are marked *not yet verified* in the code).

## Where the model list comes from

- The list comes from the Google APIs (Vertex AI Publisher Models).
- A Google model that the API no longer returns stays in the list with status **Deleted**, keeping its stored rates so that past days can still be valued.
- A non-Google model that no Google service returns anymore is removed.
- The list is never changed when the API answer is incomplete or fails. The result is recorded in `lastApiSync.listAuthoritative`.
- The sync tries several quota projects and records the one that answered (`lastApiSync.quotaProject`).

## Rates per modality

Per-model rates are read from the Cloud Billing Catalog (`cloudbilling.googleapis.com`) SKUs, split by modality (`text`, `image`, `audio`, `video`) and by service (Vertex AI and Gemini API), including regional variants and cache-read rates.

- A model without a catalog SKU is shown as **No catalog price**; no rate is guessed.
- When several SKUs compete for the same rate, the plainest standard one is used (no qualifier, not preview/experimental) and the slot is recorded as ambiguous if the competing prices differ.
- Non-token rates (per image, per video second) are shown but are not used in cost calculations.

## Sync

- Read-only. It uses the Cloud Billing Catalog API and the Vertex AI Publisher Models API.
- It runs automatically at most once per day, at the start of a scan, and can be started manually from the view (`POST /api/models-pricing/sync`).
- Errors and HTTP 429 answers are recorded in `lastApiSync.errors` and mark the sync as partial.
- If automatic USD to EUR is enabled (`usdToEurRateAuto`, default on), the EUR rate is read from the Cloud Billing Catalog; otherwise the manual `usdToEurRate` is used.

## Billing settings and overrides

Open **Pricing & Rates > Billing settings** (or edit `billingSettings` and `models` in `data/models_pricing_config.json`). Discounts default to zero; the Vertex AI implicit cache hit starts at a typical 93% (`DEFAULT_BILLING_SETTINGS` in `backend/config.py`). Calibrate both on your Cloud Billing export ([cost calibration](cost-calibration.md)):

| Setting | Default |
| :--- | :--- |
| `vertexBillingCreditDiscountPct`, `geminiApiBillingCreditDiscountPct` | `0` |
| `vertexImplicitCacheHitRatioPct` | `93` (share of Vertex AI input tokens billed at the cached-input rate) |
| `geminiApiImplicitCacheHitRatioPct` | `0` |
| `managedServiceSavingsPct` | `0` (managed AI services are billed per call: there is no cache-hit setting for them) |
| `regionalMultiplierDefault` | `1.10` (applied to non-global regional endpoints unless the model has explicit `regional_*` rates) |
| `usdToEurRate` / `usdToEurRateAuto` | `0.92` / `true` |

Values are validated against limits before being saved. Per-model manual overrides (`manualOverride`, source `MANUAL`) are preserved across catalog syncs. Budgets and overrides are saved locally and never pushed to Google Cloud.

## File safety

The pricing file is written atomically. An unreadable file is kept aside as `models_pricing_config.json.corrupt-<timestamp>`.

See also [Cost calibration](cost-calibration.md) and [Attribution and limits](attribution-and-limits.md).
