# M10 智能服药提醒终端（单文件版）

> UniHiker 行空板 M10 智能药盒配套程序，与 [eating-medication](https://github.com/diaoyunxi/eating-medication) 网页端协同工作。
> 本仓库内为**单文件实现**（`m10.py`），与 `elderly_assistant/` 多文件版并列，互不依赖。

## 项目简介

`m10.py` 是部署在 DFRobot 行空板 M10 上的老人端主程序，承担用药提醒、语音播报、按钮交互、网络同步、紧急呼叫等核心功能。程序使用 Python 标准库 + UniHiker 原生 API（`unihiker` / `pinpong`）+ `pyttsx3` 离线 TTS，**不依赖** `cv2`、`requests`、`schedule` 等第三方库，便于在嵌入式设备上直接运行。

## 使用前注意事项

|搜索药品|人脸识别|
|-------|----------|
|通电二哈识图|通电二哈识图|
|打开条形码识别|打开人脸识别|
|点击遗忘id|点击遗忘id|
|对准使用的老人|对准所有可能使用的药品条形码|
|按下物理按钮|按下物理按钮|
|在工具栏找到设置名字|在工具栏找到设置名字|
|为老人命名|为药品命名|
|开始使用|开始使用|

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
| 人脸识别 | HuskyLens 二哈识图识别人脸ID，触发提醒时切换到人脸识别模式，检测目标老人（id1）确认身份 |
| 搜索药品 | 主页和提醒界面底部"搜索药品"按钮，切换二哈到条形码识别模式，实时显示识别到的药品名 |

## 硬件接线

| 引脚 | 设备 | 电平逻辑 |
|------|------|----------|
| `Pin.P25` | 蜂鸣器 | 优先使用板载音效，回退数字引脚高低电平 |
| `Pin.P21` | 已吃药按钮（~A键） | 按下高电平（1），松开低电平（0） |
| `Pin.P27` | 启动提醒按钮（B键） | 按下低电平（0） |
| `Pin.P28` | 紧急呼叫按钮（A键） | 按下低电平（0），联网通知家属 |

### 外接模块

| 模块 | 接口 | 说明 |
|------|------|------|
| HuskylensV2（二哈识图2） | I2C | 人脸识别（提醒时切换）+ 条形码识别（搜索药品时切换），通过 `dfrobot_huskylensv2` 驱动 |
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

WiFi 连接在**初始化时执行**，SSID 和密码通过环境变量配置（`m10.py` 第 143-144 行）：

```python
_WIFI_SSID = os.environ.get("WIFI_SSID", "")
_WIFI_PASSWORD = os.environ.get("WIFI_PASSWORD", "")
```

> **安全提示**：默认值为空字符串，生产环境**必须**通过环境变量配置真实凭据，禁止在代码中硬编码密码。

**生产环境配置**：

```bash
# 设置环境变量后运行
export WIFI_SSID="your_ssid"
export WIFI_PASSWORD="your_password"
python3 m10.py
```

`init_network()` 通过 `wifi_manager.is_wifi_connected()` 查询连接状态。若 SSID 或密码为空，将自动进入离线模式。

### 业务配置常量

其余主要常量集中在 `m10.py` 顶部的「配置区」，按实际环境修改：

```python
# 服务端地址（API）与家属端地址（参考）
SERVER_BASE_URL = "https://my-website.ccwu.cc/eating-medication/server"
FAMILY_BASE_URL = "https://my-website.ccwu.cc/eating-medication/family"
PAIR_CODE = "2AIDMUNIHIKER13"
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

# 常量定义（v2.29.2 新增）
MAX_ALERT_RETRIES = 20           # 提醒最大重试次数（约 3 小时）
MAX_QUEUE_SIZE = 500             # 离线日志队列最大条数
MAX_PHOTO_SIZE = 512000          # 照片上传最大大小（500KB）
MAX_IMAGE_SIZE = 1048576         # 图片 base64 编码最大大小（1MB）
NETWORK_RECONNECT_INTERVAL = 30  # 网络恢复检查间隔（秒）
MAX_RECONNECT_FAILS = 5          # 网络恢复最大失败次数
STOCK_CHECK_INTERVAL = 6 * 3600  # 库存检查间隔（6 小时）
LOG_FLUSH_INTERVAL = 30 * 60     # 日志刷新间隔（30 分钟）
ALERT_TIMEOUT = 30               # 低库存告警超时（秒）
MISSED_MINUTES_THRESHOLD = 60    # 错过分钟数阈值
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
├── HuskyLens 二哈识图  # 人脸识别（提醒时切换）+ 条形码识别（搜索药品时切换）+ 模式切换函数
├── 搜索药品功能        # enter/exit_search_medicine + 条形码检测线程 + 搜索药品界面
├── GUI 更新            # 主页时钟 / 状态提示 / 提醒界面 / 搜索药品界面
├── 按钮处理            # P21 确认 / P27 提醒 / P28 紧急（联网呼叫）/ 触摸屏搜索药品按钮
└── 初始化与主循环      # 硬件初始化（含 HuskyLens knock 握手）/ 网络初始化（含 token 恢复） / 线程启动 / 主循环 / 退出时下线通知
```

## 工作流程

### 启动流程

1. **模块加载** → `WiFiManager.connect_wifi()` 自动连接 WiFi
2. **初始化硬件** → `Board().begin()` + 蜂鸣器 + 按钮 + GUI + HuskyLens 初始化（仅 `knock` 握手，**不切换识别模式**）
3. **初始化 TTS** → `pyttsx3` 引擎 + 后台播报线程
4. **初始化网络** → `wifi_manager.is_wifi_connected()` 检查 → 尝试从本地恢复 `device_token` → 无 token 则注册设备 → 同步提醒 → 刷新离线日志
5. **启动线程** → 按钮轮询线程 + 时钟刷新线程 + 人脸ID检测线程
6. **进入主循环**（提醒触发时才切换 HuskyLens 到人脸识别模式）

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
| API 版本 | v2.28.0（当前修复版：v2.48.0） |
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
  "device_id": "m10_2AIDMUNIHIKER13",
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
  "device_id": "m10_2AIDMUNIHIKER13",
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
  "device_id": "m10_2AIDMUNIHIKER13",
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
  "device_id": "m10_2AIDMUNIHIKER13"
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

### 已完成的 Bug 修复（v2.28.6，共 58 项）

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
| 41 | 🔴 | GUI 绘制操作（`gui.clear()`/`gui.draw_text()`）无线程锁保护，多线程同时绘制可能导致画面撕裂或崩溃 | 新增 `_gui_draw_lock`；所有绘制函数（`update_gui_status`/`update_gui_home`/`update_gui_reminder`/`clock_thread`）统一在锁内操作 |
| 42 | 🔴 | 摄像头 `capture_photo()` 无线程锁，多线程并发拍照可能导致设备冲突或文件覆盖 | 新增 `_camera_lock` 串行化所有摄像头访问 |
| 43 | 🔴 | `_speak_queue` 无大小限制，TTS 引擎堵塞时队列无限增长 | 改为 `Queue(maxsize=100)`；`tts_speak` 满时丢弃最旧消息保证时效性 |
| 44 | 🟡 | `clock_thread` 读取的 `_clock_time_obj`/`_clock_date_obj` 可能在 `update_gui_home` 清空后变为无效引用 | 在 `_gui_draw_lock` 保护下操作，与 `update_gui_home` 互斥 |
| 45 | 🟡 | `_convert_plans_to_reminders` 硬编码 `days=[1..7]`，忽略 API 可能传入的特定工作日（如仅周一/三/五） | 增加 `days`/`weekdays`/`day_of_week` 字段解析，兼容多种格式 |
| 46 | 🟡 | `_get_ocr_engine()` 无锁保护，多线程首次调用时可能重复初始化 OCR 引擎 | 新增 `_ocr_lock` + 双重检查锁定模式（DCLP） |
| 47 | 🟢 | 锁体系再次完善 | 锁数量增至 **9 把**：`lock`/`_gui_lock`/`_gui_draw_lock`/`_config_lock`/`_queue_lock`/`_log_lock`/`_camera_lock`/`_speech_lock`/`_ocr_lock` |
| 48 | 🔴 | `save_config()` 直接写文件，断电/崩溃可能导致 JSON 损坏（部分写入） | 改为原子写入：先写 `.tmp` 临时文件，再 `os.replace()` 重命名 |
| 49 | 🔴 | `queue_local_log()` 直接写文件，非原子操作；队列无大小限制可无限增长 | 原子写入 + 队列上限 500 条（超出裁剪最旧） |
| 50 | 🔴 | `alert_loop()` 无限响铃无终止，若用户永远不确认，设备永久响铃 | 增加最大重试 20 次（约 3 小时），超时自动停止并返回主页 |
| 51 | 🟡 | `sync_reminders()` 使用 `or` 链式获取字段，空列表 `[]` 被误判为 falsy 跳过 | 改用 `is not None` 逐 key 检查，正确处理空列表响应 |
| 52 | 🟡 | `update_stock()` 使用 `list(state["medicines"])` 浅拷贝，锁释放后 dict 引用可被其他线程修改 | 改为 `[dict(m) for m in state["medicines"]]` 深拷贝 |
| 53 | 🟡 | `detect_volume_control()` 使用 `text=True` 参数，Python 3.6 不兼容 | 改为 `universal_newlines=True`（兼容 Python 3.0+） |
| 54 | 🟡 | `low_stock_alert()` 显示告警后无超时返回，设备永久停留在告警屏 | 增加 `threading.Timer(30, update_gui_home)` 自动返回 |
| 55 | 🟡 | `upload_log()` 无照片大小限制，大图 base64 编码后内存翻倍 | 增加 500KB 上限检查 |
| 56 | 🟡 | `image_to_base64()` 无大小限制，超大图 base64 可能 OOM | 增加 1MB 上限检查 |
| 57 | 🟢 | `buzzer_beep()` 增加 None 设备防护 | 硬件未初始化时直接返回，避免 try/except 开销 |
| 58 | 🟢 | `main_loop()` 增加 `missed_minutes` 追踪 | 系统挂起超过 60 分钟时强制触发检查，避免遗漏提醒 |

### 已完成的 Bug 修复（v2.29.0，共 31 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `log()` 函数中日志 I/O 在锁内执行，大日志文件处理时可能阻塞其他线程 | 将 `os.rename` 和 `open` 操作移到 `_log_lock` 外部执行 |
| 2 | 🔴 | `http_request()` 没有检查 HTTP 状态码和处理非 JSON 响应 | 增加 `HTTPError` 异常处理、非 JSON 响应回退、业务状态码检查 |
| 3 | 🔴 | `check_reminders()` 中 `times` 字段可能为 None，导致循环崩溃 | 增加 `None` 检查，默认空列表 |
| 4 | 🔴 | `trigger_alert()` 缺少 `reminder` 参数的 None 检查 | 增加参数类型和有效性检查 |
| 5 | 🔴 | `calculate_remaining_days()` 可能除零错误 | 将 `if daily > 0` 改为 `if daily <= 0`，避免浮点精度问题 |
| 6 | 🟡 | `capture_photo()` 目录不存在时未检查 | 添加 `os.makedirs(PHOTO_DIR, exist_ok=True)` 和超时异常处理 |
| 7 | 🟡 | `_convert_plans_to_medicines()` 缺少 `total_quantity` 字段处理 | 新增 `total_quantity` 字段，正确处理浮点数转换 |
| 8 | 🟡 | `image_to_base64()` 对不存在的文件没有返回错误 | 添加文件存在性检查、空文件检查和更详细的错误日志 |
| 9 | 🟡 | `notify_emergency()` 未验证联系人格式 | 添加联系人有效性检查，无效时回退到默认 "120" |
| 10 | 🟡 | `main_loop()` 网络恢复逻辑可能无限循环 | 添加 `reconnect_fail_count` 计数器，超过 5 次自动告警并尝试 WiFi 重连 |
| 11 | 🟡 | `clock_thread()` 中 `gui` 检查不充分 | 改为 `gui is not None` 显式检查 |
| 12 | 🟡 | `upload_log()` 未验证 `event_type` 有效性 | 添加 `event_type` 类型和有效性检查 |
| 13 | 🟡 | `queue_local_log()` 未验证 `payload` 有效性 | 添加 payload 类型检查和损坏文件自动恢复 |
| 14 | 🟡 | `sync_reminders()` 缺乏异常处理和数据验证 | 添加 try/except、响应格式验证、无效条目过滤 |
| 15 | 🟡 | `register_device()` 响应验证不充分 | 添加响应类型检查、业务状态码检查、token 有效性检查 |
| 16 | 🟡 | `init_network()` 缺乏详细错误处理 | 添加完整的 try/except、更详细的状态日志 |
| 17 | 🟡 | `recognize_medicine()` 异常处理不完善 | 添加 AI 查询异常处理、区分不同失败原因的语音反馈 |
| 18 | 🟡 | `_get_ocr_engine()` 加载失败后重复尝试 | 新增 `_OCR_LOAD_FAILED` 哨兵值，加载失败后直接返回 None |
| 19 | 🟡 | `_ocr_engine` 标记机制有问题 | 使用 `object()` 创建唯一哨兵值，正确区分未加载和加载失败 |
| 20 | 🟡 | `save_device_token()` 未验证 token 有效性 | 添加 token 非空检查、长度验证、保存时间戳 |
| 21 | 🟡 | `load_device_token()` 错误处理不充分 | 添加配置有效性检查、token 格式验证 |
| 22 | 🟡 | `load_config()` 未处理损坏文件 | 添加 `JSONDecodeError` 捕获、损坏文件自动备份 |
| 23 | 🟡 | `save_config()` 未验证参数类型 | 添加 cfg 参数类型检查、`f.flush()` 强制写入磁盘 |
| 24 | 🟡 | `low_stock_alert()` 异常处理不完善 | 添加参数检查、每步操作独立 try/except、更详细的错误日志 |
| 25 | 🟡 | `flush_local_logs()` 错误处理不充分 | 添加损坏文件恢复、条目有效性验证、成功/失败计数统计 |
| 26 | 🟡 | `init_speech()` 线程启动无重复检查 | 添加线程存活检查，避免重复启动播报线程 |
| 27 | 🟡 | `_speak_worker()` 缺乏音量边界检查 | 添加 `vol = max(0, min(100, vol))` 限制音量范围 |
| 28 | 🟡 | `_speak_worker()` 引擎重新初始化不安全 | 在引擎重新初始化时使用 `_speech_lock` 保护 |
| 29 | 🟢 | `http_request()` 添加详细错误日志 | HTTPError 时打印错误响应体前 200 字符 |
| 30 | 🟢 | `log()` 函数代码结构优化 | 先读取状态再执行 I/O，减少锁持有时间 |
| 31 | 🟢 | `init_network()` 添加更详细的状态日志 | 每步操作都有日志输出，便于问题排查 |

### 已完成的 Bug 修复（v2.29.1，共 8 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | 版本号不一致：m10.py 声明 v2.29.0，但 openapi.json 版本为 v2.28.0 | 统一为 v2.28.0，并在文件头标注 API 版本 |
| 2 | 🔴 | `sync_reminders()` 存在重复错误检查逻辑 | 删除冗余的 `status != "ok"` 检查，消除重复代码 |
| 3 | 🔴 | `check_reminders()` 在 `with lock:` 块内调用 `trigger_alert()`，存在锁嵌套 | 将 `trigger_alert()` 调用移到锁外执行，避免潜在死锁风险 |
| 4 | 🟡 | `_parse_frequency_per_day()` 频率解析能力不足 | 增强正则匹配，支持"每日N次"、"每N小时"等更多格式 |
| 5 | 🟡 | `upload_log()` 中 `data` 字段处理不符合 API schema | 根据 `DeviceMessage` schema，支持 `data` 为 `null` |
| 6 | 🟡 | 日志中 HTTP 错误响应体过长（200字符），可能泄露敏感信息 | 限制为 100 字符，并处理空响应体情况 |
| 7 | 🟡 | GET 请求携带不必要的 `Content-Type: application/json` 头 | GET 请求自动移除 `Content-Type` 头，符合 HTTP 规范 |
| 8 | 🟢 | 版本号规范更新 | 按照版本号规范递增 PATCH 版本，更新至 v2.29.1 |

### 已完成的 Bug 修复（v2.29.2，共 12 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `low_stock_alert()` 中 `threading.Timer(30, ...)` 使用魔法数字 30 | 新增常量 `ALERT_TIMEOUT = 30`，便于统一配置 |
| 2 | 🔴 | `image_to_base64()` 中 `if size > 1048576` 使用魔法数字 | 新增常量 `MAX_IMAGE_SIZE = 1048576` |
| 3 | 🔴 | `upload_log()` 中 `if photo_size > 512000` 使用魔法数字 | 新增常量 `MAX_PHOTO_SIZE = 512000` |
| 4 | 🔴 | `queue_local_log()` 中 `if len(queue) > 500` 使用魔法数字 | 新增常量 `MAX_QUEUE_SIZE = 500` |
| 5 | 🟡 | `alert_loop()` 中 `max_retries = 20` 使用魔法数字 | 新增常量 `MAX_ALERT_RETRIES = 20` |
| 6 | 🟡 | `main_loop()` 中多处魔法数字（`6 * 3600`、`30 * 60`、`30`、`60`、`5`） | 新增常量：`STOCK_CHECK_INTERVAL`、`LOG_FLUSH_INTERVAL`、`NETWORK_RECONNECT_INTERVAL`、`MISSED_MINUTES_THRESHOLD`、`MAX_RECONNECT_FAILS` |
| 7 | 🟡 | `main_loop()` 中 `MAX_RECONNECT_FAILS` 在函数内重新定义为局部变量 | 移至全局常量区，统一管理 |
| 8 | 🟡 | `alert_loop()` 注释不准确，描述 `time.sleep` 已被替换但仍提及 | 更新注释为"可中断等待机制" |
| 9 | 🟢 | `upload_log()` 函数文档不完善 | 添加完整的 docstring（Args、Returns） |
| 10 | 🟢 | `low_stock_alert()` 函数文档不完善 | 添加完整的 docstring（Args） |
| 11 | 🟢 | `image_to_base64()` 注释不准确 | 更新注释反映使用 `MAX_IMAGE_SIZE` 常量 |
| 12 | 🟢 | `queue_local_log()` 注释不准确 | 更新注释反映使用 `MAX_QUEUE_SIZE` 常量 |

**v2.29.2 追加修复（共 15 项，代码审查增强）**：

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `http_request()` 未捕获 `URLError`（网络不通、DNS 解析失败） | 增加 `urllib.error.URLError` 捕获，返回 None 并记录日志 |
| 2 | 🔴 | `upload_log()` 未检查业务错误标记（`_error`），业务错误时误判成功 | 增加 `_error` 标记检查，`msg_ok` 和 `photo_ok` 判定包含业务错误检测 |
| 3 | 🔴 | `register_device()` token 为空时仍返回 True，导致无效注册状态 | token 为空时返回 False，记录 ERROR 日志 |
| 4 | 🔴 | `log()` 函数文件 I/O（rename、open、write）在锁内执行，可能阻塞其他线程 | 将文件 I/O 操作移到 `_log_lock` 外部执行 |
| 5 | 🟡 | `init_network()` 网络检测失败无重试，临时网络波动直接放弃 | 增加 3 次重试机制，每次间隔 1 秒 |
| 6 | 🟡 | `flush_local_logs()` 并发调用可能导致重复上传 | 增加 `_flush_in_progress` 事件防止并发刷新，添加 finally 确保释放 |
| 7 | 🟡 | `check_network()` 使用默认 User-Agent，部分服务器拒绝 | 添加自定义 User-Agent 请求头 |
| 8 | 🟡 | 图片大小限制检查不一致：`upload_log` 500KB 限制与 `image_to_base64` 1MB 检查脱节 | 在 `upload_log` 中增加 `image_to_base64` 返回 None 的二次检查 |
| 9 | 🟡 | 版本号注释不一致：API 端点注释与文件头版本描述矛盾 | 统一注释为"API 端点（v2.28.0，对应 openapi.json，m10.py 当前版本 v2.29.2）" |
| 10 | 🟢 | `alert_loop()` 使用 `time.sleep(1)` 轮询，响应不够灵敏 | 改用 `threading.Event.wait()` 实现可中断等待 |
| 11 | 🟢 | 提醒重试次数 `max_retries = 20` 硬编码在 `alert_loop()` 中 | 新增 `MAX_ALERT_RETRIES = 20` 全局常量 |
| 12 | 🟢 | `_speak_worker()` 引擎重新初始化失败无详细日志 | 添加具体的异常信息记录，便于问题排查 |
| 13 | 🟢 | OCR 引擎加载失败后无法重置，需重启设备 | 新增 `reset_ocr_engine()` 函数，支持运行时重置 |
| 14 | 🟢 | `_get_ocr_engine()` 缺少文档说明 | 添加详细 docstring，说明返回值和异常情况 |
| 15 | 🟢 | `flush_local_logs()` 的 `_flush_in_progress` 事件可能因异常未释放 | 添加 finally 块确保事件清理 |

### 已完成的 Bug 修复（v2.48.0，共 6 项，涵盖版本一致性、数据持久化、代码复用、并发安全、性能优化、日志健壮性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | 版本号不一致：文件头声明 v2.47.0，但 API 端点注释仍为 v2.45.0，造成版本追踪混乱 | 统一所有版本号为 v2.48.0，在文件头集中维护版本变更记录 |
| 2 | 🟡 | `update_stock()` 库存为 0 时跳过持久化但已修改内存状态，若程序崩溃将导致数据丢失 | 库存为 0 时仍进行持久化，确保内存与配置文件状态一致 |
| 3 | 🟡 | `save_device_token()` 重复实现 `load_config` 逻辑，代码复用性差且增加维护成本 | 将 `_config_lock` 改为 `RLock`，在 `save_device_token()` 中复用 `load_config()` 函数 |
| 4 | 🟡 | `notify_emergency()` 配置加载失败时缺少明确的日志提示，不利于问题排查 | 记录配置加载错误信息，在配置加载失败时添加详细 WARNING 日志 |
| 5 | 🟢 | `log()` 日志轮转在锁内执行文件大小检查，高频日志写入时增加锁竞争 | 将日志大小检查移到锁外执行，锁内仅执行必要的轮转和写入操作 |
| 6 | 🟢 | 版本变更记录分散，开发者难以快速了解版本历史 | 在文件头集中维护版本修复记录，便于追溯和交付 |

### 已完成的 Bug 修复（v2.47.0，共 5 项，涵盖缺失常量、数据完整性、并发安全、输入校验）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `DEFAULT_CONFIG` 常量未定义，`save_device_token()` 在空配置场景下会抛出 `NameError` | 在配置区顶部显式定义 `DEFAULT_CONFIG` 默认配置模板，包含 `medicines`/`device_token`/`emergency_contact`/`wifi_ssid`/`wifi_password` 等字段 |
| 2 | 🔴 | `ALGORITHM_FACE_RECOGNITION` / `ALGORITHM_BARCODE_RECOGNITION` 常量未定义（v2.41.0 改为显式导入后丢失原通配符导入中的常量），人脸识别/条形码识别所有调用点均会抛出 `NameError` | 在 `dfrobot_huskylensv2` 导入 `try/except` 块中显式定义两个算法常量（值 `1` 和 `2`），导入成功和失败场景下均保证常量可用 |
| 3 | 🟡 | `flush_local_logs()` 写回合并逻辑中，`existing_entries` 直接拼接到 `remain` 之后，网络请求期间新增条目与已失败条目重复时会造成同一条目被重复存储，影响刷新效率 | 使用设备ID+内容特征（照片用 `image_base64` 前缀、消息用 `message_type+content`）作为去重键，先过滤 `existing_entries` 中已在 `remain` 的条目，再合并 |
| 4 | 🟡 | `capture_photo()` 文件名安全校验正则 `r'^[\w\u4e00-\u9fff\.\-]+$'` 未启用 `re.UNICODE` 标志，中文字符文件名可能被误判为非法 | 在 `re.match` 调用中添加 `re.UNICODE` 标志，确保 `\w` 正确匹配 Unicode 字母数字 |
| 5 | 🟢 | 修复记录在代码中以注释形式维护，README 需同步以保持文档一致性 | 同步本章节修复记录，便于交付和回溯 |

### 已完成的 Bug 修复（v2.46.0，共 10 项，涵盖致命逻辑缺陷、并发安全、数据完整性、异常容错、内存安全、日志健壮性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `main_loop()` 中先 `clear()` `_device_needs_re_register` 标志位再调用 `register_device()`，若注册失败标志位已清除，设备永远无法触发重新注册 | 将 `clear()` 移到 `register_device()` 成功返回之后；注册失败时保留标志位供后续重试；离线时记录日志并等待网络恢复 |
| 2 | 🔴 | `_ensure_device_registered()` 心跳全部失败时仍返回 `True`，导致设备在服务端已失效的情况下仍被标记为"已注册" | 心跳连续失败超过阈值时返回 `False` 并触发 `_device_needs_re_register` 事件 |
| 3 | 🔴 | `_enter_search_medicine_impl()` `finally` 块依赖 `_searching_set` 标志判断是否清除状态，异常发生在 `set()` 与标志设置之间时，`_searching_medicine` 状态残留导致人脸检测永久暂停 | `finally` 块直接检查 `_searching_medicine.is_set()`，不依赖中间变量；移除对 `_searching_set` 的依赖 |
| 4 | 🔴 | `flush_local_logs()` 写回时覆盖网络请求期间的新队列条目，导致数据丢失 | 写回前先读取当前 `QUEUE_FILE` 内容，合并 `remain` 与新条目后再写回；增加队列大小限制 |
| 5 | 🔴 | `notify_emergency()` 中存在 `_config_lock` → `_emergency_lock` 的锁排序风险，若其他位置存在反向获取将产生死锁 | 将 `load_config()` 完全移到 `_emergency_lock` 锁外，避免跨锁嵌套；锁内仅做 TTL 检查和缓存更新 |
| 6 | 🔴 | `notify_emergency()` 网络请求失败时无重试机制且不入离线队列，紧急通知可能永久丢失 | 失败时重试 1 次（间隔 1 秒），全部失败后写入离线队列确保后续补发 |
| 7 | 🔴 | `queue_local_log()` 将 base64 照片直接存入 JSON 队列文件，存在 OOM 风险 | 对单张照片数据限制 50KB，队列文件总大小限制 50MB，超限截断并标记 `_photo_truncated` |
| 8 | 🟡 | `save_device_token()` 读取-修改-写入非原子操作，`load_config()` → `save_config()` 之间存在竞态条件 | 将读取-修改-写入操作合并到单次 `_config_lock` 临界区内，确保原子性 |
| 9 | 🟡 | `save_device_token()` 空配置时创建仅含 token 的新配置，可能覆盖已有配置 | 空配置时使用 `DEFAULT_CONFIG.copy()` 默认配置模板 |
| 10 | 🟡 | `log()` 函数异常被完全吞噬，日志丢失无任何告警 | 日志写入异常时输出到 `stderr`，便于开发者发现日志系统故障 |

### 已完成的 Bug 修复（v2.45.0，共 4 项，涵盖库存告警准确性、并发健壮性、日志准确性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `update_stock()` 中库存为 0 时提前 `break` 未设置 `found=True`，日志误报"未找到药品"、跳过库存为 0 场景的持久化路径 | 在 `break` 前设置 `found=True`，使库存为 0 与正常扣减走同一 `found` 分支；同时显式设置 `remaining=0` 保证快照数据正确 |
| 2 | 🔴 | `update_stock()` 中 `alert_medicine = dict(m)` 在扣减前取值，传递给 `low_stock_alert` 的 `remaining` 为扣减前旧值（如 6→5 时仍显示 6） | 将 `alert_medicine` 快照移到扣减/阈值判断之后，确保告警使用最新值 |
| 3 | 🟡 | `update_stock()` 循环前已创建完整快照，循环后又重建快照为冗余操作，且循环前快照不会反映修改 | 移除循环前快照，改为循环结束后基于最新状态在锁内重建快照，保证持久化数据与内存一致 |
| 4 | 🟡 | `notify_emergency()` 中双重检查锁定读取 TTL 与写缓存之间存在 TOCTOU，高并发下可能多次触发文件重新加载 | 将 TTL 判断与缓存更新合并到同一锁内执行，消除 TOCTOU 窗口 |

### 已完成的 Bug 修复（v2.44.0，共 5 项，涵盖致命逻辑缺陷、并发安全、数据校验、路由修复）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `init_hardware()` 中 `buzzer`/`button_take` 等模块级变量初始化为 `None`，导致 `Board` 初始化成功后引脚初始化代码永远不会执行（`None` 检查始终通过） | 引入 `board_init_ok` 标志跟踪 `Board` 初始化状态，替代不可靠的 `None` 检查；合并重复的 `Board().begin()` 调用 |
| 2 | 🟡 | `_convert_plans_to_medicines()` 中 `remaining_quantity` 可为负数，异常数据导致药品库存显示为负值 | 使用 `max(0, ...)` 限制 `remaining` 为非负数 |
| 3 | 🟡 | `flush_local_logs()` 中照片类型队列条目（含 `image_base64` 但无 `message_type`）被错误路由到 `API_MESSAGE` 接口，导致上传失败 | 检测照片专用条目并路由到 `API_UPLOAD` 接口 |
| 4 | 🟡 | `notify_emergency()` 中 `load_config()` 在 `_emergency_lock` 锁内执行，嵌套 `_config_lock` 存在死锁风险且 I/O 阻塞其他线程 | 采用双重检查锁定模式（DCLP），将文件 I/O 移到锁外执行 |
| 5 | 🔵 | `init_hardware()` 中存在重复的 `Board().begin()` 调用 | 合并为单一初始化逻辑 |

### 已完成的 Bug 修复（v2.43.0，共 6 项，涵盖竞态条件、异常恢复、安全脱敏、代码健壮性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `_enter_search_medicine_impl()` 中 `_searching_medicine.set()` 和 `_searching_set=True` 之间存在竞态条件，异常时状态残留导致人脸检测永久暂停 | 调整赋值顺序，先标记 `_searching_set` 再 `set` 事件，确保原子性 |
| 2 | 🟡 | `_exit_search_medicine_impl()` 中异常时 `_searching_medicine.clear()` 不会执行，导致人脸检测无法恢复 | 使用 `try-finally` 确保异常时也能清除状态 |
| 3 | 🟡 | 版本号注释不一致（API 端点注释仍为 v2.41.0） | 更新注释为 v2.43.0 |
| 4 | 🟡 | `notify_emergency()` 中日志记录紧急联系人信息（可能包含手机号），存在敏感信息泄露风险 | 日志脱敏，仅记录联系人信息长度 |
| 5 | 🟡 | `init_hardware()` 中 Board 初始化失败后，引脚对象仍会被创建，可能导致后续代码崩溃 | 增加 `None` 检查，Board 未初始化时跳过引脚初始化 |
| 6 | 🟢 | `http_request()` 中 403 错误关键词列表为局部变量，可维护性差 | 提取为模块级常量 `_403_AUTH_KEYWORDS` |

### 已完成的 Bug 修复（v2.42.0，共 6 项，涵盖致命逻辑缺陷、异常恢复、安全检测、代码清理）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `update_stock()` 中库存为 0 时跳过了 `low_stock_alert` 告警触发，用户库存耗尽时得不到告警 | 库存为 0 时仍触发低库存告警，确保用户及时收到通知 |
| 2 | 🟡 | `_enter_search_medicine_impl()` 异常时 `_searching_medicine` 状态可能残留，导致人脸检测永久暂停 | 使用 `finally` 块确保异常时也能清除 `_searching_medicine` 状态 |
| 3 | 🟡 | `http_request()` 中 403 错误检测关键词范围过宽（含 "unauthorized"、"authentication"），可能误触发重新注册流程 | 收窄关键词范围，仅检测 "device_token"、"token missing"、"设备令牌" 等直接相关关键词 |
| 4 | 🟡 | `notify_emergency()` 中紧急联系人验证不够严格，空字符串可能被当作有效联系人 | 增加对 `None` 和空字符串（含纯空白字符）的检查 |
| 5 | 🟢 | 冗余 docstring 和多余注释，影响代码可读性 | 删除冗余 docstring 和 `MAX_ALERT_RETRIES` 多余注释 |
| 6 | 🟢 | 版本号未同步更新 | 更新版本号为 v2.42.0，添加修复记录 |

### 已完成的 Bug 修复（v2.41.0，共 7 项，涵盖并发安全、降级容错、日志脱敏、API解析、依赖管理）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `_alert_interrupt_event` 从未被 `set()`，用户确认服药后提醒循环仍需等待最长10秒才能响应 | 在 `confirm_take()` 两个分支中均添加 `_alert_interrupt_event.set()`，实现即时中断 |
| 2 | 🟡 | `update_stock()` 中库存已为0时仍执行文件持久化 I/O | 增加 `current_remaining <= 0` 判断，跳过不必要的持久化操作 |
| 3 | 🟡 | `init_hardware()` 中 Board 初始化失败后 `raise` 阻断 GUI/HuskyLens 等其他硬件初始化 | 移除 `raise`，改为降级处理，仅跳过引脚初始化 |
| 4 | 🟡 | `http_request()` 中 403/HTTP 错误日志记录完整 URL，可能泄露 `device_id` 等敏感信息 | 日志脱敏，403 和通用 HTTP 错误均不再记录 URL |
| 5 | 🟡 | `_convert_plans_to_reminders()` 不处理字符串格式的 days（如 "1,2,3"） | 新增 `str` 类型解析分支，支持逗号分隔的星期字符串 |
| 6 | 🟡 | `confirm_take()` 未设置搜索药品退出事件，搜索模式下服药确认无法立即停止提醒循环 | 在删除活跃提醒后立即调用 `_alert_interrupt_event.set()` |
| 7 | 🟢 | 通配符导入 `from dfrobot_huskylensv2 import *` 可能导致命名冲突 | 改为显式导入 `HuskylensV2_I2C` |

### 已完成的 Bug 修复（v2.40.0，共 4 项，涵盖致命缩进错误、心跳重试、设备兼容性、API端点）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `main_loop()` 中 `try` 块缩进错误，核心逻辑在 `try` 块外导致异常无法捕获 | 将所有循环逻辑正确缩进到 `try` 块内，确保异常保护覆盖完整 |
| 2 | 🟡 | `_ensure_device_registered()` 心跳失败时直接返回 True，无重试机制，单次网络抖动可能误判设备状态 | 增加 2 次心跳重试（间隔1秒），避免单次网络抖动误判设备状态 |
| 3 | 🟡 | `_build_device_payload()` 中 `device_name` 为 None，部分服务器实现可能需要此字段 | 提供默认设备名称 `"M10-Device-{id}"`，提升服务器兼容性 |
| 4 | 🟢 | API 端点常量注释中的版本号与实际代码版本不一致 | 更新注释中的版本号为 v2.40.0 |

### 已完成的 Bug 修复（v2.39.0，共 5 项，涵盖网络检测、安全日志、数据持久化、异常处理）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `check_network()` 检查 `SERVER_BASE_URL` 根路径而非 API 端点，服务器正常但 API 故障时误判网络正常 | 改用 `/health` 健康检查端点（`openapi.json` 定义），精确检测 API 可用性 |
| 2 | 🟡 | `send_heartbeat()` 中 token 检查仅验证非空，未过滤空白字符串，可能保存无效 token | 增加 `isinstance(token, str)` 和 `token.strip()` 检查，确保 token 有效 |
| 3 | 🟡 | `update_stock()` 未找到药品时仍执行不必要的持久化操作，浪费 I/O 资源 | 仅在找到药品时才持久化，避免无意义的文件读写 |
| 4 | 🟡 | `http_request()` 异常日志记录完整 URL 和异常信息，可能泄露敏感数据（堆栈、路径等） | 日志脱敏，`URLError` 仅记录错误类型，通用异常仅记录异常类名 |
| 5 | 🟡 | `sync_reminders()` 返回错误状态时未检查 `_device_needs_re_register` 标记，无法主动触发重新注册 | 增加对 `_device_needs_re_register` 事件的检查，主动触发重新注册流程 |

### 已完成的 Bug 修复（v2.38.5，共 17 项，涵盖异常处理、线程安全、代码健壮性、性能优化、安全性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `_control_exists()` 中 `subprocess.run()` 无异常保护，缺少 amixer 命令时抛 `FileNotFoundError` | 添加 try-except 捕获 `FileNotFoundError`/`SubprocessError`/`OSError`，异常时返回 False |
| 2 | 🔴 | `_convert_plans_to_reminders()` 中 `plans` 列表元素可能非 dict，导致 `AttributeError` | 在循环内添加 `isinstance(p, dict)` 类型检查，非字典元素跳过并记录警告 |
| 3 | 🔴 | `_convert_plans_to_medicines()` 中 `plans` 列表元素可能非 dict，导致 `AttributeError` | 同上，添加类型检查 |
| 4 | 🔴 | `check_reminders()` 中 `times` 可能为字符串/整数等非可迭代类型，导致遍历逻辑错误 | 添加类型检查，字符串自动包装为列表，非列表/字符串类型转为字符串后包装 |
| 5 | 🔴 | `alert_loop()` 中 `reminder` 可能非 dict，调用 `.get()` 时崩溃 | 改用 `isinstance(reminder, dict)` 进行类型检查 |
| 6 | 🔴 | `update_stock()` 中 `state["medicines"]` 元素可能非 dict，导致 `AttributeError` | 在循环内添加类型检查，快照创建时过滤非字典元素 |
| 7 | 🔴 | `upload_log()` 中 `os.path.getsize()` 无异常保护，文件并发删除时抛 `OSError` | 添加 try-except 保护文件访问操作 |
| 8 | 🔴 | `main_loop()` 无顶层 try-except，未预期异常将导致主循环退出 | 在循环体内添加顶层 try-except，异常时记录 CRITICAL 日志并等待 1 秒 |
| 9 | 🔴 | `confirm_take()` 中 `next(iter(...))` 无默认值，字典为空时抛 `StopIteration` | 使用 `next(iter(...), None)` 提供默认值，检查 None 后再访问 |
| 10 | 🔴 | `capture_photo()` 中 `os.path.exists()` + `os.path.getsize()` 存在 TOCTOU 竞态条件 | 改用 try-except 处理文件检查，合并 exists 和 getsize 调用 |
| 11 | 🔴 | `log()` 日志文件写入无锁保护，多线程并发可能导致日志交错 | 将文件写入和大小检查都放入 `_log_lock` 保护范围 |
| 12 | 🔴 | `send_heartbeat()` 中存在死代码分支（`status != "ok"` 永远不会执行） | 移除死代码分支，简化逻辑 |
| 13 | 🟡 | `_speak_worker()` 每条播报都调用 `set_system_volume()`，造成大量 amixer 系统调用 | 缓存上次设置的音量值，仅在音量变化时才调用 set_system_volume |
| 14 | 🟡 | `sync_reminders()` 未检查 `_device_needs_re_register` 事件，同步失败时无法触发重新注册 | 在同步异常和无响应时检查事件状态并记录警告 |
| 15 | 🟡 | `notify_emergency()` 中 `content` 字段包含敏感联系信息 | 改用通用描述，联系信息仅在 `data` 字段中传递 |
| 16 | 🟡 | `save_device_token()` 未检查配置是否为空，可能覆盖已有配置 | 添加配置为空检查，记录警告日志 |
| 17 | 🟡 | `init_hardware()` 中 `Board().begin()` 异常可能导致引脚对象状态不一致 | 添加异常保护，初始化失败时清理已赋值的引脚对象 |

**魔法数字提取（v2.38.5）**：
- 新增常量 `DEFAULT_LOW_STOCK_THRESHOLD = 5`（默认低库存阈值）
- 新增常量 `LOW_STOCK_DAYS_THRESHOLD = 5`（剩余天数告警阈值）
- 新增常量 `ALL_WEEKDAYS = [1, 2, 3, 4, 5, 6, 7]`（全周默认值）
- 替换代码中所有硬编码的魔法数字为对应常量

### 已完成的 Bug 修复（v2.38.3，共 6 项，涵盖空响应处理、返回值检查、可维护性、性能优化）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `sync_reminders()` 未处理 `_empty_response` 标识，API 返回空响应体时可能丢失数据 | 增加 `_empty_response` 检查，空响应体视为成功但无数据，保留现有数据 |
| 2 | 🔴 | `_ensure_device_registered()` 中 `send_heartbeat()` 返回值未检查，心跳失败时仍返回 True | 检查 `send_heartbeat()` 返回值，心跳失败时记录警告但仍视为已注册（网络抖动容错） |
| 3 | 🟡 | 9 个辅助函数 docstring 不完整，缺少 Args/Returns 标准格式 | 补充 `_get_online`/`_set_online`/`_get_camera_available`/`_set_camera_available`/`_get_device_token`/`_set_device_token`/`_speak_worker`/`tts_speak`/`_build_device_payload`/`invalidate_emergency_contact_cache` 的完整 docstring |
| 4 | 🟡 | `_parse_dose_count()` 未处理含范围的剂量字符串（如"1-2片"、"1~2粒"），只匹配第一个数字 | 增加范围格式检测正则 `(\d+)\s*[-~至到]\s*(\d+)`，取最大值作为推荐剂量 |
| 5 | 🔵 | `_speak_worker()` 语音播报日志级别为 INFO，高频播报时日志过多 | 将语音播报日志降级为 DEBUG，减少不必要的日志输出 |
| 6 | 🔵 | `alert_loop()` 搜索药品暂停超时使用魔法数字 900，维护困难 | 提取为常量 `_MAX_SEARCH_MEDICINE_PAUSE_COUNT = 900`，便于统一管理 |

### 已完成的 Bug 修复（v2.38.2，共 2 项，涵盖代码健壮性、逻辑清晰度）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `update_stock()` 中 `current_remaining` 变量在库存为 0 或未找到药品时可能未定义，导致 `NameError` 崩溃 | 在函数开头初始化 `current_remaining = 0`，确保所有分支都有定义 |
| 2 | 🟡 | `http_request()` 业务错误检测逻辑不清晰，`status` 检查条件冗余且可能误判正常响应 | 简化为三种情况清晰处理：`status` 明确存在且不为 "ok" → 直接标记错误；`status` 为 "ok" → 不标记错误；`status` 不存在 → 检查 `message`/`error` 字段 |

### 已完成的 Bug 修复（v2.38.1，共 7 项，涵盖逻辑正确性、代码可维护性、健壮性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `alert_loop()` 搜索药品暂停时 `pause_count` 达到 `MAX_ALERT_RETRIES`（20次/40秒）会强制终止提醒，影响正常搜索药品流程 | 搜索药品暂停超时改为 30 分钟（900次 * 2秒），避免正常搜索导致提醒被意外终止 |
| 2 | 🔴 | `main_loop()` 网络恢复成功后 `heartbeat_fail_count` 未重置，导致下次心跳一次失败就误判设备离线 | 网络恢复成功时将 `heartbeat_fail_count` 重置为 0 |
| 3 | 🟡 | `http_request()` 业务错误检测仅检查 `status` 字段，部分接口可能返回无 `status` 但有 `message`/`error` 的错误响应 | 增加对 `message` 和 `error` 字段的检查，覆盖更多错误格式 |
| 4 | 🟡 | `register_device()` 和 `send_heartbeat()` 存在大量重复的 payload 构建和响应处理逻辑 | 抽取 `_build_device_payload()` 和 `_handle_register_response()` 公共函数，消除代码重复 |
| 5 | 🟡 | `send_heartbeat()` 业务错误时未检查 `_error` 标记，逻辑不完整 | 使用公共响应处理函数，增强业务错误检测逻辑 |
| 6 | 🟢 | `import uuid` 未使用，存在死导入 | 移除未使用的 `import uuid` |
| 7 | 🟢 | `low_stock_alert()` 中 `threading.Timer` 闭包使用外部变量 `prev_mode` 存在潜在引用风险 | 将 `prev_mode` 作为默认参数传递给闭包，确保引用安全 |

### 已完成的 Bug 修复（v2.38.0，共 10 项，涵盖致命缺陷修复、逻辑正确性、并发安全、安全性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `update_stock()` 中 `medicines_snapshot` 可能为 None 导致数据丢失：当库存为 0 时提前 break，快照未创建导致配置被覆盖为 None | 在循环前先创建完整快照，确保任何情况下都有有效值；找到药品且库存有更新时重新创建快照以反映最新修改 |
| 2 | 🔴 | `init_network()` 中 `_wifi_initialized` 状态不一致：WiFi 连接成功但 `is_wifi_connected()` 返回 False 时，`_wifi_initialized` 仍为 True，导致后续网络恢复检查跳过 WiFi 重连 | 在 WiFi 连接状态异常的 else 分支中重置 `_wifi_initialized = False` |
| 3 | 🔴 | `_enter_search_medicine_impl()` 退出检查事件耦合：使用 `_button_thread_stop_event` 作为搜索药品的退出检查，与按钮线程停止事件耦合导致状态不一致 | 添加专门的 `_search_medicine_stop_event` 事件，在 `exit_search_medicine()` 中设置此事件，与按钮线程停止事件解耦 |
| 4 | 🟡 | `low_stock_alert()` GUI 模式检查与恢复操作之间存在时间窗口：告警界面可能覆盖用户正在进行的操作 | 保存当前 GUI 模式，告警结束后仅当仍为 status 告警模式时才恢复到之前的模式；增加对 reminder 模式的特殊处理 |
| 5 | 🟡 | `confirm_take()` 当 `medicine_id` 为 None 时跳过库存更新但未告知用户 | 当 tid 为 None 时自动获取第一个活跃提醒；当无法获取有效提醒时，语音告知用户并返回 |
| 6 | 🟡 | `_parse_frequency_per_day()` 逻辑正确但注释不完善 | 保留现有实现，添加详细注释说明计算逻辑（每天平均次数的向上取整） |
| 7 | 🟢 | `_do_network_recovery_sync()` 与 `init_network()` 存在重复的 token 检查和设备注册逻辑 | 提取公共函数 `_ensure_device_registered()`，消除重复代码 |
| 8 | 🟢 | `clock_thread()` 中 Tkinter 对象可能在刷新过程中被销毁 | 增加 `winfo_exists()` 检查，防止对象被销毁后调用 `config()` 抛出异常 |
| 9 | 🟢 | `notify_emergency()` 紧急联系人缓存在配置更新后不会自动刷新 | 增加缓存过期机制（EMERGENCY_CACHE_TTL = 300 秒），过期后自动重新读取配置；新增 `invalidate_emergency_contact_cache()` 手动清除缓存接口 |
| 10 | 🔵 | `capture_photo()` 文件名正则缺少路径安全校验，可能存在路径遍历攻击 | 使用 `os.path.basename()` 提取纯文件名；添加文件名长度检查；使用 `os.path.realpath()` 验证最终路径在 PHOTO_DIR 下 |

### 已完成的 Bug 修复（v2.37.1，共 1 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `_barcode_detect_thread` 每 0.5 秒调用 `get_barcode_name()`（9 次 I2C 操作）+ 持续检测到条形码时每 0.5 秒写日志 + 即使名字没变也调用 `config()` 更新 tkinter，导致搜索药品时卡顿严重 | (1) 只在条形码名字变化时更新 GUI 和写日志，避免重复 tkinter 操作和日志刷屏；(2) 检测间隔从 0.5 秒增加到 1 秒，减少 I2C 压力 |

### 已完成的 Bug 修复（v2.37.0，共 6 项，涵盖优雅退出、逻辑正确性、代码可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `button_thread()` 使用 `while True` 无限循环，无法优雅退出 | 添加 `_button_thread_stop_event` 停止事件，改用可中断等待 `_button_thread_stop_event.wait(timeout=0.1)` 替代 `time.sleep(0.1)` |
| 2 | 🔴 | `main_loop()` 使用 `while True` 无限循环，无法优雅退出 | 添加 `_main_loop_stop_event` 停止事件，改用可中断等待 `_main_loop_stop_event.wait(timeout=CHECK_INTERVAL)` 替代 `time.sleep(CHECK_INTERVAL)` |
| 3 | 🔴 | `send_heartbeat()` 中 `elif` 分支永远不会执行，逻辑分支设计缺陷 | 简化逻辑，移除 `elif` 分支，直接在 `status != "ok"` 时检查业务错误，代码更清晰 |
| 4 | 🔴 | `update_stock()` 中 `found` 变量逻辑错误：库存为 0 时提前 break 但 `found` 仍为 False，导致误报"未找到药品" | 在检查库存前先标记 `found = True`，确保即使库存为 0 也能正确识别药品 |
| 5 | 🟡 | `_enter_search_medicine_impl()` 缺少异常保护，异常时可能导致 `_searching_medicine` 状态不一致 | 添加 `try-except` 保护，异常时调用 `_exit_search_medicine_impl()` 恢复状态；同时改用可中断等待 |
| 6 | 🟡 | `alert_loop()` 中搜索药品暂停时 `retry_count` 仍递增，导致在搜索期间过早超时 | 使用独立的 `pause_count` 计数器替代 `retry_count`，搜索药品暂停期间不再消耗重试次数 |

### 已完成的 Bug 修复（v2.36.0，共 8 项，涵盖并发安全、代码冗余、性能优化、可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `_enter_search_medicine_impl()` 日志在锁外读取共享变量 `_previous_gui_mode`，存在竞态条件 | 将日志语句移到 `with _gui_lock` 块内执行，确保日志输出使用加锁读取的一致值 |
| 2 | 🔴 | `face_id_thread()` 使用 `time.sleep(0.5)` 导致退出时无法立即响应停止事件 | 改用 `_face_id_stop_event.wait(timeout=0.5)` 实现可中断等待 |
| 3 | 🟡 | `clock_thread()` 使用 `time.sleep()` 导致退出延迟最多 1 秒 | 改用 `_clock_stop_event.wait(timeout=CLOCK_REFRESH_INTERVAL)` 实现可中断等待 |
| 4 | 🟡 | `main_loop()` 中 `_do_network_recovery_sync()` 闭包每次循环重新定义，增加不必要开销 | 将函数提取为模块级独立函数，避免每次循环迭代都重新创建函数对象 |
| 5 | 🟡 | `_barcode_detect_thread()` 使用 `time.sleep()` 导致退出延迟 | 改用 `_barcode_thread_stop.wait(timeout=0.5)` 实现可中断等待 |
| 6 | 🟢 | `update_gui_home()`/`update_gui_reminder()` 按钮回调创建不必要的闭包函数 | 简化为直接在 lambda 中使用 `enter_search_medicine`，消除冗余闭包 |
| 7 | 🔵 | `detect_volume_control()` 中 `control_exists()` 函数定义在函数内部 | 提取为模块级独立函数 `_control_exists`，避免每次调用重复创建 |
| 8 | 🔵 | 所有修复的线程函数文档字符串中缺少修复版本说明 | 为每个修复的函数添加 v2.36.0 修复说明注释，提高可追溯性 |

### 已完成的 Bug 修复（v2.35.7，共 9 项，涵盖并发安全、代码冗余、逻辑正确性、可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `_gui_mode` 变量无锁保护并发读写：`main_loop()` 中读取 `_gui_mode` 未加锁，可能导致竞态条件 | 使用 `_gui_lock` 保护读取操作 |
| 2 | 🔴 | `low_stock_alert()` 中 `_restore_status()` 读取 `_gui_mode` 未加锁 | 添加 `_gui_lock` 保护，确保线程安全 |
| 3 | 🔴 | `_enter_search_medicine_impl()` 中 `saved_mode` 变量冗余赋值：在锁内重复赋值 | 移除冗余变量，直接使用 `_previous_gui_mode` 进行日志输出 |
| 4 | 🟡 | `update_stock()` 中阈值获取逻辑冗余嵌套：存在双重 `try-except` 和重复的 `int()` 转换 | 简化为单次 `try-except`，提高代码可读性 |
| 5 | 🟡 | `_convert_plans_to_medicines()` 中类型转换逻辑冗余：多处嵌套 try-except 和重复的 `int()` 转换 | 简化类型转换逻辑，减少代码重复 |
| 6 | 🟢 | `notify_emergency()` 紧急联系人缓存初始化逻辑可优化 | 保留现有缓存机制，确保首次读取正确 |
| 7 | 🟢 | 版本号不一致：文件头、注释中版本号不统一 | 统一为 v2.35.7 |
| 8 | 🟢 | API 端点注释版本号与实际版本号不同步 | 更新注释中的版本号为 v2.35.7 |
| 9 | 🟢 | 代码中存在多处版本号引用，维护成本高 | 统一版本号引用，便于后续维护 |

### 已完成的 Bug 修复（v2.35.6，共 6 项，涵盖逻辑正确性、安全性、代码质量）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `sync_reminders()` 状态检查逻辑缺陷：当 status 字段不存在时跳过错误检测 | 增加 status 存在性检查，防止字段缺失时误判 |
| 2 | 🔴 | `init_network()` WiFi 凭据检查不完整：只检查 SSID 未检查密码 | 同时检查 SSID 和密码是否为空 |
| 3 | 🟡 | `_parse_dose_count()` 返回值缺乏边界验证 | 添加 `max(1, val)` 范围检查，确保返回值 >= 1 |
| 4 | 🟡 | `detect_volume_control()` 中 `control_exists()` 文档字符串不完整 | 添加标准 Args/Returns 格式，补充参数说明 |
| 5 | 🟢 | `detect_volume_control()` 中 subprocess 参数列表使用三元表达式拼接 | 改用 if-else 语句提高可读性，消除运算符优先级歧义 |
| 6 | 🟢 | WiFi 配置示例与实际代码不一致（README 显示硬编码密码） | 更新文档示例为空字符串默认值，与 v2.35.5 安全修复保持一致 |

### 已完成的 Bug 修复（v2.35.5，共 8 项，涵盖安全性、并发安全、性能优化、代码质量）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | WiFi 密码硬编码默认值为真实密码，存在安全风险 | 改为空字符串默认值，强制生产环境通过环境变量配置 |
| 2 | 🔴 | `init_network()` 未检查 WiFi 凭据是否配置就尝试连接 | 添加凭据检查，未配置时提前进入离线模式 |
| 3 | 🔴 | `_exit_search_medicine_impl()` 中 reminder 在锁释放后使用，存在数据竞争 | 在锁内创建副本后锁外使用 |
| 4 | 🔴 | `http_request()` 403 关键词 "invalid" 过宽，可能误判非认证错误 | 收紧关键词列表，仅保留精确匹配的认证相关关键词 |
| 5 | 🟡 | `flush_local_logs()` 中 `del photo/msg_payload/entry` 操作冗余 | 改为 `= None` 赋值，更优雅地释放引用 |
| 6 | 🟡 | `face_id_thread()` 文本未变化时仍更新 GUI，造成无效刷新 | 添加文本变化检查，仅在变化时更新 |
| 7 | 🟢 | `http_request()` URLError 日志泄露具体原因 | 仅记录错误类型名称，不泄露敏感信息 |
| 8 | 🟢 | `upload_log()` 中 photo_ok 判断逻辑冗余，代码可读性差 | 简化逻辑，无照片时直接成功，照片失败时立即入队并返回 |

### 已完成的 Bug 修复（v2.35.4，共 8 项，涵盖安全性、逻辑正确性、健壮性、可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `capture_photo()` 文件名正则验证过严，不支持中文字符 | 扩展正则支持中文和国际化文件名 |
| 2 | 🔴 | `load_device_token()` token 验证过严，强制要求长度 > 10 且不含空格 | 放宽为非空字符串验证，兼容各种 token 格式 |
| 3 | 🟡 | `update_stock()` 库存不足时日志信息不完整 | 添加药品名称和具体数量的详细日志 |
| 4 | 🟡 | `http_request()` 403 关键词"令牌"过宽，可能误判非认证错误 | 移除"令牌"关键词，保留精确匹配"device_token"和"认证" |
| 5 | 🟡 | `sync_reminders()` 状态检查逻辑冗余 | 简化 status 判断，移除不必要的 None 检查 |
| 6 | 🟢 | `_convert_plans_to_medicines()` per_time 类型转换逻辑嵌套过深 | 改用 try-except 简化 |
| 7 | 🟢 | `flush_local_logs()` 内存清理不完整，entry 变量未释放 | finally 块中显式删除所有临时变量 |
| 8 | 🔵 | 修复记录格式不规范 | 统一修复记录格式，确保可追溯 |

### 已完成的 Bug 修复（v2.35.3，共 7 项，涵盖安全性、逻辑正确性、健壮性、可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `http_request()` 中 403 关键词 "auth" 过于宽泛，可能误触发重新注册 | 改为更精确的 "authentication"，减少误判 |
| 2 | 🟡 | 版本号不一致：API 端点注释仍显示 v2.35.0，与文件头 v2.35.2 不匹配 | 统一更新为 v2.35.3，同步更新文件头和注释 |
| 3 | 🟡 | `_convert_plans_to_medicines()` 中 `threshold`/`unit` 字段可能为 None，导致后续异常 | 添加 None 和类型检查，`threshold` 为负数时默认回退到 5 |
| 4 | 🟡 | `sync_reminders()` 中 `plans` 列表为空时仍覆盖 `state["reminders"]` 和 `state["medicines"]`，可能导致提醒丢失 | 仅当有效计划数大于 0 时才更新状态，空列表保留现有数据 |
| 5 | 🟡 | `init_network()` 中网络检测失败时 `_wifi_initialized` 未重置，导致 WiFi 重连逻辑失效 | 网络检测失败时显式重置 `_wifi_initialized = False` |
| 6 | 🟡 | `main_loop()` 中网络恢复后直接调用 `update_gui_home()`，无条件覆盖搜索药品/提醒界面 | 仅在 `_gui_mode` 为 "home" 或 "status" 时才恢复主页 |
| 7 | 🟢 | `flush_local_logs()` 中 `photo_base64` 字段在循环迭代期间长期占用内存 | 添加 `finally` 块显式清理 `photo` 和 `msg_payload` 变量 |

### 已完成的 Bug 修复（v2.35.2，共 7 项，涵盖安全性、健壮性、代码质量）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `http_request()` 中 403 错误检测关键词包含 "token"，过于宽泛可能误触发重新注册 | 移除 "token"，仅保留 "device_token" 精确匹配 |
| 2 | 🟡 | `upload_log()` 末尾注释不准确（"消息成功或照片失败的其他情况"），分支逻辑冗余 | 修正注释为兜底说明，表明此分支为未预期执行路径的安全返回 |
| 3 | 🟡 | `main_loop()` 心跳单次失败立即标记离线，对网络抖动过于敏感 | 新增 `heartbeat_fail_count` 计数器，连续失败 2 次后再标记离线，成功时重置计数 |
| 4 | 🟡 | `alert_loop()` 搜索药品暂停时重试间隔 0.5 秒，20 次仅 10 秒就超时 | 延长等待间隔到 2 秒（总超时约 40 秒），避免在搜索药品期间过早超时 |
| 5 | 🟢 | `flush_local_logs()` 中 `slim_entry` 构建逻辑与 `msg_payload` 重复 | 直接复用已构建的 `msg_payload`，消除冗余代码 |
| 6 | 🟢 | `send_heartbeat()` 未预期响应分支注释不清晰 | 简化注释说明，明确为统一兜底返回 |
| 7 | 🟢 | `heartbeat_fail_count` 计数器在心跳成功时未重置，逻辑不完整 | 添加心跳成功时的计数重置逻辑 |

### 已完成的 Bug 修复（v2.35.1，共 8 项，涵盖健壮性、并发安全、逻辑正确性、可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `flush_local_logs()` 中 Lock.release() 在未获取锁时调用会抛 RuntimeError，导致程序崩溃 | 记录 `lock_acquired` 标志，仅在成功获取锁时才释放 |
| 2 | 🔴 | `button_thread()` 中按钮读取无异常保护，引脚访问失败导致整个轮询线程崩溃 | 为每个按钮读取添加 try-except 异常保护，记录警告日志并继续循环 |
| 3 | 🔴 | `init_network()` WiFi 连接失败后 `_wifi_initialized` 仍设为 True，导致无法重试 WiFi 连接 | 仅在连接成功时标记为已初始化，失败时保持 False 允许后续重试 |
| 4 | 🟡 | `_previous_gui_mode` 无锁保护，在多线程环境下可能出现竞态条件 | 使用 `_gui_lock` 保护 `_previous_gui_mode` 的设置和读取 |
| 5 | 🟡 | `http_request()` 中 403 错误检测关键词包含 "not found"/"not exist"，可能误触发重新注册 | 移除容易误判的关键词，收紧检测范围，仅保留认证相关关键词 |
| 6 | 🟡 | `_parse_frequency_per_day()` 中 "每N天1次" 返回硬编码值 1，未正确计算每日服用次数 | 使用向上取整除法 `max(1, (1 + days - 1) // days)` 计算合理的每日次数 |
| 7 | 🟢 | `button_thread()` 函数缺少文档字符串 | 添加 docstring 说明轮询机制和异常处理策略 |
| 8 | 🟢 | 部分修复函数注释不完善，缺少修复版本说明 | 为修复函数添加 v2.35.1 修复说明注释，提高可追溯性 |

### 已完成的 Bug 修复（v2.35.0，共 6 项，涵盖逻辑正确性、健壮性、安全性、可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `switch_huskylens_to_face()` 无返回值，调用方无法判断切换是否成功 | 添加 True/False 返回值，HuskyLens 不可用或异常时返回 False |
| 2 | 🔴 | `trigger_alert()` 未检查 `switch_huskylens_to_face()` 返回值，切换失败时仍继续启动 alert_loop | 检查返回值，失败时记录 WARNING 日志，提醒功能继续但提示人脸识别不可用 |
| 3 | 🔴 | `_exit_search_medicine_impl()` 未检查 `switch_huskylens_to_face()` 返回值，退出搜索药品时切换回人脸识别失败无日志 | 检查返回值并记录失败日志 |
| 4 | 🟡 | `send_heartbeat()` 返回 False 时缺少详细日志，网络问题排查困难 | 添加心跳无响应日志、响应格式异常日志、非预期状态日志 |
| 5 | 🟢 | `http_request()` 中 403 错误检测范围过窄，仅检查"device_token"/"token"/"令牌"关键字 | 扩展为多关键字列表检测（含 unauthorized/forbidden/auth/invalid/missing/expired 等） |
| 6 | 🟢 | User-Agent 硬编码字符串分散在 `check_network()` 和 `_auth_headers()` 两处 | 提取为 `USER_AGENT` 常量，统一管理 |

### 已完成的 Bug 修复（v2.34.0，共 5 项，涵盖逻辑正确性、健壮性、并发安全、可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | 版本号不一致：文件头版本为 v2.33.9，API 端点注释仍为 v2.33.8，README 为 v2.33.10 | 统一更新为 v2.34.0，新增 v2.34.0 修复记录注释 |
| 2 | 🟡 | `alert_loop()` 搜索药品暂停时 `retry_count` 不增加，若搜索模式持续时间过长，提醒永不超时 | 搜索药品暂停时仍递增 `retry_count`，达到 `MAX_ALERT_RETRIES` 时自动停止提醒并清理状态 |
| 3 | 🟡 | `_enter_search_medicine_impl()` 未检查 `switch_huskylens_to_barcode()` 返回值，切换失败时仍启动条形码线程和显示搜索界面 | 检查返回值，切换失败时记录 WARNING 日志，且不启动条形码检测线程 |
| 4 | 🟡 | `low_stock_alert()` 中 `state.get("mode", "home")` 读取不存在的键，导致业务模式检查始终返回默认值"home"，保护逻辑失效 | 移除无效的 `state.mode` 检查，仅保留 `_gui_mode` 检查（已覆盖所有场景） |
| 5 | 🟢 | `_convert_plans_to_medicines()` 中 `per_time` 和 `freq_per_day` 的异常处理存在冗余嵌套 | 简化为条件表达式 `max(1, int(x)) if x is not None and isinstance(x, (int, float)) else 1` |

### 已完成的 Bug 修复（v2.33.10，共 5 项，涵盖逻辑正确性、健壮性、安全性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `update_stock()` 库存扣减未检查剩余量，`remaining` 为 0 或负数时仍会扣减，导致库存变为负数 | 在扣减前检查剩余量，若 `current_remaining <= 0` 则跳过扣减并记录警告日志 |
| 2 | 🟡 | `send_heartbeat()` 心跳业务错误（`_error`）未被识别，业务失败时无日志记录 | 增加 `_error` 标记检查，业务错误时记录详细错误信息并返回 False |
| 3 | 🟡 | `http_request()` 空响应体未正确处理，部分接口返回空 200 时仍报错 | 空响应体时返回 `{"status": "ok", "_empty_response": True}` 表示成功 |
| 4 | 🟡 | `alert_loop()` 中 `get_face_name()` 无法获取真实名字时返回默认 id 字符串（如 "id1"），播报内容不友好 | 检查返回值是否为默认 id 格式，是则使用"老人"作为称呼 |
| 5 | 🟢 | 版本修复记录不完整 | 新增 v2.33.10 修复记录注释，保持变更可追溯 |

### 已完成的 Bug 修复（v2.33.9，共 5 项，涵盖逻辑正确性、健壮性、可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `_convert_plans_to_medicines()` 中 `per_time` 为 None 或非数字时会抛 TypeError | 添加安全转换逻辑，异常时默认值为 1 |
| 2 | 🟡 | `notify_emergency()` 中 `_emergency_contact_cache` 全局变量无初始化检查 | 改为函数内安全初始化，增加 `strip()` 和空值校验 |
| 3 | 🟡 | `flush_local_logs()` 中上传失败的 entry 保留了 base64 照片数据，长期积累占用内存 | 上传失败时剥离 `_photo` 字段，仅保留必要字段 |
| 4 | 🟡 | `http_request()` 中 GET 请求仍需先 pop Content-Type header，逻辑冗余 | 简化为 GET 请求时直接移除 Content-Type header |
| 5 | 🟢 | 版本修复记录不完整 | 新增 v2.33.9 修复记录注释，保持变更可追溯 |

### 已完成的 Bug 修复（v2.33.8，共 6 项，涵盖逻辑正确性、健壮性、可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `alert_loop()` 中搜索药品模式使用 `time.sleep(0.5)` 阻塞，无法及时响应中断 | 改用 `_alert_interrupt_event.wait(timeout=0.5)` 可中断等待 |
| 2 | 🟡 | `sync_reminders()` 中 status 检查逻辑：`resp.get("status")` 在 status 为空时误判为错误 | 改为 `resp.get("status") is not None` 判断 |
| 3 | 🟡 | `update_stock()` 阈值检查使用 `<`，剩余数量恰好等于阈值时不触发告警 | 改为 `<=`，覆盖边界情况 |
| 4 | 🟡 | `calculate_remaining_days()` 向上取整使用 `int(total)` 截断导致精度丢失 | 改为浮点运算的向上取整 `int(-(-total // daily))` |
| 5 | 🟡 | `low_stock_alert()` 定时器可能覆盖用户搜索药品或提醒界面 | 增加 GUI 模式检查，仅在 home/status 模式下恢复 |
| 6 | 🟢 | 版本号注释不一致 | 修正 API 端点注释版本号为 v2.33.8 |

### 已完成的 Bug 修复（v2.33.7，共 3 项，涵盖逻辑正确性、健壮性、可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `_convert_plans_to_medicines()` 中 `dosage` 变量未定义（缺少 `dosage = p.get("dosage", "1片")`），运行时抛 `NameError`，导致库存计算和持久化全部失败 | 在循环内添加 `dosage = p.get("dosage", "1片")` 定义 |
| 2 | 🟡 | 版本号注释不一致：API 端点注释仍显示 v2.33.6，与文件头 v2.33.7 不一致 | 修正 API 端点注释版本号为 v2.33.7 |
| 3 | 🟢 | 新增版本修复记录注释 | 保持变更可追溯 |

### 已完成的 Bug 修复（v2.33.6，共 4 项，涵盖逻辑正确性、可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | 版本号注释不一致：API 端点注释仍显示 v2.33.4，与文件头 v2.33.5 不一致 | 修正 API 端点注释版本号为 v2.33.6 |
| 2 | 🔴 | `_convert_plans_to_medicines()` 中 `per_time` 硬编码为 1，未从 `dosage` 字段解析，导致库存计算不准确 | 改用 `_parse_dose_count(dosage)` 解析每次服用数量 |
| 3 | 🟡 | `alert_loop()` 中 `wait_timeout` 硬编码为 10，不便于统一配置 | 提取为 `ALERT_WAIT_TIMEOUT` 常量 |
| 4 | 🟢 | 提醒循环等待时间无独立常量管理 | 新增 `ALERT_WAIT_TIMEOUT` 常量，统一管理提醒循环等待时间 |

### 已完成的 Bug 修复（v2.33.5，共 8 项，涵盖并发安全、健壮性、可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | 版本号注释不一致：API 端点注释仍显示 v2.33.3，与文件头 v2.33.4 不一致 | 修正 API 端点注释版本号为 v2.33.4 |
| 2 | 🔴 | `alert_loop()` 中 `volume` 在锁内读取后锁外使用，存在竞态条件，其他线程可能在播报期间修改音量 | 改用 `current_volume` 副本，在锁内获取后传递给 `tts_speak()` |
| 3 | 🔴 | `http_request()` 403 错误检测仅依赖"设备令牌"关键字，过于脆弱，可能漏判 | 扩展为检查 `device_token`/`token`/`令牌` 多种关键字（含大小写不敏感） |
| 4 | 🔴 | `confirm_take()` 在 `medicine_id` 为 None 时仍调用 `update_stock()`，可能导致库存异常 | 添加空值检查，仅在有有效药品ID时更新库存 |
| 5 | 🟡 | `send_heartbeat()` 心跳成功日志为 DEBUG 级别，不利于生产环境监控 | 改为 INFO 级别，便于追踪心跳状态 |
| 6 | 🟡 | `face_id_thread()` 中变量更新顺序可能导致短暂不一致状态 | 优化更新顺序：先计算新文本，再更新全局变量，最后更新 GUI |
| 7 | 🟡 | `alert_loop()` 等待循环使用 `time.sleep` + `time.time()` 轮询，响应不够高效 | 改用 `threading.Event.wait(timeout=1.0)` 分段等待，每1秒检查一次退出条件 |
| 8 | 🟢 | `trigger_alert()` 启动新提醒循环前未清理中断事件，可能导致旧事件残留 | 添加 `_alert_interrupt_event.clear()` 确保每次新提醒都有干净状态 |

### 已完成的 Bug 修复（v2.33.4，共 6 项，涵盖并发安全、健壮性、可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | 版本号注释不一致：API 端点注释仍显示 v2.33.2，与文件头 v2.33.3 不一致 | 修正 API 端点注释版本号为 v2.33.3 |
| 2 | 🔴 | `clock_thread()` 中 GUI 变量（`_gui_mode`/`_clock_time_obj`/`_clock_date_obj`）读取无锁保护，存在竞态条件 | 添加 `_gui_lock` 保护 GUI 变量读取 |
| 3 | 🔴 | `_barcode_detect_thread()` 中 `_barcode_text_obj` 读取无锁保护，存在竞态条件 | 添加 `_gui_draw_lock` 保护 GUI 对象读取和更新 |
| 4 | 🟡 | `send_heartbeat()` 心跳成功缺少日志记录，难以追踪心跳状态 | 添加心跳成功日志（DEBUG 级别） |
| 5 | 🟡 | 程序退出时未设置 `_clock_stop_event`/`_face_id_stop_event`/`_barcode_thread_stop`，可能导致线程无法正常退出 | 在 `main()` 的 finally 块中添加清理逻辑 |
| 6 | 🟢 | 文件头缺少版权声明 | 添加版权声明头 |

### 已完成的 Bug 修复（v2.33.3，共 6 项，涵盖安全、并发、健壮性、可维护性）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | WiFi SSID/密码硬编码，存在安全风险且部署不灵活 | 改为从环境变量读取（`WIFI_SSID`/`WIFI_PASSWORD`），代码中保留默认值作为回退 |
| 2 | 🔴 | `update_stock()` 库存阈值计算错误，`low_stock_threshold` 被错误地乘以 `frequency_per_day` | 修正为直接使用 `low_stock_threshold` 作为剩余片数阈值 |
| 3 | 🟡 | `_face_id_text` 全局变量无锁保护，存在并发读写竞态条件 | 新增 `_face_id_lock` 和 `_get_face_id_text()` 线程安全读取方法 |
| 4 | 🟡 | `http_request()` 错误日志泄露响应体内容，可能暴露敏感信息 | 改为仅记录错误码和 URL，不记录响应体 |
| 5 | 🟡 | `enter_search_medicine()`/`exit_search_medicine()` 缺少防重复调用机制 | 添加状态检查，已在搜索模式中时忽略重复调用 |
| 6 | 🟢 | 搜索药品模式切换等待时间硬编码 `time.sleep(1)` | 提取为 `SEARCH_MEDICINE_PAUSE_DELAY` 常量，便于维护 |

### 已完成的 Bug 修复（v2.33.2，共 1 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `enter_search_medicine()`/`exit_search_medicine()` 在 GUI 主线程（onclick 回调）中执行，`switch_huskylens_to_barcode/face()` 阻塞 GUI 主线程 5 秒，期间 `clock_thread`/`face_id_thread` 操作 tkinter 导致死锁（主页卡住需重启） | 将实际逻辑拆分到后台线程执行（`_enter/_exit_search_medicine_impl`），onclick 回调立即返回不阻塞 GUI 主线程；进入搜索前等待 1 秒确保 `face_id_thread` 暂停，避免 I2C 冲突 |

### 已完成的 Bug 修复（v2.33.1，共 1 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `alert_loop()` 提醒循环在搜索药品模式下仍调用 `detect_face_id()`，其内部的 `huskylens.getResult(ALGORITHM_FACE_RECOGNITION)` 会把二哈从条形码识别切回人脸识别，导致搜索药品时二哈模式切换失效 | 在 `alert_loop()` 循环开头检查 `_searching_medicine` 事件，搜索药品时暂停提醒循环（不检测人脸、不播报、不增加重试次数） |

### 已完成的 Bug 修复（v2.33.0，共 6 项，新增搜索药品功能和二哈初始化逻辑调整）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🟢 新增 | 缺少药品条形码搜索功能 | 主页和提醒吃药界面底部新增"搜索药品"触摸按钮，点击后切换 HuskyLens 到条形码识别模式 |
| 2 | 🟢 新增 | 搜索药品界面缺失 | 新增 `update_gui_search_medicine()`：中间偏上显示"药品为："和实时识别到的条形码名字，底部"返回"按钮恢复前一界面 |
| 3 | 🟢 新增 | 缺少模式切换函数 | 新增 `enter_search_medicine()`/`exit_search_medicine()`，记录前一界面（home/reminder）并正确恢复 |
| 4 | 🟢 新增 | 缺少条形码检测线程 | 新增 `_barcode_detect_thread()`，每 0.5 秒检测一次条形码并实时更新界面显示 |
| 5 | 🟡 修改 | 开机即切换人脸识别模式浪费资源 | `init_hardware()` 中 HuskyLens 仅初始化硬件（`knock` 握手），改为在 `trigger_alert()` 触发提醒时才切换到人脸识别模式 |
| 6 | 🟡 修改 | `face_id_thread()` 搜索药品时仍检测人脸导致冲突 | 搜索药品模式下（`_searching_medicine` 事件 set）暂停人脸检测；`exit_search_medicine()` 返回时统一切换回人脸识别模式 |

### 已完成的 Bug 修复（v2.32.1，共 1 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `get_face_name()`/`detect_face_id()`/`get_current_face_ids()` 缺少 `getResult()`+`available()` 预检，直接调用 `getCachedResultByID` 导致永远检测不到人脸 | 按官方实例代码流程修正：先 `getResult()` → `available()` 检查 → 再 `getCachedResultByID()` |

### 已完成的 Bug 修复（v2.32.0，共 5 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🟢 新增 | 缺少人脸名字获取和ID检测函数 | 新增 `get_face_name()`/`detect_face_id()`/`get_current_face_ids()`，通过 `getCachedResultByID` 获取人脸信息 |
| 2 | 🟢 新增 | GUI 左下角无人脸ID显示 | 新增 `face_id_thread()` 后台线程，每 0.5 秒检测人脸ID并更新左下角显示 |
| 3 | 🟢 新增 | 开机后 HuskyLens 未切换到人脸识别模式 | `init_hardware()` 中初始化后即切换到 `ALGORITHM_FACE_RECOGNITION` |
| 4 | 🟡 修改 | `alert_loop()` 无人脸检测，固定播报提醒内容 | 改为检测 id2：检测到前播报"请{名字}来吃药"，检测到后播报用药信息（在线用计划，离线播报"吃1个测试药品"），循环播报直到按"已吃药"按钮 |
| 5 | 🟡 修改 | `gui.clear()` 后 `_face_id_obj` 引用未重置 | `update_gui_home/status/reminder()` 中重置 `_face_id_obj = None`，由 `face_id_thread` 自动重建 |

### 已完成的 Bug 修复（v2.31.0，共 3 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🟢 新增 | HuskyLens 二哈识图未初始化 | `init_hardware()` 中添加 `HuskylensV2_I2C()` + `knock()` 初始化 |
| 2 | 🟢 新增 | 缺少人脸识别模式切换函数 | 新增 `switch_huskylens_to_face()`，切换到 `ALGORITHM_FACE_RECOGNITION` 并等待 5 秒 |
| 3 | 🟢 新增 | 到时间提醒和按提醒按钮时未切换人脸识别模式 | `trigger_alert()` 中调用 `switch_huskylens_to_face()`（覆盖两种触发场景） |

### 已完成的 Bug 修复（v2.30.2，共 1 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🟡 | `http_request()` 仅检测 404"设备未注册"，未检测 403"设备令牌无效或缺失"（本地 token 与服务端不匹配） | 补充 403"设备令牌"检测，触发 `_device_needs_re_register` 标志重新注册 |

### 已完成的 Bug 修复（v2.30.1，共 3 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `pyttsx3`/`unihiker`/`pinpong` 导入缺少 try-except，`_PYTTSX3_AVAILABLE`/`_GUI_AVAILABLE`/`_PINPONG_AVAILABLE` 未定义导致 NameError，硬件初始化和 TTS 初始化全部失败 | 三个 import 改为 try-except 并定义标志位 |
| 2 | 🟡 | `register_device()` 收到"成功但无 token"时误判为失败（服务端已注册设备心跳模式不返回 token 是正常行为） | 改为返回 True，日志输出"设备已注册（心跳模式）" |
| 3 | 🟡 | `register_device()`/`send_heartbeat()` 未携带 X-Device-Token header，服务端无法区分心跳和 token 丢失 | `_auth_headers()` 已自动添加 X-Device-Token，配合服务端 `register_or_heartbeat` 的 `existing_token` 参数 |

### 已完成的 Bug 修复（v2.30.0，共 3 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | 设备 ID 变更后本地旧 token 失效，服务器返回 404"设备未注册"，所有接口（schedule/message/upload）均失败 | `http_request()` 检测 404 + "设备未注册"时设置 `_device_needs_re_register` 标志；`main_loop` 检测后调用 `clear_device_token()` 清除旧 token 并 `register_device()` 重新注册 |
| 2 | 🟢 新增 | 缺少心跳机制，服务器无法感知设备是否在线 | 新增 `send_heartbeat()` 函数，`main_loop` 每 20 秒向 register 接口发送心跳（首次注册返回 token，已注册设备仅更新 `last_heartbeat_at`） |
| 3 | 🟢 新增 | 无法清除失效的本地 token | 新增 `clear_device_token()` 函数，同时清除内存和配置文件中的 token |

### 已完成的 Bug 修复（v2.29.9，共 2 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `_auth_headers()` 缺少 User-Agent 头，Cloudflare 返回 403 error code:1010 拦截所有 API 请求（注册、同步、上传均失败） | 在 `_auth_headers()` 中添加 `User-Agent: Mozilla/5.0 (compatible; M10MedicationChecker/1.0)` 请求头 |
| 2 | 🟡 | `_do_network_recovery_sync()` 网络恢复时重复调用 `register_device()`，注册失败后无限重试 | 改为本地有 token 时仅同步用药计划，注册只跑一次；注册失败时跳过同步 |

### 已完成的 Bug 修复（v2.29.8，共 12 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | 模块加载时 WiFi 连接阻塞（30秒超时），导致启动卡死 | 移至 `init_network()` 延迟执行，添加 3 次重试机制，每次间隔 2 秒 |
| 2 | 🔴 | `_emergency_contact_cache` 和 `_volume_control_cmd` 全局缓存变量缺少并发锁保护 | 新增 `_emergency_lock` 和 `_volume_lock`，在所有缓存访问处加锁 |
| 3 | 🟡 | `on_take_button_pressed()` 使用 `next(iter())` 无默认值，集合为空时抛 StopIteration | 添加默认值 `next(iter(...), None)`，确保安全获取 |
| 4 | 🟡 | `_convert_plans_to_medicines()` `total_quantity` 非数字字符串时转换崩溃 | 添加 try/except 处理 ValueError 和 TypeError，异常时默认 0 |
| 5 | 🟡 | `init_hardware()` 中 `subprocess.run` 调用无超时，`fswebcam` 检测可能卡死 | 添加 `timeout=5` 和超时异常捕获，超时后置为 False |
| 6 | 🟡 | `upload_log()` `event_type` 空字符串校验不完整 | 增加 `strip()` 检查，空白字符串也视为无效 |
| 7 | 🟡 | `config` 和 `queue` 备份路径仅用时间戳，并发写文件时可能覆盖备份 | 备份文件名添加 `os.getpid()` 避免并发冲突 |
| 8 | 🟡 | `http_request()` 超时值使用魔法数字 15，难以维护 | 提取为 `HTTP_REQUEST_TIMEOUT` 常量，默认参数改为 None |
| 9 | 🟢 | `button_thread()` 按钮去重时间使用魔法数字 2/3 | 提取为 `BUTTON_DEBOUNCE_TAKE/REMIND/EMERGENCY` 常量 |
| 10 | 🟢 | `init_network()` 异常日志类型信息不足 | 添加详细异常类型和堆栈日志，提升可调试性 |
| 11 | 🟢 | 网络连接首次尝试无提示，重试间隔不明确 | 添加首次提示日志和重试间隔说明 |
| 12 | 🟢 | 代码注释优化 | 优化注释说明，提升代码可读性 |

### 已完成的 Bug 修复（v2.29.7，共 9 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `_speech_lock` 使用 `threading.Lock`，`_speak_worker` 中嵌套获取导致永久死锁 | 改用 `threading.RLock()` 支持嵌套获取 |
| 2 | 🔴 | `check_reminders()` 空列表 `[]` 作为 days 时默认值不生效，提醒永不触发 | 增加空列表检查，空列表时使用默认值 `[1-7]` |
| 3 | 🔴 | `upload_log()` 消息成功但照片失败时，消息被重复入队导致重复发送 | 照片失败时仅入队照片数据，不再重复入队消息 |
| 4 | 🟡 | `_convert_plans_to_medicines()` `total_quantity` 为 None 时 `float()` 抛出 TypeError | 改用 `p.get("total_quantity") or 0` 安全处理 |
| 5 | 🟡 | `trigger_alert()` 中 `reminder` 在锁外被引用，可能导致数据竞争 | 函数入口立即创建副本 `reminder_copy`，锁内外均使用副本 |
| 6 | 🟡 | `set_system_volume()` `_volume_control_cmd` 为空字符串时 amixer 参数错误 | 增加空字符串检查，为空时跳过音量设置 |
| 7 | 🟡 | `notify_emergency()` 每次紧急呼叫同步读取配置文件，响应延迟 | 缓存紧急联系人信息到模块级变量，首次读取后复用 |
| 8 | 🟢 | `_speak_worker()` espeak 回退无特殊字符处理 | 清理换行符、引号等特殊字符，避免 espeak 解析错误 |
| 9 | 🟢 | 代码注释优化 | 优化注释说明，提升代码可读性 |

### 已完成的 Bug 修复（v2.29.6，共 6 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | 版本号注释过时，API 端点注释仍为 v2.29.3 | 更新注释为 v2.29.6，与当前代码版本一致 |
| 2 | 🔴 | `upload_log()` 消息发送失败后仍尝试上传照片，浪费网络资源和时间 | 消息失败时直接写入离线队列，跳过照片上传，提升效率 |
| 3 | 🟡 | `low_stock_alert()` AI 查询补货失败日志不详细，无法区分错误类型 | 增加业务错误检查、网络错误检查和详细异常类型记录 |
| 4 | 🟡 | `flush_local_logs()` 空照片数据仍尝试上传，且消息失败时仍处理照片 | 增加照片数据有效性校验（非空字符串），消息失败时直接保留条目跳过照片处理 |
| 5 | 🟡 | `init_network()` WiFi 重连成功无日志，异常日志不详细 | 添加重连成功日志和详细异常类型记录，便于问题排查 |
| 6 | 🟢 | 代码注释优化 | 优化注释说明，提升代码可读性 |

### 已完成的 Bug 修复（v2.29.5，共 12 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `flush_local_logs()` 队列为空时提前返回导致 `_flush_in_progress` 锁无法释放，后续调用永久阻塞 | 重构逻辑：损坏文件处理后使用空队列继续执行，队列为空时写回空队列后返回，确保 finally 释放锁 |
| 2 | 🔴 | `flush_local_logs()` 文件损坏后直接 `return`，跳过锁释放 | 损坏文件处理后设 `queue = []` 继续执行后续逻辑 |
| 3 | 🟡 | `notify_emergency()` 未区分网络错误和业务错误，日志信息不明确 | 增加 `resp is None` 检查和业务错误日志记录 |
| 4 | 🟡 | `device_offline()` 未检查业务错误响应，无法判断下线是否真正成功 | 增加完整的业务错误响应检查和详细日志 |
| 5 | 🟡 | `recognize_medicine()` 错误处理不完善，OCR 失败/离线/AI 无响应均无反馈 | 增加分支处理：OCR失败提示、离线提示、AI响应检查 |
| 6 | 🟡 | `calculate_remaining_days()` 未处理 remaining 为负数的异常情况 | 增加 `total < 0` 检查，负数时重置为 0 |
| 7 | 🟡 | `save_config()` 临时文件在异常时可能残留 | 使用 `os.fsync()` 确保数据落盘，异常时清理临时文件 |
| 8 | 🟢 | `load_config()` 返回值未验证类型，非 dict 可能导致后续错误 | 增加 `isinstance(cfg, dict)` 检查 |
| 9 | 🟢 | `load_device_token()` 未验证 token 格式 | 增加长度检查（>10字符）和空格检查 |
| 10 | 🟢 | `init_network()` 异常日志不详细 | 增加异常类型信息，日志更可诊断 |
| 11 | 🟢 | `alert_loop()` 中断逻辑复杂，可读性差 | 简化代码结构，优化中断检查逻辑，增加离线响应优化 |
| 12 | 🟢 | `trigger_alert()`、`confirm_take()` 等函数 docstring 不完整 | 补充完整 docstring（Args、Returns） |

### 已完成的 Bug 修复（v2.29.4，共 10 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🟡 | `main_loop()` 中 `_do_sync` 函数在循环内重复创建，每次网络恢复时都生成新的函数对象 | 提取为嵌套函数 `_do_network_recovery_sync()`，仅定义一次，复用闭包 |
| 2 | 🟡 | `alert_loop()` 中局部变量 `max_retries` 与全局常量 `MAX_ALERT_RETRIES` 重复定义 | 移除局部变量，直接使用全局常量 `MAX_ALERT_RETRIES` |
| 3 | 🟡 | 魔法数字 `10*1024*1024` 和 `60` 未提取为命名常量 | 新增 `LOG_MAX_SIZE` 和 `_LOG_SIZE_CHECK_INTERVAL` 常量 |
| 4 | 🟡 | 音量转换 `/100` 硬编码，缺乏语义 | 新增 `_VOLUME_DIVISOR = 100` 常量，替换两处硬编码 |
| 5 | 🟡 | 注释引用错误行号（"第168行"实际为第192行） | 删除具体行号引用，改为通用描述 |
| 6 | 🟡 | `upload_log()` 中 `content` 字段使用三重嵌套三元表达式，可读性差 | 拆分为独立的 `content_field` 变量，逻辑清晰 |
| 7 | 🟢 | `ensure_dirs()`、`log()`、`set_system_volume()`、`calculate_remaining_days()`、`init_hardware()` 函数文档不完整 | 补充完整 docstring（Args、Returns、Raises） |
| 8 | 🟢 | 日志函数说明不完整 | 在 docstring 中增加日志轮转功能说明 |
| 9 | 🟢 | 音量参数边界检查逻辑优化 | 完善参数类型检查和范围校验 |
| 10 | 🟢 | 代码结构优化 | 减少冗余代码，统一命名规范 |

### 已完成的 Bug 修复（v2.29.3，共 30 项）

| # | 严重度 | 描述 | 修复方案 |
|---|--------|------|----------|
| 1 | 🔴 | `flush_local_logs()` 未检查业务错误标记（`_error`），业务失败被当作成功导致日志丢失 | 增加 `_error` 标记检查，`msg_ok` 和 `photo_ok` 判定包含业务错误检测 |
| 2 | 🔴 | `capture_photo()` 使用 `subprocess.run(shell=True)` 存在命令注入风险 | 改用列表形式 `["fswebcam", "-r", "640x480", "--no-banner", path]`，设置 `shell=False` |
| 3 | 🔴 | `set_system_volume()` 使用 `subprocess.run(shell=True)` 存在命令注入风险 | 改用列表形式 + `shell=False`，增加参数范围校验（0-100） |
| 4 | 🔴 | `notify_emergency()` 异常处理不完善，关键安全功能可能静默失败 | 增加完整异常捕获和业务错误检查 |
| 5 | 🔴 | `main()` 异常处理将完整 traceback 写入日志，泄露系统路径和变量信息 | 改为仅记录异常类型+简要信息，详细堆栈写入本地 `.crash` 文件 |
| 6 | 🔴 | `query_drug_by_ocr()` 和 `query_refill()` API 请求包含未定义的 `context` 字段 | 移除 `context` 字段，添加 `device_id` 字段符合 `AIQuestion` schema |
| 7 | 🔴 | `init_hardware()` 使用 `subprocess.run("which fswebcam", shell=True)` 存在命令注入风险 | 改用列表形式 `["which", "fswebcam"]`，设置 `shell=False` |
| 8 | 🔴 | `detect_volume_control()` 多处使用 `subprocess.run(shell=True)` 存在命令注入风险 | 全部改用列表形式 + `shell=False`，重构 `control_exists()` 使用列表参数 |
| 9 | 🟡 | `flush_local_logs()` 并发控制使用 `threading.Event`，无法确保严格互斥 | 改用 `threading.Lock` 的 `acquire(blocking=False)` 实现严格互斥 |
| 10 | 🟡 | `http_request()` 删除 `Content-Type` 头时使用 `del` 可能触发 `KeyError` | 改用 `hdrs.pop("Content-Type", None)` 安全删除 |
| 11 | 🟡 | `upload_log()` 照片大小检查使用魔法数字 512000 | 改用 `MAX_PHOTO_SIZE` 常量 |
| 12 | 🟡 | `MAX_ALERT_RETRIES` 常量重复定义（第 150/168 行） | 删除重复项，保留统一定义 |
| 13 | 🟡 | `low_stock_alert()` 使用 `threading.Timer` 强制恢复主页，覆盖用户紧急操作界面 | 改为仅恢复状态显示，不强制调用 `update_gui_home()` |
| 14 | 🟡 | `on_remind_button_pressed()` 未优先使用真实用药计划 | 优先从 `state["reminders"]` 获取第一条，无计划时降级为默认提醒 |
| 15 | 🟡 | `update_stock()` 未校验 `used_count` 参数类型和有效性 | 增加 `isinstance(used_count, (int, float))` 和 `used_count > 0` 检查 |
| 16 | 🟡 | `alert_loop()` 中 `interrupted` 变量在 `with lock:` 内设置但锁外检查，存在竞态条件 | 重构代码结构，确保中断标志在锁内设置后立即在锁外正确检查 |
| 17 | 🟡 | `update_stock()` 找不到对应药品时静默失败，无任何日志提示 | 添加 `found` 标志追踪，未找到时记录 WARNING 日志 |
| 18 | 🟡 | API 端点注释版本号过时（v2.29.2 → v2.29.3） | 更新注释中的版本号 |
| 19 | 🟢 | `calculate_remaining_days()` 使用普通除法可能导致库存预警偏少 | 使用向上取整算法 `max(0, -(-int(total) // daily))` |
| 20 | 🟢 | `update_stock()`、`device_offline()`、`ensure_dirs()` 等函数文档不完整 | 补充完整 docstring（Args、Returns、Raises） |
| 21 | 🟢 | GUI 颜色硬编码（`#FF4444`、`#333333`、`#666666` 等）分散在多处 | 新增颜色常量 `COLOR_TITLE`、`COLOR_ALERT_RED`、`COLOR_ALERT_DARK`、`COLOR_CLOCK_BLUE`、`COLOR_TEXT_DARK`、`COLOR_TEXT_GRAY`，统一管理 |
| 22 | 🟢 | `capture_photo()` 文件名未做安全校验，可能包含特殊字符 | 增加正则校验 `r'^[\w\.\-]+$'`，仅允许字母数字下划线点 |
| 23 | 🟢 | `capture_photo()` 未处理 `FileNotFoundError`（fswebcam 未安装） | 增加 `FileNotFoundError` 异常处理，提示安装 fswebcam |
| 24 | 🟢 | `device_offline()` 下线通知无异常保护 | 增加 `try/except` 保护，下线通知不再抛异常 |
| 25 | 🟢 | `main()` finally 块中 `device_offline()` 阻塞进程退出 | 改为 `threading.Thread` 异步执行 |
| 26 | 🟢 | `update_stock()` 未校验 `medicine_id` 有效性 | 增加 `if not medicine_id: return` 提前返回 |
| 27 | 🟢 | `update_gui_status()` 硬编码颜色值 | 改用颜色常量 `COLOR_ALERT_RED`、`COLOR_TEXT_DARK`、`COLOR_TITLE`、`COLOR_TEXT_GRAY` |
| 28 | 🟢 | `update_gui_home()` 硬编码颜色值 | 改用颜色常量 `COLOR_TITLE`、`COLOR_TEXT_GRAY`、`COLOR_TEXT_DARK`、`COLOR_CLOCK_BLUE` |
| 29 | 🟢 | `update_gui_reminder()` 硬编码颜色值 | 改用颜色常量 `COLOR_ALERT_DARK`、`COLOR_ALERT_RED`、`COLOR_TEXT_GRAY` |
| 30 | 🟢 | `log()` 函数每次调用都检查文件大小，高频调用时开销过大 | 添加 `_LOG_SIZE_CHECK_INTERVAL = 60` 秒检查间隔，减少系统调用开销 |

**新增常量汇总**（配置区）：

```python
# 常量定义
MAX_ALERT_RETRIES = 20           # 提醒最大重试次数（约 3 小时）
MAX_QUEUE_SIZE = 500             # 离线日志队列最大条数
MAX_PHOTO_SIZE = 512000          # 照片上传最大大小（500KB）
MAX_IMAGE_SIZE = 1048576         # 图片 base64 编码最大大小（1MB）
NETWORK_RECONNECT_INTERVAL = 30  # 网络恢复检查间隔（秒）
MAX_RECONNECT_FAILS = 5          # 网络恢复最大失败次数
STOCK_CHECK_INTERVAL = 6 * 3600  # 库存检查间隔（6 小时）
LOG_FLUSH_INTERVAL = 30 * 60     # 日志刷新间隔（30 分钟）
ALERT_TIMEOUT = 30               # 低库存告警超时（秒）
MISSED_MINUTES_THRESHOLD = 60    # 错过分钟数阈值
```

**API 规范一致性检查**：
- ✅ `POST /api/v1/public/device/message` — 用于 `upload_log()`、`notify_emergency()`
- ✅ `POST /api/v1/public/device/upload` — 用于照片上传
- ✅ `GET /api/v1/public/device/schedule/{device_id}` — 用于 `sync_reminders()`
- ✅ `POST /api/v1/public/device/offline` — 用于 `device_offline()`
- ✅ `POST /api/v1/public/ai/ask` — 用于 `query_refill()`、`recognize_medicine()`
- ✅ 所有请求正确携带 `X-Device-Token` Header（通过 `_auth_headers()` 自动注入）

## 版本与更新

本仓库 [`ha-ji-mi-MAN-BO/eating-medication`](https://github.com/ha-ji-mi-MAN-BO/eating-medication) 维护 `m10.py` 单文件版及其文档。配套网页端位于 [`diaoyunxi/eating-medication`](https://github.com/diaoyunxi/eating-medication)，建议二者同步更新以确保接口协议一致。

## 许可

本项目仅供学习和个人使用，最终解释权归 GitHub 账户 ha-ji-mi-MAN-BO 所有。