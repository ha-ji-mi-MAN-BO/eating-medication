import os
import json
import tempfile
import unittest
from unittest.mock import patch

from m10 import load_config, save_config, CONFIG_FILE

class TestConfig(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, "config.json")
        self.patcher = patch('m10.CONFIG_FILE', self.config_path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(self.config_path):
            os.remove(self.config_path)

    def test_save_and_load_config(self):
        cfg = {"wifi_ssid": "test_ssid", "wifi_password": "123456", "medicines": []}
        save_config(cfg)
        loaded = load_config()
        self.assertEqual(loaded, cfg)

    def test_load_missing_config_returns_empty(self):
        if os.path.exists(self.config_path):
            os.remove(self.config_path)
        loaded = load_config()
        self.assertEqual(loaded, {})

if __name__ == '__main__':
    unittest.main()
