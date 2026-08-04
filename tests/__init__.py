# tests/__init__.py
import sys
from unittest.mock import MagicMock

# 在所有测试导入 m10 之前，先 mock 掉硬件库
mock_modules = [
    'unihiker',
    'pinpong',
    'pinpong.board',
    'pinpong.extension.unihiker',
    'dfrobot_huskylensv2'
]
for mod in mock_modules:
    sys.modules[mod] = MagicMock()
