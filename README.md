# NearShift data engineering take-home: Olist analytics pipeline

This repository loads the public [Olist Brazilian E-Commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) into DuckDB, builds a small analytics model, reconciles it to the source, and answers the requested business questions. A standalone [showcase dashboard](showcase/index.html) presents the results without needing the database or an API key. The source covers historical orders from 2016–2018; it is not live NearShift data.

## Open the finished demo

Open [`showcase/index.html`](showcase/index.html) in a browser. The packaged page contains the verified summary data, an interactive monthly chart, category ranking, operational KPIs, five guided questions, and a presentation section covering architecture, technical decisions, and validation. It works offline after extracting the ZIP. A short presenter walkthrough is in [`DEMO.md`](DEMO.md). To enable free-text GPT questions on the same page, run the local server after the database is built:

```powershell
python showcase_server.py
```

Then open `http://127.0.0.1:8001/`. This optional feature uses the existing `OPENAI_API_KEY` and requires API credits. If credits are unavailable, the guided questions and every dashboard chart still work. The server binds only to `127.0.0.1`.

## Continue on another computer

Clone the [private GitHub repository](https://github.com/DanielDi/nearshift-data-engineer-takehome) and open `showcase/index.html` for an immediate offline demo:

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
python -m pip install -r requirements.txt
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
| `build_showcase.py`, `showcase/` | Standalone interactive dashboard generator, template and finished HTML |
| `showcase_server.py` | Local dashboard server with optional bounded GPT question endpoint |
| `DEMO.md` | Two-minute walkthrough for reviewers |
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
python assistant.py "¿Cuál fue el valor de mercancía entregada en noviembre de 2017?"
python assistant.py "¿Cuál fue el AOV del último mes disponible?"
python assistant.py "¿Cuál fue la tasa histórica de recompra?"
python assistant.py "¿Cuáles son las cinco categorías principales?"
python assistant.py "¿Qué porcentaje de entregas llegó tarde?"
```

The supported scope is monthly delivered merchandise value, monthly AOV, lifetime repeat-purchase rate, top five categories by delivered merchandise value, and overall late-delivery rate. Other questions, requests for customer records, arbitrary SQL and period filters unsupported by a metric are rejected. A monthly question needs `YYYY-MM` or an explicit request for the latest **available source month**. “Last month” means the previous calendar month, which may be absent from this historical source; it is never silently replaced with August 2018. Numeric answers always identify the curated source table and the Olist historical period. The API endpoint above remains usable without OpenAI for direct revenue queries.

Run all tests with `python -m unittest discover -s tests -v`. Unit tests use a fake model response and a temporary database, so they do not spend API credits. A live GPT call is needed to verify model routing in your OpenAI project.

## Findings and scope

See [`reports/INSIGHTS.md`](reports/INSIGHTS.md) for the five answers and charts. This implementation uses DuckDB and plain SQL to keep setup short and each transformation inspectable. It does not include an optional Metabase dashboard. With more time, I would add a scheduled refresh and CI check, investigate the payment discrepancies with refund records, and build a dashboard over the curated marts.

Dataset attribution: Olist, *Brazilian E-Commerce Public Dataset*, version 2, [Kaggle data card](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce). The Kaggle metadata lists a CC BY-NC-SA 4.0 license; raw data is downloaded at runtime instead of redistributed in this repository.
