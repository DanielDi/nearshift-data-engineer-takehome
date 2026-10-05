# Demo walkthrough (3 minutes)

The entire application and its metric answers use English. The data is a historical Olist snapshot from 2016–2018, not current NearShift business data.

1. Open the [hosted review demo](https://nearshift-takehome-demo.onrender.com/) with the reviewer credentials provided separately. Alternatively, open [`showcase/index.html`](showcase/index.html) for an offline demo, or start `python showcase_server.py` and open `http://127.0.0.1:8001/` for local queries.
2. In **Overview**, show the full-dataset metrics: R$ 13,221,498.11 in delivered merchandise, 96,478 delivered orders, R$ 137.04 AOV and 3.00% repeat purchase rate. Merchandise value excludes freight and unobserved refunds; it is a revenue proxy.
3. Switch the chart between **Value** and **AOV**. Use **Inspect month** to select November 2017: R$ 987,765.37 across 7,289 delivered orders. Explain that this selection only changes the chart detail, while the four headline metrics retain their full-dataset scope. Sparse boundary months remain in the mart and CSV.
4. Show the category ranking and the 6.77% late-delivery rate. Its denominator includes only delivered orders with comparable actual and estimated dates.
5. Open **Ask the data**. In **Offline examples**, select a metric to show its definition, denominator where applicable and curated source table. These examples work without a server or API credits; the month selector affects only monthly value and AOV.
6. With the local server running, switch to **Revenue lookup**. November 2017 returns R$ 987,765.37 through a real MCP tool backed by DuckDB, using no OpenAI credits. **Latest available month** returns August 2018. Try `2026-09` to demonstrate explicit no-data handling.
7. If API credits are available, open **AI assistant**, click **November 2017 value** to fill the example, then click **Ask the assistant**. GPT selects an intent and month; monthly merchandise value goes through MCP. The application formats the verified result in English. The other four metrics use the shared service with fixed SQL. Unsupported requests and missing months receive explicit responses.
8. Open **Engineering**. Follow the five pipeline stages, inspect the validation evidence and expand two decisions: independent item/payment aggregation prevents duplicate amounts; customer_unique_id enables repeat purchase measurement. Open `reports/VALIDATION.md` for all 25 checks and explain the 303 retained payment exceptions.

## What the solution demonstrates

- Reproducible ingestion and explicit grains for orders, items and payments.
- Shared metric definitions with documented differences from accounting payments.
- Automated validation before generating reports and the dashboard.
- A standalone deliverable with separately maintained HTML, CSS and JavaScript.
- Bounded queries, a read-only MCP tool and optional natural-language routing through OpenAI.

## One-minute technical explanation

Operational CSVs mix order, item and payment grains. The pipeline preserves the source, applies types and explicit business definitions, and creates reconciled marts. The reports, dashboard and query service use these same definitions. GPT interprets the question; the database supplies the numbers. The deliverable makes historical coverage and unresolved payment exceptions visible.
