#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniHiker M10 智能服药提醒终端主程序（对齐服务端 v2.29 API）
项目仓库: ha-ji-mi-MAN-BO/eating-medication (设备端单文件)
服务端接口基准: diaoyunxi/eating-medication server/app/api/v1/endpoints/public.py

与服务端交互总览
================
  认证方式：device_id + X-Device-Token
          首次 /device/register 返回 device_token，持久化到本地 chmod 0600
  心跳：每 30s POST /api/v1/public/device/register（复用注册端点当心跳）
  拉计划：每 60s GET /api/v1/public/device/schedule/{device_id}
  服药确认：POST /api/v1/public/device/message (message_type=medication)
          带 items[plan_id,scheduled_time] 让服务端精确落库
  紧急呼叫：POST /api/v1/public/device/message (message_type=emergency)
  照片上传：POST /api/v1/public/device/upload (base64 JPEG/PNG, 10MB 上限)
  AI 问答：POST /api/v1/public/ai/ask（IP 限流 10/分钟）
  主动下线：POST /api/v1/public/device/offline（程序 finally 调用）
"""

import os
os.environ["DISPLAY"] = os.environ.get("DISPLAY") or ":0"

import re
import time
import json
import base64
import queue
import threading
import datetime
import subprocess
import traceback
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

from unihiker import GUI
from pinpong.board import Board, Pin
from dfrobot_huskylensv2 import *
from unihiker_connet_wifi import *

# ============== 配置区 ==============
SERVER_BASE_URL = "https://my-website.ccwu.cc/eating-medication/server"
DEVICE_NAME = "M10智能药盒"
DEVICE_ID_SUFFIX = "275527387791320"
DEVICE_ID = "m10_" + DEVICE_ID_SUFFIX

# 新版服务端公开端点路径
_PUBLIC = f"{SERVER_BASE_URL}/api/v1/public"
API_REGISTER = f"{_PUBLIC}/device/register"
API_OFFLINE = f"{_PUBLIC}/device/offline"
API_SCHEDULE = f"{_PUBLIC}/device/schedule"
API_MESSAGE = f"{_PUBLIC}/device/message"
API_UPLOAD = f"{_PUBLIC}/device/upload"
API_AI_ASK = f"{_PUBLIC}/ai/ask"

TOKEN_FILE = "/root/device_token.txt"
CONFIG_FILE = "/root/medication_config.json"
LOG_FILE = "/root/medication_local.log"
PHOTO_DIR = "/root/medication_photos"
QUEUE_FILE = "/root/medication_log_queue.json"

WIFI_SSID = "666"
WIFI_PASSWORD = "15756491077"

# 硬件引脚
BUZZER_PIN = Pin.P25
BUTTON_TAKE_PIN = Pin.P21        # ~A 已吃药（按下高电平）
BUTTON_REMIND_PIN = Pin.P27      # B 键 直接启动提醒（按下低电平）
BUTTON_EMERGENCY_PIN = Pin.P28   # A 键 紧急呼叫（按下低电平，仅记录日志+上报）

# 提醒音量递增 / 间隔
VOLUME_INITIAL = 30
VOLUME_STEP = 15
VOLUME_MAX = 100
SNOOZE_MINUTES = 10
VOLUME_CONTROL = ""
TTS_RATE = 200

# 线程轮询间隔
CHECK_INTERVAL = 1
HEARTBEAT_INTERVAL = 30
SCHEDULE_POLL_INTERVAL = 60

# 固定服药提醒时间（每天触发，HH:MM）
FIXED_REMINDER_TIMES = ["09:00", "13:00", "17:00"]
CLOCK_REFRESH_INTERVAL = 1

# 人脸识别参数
FACE_ALGORITHM = ALGORITHM_FACE_RECOGNITION
FACE_TRIGGER_ID = 1      # 识别到此 ID 的人时自动触发吃药提醒（无活跃提醒且过冷却）
FACE_COOLDOWN = 30       # 人脸触发冷却秒数，避免短时间重复触发

# ============== 全局状态 ==============
state = {
    "online": False,
    "last_sync": None,
    "device_token": None,          # 服务端首次注册时签发，持久化到 TOKEN_FILE
    "schedules": [],               # 服务端 schedule 扁平列表原始缓存
    "reminders": [],               # 旧 reminders 格式（由 _schedules_to_reminders 生成）
    "medicines": [],               # 本地库存视图
    "active_alerts": {},           # {tid: {started_at,volume,reminder,plan_id,scheduled_time}}
    "current_volume": VOLUME_INITIAL,
    "camera_available": False,
    "triggered_fixed_times": set(),
    "current_date": None,
    "current_face_id": None,
}

lock = threading.Lock()
gui = None
buzzer = None
button_take = None
button_emergency = None
button_remind = None
huskylens = None

_gui_mode = "home"                # home / status / reminder
_clock_date_obj = None
_clock_time_obj = None
_clock_stop_event = threading.Event()
_face_id_obj = None               # 右下角人脸 ID 文本对象，gui.clear 后需重建

# ============== 工具函数 ==============
def log(msg, level="INFO"):
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def ensure_dirs():
    Path(PHOTO_DIR).mkdir(parents=True, exist_ok=True)


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log(f"读取配置失败: {e}", "ERROR")
    return {}


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"保存配置失败: {e}", "ERROR")


def _load_device_token():
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "r") as f:
                t = f.read().strip()
                if t:
                    return t
    except Exception as e:
        log(f"加载 device_token 失败: {e}", "WARNING")
    return None


def _save_device_token(token):
    try:
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            f.write(token)
        os.chmod(TOKEN_FILE, 0o600)
        log("device_token 已保存到本地")
    except Exception as e:
        log(f"保存 device_token 失败: {e}", "ERROR")


def connect_wifi(ssid, password):
    """使用 unihiker_connet_wifi.WiFiManager 连接 WiFi"""
    if not ssid:
        return False
    try:
        wifi_manager = WiFiManager()
        ok = wifi_manager.connect_wifi(ssid, password)
        log(f"WiFi 连接: ssid={ssid}, success={ok}")
        return bool(ok)
    except Exception as e:
        log(f"WiFi 连接异常: {e}", "ERROR")
        return False


def check_network():
    try:
        urllib.request.urlopen("https://my-website.ccwu.cc", timeout=5)
        return True
    except Exception:
        return False


def detect_volume_control():
    try:
        r = subprocess.run("aplay -l", shell=True, capture_output=True, text=True, timeout=5)
        usb_card = None
        for line in r.stdout.splitlines():
            if "USB" in line.upper() and line.lower().startswith("card "):
                try:
                    usb_card = int(line.split(':')[0].replace("card ", "").strip())
                    break
                except Exception:
                    continue
        controls = ["Speaker", "Headphone", "PCM", "Master", "Digital"]
        def exists(card_arg, ctrl):
            cmd = f"amixer {card_arg} scontrols" if card_arg else "amixer scontrols"
            rr = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3)
            return ctrl.lower() in rr.stdout.lower()
        if usb_card is not None:
            card_arg = f"-c {usb_card}"
            for ctrl in controls:
                if exists(card_arg, ctrl):
                    return f"{card_arg} set {ctrl}"
        for ctrl in controls:
            if exists("", ctrl):
                return f"set {ctrl}"
    except Exception as e:
        log(f"检测音量控制失败: {e}", "WARNING")
    return "set PCM"


_volume_control_cmd = None

def set_system_volume(vol):
    global _volume_control_cmd
    if not _volume_control_cmd:
        _volume_control_cmd = VOLUME_CONTROL if VOLUME_CONTROL else detect_volume_control()
    try:
        subprocess.run(f"amixer {_volume_control_cmd} {vol}%", shell=True, timeout=5)
    except Exception as e:
        log(f"设置音量失败: {e}", "ERROR")


# ============== TTS 语音播报 ==============
_speech_engine = None
_speak_queue = queue.Queue()
_speech_stop_event = threading.Event()
_speech_thread = None
_speech_lock = threading.Lock()


def init_speech():
    global _speech_engine, _speech_thread
    try:
        import pyttsx3
        _speech_engine = pyttsx3.init()
        _speech_engine.setProperty('volume', VOLUME_INITIAL / 100)
        _speech_engine.setProperty('rate', TTS_RATE)
        log("pyttsx3 TTS 初始化成功")
    except Exception as e:
        log(f"pyttsx3 初始化失败，回退 espeak: {e}", "WARNING")
        _speech_engine = None
    _speech_thread = threading.Thread(target=_speak_worker, daemon=True)
    _speech_thread.start()


def _speak_worker():
    global _speech_engine
    while not _speech_stop_event.is_set():
        try:
            item = _speak_queue.get(timeout=1)
            if item is None:
                break
            text, volume = item
            vol = volume if volume is not None else state.get("current_volume", VOLUME_INITIAL)
            set_system_volume(vol)
            if _speech_engine:
                try:
                    with _speech_lock:
                        _speech_engine.setProperty('volume', vol / 100)
                        _speech_engine.say(text)
                        _speech_engine.runAndWait()
                except Exception as e:
                    log(f"pyttsx3 播报失败: {e}", "ERROR")
                    try:
                        import pyttsx3
                        _speech_engine = pyttsx3.init()
                        _speech_engine.setProperty('rate', TTS_RATE)
                    except Exception:
                        _speech_engine = None
            else:
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
    _speak_queue.put((text, volume))


def stop_speech():
    _speech_stop_event.set()
    _speak_queue.put(None)
    if _speech_engine:
        try:
            _speech_engine.stop()
        except Exception:
            pass
    log("TTS 服务已停止")


def buzzer_beep(times=1, duration=0.2):
    try:
        if hasattr(buzzer, "play"):
            for _ in range(times):
                buzzer.play(buzzer.BA_DING, buzzer.Once)
                time.sleep(duration)
        else:
            for _ in range(times):
                buzzer.write_digital(1)
                time.sleep(duration)
                buzzer.write_digital(0)
                time.sleep(0.1)
    except Exception as e:
        log(f"蜂鸣器异常: {e}", "ERROR")


def capture_photo(filename=None):
    if filename is None:
        filename = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    path = os.path.join(PHOTO_DIR, filename)
    try:
        cmd = f"fswebcam -r 640x480 --no-banner {path}"
        r = subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
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


# ============== HTTP 通信（urllib + X-Device-ID + X-Device-Token）==============
def http_request(url, payload=None, timeout=15):
    """统一请求封装；GET(无 payload) 或 POST(json)，自动带双头认证"""
    try:
        headers = {"Content-Type": "application/json", "X-Device-ID": DEVICE_ID}
        if state.get("device_token"):
            headers["X-Device-Token"] = state["device_token"]
        data = None
        method = "GET"
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            method = "POST"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except Exception as e:
        log(f"HTTP 请求失败 {url}: {e}", "ERROR")
        return None


def register_or_heartbeat():
    """POST /device/register
    首次注册：服务端返回 device_token 并保存
    后续心跳：服务端仅刷新 last_heartbeat_at，不返回 token（防枚举）
    """
    payload = {"device_id": DEVICE_ID, "device_name": DEVICE_NAME}
    resp = http_request(API_REGISTER, payload)
    if resp and resp.get("status") == "ok":
        token = resp.get("device_token")
        if token:
            state["device_token"] = token
            _save_device_token(token)
            log(f"设备注册成功, user_id={resp.get('user_id')}")
        else:
            log(f"心跳上报成功, user_id={resp.get('user_id')}")
        return True
    log(f"注册/心跳失败: {resp}", "ERROR")
    return False


def unregister_device():
    """POST /device/offline，主动通知服务端置 last_heartbeat_at 为很早时间，立即判离线"""
    payload = {"device_id": DEVICE_ID}
    resp = http_request(API_OFFLINE, payload, timeout=3)
    if resp and resp.get("status") == "ok":
        log("设备离线通知成功")
        return True
    return False


def _extract_count(dosage_str):
    """从"1片/2粒/0.5片"等抽取剂量数字，失败返回 1（用于库存扣减）"""
    m = re.search(r'(\d+\.?\d*)', str(dosage_str or "1片"))
    if m:
        try:
            v = float(m.group(1))
            return int(v) if v == int(v) else v
        except Exception:
            pass
    return 1


def _schedules_to_reminders(schedules):
    """服务端扁平 schedule 列表 [{plan_id,drug_name,dosage,time,...}]
    合并同 plan_id 的多个 times，转成旧 reminders 格式保持后续逻辑不变。
    """
    merged = {}
    for s in schedules or []:
        pid = s.get("plan_id")
        if pid is None:
            continue
        t = s.get("time")
        if pid not in merged:
            merged[pid] = {
                "id": f"plan_{pid}",
                "_plan_id": pid,
                "user_name": DEVICE_NAME or "老人",
                "medicine_name": s.get("drug_name", "药品"),
                "dose": s.get("dosage", "1片"),
                "medicine_id": pid,
                "dose_count": _extract_count(s.get("dosage", "1片")),
                "times": [t] if t else [],
                "days": [1, 2, 3, 4, 5, 6, 7],
                "frequency": s.get("frequency", "每日"),
                "remaining_quantity": s.get("remaining_quantity"),
                "unit": s.get("unit"),
            }
        else:
            if t and t not in merged[pid]["times"]:
                merged[pid]["times"].append(t)
    return list(merged.values())


def get_medication_schedule():
    """GET /device/schedule/{device_id}，每 60s 轮询调用一次
    成功时刷新 state.schedules / reminders / medicines。
    """
    url = f"{API_SCHEDULE}/{urllib.parse.quote(DEVICE_ID)}"
    resp = http_request(url, timeout=15)
    if resp and isinstance(resp, dict):
        scheds = resp.get("schedules") or []
        with lock:
            state["schedules"] = scheds
            state["reminders"] = _schedules_to_reminders(scheds)
            # 同步库存视图（去重：每个 plan 一个药品条目）
            meds, seen = [], set()
            for r in state["reminders"]:
                pid = r.get("_plan_id")
                if pid in seen:
                    continue
                seen.add(pid)
                meds.append({
                    "id": r.get("medicine_id"),
                    "name": r.get("medicine_name"),
                    "remaining": r.get("remaining_quantity") if r.get("remaining_quantity") is not None else 99,
                    "unit": r.get("unit", "片"),
                    "daily_count": max(1, len(r.get("times", []))),
                    "per_time": r.get("dose_count", 1),
                    "threshold": 5,
                })
            state["medicines"] = meds
            state["last_sync"] = datetime.datetime.now().isoformat()
        log(f"同步计划: {len(scheds)} 个时间点 → {len(state['reminders'])} 个提醒")
        return True
    return False


def confirm_medication(reminder=None, taken_at=None):
    """POST /device/message  type=medication
    带 items=[{plan_id, scheduled_time}] 让服务端精确匹配并落库。
    上报失败时入本地队列等待下次 flush。
    """
    if taken_at is None:
        taken_at = datetime.datetime.now().isoformat()
    items = []
    drug_name = "药品"
    dosage = "1片"
    if reminder:
        pid = reminder.get("_plan_id")
        scheduled_time = reminder.get("_scheduled_time", "")
        drug_name = reminder.get("medicine_name", drug_name)
        dosage = reminder.get("dose", dosage)
        if pid is not None:
            items.append({
                "plan_id": pid,
                "drug_name": drug_name,
                "scheduled_time": scheduled_time or datetime.datetime.now().strftime("%H:%M"),
            })
    payload = {
        "device_id": DEVICE_ID,
        "message_type": "medication",
        "content": f"已服用 {drug_name} {dosage}",
        "data": {
            "drug_name": drug_name,
            "dosage": dosage,
            "taken_at": taken_at,
            "items": items,
        },
    }
    resp = http_request(API_MESSAGE, payload)
    if resp and resp.get("status") == "ok":
        log(f"服药确认已上报: {drug_name} {dosage}")
        return True
    queue_local_log(payload, "medication")
    return False


def send_emergency():
    """POST /device/message  type=emergency"""
    payload = {
        "device_id": DEVICE_ID,
        "message_type": "emergency",
        "content": "紧急求助",
    }
    resp = http_request(API_MESSAGE, payload)
    if resp and resp.get("status") == "ok":
        tts_speak("紧急通知已发送给家属")
        return True
    tts_speak("紧急通知发送失败，请手动拨打 120")
    queue_local_log(payload, "emergency")
    return False


def upload_photo(image_path, note=""):
    """POST /device/upload  base64 JPEG/PNG（10MB 上限，服务端会校验魔数）"""
    if not (image_path and os.path.exists(image_path)):
        return False
    b64 = image_to_base64(image_path)
    if not b64:
        return False
    payload = {"device_id": DEVICE_ID, "image_base64": b64, "note": note}
    resp = http_request(API_UPLOAD, payload, timeout=30)
    if resp and resp.get("status") == "ok":
        log(f"照片上传成功: {resp.get('path', '')}")
        return True
    # 上传失败也入本地队列（注意：大 base64 可能撑爆 JSON，故失败仅记录日志）
    log(f"照片上传失败，稍后重试", "WARNING")
    return False


def ask_ai(question):
    """POST /ai/ask  公开接口，IP 限流 10/分钟"""
    payload = {"question": question, "device_id": DEVICE_ID}
    resp = http_request(API_AI_ASK, payload, timeout=30)
    if resp and isinstance(resp, dict) and "answer" in resp:
        return resp["answer"]
    return "抱歉，AI 服务暂时不可用"


def queue_local_log(payload, kind):
    """离线队列：失败的 medication / emergency 上报"""
    try:
        q = []
        if os.path.exists(QUEUE_FILE):
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                q = json.load(f)
        q.append({"kind": kind, "payload": payload, "ts": datetime.datetime.now().isoformat()})
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(q, f, ensure_ascii=False)
    except Exception as e:
        log(f"本地队列写入失败: {e}", "ERROR")


def flush_local_logs():
    if not os.path.exists(QUEUE_FILE):
        return
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            q = json.load(f)
        remain = []
        for item in q:
            kind = item.get("kind")
            payload = item.get("payload")
            ok = False
            if kind in ("medication", "emergency"):
                resp = http_request(API_MESSAGE, payload)
                ok = bool(resp and resp.get("status") == "ok")
            else:
                continue
            if not ok:
                remain.append(item)
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(remain, f, ensure_ascii=False)
        log(f"刷新本地队列: 成功 {len(q)-len(remain)}, 剩余 {len(remain)}")
    except Exception as e:
        log(f"刷新本地队列失败: {e}", "ERROR")


# ============== 提醒核心 ==============
def reset_fixed_trigger_if_new_day():
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    if state["current_date"] != today:
        state["current_date"] = today
        state["triggered_fixed_times"] = set()
        log(f"日期切换到 {today}，已重置固定提醒触发记录")


def check_fixed_reminders():
    """固定时间 9:00/13:00/17:00，每天每个时间点仅触发一次"""
    reset_fixed_trigger_if_new_day()
    now_str = datetime.datetime.now().strftime("%H:%M")
    for t in FIXED_REMINDER_TIMES:
        if t == now_str and t not in state["triggered_fixed_times"]:
            state["triggered_fixed_times"].add(t)
            reminder = {
                "id": f"fixed_{t}",
                "user_name": "老人",
                "medicine_name": "药品",
                "dose": "请按医嘱服用",
                "medicine_id": None,
                "dose_count": 1,
            }
            log(f"触发固定时间提醒: {t}")
            trigger_alert(reminder, scheduled_time=t)


def check_reminders():
    now = datetime.datetime.now()
    now_str = now.strftime("%H:%M")
    weekday = now.weekday() + 1
    with lock:
        reminders = list(state["reminders"])
    for r in reminders:
        tid = r.get("id")
        times = r.get("times", [])
        days = r.get("days", [1, 2, 3, 4, 5, 6, 7])
        if weekday not in days:
            continue
        for t in times:
            if t == now_str and tid not in state["active_alerts"]:
                trigger_alert(r, scheduled_time=t)


def trigger_alert(reminder, scheduled_time=""):
    """触发提醒：记住 plan_id + scheduled_time，用于 confirm 精确匹配上报"""
    tid = reminder.get("id")
    name = reminder.get("user_name", "老人")
    drug = reminder.get("medicine_name", "药品")
    dose = reminder.get("dose", "")
    face_id = state.get("current_face_id")
    with lock:
        state["active_alerts"][tid] = {
            "started_at": datetime.datetime.now(),
            "volume": VOLUME_INITIAL,
            "reminder": reminder,
            "plan_id": reminder.get("_plan_id"),
            "scheduled_time": scheduled_time or datetime.datetime.now().strftime("%H:%M"),
        }
    log(f"触发提醒: tid={tid} face_id={face_id} drug={drug} dose={dose}")
    update_gui_reminder(name, drug, dose)
    threading.Thread(target=alert_loop, args=(tid,), daemon=True).start()


def alert_loop(tid):
    """提醒播报循环：
    第一句 "id{X}老人来吃药" / "{name}，来吃药了"
    之后每轮重复播报 "吃{药品}{剂量}"
    每 SNOOZE_MINUTES 分钟加大音量 VOLUME_STEP
    """
    first = True
    while tid in state["active_alerts"]:
        info = state["active_alerts"][tid]
        volume = info["volume"]
        reminder = info["reminder"]
        drug = reminder.get("medicine_name", "药品")
        dose = reminder.get("dose", "1片")
        name = reminder.get("user_name", "老人")
        face_id = state.get("current_face_id")
        if first:
            if face_id:
                opening = f"id{face_id}老人来吃药"
            else:
                opening = f"{name}，来吃药了"
            first = False
            buzzer_beep(times=3, duration=0.3)
            tts_speak(opening, volume=volume)
        repeat_msg = f"吃{drug}，{dose}"
        buzzer_beep(times=2, duration=0.25)
        tts_speak(repeat_msg, volume=volume)
        time.sleep(SNOOZE_MINUTES * 60)
        if tid in state["active_alerts"]:
            info["volume"] = min(volume + VOLUME_STEP, VOLUME_MAX)


def confirm_take(tid=None):
    """确认服药：上报 message_type=medication（精确 items），异步上传照片，返回主页"""
    photo_path = None
    if state.get("camera_available"):
        photo_path = capture_photo(filename=f"take_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    reminder = {}
    plan_id = None
    scheduled_time = ""
    if tid and tid in state["active_alerts"]:
        info = state["active_alerts"][tid]
        reminder = dict(info["reminder"])
        plan_id = info.get("plan_id")
        scheduled_time = info.get("scheduled_time", "")
        if plan_id is not None:
            reminder["_plan_id"] = plan_id
        reminder["_scheduled_time"] = scheduled_time
        del state["active_alerts"][tid]
        confirm_medication(reminder)
    else:
        confirm_medication()
    if photo_path:
        threading.Thread(target=lambda: upload_photo(photo_path, note="服药确认照片"), daemon=True).start()
    tts_speak("已记录服药")
    update_gui_home()
    update_stock(reminder.get("medicine_id"), _extract_count(reminder.get("dose", "1片")))


def update_stock(medicine_id, used_count):
    if not medicine_id or not used_count:
        return
    with lock:
        for m in state["medicines"]:
            if m.get("id") == medicine_id:
                m["remaining"] = max(0, m.get("remaining", 0) - used_count)
                cfg = load_config()
                cfg["medicines"] = state["medicines"]
                save_config(cfg)
                threshold = m.get("threshold", 5) * m.get("daily_count", 1)
                if m["remaining"] < threshold:
                    threading.Thread(target=low_stock_alert, args=(m,), daemon=True).start()
                break


def low_stock_alert(medicine):
    msg = f"{medicine.get('name')} 余量不足，请及时补药"
    log(msg)
    tts_speak(msg)
    update_gui_status(msg, alert=True)


def recognize_medicine():
    """AI 药物识别：拍照 → 本地 pytesseract OCR → 上传照片 → 询问服务端 AI
    vision/recognize 需 JWT，device 端不可用，故走公开 /ai/ask。
    """
    if not state.get("camera_available"):
        tts_speak("摄像头未就绪，请手动核对药品")
        update_gui_home()
        return
    update_gui_status("正在识别药品...")
    photo_path = capture_photo(filename=f"ocr_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    if not photo_path:
        tts_speak("拍照失败")
        update_gui_home()
        return
    text = ""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(photo_path).convert("L")
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        log(f"OCR: {text.strip()[:200]}")
    except Exception as e:
        log(f"OCR 未就绪: {e}", "WARNING")
    threading.Thread(target=lambda: upload_photo(photo_path, "药品识别图片"), daemon=True).start()
    if text.strip():
        q = f"以下文字是药品包装上的 OCR 结果，请识别是哪种药，简短告诉我药名、用途、每次用量：{text.strip()[:500]}"
        answer = ask_ai(q)
        display_txt = answer[:50] + ("…" if len(answer) > 50 else "")
        update_gui_status(display_txt)
        tts_speak(answer)
    else:
        tts_speak("未能识别文字，请手动核对说明书")
        update_gui_home()


def calculate_remaining_days():
    with lock:
        for m in state["medicines"]:
            total = m.get("remaining", 0)
            per_time = m.get("per_time", 1)
            freq = m.get("daily_count", 1)
            daily = per_time * freq
            if daily > 0:
                m["remaining_days"] = int(total / daily)
            else:
                m["remaining_days"] = 999
            if m["remaining_days"] < 5:
                threading.Thread(target=low_stock_alert, args=(m,), daemon=True).start()


# ============== GUI 更新（所有界面右下角统一绘制人脸 ID）==============
def _format_date(now):
    return now.strftime("%Y-%m-%d")

def _format_time(now):
    return now.strftime("%H:%M:%S")

def _draw_face_id_label():
    """在当前屏幕右下角绘制小字号人脸 idX；无识别则置空串。
    每次 gui.clear() 后旧的 _face_id_obj 失效，需重建。
    """
    global _face_id_obj
    if not gui:
        return
    fid = state.get("current_face_id")
    txt = f"id{fid}" if fid else ""
    try:
        if _face_id_obj is not None:
            _face_id_obj.config(text=txt)
            return
    except Exception:
        _face_id_obj = None
    try:
        _face_id_obj = gui.draw_text(
            x=238, y=316, text=txt,
            font_size=10, color="#888888", origin="bottom_right",
        )
    except Exception as e:
        log(f"右下角人脸ID绘制失败: {e}", "WARNING")


def _update_face_id_display():
    """face_thread 每秒调用：尝试复用旧对象，失败则重建"""
    _draw_face_id_label()


def update_gui_status(text, alert=False):
    global _gui_mode, _face_id_obj
    if not gui:
        return
    try:
        _gui_mode = "status"
        color = "#FF4444" if alert else "#333333"
        gui.clear()
        _face_id_obj = None
        gui.draw_text(x=120, y=40, text="智能服药提醒", font_size=20, color="#000000", origin="center")
        gui.draw_text(x=120, y=100, text=text, font_size=16, color=color, origin="center")
        status_text = "在线" if state["online"] else "离线模式"
        gui.draw_text(x=120, y=200, text=status_text, font_size=14, color="#666666", origin="center")
        _draw_face_id_label()
    except Exception as e:
        log(f"GUI 更新失败: {e}", "ERROR")


def update_gui_home():
    global _gui_mode, _clock_date_obj, _clock_time_obj, _face_id_obj
    if not gui:
        return
    try:
        gui.clear()
        _gui_mode = "home"
        _clock_date_obj = None
        _clock_time_obj = None
        _face_id_obj = None
        gui.draw_text(x=120, y=30, text="智能服药提醒", font_size=18, color="#000000", origin="center")
        status_text = "在线" if state["online"] else "离线模式"
        gui.draw_text(x=120, y=65, text=status_text, font_size=12, color="#666666", origin="center")
        now = datetime.datetime.now()
        _clock_date_obj = gui.draw_text(
            x=120, y=120, text=_format_date(now),
            font_size=16, color="#333333", origin="center",
        )
        _clock_time_obj = gui.draw_text(
            x=120, y=165, text=_format_time(now),
            font_size=24, color="#0050FF", origin="center",
        )
        gui.draw_text(x=120, y=220, text="B键启动提醒 A键紧急", font_size=11, color="#666666", origin="center")
        _draw_face_id_label()
    except Exception as e:
        log(f"GUI 更新失败: {e}", "ERROR")


def update_gui_reminder(name, drug, dose):
    global _gui_mode, _face_id_obj
    if not gui:
        return
    try:
        gui.clear()
        _gui_mode = "reminder"
        _face_id_obj = None
        gui.draw_text(x=120, y=40, text="该吃药了", font_size=20, color="#FF0000", origin="center")
        gui.draw_text(x=120, y=100, text=f"{name}，该吃 {drug}", font_size=16, color="#FF4444", origin="center")
        gui.draw_text(x=120, y=140, text=f"每次 {dose}", font_size=16, color="#FF4444", origin="center")
        gui.draw_text(x=120, y=220, text="按~A键确认已吃药", font_size=12, color="#666666", origin="center")
        _draw_face_id_label()
    except Exception as e:
        log(f"GUI 更新失败: {e}", "ERROR")


def clock_thread():
    while not _clock_stop_event.is_set():
        try:
            if gui and _gui_mode == "home":
                now = datetime.datetime.now()
                if _clock_time_obj is not None:
                    try:
                        _clock_time_obj.config(text=_format_time(now))
                    except Exception:
                        pass
                if _clock_date_obj is not None:
                    try:
                        _clock_date_obj.config(text=_format_date(now))
                    except Exception:
                        pass
        except Exception as e:
            log(f"时钟刷新失败: {e}", "WARNING")
        time.sleep(CLOCK_REFRESH_INTERVAL)


# ============== 人脸识别（HuskylensV2 I2C）==============
def face_thread():
    """后台线程：每 0.3s 读取 HuskylensV2 靠中心的人脸 ID 并刷新右下角
    识别到 FACE_TRIGGER_ID=id1 且当前无活跃提醒 + 30s 冷却 → 自动触发吃药提醒
    """
    global huskylens
    last_face_update = 0
    last_trigger = 0
    try:
        huskylens = HuskylensV2_I2C()
        huskylens.knock()
        huskylens.switchAlgorithm(FACE_ALGORITHM)
        log("HuskylensV2 人脸识别初始化成功")
    except Exception as e:
        log(f"HuskylensV2 初始化失败（人脸识别不可用，其他功能正常）: {e}", "WARNING")
        huskylens = None
        return
    while True:
        try:
            huskylens.getResult(FACE_ALGORITHM)
            fid = -1
            if huskylens.available(FACE_ALGORITHM):
                center = huskylens.getCachedCenterResult(FACE_ALGORITHM)
                if center is not None and hasattr(center, "ID"):
                    try:
                        fid = int(center.ID or 0)
                    except Exception:
                        fid = -1
            now_ts = time.time()
            if now_ts - last_face_update >= 1:
                last_face_update = now_ts
                state["current_face_id"] = fid if fid > 0 else None
                _update_face_id_display()
            if (fid == FACE_TRIGGER_ID
                    and not state["active_alerts"]
                    and now_ts - last_trigger > FACE_COOLDOWN):
                last_trigger = now_ts
                log(f"人脸识别 id{fid} 触发吃药提醒")
                auto = {
                    "id": f"face_{fid}_{int(now_ts)}",
                    "user_name": f"id{fid}老人",
                    "medicine_name": "测试药品",
                    "dose": "1粒",
                    "medicine_id": None,
                    "dose_count": 1,
                }
                trigger_alert(auto)
        except Exception as e:
            log(f"人脸识别线程异常: {e}", "WARNING")
            time.sleep(2)
            continue
        time.sleep(0.3)


# ============== 按钮处理 ==============
def on_take_button_pressed():
    """P21 ~A 已吃药：有活跃提醒才确认"""
    log("已吃药按钮被按下")
    if state["active_alerts"]:
        tid = next(iter(state["active_alerts"]))
        confirm_take(tid)


def on_emergency_button_pressed():
    """P28 A 键 紧急呼叫：上报 message_type=emergency 并记录日志"""
    log("紧急按钮被按下", "WARNING")
    send_emergency()
    update_gui_status("已记录紧急呼叫", alert=True)


def on_remind_button_pressed():
    """P27 B 键 直接启动吃药提醒（测试）"""
    log("提醒按钮被按下，直接启动吃药提醒")
    test = {
        "id": "test_reminder",
        "user_name": "老人",
        "medicine_name": "测试药品",
        "dose": "1粒",
        "medicine_id": None,
        "dose_count": 1,
    }
    trigger_alert(test)


# ============== 初始化 / 线程 / 主循环 ==============
def init_hardware():
    global buzzer, button_take, button_emergency, button_remind, gui
    try:
        Board().begin()
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
            log(f"GUI 初始化失败，无界面模式: {e}", "WARNING")
            gui = None
        r = subprocess.run("which fswebcam", shell=True, capture_output=True)
        state["camera_available"] = r.returncode == 0
        log("硬件初始化完成")
    except Exception as e:
        log(f"硬件初始化异常: {e}", "ERROR")


def init_network():
    cfg = load_config()
    ssid = cfg.get("wifi_ssid", WIFI_SSID)
    pwd = cfg.get("wifi_password", WIFI_PASSWORD)
    state["device_token"] = _load_device_token()
    if ssid and connect_wifi(ssid, pwd):
        state["online"] = check_network()
        if state["online"]:
            register_or_heartbeat()
            get_medication_schedule()
            flush_local_logs()
    else:
        state["online"] = False
    log(f"网络状态: {'在线' if state['online'] else '离线'}")


def button_thread():
    last_take = 0
    last_emergency = 0
    last_remind = 0
    while True:
        now = time.time()
        if button_take and button_take.read_digital() == 1 and now - last_take > 2:
            last_take = now
            on_take_button_pressed()
        if button_remind and button_remind.read_digital() == 0 and now - last_remind > 3:
            last_remind = now
            on_remind_button_pressed()
        if button_emergency and button_emergency.read_digital() == 0 and now - last_emergency > 3:
            last_emergency = now
            on_emergency_button_pressed()
        time.sleep(0.1)


def heartbeat_thread():
    """每 30s 调用一次 register_or_heartbeat，让服务端 last_heartbeat_at 始终 < 60s → 在线"""
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        if state["online"]:
            try:
                register_or_heartbeat()
            except Exception as e:
                log(f"心跳线程异常: {e}", "WARNING")


def schedule_thread():
    """每 60s 拉一次用药计划，家属端改完后 1 分钟内同步到设备"""
    while True:
        time.sleep(SCHEDULE_POLL_INTERVAL)
        if state["online"]:
            try:
                get_medication_schedule()
            except Exception as e:
                log(f"计划拉取线程异常: {e}", "WARNING")


def main_loop():
    last_minute = ""
    last_stock_check = 0
    last_flush = 0
    while True:
        now = datetime.datetime.now()
        now_str = now.strftime("%H:%M")
        if now_str != last_minute:
            last_minute = now_str
            check_reminders()
            check_fixed_reminders()
        if time.time() - last_stock_check > 6 * 3600:
            last_stock_check = time.time()
            calculate_remaining_days()
        if time.time() - last_flush > 30 * 60:
            last_flush = time.time()
            if state["online"]:
                flush_local_logs()
        if not state["online"] and now.second % 30 == 0:
            if check_network():
                state["online"] = True
                register_or_heartbeat()
                get_medication_schedule()
                flush_local_logs()
                update_gui_status("网络已恢复")
        time.sleep(CHECK_INTERVAL)


def main():
    ensure_dirs()
    log("程序启动")
    init_hardware()
    init_speech()
    update_gui_status("正在连接网络...")
    init_network()

    threading.Thread(target=button_thread, daemon=True).start()
    threading.Thread(target=clock_thread, daemon=True).start()
    threading.Thread(target=heartbeat_thread, daemon=True).start()
    threading.Thread(target=schedule_thread, daemon=True).start()
    threading.Thread(target=face_thread, daemon=True).start()

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
            if state.get("online"):
                unregister_device()
        except Exception:
            pass
        stop_speech()
