from __future__ import annotations

import os


def _required_secret(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise SystemExit(f"{name} is missing")
    if len(value) < 32:
        raise SystemExit(f"{name} must contain at least 32 characters")
    return value


def main() -> int:
    execute_key = _required_secret("CURATOR_AGENT_API_KEY")
    admin_key = _required_secret("CURATOR_ADMIN_API_KEY")
    if execute_key == admin_key:
        raise SystemExit("Curator execute and admin credentials must be different")
    print("Curator managed secrets are present, distinct and sufficiently long.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
