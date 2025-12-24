# tests/mock_config_manager.py

"""
A mock version of the app.config_manager for testing the auto-learning client.
"""

class MockConfigManager:
    def get(self, key: str, default=None):
        """Returns a mock URL for the auto-learning agent."""
        if key == "AUTO_LEARNING_AGENT_URL":
            return "http://mock-auto-learning-agent"
        return default

# The client imports the singleton 'config_manager', so we provide a mock
# instance with the same name.
config_manager = MockConfigManager()
