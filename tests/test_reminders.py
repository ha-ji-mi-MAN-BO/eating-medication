import unittest
from unittest.mock import patch, MagicMock
import datetime

from m10 import (
    state, check_fixed_reminders, trigger_alert, confirm_take,
    FIXED_REMINDER_TIMES, reset_fixed_trigger_if_new_day
)

class TestReminders(unittest.TestCase):
    def setUp(self):
        state["active_alerts"] = {}
        state["triggered_fixed_times"] = set()
        state["current_date"] = None

    @patch('m10.datetime')
    def test_reset_fixed_trigger_if_new_day(self, mock_datetime):
        mock_now = datetime.datetime(2026, 8, 4, 10, 0, 0)
        mock_datetime.datetime.now.return_value = mock_now
        state["current_date"] = "2026-08-03"
        reset_fixed_trigger_if_new_day()
        self.assertEqual(state["current_date"], "2026-08-04")
        self.assertEqual(state["triggered_fixed_times"], set())

    @patch('m10.datetime')
    @patch('m10.trigger_alert')
    def test_check_fixed_reminders_triggers_once_per_day(self, mock_trigger, mock_datetime):
        mock_now = datetime.datetime(2026, 8, 4, 9, 0, 0)
        mock_datetime.datetime.now.return_value = mock_now
        mock_datetime.datetime.strftime = lambda self, fmt: "09:00" if fmt == "%H:%M" else "2026-08-04"
        state["current_date"] = "2026-08-04"
        check_fixed_reminders()
        mock_trigger.assert_called_once()
        mock_trigger.reset_mock()
        check_fixed_reminders()
        mock_trigger.assert_not_called()

    @patch('m10.tts_speak')
    @patch('m10.buzzer_beep')
    @patch('m10.update_gui_reminder')
    def test_trigger_alert(self, mock_gui, mock_buzzer, mock_tts):
        reminder = {"id": "t1", "user_name": "张三", "medicine_name": "阿莫西林", "dose": "1粒"}
        trigger_alert(reminder)
        self.assertIn("t1", state["active_alerts"])
        mock_gui.assert_called_with("张三", "阿莫西林", "1粒")
        state["active_alerts"].clear()

    @patch('m10.capture_photo')
    @patch('m10.upload_log')
    @patch('m10.update_gui_home')
    @patch('m10.tts_speak')
    @patch('m10.update_stock')
    def test_confirm_take(self, mock_stock, mock_tts, mock_home, mock_upload, mock_photo):
        mock_photo.return_value = "/tmp/photo.jpg"
        reminder = {
            "id": "t1",
            "user_name": "张三",
            "medicine_name": "阿莫西林",
            "dose": "1粒",
            "medicine_id": "m1",
            "dose_count": 2
        }
        state["active_alerts"]["t1"] = {
            "reminder": reminder,
            "started_at": datetime.datetime.now(),
            "volume": 30
        }
        confirm_take("t1")
        self.assertNotIn("t1", state["active_alerts"])
        mock_upload.assert_called_once()
        mock_home.assert_called_once()
        mock_tts.assert_called_with("已记录服药")
        mock_stock.assert_called_with("m1", 2)
