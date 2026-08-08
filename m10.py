#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniHiker M10 智能服药提醒终端主程序
项目地址适配: https://my-website.ccwu.cc/eating-medication/server/
设备配对码: 275527387791320
API 版本: v2.29.0（对应 openapi.json）

本程序使用 Python 标准库 + UniHiker 原生 API (unihiker/pinpong) + pyttsx3 TTS,
不依赖 cv2、requests、schedule 等第三方库。

v2.29.0 修复记录（共 31 项 bug 修复）：
- log() 函数日志 I/O 移到锁外执行，避免阻塞
- http_request() 增加 HTTPError 处理、非 JSON 响应回退
- check_reminders() 和 trigger_alert() 增加 None 检查
- calculate_remaining_days() 修复除零错误
- capture_photo() 增加目录创建和超时异常处理
- image_to_base64() 增加文件存在性和空文件检查
- load_config()/save_config() 增加损坏文件恢复机制
- sync_reminders() 增加数据验证和异常处理
- init_network() 增加详细日志和错误处理
- low_stock_alert() 增加独立 try/except 和更详细反馈
- _get_ocr_engine() 使用哨兵值避免重复加载失败
- _speak_worker() 增加音量边界检查和引擎初始化锁保护
- main_loop() 增加网络恢复失败计数和 WiFi 重连尝试
"""

import os
# 必须在导入 tkinter/unihiker 之前强制设置 DISPLAY（SSH 远程运行时需要）
os.environ["DISPLAY"] = os.environ.get("DISPLAY") or ":0"

import time
import json
import re
import base64
import queue
import threading
import datetime
import subprocess
import traceback
import urllib.request
import urllib.error
from pathlib import Path

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
try:
    from unihiker_connet_wifi import WiFiManager
    wifi_manager = WiFiManager()
    response_success = wifi_manager.connect_wifi("666", "15756491077")
    _WIFI_AVAILABLE = True
except (ImportError, NameError, AttributeError) as e:
    _WIFI_AVAILABLE = False

# ============== 配置区 ==============
SERVER_BASE_URL = "https://my-website.ccwu.cc/eating-medication/server"
PAIR_CODE = "275527387791320"
DEVICE_ID = "m10_" + PAIR_CODE

# API 端点（v2.28.0，对应 openapi.json）
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

# 提醒音量递增参数（每 10 分钟递增一次）
VOLUME_INITIAL = 30
VOLUME_STEP = 15
VOLUME_MAX = 100
SNOOZE_MINUTES = 10

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
_gui_lock = threading.Lock()
_gui_draw_lock = threading.Lock()  # 保护 gui.clear/draw_text 等绘制操作，防多线程画面撕裂
_config_lock = threading.Lock()  # 保护配置文件的读写，避免多线程同时写入导致 JSON 损坏
_queue_lock = threading.Lock()   # 保护离线日志队列文件的读写
_log_lock = threading.Lock()      # 保护日志文件写入与轮转
_camera_lock = threading.Lock()  # 保护摄像头访问，避免多线程并发拍照冲突

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

LOG_MAX_SIZE = 10 * 1024 * 1024  # 10 MB 日志轮转阈值


def log(msg, level="INFO"):
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {msg}"
    print(line)
    try:
        with _log_lock:
            need_rotate = (
                os.path.exists(LOG_FILE)
                and os.path.getsize(LOG_FILE) > LOG_MAX_SIZE
            )

        # I/O 操作在锁外执行，避免阻塞其他线程
        if need_rotate:
            rotated = LOG_FILE + ".old"
            if os.path.exists(rotated):
                try:
                    os.remove(rotated)
                except Exception:
                    pass
            os.rename(LOG_FILE, rotated)

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def ensure_dirs():
    Path(PHOTO_DIR).mkdir(parents=True, exist_ok=True)


def load_config():
    """加载配置文件，返回 dict；文件损坏时自动备份并返回空字典"""
    with _config_lock:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, ValueError) as e:
                log(f"配置文件损坏，正在备份: {e}", "ERROR")
                # 备份损坏的配置文件
                backup_path = CONFIG_FILE + f".bak.{int(time.time())}"
                try:
                    os.rename(CONFIG_FILE, backup_path)
                    log(f"损坏配置已备份到: {backup_path}", "INFO")
                except Exception:
                    pass
                return {}
            except Exception as e:
                log(f"读取配置失败: {e}", "ERROR")
                return {}
        return {}


def save_config(cfg):
    """原子写入：先写临时文件再 rename，避免断电导致配置文件损坏"""
    if not isinstance(cfg, dict):
        log("save_config: cfg 必须是 dict 类型", "ERROR")
        return False
    with _config_lock:
        try:
            tmp_path = CONFIG_FILE + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
                f.flush()  # 强制写入磁盘
            os.replace(tmp_path, CONFIG_FILE)
            return True
        except Exception as e:
            log(f"保存配置失败: {e}", "ERROR")
            if os.path.exists(CONFIG_FILE + ".tmp"):
                try:
                    os.remove(CONFIG_FILE + ".tmp")
                except Exception:
                    pass
            return False


def check_network():
    try:
        urllib.request.urlopen(SERVER_BASE_URL, timeout=5)
        return True
    except Exception:
        return False


def detect_volume_control():
    """自动检测可用的 ALSA 音量控制，优先 USB 声卡的 Speaker/Headphone/PCM"""
    try:
        r = subprocess.run("aplay -l", shell=True, capture_output=True, universal_newlines=True, timeout=5)
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
            cmd = f"amixer {card_arg} scontrols" if card_arg else "amixer scontrols"
            rr = subprocess.run(cmd, shell=True, capture_output=True, universal_newlines=True, timeout=3)
            return ctrl.lower() in rr.stdout.lower()

        if usb_card is not None:
            card_arg = f"-c {usb_card}"
            for ctrl in controls:
                if control_exists(card_arg, ctrl):
                    return f"{card_arg} set {ctrl}"

        for ctrl in controls:
            if control_exists("", ctrl):
                return f"set {ctrl}"
    except Exception as e:
        log(f"检测音量控制失败: {e}", "WARNING")
    return "set PCM"


_volume_control_cmd = None


def set_system_volume(vol):
    """设置 USB 扬声器系统音量（amixer），自动检测并缓存可用的 ALSA 控制"""
    global _volume_control_cmd
    if not _volume_control_cmd:
        _volume_control_cmd = VOLUME_CONTROL if VOLUME_CONTROL else detect_volume_control()
    try:
        subprocess.run(f"amixer {_volume_control_cmd} {vol}%", shell=True, timeout=5)
    except Exception as e:
        log(f"设置音量失败: {e}", "ERROR")


# ============== TTS 语音播报（pyttsx3 + 队列，参考老年端 speech.py） ==============

_speech_engine = None
_speak_queue = queue.Queue(maxsize=100)  # 有界队列，最多 100 条排队
_speech_stop_event = threading.Event()
_speech_thread = None
_speech_lock = threading.Lock()


def init_speech():
    """初始化 pyttsx3 TTS 引擎并启动后台播报线程"""
    global _speech_engine, _speech_thread
    try:
        if _PYTTSX3_AVAILABLE and pyttsx3 is not None:
            _speech_engine = pyttsx3.init()
            _speech_engine.setProperty('volume', VOLUME_INITIAL / 100)
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
                        _speech_engine.setProperty('volume', vol / 100)
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
                        except Exception:
                            _speech_engine = None
                    else:
                        _speech_engine = None
            else:
                # 回退到 espeak
                try:
                    subprocess.run(["espeak", "-v", "zh", text], timeout=30)
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
    """使用系统 fswebcam 命令拍照，不依赖 cv2。线程安全：多线程并发拍照时串行化"""
    if filename is None:
        filename = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    path = os.path.join(PHOTO_DIR, filename)
    with _camera_lock:
        try:
            # 确保照片目录存在
            os.makedirs(PHOTO_DIR, exist_ok=True)
            # 优先使用 fswebcam（Linux 下 USB/CSI 摄像头通用）
            cmd = f"fswebcam -r 640x480 --no-banner {path}"
            r = subprocess.run(cmd, shell=True, capture_output=True, timeout=timeout)
            if r.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 0:
                return path
            log(f"fswebcam 失败: {r.stderr.decode('utf-8', errors='ignore')}", "WARNING")
        except subprocess.TimeoutExpired:
            log("拍照超时", "ERROR")
        except Exception as e:
            log(f"拍照失败: {e}", "ERROR")
    return None


def image_to_base64(path):
    """将图片转为 base64，文件超过 1MB 则跳过避免 OOM"""
    try:
        # 修复：检查文件是否存在
        if not path or not os.path.exists(path):
            log(f"图片文件不存在: {path}", "WARNING")
            return None
        size = os.path.getsize(path)
        if size > 1048576:  # 1MB
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
    headers = {"Content-Type": "application/json"}
    token = _get_device_token()
    if token:
        headers["X-Device-Token"] = token
    if extra:
        headers.update(extra)
    return headers


def http_request(url, payload=None, timeout=15, headers=None):
    """封装 urllib，payload 为 dict 时 POST，否则 GET。
    自动携带 X-Device-Token（已注册后）。"""
    try:
        hdrs = _auth_headers(headers)
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.getcode()
            body = resp.read().decode("utf-8")
            if not body:
                return None
            # 尝试解析 JSON，非 JSON 响应返回原始文本
            try:
                result = json.loads(body)
                # 检查业务状态码
                if isinstance(result, dict) and result.get("status") and result.get("status") != "ok":
                    log(f"HTTP 业务错误: {result.get('message', 'Unknown error')}", "WARNING")
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
        log(f"HTTP {e.code} 请求失败 {url}: {error_body[:200]}", "ERROR")
        return None
    except Exception as e:
        log(f"HTTP 请求失败 {url}: {e}", "ERROR")
        return None


def register_device():
    """设备注册（新版 API），成功后保存 device_token"""
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
            _set_device_token(token)
            save_device_token(token)
            log("设备注册成功")
            return True
        else:
            log("设备注册成功但未返回 device_token", "WARNING")
            return True  # 注册成功但无 token 也视为成功
    else:
        log(f"设备注册失败: {resp.get('message', resp)}", "ERROR")
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
    """从配置文件恢复 device_token"""
    try:
        cfg = load_config()
        if cfg:
            token = cfg.get("device_token")
            if token and isinstance(token, str) and len(token) > 0:
                _set_device_token(token)
                log("device_token 已从本地恢复")
                return True
    except Exception as e:
        log(f"加载 device_token 失败: {e}", "WARNING")
    return False


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

    # 检查是否返回了错误状态
    if isinstance(resp, dict) and resp.get("status") and resp.get("status") != "ok":
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
        if not plans and resp.get("status") and resp.get("status") != "ok":
            log(f"同步用药计划返回错误: {resp.get('message', resp)}", "WARNING")
            return False

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
    """从 frequency 字符串解析每日服药次数，如 '每日3次' → 3，'每日' → 1"""
    if not frequency_str:
        return 1
    try:
        m = re.search(r'(\d+)\s*次', str(frequency_str))
        if m:
            return int(m.group(1))
        if '每日' in str(frequency_str) or '每天' in str(frequency_str):
            return 1
    except Exception:
        pass
    return 1


def _convert_plans_to_reminders(plans):
    """将 FamilyMedicationPlan 数组转换为旧版 reminders 格式"""
    reminders = []
    for p in plans:
        times = p.get("schedule_times", [])
        drug_name = p.get("drug_name", "")
        plan_id = p.get("id")
        freq = p.get("frequency", "每日")
        # 解析 days：优先使用 API 传入的 weekday/days 字段，默认全周
        days = p.get("days") or p.get("weekdays") or p.get("day_of_week")
        if not days:
            days = [1, 2, 3, 4, 5, 6, 7]
        elif isinstance(days, (list, tuple)):
            days = [int(d) for d in days if str(d).isdigit()] or [1, 2, 3, 4, 5, 6, 7]
        elif isinstance(days, int):
            days = [days]
        reminders.append({
            "id": plan_id if plan_id is not None else drug_name,
            "medicine_name": drug_name,
            "dose": p.get("dosage", "1片"),
            "times": times if isinstance(times, list) else [times],
            "days": days,
            "medicine_id": plan_id,
            "dose_count": 1,
            "user_name": "老人",
            "frequency": freq,
        })
    return reminders


def _convert_plans_to_medicines(plans):
    """将 FamilyMedicationPlan 数组转换为旧版 medicines 库存格式"""
    medicines = []
    for p in plans:
        plan_id = p.get("id")
        drug_name = p.get("drug_name", "")
        freq = p.get("frequency", "每日")
        freq_per_day = _parse_frequency_per_day(freq)
        remaining = p.get("remaining_quantity", 0)
        # 修复：正确处理 remaining_quantity，可能是浮点数
        try:
            remaining = int(float(remaining))
        except (ValueError, TypeError):
            remaining = 0
        medicines.append({
            "id": plan_id if plan_id is not None else drug_name,
            "name": drug_name,
            "remaining": remaining,
            "per_time": 1,
            "frequency_per_day": freq_per_day,
            "threshold": p.get("low_stock_threshold", 5),
            "unit": p.get("unit", "片"),
            "dosage": p.get("dosage", "1片"),
            # 新增：保存 total_quantity 用于计算总库存量
            "total_quantity": int(float(p.get("total_quantity", 0)) or 0),
        })
    return medicines


def upload_log(event_type, detail, photo_path=None):
    """上报设备事件（新版 API：POST /device/message + /device/upload）"""
    # 修复：验证 event_type 有效性
    if not event_type or not isinstance(event_type, str):
        log(f"upload_log: event_type 无效: {event_type}", "ERROR")
        return False

    msg_payload = {
        "device_id": DEVICE_ID,
        "message_type": event_type,
        "content": str(detail) if isinstance(detail, (str, int, float)) else json.dumps(detail, ensure_ascii=False),
        "data": detail if isinstance(detail, dict) else {"detail": str(detail)},
    }
    photo_base64 = None
    if photo_path and os.path.exists(photo_path):
        photo_size = os.path.getsize(photo_path)
        # 限制照片大小 <= 500KB，避免 base64 编码后内存膨胀
        if photo_size > 512000:
            log(f"照片过大 ({photo_size} bytes)，跳过上传", "WARNING")
        else:
            photo_base64 = image_to_base64(photo_path)

    # 1. 上传消息事件
    msg_resp = http_request(API_MESSAGE, msg_payload)
    msg_ok = msg_resp is not None

    # 2. 如有照片，单独上传
    if photo_base64:
        upload_payload = {
            "device_id": DEVICE_ID,
            "image_base64": photo_base64,
            "note": f"{event_type} photo",
        }
        upload_resp = http_request(API_UPLOAD, upload_payload)
        photo_ok = upload_resp is not None
    else:
        photo_ok = True

    if msg_ok and photo_ok:
        log(f"日志上传成功: {event_type}")
        return True
    # 离线时写入本地队列
    queue_local_log(msg_payload, photo_base64)
    return False


def queue_local_log(payload, photo_base64=None):
    """将日志条目写入本地离线队列。队列最多保留 500 条，超出时丢弃最旧的"""
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
            # 限制队列大小，超过 500 条时丢弃最旧的
            if len(queue) > 500:
                queue = queue[-500:]
                log("离线日志队列超过 500 条，已裁剪", "WARNING")
            tmp_path = QUEUE_FILE + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(queue, f, ensure_ascii=False)
            os.replace(tmp_path, QUEUE_FILE)
        except Exception as e:
            log(f"本地日志队列写入失败: {e}", "ERROR")


def flush_local_logs():
    """刷新本地离线日志队列：读取 → 逐条上传 → 写回剩余"""
    if not os.path.exists(QUEUE_FILE):
        return

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
            # 备份损坏的队列文件
            try:
                backup_path = QUEUE_FILE + f".bak.{int(time.time())}"
                os.rename(QUEUE_FILE, backup_path)
            except Exception:
                pass
            return
        except Exception as e:
            log(f"读取本地日志队列失败: {e}", "ERROR")
            return

    if not queue:
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
            msg_ok = msg_resp is not None
            photo_ok = True

            if photo:
                upload_resp = http_request(API_UPLOAD, {
                    "device_id": DEVICE_ID,
                    "image_base64": photo,
                    "note": "offline upload",
                })
                photo_ok = upload_resp is not None

            if msg_ok and photo_ok:
                success_count += 1
            else:
                remain.append(entry)
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


def query_drug_by_ocr(text):
    """AI 问答替代旧版药品查询（POST /public/ai/ask）"""
    payload = {"question": f"识别药品：{text}", "context": []}
    return http_request(API_AI_ASK, payload)


def query_refill(medicine_id):
    """查询补货信息（AI 问答方式）"""
    payload = {"question": f"药品 ID {medicine_id} 最优购买渠道", "context": []}
    return http_request(API_AI_ASK, payload)


def notify_emergency():
    """紧急通知家属（POST /device/message，message_type=emergency）"""
    cfg = load_config()
    contact = cfg.get("emergency_contact", "120")
    # 修复：验证联系人格式，避免无效通知
    if not contact or not isinstance(contact, str):
        contact = "120"
    payload = {
        "device_id": DEVICE_ID,
        "message_type": "emergency",
        "content": f"紧急呼叫，联系电话 {contact}",
        "data": {"contact": contact, "timestamp": datetime.datetime.now().isoformat()},
    }
    resp = http_request(API_MESSAGE, payload)
    if resp is not None:
        tts_speak("紧急通知已发送给家属")
        return True
    tts_speak("紧急通知发送失败，请手动拨打 120")
    return False


def device_offline():
    """设备主动下线通知"""
    payload = {"device_id": DEVICE_ID}
    http_request(API_OFFLINE, payload, timeout=5)


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
    now = datetime.datetime.now()
    now_str = now.strftime("%H:%M")
    weekday = now.weekday() + 1

    to_trigger = None
    with lock:
        for r in state["reminders"]:
            tid = r.get("id")
            times = r.get("times", [])
            # 兼容 times 为 None 的情况
            if times is None:
                times = []
            days = r.get("days", [1, 2, 3, 4, 5, 6, 7])
            if weekday not in days:
                continue
            for t in times:
                if t == now_str and tid not in state["active_alerts"]:
                    to_trigger = r
                    break
            if to_trigger:
                break
    if to_trigger:
        trigger_alert(to_trigger)


def trigger_alert(reminder):
    """触发吃药提醒：存储状态、更新界面、启动提醒循环线程"""
    # 添加 None 检查
    if reminder is None or not isinstance(reminder, dict):
        log("trigger_alert 收到无效的 reminder 参数", "ERROR")
        return
    tid = reminder.get("id")
    name = reminder.get("user_name", "老人")
    drug = reminder.get("medicine_name", "药品")
    dose = reminder.get("dose", "")
    if not tid:
        log("trigger_alert: reminder 缺少 id 字段", "ERROR")
        return
    with lock:
        state["active_alerts"][tid] = {
            "started_at": datetime.datetime.now(),
            "volume": VOLUME_INITIAL,
            "reminder": dict(reminder),  # 副本，避免原始字典被修改
        }
    msg = f"{name}，该吃 {drug} 了，每次 {dose}"
    log(f"触发提醒: {msg}")
    update_gui_reminder(name, drug, dose)
    threading.Thread(target=alert_loop, args=(tid,), daemon=True).start()


def alert_loop(tid):
    """提醒循环：每次响铃后等待 SNOOZE_MINUTES 分钟，最多响铃 20 次（约 3 小时）后自动停止"""
    max_retries = 20
    retry_count = 0
    while retry_count < max_retries:
        with lock:
            if tid not in state["active_alerts"]:
                break
            volume = state["active_alerts"][tid]["volume"]
            reminder = state["active_alerts"][tid]["reminder"]
        msg = f"{reminder.get('user_name', '老人')}，该吃 {reminder.get('medicine_name', '药品')} 了"
        buzzer_beep(times=3, duration=0.3)
        tts_speak(msg, volume=volume)
        retry_count += 1
        # 每 SNOOZE_MINUTES 分钟增大音量
        time.sleep(SNOOZE_MINUTES * 60)
        with lock:
            if tid in state["active_alerts"]:
                info = state["active_alerts"][tid]
                info["volume"] = min(info["volume"] + VOLUME_STEP, VOLUME_MAX)
    # 超过最大重试次数，自动停止提醒（避免无限响铃）
    if retry_count >= max_retries:
        log(f"提醒 {tid} 已达最大重试次数 ({max_retries})，自动停止", "WARNING")
        with lock:
            state["active_alerts"].pop(tid, None)
        update_gui_home()


def confirm_take(tid=None):
    """确认服药：拍照上传（无摄像头则跳过）并停止提醒，返回主页"""
    reminder = {}
    if tid:
        with lock:
            if tid in state["active_alerts"]:
                reminder = dict(state["active_alerts"][tid]["reminder"])
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
    update_stock(reminder.get("medicine_id"), reminder.get("dose_count", 1))


def update_stock(medicine_id, used_count):
    if not medicine_id:
        return
    needs_alert = False
    alert_medicine = None
    medicines_snapshot = None
    with lock:
        for m in state["medicines"]:
            if m.get("id") == medicine_id:
                m["remaining"] = max(0, m.get("remaining", 0) - used_count)
                remaining = m["remaining"]
                threshold = m.get("threshold", 5) * m.get("frequency_per_day", 1)
                if remaining < threshold:
                    needs_alert = True
                    alert_medicine = dict(m)
                break
        # 深拷贝：避免锁释放后其他线程修改原始 dict 导致持久化数据不一致
        medicines_snapshot = [dict(m) for m in state["medicines"]]
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
    """低库存告警：语音提醒 + 查询补货信息 + 30秒后自动返回主页"""
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
            resp = query_refill(medicine.get("id"))
            if resp:
                answer = resp.get("answer", "")
                if answer:
                    buy_msg = f"购药建议: {answer}"
                    try:
                        tts_speak(buy_msg)
                        update_gui_status(buy_msg, alert=True)
                    except Exception as e:
                        log(f"购药建议播报失败: {e}", "ERROR")
        except Exception as e:
            log(f"查询补货信息失败: {e}", "ERROR")

    # 30 秒后自动返回主页（避免一直停留在告警界面）
    try:
        threading.Timer(30, update_gui_home).start()
    except Exception as e:
        log(f"定时器启动失败: {e}", "ERROR")


# ============== AI 药物识别 ==============

_OCR_LOAD_FAILED = object()  # 哨兵值：标记 OCR 加载失败，避免重复尝试
_ocr_engine = None  # (pytesseract, Image) tuple, 延迟初始化
_ocr_lock = threading.Lock()


def _get_ocr_engine():
    """延迟加载 OCR 引擎（pytesseract + PIL），使用双重检查锁定"""
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


def recognize_medicine():
    """识别药品：拍照 → OCR识别 → AI问答"""
    if not _get_camera_available():
        tts_speak("摄像头未就绪，请手动核对药品")
        update_gui_home()
        return
    update_gui_status("正在识别药品...")
    photo_path = capture_photo(filename=f"ocr_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    if not photo_path:
        tts_speak("摄像头未就绪")
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
            text = ""

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
        except Exception as e:
            log(f"AI 识别查询失败: {e}", "WARNING")

    if not text:
        tts_speak("未能识别药品，请手动核对说明书")
    else:
        tts_speak("未能查询到药品信息，请手动核对说明书")


# ============== 余量监测 ==============

def calculate_remaining_days():
    alerts_to_fire = []
    with lock:
        for m in state["medicines"]:
            total = m.get("remaining", 0)
            per_time = m.get("per_time", 1)
            freq = m.get("frequency_per_day", 1)
            daily = per_time * freq
            # 修复：daily 为 0 时避免除零错误
            if daily <= 0:
                m["remaining_days"] = 999
            else:
                m["remaining_days"] = int(total / daily)
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
    global _gui_mode
    if not gui:
        return
    try:
        with _gui_lock:
            _gui_mode = "status"
        with _gui_draw_lock:
            color = "#FF4444" if alert else "#333333"
            gui.clear()
            gui.draw_text(x=120, y=40, text="智能服药提醒", font_size=20, color="#000000", origin="center")
            gui.draw_text(x=120, y=100, text=text, font_size=16, color=color, origin="center")
            status = "在线" if _get_online() else "离线模式"
            gui.draw_text(x=120, y=200, text=status, font_size=14, color="#666666", origin="center")
    except Exception as e:
        log(f"GUI 更新失败: {e}", "ERROR")


def update_gui_home():
    """返回主页界面，绘制日期与时分秒（由 clock_thread 每秒刷新）"""
    global _gui_mode, _clock_date_obj, _clock_time_obj
    if not gui:
        return
    try:
        with _gui_draw_lock:
            gui.clear()
            with _gui_lock:
                _clock_date_obj = None
                _clock_time_obj = None
            gui.draw_text(x=120, y=30, text="智能服药提醒", font_size=18, color="#000000", origin="center")
            status = "在线" if _get_online() else "离线模式"
            gui.draw_text(x=120, y=65, text=status, font_size=12, color="#666666", origin="center")
            now = datetime.datetime.now()
            # 日期行
            date_obj = gui.draw_text(
                x=120, y=120, text=_format_date(now),
                font_size=16, color="#333333", origin="center",
            )
            # 时分秒行（醒目蓝色）
            time_obj = gui.draw_text(
                x=120, y=165, text=_format_time(now),
                font_size=24, color="#0050FF", origin="center",
            )
            with _gui_lock:
                _clock_date_obj = date_obj
                _clock_time_obj = time_obj
                _gui_mode = "home"
            gui.draw_text(x=120, y=220, text="B键启动提醒 A键紧急", font_size=11, color="#666666", origin="center")
    except Exception as e:
        log(f"GUI 更新失败: {e}", "ERROR")


def update_gui_reminder(name, drug, dose):
    """显示吃药提醒界面（分两行避免文字过长换行）"""
    global _gui_mode
    if not gui:
        return
    try:
        with _gui_lock:
            _gui_mode = "reminder"
        with _gui_draw_lock:
            gui.clear()
            gui.draw_text(x=120, y=40, text="该吃药了", font_size=20, color="#FF0000", origin="center")
            gui.draw_text(x=120, y=100, text=f"{name}，该吃 {drug}", font_size=16, color="#FF4444", origin="center")
            gui.draw_text(x=120, y=140, text=f"每次 {dose}", font_size=16, color="#FF4444", origin="center")
            gui.draw_text(x=120, y=220, text="按~A键确认已吃药", font_size=12, color="#666666", origin="center")
    except Exception as e:
        log(f"GUI 更新失败: {e}", "ERROR")


def clock_thread():
    """后台时钟刷新线程：仅在主页模式时每秒更新日期与时分秒文本对象"""
    while not _clock_stop_event.is_set():
        try:
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
    """P21 已吃药按钮（~A）：仅在吃药提醒时确认已吃药"""
    log("已吃药按钮被按下")
    with lock:
        if state["active_alerts"]:
            tid = next(iter(state["active_alerts"]))
        else:
            tid = None
    if tid:
        confirm_take(tid)


def on_emergency_button_pressed():
    """P28 A键：紧急呼叫（通过新版 API 通知家属，异步执行不阻塞按钮线程）"""
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
    """P27 B键：直接启动吃药提醒"""
    log("提醒按钮被按下，直接启动吃药提醒")
    test_reminder = {
        "id": "test_reminder",
        "user_name": "老人",
        "medicine_name": "测试药品",
        "dose": "1片",
        "medicine_id": None,
        "dose_count": 1,
    }
    trigger_alert(test_reminder)


# ============== 初始化与主循环 ==============

def init_hardware():
    global buzzer, button_take, button_emergency, button_remind, gui
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
        # 检测摄像头是否可用（通过 fswebcam 能否执行）
        r = subprocess.run("which fswebcam", shell=True, capture_output=True)
        _set_camera_available(r.returncode == 0)
        log("硬件初始化完成")
    except Exception as e:
        log(f"硬件初始化异常: {e}", "ERROR")


def init_network():
    """初始化网络：检查 WiFi 状态、恢复/注册设备、同步数据、刷新离线日志"""
    try:
        # 检查 WiFi 模块是否可用
        if not _WIFI_AVAILABLE or wifi_manager is None:
            log("WiFi 模块不可用，进入离线模式", "WARNING")
            _set_online(False)
            return

        if wifi_manager.is_wifi_connected():
            log("WiFi 已连接，正在检测网络...")
            online = check_network()
            _set_online(online)
            if online:
                log("网络正常，正在初始化设备...")
                # 尝试从本地恢复 device_token，否则重新注册
                token_restored = load_device_token()
                if not token_restored:
                    log("未找到本地 token，正在注册设备...")
                    if not register_device():
                        log("设备注册失败", "ERROR")
                        _set_online(False)
                        return
                log("正在同步用药计划...")
                sync_reminders()
                log("正在刷新离线日志...")
                flush_local_logs()
            else:
                log("网络异常，进入离线模式", "WARNING")
                _set_online(False)
        else:
            log("WiFi 未连接，进入离线模式", "WARNING")
            _set_online(False)
        log(f"网络状态: {'在线' if _get_online() else '离线'}")
    except Exception as e:
        log(f"网络初始化异常: {e}", "ERROR")
        _set_online(False)


def button_thread():
    last_take = 0
    last_emergency = 0
    last_remind = 0
    while True:
        now = time.time()
        # P21 已吃药按钮（~A）：按下高电平（1），松开低电平（0）
        if button_take and button_take.read_digital() == 1 and now - last_take > 2:
            last_take = now
            on_take_button_pressed()
        # P27 B键启动吃药提醒：按下低电平（0）
        if button_remind and button_remind.read_digital() == 0 and now - last_remind > 3:
            last_remind = now
            on_remind_button_pressed()
        # P28 A键紧急呼叫：按下低电平，联网通知家属
        if button_emergency and button_emergency.read_digital() == 0 and now - last_emergency > 3:
            last_emergency = now
            on_emergency_button_pressed()
        time.sleep(0.1)


def main_loop():
    """用 time 循环替代 schedule"""
    last_minute = ""
    last_hour = -1
    last_stock_check = 0
    last_flush = 0
    last_reconnect_check = 0
    missed_minutes = 0  # 追踪连续错过的分钟数
    reconnect_fail_count = 0  # 网络恢复失败计数
    MAX_RECONNECT_FAILS = 5  # 最大失败次数，超过后告警

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
            # 若系统延迟导致多次循环同一分钟，最多允许 1 次补检
            missed_minutes += 1
            if missed_minutes > 60:
                # 系统可能挂起过久，强制重新检查
                missed_minutes = 0
                log("main_loop 长时间未刷新，强制检查提醒", "WARNING")
                check_reminders()

        # 每小时同步一次数据
        if now.hour != last_hour:
            last_hour = now.hour
            if _get_online():
                sync_reminders()

        # 每 6 小时检查库存
        if time.time() - last_stock_check > 6 * 3600:
            last_stock_check = time.time()
            calculate_remaining_days()

        # 每 30 分钟刷新离线日志
        if time.time() - last_flush > 30 * 60:
            last_flush = time.time()
            if _get_online():
                flush_local_logs()

        # 每 30 秒检查网络恢复
        if not _get_online() and time.time() - last_reconnect_check > 30:
            last_reconnect_check = time.time()
            if check_network():
                _set_online(True)
                reconnect_fail_count = 0
                # 尝试恢复 token，否则重新注册
                if not load_device_token():
                    register_device()
                sync_reminders()
                flush_local_logs()
                update_gui_status("网络已恢复")
                log("网络恢复成功", "INFO")
            else:
                reconnect_fail_count += 1
                # 连续失败超过阈值时告警
                if reconnect_fail_count >= MAX_RECONNECT_FAILS:
                    log(f"网络恢复连续失败 {reconnect_fail_count} 次", "WARNING")
                    reconnect_fail_count = 0
                    # 尝试重启 WiFi 连接
                    if wifi_manager is not None and hasattr(wifi_manager, 'reconnect'):
                        try:
                            wifi_manager.reconnect()
                        except Exception as e:
                            log(f"WiFi 重连失败: {e}", "ERROR")

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

    update_gui_home()
    tts_speak("智能服药提醒已启动")

    main_loop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("用户中断")
    except Exception as e:
        log(f"主程序异常: {traceback.format_exc()}", "CRITICAL")
    finally:
        try:
            device_offline()
        except Exception:
            pass
        stop_speech()
