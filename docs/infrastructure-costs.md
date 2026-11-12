# Infrastructure costs (estimates)

JanusTower adds the **fixed cost of the infrastructure behind your AI workloads** to the AI cost: databases, caches, VMs and
a few smaller services. Nothing is read from your invoice and no amount is hard-coded: for each project it **reads the
resources** (read-only) and **prices them from the public Cloud Billing Catalog** (list price, USD).

Only projects with a real AI workload are evaluated (same threshold as the "non-AI" exclusion), so unrelated infrastructure
projects do not trigger extra API calls.

| Service | What is read | How it is priced |
| :--- | :--- | :--- |
| **Cloud SQL** | Instances (Cloud SQL Admin API): tier, edition, HA, disk, region. Data cache size: `database/data_cache/quota` metric. | vCPU-hours, GiB RAM-hours, disk and data cache GiB-months |
| **Memorystore for Redis** | Instances (Memorystore API): tier, memory, region | GiB-hours by tier and capacity class (M1-M5) |
| **Compute Engine** | Running VMs (predefined and custom), persistent disks, external IP addresses | Core and RAM hours, disk GiB-months, IP hours |
| **Artifact Registry** | Repository sizes (`sizeBytes`) | GiB-months |
| **Secret Manager** | Active secret versions and replicas | Version replicas per month |
| **BigQuery** | Monitoring: `query/scanned_bytes_billed`, `storage/stored_bytes` | TiB analysed, active logical GiB-months |
| **Cloud Storage** | Monitoring: `storage/total_bytes` by class and location | GiB-months (no operations, no egress) |
| **Cloud Run** | Monitoring: CPU and memory allocation time, request count | Request-based billing SKUs |

## What the numbers mean

- **List price.** Your negotiated discounts and committed-use discounts are not visible to the tool. Set
  **Pricing & Rates → Infrastructure savings (%)** to model them (0 by default).
- **Hours.** A resource is assumed to run for the whole window, or since its creation. Storage volumes (BigQuery, Cloud Storage) use the **average** of the readings over the window, not the peak.
- **Cloud Run** memory/CPU allocation time is converted to GiB-seconds / vCPU-seconds from the unit declared by the metric; if the unit cannot be read the line says so.
- **Not included:** backups, network egress, licences, sustained-use discounts, the free tiers of the smaller services
  (they are shared at billing-account level, so those lines are an upper bound).
- **Cloud Monitoring, Cloud Logging and Cloud Trace are not estimated** (ingestion volumes with a free allowance shared by the
  whole billing account).

## When a line cannot be computed

The line says so instead of showing 0:

- *Dati non disponibili: permesso mancante o API non abilitata*: the project does not grant the read permission or the API is
  off (`cloudsql.instances.list`, `redis.instances.list`, `compute.instances.list`, ...).
- *non stimabile*: a resource type is not supported (for example shared-core Cloud SQL tiers) or its price was not found in the
  catalog. The note names the resource and the reason.
- *stima parziale*: some resources were priced and some were not.

The catalog is cached for 7 days in `data/infra_catalog_cache.json` (git-ignored).
