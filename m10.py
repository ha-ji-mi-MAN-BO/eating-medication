#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniHiker M10 智能服药提醒终端主程序
项目地址适配: https://my-website.ccwu.cc/eating-medication/server/
设备配对码: 275527387791320
API 版本: v2.28.0（对应 openapi.json）

本程序使用 Python 标准库 + UniHiker 原生 API (unihiker/pinpong) + pyttsx3 TTS,
不依赖 cv2、requests、schedule 等第三方库。

v2.28.4 修复记录（共 40 项 bug 修复）：
- state["device_token"] 全面加锁保护（_get_device_token/_set_device_token 辅助函数）
- 新增 _queue_lock 保护离线日志队列文件，flush_local_logs 读锁内/网络锁外/写锁内
- 新增 _log_lock 保护日志写入与 10MB 自动轮转
- pyttsx3 预导入设 _PYTTSX3_AVAILABLE 标志，消除异常分支内动态 import
- trigger_alert 存储 reminder 副本，消除引用风险
- sync_reminders 增加完善的 API 响应校验
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
from unihiker import GUI
from pinpong.board import Board, Pin
from unihiker_connet_wifi import *
wifi_manager = WiFiManager()
response_success = wifi_manager.connect_wifi("666", "15756491077")

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

# 硬件引脚
BUZZER_PIN = Pin.P25      # 蜂鸣器
BUTTON_TAKE_PIN = Pin.P21  # 已吃药按钮（~A，按下高电平，松开低电平）
BUTTON_REMIND_PIN = Pin.P27  # B键：直接启动吃药提醒（按下低电平）
BUTTON_EMERGENCY_PIN = Pin.P28  # A键：紧急呼叫（联网通知家属）

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
_config_lock = threading.Lock()  # 保护配置文件的读写，避免多线程同时写入导致 JSON 损坏
_queue_lock = threading.Lock()   # 保护离线日志队列文件的读写
_log_lock = threading.Lock()      # 保护日志文件写入与轮转

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
    with _log_lock:
        try:
            if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > LOG_MAX_SIZE:
                rotated = LOG_FILE + ".old"
                if os.path.exists(rotated):
                    os.remove(rotated)
                os.rename(LOG_FILE, rotated)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def ensure_dirs():
    Path(PHOTO_DIR).mkdir(parents=True, exist_ok=True)


def load_config():
    with _config_lock:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log(f"读取配置失败: {e}", "ERROR")
        return {}


def save_config(cfg):
    with _config_lock:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log(f"保存配置失败: {e}", "ERROR")


def check_network():
    try:
        urllib.request.urlopen(SERVER_BASE_URL, timeout=5)
        return True
    except Exception:
        return False


def detect_volume_control():
    """自动检测可用的 ALSA 音量控制，优先 USB 声卡的 Speaker/Headphone/PCM"""
    try:
        r = subprocess.run("aplay -l", shell=True, capture_output=True, text=True, timeout=5)
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
            rr = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3)
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
_speak_queue = queue.Queue()
_speech_stop_event = threading.Event()
_speech_thread = None
_speech_lock = threading.Lock()


def init_speech():
    """初始化 pyttsx3 TTS 引擎并启动后台播报线程"""
    global _speech_engine, _speech_thread
    if _PYTTSX3_AVAILABLE and pyttsx3 is not None:
        try:
            _speech_engine = pyttsx3.init()
            _speech_engine.setProperty('volume', VOLUME_INITIAL / 100)
            _speech_engine.setProperty('rate', TTS_RATE)
            log("pyttsx3 TTS 引擎初始化成功")
        except Exception as e:
            log(f"pyttsx3 初始化失败，将回退到 espeak: {e}", "WARNING")
            _speech_engine = None
    else:
        log("pyttsx3 未安装，使用 espeak 回退")
        _speech_engine = None

    _speech_thread = threading.Thread(target=_speak_worker, daemon=True)
    _speech_thread.start()


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
                            _speech_engine = pyttsx3.init()
                            _speech_engine.setProperty('rate', TTS_RATE)
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


def tts_speak(text, volume=None):
    """语音播报（非阻塞，加入队列由后台线程处理）"""
    _speak_queue.put((text, volume))


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
    """使用系统 fswebcam 命令拍照，不依赖 cv2"""
    if filename is None:
        filename = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    path = os.path.join(PHOTO_DIR, filename)
    try:
        # 优先使用 fswebcam（Linux 下 USB/CSI 摄像头通用）
        cmd = f"fswebcam -r 640x480 --no-banner {path}"
        r = subprocess.run(cmd, shell=True, capture_output=True, timeout=timeout)
        if r.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 0:
            return path
        log(f"fswebcam 失败: {r.stderr.decode('utf-8', errors='ignore')}", "WARNING")
    except Exception as e:
        log(f"拍照失败: {e}", "ERROR")
    return None


