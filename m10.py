#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniHiker M10 智能服药提醒终端主程序
项目地址适配: https://my-website.ccwu.cc/eating-medication/family/
设备配对码: 275527387791320

本程序使用 Python 标准库 + UniHiker 原生 API (unihiker/pinpong) + pyttsx3 TTS,
不依赖 cv2、requests、schedule 等第三方库。
"""

import os
# 必须在导入 tkinter/unihiker 之前强制设置 DISPLAY（SSH 远程运行时需要）
os.environ["DISPLAY"] = os.environ.get("DISPLAY") or ":0"

import time
import json
import base64
import queue
import threading
import datetime
import subprocess
import traceback
import urllib.request
import urllib.error
from pathlib import Path

# 适配 UniHiker 平台
from unihiker import GUI
from pinpong.board import Board, Pin
from dfrobot_huskylensv2 import *

# ============== 配置区 ==============
BASE_URL = "https://my-website.ccwu.cc/eating-medication/family"
PAIR_CODE = "275527387791320"
DEVICE_ID = "m10_" + PAIR_CODE

# API 端点（兼容 BASE_URL 及其子页面）
API_REGISTER = f"{BASE_URL}/api/device/register"
API_REMINDERS = f"{BASE_URL}/api/reminders"
API_LOGS = f"{BASE_URL}/api/logs"
API_DRUG_QUERY = f"{BASE_URL}/api/drug/query"
API_REFILL = f"{BASE_URL}/api/refill/query"
API_EMERGENCY = f"{BASE_URL}/api/emergency/notify"

CONFIG_FILE = "/root/medication_config.json"
LOG_FILE = "/root/medication_local.log"
PHOTO_DIR = "/root/medication_photos"
QUEUE_FILE = "/root/medication_log_queue.json"

WIFI_SSID = "TP-LINK_5G_36DB"
WIFI_PASSWORD = "15756491077"

# 硬件引脚
BUZZER_PIN = Pin.P25      # 蜂鸣器
BUTTON_TAKE_PIN = Pin.P21  # 已吃药按钮（~A，按下高电平，松开低电平）
BUTTON_REMIND_PIN = Pin.P27  # B键：直接启动吃药提醒（按下低电平）
BUTTON_EMERGENCY_PIN = Pin.P28  # A键：紧急呼叫（按下低电平，仅记录日志）

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
    "last_sync": None,
    "reminders": [],          # 服药提醒列表
    "medicines": [],          # 药品库存
    "active_alerts": {},      # 当前活跃的提醒 {reminder_id: info}
    "current_volume": VOLUME_INITIAL,
    "camera_available": False,
    "triggered_fixed_times": set(),  # 当天已触发的固定提醒时间，避免重复触发
    "current_date": None,     # 当天日期字符串 YYYY-MM-DD，用于跨天重置触发记录
}

lock = threading.Lock()

gui = None
buzzer = None
button_take = None
button_emergency = None
button_remind = None

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


def connect_wifi(ssid, password):
    """连接 WiFi，返回是否成功"""
    if not ssid:
        return False
    try:
        cmd = f'nmcli dev wifi connect "{ssid}" password "{password}"'
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        ok = r.returncode == 0 or "successfully" in r.stdout.lower() or "已激活" in r.stdout
        log(f"WiFi 连接: {r.stdout.strip()}")
        return ok
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
    try:
        import pyttsx3
        _speech_engine = pyttsx3.init()
        _speech_engine.setProperty('volume', VOLUME_INITIAL / 100)
        _speech_engine.setProperty('rate', TTS_RATE)
        log("pyttsx3 TTS 引擎初始化成功")
    except Exception as e:
        log(f"pyttsx3 初始化失败，将回退到 espeak: {e}", "WARNING")
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
            vol = volume if volume is not None else state.get("current_volume", VOLUME_INITIAL)

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
                    try:
                        import pyttsx3
                        _speech_engine = pyttsx3.init()
                        _speech_engine.setProperty('rate', TTS_RATE)
                    except Exception:
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


def capture_photo(filename=None):
    """使用系统 fswebcam 命令拍照，不依赖 cv2"""
    if filename is None:
        filename = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    path = os.path.join(PHOTO_DIR, filename)
    try:
        # 优先使用 fswebcam（Linux 下 USB/CSI 摄像头通用）
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


# ============== 网络通信（仅使用 urllib） ==============

def http_request(url, payload=None, timeout=15):
    """封装 urllib，payload 为 dict 时 POST，否则 GET"""
    try:
        headers = {"Content-Type": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except Exception as e:
        log(f"HTTP 请求失败 {url}: {e}", "ERROR")
        return None


def register_device():
    payload = {
        "device_id": DEVICE_ID,
        "pair_code": PAIR_CODE,
        "model": "unihiker_m10",
        "base_url": BASE_URL,
    }
    resp = http_request(API_REGISTER, payload)
    if resp and resp.get("code") == 0:
        log("设备注册成功")
        return True
    log(f"设备注册失败: {resp}", "ERROR")
    return False


def sync_reminders():
    url = f"{API_REMINDERS}?device_id={DEVICE_ID}&pair_code={PAIR_CODE}"
    resp = http_request(url)
    if resp and resp.get("code") == 0:
        with lock:
            state["reminders"] = resp.get("data", {}).get("reminders", [])
            state["medicines"] = resp.get("data", {}).get("medicines", [])
            state["last_sync"] = datetime.datetime.now().isoformat()
        log(f"同步提醒: {len(state['reminders'])} 条")
        return True
    return False


def upload_log(event_type, detail, photo_path=None):
    payload = {
        "device_id": DEVICE_ID,
        "pair_code": PAIR_CODE,
        "event_type": event_type,
        "detail": detail,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    if photo_path and os.path.exists(photo_path):
        payload["photo"] = image_to_base64(photo_path)
    resp = http_request(API_LOGS, payload)
    if resp and resp.get("code") == 0:
        log(f"日志上传成功: {event_type}")
        return True
    # 离线时写入本地队列
    queue_local_log(payload)
    return False


def queue_local_log(payload):
    try:
        queue = []
        if os.path.exists(QUEUE_FILE):
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                queue = json.load(f)
        queue.append(payload)
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False)
    except Exception as e:
        log(f"本地日志队列写入失败: {e}", "ERROR")


def flush_local_logs():
    if not os.path.exists(QUEUE_FILE):
        return
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            queue = json.load(f)
        remain = []
        for payload in queue:
            resp = http_request(API_LOGS, payload)
            if not (resp and resp.get("code") == 0):
                remain.append(payload)
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(remain, f, ensure_ascii=False)
        log(f"刷新本地日志: 成功 {len(queue) - len(remain)}, 剩余 {len(remain)}")
    except Exception as e:
        log(f"刷新本地日志失败: {e}", "ERROR")


def query_drug_by_ocr(text):
    payload = {"device_id": DEVICE_ID, "pair_code": PAIR_CODE, "text": text}
    return http_request(API_DRUG_QUERY, payload)


def query_refill(medicine_id):
    payload = {"device_id": DEVICE_ID, "pair_code": PAIR_CODE, "medicine_id": medicine_id}
    return http_request(API_REFILL, payload)


def notify_emergency(contact="120"):
    payload = {
        "device_id": DEVICE_ID,
        "pair_code": PAIR_CODE,
        "contact": contact,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    resp = http_request(API_EMERGENCY, payload)
    if resp and resp.get("code") == 0:
        tts_speak("紧急通知已发送给家属")
        return True
    tts_speak("紧急通知发送失败，请手动拨打 120")
    return False


# ============== 提醒核心 ==============

def reset_fixed_trigger_if_new_day():
    """跨天时清空当日已触发固定提醒记录，避免第二天漏触发"""
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    if state["current_date"] != today:
        state["current_date"] = today
        state["triggered_fixed_times"] = set()
        log(f"日期切换到 {today}，已重置固定提醒触发记录")


def check_fixed_reminders():
    """检查固定服药提醒时间（9:00 / 13:00 / 17:00），每天每个时间点仅触发一次"""
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
            trigger_alert(reminder)


def check_reminders():
    now = datetime.datetime.now()
    now_str = now.strftime("%H:%M")
    weekday = now.weekday() + 1

    for r in state["reminders"]:
        tid = r.get("id")
        times = r.get("times", [])
        days = r.get("days", [1, 2, 3, 4, 5, 6, 7])
        if weekday not in days:
            continue
        for t in times:
            if t == now_str and tid not in state["active_alerts"]:
                trigger_alert(r)


def trigger_alert(reminder):
    tid = reminder.get("id")
    name = reminder.get("user_name", "老人")
    drug = reminder.get("medicine_name", "药品")
    dose = reminder.get("dose", "")
    with lock:
        state["active_alerts"][tid] = {
            "started_at": datetime.datetime.now(),
            "volume": VOLUME_INITIAL,
            "reminder": reminder,
        }
    msg = f"{name}，该吃 {drug} 了，每次 {dose}"
    log(f"触发提醒: {msg}")
    update_gui_reminder(name, drug, dose)
    threading.Thread(target=alert_loop, args=(tid,), daemon=True).start()


def alert_loop(tid):
    while tid in state["active_alerts"]:
        info = state["active_alerts"][tid]
        volume = info["volume"]
        reminder = info["reminder"]
        msg = f"{reminder.get('user_name', '老人')}，该吃 {reminder.get('medicine_name', '药品')} 了"
        buzzer_beep(times=3, duration=0.3)
        tts_speak(msg, volume=volume)
        # 每 10 分钟增大音量
        time.sleep(SNOOZE_MINUTES * 60)
        if tid in state["active_alerts"]:
            info["volume"] = min(volume + VOLUME_STEP, VOLUME_MAX)


def confirm_take(tid=None):
    """确认服药：拍照上传（无摄像头则跳过）并停止提醒，返回主页"""
    photo_path = None
    if state.get("camera_available"):
        photo_path = capture_photo(filename=f"take_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    if tid and tid in state["active_alerts"]:
        reminder = state["active_alerts"][tid]["reminder"]
        del state["active_alerts"][tid]
    else:
        reminder = {}

    detail = {
        "action": "confirm_take",
        "medicine": reminder.get("medicine_name", ""),
        "user": reminder.get("user_name", ""),
        "photo_path": photo_path,
    }
    upload_log("confirm_take", detail, photo_path)
    tts_speak("已记录服药")
    update_gui_home()
    update_stock(reminder.get("medicine_id"), reminder.get("dose_count", 1))


def update_stock(medicine_id, used_count):
    if not medicine_id:
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
    if state["online"]:
        resp = query_refill(medicine.get("id"))
        if resp and resp.get("data"):
            cheapest = resp["data"]
            buy_msg = f"最优购: {cheapest.get('name')}，价格 {cheapest.get('price')} 元"
            tts_speak(buy_msg)


# ============== AI 药物识别 ==============

def recognize_medicine():
    if not state.get("camera_available"):
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
    # 尝试使用 pytesseract（如果设备已安装）
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(photo_path).convert("L")
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        log(f"OCR 结果: {text.strip()}")
    except Exception as e:
        log(f"OCR 失败或未安装 tesseract: {e}", "WARNING")
        text = ""

    if state["online"] and text.strip():
        resp = query_drug_by_ocr(text.strip())
        if resp and resp.get("code") == 0:
            info = resp.get("data", {})
            speak = f"这是 {info.get('name')}，{info.get('usage')}，每次 {info.get('dose')}"
            update_gui_status(speak)
            tts_speak(speak)
            return
    tts_speak("未能识别药品，请手动核对说明书")


# ============== 余量监测 ==============

def calculate_remaining_days():
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
                threading.Thread(target=low_stock_alert, args=(m,), daemon=True).start()


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
        _gui_mode = "status"
        color = "#FF4444" if alert else "#333333"
        gui.clear()
        gui.draw_text(x=120, y=40, text="智能服药提醒", font_size=20, color="#000000", origin="center")
        gui.draw_text(x=120, y=100, text=text, font_size=16, color=color, origin="center")
        status = "在线" if state["online"] else "离线模式"
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
        _clock_date_obj = None
        _clock_time_obj = None
        gui.draw_text(x=120, y=30, text="智能服药提醒", font_size=18, color="#000000", origin="center")
        status = "在线" if state["online"] else "离线模式"
        gui.draw_text(x=120, y=65, text=status, font_size=12, color="#666666", origin="center")
        now = datetime.datetime.now()
        # 日期行
        _clock_date_obj = gui.draw_text(
            x=120, y=120, text=_format_date(now),
            font_size=16, color="#333333", origin="center",
        )
        # 时分秒行（醒目蓝色）
        _clock_time_obj = gui.draw_text(
            x=120, y=165, text=_format_time(now),
            font_size=24, color="#0050FF", origin="center",
        )
        gui.draw_text(x=120, y=220, text="B键启动提醒 A键紧急", font_size=11, color="#666666", origin="center")
        _gui_mode = "home"
    except Exception as e:
        log(f"GUI 更新失败: {e}", "ERROR")


def update_gui_reminder(name, drug, dose):
    """显示吃药提醒界面（分两行避免文字过长换行）"""
    global _gui_mode
    if not gui:
        return
    try:
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


# ============== 按钮处理 ==============

def on_take_button_pressed():
    """P21 已吃药按钮（~A）：仅在吃药提醒时确认已吃药"""
    log("已吃药按钮被按下")
    if state["active_alerts"]:
        tid = next(iter(state["active_alerts"]))
        confirm_take(tid)


def on_emergency_button_pressed():
    """P28 A键：紧急呼叫（仅记录日志，不鸣叫，联网功能后续再接入）"""
    log("紧急按钮被按下（仅记录日志，联网呼叫功能待后续接入）", "WARNING")
    update_gui_status("已记录紧急呼叫", alert=True)


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
        state["camera_available"] = r.returncode == 0
        log("硬件初始化完成")
    except Exception as e:
        log(f"硬件初始化异常: {e}", "ERROR")


def init_network():
    cfg = load_config()
    ssid = cfg.get("wifi_ssid", WIFI_SSID)
    pwd = cfg.get("wifi_password", WIFI_PASSWORD)
    if ssid and connect_wifi(ssid, pwd):
        state["online"] = check_network()
        if state["online"]:
            register_device()
            sync_reminders()
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
        # P21 已吃药按钮（~A）：按下高电平（1），松开低电平（0）
        if button_take and button_take.read_digital() == 1 and now - last_take > 2:
            last_take = now
            on_take_button_pressed()
        # P27 B键启动吃药提醒：按下低电平（0）
        if button_remind and button_remind.read_digital() == 0 and now - last_remind > 3:
            last_remind = now
            on_remind_button_pressed()
        # P28 A键紧急呼叫：按下低电平（0），仅记录日志
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
            if state["online"]:
                sync_reminders()

        # 每 6 小时检查库存
        if time.time() - last_stock_check > 6 * 3600:
            last_stock_check = time.time()
            calculate_remaining_days()

        # 每 30 分钟刷新离线日志
        if time.time() - last_flush > 30 * 60:
            last_flush = time.time()
            if state["online"]:
                flush_local_logs()

        # 定期检查网络恢复
        if not state["online"] and now.second % 30 == 0:
            if check_network():
                state["online"] = True
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
    init_network()

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
        stop_speech()
