#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2026 UniHiker M10 智能服药提醒终端
# 版权所有，未经授权禁止复制、修改或商业使用
#
"""
UniHiker M10 智能服药提醒终端主程序
项目地址适配: https://my-website.ccwu.cc/eating-medication/server/
设备配对码: 2AIDMUNIHIKER13
API 版本: v2.28.0（对应 openapi.json）
当前代码版本: v2.34.0

本程序使用 Python 标准库 + UniHiker 原生 API (unihiker/pinpong) + pyttsx3 TTS,
不依赖 cv2、requests、schedule 等第三方库。

v2.34.0 修复记录（共 6 项 bug 修复，涵盖逻辑正确性、健壮性、并发安全、可维护性）：
- 【致命】版本号不一致：API 端点注释仍显示 v2.33.8，与文件头 v2.33.9 不一致；且文件头版本未同步到已完成的 v2.33.10，修正为 v2.34.0
- 【严重】alert_loop() 搜索药品暂停时 retry_count 不增加，若搜索模式持续时间过长，提醒可能永不超时；修复：搜索药品暂停时仍递增 retry_count 并检查上限
- 【严重】_enter_search_medicine_impl() 未检查 switch_huskylens_to_barcode() 返回值，切换失败时仍继续后续操作（启动条形码线程、显示搜索界面），导致功能异常；修复：检查返回值，切换失败时记录警告并保持当前界面
- 【严重】low_stock_alert() 中读取 state.get("mode") 进行业务模式检查，但 state 字典中不存在 "mode" 键，导致检查逻辑始终返回默认值"home"，意图中的搜索药品/提醒界面保护失效；修复：移除无效的 state.mode 检查，仅保留 _gui_mode 检查
- 【一般】_convert_plans_to_medicines() 中 per_time 和 freq_per_day 的异常处理存在冗余嵌套（外层 _parse_dose_count/_parse_frequency_per_day 已有保护）；修复：简化异常处理逻辑
- 【一般】版本修复记录注释不完整；修复：新增 v2.34.0 修复记录注释

"""

import os
# 必须在导入 tkinter/unihiker 之前强制设置 DISPLAY（SSH 远程运行时需要）
os.environ["DISPLAY"] = os.environ.get("DISPLAY") or ":0"

import time
import json
import re
import base64
import math
import queue
import threading
import datetime
import subprocess
import traceback
import urllib.request
import urllib.error
from pathlib import Path
import uuid
# HuskyLens 二哈识图：可选依赖，缺失时跳过人脸/条形码识别
try:
    from dfrobot_huskylensv2 import *
    _HUSKYLENS_AVAILABLE = True
except ImportError:
    _HUSKYLENS_AVAILABLE = False



# 可选依赖：pyttsx3（用于 TTS，缺失时自动回退到 espeak）
try:
    import pyttsx3
    _PYTTSX3_AVAILABLE = True
except ImportError:
    pyttsx3 = None
    _PYTTSX3_AVAILABLE = False

# 适配 UniHiker 平台
# GUI 模块：可选依赖
try:
    from unihiker import GUI
    _GUI_AVAILABLE = True
except ImportError:
    GUI = None
    _GUI_AVAILABLE = False

# 硬件引脚模块：可选依赖
try:
    from pinpong.board import Board, Pin
    _PINPONG_AVAILABLE = True
except ImportError:
    Board = None
    Pin = None
    _PINPONG_AVAILABLE = False

# WiFi 模块：可选依赖，缺失时优雅降级
_WIFI_AVAILABLE = False
WiFiManager = None
wifi_manager = None
_wifi_initialized = False  # WiFi 是否已初始化连接
# WiFi 凭据：优先从环境变量读取，回退到默认值（生产环境请设置 WIFI_SSID/WIFI_PASSWORD 环境变量）
_WIFI_SSID = os.environ.get("WIFI_SSID", "666")
_WIFI_PASSWORD = os.environ.get("WIFI_PASSWORD", "15756491077")

try:
    from unihiker_connet_wifi import WiFiManager
    wifi_manager = WiFiManager()
    _WIFI_AVAILABLE = True
except (ImportError, NameError, AttributeError) as e:
    _WIFI_AVAILABLE = False

# ============== 配置区 ==============
SERVER_BASE_URL = "https://my-website.ccwu.cc/eating-medication/server"
PAIR_CODE = "2AIDMUNIHIKER13"
DEVICE_ID = "m10_" + PAIR_CODE

# API 端点（v2.28.0，对应 openapi.json，m10.py 当前版本 v2.34.0）
API_REGISTER = f"{SERVER_BASE_URL}/api/v1/public/device/register"
API_SCHEDULE = f"{SERVER_BASE_URL}/api/v1/public/device/schedule/{DEVICE_ID}"
API_MESSAGE = f"{SERVER_BASE_URL}/api/v1/public/device/message"
API_UPLOAD = f"{SERVER_BASE_URL}/api/v1/public/device/upload"
API_OFFLINE = f"{SERVER_BASE_URL}/api/v1/public/device/offline"
API_AI_ASK = f"{SERVER_BASE_URL}/api/v1/public/ai/ask"

CONFIG_FILE = "/root/medication_config.json"
LOG_FILE = "/root/medication_local.log"
PHOTO_DIR = "/root/medication_photos"
QUEUE_FILE = "/root/medication_log_queue.json"

# 硬件引脚（使用数字引脚号，Pin 类在 init_hardware 中使用）
BUZZER_PIN_NUM = 25      # 蜂鸣器
BUTTON_TAKE_PIN_NUM = 21  # 已吃药按钮（~A，按下高电平，松开低电平）
BUTTON_REMIND_PIN_NUM = 27  # B键：直接启动吃药提醒（按下低电平）
BUTTON_EMERGENCY_PIN_NUM = 28  # A键：紧急呼叫（联网通知家属）

# HuskyLens 算法切换后的稳定等待时间（秒）
HUSKYLENS_SWITCH_DELAY = 5

# 搜索药品模式切换时等待 face_id_thread 暂停的时间（秒）
SEARCH_MEDICINE_PAUSE_DELAY = 1

# HuskyLens 全局实例（init_hardware 中初始化）
huskylens = None

# 人脸ID显示相关全局变量
_face_id_text = "ID: --"       # 当前检测到的人脸ID文本
_face_id_obj = None            # GUI 文本对象（左下角）
_face_id_stop_event = threading.Event()  # 人脸ID检测线程停止信号

# 搜索药品功能相关全局变量
_searching_medicine = threading.Event()  # 搜索药品模式标志（True时暂停人脸检测）
_previous_gui_mode = "home"  # 进入搜索药品前的界面（home/reminder），用于返回
_search_button_obj = None    # "搜索药品"按钮对象
_back_button_obj = None      # "返回"按钮对象
_barcode_text_obj = None     # 条形码名字文本对象
_barcode_thread_stop = threading.Event()  # 条形码检测线程停止信号

# 提醒时需要检测的目标人脸ID（id1 对应的老人）
TARGET_FACE_ID = 1

# 提醒音量递增参数（每 10 分钟递增一次）
VOLUME_INITIAL = 30
VOLUME_STEP = 15
VOLUME_MAX = 100
SNOOZE_MINUTES = 10
# MAX_ALERT_RETRIES 已在下方常量定义区统一定义，此处不再重复

# USB 扬声器音量控制名称，留空则自动检测（常见值：Speaker / Headphone / PCM / Master）
VOLUME_CONTROL = ""

# TTS 语速（pyttsx3 rate 属性）
TTS_RATE = 200

# 定时循环间隔（秒）
CHECK_INTERVAL = 1

# 固定服药提醒时间（每天触发，HH:MM 格式）
FIXED_REMINDER_TIMES = ["09:00", "13:00", "17:00"]

# 主界面时钟刷新间隔（秒）
CLOCK_REFRESH_INTERVAL = 1

# 常量定义（统一管理，避免分散硬编码）
MAX_ALERT_RETRIES = 20           # 提醒最大重试次数（约 3 小时）
MAX_QUEUE_SIZE = 500             # 离线日志队列最大条数
MAX_PHOTO_SIZE = 512000          # 照片上传最大大小（500KB）
MAX_IMAGE_SIZE = 1048576         # 图片 base64 编码最大大小（1MB）
NETWORK_RECONNECT_INTERVAL = 30  # 网络恢复检查间隔（秒）
MAX_RECONNECT_FAILS = 5          # 网络恢复最大失败次数
HEARTBEAT_INTERVAL = 20          # 心跳上报间隔（秒），向 register 接口发送心跳
STOCK_CHECK_INTERVAL = 6 * 3600  # 库存检查间隔（6 小时）
LOG_FLUSH_INTERVAL = 30 * 60     # 日志刷新间隔（30 分钟）
ALERT_TIMEOUT = 30               # 低库存告警超时（秒）
ALERT_WAIT_TIMEOUT = 10          # 提醒循环等待超时（秒），每轮播报后等待时间
MISSED_MINUTES_THRESHOLD = 60    # 错过分钟数阈值
HTTP_REQUEST_TIMEOUT = 15        # HTTP 请求默认超时（秒）
BUTTON_DEBOUNCE_TAKE = 2         # 吃药按钮去重时间（秒）
BUTTON_DEBOUNCE_REMIND = 3       # 提醒按钮去重时间（秒）
BUTTON_DEBOUNCE_EMERGENCY = 3    # 紧急按钮去重时间（秒）

# GUI 颜色常量
COLOR_TITLE = "#000000"
COLOR_ALERT_RED = "#FF4444"
COLOR_ALERT_DARK = "#FF0000"
COLOR_CLOCK_BLUE = "#0050FF"
COLOR_TEXT_DARK = "#333333"
COLOR_TEXT_GRAY = "#666666"

# ============== 全局状态 ==============
state = {
    "online": False,
    "device_token": None,      # 设备注册后获得，用于 X-Device-Token Header
    "last_sync": None,
    "reminders": [],          # 服药提醒列表
    "medicines": [],          # 药品库存
    "active_alerts": {},      # 当前活跃的提醒 {reminder_id: info}
    "current_volume": VOLUME_INITIAL,
    "camera_available": False,
    "triggered_fixed_times": set(),  # 当天已触发的固定提醒时间，避免重复触发
    "current_date": None,     # 当天日期字符串 YYYY-MM-DD，用于跨天重置触发记录
}

lock = threading.RLock()
_gui_lock = threading.RLock()  # 改为 RLock 支持嵌套获取，GUI 函数可能嵌套获取
_gui_draw_lock = threading.Lock()  # 保护 gui.clear/draw_text 等绘制操作，防多线程画面撕裂
_config_lock = threading.Lock()  # 保护配置文件的读写，避免多线程同时写入导致 JSON 损坏
_queue_lock = threading.Lock()   # 保护离线日志队列文件的读写
_log_lock = threading.Lock()      # 保护日志文件写入与轮转
_camera_lock = threading.Lock()  # 保护摄像头访问，避免多线程并发拍照冲突
_emergency_lock = threading.Lock()  # 保护紧急联系人缓存的并发访问
_volume_lock = threading.Lock()  # 保护音量控制命令缓存的并发访问
_face_id_lock = threading.Lock()  # 保护 _face_id_text 变量的并发访问

# 设备未注册标志：检测到 404"设备未注册"时置位，main_loop 检测后清除旧 token 并重新注册
_device_needs_re_register = threading.Event()

gui = None
buzzer = None
button_take = None
button_emergency = None
button_remind = None

# ============== 工具函数 ==============

def _get_online():
    """线程安全读取在线状态"""
    with lock:
        return state["online"]

def _set_online(value):
    """线程安全设置在线状态"""
    with lock:
        state["online"] = value

def _get_camera_available():
    """线程安全读取摄像头可用性"""
    with lock:
        return state["camera_available"]

def _set_camera_available(value):
    """线程安全设置摄像头可用性"""
    with lock:
        state["camera_available"] = value

def _get_device_token():
    """线程安全读取设备令牌"""
    with lock:
        return state.get("device_token")

def _set_device_token(token):
    """线程安全设置设备令牌"""
    with lock:
        state["device_token"] = token

# 日志轮转与检查常量
LOG_MAX_SIZE = 10 * 1024 * 1024  # 10 MB 日志轮转阈值
_LOG_SIZE_CHECK_INTERVAL = 60  # 日志大小检查间隔（秒），避免每次都检查
_VOLUME_DIVISOR = 100  # 音量转换除数（0-100 转 0.0-1.0）
_last_log_size_check = 0  # 上次检查时间戳


def log(msg, level="INFO"):
    """线程安全的日志函数，支持日志轮转。文件 I/O 在锁外执行以避免阻塞
    
    优化：每 _LOG_SIZE_CHECK_INTERVAL 秒检查一次文件大小，减少高频调用时的开销。
    日志超过 LOG_MAX_SIZE 时自动轮转（保留 .old 文件）。
    
    Args:
        msg: 日志消息文本
        level: 日志级别（INFO/WARNING/ERROR/CRITICAL），默认 INFO
    
    Returns:
        None
    
    Raises:
        无（所有异常已内部捕获）
    """
    global _last_log_size_check
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {msg}"
    print(line)
    try:
        need_rotate = False
        rotated = None
        now = time.time()
        # 仅在检查间隔到期时才检查文件大小，减少系统调用开销
        if now - _last_log_size_check >= _LOG_SIZE_CHECK_INTERVAL:
            with _log_lock:
                _last_log_size_check = now
                need_rotate = (
                    os.path.exists(LOG_FILE)
                    and os.path.getsize(LOG_FILE) > LOG_MAX_SIZE
                )
                if need_rotate:
                    rotated = LOG_FILE + ".old"
                    if os.path.exists(rotated):
                        try:
                            os.remove(rotated)
                        except Exception:
                            pass
                    os.rename(LOG_FILE, rotated)
        # 文件 I/O 在锁外执行，避免阻塞其他线程
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def ensure_dirs():
    """确保照片存储目录存在
    
    Args:
        无
    
    Returns:
        None
    
    Raises:
        OSError: 目录创建失败时
    """
    Path(PHOTO_DIR).mkdir(parents=True, exist_ok=True)