def image_to_base64(path):
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
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
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except Exception as e:
        log(f"HTTP 请求失败 {url}: {e}", "ERROR")
        return None


def register_device():
    """设备注册（新版 API），成功后保存 device_token"""
    payload = {
        "device_id": DEVICE_ID,
        "device_name": None,
    }
    resp = http_request(API_REGISTER, payload)
    if resp and resp.get("status") == "ok":
        token = resp.get("device_token")
        if token:
            _set_device_token(token)
            save_device_token(token)
        log("设备注册成功")
        return True
    log(f"设备注册失败: {resp}", "ERROR")
    return False


def save_device_token(token):
    """将 device_token 持久化到配置文件，重启后可恢复"""
    try:
        cfg = load_config()
        cfg["device_token"] = token
        save_config(cfg)
    except Exception as e:
        log(f"保存 device_token 失败: {e}", "WARNING")


def load_device_token():
    """从配置文件恢复 device_token"""
    try:
        cfg = load_config()
        token = cfg.get("device_token")
        if token:
            _set_device_token(token)
            return True
    except Exception:
        pass
    return False


def sync_reminders():
    """获取用药计划（新版 API：GET /device/schedule/{id}）"""
    resp = http_request(API_SCHEDULE)
    if resp is None:
        log("同步用药计划失败：网络请求无响应", "WARNING")
        return False
    plans = []
    if isinstance(resp, list):
        plans = resp
    elif isinstance(resp, dict):
        plans = resp.get("plans") or resp.get("data") or resp.get("items") or []
        if not plans and resp.get("status") and resp.get("status") != "ok":
            log(f"同步用药计划返回错误: {resp.get('message', resp)}", "WARNING")
            return False
    with lock:
        state["reminders"] = _convert_plans_to_reminders(plans)
        state["medicines"] = _convert_plans_to_medicines(plans)
        state["last_sync"] = datetime.datetime.now().isoformat()
    log(f"同步用药计划: {len(plans)} 条")
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
        reminders.append({
            "id": plan_id if plan_id is not None else drug_name,
            "medicine_name": drug_name,
            "dose": p.get("dosage", "1片"),
            "times": times if isinstance(times, list) else [times],
            "days": [1, 2, 3, 4, 5, 6, 7],
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
        medicines.append({
            "id": plan_id if plan_id is not None else drug_name,
            "name": drug_name,
            "remaining": int(p.get("remaining_quantity", 0)),
            "per_time": 1,
            "frequency_per_day": freq_per_day,
            "threshold": p.get("low_stock_threshold", 5),
            "unit": p.get("unit", "片"),
            "dosage": p.get("dosage", "1片"),
        })
    return medicines


def upload_log(event_type, detail, photo_path=None):
    """上报设备事件（新版 API：POST /device/message + /device/upload）"""
    msg_payload = {
        "device_id": DEVICE_ID,
        "message_type": event_type,
        "content": str(detail) if isinstance(detail, (str, int, float)) else json.dumps(detail, ensure_ascii=False),
        "data": detail if isinstance(detail, dict) else {"detail": str(detail)},
    }
    photo_base64 = None
    if photo_path and os.path.exists(photo_path):
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
    with _queue_lock:
        try:
            queue = []
            if os.path.exists(QUEUE_FILE):
                with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                    queue = json.load(f)
            entry = payload.copy()
            if photo_base64:
                entry["_photo"] = photo_base64
            queue.append(entry)
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(queue, f, ensure_ascii=False)
        except Exception as e:
            log(f"本地日志队列写入失败: {e}", "ERROR")


def flush_local_logs():
    if not os.path.exists(QUEUE_FILE):
        return
    # 读取阶段：在锁内读取队列快照后释放锁，网络请求在锁外执行
    with _queue_lock:
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                queue = json.load(f)
        except Exception as e:
            log(f"读取本地日志队列失败: {e}", "ERROR")
            return

    if not queue:
        return

    remain = []
    for entry in queue:
        photo = entry.get("_photo")
        msg_payload = {k: v for k, v in entry.items() if k != "_photo"}
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
        if not (msg_ok and photo_ok):
            remain.append(entry)

    # 写回阶段：在锁内写回剩余队列
    with _queue_lock:
        try:
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(remain, f, ensure_ascii=False)
        except Exception as e:
            log(f"写回本地日志队列失败: {e}", "ERROR")
    log(f"刷新本地日志: 成功 {len(queue) - len(remain)}, 剩余 {len(remain)}")


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
    tid = reminder.get("id")
    name = reminder.get("user_name", "老人")
    drug = reminder.get("medicine_name", "药品")
    dose = reminder.get("dose", "")
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
    while True:
        with lock:
            if tid not in state["active_alerts"]:
                break
            volume = state["active_alerts"][tid]["volume"]
            reminder = state["active_alerts"][tid]["reminder"]
        msg = f"{reminder.get('user_name', '老人')}，该吃 {reminder.get('medicine_name', '药品')} 了"
        buzzer_beep(times=3, duration=0.3)
        tts_speak(msg, volume=volume)
        # 每 10 分钟增大音量
        time.sleep(SNOOZE_MINUTES * 60)
        with lock:
            if tid in state["active_alerts"]:
                info = state["active_alerts"][tid]
                info["volume"] = min(info["volume"] + VOLUME_STEP, VOLUME_MAX)


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
        medicines_snapshot = list(state["medicines"])
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
    name = medicine.get('name', '')
    msg = f"{name} 余量不足，请及时补药"
    log(msg)
    tts_speak(msg)
    update_gui_status(msg, alert=True)
    if _get_online():
        resp = query_refill(medicine.get("id"))
        if resp:
            answer = resp.get("answer", "")
            if answer:
                buy_msg = f"购药建议: {answer}"
                tts_speak(buy_msg)
                update_gui_status(buy_msg, alert=True)


# ============== AI 药物识别 ==============

_ocr_engine = None  # (pytesseract, Image) tuple, 延迟初始化


def _get_ocr_engine():
    """延迟加载 OCR 引擎（pytesseract + PIL）"""
    global _ocr_engine
    if _ocr_engine is not None:
        return _ocr_engine
    try:
        import pytesseract
        from PIL import Image
        _ocr_engine = (pytesseract, Image)
        return _ocr_engine
    except Exception as e:
        log(f"OCR 引擎加载失败: {e}", "WARNING")
        return None


def recognize_medicine():
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
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
            log(f"OCR 结果: {text.strip()}")
        except Exception as e:
            log(f"OCR 识别失败: {e}", "WARNING")
            text = ""

    if _get_online() and text.strip():
        resp = query_drug_by_ocr(text.strip())
        if resp:
            answer = resp.get("answer", "")
            if answer:
                speak = f"AI 识别结果: {answer}"
                update_gui_status(speak)
                tts_speak(speak)
                return
    tts_speak("未能识别药品，请手动核对说明书")


# ============== 余量监测 ==============

def calculate_remaining_days():
    alerts_to_fire = []
    with lock:
        for m in state["medicines"]:
            total = m.get("remaining", 0)
            per_time = m.get("per_time", 1)
            freq = m.get("frequency_per_day", 1)
            daily = per_time * freq
            if daily > 0:
                m["remaining_days"] = int(total / daily)
            else:
                m["remaining_days"] = 999
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
            if gui and mode == "home":
                now = datetime.datetime.now()
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
        Board().begin()
        # 优先使用 pinpong 板载蜂鸣器（支持音效），回退到数字引脚
        try:
            from pinpong.extension.unihiker import buzzer as _buzzer
            buzzer = _buzzer
            log("使用 pinpong 板载蜂鸣器（音效模式）")
        except ImportError:
            buzzer = Pin(BUZZER_PIN, Pin.OUT)
            log("使用数字引脚蜂鸣器（兼容模式）")
        button_take = Pin(BUTTON_TAKE_PIN, Pin.IN)
        button_emergency = Pin(BUTTON_EMERGENCY_PIN, Pin.IN)
        button_remind = Pin(BUTTON_REMIND_PIN, Pin.IN)
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
    if wifi_manager.is_wifi_connected():
        _set_online(check_network())
        if _get_online():
            # 尝试从本地恢复 device_token，否则重新注册
            if not load_device_token():
                register_device()
            sync_reminders()
            flush_local_logs()
    else:
        _set_online(False)
    log(f"网络状态: {'在线' if _get_online() else '离线'}")


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

    while True:
        now = datetime.datetime.now()
        now_str = now.strftime("%H:%M")

        # 每分钟检查提醒（含固定时间提醒 9:00/13:00/17:00）
        if now_str != last_minute:
            last_minute = now_str
            check_reminders()
            check_fixed_reminders()

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
                # 尝试恢复 token，否则重新注册
                if not load_device_token():
                    register_device()
                sync_reminders()
                flush_local_logs()
                update_gui_status("网络已恢复")

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
