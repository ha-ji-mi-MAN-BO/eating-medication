# M10 智能服药提醒终端（单文件版）

> UniHiker 行空板 M10 智能药盒配套程序，与 [eating-medication](https://github.com/diaoyunxi/eating-medication) 网页端协同工作。
> 本仓库内为**单文件实现**（`m10.py`），与 `elderly_assistant/` 多文件版并列，互不依赖。

## 项目简介

`m10.py` 是部署在 DFRobot 行空板 M10 上的老人端主程序，承担用药提醒、语音播报、按钮交互、网络同步、紧急呼叫等核心功能。程序使用 Python 标准库 + UniHiker 原生 API（`unihiker` / `pinpong`）+ `pyttsx3` 离线 TTS，**不依赖** `cv2`、`requests`、`schedule` 等第三方库，便于在嵌入式设备上直接运行。

## 核心功能

| 模块 | 功能说明 |
|------|----------|
| WiFi 自动连接 | 模块加载时通过 `unihiker_connet_wifi.WiFiManager` 自动连接，`init_network()` 检查连接状态后注册设备、同步数据 |
| 固定时间提醒 | 每日 **09:00 / 13:00 / 17:00** 自动触发服药提醒，跨天自动重置触发记录避免漏触发 |
| 服务端提醒同步 | 每小时从服务端拉取用药计划，按星期+时间匹配触发提醒 |
| 按钮触发提醒 | 按下 **P27（B键）** 随时手动启动一次服药提醒 |
| 已吃药确认 | 按下 **P21（~A键）** 确认服药，停止提醒并返回主页，自动拍照上传、扣减库存 |
| 紧急呼叫 | 按下 **P28（A键）** 记录紧急呼叫日志（当前版本仅本地记录，联网呼叫待后续接入） |
| 主界面时钟 | 主页显示**年月日 + 时分秒**（系统时间），后台线程每秒刷新 |
| 语音播报 | `pyttsx3` 队列播报 + `espeak` 回退，配合 `amixer` 自动检测并控制 USB 扬声器音量 |
| 提醒音量递增 | 触发后每 10 分钟音量递增一档（30 → 100），避免老人忽略 |
| 蜂鸣器提示 | 优先使用 `pinpong` 板载蜂鸣器音效（BA_DING），回退到数字引脚控制 |
| 离线日志队列 | 网络断开时服药日志写入本地队列（`/root/medication_log_queue.json`），恢复后自动回传服务端 |
| 余量监测 | 每 6 小时计算药品剩余天数，低于阈值语音告警并查询补货信息 |
| AI 药品识别 | 通过 `fswebcam` 拍照 + `pytesseract` OCR 识别药品名，并查询服务端药品库 |
| 网络自恢复 | 离线时每 30 秒探测网络恢复，恢复后自动注册设备、同步提醒、刷新日志 |

## 硬件接线

| 引脚 | 设备 | 电平逻辑 |
|------|------|----------|
| `Pin.P25` | 蜂鸣器 | 优先使用板载音效，回退数字引脚高低电平 |
| `Pin.P21` | 已吃药按钮（~A键） | 按下高电平（1），松开低电平（0） |
| `Pin.P27` | 启动提醒按钮（B键） | 按下低电平（0） |
| `Pin.P28` | 紧急呼叫按钮（A键） | 按下低电平（0），仅记录日志 |

### 外接模块

| 模块 | 接口 | 说明 |
|------|------|------|
| HuskylensV2（二哈识图2） | I2C | 预留人脸识别扩展接口，通过 `dfrobot_huskylensv2` 驱动 |
| USB 摄像头 | USB | 用于 `fswebcam` 拍照（服药确认、药品 OCR） |
| USB 扬声器 | USB | TTS 语音播报输出 |

> 显示屏由 `unihiker.GUI` 自动接管，无需手动接线。HuskylensV2 通过板载 I2C 接口连接，无需额外引脚。

## 依赖说明

### Python 库

仅依赖 Python 标准库 + UniHiker 平台库，`pyttsx3` 可选（缺失时自动回退到 `espeak`）：

```python
import time, json, threading, queue
from unihiker import GUI              # 屏幕 GUI
from pinpong.board import Board, Pin  # 硬件抽象层
from dfrobot_huskylensv2 import *     # 二哈识图2 驱动（预留）
from unihiker_connet_wifi import *    # WiFi 连接管理
```

### 系统级依赖

| 依赖 | 用途 | 缺失时行为 |
|------|------|-----------|
| `fswebcam` | USB 摄像头拍照 | 跳过拍照功能 |
| `tesseract` + `pytesseract` | 药品包装 OCR 识别 | 跳过识别功能 |
| `espeak` | TTS 回退引擎 | 语音播报失败 |
| `amixer` / `aplay` | USB 扬声器音量控制 | 音量调节失效 |
| `WiFiManager` (unihiker_connet_wifi) | WiFi 自动连接 | 模块加载时 WiFi 连接失败 |

## 配置项

### WiFi 配置

WiFi 连接在**模块加载时自动执行**（`m10.py` 第 32-34 行）：

```python
from unihiker_connet_wifi import *
wifi_manager = WiFiManager()
response_success = wifi_manager.connect_wifi("666", "15756491077")
```

修改 WiFi 需直接编辑这行代码中的 SSID 和密码。`init_network()` 通过 `wifi_manager.is_wifi_connected()` 查询连接状态，**不再**从配置文件读取 WiFi 凭据。

### 业务配置常量

其余主要常量集中在 `m10.py` 顶部的「配置区」，按实际环境修改：

```python
# 服务端地址（API）与家属端地址（参考）
SERVER_BASE_URL = "https://my-website.ccwu.cc/eating-medication/server"
FAMILY_BASE_URL = "https://my-website.ccwu.cc/eating-medication/family"
PAIR_CODE = "275527387791320"
DEVICE_ID = "m10_" + PAIR_CODE

# 新版 API 端点（v2.28.0）
API_REGISTER = f"{SERVER_BASE_URL}/api/v1/public/device/register"
API_SCHEDULE = f"{SERVER_BASE_URL}/api/v1/public/device/schedule/{DEVICE_ID}"
API_MESSAGE = f"{SERVER_BASE_URL}/api/v1/public/device/message"
API_UPLOAD = f"{SERVER_BASE_URL}/api/v1/public/device/upload"
API_OFFLINE = f"{SERVER_BASE_URL}/api/v1/public/device/offline"
API_AI_ASK = f"{SERVER_BASE_URL}/api/v1/public/ai/ask"

# 固定服药提醒时间
FIXED_REMINDER_TIMES = ["09:00", "13:00", "17:00"]

# 提醒音量递增参数
VOLUME_INITIAL = 30   # 初始音量
VOLUME_STEP = 15      # 每档增量
VOLUME_MAX = 100      # 最大音量
SNOOZE_MINUTES = 10   # 贪睡间隔（分钟）

# TTS 语速（pyttsx3 rate 属性）
TTS_RATE = 200

# 主界面时钟刷新间隔（秒）
CLOCK_REFRESH_INTERVAL = 1
```

### device_token 持久化

设备首次注册成功后，`device_token` 会自动写入 `/root/medication_config.json`。后续启动时 `init_network()` 会优先从配置文件恢复 token，无需重复注册。若 token 失效，删除配置文件中的 `device_token` 字段即可强制重新注册。

### 运行时文件

| 路径 | 用途 |
|------|------|
| `/root/medication_config.json` | 药品库存、`device_token` 等运行时配置 |
| `/root/medication_local.log` | 本地运行日志 |
| `/root/medication_log_queue.json` | 离线日志队列（网络恢复后自动回传） |
| `/root/medication_photos/` | 服药确认照片与 OCR 照片 |

## 运行方式

将 `m10.py` 拷贝到行空板 M10 后直接运行：

```bash
# 前台运行（推荐调试时使用，可看到实时日志）
python3 m10.py

# 后台运行（生产部署）
nohup python3 m10.py > /root/m10_stdout.log 2>&1 &
```

> 程序启动会自动设置 `DISPLAY=:0`，支持 SSH 远程运行。可通过 `tail -f /root/medication_local.log` 查看运行日志。

## 程序结构

```
m10.py
├── 模块级初始化          # WiFiManager 自动连接 + WiFi 凭据硬编码
├── 配置区              # SERVER_BASE_URL / FAMILY_BASE_URL / 配对码 / 新版 API 端点 / 引脚 / 音量 / 提醒时间
├── 全局状态            # state 字典（在线/device_token/提醒/库存/活跃提醒等）
├── 工具函数            # 日志 / 配置读写 / 网络探测 / 音量控制
├── TTS 语音播报        # pyttsx3 队列 + espeak 回退 + 音量联动
├── 网络通信（新版 API）
│   ├── _auth_headers()       # 自动注入 X-Device-Token
│   ├── http_request()        # urllib 封装
│   ├── register_device()     # POST /device/register → 保存 device_token
│   ├── load_device_token()   # 从配置恢复 token
│   ├── sync_reminders()      # GET /device/schedule/{id} → 转换为内部格式
│   ├── upload_log()          # POST /device/message + /device/upload
│   ├── notify_emergency()    # POST /device/message（message_type=emergency）
│   ├── device_offline()      # POST /device/offline
│   └── query_drug_by_ocr()   # POST /ai/ask（AI 问答）
├── 提醒核心            # 固定提醒 / 服务端提醒 / trigger_alert / alert_loop / 服药确认
├── AI 药品识别         # fswebcam 拍照 + pytesseract OCR + AI 问答
├── 余量监测            # 剩余天数计算 + 低库存告警
├── GUI 更新            # 主页时钟 / 状态提示 / 提醒界面（三种模式）
├── 按钮处理            # P21 确认 / P27 提醒 / P28 紧急（联网呼叫）
└── 初始化与主循环      # 硬件初始化 / 网络初始化（含 token 恢复） / 线程启动 / 主循环 / 退出时下线通知
```

## 工作流程

### 启动流程

1. **模块加载** → `WiFiManager.connect_wifi()` 自动连接 WiFi
2. **初始化硬件** → `Board().begin()` + 蜂鸣器 + 按钮 + GUI
3. **初始化 TTS** → `pyttsx3` 引擎 + 后台播报线程
4. **初始化网络** → `wifi_manager.is_wifi_connected()` 检查 → 尝试从本地恢复 `device_token` → 无 token 则注册设备 → 同步提醒 → 刷新离线日志
5. **启动线程** → 按钮轮询线程 + 时钟刷新线程
6. **进入主循环**

### 主循环（每秒一次）

| 触发条件 | 执行内容 |
|----------|---------|
| 每分钟 | `check_reminders()` + `check_fixed_reminders()` |
| 每小时 | `sync_reminders()`（仅在线时） |
| 每 6 小时 | `calculate_remaining_days()` |
| 每 30 分钟 | `flush_local_logs()`（仅在线时） |
| 离线每 30 秒 | 探测网络恢复 → 恢复后自动注册/同步/刷新 |

### 按钮线程（每 0.1 秒轮询）

| 按钮 | 引脚 | 触发条件 | 行为 |
|------|------|---------|------|
| 已吃药（~A） | P21 | 按下高电平（1） | 确认服药 → 拍照上传（`/device/upload`）→ 发送消息（`/device/message`）→ 扣减库存 → 返回主页 |
| 启动提醒（B） | P27 | 按下低电平（0） | 立即启动一次服药提醒（测试药品 1片） |
| 紧急呼叫（A） | P28 | 按下低电平（0） | 通过 `/device/message`（message_type=emergency）通知家属 → 语音播报结果 |

### 时钟线程（每秒一次）

仅在 `_gui_mode == "home"` 时刷新主页日期与时分秒文本对象，避免与提醒/状态界面冲突。

## API 接口规范

`m10.py` 通过 HTTP 与 [eating-medication](https://github.com/diaoyunxi/eating-medication) 服务端通信。API 规范详见 [`openapi.json`](file:///e:/m10/eating-medication/openapi.json)（OpenAPI 3.1.0）。

### 基础信息

| 项目 | 值 |
|------|-----|
| 服务端基础路径 | `/eating-medication/server` |
| API 版本 | v2.28.0 |
| 认证方式 | 设备注册后返回 `device_token`，后续请求通过 `X-Device-Token` Header 校验 |
| 限流 | 设备端基于 IP 限流；部分接口需 `device_token` |

### 设备端公开接口

以下接口位于 `openapi.json` 的 `设备公开接口` tag，供 M10 老人端调用：

| 接口路径 | 方法 | 用途 | 认证 |
|----------|------|------|------|
| `/api/v1/public/device/register` | POST | 设备注册/心跳上报 | 无需 |
| `/api/v1/public/device/offline` | POST | 设备主动下线通知 | `X-Device-Token` |
| `/api/v1/public/device/message` | POST | 上报设备消息（服药/紧急/识别等事件） | `X-Device-Token` |
| `/api/v1/public/device/upload` | POST | 上传服药照片（base64 编码） | `X-Device-Token` |
| `/api/v1/public/device/schedule/{device_id}` | GET | 获取用药计划（每分钟轮询） | `X-Device-Token` |
| `/api/v1/public/device/plans/{device_id}` | GET | 获取所有用药计划 | `X-Device-Token` |
| `/api/v1/public/device/records/{device_id}` | GET | 获取服药历史记录 | `X-Device-Token` |
| `/api/v1/public/device/check/{device_id}` | GET | 检查设备是否已注册 | 无需 |
| `/api/v1/public/device/status/{device_id}` | GET | 获取设备在线状态 | `X-Device-Token` |
| `/api/v1/public/ai/ask` | POST | AI 健康问答（设备端，IP 限流 10次/分钟） | 可选 `X-Device-Token` |

### 关键接口请求/响应格式

#### 1. 设备注册 — `POST /api/v1/public/device/register`

**请求体** (`DeviceRegister`)：
```json
{
  "device_id": "m10_275527387791320",
  "device_name": null
}
```

**响应**：
```json
{
  "status": "ok",
  "user_id": 123,
  "device_token": "dh_xxxxx"   // 首次注册返回，后续请求需携带
}
```

> 查找逻辑：优先按 `User.device_id` 查找（家属已绑定）→ 回退按 `User.username == device_id` 查找 → 都找不到则创建虚拟用户。

#### 2. 设备消息上报 — `POST /api/v1/public/device/message`

**请求体** (`DeviceMessage`)：
```json
{
  "device_id": "m10_275527387791320",
  "message_type": "info",
  "content": "服药确认",
  "data": {
    "action": "confirm_take",
    "medicine": "测试药品",
    "user": "老人"
  }
}
```

**Header**：`X-Device-Token: dh_xxxxx`

#### 3. 服药照片上传 — `POST /api/v1/public/device/upload`

**请求体** (`DeviceUpload`)：
```json
{
  "device_id": "m10_275527387791320",
  "image_base64": "/9j/4AAQSkZJRg...",
  "note": "服药确认照片"
}
```

#### 4. 用药计划查询 — `GET /api/v1/public/device/schedule/{device_id}`

**路径参数**：`device_id` — 设备唯一标识

**Header**：`X-Device-Token: dh_xxxxx`

**响应**：用药计划列表（`FamilyMedicationPlan` 数组），包含：
- `drug_name` / `dosage` / `frequency` / `schedule_times`
- `total_quantity` / `remaining_quantity` / `unit`
- `low_stock_threshold`

#### 5. AI 问答 — `POST /api/v1/public/ai/ask`

**请求体**：
```json
{
  "question": "老人吃什么药比较好？",
  "context": []
}
```

**响应**：
```json
{
  "answer": "根据老人的情况，建议..."
}
```

### 已完成的 API 迁移

`m10.py` 已完成向 `openapi.json` v2.28.0 新版 API 的迁移：

| 旧版路径 | 新版路径 | 状态 |
|---------|---------|------|
| `POST /api/device/register` | `POST /api/v1/public/device/register` | ✅ 已迁移 |
| `GET /api/reminders` | `GET /api/v1/public/device/schedule/{device_id}` | ✅ 已迁移 |
| `POST /api/logs` | `POST /api/v1/public/device/message` + `POST /api/v1/public/device/upload` | ✅ 已迁移 |
| `POST /api/emergency/notify` | `POST /api/v1/public/device/message`（message_type=emergency） | ✅ 已迁移 |
| `POST /api/drug/query` | `POST /api/v1/public/ai/ask`（AI 问答替代） | ✅ 已迁移 |
| `POST /api/refill/query` | `POST /api/v1/public/ai/ask`（AI 问答替代） | ✅ 已迁移 |
| — | `POST /api/v1/public/device/offline` | ✅ 新增（下线通知） |

**认证机制变更**：旧版使用 `pair_code` 参数传递身份，新版改为 `X-Device-Token` Header。设备首次注册成功后返回 `device_token`，自动持久化到配置文件，后续启动可直接恢复无需重新注册。

**数据格式变更**：
- 旧版 `sync_reminders()` 接收 `{code, data: {reminders, medicines}}`
- 新版 `sync_reminders()` 接收 `FamilyMedicationPlan[]`，通过 `_convert_plans_to_reminders()` / `_convert_plans_to_medicines()` 自动转换为兼容的内部格式

### 已完成的 Bug 修复（v2.28.4，共 40 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `recognize_medicine()` 用旧格式 `resp.get("code") == 0` 检查 AI 问答响应 | 改为检查 `resp.get("answer")` |
| 2 | 🔴 | `low_stock_alert()` 用旧格式 `resp.get("data")` 读取 AI 问答结果 | 改为检查 `resp.get("answer")` |
| 3 | 🔴 | 多线程读写 `state["triggered_fixed_times"]` / `state["active_alerts"]` 未加锁 | 全部加 `with lock:` 保护；`threading.Lock` → `threading.RLock` 支持嵌套获取 |
| 4 | 🟡 | `update_stock()` 使用不存在的 `daily_count` 字段 | 改为 `frequency_per_day` |
| 5 | 🟡 | `upload_log()` 中 dict 类型 detail 产生 Python repr 作为 content | 改用 `json.dumps(detail)` |
| 6 | 🟡 | 网络恢复检查仅在 `second % 30 == 0` 时触发，窗口极窄 | 改用 `time.time()` 间隔计时器（30 秒） |
| 7 | 🟡 | 网络恢复时直接 `register_device()` 不检查已有 token | 加入 `load_device_token()` 优先恢复逻辑 |
| 8 | 🟡 | `finally` 中 `device_offline()` 无异常保护，可能阻断 `stop_speech()` | 包裹 try/except |
| 9 | 🟡 | `confirm_take()` 读取 `state["active_alerts"]` 未加锁 | 加 `with lock:` 保护 |
| 10 | 🟡 | `check_network()` 硬编码旧域名 | 改用 `SERVER_BASE_URL` 常量 |
| 11 | 🔴 | 紧急按钮 `notify_emergency()` 阻塞 `button_thread` 最长 30 秒 | 改为 `threading.Thread` 异步执行 |
| 12 | 🔴 | `update_stock()` 中 `load_config()`/`save_config()` 文件 I/O 在 `with lock:` 内 | 将 I/O 移到锁外，锁内仅修改内存状态 |
| 13 | 🔴 | `low_stock_alert()` 接收 `state["medicines"]` 中 dict 的可变引用，其他线程修改会导致数据竞争 | 传递 `dict(m)` 副本；同样修复 `calculate_remaining_days()` |
| 14 | 🔴 | `confirm_take()` 中 `upload_log()` 阻塞 `button_thread` 最长 30 秒 | 改为 `threading.Thread` 异步执行 |
| 15 | 🟡 | `recognize_medicine()` 每次调用都 `import pytesseract`/`PIL` | 新增 `_get_ocr_engine()` 延迟加载并缓存 |
| 16 | 🟡 | `_auth_headers()` 读取 `state["device_token"]` 无锁保护 | 加 `with lock:` 保护 |
| 17 | 🟡 | `_speak_worker()` 读取 `state["current_volume"]` 无锁保护 | 加 `with lock:` 保护 |
| 18 | 🟡 | `flush_local_logs()` 中 `entry.pop("_photo")` 导致消息成功但照片失败时照片数据丢失 | 改用 `entry.get("_photo")` + 字典推导式分离，失败时完整保留 entry |
| 19 | 🟡 | `alert_loop()` 读取 `state["active_alerts"][tid]` 无锁保护 | 加 `with lock:` 保护循环内所有读写 |
| 20 | 🟡 | GUI 模式变量（`_gui_mode`/`_clock_*_obj`）在多线程中无锁读写 | 新增 `_gui_lock` 保护所有 GUI 状态变量 |
| 21 | 🟢 | `FAMILY_BASE_URL` 常量已无引用（API 迁移后） | 删除死代码 |
| 22 | 🟢 | `from dfrobot_huskylensv2 import *` 无实际使用 | 删除死导入 |
| 23 | 🟢 | 紧急按钮注释过时（"仅记录日志"） | 更新为"联网通知家属" |
| 24 | 🔴 | `state["online"]` 在 10+ 处无锁读写（`low_stock_alert`/`recognize_medicine`/GUI/`main_loop`/`init_network`） | 新增 `_get_online()`/`_set_online()` 辅助函数，统一加锁保护 |
| 25 | 🔴 | `state["camera_available"]` 无锁读写（`init_hardware` 写，`confirm_take`/`recognize_medicine` 读） | 新增 `_get_camera_available()`/`_set_camera_available()` 辅助函数 |
| 26 | 🔴 | 配置文件竞态：`update_stock()` 与 `main_loop` 可能同时写 `medication_config.json` | 新增 `_config_lock` 保护 `load_config()`/`save_config()` |
| 27 | 🔴 | `update_stock()` 锁外读取 `state["medicines"]` 用于持久化，其他线程可能已修改 | 在锁内采集 `medicines_snapshot = list(state["medicines"])` |
| 28 | 🔴 | `init_network()` 同步阻塞主线程最长 30+ 秒（网络检查 + 注册 + 同步） | 改为 `threading.Thread` 异步执行 |
| 29 | 🔴 | `confirm_take()` 中 `capture_photo()` 阻塞 `button_thread` 最长 10 秒 | 将拍照 + 上传全部移到 `_do_confirm_upload` 后台线程，超时降为 5 秒 |
| 30 | 🟡 | `_convert_plans_to_medicines()` `frequency_per_day` 恒为 1，库存阈值计算不准确 | 新增 `_parse_frequency_per_day()` 从 `frequency` 字段解析（如"每日3次"→3） |
| 31 | 🟡 | `_convert_plans_to_medicines()` `remaining` 字段丢失（默认 0） | 改用 `int(remaining_quantity)` |
| 32 | 🟡 | `notify_emergency()` 紧急联系人硬编码 "120" | 从配置文件 `emergency_contact` 读取，默认 "120" |
| 33 | 🟢 | `import re` 在 `_parse_frequency_per_day()` 内动态导入 | 移至文件顶部导入 |
| 34 | 🔴 | `state["device_token"]` 在 `register_device()`/`load_device_token()` 写入无锁保护 | 新增 `_get_device_token()`/`_set_device_token()` 辅助函数 |
| 35 | 🔴 | 离线日志队列文件 `QUEUE_FILE` 无锁读写，多线程并发可能导致 JSON 损坏 | 新增 `_queue_lock`；`flush_local_logs()` 读取在锁内、网络请求在锁外、写回在锁内 |
| 36 | 🔴 | `log()` 文件写入与轮转无锁保护，多线程并发可能丢失日志或破坏文件 | 新增 `_log_lock` 保护；>10MB 自动轮转（保留 `.old`） |
| 37 | 🟡 | `import pyttsx3` 在 `init_speech()` 和 `_speak_worker` 异常分支内动态导入 | 移至文件顶部 try/except 预导入，设 `_PYTTSX3_AVAILABLE` 标志 |
| 38 | 🟡 | `trigger_alert()` 将 `reminder` 字典引用直接存入 `active_alerts`，后续 `sync_reminders` 替换列表后可能导致数据不一致 | 改用 `dict(reminder)` 创建副本 |
| 39 | 🟡 | `sync_reminders()` 对 API 错误响应缺乏校验，可能静默清空提醒 | 增加 `resp is None` 检查、`status != "ok"` 错误检测、`items` 字段兼容 |
| 40 | 🟢 | 锁体系统一 | 锁数量从 3 把增至 6 把：`lock`(RLock)、`_gui_lock`、`_config_lock`、`_queue_lock`、`_log_lock`，每把锁职责单一 |

## 版本与更新

本仓库 [`ha-ji-mi-MAN-BO/eating-medication`](https://github.com/ha-ji-mi-MAN-BO/eating-medication) 维护 `m10.py` 单文件版及其文档。配套网页端位于 [`diaoyunxi/eating-medication`](https://github.com/diaoyunxi/eating-medication)，建议二者同步更新以确保接口协议一致。

## 许可

本项目仅供学习和个人使用，最终解释权归 GitHub 账户 ha-ji-mi-MAN-BO 所有。