def load_config():
    """加载配置文件，返回 dict；文件损坏时自动备份并返回空字典
    
    配置文件损坏时自动备份到带时间戳的 .bak 文件，
    避免数据丢失，便于事后排查和恢复。
    
    Args:
        无
    
    Returns:
        dict: 配置字典，损坏或不存在时返回空字典 {}
    
    Raises:
        无
    """
    with _config_lock:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    if isinstance(cfg, dict):
                        return cfg
                    else:
                        log(f"配置文件格式错误（不是 dict），类型: {type(cfg)}", "ERROR")
                        return {}
            except (json.JSONDecodeError, ValueError) as e:
                log(f"配置文件损坏，正在备份: {e}", "ERROR")
                # 备份损坏的配置文件（添加 PID，避免并发冲突）
                backup_path = CONFIG_FILE + f".bak.{int(time.time())}.{os.getpid()}"
                try:
                    os.rename(CONFIG_FILE, backup_path)
                    log(f"损坏配置已备份到: {backup_path}", "INFO")
                except Exception as backup_e:
                    log(f"备份损坏配置失败: {backup_e}", "WARNING")
                return {}
            except Exception as e:
                log(f"读取配置失败: {type(e).__name__}: {e}", "ERROR")
                return {}
        return {}


def save_config(cfg):
    """原子写入：先写临时文件再 rename，避免断电导致配置文件损坏
    
    Args:
        cfg: 配置字典，必须是 dict 类型
    
    Returns:
        bool: 成功返回 True，失败返回 False
    
    Raises:
        无
    """
    if not isinstance(cfg, dict):
        log("save_config: cfg 必须是 dict 类型", "ERROR")
        return False
    with _config_lock:
        tmp_path = CONFIG_FILE + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
                f.flush()  # 强制写入磁盘
                os.fsync(f.fileno())  # 确保数据落盘
            os.replace(tmp_path, CONFIG_FILE)
            return True
        except Exception as e:
            log(f"保存配置失败: {type(e).__name__}: {e}", "ERROR")
            # 清理临时文件
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return False


def check_network():
    """检测网络连通性，使用合理的 User-Agent 避免被服务器拒绝"""
    try:
        req = urllib.request.Request(
            SERVER_BASE_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; M10MedicationChecker/1.0)"}
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


def detect_volume_control():
    """自动检测可用的 ALSA 音量控制，优先 USB 声卡的 Speaker/Headphone/PCM"""
    try:
        r = subprocess.run(["aplay", "-l"], shell=False, capture_output=True, universal_newlines=True, timeout=5)
        cards_output = r.stdout
        usb_card = None
        for line in cards_output.splitlines():
            if "USB" in line.upper() and line.lower().startswith("card "):
                try:
                    usb_card = int(line.split(':')[0].replace("card ", "").strip())
                    break
                except Exception:
                    continue

        controls = ["Speaker", "Headphone", "PCM", "Master", "Digital"]

        def control_exists(card_arg, ctrl):
            """检查指定声卡的某个控制是否存在"""
            cmd = ["amixer"] + card_arg + ["scontrols"] if card_arg else ["amixer", "scontrols"]
            rr = subprocess.run(cmd, shell=False, capture_output=True, universal_newlines=True, timeout=3)
            return ctrl.lower() in rr.stdout.lower()

        if usb_card is not None:
            card_arg = ["-c", str(usb_card)]
            for ctrl in controls:
                if control_exists(card_arg, ctrl):
                    return f"{card_arg[0]} {card_arg[1]} set {ctrl}"

        for ctrl in controls:
            if control_exists([], ctrl):
                return f"set {ctrl}"
    except Exception as e:
        log(f"检测音量控制失败: {e}", "WARNING")
    return "set PCM"


_volume_control_cmd = None


def set_system_volume(vol):
    """设置 USB 扬声器系统音量（amixer），自动检测并缓存可用的 ALSA 控制
    
    Args:
        vol: 音量值（0-100 整数）
    
    Returns:
        None
    
    Raises:
        无（所有异常已内部捕获并记录）
    """
    global _volume_control_cmd
    if not isinstance(vol, (int, float)):
        log(f"音量参数类型无效: {type(vol)}", "ERROR")
        return
    vol = max(0, min(100, int(vol)))
    # 保护 _volume_control_cmd 的并发访问
    with _volume_lock:
        if not _volume_control_cmd:
            _volume_control_cmd = VOLUME_CONTROL if VOLUME_CONTROL else detect_volume_control()
        current_cmd = _volume_control_cmd
    if not current_cmd or not current_cmd.strip():
        log("音量控制命令为空，跳过音量设置", "DEBUG")
        return
    try:
        # 解析控制命令，构建安全的 subprocess 列表参数
        cmd_parts = current_cmd.split()
        amixer_args = ["amixer"] + cmd_parts + [f"{vol}%"]
        subprocess.run(amixer_args, capture_output=True, timeout=5, shell=False)
    except Exception as e:
        log(f"设置音量失败: {e}", "ERROR")


# ============== TTS 语音播报（pyttsx3 + 队列，参考老年端 speech.py） ==============

_speech_engine = None
_speak_queue = queue.Queue(maxsize=100)  # 有界队列，最多 100 条排队
_speech_stop_event = threading.Event()
_speech_thread = None
_speech_lock = threading.RLock()  # 使用 RLock 支持嵌套获取，避免 _speak_worker 中死锁


def init_speech():
    """初始化 pyttsx3 TTS 引擎并启动后台播报线程"""
    global _speech_engine, _speech_thread
    try:
        if _PYTTSX3_AVAILABLE and pyttsx3 is not None:
            _speech_engine = pyttsx3.init()
            _speech_engine.setProperty('volume', VOLUME_INITIAL / _VOLUME_DIVISOR)
            _speech_engine.setProperty('rate', TTS_RATE)
            log("pyttsx3 TTS 引擎初始化成功")
        else:
            log("pyttsx3 未安装，使用 espeak 回退")
            _speech_engine = None
    except Exception as e:
        log(f"pyttsx3 初始化失败，将回退到 espeak: {e}", "WARNING")
        _speech_engine = None

    # 确保停止事件已清除
    if _speech_stop_event.is_set():
        _speech_stop_event.clear()

    # 启动后台播报线程（如果未启动）
    if _speech_thread is None or not _speech_thread.is_alive():
        _speech_thread = threading.Thread(target=_speak_worker, daemon=True)
        _speech_thread.start()
        log("TTS 播报线程已启动")


def _speak_worker():
    """TTS 后台工作线程：从队列取出文本并播报，避免阻塞主线程"""
    global _speech_engine
    while not _speech_stop_event.is_set():
        try:
            item = _speak_queue.get(timeout=1)
            if item is None:
                break
            text, volume = item
            if volume is None:
                with lock:
                    vol = state.get("current_volume", VOLUME_INITIAL)
            else:
                vol = volume

            # 限制音量范围
            vol = max(0, min(100, vol))

            # 先设置 USB 扬声器系统音量
            set_system_volume(vol)

            if _speech_engine:
                try:
                    with _speech_lock:
                        _speech_engine.setProperty('volume', vol / _VOLUME_DIVISOR)
                        _speech_engine.say(text)
                        _speech_engine.runAndWait()
                except Exception as e:
                    log(f"pyttsx3 播报失败: {e}", "ERROR")
                    # 尝试重新初始化引擎
                    if _PYTTSX3_AVAILABLE and pyttsx3 is not None:
                        try:
                            with _speech_lock:
                                _speech_engine = pyttsx3.init()
                                _speech_engine.setProperty('rate', TTS_RATE)
                            log("pyttsx3 引擎已重新初始化", "INFO")
                        except Exception as reinit_e:
                            log(f"pyttsx3 引擎重新初始化失败: {reinit_e}", "ERROR")
                            _speech_engine = None
                    else:
                        _speech_engine = None
            else:
                # 回退到 espeak
                try:
                    # 清理文本中的特殊字符，避免 espeak 解析错误
                    safe_text = text.replace('\n', ' ').replace('\r', ' ').replace('"', '')
                    subprocess.run(["espeak", "-v", "zh", safe_text], timeout=30)
                except Exception as e:
                    log(f"espeak 回退播报失败: {e}", "ERROR")

            log(f"语音播报: {text} (音量 {vol})")
        except queue.Empty:
            continue
        except Exception as e:
            log(f"TTS 工作线程异常: {e}", "ERROR")
            time.sleep(1)

    log("TTS 工作线程已退出")


def tts_speak(text, volume=None):
    """语音播报（非阻塞，加入队列由后台线程处理）。队列满时丢弃最旧的一条"""
    try:
        _speak_queue.put((text, volume), timeout=0.1)
    except queue.Full:
        # 队列已满，丢弃最旧的（后台还在大量堆积时，优先保证新消息播送）
        try:
            _speak_queue.get_nowait()
            _speak_queue.put((text, volume), timeout=0.1)
        except queue.Empty:
            pass  # 极端情况下丢弃旧消息


def stop_speech():
    """停止 TTS 服务"""
    _speech_stop_event.set()
    _speak_queue.put(None)
    if _speech_engine:
        try:
            _speech_engine.stop()
        except Exception:
            pass
    log("TTS 服务已停止")


def buzzer_beep(times=1, duration=0.2):
    """蜂鸣器提示，优先使用 pinpong 板载蜂鸣器音效，回退到数字引脚"""
    if buzzer is None:
        return
    try:
        if hasattr(buzzer, "play"):
            # 使用 pinpong 板载蜂鸣器音效（BA_DING）
            for i in range(times):
                buzzer.play(buzzer.BA_DING, buzzer.Once)
                time.sleep(duration)
        else:
            # 回退到数字引脚控制
            for _ in range(times):
                buzzer.write_digital(1)
                time.sleep(duration)
                buzzer.write_digital(0)
                time.sleep(0.1)
    except Exception as e:
        log(f"蜂鸣器异常: {e}", "ERROR")


def capture_photo(filename=None, timeout=10):
    """使用系统 fswebcam 命令拍照，不依赖 cv2。线程安全：多线程并发拍照时串行化
    
    Args:
        filename: 照片文件名，默认使用时间戳生成
        timeout: 拍照超时时间（秒）
    
    Returns:
        str/None: 照片文件路径，失败返回 None
    """
    if filename is None:
        filename = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    # 安全过滤：文件名仅允许字母数字下划线点
    if not re.match(r'^[\w\.\-]+$', filename):
        log(f"拍照文件名非法: {filename}", "ERROR")
        return None
    path = os.path.join(PHOTO_DIR, filename)
    with _camera_lock:
        try:
            os.makedirs(PHOTO_DIR, exist_ok=True)
            # 使用列表形式避免命令注入风险
            cmd = ["fswebcam", "-r", "640x480", "--no-banner", path]
            r = subprocess.run(cmd, capture_output=True, timeout=timeout, shell=False)
            if r.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 0:
                return path
            log(f"fswebcam 失败: {r.stderr.decode('utf-8', errors='ignore')}", "WARNING")
        except subprocess.TimeoutExpired:
            log("拍照超时", "ERROR")
        except FileNotFoundError:
            log("fswebcam 命令未找到，请安装 fswebcam", "ERROR")
        except Exception as e:
            log(f"拍照失败: {e}", "ERROR")
    return None


def image_to_base64(path):
    """将图片转为 base64，文件超过 MAX_IMAGE_SIZE 则跳过避免 OOM"""
    try:
        # 修复：检查文件是否存在
        if not path or not os.path.exists(path):
            log(f"图片文件不存在: {path}", "WARNING")
            return None
        size = os.path.getsize(path)
        if size > MAX_IMAGE_SIZE:
            log(f"图片过大 ({size} bytes)，跳过 base64 编码", "WARNING")
            return None
        if size == 0:
            log(f"图片文件为空: {path}", "WARNING")
            return None
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        log(f"图片转 base64 失败: {e}", "ERROR")
        return None


# ============== 网络通信（仅使用 urllib） ==============

def _auth_headers(extra=None):
    """构建请求头，自动携带 X-Device-Token（已注册时）"""
    headers = {
        "Content-Type": "application/json",
        # 添加 User-Agent 避免 Cloudflare 1010 拦截（urllib 默认 UA 被封禁）
        "User-Agent": "Mozilla/5.0 (compatible; M10MedicationChecker/1.0)",
    }
    token = _get_device_token()
    if token:
        headers["X-Device-Token"] = token
    if extra:
        headers.update(extra)
    return headers


def http_request(url, payload=None, timeout=None, headers=None):
    """封装 urllib，payload 为 dict 时 POST，否则 GET。
    自动携带 X-Device-Token（已注册后）。
    
    Returns:
        dict/list/None: 请求成功返回解析后的 JSON，失败返回 None。
        业务错误时返回 {"status": "error", "message": "..."} 格式。
    """
    if timeout is None:
        timeout = HTTP_REQUEST_TIMEOUT
    try:
        hdrs = _auth_headers(headers)
        data = None
        method = "GET"
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            method = "POST"
        # GET 请求不需要 Content-Type，直接构建不带该 header 的 headers
        if method == "GET":
            hdrs.pop("Content-Type", None)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.getcode()
            body = resp.read().decode("utf-8")
            # 修复：空响应体视为成功（某些接口返回空 200 OK）
            if not body:
                return {"status": "ok", "_empty_response": True}
            # 尝试解析 JSON，非 JSON 响应返回原始文本
            try:
                result = json.loads(body)
                # 检查业务状态码：status != "ok" 时返回错误标识，调用方需检查
                if isinstance(result, dict) and result.get("status") and result.get("status") != "ok":
                    error_msg = result.get("message", "Unknown error")
                    log(f"HTTP 业务错误: {error_msg}", "WARNING")
                    result["_error"] = True  # 标记为业务错误，调用方可检查
                return result
            except (json.JSONDecodeError, ValueError):
                # 非 JSON 响应（如纯文本）
                return {"raw_text": body, "status": "ok"}
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        # 检测需要重新注册的情况：
        # - 404"设备未注册"：device_id 在服务器不存在
        # - 403"设备令牌无效或缺失"：本地 token 与服务端不匹配（设备 ID 变更或 token 失效）
        if e.code == 404 and "设备未注册" in error_body:
            log("设备未注册（device_id 在服务器不存在），标记需要重新注册", "WARNING")
            _device_needs_re_register.set()
        elif e.code == 403:
            # 403 错误可能是多种原因，只要涉及设备令牌或认证问题都需要重新注册
            # 检查响应体是否包含相关错误信息
            body_lower = error_body.lower()
            if "device_token" in body_lower or "token" in body_lower or "令牌" in error_body:
                log("设备令牌无效或缺失（本地 token 与服务端不匹配），标记需要重新注册", "WARNING")
                _device_needs_re_register.set()
            else:
                log(f"HTTP 403 请求被拒绝: {url}", "WARNING")
        # 日志脱敏：仅记录错误码和URL，不记录响应体内容（防止敏感信息泄露）
        log(f"HTTP {e.code} 请求失败: {url}", "ERROR")
        return None
    except urllib.error.URLError as e:
        # 网络不通、DNS解析失败、连接超时等
        log(f"URL请求失败 {url}: {e.reason}", "ERROR")
        return None
    except Exception as e:
        log(f"HTTP 请求失败 {url}: {e}", "ERROR")
        return None


