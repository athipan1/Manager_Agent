import unittest
from unittest.mock import patch, MagicMock, mock_open
import os
import json

# Mock the static_config before it's imported by config_manager
from . import mock_static_config
import sys
sys.modules['app.config'] = mock_static_config

# Patch os.makedirs BEFORE importing the module that calls it at the module level
patcher = patch('os.makedirs')
patcher.start()

# Now, we can safely import the module
from app.config_manager import config_manager

class TestConfigManager(unittest.TestCase):

    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data='{"RISK_PER_TRADE": 0.015}')
    def setUp(self, mock_file_open, mock_path_exists):
        """Manually reset the config_manager's state before each test."""
        mock_path_exists.return_value = True

        # Manually re-initialize the singleton's state using its own methods.
        # The mocks for open() and exists() passed to setUp are active here.
        config_manager._base_config = config_manager._load_base_config()
        config_manager._dynamic_config = config_manager._load_dynamic_config()
        config_manager.config = config_manager._merge_configs()

        self.config_manager = config_manager

    def test_initialization_loads_and_merges_configs(self):
        self.assertEqual(self.config_manager.get('RISK_PER_TRADE'), 0.015)

    @patch('shutil.copy2')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_deltas_and_clamp_upper_bound(self, mock_open_obj, mock_copy):
        deltas = {'risk_per_trade': 0.02} # Pushes initial 0.015 to 0.035
        self.config_manager.apply_deltas(deltas)
        self.assertEqual(self.config_manager.get('RISK_PER_TRADE'), 0.03)

        write_calls = mock_open_obj().write.call_args_list
        written_string = "".join(call.args[0] for call in write_calls)
        written_json = json.loads(written_string)
        self.assertEqual(written_json['RISK_PER_TRADE'], 0.03)

    @patch('shutil.copy2')
    @patch('builtins.open', new_callable=mock_open)
    def test_apply_deltas_and_clamp_lower_bound(self, mock_open_obj, mock_copy):
        deltas = {'risk_per_trade': -0.012} # Pushes initial 0.015 to 0.003
        self.config_manager.apply_deltas(deltas)
        self.assertEqual(self.config_manager.get('RISK_PER_TRADE'), 0.005)

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
        deltas = {
            "agent_weights": { "technical": 0.1, "fundamental": -0.05 }
        }
        with patch('os.path.exists', return_value=True):
            self.config_manager.apply_deltas(deltas)

        new_weights = self.config_manager.get('AGENT_WEIGHTS')
        self.assertAlmostEqual(new_weights['technical'], 0.5714, places=4)
        self.assertAlmostEqual(new_weights['fundamental'], 0.4286, places=4)

    @classmethod
    def tearDownClass(cls):
        patcher.stop()

if __name__ == '__main__':
    unittest.main()
