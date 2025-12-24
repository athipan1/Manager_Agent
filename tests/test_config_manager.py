import unittest
from unittest.mock import patch, MagicMock, mock_open
import os
import json
import importlib

# Mock the static_config before it's imported by config_manager
from . import mock_static_config
import sys
sys.modules['app.config'] = mock_static_config

# Patch os.makedirs BEFORE importing the module that calls it at the module level
patcher = patch('os.makedirs')
patcher.start()

# Now, we can safely import the module
from app.config_manager import ConfigManager

class TestConfigManager(unittest.TestCase):

    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data='{"RISK_PER_TRADE": 0.015}')
    def setUp(self, mock_file_open, mock_path_exists):
        """Set up a fresh ConfigManager for each test by reloading the module."""
        mock_path_exists.return_value = True
        importlib.reload(sys.modules['app.config_manager'])
        self.config_manager = sys.modules['app.config_manager'].config_manager

    def test_initialization_loads_and_merges_configs(self):
        self.assertEqual(self.config_manager.get('RISK_PER_TRADE'), 0.015)

    @patch('shutil.copy2')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_deltas_and_clamp_upper_bound(self, mock_open_obj, mock_copy):
        deltas = {'risk_per_trade': 0.02} # Pushes initial 0.015 to 0.035
        self.config_manager.apply_deltas(deltas)
        # Verify the in-memory value is clamped
        self.assertEqual(self.config_manager.get('RISK_PER_TRADE'), 0.03)

        # Verify the correct value was written to the file
        write_calls = mock_open_obj().write.call_args_list
        written_string = "".join(call.args[0] for call in write_calls)
        written_json = json.loads(written_string)
        self.assertEqual(written_json['RISK_PER_TRADE'], 0.03)

    @patch('shutil.copy2')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_deltas_and_clamp_lower_bound(self, mock_open_obj, mock_copy):
        deltas = {'risk_per_trade': -0.012} # Pushes initial 0.015 to 0.003
        self.config_manager.apply_deltas(deltas)
        # Verify the in-memory value is clamped
        self.assertEqual(self.config_manager.get('RISK_PER_TRADE'), 0.005)

        # Verify the correct value was written to the file
        write_calls = mock_open_obj().write.call_args_list
        written_string = "".join(call.args[0] for call in write_calls)
        written_json = json.loads(written_string)
        self.assertEqual(written_json['RISK_PER_TRADE'], 0.005)

    @patch('shutil.copy2')
    @patch('builtins.open', new_callable=mock_open)
    def test_config_backup_is_created(self, mock_open_obj, mock_copy):
        with patch('os.path.exists', return_value=True):
            self.config_manager.apply_deltas({'risk_per_trade': 0.001})
            mock_copy.assert_called_once()

    @patch('shutil.copy2')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_deltas_for_agent_weights_and_normalize(self, mock_open_obj, mock_copy):
        """
        Test that agent_weights are updated and normalized correctly.
        """
        # Initial weights are {"technical": 0.5, "fundamental": 0.5}
        deltas = {
            "agent_weights": {
                "technical": 0.1,  # New value -> 0.6
                "fundamental": -0.05 # New value -> 0.45
            }
        }
        with patch('os.path.exists', return_value=True):
            self.config_manager.apply_deltas(deltas)

        new_weights = self.config_manager.get('AGENT_WEIGHTS')

        # Total weight before normalization is 0.6 + 0.45 = 1.05
        # Expected normalized values:
        # technical: 0.6 / 1.05 = 0.5714...
        # fundamental: 0.45 / 1.05 = 0.4285...
        self.assertAlmostEqual(new_weights['technical'], 0.5714, places=4)
        self.assertAlmostEqual(new_weights['fundamental'], 0.4286, places=4)
        self.assertAlmostEqual(sum(new_weights.values()), 1.0)


    @classmethod
    def tearDownClass(cls):
        patcher.stop()

if __name__ == '__main__':
    unittest.main()