def register_device():
    """设备注册（新版 API），成功后保存 device_token

    http_request 自动通过 _auth_headers() 携带 X-Device-Token（如果设备有 token），
    服务端据此区分：
    - 无 token / token 不匹配 → 重新生成并返回新 token（设备本地 token 丢失恢复）
    - token 匹配 → 仅更新心跳，不返回 token（正常心跳）
    """
    payload = {
        "device_id": DEVICE_ID,
        "device_name": None,
    }
    try:
        resp = http_request(API_REGISTER, payload)
    except Exception as e:
        log(f"设备注册异常: {e}", "ERROR")
        return False

    if resp is None:
        log("设备注册失败：无响应", "ERROR")
        return False

    if not isinstance(resp, dict):
        log(f"设备注册响应格式错误: {resp}", "ERROR")
        return False

    if resp.get("status") == "ok":
        token = resp.get("device_token")
        if token:
            # 修复：首次注册或 token 恢复情况，保存新 token
            _set_device_token(token)
            save_device_token(token)
            log("设备注册成功，已获取 device_token")
            return True
        else:
            # 服务端未返回 token：设备已注册且携带的 token 匹配（心跳模式）
            # 修复：检查本地是否已有 token，如果有则确认成功，否则视为失败
            existing_token = _get_device_token()
            if existing_token:
                log("设备已注册（心跳模式），token 有效")
                return True
            else:
                log("设备注册失败：服务端未返回 token 且本地无 token", "ERROR")
                return False
    else:
        log(f"设备注册失败: {resp.get('message', resp)}", "ERROR")
        return False


def send_heartbeat():
    """发送心跳到 register 接口

    http_request 自动通过 _auth_headers() 携带 X-Device-Token（如果设备有 token），
    服务端据此区分：
    - token 匹配 → 仅更新心跳，不返回 token（正常心跳）
    - 无 token / token 不匹配 → 重新生成并返回新 token（token 丢失恢复）
    """
    payload = {
        "device_id": DEVICE_ID,
        "device_name": None,
    }
    try:
        resp = http_request(API_REGISTER, payload)
    except Exception as e:
        log(f"心跳异常: {e}", "ERROR")
        return False

    if resp is None:
        return False

    if isinstance(resp, dict) and resp.get("status") == "ok":
        # token 匹配时服务端不返回 token（心跳模式）
        # 无 token 或 token 不匹配时服务端返回新 token（恢复模式）
        token = resp.get("device_token")
        if token:
            _set_device_token(token)
            save_device_token(token)
            log("心跳获取新 token，已保存", "INFO")
        else:
            log("心跳发送成功", "INFO")
        return True
    # 修复：检查业务错误（_error 标记），区分网络错误和业务错误
    elif isinstance(resp, dict) and resp.get("_error"):
        error_msg = resp.get("message", "未知错误")
        log(f"心跳业务错误: {error_msg}", "ERROR")
        return False
    return False


def save_device_token(token):
    """将 device_token 持久化到配置文件，重启后可恢复"""
    if not token:
        log("device_token 无效，未保存", "WARNING")
        return
    try:
        cfg = load_config()
        cfg["device_token"] = token
        cfg["device_token_saved_at"] = datetime.datetime.now().isoformat()
        save_config(cfg)
        log("device_token 已保存")
    except Exception as e:
        log(f"保存 device_token 失败: {e}", "WARNING")


def load_device_token():
    """从配置文件恢复 device_token
    
    Returns:
        bool: 成功恢复返回 True，否则返回 False
    
    Raises:
        无
    """
    try:
        cfg = load_config()
        if cfg:
            token = cfg.get("device_token")
            if token and isinstance(token, str) and len(token) > 10:
                # 简单验证 token 格式（至少10个字符，不含空格）
                if token.isspace() or any(c.isspace() for c in token):
                    log("device_token 格式无效（包含空格）", "WARNING")
                    return False
                _set_device_token(token)
                log("device_token 已从本地恢复")
                return True
            elif token:
                log(f"device_token 格式无效: 长度不足 ({len(token)} 字符)", "WARNING")
    except Exception as e:
        log(f"加载 device_token 失败: {e}", "WARNING")
    return False


def clear_device_token():
    """清除设备令牌（内存 + 本地配置文件）

    当服务器返回 404"设备未注册"时调用，清除失效的旧 token，
    使后续请求不再携带无效 token，并触发重新注册。
    """
    _set_device_token(None)
    try:
        cfg = load_config()
        if cfg and cfg.get("device_token"):
            cfg.pop("device_token", None)
            cfg.pop("device_token_saved_at", None)
            save_config(cfg)
            log("已清除本地 device_token（设备未注册，token 已失效）")
    except Exception as e:
        log(f"清除本地 device_token 失败: {e}", "WARNING")


def sync_reminders():
    """获取用药计划（新版 API：GET /device/schedule/{id}）"""
    try:
        resp = http_request(API_SCHEDULE)
    except Exception as e:
        log(f"同步用药计划异常: {e}", "ERROR")
        return False

    if resp is None:
        log("同步用药计划失败：网络请求无响应", "WARNING")
        return False

    # 检查是否返回了错误状态（status 存在但不是 "ok" 视为错误）
    if isinstance(resp, dict) and resp.get("status") is not None and resp.get("status") != "ok":
        log(f"同步用药计划返回错误: {resp.get('message', resp)}", "WARNING")
        return False

    plans = []
    if isinstance(resp, list):
        plans = resp
    elif isinstance(resp, dict):
        # 使用 is not None 判断，避免空列表 [] 被 or 误判为 falsy
        for key in ("plans", "data", "items"):
            val = resp.get(key)
            if val is not None and isinstance(val, list):
                plans = val
                break

    # 验证 plans 数据有效性
    valid_plans = []
    for p in plans:
        if isinstance(p, dict):
            valid_plans.append(p)
        else:
            log(f"跳过无效的用药计划条目: {p}", "WARNING")

    with lock:
        state["reminders"] = _convert_plans_to_reminders(valid_plans)
        state["medicines"] = _convert_plans_to_medicines(valid_plans)
        state["last_sync"] = datetime.datetime.now().isoformat()
    log(f"同步用药计划: {len(valid_plans)} 条")
    return True


