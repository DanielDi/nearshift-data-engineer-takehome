# NearShift data engineering take-home: Olist analytics pipeline

This repository loads the public [Olist Brazilian E-Commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) into DuckDB, builds a small analytics model, reconciles it to the source, and answers the requested business questions. A standalone [showcase dashboard](showcase/index.html) presents the results without needing the database or an API key. The source covers historical orders from 2016–2018; it is not live NearShift data.

## Open the finished demo

The hosted review demo is available at **https://nearshift-takehome-demo.onrender.com/**. Use the reviewer credentials provided separately. The deployed English dashboard supports direct MCP revenue queries and GPT questions. See [`deploy/RENDER.md`](deploy/RENDER.md) for deployment evidence and the temporary Free service limits.

Open [`showcase/index.html`](showcase/index.html) in a browser. The English interface has three views: **Overview** for metrics and charts, **Ask the data** for queries, and **Engineering** for architecture and validation. Query modes are separate tabs: **AI assistant**, **Revenue lookup** and **Offline examples**. The packaged page embeds its data, styles and scripts; all charts and offline examples work without services. It works offline after extracting the ZIP. Edit `showcase/template.html`, `showcase/dashboard.css` and `showcase/dashboard.js`, then run `python build_showcase.py` to regenerate the standalone HTML. Legacy links such as `#consultas` still open the matching view. A short presenter walkthrough is in [`DEMO.md`](DEMO.md). To enable free-text GPT questions on the same page, run the local server after the database is built:

```powershell
python showcase_server.py
```

Then open `http://127.0.0.1:8001/`. This optional feature uses the existing `OPENAI_API_KEY` and requires API credits. If credits are unavailable, the offline examples and every dashboard chart still work. The server binds only to `127.0.0.1`.

## Continue on another computer

