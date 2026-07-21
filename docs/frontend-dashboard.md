# Frontend dashboard integration

The frontend is an optional, read-only observability layer. Manager, hourly trading, Risk gates, broker reconciliation, protection reconciliation, Backtest gates, and Alpaca Paper execution do not depend on it.

## Endpoint

`GET /dashboard/snapshot` returns the strict Pydantic contract `dashboard-snapshot.v1`. It uses existing Database_Agent and Execution_Agent clients server-side and then maps the result through an allowlist. It never returns account IDs, order IDs, broker identifiers, API keys, tokens, internal URLs, database connection strings, or raw exception messages.

The endpoint has:

- `Cache-Control: no-store`
- per-process request limiting through `DASHBOARD_RATE_LIMIT_PER_MINUTE`
- CORS allowlist through `DASHBOARD_CORS_ALLOWED_ORIGINS`
- no write or execution operations

Production example:

```env
ENVIRONMENT=production
DASHBOARD_CORS_ALLOWED_ORIGINS=https://trading.example.com
DASHBOARD_RATE_LIMIT_PER_MINUTE=120
```

`*` is rejected when `ENVIRONMENT=production`.

## Local Docker Compose

Keep `Manager_Agent` and `Trading_Frontend` as sibling directories, then run:

```bash
docker compose -f docker-compose.yml -f docker-compose.frontend.yml --profile dashboard up --build
```

Open `http://localhost:5173`. Browser requests use `/api/dashboard/snapshot`; Nginx forwards `/api` to `manager-agent` inside Docker. The internal hostname is never embedded in browser JavaScript.

Stopping or failing `trading-frontend` does not stop Manager or any trading service because the dependency direction is frontend -> Manager only.

## Production deployment

1. Deploy Manager to Railway or the existing backend platform with HTTPS.
2. Set the Vercel origin in `DASHBOARD_CORS_ALLOWED_ORIGINS`.
3. Verify `/dashboard/snapshot` returns v1 and no sensitive fields.
4. Build Trading_Frontend on Vercel with `VITE_DATA_SOURCE=manager-api` and the public Manager HTTPS URL.

Do not put a service API key or Alpaca credential in any `VITE_*` value.

## Rollback

Frontend and Manager deploy independently. Roll back or disable the frontend without changing the hourly workflow. If the Manager dashboard endpoint must be rolled back, first point the frontend to a previously sanitized `public-snapshot` v1 artifact. The operational `/dashboard/data` route remains separate for existing internal tooling.

## Known limitation

The in-process rate limiter is intentionally dependency-free and applies per Manager worker. Multi-replica production should add an edge/platform limit or a shared Redis-backed limiter while retaining the application limit.
