import unittest
from unittest.mock import patch, MagicMock, mock_open, ANY
import json

from m10 import (
    http_request, register_device, sync_reminders,
    API_REGISTER, API_REMINDERS, state, flush_local_logs
)

class TestNetwork(unittest.TestCase):
    def setUp(self):
        state["online"] = False
        state["reminders"] = []
        state["medicines"] = []

    @patch('m10.urllib.request.urlopen')
    def test_http_request_post(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"code":0,"data":{}}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = http_request("http://test.com", payload={"key": "val"})
        self.assertEqual(result, {"code": 0, "data": {}})
        mock_urlopen.assert_called_once()

    @patch('m10.http_request')
    def test_register_device_success(self, mock_http):
        mock_http.return_value = {"code": 0, "msg": "ok"}
        result = register_device()
        self.assertTrue(result)
        mock_http.assert_called_once_with(API_REGISTER, {
            "device_id": "m10_275527387791320",
            "pair_code": "275527387791320",
            "model": "unihiker_m10",
            "base_url": "https://my-website.ccwu.cc/eating-medication/family"
        })

    @patch('m10.http_request')
    def test_sync_reminders(self, mock_http):
        mock_http.return_value = {
            "code": 0,
            "data": {
                "reminders": [{"id": "r1", "times": ["09:00"], "days": [1,2,3,4,5,6,7]}],
                "medicines": [{"id": "m1", "name": "阿莫西林", "remaining": 10}]
            }
        }
        result = sync_reminders()
        self.assertTrue(result)
        self.assertEqual(len(state["reminders"]), 1)
        self.assertEqual(state["medicines"][0]["name"], "阿莫西林")
        self.assertIsNotNone(state["last_sync"])

    @patch('m10.log')
    @patch('m10.http_request')
    @patch('m10.os.path.exists')
    @patch('m10.json.load')
    @patch('m10.json.dump')
    @patch('builtins.open', new_callable=mock_open)
    def test_flush_local_logs(self, mock_open_func, mock_dump, mock_load, mock_exists, mock_http, mock_log):
        mock_exists.return_value = True
        mock_load.return_value = [{"event": "test"}]
        mock_http.return_value = {"code": 0}
        flush_local_logs()
        mock_http.assert_called_once()
        # 修正：添加 ensure_ascii=False 关键字参数匹配
        mock_dump.assert_called_once_with([], ANY, ensure_ascii=False)
        mock_open_func.assert_called_once_with('/root/medication_log_queue.json', 'w', encoding='utf-8')