# Manager_Agent
---

## Auto-Learning Feedback Loop

The Orchestrator includes an auto-learning feedback loop designed to dynamically refine trading parameters based on performance. This system allows the platform to adapt over time without manual intervention.

### Configuration Management

The system uses a hybrid approach to manage its configuration:

1.  **Static Base Configuration (`app/config.py`):** This file contains the core, version-controlled configuration. It defines the foundational settings and, most importantly, the **safety bounds** (e.g., `MIN_RISK_PER_TRADE`, `MAX_RISK_PER_TRADE`) for all dynamically adjustable parameters.

2.  **Dynamic Policy Overrides (`/persistent_config/config.json`):** This JSON file stores the policy adjustments recommended by the auto-learning agent. At startup, the Orchestrator loads the static config and then merges these dynamic values on top. This file is stored in a Docker-mounted volume (`persistent_config_volume`) to ensure that learned parameters persist across container restarts.

### How It Works

1.  **Analyze & Trade:** The Orchestrator processes a ticker, calls the analysis agents, and makes a trading decision as usual.
2.  **Trigger Learning:** After the trade is executed (or a decision is made not to trade), the Orchestrator calls the `auto-learning-agent` with a payload containing the trade details and the signals from the analysis agents.
3.  **Receive Deltas:** The learning agent responds with a set of recommended "deltas" (e.g., a small increase or decrease to `RISK_PER_TRADE`).
4.  **Apply & Persist:** The Orchestrator's `ConfigManager` receives these deltas. It clamps each value to the safety bounds defined in the static config, applies the adjusted value to the in-memory configuration, and saves the new dynamic policy to `/persistent_config/config.json`.

### Policy Rollback Procedure

The system automatically saves a timestamped snapshot of the dynamic configuration file every time a change is applied. These backups are stored in `/persistent_config/history/`.

To manually roll back to a previous policy:

1.  **Access the Volume:** Connect to the Docker host and locate the `persistent_config_volume` directory.
2.  **Stop the Orchestrator:** `docker-compose stop orchestrator`
3.  **Choose a Backup:** Identify the desired historical configuration file from the `/persistent_config/history/` directory.
4.  **Restore:** Copy the chosen backup file to `/persistent_config/config.json`, overwriting the current dynamic policy.
5.  **Restart the Orchestrator:** `docker-compose up -d orchestrator`

This process allows for a safe and complete rollback to any previously known good configuration state.
