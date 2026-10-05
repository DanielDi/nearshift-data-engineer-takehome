# Render Free evaluation deployment

This is a short-lived, authenticated demo. The Python web service and usage-counter Postgres instance both explicitly use `plan: free`. No persistent disk, paid plan, custom domain or automatic redeployment is configured. OpenAI calls are billed separately.

## Deployment configuration

The repository root [`render.yaml`](../render.yaml) is a Render Blueprint. It deploys branch `feat/mcp-metrics` without modifying `main`:

| Resource | Configuration |
|---|---|
| Web service | Python 3.13.2, Free, Oregon |
| Build | Locked dependencies, full Olist pipeline, 25 validation checks, compact serving database, standalone HTML |
| Start | `python showcase_server.py --db data/serving.duckdb --skip-build` |
| Network | `0.0.0.0:$PORT`, Render-managed HTTPS, exact Host/origin checks |
| Access | HTTP Basic over HTTPS; username `reviewer`, Render-generated password |
| Persistent counter | Render Postgres Free in the same region, internal TLS connection, external access disabled |
| GPT | 20 attempts per Bogota calendar day; single model request; no automatic retries |

The build downloads public Olist version 2 and regenerates the model and reports. It fails if a critical validation fails. DuckDB has a 256 MB build memory budget and one query thread. The serving database contains monthly/category aggregates, anonymous eligible-row flags for exact repeat/delivery denominators, and the latest observed purchase timestamp. It contains no order/customer identifiers. Packaging compares all five metric results to the full model before serving. The original CSVs and database are never committed.

The serving snapshot is produced during **build**, so waking the service does not download or remodel data. The standalone HTML is also built once. Runtime writes only usage reservations to Postgres. Local SQLite remains the default for the local CLI/server; hosted GPT never falls back to temporary SQLite.

## Publish

1. Publish the tested branch to the private repository with Daniel's explicit commit/push approval.
2. Connect Render to GitHub with access only to this private repository. Create a new Blueprint using `render.yaml` on branch `feat/mcp-metrics`.
3. Review that both resources say **Free** before creating them. If a free database is unavailable in the account, stop; do not silently choose a paid tier. The web app can still serve direct MCP/offline queries without GPT.
4. Render creates `DEMO_PASSWORD` and the internal `OPENAI_USAGE_DATABASE_URL` automatically. Retrieve the reviewer password privately from the service's environment settings; never put it in Git, URLs or logs.
5. Confirm the unauthenticated `/health` endpoint and authenticated dashboard/MCP checks below. Then enter `OPENAI_API_KEY` privately in Render's secret environment settings and redeploy. The key is not in the Blueprint or application frontend, and the MCP subprocess receives no API key or database credential.
6. Verify one actual English GPT question. Share the URL and reviewer access separately with the evaluator only when Daniel requests it.

The public origin comes from Render's `RENDER_EXTERNAL_URL`. For a custom domain, an operator must configure `APP_PUBLIC_URL` to the exact HTTPS origin; custom-domain deployment is outside this configuration. Do not disable origin checks or access protection.

## Acceptance checks

- `/health` responds with only `{"status":"ok"}` without authentication.
- Dashboard, documentation, `/api/status`, `/api/revenue` and `/api/ask` require reviewer authentication.
- Incorrect Host, cross-origin POST and a missing HTTPS proxy header are rejected. No CORS access is enabled.
- November 2017: **R$ 987,765.37 / 7,289 delivered orders** through MCP.
- Latest available month: **August 2018 / R$ 838,576.64 / 6,351 orders**.
- `2026-09` returns no data, never zero or a substituted historical month.
- AI answers identify the curated source and use English; raw records, arbitrary SQL and unsupported requests are rejected.
- The real Postgres reservation is atomic. Confirm counter persistence after a service restart and concurrent reservations in a separate test database before calling remote governance verified. Unit tests do not prove live database availability or remote persistence.
- Counter connection failure/expiry prevents an OpenAI request; direct MCP and offline examples remain available while the existing web process is running. Startup with a configured unavailable counter fails its deploy rather than serving a false-ready AI instance.
- Only one metric query runs at a time to bound concurrent MCP processes on the Free instance.

## Expiry and costs

Render Free web services sleep after 15 minutes without traffic and can take about a minute to wake. The filesystem is temporary, and free services may restart. The persistent usage counter therefore lives in Postgres rather than the service filesystem.

**Render Postgres Free expires 30 days after creation.** Record its real expiry after provisioning. This configuration does not create an automatic deletion schedule and does not purchase an upgrade. Before expiry, finish the evaluation and suspend the web service/revoke the dedicated demo API key, or explicitly choose another persistence option. Deleting provider resources requires a separate user instruction.

The request counter is not a dollar billing cap. A dedicated, restricted OpenAI project/key and Platform billing controls remain separate account settings. No Platform administrative permission is required by the app. Review actual Render quotas; zero-cost compute does not guarantee zero charges from excess account-level usage or external APIs.

References: [Render Free limits](https://render.com/docs/free), [Blueprint specification](https://render.com/docs/blueprint-spec), [port binding](https://render.com/docs/web-services#port-binding), [Postgres connectivity](https://render.com/docs/postgresql-creating-connecting).
