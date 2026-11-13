# Attribution and limits

What JanusTower can and cannot tell you. Read this before drawing conclusions about individual people.

## How usage is attributed

Usage comes from Cloud Monitoring metrics per project and model. To link it to a credential or a person, JanusTower correlates it with Cloud Audit Logs: API keys, service accounts, OAuth clients and user emails.

## What cannot be attributed

- **Shared OAuth client usage (for example an IDE such as Antigravity calling Vertex AI).** Without Data Access Audit Logs (`DATA_READ` / `DATA_WRITE`) for `aiplatform.googleapis.com`, the caller identity is not recorded. The usage is shown under a synthetic record `oauth-workload:<short client id>` ("OAuth Workload Vertex AI"), not under a person.
- **Usage with no audit trail at all** appears as `system:unattributed-audit-logs-disabled`, and the security posture raises the finding `AUDIT_LOGS_ATTRIBUTION_BLINDNESS`.
- **Known OAuth clients can be mapped to an owner by hand**: add entries to `oauthClientOwners` in `data/models_pricing_config.json` (client id to an owner email, or an object with `ownerEmail`, `displayName`, `tool`). It is empty by default and can only be edited on disk: the API refuses to change it and does not return it, because it is personal data.

To get per-person attribution, ask the project Owner to enable Data Access Audit Logs for `aiplatform.googleapis.com`. This adds Cloud Logging cost, and the logs contain user emails.

## Costs are estimates

Costs are not the invoice. They are token metrics times a rate table, with optional discount and cache-hit settings. Google does not report cached tokens in these metrics, and negotiated prices, credits and taxes are only reflected if you set them. Discounts and cache ratios can be calibrated on your invoice from the BigQuery billing export or a Billing CSV report, but there is no line-by-line reconciliation with the invoice. See [Cost calibration](cost-calibration.md).

## Other limits

- Missing IAM permissions on a project do not stop the scan; the **Projects & Permissions** view shows what is missing.
- Data is only as complete as the metrics and logs you can read; short retention windows limit history.
- Scan results can contain personal data (emails, Gemini Enterprise licenses, session metadata). Use **Delete local data** or remove the files in `data/` when you no longer need them.
