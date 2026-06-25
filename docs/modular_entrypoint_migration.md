# Modular Entrypoint Migration

Manager_Agent now has two ASGI entrypoints during the migration away from the legacy monolithic `app.main` module.

## Current entrypoints

| Entrypoint | Purpose | Notes |
| --- | --- | --- |
| `app.main:app` | Legacy production-compatible app | Keeps all existing inline routes in `app/main.py`. |
| `app.main_modular:app` | Modular migration app | Builds the app through `create_app()` and only registers routes that have been moved into routers. |

## Migrated route surface

The modular entrypoint currently exposes:

- `POST /analyze`
- `POST /dry-run/analyze`

These routes are backed by:

- `app/routes/single_analysis.py`
- `app/workflows/single_analysis_workflow.py`

## Local validation

Run the legacy app:

```bash
uvicorn app.main:app --reload
```

Run the modular app:

```bash
uvicorn app.main_modular:app --reload
```

Validate tests for the migrated surface:

```bash
python -m compileall app tests
pytest -q tests/test_main_modular.py tests/test_app_factory.py tests/routes tests/workflows tests/services
```

## Safe rollout plan

1. Keep `app.main:app` as the default production entrypoint until the modular app has every required route.
2. Run `app.main_modular:app` in a staging or local environment first.
3. Compare the migrated route behavior for:
   - `POST /analyze`
   - `POST /dry-run/analyze`
4. Move the next route group into `app/routes/` and its orchestration into `app/workflows/`.
5. After all production routes are registered through `create_app()`, switch deployment from `app.main:app` to `app.main_modular:app`.
6. Finally replace `app/main.py` with a thin compatibility shim or rename the legacy module to `main_legacy.py`.

## Remaining route groups to migrate

Recommended order:

1. Health and preflight
   - `GET /health`
   - `GET /preflight/live`
2. Replay
   - `POST /trade-replay`
3. Multi-analysis
   - `POST /analyze-multi`
4. Discovery / scanner flows
   - `POST /discover-analyze-trade`
   - scanner-backed analyze routes

## Deployment command examples

Legacy command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Modular command after rollout approval:

```bash
uvicorn app.main_modular:app --host 0.0.0.0 --port 8000
```

## Rollback

If a modular rollout fails, point the deployment command back to:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

No database migration is required for this entrypoint switch.