def _parse_frequency_per_day(frequency_str):
    """从 frequency 字符串解析每日服药次数
    
    支持格式：
    - "每日3次" / "每天3次" / "一日3次" -> 3
    - "3次" -> 3
    - "每8小时" -> max(1, 24//8) = 3
    - "每8小时一次" -> 3
    - "每周7次" -> 7/7 = 1
    - "每周3次" -> 3/7 ≈ 0.43，向上取整为 1
    - "每3天1次" -> 1/3 ≈ 0.33，向上取整为 1
    - "每日" / "每天" -> 1
    - "1次/日" -> 1
    - "3/d" -> 3
    """
    if not frequency_str:
        return 1
    try:
        freq_str = str(frequency_str)
        
        # 1. 匹配 "数字次" 格式，如 "3次"、"2次"
        m = re.search(r'(\d+)\s*次', freq_str)
        if m:
            return int(m.group(1))
        
        # 2. 匹配 "每日N次" / "每天N次" / "一日N次"
        m = re.search(r'(?:每日|每天|一日)\s*(\d+)', freq_str)
        if m:
            return int(m.group(1))
        
        # 3. 匹配 "每 N 小时" 或 "每 N 小时一次"，计算每天次数
        m = re.search(r'每\s*(\d+)\s*小时', freq_str)
        if m:
            hours = int(m.group(1))
            if hours > 0:
                return max(1, 24 // hours)
        
        # 4. 匹配 "每周N次"，计算每天平均次数（向上取整）
        m = re.search(r'每周\s*(\d+)\s*次', freq_str)
        if m:
            times_per_week = int(m.group(1))
            return max(1, (times_per_week + 6) // 7)  # 向上取整
        
        # 5. 匹配 "每N天(一)次"，计算每天次数
        m = re.search(r'每\s*(\d+)\s*天', freq_str)
        if m:
            days = int(m.group(1))
            if days > 0:
                return max(1, 1)  # 至少返回1，表示每天可能需要服药
        
        # 6. 匹配 "N次/日" 或 "N/d"
        m = re.search(r'(\d+)\s*次?\s*/\s*(?:日|d)', freq_str, re.IGNORECASE)
        if m:
            return int(m.group(1))
        
        # 7. 匹配 "每日" / "每天" 但无数字
        if '每日' in freq_str or '每天' in freq_str:
            return 1
            
    except Exception:
        pass
    return 1


def _parse_dose_count(dosage_str):
    """从剂量字符串解析每次服用数量，如 '1片' -> 1, '2袋' -> 2"""
    if not dosage_str:
        return 1
    try:
        # 匹配开头的数字
        m = re.match(r'\s*(\d+)\s*', str(dosage_str))
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 1


def _convert_plans_to_reminders(plans):
    """将 FamilyMedicationPlan 数组转换为旧版 reminders 格式

    Args:
        plans: FamilyMedicationPlan 对象列表

    Returns:
        list: reminders 提醒列表，每项包含：
            - id: 提醒ID（使用计划ID或药品名）
            - medicine_name: 药品名称
            - dose: 剂量描述
            - times: 服药时间点列表（如 ["09:00", "13:00", "17:00"]）
            - days: 服药日期列表（1-7，周一至周日）
            - medicine_id: 药品ID
            - dose_count: 每次服用数量（从 dosage 字段解析）
            - user_name: 用户名
            - frequency: 服用频率描述

    Raises:
        TypeError: 当 plans 不是列表类型时

    Note:
        - days 字段支持多种格式：days、weekdays、day_of_week
        - 当 days 未指定时，默认为全周（1-7）
    """
    reminders = []
    for p in plans:
        times = p.get("schedule_times", [])
        drug_name = p.get("drug_name", "")
        plan_id = p.get("id")
        freq = p.get("frequency", "每日")
        dosage = p.get("dosage", "1片")
        # 解析 days：优先使用 API 传入的 weekday/days 字段，默认全周
        days = p.get("days") or p.get("weekdays") or p.get("day_of_week")
        if not days:
            days = [1, 2, 3, 4, 5, 6, 7]
        elif isinstance(days, (list, tuple)):
            days = [int(d) for d in days if str(d).isdigit()] or [1, 2, 3, 4, 5, 6, 7]
        elif isinstance(days, int):
            days = [days]
        # 解析 dose_count：从 dosage 字段提取数量
        dose_count = _parse_dose_count(dosage)
        reminders.append({
            "id": plan_id if plan_id is not None else drug_name,
            "medicine_name": drug_name,
            "dose": dosage,
            "times": times if isinstance(times, list) else [times],
            "days": days,
            "medicine_id": plan_id,
            "dose_count": dose_count,
            "user_name": "老人",
            "frequency": freq,
        })
    return reminders


def _convert_plans_to_medicines(plans):
    """将 FamilyMedicationPlan 数组转换为旧版 medicines 库存格式

    Args:
        plans: FamilyMedicationPlan 对象列表，每个对象包含：
            - id: 计划ID
            - drug_name: 药品名称
            - frequency: 服用频率（如"每日3次"、"每8小时一次"）
            - remaining_quantity: 剩余数量（浮点数）
            - total_quantity: 总数量（浮点数）
            - low_stock_threshold: 低库存阈值
            - unit: 单位（如"片"）

    Returns:
        list: medicines 库存列表，每项包含：
            - id: 药品ID
            - name: 药品名称
            - remaining: 剩余数量（整数）
            - per_time: 每次服用量
            - frequency_per_day: 每日服用次数
            - threshold: 低库存阈值
            - unit: 单位
            - dosage: 剂量描述
            - total_quantity: 总数量
    """
    medicines = []
    for p in plans:
        plan_id = p.get("id")
        drug_name = p.get("drug_name", "")
        freq = p.get("frequency", "每日")
        freq_per_day = _parse_frequency_per_day(freq)
        dosage = p.get("dosage", "1片")
        remaining = p.get("remaining_quantity", 0)
        # 修复：正确处理 remaining_quantity，可能是浮点数
        try:
            remaining = int(float(remaining))
        except (ValueError, TypeError):
            remaining = 0
        # 修复：正确处理 total_quantity，添加异常保护
        total_quantity = 0
        try:
            total_val = p.get("total_quantity")
            if total_val is not None:
                total_quantity = int(float(total_val))
        except (ValueError, TypeError):
            total_quantity = 0
        # 修复：安全获取 per_time，处理 None 和非数字情况
        per_time = _parse_dose_count(dosage)
        per_time = max(1, int(per_time)) if per_time is not None and isinstance(per_time, (int, float)) else 1
        # 修复：安全获取 frequency_per_day，确保为正整数
        freq_per_day = max(1, int(freq_per_day)) if freq_per_day is not None and isinstance(freq_per_day, (int, float)) else 1

        medicines.append({
            "id": plan_id if plan_id is not None else drug_name,
            "name": drug_name,
            "remaining": remaining,
            "per_time": per_time,
            "frequency_per_day": freq_per_day,
            "threshold": p.get("low_stock_threshold", 5),
            "unit": p.get("unit", "片"),
            "dosage": dosage,
            # 新增：保存 total_quantity 用于计算总库存量
            "total_quantity": total_quantity,
        })
    return medicines


def upload_log(event_type, detail, photo_path=None):
    """上报设备事件（新版 API：POST /device/message + /device/upload）
    
    Args:
        event_type: 事件类型（如 'confirm_take', 'emergency' 等）
        detail: 事件详情，可以是 dict、str、int、float 或 None
        photo_path: 照片文件路径（可选）
    
    Returns:
        bool: 上传成功返回 True，失败返回 False
    """
    # 修复：验证 event_type 有效性（类型检查 + 空字符串检查）
    if not event_type or not isinstance(event_type, str) or not event_type.strip():
        log(f"upload_log: event_type 无效: {event_type}", "ERROR")
        return False

    # 根据 DeviceMessage schema，data 可以是 object 或 null
    if isinstance(detail, dict):
        data_field = detail
    elif detail is None:
        data_field = None
    else:
        data_field = {"detail": str(detail)}

    # 构建 content 字段：字符串直接使用，其他类型转为 JSON
    if detail is None:
        content_field = ""
    elif isinstance(detail, (str, int, float)):
        content_field = str(detail)
    else:
        content_field = json.dumps(detail, ensure_ascii=False)

    msg_payload = {
        "device_id": DEVICE_ID,
        "message_type": event_type,
        "content": content_field,
        "data": data_field,
    }
    photo_base64 = None
    if photo_path and os.path.exists(photo_path):
        photo_size = os.path.getsize(photo_path)
        # 限制照片大小 <= MAX_PHOTO_SIZE (500KB)，避免 base64 编码后内存膨胀
        if photo_size > MAX_PHOTO_SIZE:
            log(f"照片过大 ({photo_size} bytes)，跳过上传", "WARNING")
        else:
            photo_base64 = image_to_base64(photo_path)
            # image_to_base64 内部也有 1MB 限制，需再次检查
            if photo_base64 is None:
                log("照片 base64 编码失败或超过 1MB 限制", "WARNING")

    # 1. 上传消息事件
    msg_resp = http_request(API_MESSAGE, msg_payload)
    # 检查是否为业务错误（含 _error 标记）或 HTTP 错误
    msg_ok = msg_resp is not None and not (isinstance(msg_resp, dict) and msg_resp.get("_error"))

    # 消息发送失败时直接写入离线队列，无需尝试上传照片
    if not msg_ok:
        log(f"日志消息发送失败，写入本地队列: {event_type}")
        queue_local_log(msg_payload, photo_base64)
        return False

    # 2. 如有照片，单独上传
    photo_ok = True
    if photo_base64:
        upload_payload = {
            "device_id": DEVICE_ID,
            "image_base64": photo_base64,
            "note": f"{event_type} photo",
        }
        upload_resp = http_request(API_UPLOAD, upload_payload)
        photo_ok = upload_resp is not None and not (isinstance(upload_resp, dict) and upload_resp.get("_error"))
        if not photo_ok:
            log(f"照片上传失败，但消息已发送成功: {event_type}")

    # 照片上传成功
    if msg_ok and photo_ok:
        log(f"日志上传成功: {event_type}")
        return True

    # 照片上传失败时仅入队照片数据（消息已发送成功，无需重复入队消息）
    if msg_ok and not photo_ok:
        log(f"照片上传失败，但消息已发送成功: {event_type}")
        if photo_base64:
            photo_payload = {"device_id": DEVICE_ID, "image_base64": photo_base64, "note": f"{event_type} photo"}
            queue_local_log(photo_payload)
        return False

    # 消息成功或照片失败的其他情况（消息发送失败时已在前面处理过）
    return False


def queue_local_log(payload, photo_base64=None):
    """将日志条目写入本地离线队列。队列最多保留 MAX_QUEUE_SIZE 条，超出时丢弃最旧的"""
    # 修复：验证 payload 有效性
    if not payload or not isinstance(payload, dict):
        log("queue_local_log: payload 无效", "ERROR")
        return
    with _queue_lock:
        try:
            queue = []
            if os.path.exists(QUEUE_FILE):
                try:
                    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                        queue = json.load(f)
                except (json.JSONDecodeError, ValueError):
                    # 队列文件损坏，重新开始
                    log("离线日志队列文件损坏，重新创建", "WARNING")
                    queue = []
            entry = payload.copy()
            if photo_base64:
                entry["_photo"] = photo_base64
            queue.append(entry)
            # 限制队列大小，超过 MAX_QUEUE_SIZE 条时丢弃最旧的
            if len(queue) > MAX_QUEUE_SIZE:
                queue = queue[-MAX_QUEUE_SIZE:]
                log(f"离线日志队列超过 {MAX_QUEUE_SIZE} 条，已裁剪", "WARNING")
            tmp_path = QUEUE_FILE + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(queue, f, ensure_ascii=False)
            os.replace(tmp_path, QUEUE_FILE)
        except Exception as e:
            log(f"本地日志队列写入失败: {e}", "ERROR")


_flush_in_progress = threading.Lock()  # 防止并发刷新（使用 Lock 确保严格互斥）


def flush_local_logs():
    """刷新本地离线日志队列：读取 → 逐条上传 → 写回剩余
    
    使用 threading.Lock 防止并发调用导致重复上传
    
    Returns:
        None
    """
    if not os.path.exists(QUEUE_FILE):
        return

    # 防止并发刷新：使用 Lock 尝试获取，获取失败直接返回
    if not _flush_in_progress.acquire(blocking=False):
        log("日志刷新正在进行中，跳过本次调用", "DEBUG")
        return

    try:
        # 读取阶段：在锁内读取队列快照后释放锁，网络请求在锁外执行
        with _queue_lock:
            try:
                with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                    queue = json.load(f)
                if not isinstance(queue, list):
                    log("离线日志队列格式错误，已重置", "ERROR")
                    queue = []
            except (json.JSONDecodeError, ValueError) as e:
                log(f"读取本地日志队列失败（文件损坏）: {e}", "ERROR")
                # 备份损坏的队列文件（添加 PID，避免并发冲突）
                try:
                    backup_path = QUEUE_FILE + f".bak.{int(time.time())}.{os.getpid()}"
                    os.rename(QUEUE_FILE, backup_path)
                except Exception:
                    pass
                queue = []  # 损坏文件处理后继续，使用空队列
            except Exception as e:
                log(f"读取本地日志队列失败: {e}", "ERROR")
                queue = []  # 其他异常也使用空队列继续处理

        # 队列为空时，写回空队列并结束，确保 finally 释放锁
        if not queue:
            with _queue_lock:
                try:
                    tmp_path = QUEUE_FILE + ".tmp"
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        json.dump([], f, ensure_ascii=False)
                        f.flush()
                    os.replace(tmp_path, QUEUE_FILE)
                except Exception:
                    pass
            return

        remain = []
        success_count = 0
        fail_count = 0

        for entry in queue:
            try:
                photo = entry.get("_photo")
                msg_payload = {k: v for k, v in entry.items() if k != "_photo"}

                # 验证 entry 有效性
                if not isinstance(msg_payload, dict) or not msg_payload.get("device_id"):
                    log(f"跳过无效日志条目: {entry}", "WARNING")
                    fail_count += 1
                    continue

                msg_resp = http_request(API_MESSAGE, msg_payload)
                # 检查 HTTP 错误和业务错误（_error 标记）
                msg_ok = msg_resp is not None and not (isinstance(msg_resp, dict) and msg_resp.get("_error"))

                # 消息发送失败时直接保留条目（剥离照片数据避免内存膨胀）
                if not msg_ok:
                    # 修复：剥离 base64 照片数据后再保留，避免长期占用内存
                    slim_entry = {k: v for k, v in entry.items() if k != "_photo"}
                    remain.append(slim_entry)
                    fail_count += 1
                    continue

                # 仅当 photo 非空且为有效字符串时才上传照片
                photo_ok = True
                if photo and isinstance(photo, str) and len(photo) > 0:
                    upload_resp = http_request(API_UPLOAD, {
                        "device_id": DEVICE_ID,
                        "image_base64": photo,
                        "note": "offline upload",
                    })
                    # 同样检查业务错误
                    photo_ok = upload_resp is not None and not (isinstance(upload_resp, dict) and upload_resp.get("_error"))

                if msg_ok and photo_ok:
                    success_count += 1
                else:
                    # 上传失败（无论是 HTTP 错误还是业务错误），保留条目等待下次刷新
                    # 修复：仅保留消息部分，剥离照片 base64 数据
                    slim_entry = {k: v for k, v in entry.items() if k != "_photo"}
                    remain.append(slim_entry)
                    fail_count += 1
            except Exception as e:
                log(f"刷新日志条目异常: {e}", "ERROR")
                remain.append(entry)
                fail_count += 1

        # 写回阶段：在锁内写回剩余队列（原子写入）
        with _queue_lock:
            try:
                tmp_path = QUEUE_FILE + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(remain, f, ensure_ascii=False)
                    f.flush()
                os.replace(tmp_path, QUEUE_FILE)
            except Exception as e:
                log(f"写回本地日志队列失败: {e}", "ERROR")

        log(f"刷新本地日志: 成功 {success_count}, 失败 {fail_count}, 剩余 {len(remain)}")
    finally:
        # 释放互斥锁，确保下次可以调用
        _flush_in_progress.release()


def query_drug_by_ocr(text):
    """AI 问答替代旧版药品查询（POST /public/ai/ask）
    
    Args:
        text: OCR 识别到的药品文本
    
    Returns:
        dict/None: AI 回答结果，失败返回 None
    """
    if not text or not isinstance(text, str) or not text.strip():
        log("query_drug_by_ocr: 文本参数无效", "WARNING")
        return None
    try:
        payload = {
            "question": f"识别药品：{text}",
            "device_id": DEVICE_ID,
        }
        resp = http_request(API_AI_ASK, payload)
        # 修复：检查 HTTP 错误、业务错误和空响应
        if resp is None:
            log("query_drug_by_ocr: 请求无响应", "WARNING")
            return None
        if isinstance(resp, dict) and resp.get("_error"):
            log(f"query_drug_by_ocr: AI 问答业务错误 - {resp.get('message', '未知错误')}", "WARNING")
            return None
        if isinstance(resp, dict) and resp.get("_empty_response"):
            log("query_drug_by_ocr: AI 问答返回空响应", "WARNING")
            return None
        return resp
    except Exception as e:
        log(f"query_drug_by_ocr 异常: {e}", "ERROR")
        return None


def query_refill(medicine_id):
    """查询补货信息（AI 问答方式）
    
    Args:
        medicine_id: 药品 ID
    
    Returns:
        dict/None: AI 回答结果，失败返回 None
    """
    if not medicine_id:
        log("query_refill: medicine_id 无效", "WARNING")
        return None
    try:
        payload = {
            "question": f"药品 ID {medicine_id} 最优购买渠道",
            "device_id": DEVICE_ID,
        }
        resp = http_request(API_AI_ASK, payload)
        # 修复：检查 HTTP 错误、业务错误和空响应
        if resp is None:
            log("query_refill: 请求无响应", "WARNING")
            return None
        if isinstance(resp, dict) and resp.get("_error"):
            log(f"query_refill: AI 问答业务错误 - {resp.get('message', '未知错误')}", "WARNING")
            return None
        if isinstance(resp, dict) and resp.get("_empty_response"):
            log("query_refill: AI 问答返回空响应", "WARNING")
            return None
        return resp
    except Exception as e:
        log(f"query_refill 异常: {e}", "ERROR")
        return None


# 缓存紧急联系人信息，避免每次紧急呼叫都读取配置文件
_emergency_contact_cache = None


def notify_emergency():
    """紧急通知家属（POST /device/message，message_type=emergency）
    
    Returns:
        bool: 通知成功返回 True，失败返回 False
    
    Raises:
        无（所有异常已内部捕获）
    """
    global _emergency_contact_cache
    # 优先使用缓存的紧急联系人，避免每次都读取配置文件
    with _emergency_lock:
        if _emergency_contact_cache is None:
            try:
                cfg = load_config()
                if isinstance(cfg, dict):
                    contact = cfg.get("emergency_contact", "120")
                    if contact and isinstance(contact, str) and contact.strip():
                        _emergency_contact_cache = contact.strip()
                    else:
                        _emergency_contact_cache = "120"
                else:
                    _emergency_contact_cache = "120"
            except Exception as e:
                log(f"读取紧急联系人配置异常: {e}", "WARNING")
                _emergency_contact_cache = "120"
        contact = _emergency_contact_cache
    
    payload = {
        "device_id": DEVICE_ID,
        "message_type": "emergency",
        "content": f"紧急呼叫，联系电话 {contact}",
        "data": {"contact": contact, "timestamp": datetime.datetime.now().isoformat()},
    }
    
    try:
        resp = http_request(API_MESSAGE, payload)
        # 检查 HTTP 错误和业务错误
        if resp is not None and not (isinstance(resp, dict) and resp.get("_error")):
            tts_speak("紧急通知已发送给家属")
            return True
        elif resp is None:
            log("紧急通知失败: 网络请求无响应", "ERROR")
        else:
            error_msg = resp.get("message", "未知错误") if isinstance(resp, dict) else str(resp)
            log(f"紧急通知失败: {error_msg}", "ERROR")
    except Exception as e:
        log(f"紧急通知请求异常: {e}", "ERROR")
    
    tts_speak("紧急通知发送失败，请手动拨打 120")
    return False


def device_offline():
    """设备主动下线通知（在程序退出时调用，通知服务器设备已离线）
    
    通过 POST /api/v1/public/device/offline 发送下线通知，
    将 last_heartbeat_at 置为很早的时间，使 is_online 立即为 false。
    
    Returns:
        None
    
    Raises:
        无（所有异常已内部捕获）
    """
    try:
        payload = {"device_id": DEVICE_ID}
        resp = http_request(API_OFFLINE, payload, timeout=5)
        if resp is None:
            log("设备下线通知: 网络请求无响应", "WARNING")
        elif isinstance(resp, dict) and resp.get("_error"):
            error_msg = resp.get("message", "未知错误")
            log(f"设备下线通知: 业务错误 - {error_msg}", "WARNING")
        else:
            log("设备下线通知发送成功")
    except Exception as e:
        log(f"设备下线通知失败: {e}", "WARNING")


# ============== 提醒核心 ==============

def reset_fixed_trigger_if_new_day():
    """跨天时清空当日已触发固定提醒记录，避免第二天漏触发"""
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    with lock:
        if state["current_date"] != today:
            state["current_date"] = today
            state["triggered_fixed_times"] = set()
            log(f"日期切换到 {today}，已重置固定提醒触发记录")


def check_fixed_reminders():
    """检查固定服药提醒时间（9:00 / 13:00 / 17:00），每天每个时间点仅触发一次"""
    reset_fixed_trigger_if_new_day()
    now_str = datetime.datetime.now().strftime("%H:%M")
    to_trigger = None
    with lock:
        for t in FIXED_REMINDER_TIMES:
            if t == now_str and t not in state["triggered_fixed_times"]:
                state["triggered_fixed_times"].add(t)
                to_trigger = {
                    "id": f"fixed_{t}",
                    "user_name": "老人",
                    "medicine_name": "药品",
                    "dose": "请按医嘱服用",
                    "medicine_id": None,
                    "dose_count": 1,
                }
                log(f"触发固定时间提醒: {t}")
                break
    if to_trigger:
        trigger_alert(to_trigger)


def check_reminders():
    """检查用药提醒：在锁外获取数据快照，锁内做最小化检查"""
    now = datetime.datetime.now()
    now_str = now.strftime("%H:%M")
    weekday = now.weekday() + 1

    # 锁内获取 reminders 快照，避免长时间持锁
    with lock:
        reminders_snapshot = list(state.get("reminders", []))
        active_alerts_ids = set(state.get("active_alerts", {}).keys())

    to_trigger = None
    for r in reminders_snapshot:
        tid = r.get("id")
        times = r.get("times", [])
        # 兼容 times 为 None 的情况
        if times is None:
            times = []
        days = r.get("days")
        if not days or not isinstance(days, list) or len(days) == 0:
            days = [1, 2, 3, 4, 5, 6, 7]
        if weekday not in days:
            continue
        for t in times:
            if t == now_str and tid not in active_alerts_ids:
                to_trigger = r
                break
        if to_trigger:
            break

    # 在锁外调用 trigger_alert，避免锁嵌套
    if to_trigger:
        trigger_alert(to_trigger)


def trigger_alert(reminder):
    """触发吃药提醒：存储状态、更新界面、启动提醒循环线程
    
    将提醒信息存入 state["active_alerts"]，更新 GUI 显示提醒界面，
    并在后台线程中启动 alert_loop 进行响铃提醒。
    
    Args:
        reminder: 提醒字典，需包含 id、user_name、medicine_name、dose 等字段
    
    Returns:
        None
    
    Raises:
        无（参数无效时记录错误并返回）
    """
    # 添加 None 检查
    if reminder is None or not isinstance(reminder, dict):
        log("trigger_alert 收到无效的 reminder 参数", "ERROR")
        return
    # 立即创建副本，避免外部修改导致数据竞争
    reminder_copy = dict(reminder)
    tid = reminder_copy.get("id")
    name = reminder_copy.get("user_name", "老人")
    drug = reminder_copy.get("medicine_name", "药品")
    dose = reminder_copy.get("dose", "")
    if not tid:
        log("trigger_alert: reminder 缺少 id 字段", "ERROR")
        return
    with lock:
        state["active_alerts"][tid] = {
            "started_at": datetime.datetime.now(),
            "volume": VOLUME_INITIAL,
            "reminder": reminder_copy,  # 副本，避免原始字典被修改
        }
    msg = f"{name}，该吃 {drug} 了，每次 {dose}"
    log(f"触发提醒: {msg}")
    update_gui_reminder(name, drug, dose)
    # 切换 HuskyLens 到人脸识别模式（到时间了或按提醒按钮触发）
    switch_huskylens_to_face()
    # 清除中断事件，准备新的提醒循环
    _alert_interrupt_event.clear()
    threading.Thread(target=alert_loop, args=(tid,), daemon=True).start()


# 提醒中断事件：用于 alert_loop() 的可中断等待
_alert_interrupt_event = threading.Event()


def alert_loop(tid):
    """提醒循环：检测人脸ID，循环播报直到按"已吃药"按钮确认

    流程：
    1. 检测目标人脸ID（TARGET_FACE_ID=1）
    2. 未检测到时：循环播报"请{老人名字}来吃药"
    3. 检测到时：循环播报用药信息（在线用计划，离线用测试药品）
    4. 持续直到按"已吃药"按钮（active_alerts 移除）或达到最大重试次数

    Args:
        tid: 提醒 ID

    Returns:
        None
    """
    retry_count = 0
    target_name = get_face_name(TARGET_FACE_ID)
    # 修复：如果无法获取真实名字（HuskyLens 不可用），使用默认称呼
    if target_name == f"id{TARGET_FACE_ID}":
        target_name = "老人"
        log(f"无法获取人脸ID {TARGET_FACE_ID} 的名字，使用默认称呼: {target_name}", "DEBUG")
    log(f"提醒循环启动，目标人脸ID={TARGET_FACE_ID}，名字={target_name}")

    while retry_count < MAX_ALERT_RETRIES:
        # 检查提醒是否仍然活跃（按"已吃药"按钮会移除）
        with lock:
            if tid not in state["active_alerts"]:
                log(f"提醒 {tid} 已被停止（已吃药确认）")
                break
            # 在锁内获取 volume 副本，避免锁外使用时被其他线程修改
            current_volume = state["active_alerts"][tid]["volume"]
            reminder = state["active_alerts"][tid]["reminder"]

        # 搜索药品模式下暂停提醒循环（不检测人脸、不播报）
        # 修复：搜索药品暂停时仍递增重试计数，防止提醒永不超时
        # 使用可中断等待，避免 time.sleep 阻塞导致无法及时响应中断
        if _searching_medicine.is_set():
            _alert_interrupt_event.wait(timeout=0.5)
            retry_count += 1
            if retry_count >= MAX_ALERT_RETRIES:
                log(f"提醒 {tid} 在搜索药品模式下已达最大重试次数，自动停止", "WARNING")
                with lock:
                    state["active_alerts"].pop(tid, None)
                update_gui_home()
                break
            continue

        # 检测目标人脸
        face_found = detect_face_id(TARGET_FACE_ID)

        if face_found:
            # 检测到目标老人，播报用药信息
            name = get_face_name(TARGET_FACE_ID)
            if _get_online() and reminder:
                drug = reminder.get("medicine_name", "药品")
                dose = reminder.get("dose", "")
                msg = f"{name}，该吃 {drug} 了，每次 {dose}"
            else:
                # 离线或无用药计划，提醒吃测试药品
                msg = f"{name}，请吃1个测试药品"
        else:
            # 未检测到目标老人，呼叫其来吃药
            msg = f"请{target_name}来吃药"

        buzzer_beep(times=3, duration=0.3)
        # 使用锁内获取的 current_volume，避免竞态条件
        tts_speak(msg, volume=current_volume)
        retry_count += 1

        # 可中断等待：使用 Event.wait 实现高效等待，响应更快
        wait_timeout = ALERT_WAIT_TIMEOUT  # 等待时间使用常量
        _alert_interrupt_event.clear()
        # 分段等待：每1秒检查一次是否需要退出
        waited = 0
        should_break = False
        while waited < wait_timeout:
            # 等待1秒或直到事件被设置
            _alert_interrupt_event.wait(timeout=1.0)
            waited += 1
            # 检查是否被中断（按了"已吃药"按钮）
            with lock:
                if tid not in state["active_alerts"]:
                    should_break = True
                    break
            if should_break:
                break

        if should_break:
            log(f"提醒 {tid} 被中断")
            break

        # 增大音量
        with lock:
            if tid in state["active_alerts"]:
                info = state["active_alerts"][tid]
                old_volume = info["volume"]
                info["volume"] = min(info["volume"] + VOLUME_STEP, VOLUME_MAX)
                if info["volume"] != old_volume:
                    log(f"提醒 {tid} 音量提升: {old_volume} -> {info['volume']}")

    # 超过最大重试次数，自动停止提醒（避免无限响铃）
    if retry_count >= MAX_ALERT_RETRIES:
        log(f"提醒 {tid} 已达最大重试次数 ({MAX_ALERT_RETRIES})，自动停止", "WARNING")
        with lock:
            state["active_alerts"].pop(tid, None)
        update_gui_home()


def confirm_take(tid=None):
    """确认服药：拍照上传（无摄像头则跳过）并停止提醒，返回主页
    
    流程：
    1. 根据 tid 获取提醒详情
    2. 停止该提醒（从 active_alerts 中移除）
    3. 后台线程执行：拍照 → 上传日志
    4. TTS 播报确认、更新 GUI、扣减库存
    
    Args:
        tid: 提醒 ID，可选。若不传则取第一个活跃提醒
    
    Returns:
        None
    """
    reminder = {}
    dose_count = 1
    medicine_id = None
    if tid:
        with lock:
            if tid in state["active_alerts"]:
                reminder = dict(state["active_alerts"][tid]["reminder"])
                dose_count = reminder.get("dose_count", 1)
                medicine_id = reminder.get("medicine_id")
                del state["active_alerts"][tid]

    def _do_confirm_upload():
        photo_path = None
        if _get_camera_available():
            photo_path = capture_photo(
                filename=f"take_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg",
                timeout=5,
            )
        detail = {
            "action": "confirm_take",
            "medicine": reminder.get("medicine_name", ""),
            "user": reminder.get("user_name", ""),
            "photo_path": photo_path,
        }
        upload_log("confirm_take", detail, photo_path)

    threading.Thread(target=_do_confirm_upload, daemon=True).start()
    tts_speak("已记录服药")
    update_gui_home()
    # 仅在有有效药品ID时才更新库存
    if medicine_id is not None:
        update_stock(medicine_id, dose_count)
    else:
        log("无有效药品ID，跳过库存更新", "WARNING")


def update_stock(medicine_id, used_count):
    """更新药品库存：扣减使用数量、检查低库存、持久化到配置文件
    
    Args:
        medicine_id: 药品 ID，必须是非空字符串或整数
        used_count: 本次使用数量（正数，整数或浮点数）
    
    Returns:
        None
    
    Raises:
        无（参数无效时记录警告并返回）
    """
    if medicine_id is None or (isinstance(medicine_id, str) and not medicine_id.strip()):
        log("update_stock: medicine_id 无效", "WARNING")
        return
    if not isinstance(used_count, (int, float)) or used_count <= 0:
        log(f"update_stock: 无效的使用数量 {used_count}", "WARNING")
        return
    # 转换为整数使用数量（取整）
    try:
        used_count = int(used_count)
    except (ValueError, TypeError):
        log(f"update_stock: 使用数量转换失败 {used_count}", "WARNING")
        return
    if used_count <= 0:
        log(f"update_stock: 使用数量 {used_count} 转换后无效", "WARNING")
        return
    
    needs_alert = False
    alert_medicine = None
    found = False  # 追踪是否找到对应药品
    medicines_snapshot = None
    with lock:
        for m in state["medicines"]:
            if m.get("id") == medicine_id:
                found = True
                current_remaining = m.get("remaining", 0)
                # 修复：在扣减前检查，避免扣减后变为负数
                if current_remaining <= 0:
                    log(f"update_stock: 药品 {medicine_id} 剩余为0，无法扣减", "WARNING")
                    break
                m["remaining"] = max(0, current_remaining - used_count)
                remaining = m["remaining"]
                # low_stock_threshold 为剩余片数阈值（API 定义），直接使用无需乘以频率
                # 剩余数量 <= 阈值时触发告警（包括恰好等于阈值的情况）
                threshold = m.get("threshold", 5)
                # 修复：安全获取阈值，确保为非负数
                try:
                    threshold = int(threshold) if threshold is not None else 5
                    if threshold < 0:
                        threshold = 5
                except (ValueError, TypeError):
                    threshold = 5
                if remaining <= threshold:
                    needs_alert = True
                    alert_medicine = dict(m)
                break
        # 深拷贝：避免锁释放后其他线程修改原始 dict 导致持久化数据不一致
        medicines_snapshot = [dict(m) for m in state["medicines"]]
    
    # 如果未找到对应药品，记录警告
    if not found:
        log(f"update_stock: 未找到药品 ID={medicine_id}，库存未更新", "WARNING")
    
    # 文件 I/O 在锁外执行，避免阻塞其他线程
    try:
        cfg = load_config()
        cfg["medicines"] = medicines_snapshot
        save_config(cfg)
    except Exception as e:
        log(f"库存持久化失败: {e}", "ERROR")
    if needs_alert and alert_medicine:
        threading.Thread(target=low_stock_alert, args=(alert_medicine,), daemon=True).start()


def low_stock_alert(medicine):
    """低库存告警：语音提醒 + 查询补货信息 + ALERT_TIMEOUT 秒后自动返回主页
    
    Args:
        medicine: 药品信息字典，需包含 id, name, remaining, unit 等字段
    """
    if not medicine or not isinstance(medicine, dict):
        log("low_stock_alert: 参数无效", "ERROR")
        return
    name = medicine.get('name', '未知药品')
    remaining = medicine.get('remaining', 0)
    unit = medicine.get('unit', '片')
    msg = f"{name} 剩余 {remaining}{unit}，请及时补药"
    log(msg)
    try:
        tts_speak(msg)
    except Exception as e:
        log(f"语音播报失败: {e}", "ERROR")
    try:
        update_gui_status(msg, alert=True)
    except Exception as e:
        log(f"GUI 更新失败: {e}", "ERROR")

    if _get_online():
        try:
            medicine_id = medicine.get("id")
            if medicine_id:
                resp = query_refill(medicine_id)
                if resp and isinstance(resp, dict):
                    if resp.get("_error"):
                        log(f"查询补货信息业务错误: {resp.get('message', '未知错误')}", "WARNING")
                    answer = resp.get("answer", "")
                    if answer:
                        buy_msg = f"购药建议: {answer}"
                        try:
                            tts_speak(buy_msg)
                            update_gui_status(buy_msg, alert=True)
                        except Exception as e:
                            log(f"购药建议播报失败: {e}", "ERROR")
                    else:
                        log("AI 查询补货无响应内容", "DEBUG")
                elif resp is None:
                    log("查询补货信息失败: 网络请求无响应", "WARNING")
        except Exception as e:
            log(f"查询补货信息异常: {type(e).__name__}: {e}", "ERROR")

    # ALERT_TIMEOUT 秒后自动恢复状态显示（避免一直停留在告警界面）
    # 修复：仅在非特殊模式（搜索药品、提醒界面）下恢复，避免覆盖用户操作
    try:
        def _restore_status():
            # 检查当前 GUI 模式，避免在搜索药品或提醒时强制恢复
            with _gui_lock:
                current_mode = _gui_mode
            # 仅在 home/status 模式下恢复，search/reminder 模式跳过
            if current_mode in ("home", "status"):
                if _get_online():
                    update_gui_status("在线", alert=False)
                else:
                    update_gui_status("离线模式", alert=False)
            else:
                log(f"告警界面恢复跳过：GUI模式={current_mode}", "DEBUG")
        threading.Timer(ALERT_TIMEOUT, _restore_status).start()
    except Exception as e:
        log(f"定时器启动失败: {e}", "ERROR")


# ============== AI 药物识别 ==============

_OCR_LOAD_FAILED = object()  # 哨兵值：标记 OCR 加载失败，避免重复尝试
_ocr_engine = None  # (pytesseract, Image) tuple, 延迟初始化
_ocr_lock = threading.Lock()


def _get_ocr_engine():
    """延迟加载 OCR 引擎（pytesseract + PIL），使用双重检查锁定
    
    Returns:
        tuple/None: (pytesseract, Image) 元组或 None（加载失败时）
    """
    global _ocr_engine
    if _ocr_engine is _OCR_LOAD_FAILED:
        return None  # 已尝试加载但失败，直接返回 None
    if _ocr_engine is not None:
        return _ocr_engine
    with _ocr_lock:
        # Double-check after acquiring lock
        if _ocr_engine is _OCR_LOAD_FAILED:
            return None
        if _ocr_engine is not None:
            return _ocr_engine
        try:
            import pytesseract
            from PIL import Image
            # 验证 OCR 引擎可以正常工作
            _ocr_engine = (pytesseract, Image)
            log("OCR 引擎加载成功")
            return _ocr_engine
        except ImportError as e:
            log(f"OCR 引擎导入失败（缺少依赖）: {e}", "WARNING")
            _ocr_engine = _OCR_LOAD_FAILED  # 标记为已尝试加载但失败
            return None
        except Exception as e:
            log(f"OCR 引擎加载失败: {e}", "WARNING")
            _ocr_engine = _OCR_LOAD_FAILED  # 标记为已尝试加载但失败
            return None


def reset_ocr_engine():
    """重置 OCR 引擎状态，允许在运行时安装依赖后重新加载
    
    当设备运行期间安装了 pytesseract/PIL 依赖时，调用此函数可强制重新加载
    """
    global _ocr_engine
    with _ocr_lock:
        _ocr_engine = None
        log("OCR 引擎状态已重置，下次调用 _get_ocr_engine() 时将重新加载")


def recognize_medicine():
    """识别药品：拍照 → OCR识别 → AI问答
    
    流程：
    1. 检查摄像头可用性
    2. 拍照并进行 OCR 文字识别
    3. 将识别结果发送给 AI 问答接口获取药品信息
    
    Returns:
        None
    """
    if not _get_camera_available():
        tts_speak("摄像头未就绪，请手动核对药品")
        update_gui_home()
        return
    update_gui_status("正在识别药品...")
    photo_path = capture_photo(filename=f"ocr_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    if not photo_path:
        tts_speak("拍照失败，请检查摄像头")
        update_gui_home()
        return

    text = ""
    ocr = _get_ocr_engine()
    if ocr:
        pytesseract, Image = ocr
        try:
            img = Image.open(photo_path).convert("L")
            text = pytesseract.image_to_string(img, lang="chi_sim+eng").strip()
            log(f"OCR 结果: {text}")
        except Exception as e:
            log(f"OCR 识别失败: {e}", "WARNING")
            tts_speak("文字识别失败，请手动核对说明书")
            update_gui_home()
            return
    else:
        log("OCR 引擎未加载，跳过文字识别", "WARNING")
        tts_speak("文字识别功能未安装，请手动核对说明书")
        update_gui_home()
        return

    if text and _get_online():
        try:
            resp = query_drug_by_ocr(text)
            if resp:
                answer = resp.get("answer", "")
                if answer:
                    speak = f"AI 识别结果: {answer}"
                    update_gui_status(speak)
                    tts_speak(speak)
                    return
                else:
                    log("AI 问答响应无 answer 字段", "WARNING")
        except Exception as e:
            log(f"AI 识别查询失败: {e}", "WARNING")
    elif text and not _get_online():
        log("AI 识别需要网络连接，但当前离线", "WARNING")
        tts_speak("当前离线，无法查询药品信息")
        update_gui_home()
        return

    if not text:
        tts_speak("未能识别药品，请手动核对说明书")
    else:
        tts_speak("未能查询到药品信息，请手动核对说明书")
    update_gui_home()


# ============== 余量监测 ==============

def calculate_remaining_days():
    """计算每个药品的剩余天数，对库存不足 5 天的药品触发低库存告警
    
    使用向上取整算法，确保在剩余药量不足以覆盖整天时提前预警。
    告警在锁外异步触发，避免阻塞主循环。
    
    Args:
        无
    
    Returns:
        None
    
    Raises:
        无（所有异常已内部捕获）
    """
    alerts_to_fire = []
    with lock:
        for m in state["medicines"]:
            total = m.get("remaining", 0)
            # 确保 total 不为负数
            if not isinstance(total, (int, float)) or total < 0:
                total = 0
            per_time = m.get("per_time", 1)
            # 修复：安全获取 per_time，确保为正数
            try:
                per_time = float(per_time) if per_time is not None else 1.0
                if per_time <= 0:
                    per_time = 1.0
            except (ValueError, TypeError):
                per_time = 1.0
            freq = m.get("frequency_per_day", 1)
            # 修复：安全获取 frequency_per_day，确保为正数
            try:
                freq = float(freq) if freq is not None else 1.0
                if freq <= 0:
                    freq = 1.0
            except (ValueError, TypeError):
                freq = 1.0
            daily = per_time * freq
            if daily <= 0 or total <= 0:
                # 每日用量为0或剩余为0，视为库存充足或已用完
                m["remaining_days"] = 0 if total <= 0 else 999
                if total <= 0:
                    alerts_to_fire.append(dict(m))
            else:
                # 修复：使用 math.ceil 进行精确的向上取整，避免整数运算精度问题
                try:
                    m["remaining_days"] = max(0, math.ceil(total / daily))
                except (ValueError, ZeroDivisionError, OverflowError):
                    m["remaining_days"] = 0
                if m["remaining_days"] < 5:
                    alerts_to_fire.append(dict(m))
    for med_copy in alerts_to_fire:
        threading.Thread(target=low_stock_alert, args=(med_copy,), daemon=True).start()


# ============== GUI 更新 ==============

# GUI 模式与可刷新时钟对象（仅主页模式刷新，避免与提醒/状态界面冲突）
_gui_mode = "home"            # home / status / reminder
_clock_date_obj = None        # 主页日期文本对象（可 config 更新）
_clock_time_obj = None        # 主页时分秒文本对象（可 config 更新）
_clock_stop_event = threading.Event()


def _format_date(now):
    return now.strftime("%Y-%m-%d")


def _format_time(now):
    return now.strftime("%H:%M:%S")


def update_gui_status(text, alert=False):
    """临时状态界面（不显示时钟，时钟线程会跳过非 home 模式）"""
    global _gui_mode, _face_id_obj
    if not gui:
        return
    try:
        with _gui_lock:
            _gui_mode = "status"
            _face_id_obj = None
        with _gui_draw_lock:
            color = COLOR_ALERT_RED if alert else COLOR_TEXT_DARK
            gui.clear()
            gui.draw_text(x=120, y=40, text="智能服药提醒", font_size=20, color=COLOR_TITLE, origin="center")
            gui.draw_text(x=120, y=100, text=text, font_size=16, color=color, origin="center")
            status = "在线" if _get_online() else "离线模式"
            gui.draw_text(x=120, y=200, text=status, font_size=14, color=COLOR_TEXT_GRAY, origin="center")
    except Exception as e:
        log(f"GUI 更新失败: {e}", "ERROR")


def update_gui_home():
    """返回主页界面，绘制日期与时分秒（由 clock_thread 每秒刷新）"""
    global _gui_mode, _clock_date_obj, _clock_time_obj, _face_id_obj, _search_button_obj
    if not gui:
        return
    try:
        # 统一锁获取顺序：先 _gui_lock 再 _gui_draw_lock，避免死锁
        with _gui_lock:
            _clock_date_obj = None
            _clock_time_obj = None
            _face_id_obj = None  # gui.clear() 会销毁对象，重置引用
            _search_button_obj = None
        with _gui_draw_lock:
            gui.clear()
            gui.draw_text(x=120, y=30, text="智能服药提醒", font_size=18, color=COLOR_TITLE, origin="center")
            status = "在线" if _get_online() else "离线模式"
            gui.draw_text(x=120, y=65, text=status, font_size=12, color=COLOR_TEXT_GRAY, origin="center")
            now = datetime.datetime.now()
            # 日期行
            date_obj = gui.draw_text(
                x=120, y=120, text=_format_date(now),
                font_size=16, color=COLOR_TEXT_DARK, origin="center",
            )
            # 时分秒行（醒目蓝色）
            time_obj = gui.draw_text(
                x=120, y=165, text=_format_time(now),
                font_size=24, color=COLOR_CLOCK_BLUE, origin="center",
            )
            with _gui_lock:
                _clock_date_obj = date_obj
                _clock_time_obj = time_obj
                _gui_mode = "home"
            gui.draw_text(x=120, y=210, text="B键启动提醒 A键紧急", font_size=11, color=COLOR_TEXT_GRAY, origin="center")
            # 底部搜索药品按钮（触摸屏）
            add_button = getattr(gui, "add_button", None)
            if callable(add_button):
                # 修复：按钮回调在后台线程执行，避免阻塞 GUI 主线程
                def _enter_search():
                    enter_search_medicine()
                _search_button_obj = add_button(
                    x=120, y=245, w=120, h=36,
                    text="搜索药品", origin="center",
                    onclick=lambda: threading.Thread(target=_enter_search, daemon=True).start(),
                )
            else:
                gui.draw_text(x=120, y=245, text="[搜索药品]", font_size=14, color=COLOR_TEXT_GRAY, origin="center")
    except Exception as e:
        log(f"GUI 更新失败: {e}", "ERROR")


def update_gui_reminder(name, drug, dose):
    """显示吃药提醒界面（分两行避免文字过长换行）"""
    global _gui_mode, _face_id_obj, _search_button_obj
    if not gui:
        return
    try:
        with _gui_lock:
            _gui_mode = "reminder"
            _face_id_obj = None
            _search_button_obj = None
        with _gui_draw_lock:
            gui.clear()
            gui.draw_text(x=120, y=40, text="该吃药了", font_size=20, color=COLOR_ALERT_DARK, origin="center")
            gui.draw_text(x=120, y=100, text=f"{name}，该吃 {drug}", font_size=16, color=COLOR_ALERT_RED, origin="center")
            gui.draw_text(x=120, y=140, text=f"每次 {dose}", font_size=16, color=COLOR_ALERT_RED, origin="center")
            gui.draw_text(x=120, y=210, text="按~A键确认已吃药", font_size=12, color=COLOR_TEXT_GRAY, origin="center")
            # 底部搜索药品按钮（触摸屏）
            add_button = getattr(gui, "add_button", None)
            if callable(add_button):
                # 修复：按钮回调在后台线程执行，避免阻塞 GUI 主线程
                def _enter_search():
                    enter_search_medicine()
                _search_button_obj = add_button(
                    x=120, y=245, w=120, h=36,
                    text="搜索药品", origin="center",
                    onclick=lambda: threading.Thread(target=_enter_search, daemon=True).start(),
                )
            else:
                gui.draw_text(x=120, y=245, text="[搜索药品]", font_size=14, color=COLOR_TEXT_GRAY, origin="center")
    except Exception as e:
        log(f"GUI 更新失败: {e}", "ERROR")


def clock_thread():
    """后台时钟刷新线程：仅在主页模式时每秒更新日期与时分秒文本对象"""
    while not _clock_stop_event.is_set():
        try:
            # 使用 _gui_lock 保护 GUI 变量读取，防止与写操作竞争
            with _gui_lock:
                mode = _gui_mode
                time_obj = _clock_time_obj
                date_obj = _clock_date_obj
            # 修复：检查 gui 是否存在且模式正确
            if gui is not None and mode == "home":
                now = datetime.datetime.now()
                with _gui_draw_lock:
                    # 修复：检查对象有效性
                    if time_obj is not None:
                        try:
                            time_obj.config(text=_format_time(now))
                        except Exception:
                            pass
                    if date_obj is not None:
                        try:
                            date_obj.config(text=_format_date(now))
                        except Exception:
                            pass
        except Exception as e:
            log(f"时钟刷新失败: {e}", "WARNING")
        time.sleep(CLOCK_REFRESH_INTERVAL)


# ============== 按钮处理 ==============

def on_take_button_pressed():
    """P21 已吃药按钮（~A）：确认已吃药
    
    当存在活跃提醒时，获取第一个提醒 ID 并调用 confirm_take() 确认服药。
    若无活跃提醒则忽略按钮事件。
    
    Args:
        无
    
    Returns:
        None
    """
    log("已吃药按钮被按下")
    with lock:
        if state["active_alerts"]:
            # 使用 next() 默认值 None 防止 StopIteration 异常
            tid = next(iter(state["active_alerts"]), None)
        else:
            tid = None
    if tid:
        confirm_take(tid)
    else:
        log("无活跃提醒，忽略吃药按钮", "DEBUG")


def on_emergency_button_pressed():
    """P28 A键：紧急呼叫
    
    通过 POST /api/v1/public/device/message 接口异步通知家属，
    不阻塞按钮线程，在后台线程中执行实际的网络请求。
    
    Args:
        无
    
    Returns:
        None
    
    Raises:
        无
    """
    log("紧急按钮被按下，正在通知家属...", "WARNING")
    update_gui_status("正在发送紧急通知...", alert=True)
    def _do_emergency():
        success = notify_emergency()
        if success:
            update_gui_status("已通知家属", alert=True)
        else:
            update_gui_status("通知失败，请手动拨打 120", alert=True)
    threading.Thread(target=_do_emergency, daemon=True).start()


def on_remind_button_pressed():
    """P27 B键：直接启动吃药提醒
    
    优先使用已同步的真实用药计划（第一条），
    若无可用计划则使用默认提醒，确保功能始终可用。
    
    Args:
        无
    
    Returns:
        None
    
    Raises:
        无
    """
    log("提醒按钮被按下，直接启动吃药提醒")
    # 优先从已同步的用药计划中获取第一条作为即时提醒
    real_reminder = None
    with lock:
        reminders = state.get("reminders", [])
        if reminders:
            real_reminder = dict(reminders[0])
    
    if real_reminder:
        log(f"使用真实用药计划: {real_reminder.get('medicine_name', '未知')}")
        trigger_alert(real_reminder)
    else:
        # 无用药计划时使用默认提醒，确保功能可用
        log("无可用用药计划，使用默认提醒")
        default_reminder = {
            "id": f"manual_{int(time.time())}",
            "user_name": "老人",
            "medicine_name": "药品",
            "dose": "请按医嘱服用",
            "medicine_id": None,
            "dose_count": 1,
        }
        trigger_alert(default_reminder)


# ============== 初始化与主循环 ==============

def get_face_name(face_id):
    """从 HuskyLens 获取指定人脸 ID 的名字

    使用 getCachedResultByID 获取已学习的人脸信息。
    必须先 getResult() + available() 确保有识别结果，再读取 name 字段。

    Args:
        face_id: 人脸 ID（如 2）

    Returns:
        str: 人脸名字，获取失败时返回 "id{face_id}"
    """
    if not _HUSKYLENS_AVAILABLE or huskylens is None:
        return f"id{face_id}"
    try:
        huskylens.getResult(ALGORITHM_FACE_RECOGNITION)
        if not huskylens.available(ALGORITHM_FACE_RECOGNITION):
            return f"id{face_id}"
        result = huskylens.getCachedResultByID(ALGORITHM_FACE_RECOGNITION, face_id)
        if result and result.name:
            return result.name
        return f"id{face_id}"
    except Exception as e:
        log(f"获取人脸ID{face_id}名字失败: {e}", "WARNING")
        return f"id{face_id}"


def detect_face_id(face_id):
    """检测当前帧中是否存在指定 ID 的人脸

    按 HuskyLens 实例代码流程：
    1. getResult() 请求一次识别
    2. available() 检查是否有结果
    3. getCachedResultByID() 检查目标 ID 是否在当前帧

    Args:
        face_id: 目标人脸 ID

    Returns:
        bool: True 表示检测到目标人脸
    """
    if not _HUSKYLENS_AVAILABLE or huskylens is None:
        return False
    try:
        huskylens.getResult(ALGORITHM_FACE_RECOGNITION)
        if not huskylens.available(ALGORITHM_FACE_RECOGNITION):
            return False
        result = huskylens.getCachedResultByID(ALGORITHM_FACE_RECOGNITION, face_id)
        return result is not None
    except Exception as e:
        log(f"检测人脸ID{face_id}失败: {e}", "WARNING")
        return False


def get_current_face_ids():
    """获取当前帧中检测到的所有人脸 ID 列表

    按 HuskyLens 实例代码流程：
    1. getResult() 请求识别
    2. available() 检查是否有结果
    3. 遍历 ID 1-7，用 getCachedResultByID 检查哪些在当前帧中

    Returns:
        list: 检测到的人脸 ID 列表（如 [1, 2]），无检测或异常时返回空列表
    """
    if not _HUSKYLENS_AVAILABLE or huskylens is None:
        return []
    try:
        huskylens.getResult(ALGORITHM_FACE_RECOGNITION)
        if not huskylens.available(ALGORITHM_FACE_RECOGNITION):
            return []
        ids = []
        for fid in range(1, 8):
            result = huskylens.getCachedResultByID(ALGORITHM_FACE_RECOGNITION, fid)
            if result is not None:
                ids.append(fid)
        return ids
    except Exception as e:
        log(f"获取当前人脸ID列表失败: {e}", "WARNING")
        return []


def update_face_id_label():
    """在 GUI 左下角绘制/更新人脸 ID 文本

    使用全局 _face_id_text 作为内容，若文本对象不存在则创建。
    每次调用时更新文本对象的 text 属性。
    线程安全：通过 _get_face_id_text() 读取。
    """
    global _face_id_obj
    if not gui:
        return
    try:
        # 线程安全读取人脸ID文本
        face_id_text = _get_face_id_text()
        with _gui_draw_lock:
            if _face_id_obj is None:
                _face_id_obj = gui.draw_text(
                    x=5, y=225, text=face_id_text,
                    font_size=10, color=COLOR_TEXT_GRAY, origin="top_left",
                )
            else:
                try:
                    _face_id_obj.config(text=face_id_text)
                except Exception:
                    _face_id_obj = gui.draw_text(
                        x=5, y=225, text=face_id_text,
                        font_size=10, color=COLOR_TEXT_GRAY, origin="top_left",
                    )
    except Exception as e:
        log(f"更新人脸ID标签失败: {e}", "WARNING")


def face_id_thread():
    """后台人脸 ID 检测线程

    持续读取 HuskyLens 人脸识别结果，更新左下角显示。
    HuskyLens 未初始化时跳过。
    每 0.5 秒检测一次，避免 I2C 总线过载。
    搜索药品模式下（_searching_medicine 事件被 set）暂停检测，避免与条形码识别冲突。
    """
    log("人脸ID检测线程已启动")
    while not _face_id_stop_event.is_set():
        try:
            # 搜索药品模式下暂停人脸检测（二哈已切换到条形码识别）
            if _searching_medicine.is_set():
                time.sleep(0.5)
                continue
            if huskylens is not None and _HUSKYLENS_AVAILABLE:
                ids = get_current_face_ids()
                # 先更新文本，再更新GUI显示，确保一致性
                if ids:
                    new_text = f"ID: {','.join(str(i) for i in ids)}"
                else:
                    new_text = "ID: --"
                # 使用锁保护设置全局变量
                _set_face_id_text(new_text)
                # 然后更新GUI显示
                update_face_id_label()
            time.sleep(0.5)
        except Exception as e:
            log(f"人脸ID检测线程异常: {e}", "WARNING")
            time.sleep(1)
    log("人脸ID检测线程已停止")


def _set_face_id_text(text):
    """线程安全设置人脸ID文本"""
    global _face_id_text
    with _face_id_lock:
        _face_id_text = text


def _get_face_id_text():
    """线程安全读取人脸ID文本"""
    with _face_id_lock:
        return _face_id_text


def update_gui_search_medicine(barcode_name=""):
    """搜索药品界面：中间偏上显示"药品为："和条形码名字，底部返回按钮

    Args:
        barcode_name: 当前检测到的条形码名字（空字符串时显示"等待识别..."）
    """
    global _gui_mode, _face_id_obj, _back_button_obj, _barcode_text_obj
    if not gui:
        return
    try:
        with _gui_lock:
            _gui_mode = "search"
            _face_id_obj = None
            _barcode_text_obj = None
            _back_button_obj = None
        with _gui_draw_lock:
            gui.clear()
            gui.draw_text(x=120, y=40, text="搜索药品", font_size=20, color=COLOR_TITLE, origin="center")
            gui.draw_text(x=120, y=90, text="药品为：", font_size=16, color=COLOR_TEXT_DARK, origin="center")
            display_name = barcode_name if barcode_name else "等待识别..."
            _barcode_text_obj = gui.draw_text(
                x=120, y=125, text=display_name,
                font_size=16, color=COLOR_ALERT_RED, origin="center",
            )
            # 底部返回按钮（触摸屏）
            add_button = getattr(gui, "add_button", None)
            if callable(add_button):
                # 修复：按钮回调在后台线程执行，避免阻塞 GUI 主线程
                def _exit_search():
                    exit_search_medicine()
                _back_button_obj = add_button(
                    x=120, y=230, w=120, h=36,
                    text="返回", origin="center",
                    onclick=lambda: threading.Thread(target=_exit_search, daemon=True).start(),
                )
            else:
                gui.draw_text(x=120, y=230, text="[返回]", font_size=14, color=COLOR_TEXT_GRAY, origin="center")
    except Exception as e:
        log(f"GUI 搜索药品界面更新失败: {e}", "ERROR")


def _barcode_detect_thread():
    """条形码检测线程：持续检测条形码并更新界面显示"""
    log("条形码检测线程已启动")
    while not _barcode_thread_stop.is_set():
        try:
            name = get_barcode_name()
            if name:
                # 使用 _gui_draw_lock 保护 GUI 对象读取和更新
                with _gui_draw_lock:
                    if _barcode_text_obj is not None:
                        try:
                            _barcode_text_obj.config(text=name)
                        except Exception:
                            pass
                log(f"检测到条形码: {name}")
            time.sleep(0.5)
        except Exception as e:
            log(f"条形码检测线程异常: {e}", "WARNING")
            time.sleep(1)
    log("条形码检测线程已停止")


def enter_search_medicine():
    """进入搜索药品模式（后台线程执行，避免阻塞 GUI 主线程）

    onclick 回调在 GUI 主线程执行，若直接调用 switch_huskylens_to_barcode()
    会阻塞 5 秒，期间 clock_thread/face_id_thread 操作 tkinter 导致死锁。
    因此将实际逻辑放到后台线程，回调立即返回。

    流程：
    1. 检查是否已在搜索模式中（防重复调用）
    2. 记录当前界面（home/reminder）
    3. 暂停人脸ID检测
    4. 等待 face_id_thread 暂停（避免 I2C 冲突）
    5. 切换 HuskyLens 到条形码识别模式
    6. 显示搜索药品界面
    7. 启动条形码检测线程
    """
    # 防重复调用：检查是否已在搜索模式中
    if _searching_medicine.is_set():
        log("已在搜索药品模式中，忽略重复调用", "DEBUG")
        return
    threading.Thread(target=_enter_search_medicine_impl, daemon=True).start()


def _enter_search_medicine_impl():
    """进入搜索药品模式的实际实现（在后台线程执行）"""
    global _previous_gui_mode
    # 记录当前界面
    with _gui_lock:
        _previous_gui_mode = _gui_mode
    log(f"进入搜索药品模式，前一界面: {_previous_gui_mode}")
    # 暂停人脸检测
    _searching_medicine.set()
    # 等待 face_id_thread 检测到事件并暂停（检测周期 0.5 秒，等 SEARCH_MEDICINE_PAUSE_DELAY 秒确保暂停）
    time.sleep(SEARCH_MEDICINE_PAUSE_DELAY)
    # 切换到条形码识别
    switch_ok = switch_huskylens_to_barcode()
    if not switch_ok:
        log("HuskyLens 条形码识别切换失败，将在无识别模式下显示搜索界面", "WARNING")
    # 显示搜索界面
    update_gui_search_medicine()
    # 仅在切换成功时启动条形码检测线程
    if switch_ok:
        _barcode_thread_stop.clear()
        threading.Thread(target=_barcode_detect_thread, daemon=True).start()


def exit_search_medicine():
    """退出搜索药品模式（后台线程执行，避免阻塞 GUI 主线程）

    onclick 回调在 GUI 主线程执行，若直接调用 switch_huskylens_to_face()
    会阻塞 5 秒。因此将实际逻辑放到后台线程，回调立即返回。

    流程：
    1. 检查是否在搜索模式中（防重复调用）
    2. 停止条形码检测线程
    3. 切换 HuskyLens 回人脸识别模式（无论返回主页还是提醒界面）
    4. 恢复前一界面（home/reminder）
    5. 恢复人脸ID检测
    """
    # 防重复调用：检查是否在搜索模式中
    if not _searching_medicine.is_set():
        log("不在搜索药品模式中，忽略退出调用", "DEBUG")
        return
    threading.Thread(target=_exit_search_medicine_impl, daemon=True).start()


def _exit_search_medicine_impl():
    """退出搜索药品模式的实际实现（在后台线程执行）"""
    log("退出搜索药品模式")
    # 停止条形码检测
    _barcode_thread_stop.set()
    # 切换回人脸识别模式（主页和提醒界面均需要）
    switch_huskylens_to_face()
    # 恢复前一界面
    prev = _previous_gui_mode
    if prev == "reminder":
        # 返回提醒界面，从 active_alerts 恢复提醒数据
        with lock:
            if state["active_alerts"]:
                tid = next(iter(state["active_alerts"]), None)
                if tid:
                    reminder = state["active_alerts"][tid]["reminder"]
                    update_gui_reminder(
                        reminder.get("user_name", "老人"),
                        reminder.get("medicine_name", "药品"),
                        reminder.get("dose", ""),
                    )
                else:
                    update_gui_home()
            else:
                # 提醒已被停止，回主页
                update_gui_home()
    else:
        # 返回主页
        update_gui_home()
    # 恢复人脸ID检测
    _searching_medicine.clear()


def switch_huskylens_to_face():
    """切换 HuskyLens 到人脸识别模式

    在触发吃药提醒时调用（到时间了或按提醒按钮），
    切换到 ALGORITHM_FACE_RECOGNITION 以识别人脸确认身份。
    HuskyLens 未初始化时跳过。
    """
    global huskylens
    if not _HUSKYLENS_AVAILABLE or huskylens is None:
        log("HuskyLens 未初始化，跳过切换人脸识别模式", "WARNING")
        return
    try:
        huskylens.switchAlgorithm(ALGORITHM_FACE_RECOGNITION)
        time.sleep(HUSKYLENS_SWITCH_DELAY)
        log("HuskyLens 已切换到人脸识别模式")
    except Exception as e:
        log(f"HuskyLens 切换人脸识别模式失败: {e}", "ERROR")


def switch_huskylens_to_barcode():
    """切换 HuskyLens 到条形码识别模式

    在搜索药品时调用，切换到 ALGORITHM_BARCODE_RECOGNITION。
    HuskyLens 未初始化时跳过。
    """
    global huskylens
    if not _HUSKYLENS_AVAILABLE or huskylens is None:
        log("HuskyLens 未初始化，跳过切换条形码识别模式", "WARNING")
        return False  # 修复：返回 False 表示未成功切换，调用方可据此调整策略
    try:
        huskylens.switchAlgorithm(ALGORITHM_BARCODE_RECOGNITION)
        time.sleep(HUSKYLENS_SWITCH_DELAY)
        log("HuskyLens 已切换到条形码识别模式")
        return True
    except Exception as e:
        log(f"HuskyLens 切换条形码识别模式失败: {e}", "ERROR")
        return False


def get_barcode_name():
    """获取当前检测到的条形码名字

    按 HuskyLens 实例代码流程：
    1. getResult() 请求识别
    2. available() 检查是否有结果
    3. 遍历 ID 1-7，用 getCachedResultByID 获取条形码信息

    Returns:
        str: 条形码名字，无检测或异常时返回空字符串
    """
    if not _HUSKYLENS_AVAILABLE or huskylens is None:
        return ""
    try:
        huskylens.getResult(ALGORITHM_BARCODE_RECOGNITION)
        if not huskylens.available(ALGORITHM_BARCODE_RECOGNITION):
            return ""
        for bid in range(1, 8):
            result = huskylens.getCachedResultByID(ALGORITHM_BARCODE_RECOGNITION, bid)
            if result is not None:
                # 条形码的 name 字段可能存储条形码内容或自定义名称
                return result.name if result.name else f"条形码{bid}"
        return ""
    except Exception as e:
        log(f"获取条形码名字失败: {e}", "WARNING")
        return ""


def init_hardware():
    """初始化硬件：蜂鸣器、按钮、GUI、HuskyLens 和摄像头检测

    硬件模块不可用时优雅降级（如无 GUI 模式运行）。
    HuskyLens 初始化顺序：huskylens = HuskylensV2_I2C() → huskylens.knock()

    Args:
        无

    Returns:
        None

    Raises:
        无（所有异常已内部捕获）
    """
    global buzzer, button_take, button_emergency, button_remind, gui, huskylens
    try:
        # 检查硬件模块是否可用
        if not _PINPONG_AVAILABLE or Board is None or Pin is None:
            log("Pinpong 硬件模块不可用，跳过硬件初始化", "WARNING")
            return
        if not _GUI_AVAILABLE or GUI is None:
            log("GUI 模块不可用，将以无界面模式运行", "WARNING")
            gui = None
        
        Board().begin()
        # 优先使用 pinpong 板载蜂鸣器（支持音效），回退到数字引脚
        try:
            from pinpong.extension.unihiker import buzzer as _buzzer
            buzzer = _buzzer
            log("使用 pinpong 板载蜂鸣器（音效模式）")
        except ImportError:
            buzzer = Pin(BUZZER_PIN_NUM, Pin.OUT)
            log("使用数字引脚蜂鸣器（兼容模式）")
        button_take = Pin(BUTTON_TAKE_PIN_NUM, Pin.IN)
        button_emergency = Pin(BUTTON_EMERGENCY_PIN_NUM, Pin.IN)
        button_remind = Pin(BUTTON_REMIND_PIN_NUM, Pin.IN)
        try:
            gui = GUI()
            log("GUI 初始化成功")
        except Exception as e:
            log(f"GUI 初始化失败，将以无界面模式运行: {e}", "WARNING")
            gui = None
        # 初始化 HuskyLens 二哈识图（仅 I2C 连接 + knock 握手，不切换算法）
        try:
            if _HUSKYLENS_AVAILABLE:
                huskylens = HuskylensV2_I2C()
                huskylens.knock()
                log("HuskyLens 初始化成功")
            else:
                log("HuskyLens 模块不可用，跳过初始化", "WARNING")
        except Exception as e:
            log(f"HuskyLens 初始化失败: {e}", "WARNING")
            huskylens = None
        # 检测摄像头是否可用（通过 fswebcam 能否执行）
        try:
            r = subprocess.run(["which", "fswebcam"], shell=False, capture_output=True, timeout=5)
            _set_camera_available(r.returncode == 0)
        except subprocess.TimeoutExpired:
            log("检测摄像头超时", "WARNING")
            _set_camera_available(False)
        except Exception as e:
            log(f"检测摄像头失败: {e}", "WARNING")
            _set_camera_available(False)
        log("硬件初始化完成")
    except Exception as e:
        log(f"硬件初始化异常: {e}", "ERROR")


def init_network():
    """初始化网络：连接 WiFi、检查状态、恢复/注册设备、同步数据、刷新离线日志
    
    流程：
    1. 检查 WiFi 模块可用性
    2. 首次调用时延迟连接 WiFi（带超时和重试）
    3. 检测 WiFi 连接状态
    4. 通过 HTTP 请求验证网络连通性（含重试）
    5. 在线时恢复 token 或注册设备
    6. 同步用药计划和刷新离线日志
    
    Returns:
        None
    """
    global _wifi_initialized
    try:
        # 检查 WiFi 模块是否可用
        if not _WIFI_AVAILABLE or wifi_manager is None:
            log("WiFi 模块不可用，进入离线模式", "WARNING")
            _set_online(False)
            return

        # 首次调用时尝试连接 WiFi（延迟执行，避免模块加载时阻塞）
        if not _wifi_initialized:
            log("正在连接 WiFi...")
            wifi_connected = False
            for attempt in range(3):
                try:
                    wifi_manager.connect_wifi(_WIFI_SSID, _WIFI_PASSWORD)
                    if wifi_manager.is_wifi_connected():
                        wifi_connected = True
                        log(f"WiFi 连接成功（第 {attempt + 1} 次尝试）")
                        break
                    log(f"WiFi 连接第 {attempt + 1} 次失败，2秒后重试...", "WARNING")
                    time.sleep(2)
                except Exception as e:
                    log(f"WiFi 连接异常（第 {attempt + 1} 次）: {type(e).__name__}: {e}", "WARNING")
                    time.sleep(2)
            _wifi_initialized = True
            if not wifi_connected:
                log("WiFi 连接失败，进入离线模式", "WARNING")
                _set_online(False)
                return

        if wifi_manager.is_wifi_connected():
            log("WiFi 已连接，正在检测网络...")
            # 增加网络检测重试机制，应对临时网络波动
            online = False
            for attempt in range(3):
                online = check_network()
                if online:
                    log(f"网络检测成功（第 {attempt + 1} 次尝试）")
                    break
                log(f"网络检测第 {attempt + 1} 次失败，1秒后重试...", "WARNING")
                time.sleep(1)
            _set_online(online)
            if online:
                log("网络正常，正在初始化设备...")
                # 尝试从本地恢复 device_token，否则重新注册
                token_restored = load_device_token()
                if not token_restored:
                    log("未找到本地 token，正在注册设备...")
                    if not register_device():
                        log("设备注册失败，进入离线模式", "ERROR")
                        _set_online(False)
                        return
                else:
                    # 本地有 token，发心跳确认 device_id 在服务器已注册
                    # （设备 ID 变更后旧 token 失效，心跳会触发服务端创建新用户并返回新 token）
                    send_heartbeat()
                log("正在同步用药计划...")
                sync_reminders()
                log("正在刷新离线日志...")
                flush_local_logs()
            else:
                log("网络异常（WiFi 已连接但无法访问服务器），进入离线模式", "WARNING")
                _set_online(False)
        else:
            log("WiFi 未连接，进入离线模式", "WARNING")
            _set_online(False)
        log(f"网络状态: {'在线' if _get_online() else '离线'}")
    except Exception as e:
        log(f"网络初始化异常: {type(e).__name__}: {e}", "ERROR")
        _set_online(False)


def button_thread():
    last_take = 0
    last_emergency = 0
    last_remind = 0
    while True:
        now = time.time()
        # P21 已吃药按钮（~A）：按下高电平（1），松开低电平（0）
        if button_take and button_take.read_digital() == 1 and now - last_take > BUTTON_DEBOUNCE_TAKE:
            last_take = now
            on_take_button_pressed()
        # P27 B键启动吃药提醒：按下低电平（0）
        if button_remind and button_remind.read_digital() == 0 and now - last_remind > BUTTON_DEBOUNCE_REMIND:
            last_remind = now
            on_remind_button_pressed()
        # P28 A键紧急呼叫：按下低电平，联网通知家属
        if button_emergency and button_emergency.read_digital() == 0 and now - last_emergency > BUTTON_DEBOUNCE_EMERGENCY:
            last_emergency = now
            on_emergency_button_pressed()
        time.sleep(0.1)


def main_loop():
    """主循环：定时检查提醒、同步数据、网络恢复等"""
    last_minute = ""
    last_hour = -1
    last_stock_check = 0
    last_flush = 0
    last_reconnect_check = 0
    missed_minutes = 0  # 追踪连续错过的分钟数
    reconnect_fail_count = 0  # 网络恢复失败计数
    _sync_thread = None  # 网络恢复同步线程引用
    last_heartbeat = 0  # 上次心跳时间戳

    def _do_network_recovery_sync():
        """网络恢复后的数据同步操作（仅定义一次，复用闭包）

        注册只跑一次：本地已有 token 时不再重复注册，仅同步用药计划。
        """
        try:
            token_exists = load_device_token()
            if not token_exists:
                # 本地无 token，尝试注册（仅首次或 token 丢失时）
                if register_device():
                    sync_reminders()
                else:
                    log("注册失败，跳过用药计划同步", "WARNING")
            else:
                # 已有 token（之前注册成功），仅同步用药计划
                sync_reminders()
            flush_local_logs()
            log("网络恢复数据同步完成", "INFO")
        except Exception as e:
            log(f"网络恢复数据同步失败: {e}", "ERROR")

    while True:
        now = datetime.datetime.now()
        now_str = now.strftime("%H:%M")

        # 每分钟检查提醒（含固定时间提醒 9:00/13:00/17:00）
        if now_str != last_minute:
            last_minute = now_str
            missed_minutes = 0
            check_reminders()
            check_fixed_reminders()
        else:
            # 若系统延迟导致多次循环同一分钟，超过阈值则强制检查
            missed_minutes += 1
            if missed_minutes > MISSED_MINUTES_THRESHOLD:
                missed_minutes = 0
                log("main_loop 长时间未刷新，强制检查提醒", "WARNING")
                check_reminders()

        # 每小时同步一次数据
        if now.hour != last_hour:
            last_hour = now.hour
            if _get_online():
                sync_reminders()

        # 检测设备未注册（404），清除旧 token 并重新注册
        if _device_needs_re_register.is_set() and _get_online():
            _device_needs_re_register.clear()
            log("检测到设备未注册，清除旧 token 并重新注册...", "WARNING")
            clear_device_token()
            if register_device():
                log("重新注册成功，正在同步用药计划...", "INFO")
                sync_reminders()
            else:
                log("重新注册失败，稍后重试", "WARNING")

        # 每 HEARTBEAT_INTERVAL 秒发送心跳（在线时），并根据心跳结果更新在线状态
        if _get_online() and time.time() - last_heartbeat > HEARTBEAT_INTERVAL:
            last_heartbeat = time.time()
            heartbeat_ok = send_heartbeat()
            # 修复：心跳失败时标记为离线，触发重连机制
            if not heartbeat_ok:
                log("心跳发送失败，标记为离线", "WARNING")
                _set_online(False)

        # 每 STOCK_CHECK_INTERVAL 检查库存
        if time.time() - last_stock_check > STOCK_CHECK_INTERVAL:
            last_stock_check = time.time()
            calculate_remaining_days()

        # 每 LOG_FLUSH_INTERVAL 刷新离线日志
        if time.time() - last_flush > LOG_FLUSH_INTERVAL:
            last_flush = time.time()
            if _get_online():
                flush_local_logs()

        # 每 NETWORK_RECONNECT_INTERVAL 检查网络恢复（异步执行，避免阻塞主循环）
        if not _get_online() and time.time() - last_reconnect_check > NETWORK_RECONNECT_INTERVAL:
            last_reconnect_check = time.time()
            if check_network():
                _set_online(True)
                reconnect_fail_count = 0
                # 网络恢复后直接回到主页，显示"在线"状态和时钟
                update_gui_home()
                log("网络恢复成功，正在同步数据...", "INFO")
                
                # 异步执行数据同步，避免阻塞主循环
                if _sync_thread is None or not _sync_thread.is_alive():
                    _sync_thread = threading.Thread(target=_do_network_recovery_sync, daemon=True)
                    _sync_thread.start()
            else:
                reconnect_fail_count += 1
                # 连续失败超过阈值时告警
                if reconnect_fail_count >= MAX_RECONNECT_FAILS:
                    log(f"网络恢复连续失败 {reconnect_fail_count} 次", "WARNING")
                    reconnect_fail_count = 0
                    # 尝试重启 WiFi 连接
                    if wifi_manager is not None and hasattr(wifi_manager, 'reconnect'):
                        try:
                            log("尝试 WiFi 重连...", "INFO")
                            wifi_manager.reconnect()
                            log("WiFi 重连成功", "INFO")
                        except Exception as e:
                            log(f"WiFi 重连失败: {type(e).__name__}: {e}", "ERROR")

        time.sleep(CHECK_INTERVAL)


def main():
    ensure_dirs()
    log("程序启动")
    init_hardware()
    init_speech()
    update_gui_status("正在连接网络...")
    # 网络初始化改为异步，不阻塞主界面显示
    threading.Thread(target=init_network, daemon=True).start()

    threading.Thread(target=button_thread, daemon=True).start()
    # 启动主界面时钟刷新线程（每秒更新年月日时分秒）
    threading.Thread(target=clock_thread, daemon=True).start()
    # 启动人脸ID检测线程（持续读取HuskyLens结果，更新左下角显示）
    threading.Thread(target=face_id_thread, daemon=True).start()

    update_gui_home()
    tts_speak("智能服药提醒已启动")

    main_loop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("用户中断")
    except Exception as e:
        # 修复 F4：不再输出完整 traceback（避免泄露系统路径和变量信息）
        # 仅记录异常类型和简要描述，详细堆栈仅写入本地调试日志
        log(f"主程序异常: {type(e).__name__}: {e}", "CRITICAL")
        # 将完整堆栈写入本地文件，不上传日志服务器
        try:
            with open(LOG_FILE + ".crash", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.datetime.now().isoformat()}] {traceback.format_exc()}\n")
        except Exception:
            pass
    finally:
        try:
            # 停止时钟刷新线程
            _clock_stop_event.set()
            # 停止人脸ID检测线程
            _face_id_stop_event.set()
            # 停止条形码检测线程
            _barcode_thread_stop.set()
            # 异步发送下线通知，不阻塞进程退出
            threading.Thread(target=device_offline, daemon=True).start()
        except Exception:
            pass
        stop_speech()
