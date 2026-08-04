# tests/__init__.py
import sys
from unittest.mock import MagicMock

mock_modules = [
    'unihiker',
    'pinpong',
    'pinpong.board',
    'pinpong.extension.unihiker',
    'dfrobot_huskylensv2',
    'unihiker_connet_wifi'
]
for mod in mock_modules:
    sys.modules[mod] = MagicMock()