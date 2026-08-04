import unittest
from unittest.mock import MagicMock, patch
import m10   # 导入整个模块，通过 m10. 访问全局变量

class TestGUI(unittest.TestCase):
    def setUp(self):
        self.gui_mock = MagicMock()
        self.gui_mock.draw_text.return_value = MagicMock()
        self.patcher_gui = patch('m10.gui', self.gui_mock)
        self.patcher_gui.start()
        # 重置 m10 模块中的全局变量（不是测试局部变量）
        m10._gui_mode = "home"
        m10._clock_time_obj = None
        m10._clock_date_obj = None

    def tearDown(self):
        self.patcher_gui.stop()

    def test_update_gui_home(self):
        m10.update_gui_home()
        self.assertEqual(m10._gui_mode, "home")
        self.assertGreaterEqual(self.gui_mock.draw_text.call_count, 5)

    def test_update_gui_reminder(self):
        m10.update_gui_reminder("李四", "头孢", "2粒")
        self.assertEqual(m10._gui_mode, "reminder")
        calls = self.gui_mock.draw_text.call_args_list
        found = any("该吃药了" in str(call) for call in calls)
        self.assertTrue(found)

    def test_update_gui_status(self):
        m10.update_gui_status("正在测试", alert=True)
        self.assertEqual(m10._gui_mode, "status")
        calls = self.gui_mock.draw_text.call_args_list
        found_red = any("FF4444" in str(call) for call in calls)
        self.assertTrue(found_red)