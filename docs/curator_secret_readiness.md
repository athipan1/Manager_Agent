# Curator managed-secret readiness gate

The `Curator Secret and Sandbox Readiness` workflow validates the persistent GitHub Actions credentials before Curator is allowed into the Hourly Paper stack.

## What the gate proves

- `CURATOR_AGENT_API_KEY` and `CURATOR_ADMIN_API_KEY` exist, are different, and contain at least 32 characters.
- Curator starts with role-based authentication enabled.
- The configured Docker sandbox image is available.
- `/ready` reports secure container execution with fallback disabled.
- The execute credential cannot register or approve skills.
- The admin credential can register and approve a harmless advisory skill.
- The execute credential can run the approved skill in a network-disabled, read-only container.
- Manager can complete its authenticated Curator smoke flow.

## Safety boundary

`docker-compose.hourly-paper.yml` intentionally keeps `CURATOR_AGENT_ENABLED=false` until this workflow passes. Curator remains advisory-only; Risk_Agent and Execution_Agent retain their mandatory trading boundaries.

## Running the gate

Open GitHub Actions in `athipan1/Manager_Agent`, select `Curator Secret and Sandbox Readiness`, and choose `Run workflow`. The workflow reads the credentials from repository Actions secrets and never stores them in source control.