Clone the [GitHub repository](https://github.com/DanielDi/nearshift-data-engineer-takehome) and open `showcase/index.html` for an immediate offline demo. The default `main` branch contains the complete submission:

```powershell
git clone https://github.com/DanielDi/nearshift-data-engineer-takehome.git
cd nearshift-data-engineer-takehome
```

To rebuild the pipeline on the new computer, install Python 3.11+ and run the commands in **Run end to end** below. The first pipeline run downloads the public Olist source again. The raw CSVs, DuckDB database, local virtual environment, ZIP package, and original assignment PDF are deliberately excluded from Git. Transfer the PDF separately if it is needed for review. Configure `OPENAI_API_KEY` separately on that computer if you want to use GPT; never commit it or a `.env` file.

If a remote is not available yet, transfer `NearShift_project.bundle` to the new computer and clone it with `git clone NearShift_project.bundle Prueba_NearShift`. The bundle contains the full Git history and source files; it does not contain the ignored database or PDF.

## Run end to end

Use Python 3.11 or newer. From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock.txt
python run.py
```

On macOS or Linux, activate the environment with `source .venv/bin/activate`. The first run downloads Olist dataset version 2 from Kaggle, extracts the seven CSVs used here, creates `data/nearshift.duckdb`, and regenerates `reports/` and `showcase/index.html`. Later runs reuse the CSVs. Use `python run.py --offline` to require local CSVs and avoid a network request. A successful run reports that every validation check passed; any failed critical check produces a nonzero exit code. Run `python build_showcase.py` to regenerate just the standalone page from an existing database and reports.

The source CSVs, archive, and database live under `data/` and are excluded from Git. The first download also records its SHA-256 and source URL in `data/source_manifest.json`. The generated reports and charts are included in the submission, so the findings can be read without downloading the dataset.

## Repository contents

| Path | Purpose |
|---|---|
| `run.py` | Download, raw load, model execution, validation, exports and charts |
| `api.py` and `api/openapi.json` | Local read-only revenue metric endpoint and OpenAPI schema |
| `assistant.py` | GPT question router for five approved metrics, backed by fixed curated queries |
| `metrics.py` | Shared read-only query service for HTTP, MCP and GPT |
| `metrics_mcp.py`, `metrics_client.py`, `metric_contract.py` | MCP stdio server, local bridge and structured revenue contract |
| `openai_policy.py` | Persistent daily API-attempt cap: SQLite locally, Postgres when hosted |
| `render.yaml`, `deploy/`, `hosting_policy.py` | Render Free build, authenticated HTTPS hosting and deployment guide |
| `requirements.lock.txt`, `.github/workflows/tests.yml` | Locked dependencies and offline CI checks |
| `build_showcase.py`, `showcase/` | Dashboard generator; separate HTML template, dashboard.css and dashboard.js; generated standalone index.html |
| `showcase_server.py` | Local dashboard server with optional bounded GPT question endpoint |
| `DEMO.md` | Three-minute walkthrough for reviewers |
| `tests/` | HTTP and assistant routing/guardrail tests |
| `sql/model.sql` | Typed facts/dimensions and curated marts |
| `reports/INSIGHTS.md` | Metric definitions, answers and charts |
| `reports/VALIDATION.md` | Source counts, automated checks and reconciliation |
| `reports/*.csv` | Monthly/category metrics and order-level payment exceptions |

## Data flow and grain

`Olist CSVs → raw.* (source columns as VARCHAR) → analytics facts/dimensions → analytics marts → reports`

The source files remain unchanged on disk. The raw database layer retains the source columns without business transformations; DuckDB's CSV reader represents blank fields as SQL `NULL`. Types and business rules are applied only in `analytics`.

| Table | Grain | Modeling decision |
|---|---|---|
| `analytics.dim_customer` | One `customer_unique_id` | `customer_id` is an order-specific identifier in Olist; repeat purchases require `customer_unique_id`. Location is omitted because it can vary across that customer's orders. |
| `analytics.dim_product` | One `product_id` | Uses English category translation where present, the original name as fallback, and `uncategorized` for missing names. |
| `analytics.fact_order` | One `order_id` | Stores status and typed lifecycle timestamps. |
| `analytics.fact_order_item` | One `(order_id, order_item_id)` | Stores merchandise price and freight separately. |
| `analytics.fact_payment` | One `(order_id, payment_sequential)` | Preserves multiple payment rows per order. |
| `analytics.mart_order` | One `order_id` | Aggregates items and payments independently before joining them to orders, preventing a many-to-many multiplication. |
| `analytics.mart_customer_repeat` | One `customer_unique_id` with a delivered order | Lifetime repeat flag. |
| `analytics.mart_monthly_metrics` | One purchase month | Delivered merchandise value, AOV and monthly repeat-buyer rate for every source month; `in_trend_window` marks months shown in the charts. |
| `analytics.mart_category_metrics` | One product category | Delivered merchandise value by category. |
| `analytics.mart_delivery` | One delivered order with actual and estimated dates | Late-delivery flag based on calendar dates. |

Orders, items, payments, customers, products, reviews and category translations are loaded. Reviews are kept in raw for traceability but are not needed for the five requested metrics; review IDs are not unique at the row grain. Seller and geolocation files are omitted because the selected metrics do not use them. In particular, the geolocation CSV has over one million rows and would add load time without improving these answers.

## Metric definitions

- **Revenue proxy:** delivered merchandise value = sum of item `price` on orders with `order_status = 'delivered'`, in BRL. This excludes freight and any refunds not observable in the dataset; it is not accounting revenue.
- **Monthly revenue and AOV:** assign delivered orders to their purchase month; AOV is monthly delivered merchandise value divided by delivered order count.
- **Lifetime repeat-purchase rate:** distinct `customer_unique_id` values with at least two delivered orders divided by those with at least one delivered order. The monthly repeat-buyer rate in the CSV uses active buyers with a prior delivered order, including orders before the displayed period.
- **Top categories:** sum delivered item prices by translated or fallback product category; missing categories are retained as `uncategorized` so totals reconcile.
- **Late-delivery rate:** delivered orders with actual delivery **date** after estimated delivery **date**, divided by delivered orders with both dates. Comparing timestamps would misclassify deliveries on the estimated day because estimated dates are stored at midnight.

The trend charts show January 2017 through August 2018. Source months before and after that range are exceptionally sparse; they remain in the raw, modeled and monthly mart tables and in `reports/monthly_metrics.csv`. All source timestamps are treated as naive local timestamps because the dataset does not document an offset.

## Validation and known differences

`run.py` checks source-to-model row counts, primary/composite key uniqueness, referential integrity, invalid numeric and purchase timestamp casts, raw-to-model monetary sums and order-level totals, and category/monthly revenue reconciliation. It writes the full result to [`reports/VALIDATION.md`](reports/VALIDATION.md).

Payments are reconciled against item price plus freight at the **order** grain. A mismatch greater than R$0.01 is reported in `reports/payment_exceptions.csv`, rather than silently corrected. Canceled and unavailable orders can still have payment records, and the dataset has no reliable refund ledger. Thus total payments should not be used as the revenue metric.

## Assistant-ready metric API (optional bonus)

After `python run.py`, start the local server:

```powershell
python api.py
```

The server listens only on `127.0.0.1:8000`. Its [OpenAPI schema](api/openapi.json) is also available at `http://127.0.0.1:8000/openapi.json` so an assistant with HTTP/OpenAPI tool support can call it. Example requests:

```text
GET http://127.0.0.1:8000/metrics/revenue?month=2017-11
GET http://127.0.0.1:8000/metrics/revenue/latest
GET http://127.0.0.1:8000/health
```

For November 2017, the first endpoint returns `"value": "987765.37"`, `"currency": "BRL"`, `"month": "2017-11"`, the metric definition and its source table. `latest` means the latest **historical month with delivered orders in this dataset** (August 2018), not the previous calendar month. A request for a month absent from the source returns 404 instead of fabricating a number. Months at the sparse source boundary are returned with `in_trend_window: false` and a coverage note.

Guardrails: the API accepts only a validated `YYYY-MM` month, uses a parameterized query against `analytics.mart_monthly_metrics`, exposes no arbitrary SQL or customer records, rejects write methods, and opens the database read-only. The response states the exact month, currency, definition and latest source purchase date. It binds to loopback and has no authentication or TLS; add both before exposing it beyond this machine. An assistant should use the returned month in its answer and should never describe these static Olist values as current NearShift revenue.

Run the HTTP tests with `python -m unittest discover -s tests -v`. The tests use a temporary modeled database; they do not need a fresh Olist download.

## GPT assistant for the requested metrics

`assistant.py` uses `gpt-6-luna` through the OpenAI Responses API to select one of five allowed metrics from a natural-language question. The model sees the question and metric descriptions, but does **not** receive the source CSVs, database contents, customer records or arbitrary SQL access. The application validates the selected metric and month, runs a fixed read-only query against the curated marts, and formats the answer from the returned values. The model's free-form text is never used as a numeric answer. The OpenAI API requires an API key and available API credits; its billing is separate from ChatGPT.

With `OPENAI_API_KEY` already set in your environment and `python run.py` completed:

```powershell
python assistant.py "What was the delivered merchandise value in November 2017?"
python assistant.py "What was the AOV in the latest available month?"
python assistant.py "What was the historical repeat purchase rate?"
python assistant.py "What were the top five categories?"
python assistant.py "What percentage of delivered orders arrived late?"
```

The interface, deterministic answers, errors and demo guide use English with en-US number/date formatting. Questions in other languages can still be routed to the same approved metrics.

The supported scope is monthly delivered merchandise value, monthly AOV, lifetime repeat-purchase rate, top five categories by delivered merchandise value, and overall late-delivery rate. Other questions, requests for customer records, arbitrary SQL and period filters unsupported by a metric are rejected. A monthly question needs `YYYY-MM` or an explicit request for the latest **available source month**. “Last month” means the previous calendar month, which may be absent from this historical source; it is never silently replaced with August 2018. Numeric answers always identify the curated source table and the Olist historical period. The API endpoint above remains usable without OpenAI for direct revenue queries.

Run all tests with `python -m unittest discover -s tests -v`. Unit tests use a fake model response and a temporary database, so they do not spend API credits. A live GPT call is needed to verify model routing in your OpenAI project.

## Findings and scope

See [`reports/INSIGHTS.md`](reports/INSIGHTS.md) for the five answers and charts. This implementation uses DuckDB and plain SQL to keep setup short and each transformation inspectable. It includes a standalone dashboard and an offline CI workflow, but no optional Metabase deployment. With more time, I would add a scheduled refresh and investigate payment discrepancies with refund records.

Dataset attribution: Olist, *Brazilian E-Commerce Public Dataset*, version 2, [Kaggle data card](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce). The Kaggle metadata lists a CC BY-NC-SA 4.0 license; raw data is downloaded at runtime instead of redistributed in this repository.

## Local MCP integration and governance

Start `python showcase_server.py` and open `http://127.0.0.1:8001/`. **Revenue lookup** queries DuckDB through a real MCP stdio subprocess without OpenAI or credits. Natural-language monthly revenue questions use OpenAI to select intent/month, then call the same MCP tool. AOV, repeat purchase, categories and late delivery use the shared `metrics.py` service; only revenue is exposed over MCP in contract v1.

```powershell
python metrics_client.py 2017-11
python metrics_client.py latest
python showcase_server.py
```

The client starts/stops `metrics_mcp.py` automatically. Another MCP host can start it with the virtual environment Python executable and absolute script path. `--db` is operator configuration, never a model argument. No API key belongs in MCP host configuration. `python metrics_mcp.py` is a protocol server, not an interactive prompt.

The sole tool is `get_monthly_revenue(month: str)`, requiring YYYY-MM or explicit `latest`. Structured output includes status, exact decimal amount as a string, BRL, month, delivered orders, definition, source table and historical coverage note. An absent month returns `month_unavailable`, not zero or the latest month. SQL is shared with the existing HTTP API. No SQL, raw-record, filesystem or write tool is exposed. Annotations describe behavior; fixed parameterized SQL and DuckDB read-only connections enforce it.

The official SDK is pinned to `mcp==2.3.0` and negotiates the protocol. The subprocess receives an OS environment allowlist and an empty `OPENAI_API_KEY`; it makes no OpenAI calls. Protocol messages use stdout and audit records stderr. Records contain request ID, tool, validated month, outcome, duration and contract version, never the key or full question. Capture logs outside Git with a short retention policy. `data/source_manifest.json` records source version/hash; Git identifies the code version. Rebuild before starting services; do not run database writers concurrently with readers.

OpenAI policy: `OPENAI_MODEL` defaults to `gpt-6-luna`; one model request and at most one metric call per question; 160 maximum output tokens; `store=False`; 30-second API timeout; no automatic retries; 20 API attempts per Bogota calendar day. `data/openai_usage.sqlite3` persists the counter across CLI/server restarts and processes; errors consume an attempt. This local demo limit is not a billing cap. MCP has a 20-second overall timeout. Dashboard POST requests require its loopback Host and same Origin when supplied; CORS is not enabled.

Use a dedicated OpenAI project with only model-request permissions and model-list read if needed. Administrative credentials remain outside the application. Rotate keys exposed in chat, confirm the owner's email in Platform, and set expiry. Keep the key outside Git/frontend and only in the assistant parent process. A USD 5 monthly hard spend limit and alerts at 50%/80% are recommended **Platform settings, not configured by this repository**. `store=False` does not establish Zero Data Retention. No raw Olist/customer records are sent to OpenAI.

CI runs locked dependencies and fixture-backed tests on Python 3.13, Windows and Linux, without keys, downloads or API costs. Tests exercise real MCP discovery/calls, invalid/missing/extra arguments, unknown tools, output validation, shared-service values, database immutability, dashboard integration and the persistent daily cap. Remote CI still needs a push; a local pass alone is not a remote CI result.

Hosted Responses MCP cannot directly reach this stdio process: this application uses a local bridge. Native remote MCP, OAuth or Secure MCP Tunnel is a separate deployment decision. No public service or Platform administration is required for this take-home.

## Temporary hosting on Render Free

The tested hosting configuration is in [`render.yaml`](render.yaml); follow [`deploy/RENDER.md`](deploy/RENDER.md) for setup and acceptance checks. It builds a compact read-only metrics snapshot and serves the English dashboard behind reviewer authentication. Render handles HTTPS and the public port; exact origin validation remains enabled. A separate free Postgres instance persists the daily API-attempt counter across web-service restarts and expires after 30 days. Hosted AI fails closed without that counter. No paid upgrade or automatic deletion is configured. Publishing the configuration alone does not prove a live deployment or live Postgres persistence.
