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

WiFi 连接在**初始化时执行**，SSID 和密码通过环境变量配置（`m10.py` 第 252-254 行）：

```python
_WIFI_SSID = os.environ.get("WIFI_SSID", "666")
_WIFI_PASSWORD = os.environ.get("WIFI_PASSWORD", "15756491077")
```

**生产环境建议**：设置 `WIFI_SSID` 和 `WIFI_PASSWORD` 环境变量，避免在代码中硬编码凭据。

```bash
# 设置环境变量后运行
export WIFI_SSID="your_ssid"
export WIFI_PASSWORD="your_password"
python3 m10.py
```

`init_network()` 通过 `wifi_manager.is_wifi_connected()` 查询连接状态。

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
| API 版本 | v2.28.0（当前修复版：v2.34.0） |
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