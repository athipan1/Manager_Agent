from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/hourly-auto-trading.yml")


def replace_once(content: str, old: str, new: str, label: str) -> str:
    if new in content:
        return content
    if old not in content:
        raise RuntimeError(f"Missing workflow anchor: {label}")
    return content.replace(old, new, 1)


def replace_all(content: str, old: str, new: str) -> str:
    return content.replace(old, new)


def main() -> int:
    content = WORKFLOW.read_text(encoding="utf-8")

    content = replace_once(
        content,
        '      dry_run:\n        description: "Keep execution in simulator/safety mode"\n        required: false\n        default: "false"\n',
        '      dry_run:\n        description: "Keep execution in simulator/safety mode"\n        required: false\n        default: "false"\n      curator_enabled:\n        description: "Enable Curator_Agent advisory metadata signals"\n        required: false\n        default: "true"\n',
        "workflow_dispatch curator input",
    )

    content = replace_once(
        content,
        "      ALPACA_API_URL: ${{ secrets.ALPACA_API_URL || 'https://paper-api.alpaca.markets' }}\n",
        "      CURATOR_AGENT_ENABLED: ${{ github.event.inputs.curator_enabled || 'true' }}\n      CURATOR_AGENT_URL: http://curator-agent:8010\n      CURATOR_SKILL_TIMEOUT_SECONDS: \"1.0\"\n      ALPACA_API_URL: ${{ secrets.ALPACA_API_URL || 'https://paper-api.alpaca.markets' }}\n",
        "curator environment",
    )

    content = replace_once(
        content,
        '      - name: Show checked out agent commits\n',
        '      - name: Checkout Curator_Agent\n        uses: actions/checkout@v4\n        with:\n          repository: athipan1/Curator_Agent\n          ref: main\n          path: Curator_Agent\n          fetch-depth: 1\n\n      - name: Show checked out agent commits\n',
        "checkout Curator_Agent",
    )

    content = replace_once(
        content,
        '          echo "Risk_Agent=$(git -C Risk_Agent rev-parse HEAD)"\n          echo "DRY_RUN=${DRY_RUN}"\n          echo "BROKER_MODE=${BROKER_MODE}"\n',
        '          echo "Risk_Agent=$(git -C Risk_Agent rev-parse HEAD)"\n          echo "Curator_Agent=$(git -C Curator_Agent rev-parse HEAD)"\n          echo "DRY_RUN=${DRY_RUN}"\n          echo "BROKER_MODE=${BROKER_MODE}"\n          echo "CURATOR_AGENT_ENABLED=${CURATOR_AGENT_ENABLED}"\n',
        "show Curator commit",
    )

    content = replace_all(
        content,
        "docker compose -f docker-compose.yml -f docker-compose.risk.yml",
        "docker compose -f docker-compose.yml -f docker-compose.risk.yml -f docker-compose.curator.yml",
    )

    content = replace_all(
        content,
        'runtime_services="database-agent technical-agent scanner-agent fundamental-agent learning-agent risk-agent execution-agent manager-agent db"',
        'runtime_services="database-agent technical-agent scanner-agent fundamental-agent learning-agent risk-agent execution-agent curator-agent manager-agent db"',
    )

    content = replace_once(
        content,
        '            execution=$(curl -fsS http://localhost:8006/health >/dev/null && echo ok || echo wait)\n',
        '            execution=$(curl -fsS http://localhost:8006/health >/dev/null && echo ok || echo wait)\n            curator=$(curl -fsS http://localhost:8010/health >/dev/null && echo ok || echo wait)\n',
        "curator host health",
    )

    content = replace_once(
        content,
        '          )\n            echo "health: manager=$manager fundamental=$fundamental technical=$technical scanner=$scanner database=$database learning=$learning risk=$risk execution=$execution manager_to_scanner=$manager_to_scanner"\n            if [ "$manager$fundamental$technical$scanner$database$learning$risk$execution$manager_to_scanner" = "okokokokokokokokok" ]; then\n              echo "All services are reachable, including manager-agent -> scanner-agent and manager-agent -> risk-agent."\n',
        '          )\n            manager_to_curator=$(docker compose -f docker-compose.yml -f docker-compose.risk.yml -f docker-compose.curator.yml exec -T manager-agent python - <<\'PY\' >/dev/null 2>&1 && echo ok || echo wait\n          import urllib.request\n          urllib.request.urlopen("http://curator-agent:8010/health", timeout=5).read()\n          PY\n          )\n            echo "health: manager=$manager fundamental=$fundamental technical=$technical scanner=$scanner database=$database learning=$learning risk=$risk execution=$execution curator=$curator manager_to_scanner=$manager_to_scanner manager_to_curator=$manager_to_curator"\n            if [ "$manager$fundamental$technical$scanner$database$learning$risk$execution$curator$manager_to_scanner$manager_to_curator" = "okokokokokokokokokokok" ]; then\n              echo "All services are reachable, including manager-agent -> scanner-agent and manager-agent -> curator-agent."\n',
        "manager to curator health",
    )

    content = replace_once(
        content,
        '      - name: Run hourly portfolio discovery, risk checks, execution, and broker snapshot\n',
        '      - name: Seed Curator advisory skill\n        working-directory: Manager_Agent\n        env:\n          CURATOR_AGENT_URL: http://localhost:8010\n        run: |\n          python scripts/seed_curator_advisory_skill.py\n\n      - name: Run hourly portfolio discovery, risk checks, execution, and broker snapshot\n',
        "seed Curator advisory skill",
    )

    content = replace_all(
        content,
        "database-agent technical-agent scanner-agent fundamental-agent learning-agent risk-agent execution-agent manager-agent db",
        "database-agent technical-agent scanner-agent fundamental-agent learning-agent risk-agent execution-agent curator-agent manager-agent db",
    )

    WORKFLOW.write_text(content, encoding="utf-8")
    print("Patched hourly workflow to include Curator_Agent advisory runtime.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
