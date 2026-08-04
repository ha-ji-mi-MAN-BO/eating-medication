import unittest
from unittest.mock import MagicMock, patch
from m10 import (
    update_gui_home, update_gui_reminder, update_gui_status,
    _gui_mode, _clock_time_obj, _clock_date_obj
)

class TestGUI(unittest.TestCase):
    def setUp(self):
        self.gui_mock = MagicMock()
        self.gui_mock.draw_text.return_value = MagicMock()
        self.patcher_gui = patch('m10.gui', self.gui_mock)
        self.patcher_gui.start()
        global _gui_mode, _clock_time_obj, _clock_date_obj
        _gui_mode = "home"
        _clock_time_obj = None
        _clock_date_obj = None

    def tearDown(self):
        self.patcher_gui.stop()

    def test_update_gui_home(self):
        update_gui_home()
        self.assertEqual(_gui_mode, "home")
        self.assertGreaterEqual(self.gui_mock.draw_text.call_count, 5)

    def test_update_gui_reminder(self):
        update_gui_reminder("李四", "头孢", "2粒")
        self.assertEqual(_gui_mode, "reminder")
        calls = self.gui_mock.draw_text.call_args_list
        found = any("该吃药了" in str(call) for call in calls)
        self.assertTrue(found)

    def test_update_gui_status(self):
        update_gui_status("正在测试", alert=True)
        self.assertEqual(_gui_mode, "status")
        calls = self.gui_mock.draw_text.call_args_list
        found_red = any("FF4444" in str(call) for call in calls)
        self.assertTrue(found_red)
