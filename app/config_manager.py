import os
import json
import shutil
from datetime import datetime, timezone
from copy import deepcopy
from . import config as static_config

# Define persistent storage paths
CONFIG_DIR = "/persistent_config"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
HISTORY_DIR = os.path.join(CONFIG_DIR, "history")


class ConfigManager:
    """
    Manages the application's configuration by merging a static base config
    with a dynamic, persistent JSON config that can be updated by the
    auto-learning agent.
    """
    def __init__(self):
        self._base_config = self._load_base_config()
        self._dynamic_config = self._load_dynamic_config()
        self.config = self._merge_configs()

        # Ensure directories exist
        os.makedirs(HISTORY_DIR, exist_ok=True)

    def _load_base_config(self):
        """Loads the static configuration from the config.py module."""
        # Convert the module to a dictionary, only including uppercase constants
        return {key: getattr(static_config, key) for key in dir(static_config) if key.isupper()}

    def _load_dynamic_config(self):
        """Loads the dynamic configuration from the JSON file."""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading dynamic config: {e}. Starting with an empty one.")
                return {}
        return {}

    def _merge_configs(self):
        """Merges the base and dynamic configurations."""
        merged = deepcopy(self._base_config)
        merged.update(self._dynamic_config)
        return merged

    def apply_deltas(self, deltas: dict):
        """
        Applies deltas to the current configuration, clamps them to safe
        bounds, and persists the new configuration.
        """
        # Create a deepcopy to modify
        updated_config_values = deepcopy(self.config)

        # Note: This is a simple implementation. A more robust one might handle
        # nested dictionaries for things like 'agent_weights'. The current
        # task description implies flat parameters like RISK_PER_TRADE.
        # This will be extended if nested structures are required.

        # Example for RISK_PER_TRADE
        if 'risk_per_trade' in deltas:
            current_value = updated_config_values.get('RISK_PER_TRADE', self._base_config.get('RISK_PER_TRADE'))
            delta = deltas['risk_per_trade']
            new_value = current_value + delta

            # Clamp the value to the safe bounds defined in the base config
            min_bound = self._base_config.get('MIN_RISK_PER_TRADE')
            max_bound = self._base_config.get('MAX_RISK_PER_TRADE')

            clamped_value = max(min_bound, min(new_value, max_bound))
            updated_config_values['RISK_PER_TRADE'] = clamped_value

        # Handle agent_weights deltas
        if 'agent_weights' in deltas:
            current_weights = updated_config_values.get('AGENT_WEIGHTS', {}).copy()
            for agent, delta in deltas['agent_weights'].items():
                if agent in current_weights:
                    current_weights[agent] += delta

            # Normalize weights to ensure they sum to 1.0
            total_weight = sum(current_weights.values())
            if total_weight > 0:
                normalized_weights = {agent: w / total_weight for agent, w in current_weights.items()}
                updated_config_values['AGENT_WEIGHTS'] = normalized_weights

        # Persist the changes
        self._save_dynamic_config(updated_config_values)

        # Update the in-memory config
        self.config = updated_config_values

    def _save_dynamic_config(self, new_config_data: dict):
        """Saves the updated dynamic configuration to a file."""
        # 1. Backup the old config if it exists
        if os.path.exists(CONFIG_FILE):
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
            backup_file = os.path.join(HISTORY_DIR, f"config-{timestamp}.json")
            shutil.copy2(CONFIG_FILE, backup_file)

        # 2. Extract only the keys that are different from the base config
        dynamic_values = {
            key: value for key, value in new_config_data.items()
            if key in self._base_config and self._base_config[key] != value
        }

        # 3. Write the new dynamic config
        with open(CONFIG_FILE, 'w') as f:
            json.dump(dynamic_values, f, indent=4)

    def get(self, key: str, default=None):
        """Gets a configuration value by key."""
        return self.config.get(key, default)

# Singleton instance
config_manager = ConfigManager()
