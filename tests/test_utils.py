import unittest
from unittest.mock import patch, MagicMock
import os
import tempfile
import sys

from m10 import (
    capture_photo, image_to_base64, set_system_volume,
    detect_volume_control, log, ensure_dirs
)

class TestUtils(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.photo_dir = os.path.join(self.temp_dir, "photos")
        os.makedirs(self.photo_dir, exist_ok=True)
        self.patcher_photo = patch('m10.PHOTO_DIR', self.photo_dir)
        self.patcher_photo.start()

    def tearDown(self):
        self.patcher_photo.stop()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch('m10.subprocess.run')
    def test_capture_photo_success(self, mock_run):
        mock_run.return_value.returncode = 0
        with patch('os.path.exists', return_value=True), patch('os.path.getsize', return_value=100):
            result = capture_photo("test.jpg")
            self.assertEqual(result, os.path.join(self.photo_dir, "test.jpg"))
            mock_run.assert_called_once()

    @patch('m10.subprocess.run')
    def test_capture_photo_fail(self, mock_run):
        mock_run.return_value.returncode = 1
        result = capture_photo("test.jpg")
        self.assertIsNone(result)

    def test_image_to_base64(self):
        with tempfile.NamedTemporaryFile(mode='w+b') as f:
            f.write(b'test data')
            f.flush()
            b64 = image_to_base64(f.name)
            self.assertEqual(b64, 'dGVzdCBkYXRh')

    @patch('m10.subprocess.run')
    def test_set_system_volume(self, mock_run):
        set_system_volume(50)
        mock_run.assert_called_with('amixer set PCM 50%', shell=True, timeout=5)

    @patch('m10.subprocess.run')
    def test_detect_volume_control(self, mock_run):
        def side_effect(cmd, **kwargs):
            if 'aplay' in cmd:
                return MagicMock(stdout="card 1: USB Audio [USB Audio]\n")
            elif 'scontrols' in cmd:
                return MagicMock(stdout="Simple mixer control 'Speaker',0\n")
            return MagicMock()
        mock_run.side_effect = side_effect
        result = detect_volume_control()
        self.assertIn("Speaker", result)

    def test_ensure_dirs(self):
        ensure_dirs()
        self.assertTrue(os.path.exists(self.photo_dir))

    @patch('builtins.print')
    @patch('m10.open')
    def test_log(self, mock_open, mock_print):
        log("test message", "INFO")
        mock_print.assert_called()
        mock_open.assert_called()
