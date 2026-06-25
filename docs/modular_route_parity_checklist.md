# Modular Route Parity Checklist

This checklist tracks parity between the legacy entrypoint and the modular entrypoint.

## Entrypoints

| Entrypoint | Role |
| --- | --- |
| `app.main:app` | Legacy entrypoint |
| `app.main_modular:app` | Modular migration entrypoint |

## Migrated routes

| Method | Path | Modular owner |
| --- | --- | --- |
| GET | `/health` | `app/routes/system.py` |
| GET | `/preflight/live` | `app/routes/system.py` |
| POST | `/analyze` | `app/routes/single_analysis.py` |
| POST | `/dry-run/analyze` | `app/routes/single_analysis.py` |
| POST | `/analyze-multi` | `app/routes/multi_analysis.py` |
| POST | `/discover-analyze-trade` | `app/routes/discovery.py` |
| POST | `/scan-and-analyze` | `app/routes/scanner.py` |
| POST | `/trade-replay` | `app/routes/trade_replay.py` |

## Validation before switching entrypoints

- [ ] `python -m compileall app tests`
- [ ] `pytest -q tests/test_main_modular.py tests/test_app_factory.py tests/routes tests/workflows tests/services`
- [ ] Run legacy app locally with `uvicorn app.main:app --reload`
- [ ] Run modular app locally with `uvicorn app.main_modular:app --reload`
- [ ] Confirm `app.main_modular:app` exposes every route listed above
- [ ] Smoke test `/health`
- [ ] Smoke test `/preflight/live`
- [ ] Smoke test `/dry-run/analyze`
- [ ] Smoke test `/analyze`
- [ ] Smoke test `/analyze-multi`
- [ ] Smoke test `/discover-analyze-trade` with `execute=false`
- [ ] Smoke test `/scan-and-analyze`
- [ ] Smoke test `/trade-replay`

## Rollout notes

1. Switch only the ASGI target first.
2. Keep rollback command ready: `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
3. Candidate modular command: `uvicorn app.main_modular:app --host 0.0.0.0 --port 8000`.
4. Remove duplicate code from `app/main.py` only after modular route smoke tests pass.

## Next step

Prepare a controlled entrypoint switch from `app.main:app` to `app.main_modular:app`.
