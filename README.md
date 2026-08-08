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
# 服务端地址与设备配对码
BASE_URL = "https://my-website.ccwu.cc/eating-medication/family"
PAIR_CODE = "275527387791320"
DEVICE_ID = "m10_" + PAIR_CODE

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

### 运行时文件

| 路径 | 用途 |
|------|------|
| `/root/medication_config.json` | 药品库存等运行时配置（不再包含 WiFi） |
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
├── 配置区              # BASE_URL / 配对码 / API 端点 / 引脚 / 音量 / 提醒时间
├── 全局状态            # state 字典（在线/提醒/库存/活跃提醒等）
├── 工具函数            # 日志 / 配置读写 / 网络探测 / 音量控制
├── TTS 语音播报        # pyttsx3 队列 + espeak 回退 + 音量联动
├── 网络通信            # urllib 封装 / 设备注册 / 提醒同步 / 日志上传 / 紧急呼叫
├── 提醒核心            # 固定提醒 / 服务端提醒 / trigger_alert / alert_loop / 服药确认
├── AI 药品识别         # fswebcam 拍照 + pytesseract OCR + 服务端查询
├── 余量监测            # 剩余天数计算 + 低库存告警
├── GUI 更新            # 主页时钟 / 状态提示 / 提醒界面（三种模式）
├── 按钮处理            # P21 确认 / P27 提醒 / P28 紧急
└── 初始化与主循环      # 硬件初始化 / 网络初始化 / 时钟线程 / 按钮线程 / 主循环
```

## 工作流程

### 启动流程

1. **模块加载** → `WiFiManager.connect_wifi()` 自动连接 WiFi
2. **初始化硬件** → `Board().begin()` + 蜂鸣器 + 按钮 + GUI
3. **初始化 TTS** → `pyttsx3` 引擎 + 后台播报线程
4. **初始化网络** → `wifi_manager.is_wifi_connected()` 检查 → 在线则注册设备/同步提醒/刷新日志
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
| 已吃药（~A） | P21 | 按下高电平（1） | 确认服药 → 拍照上传 → 扣减库存 → 返回主页 |
| 启动提醒（B） | P27 | 按下低电平（0） | 立即启动一次服药提醒（测试药品 1片） |
| 紧急呼叫（A） | P28 | 按下低电平（0） | 记录紧急日志 → 显示"已记录紧急呼叫" |

### 时钟线程（每秒一次）

仅在 `_gui_mode == "home"` 时刷新主页日期与时分秒文本对象，避免与提醒/状态界面冲突。

## 与网页端的关系

`m10.py` 通过 HTTP 与 [eating-medication](https://github.com/diaoyunxi/eating-medication) 服务端通信：

| 接口 | 方法 | 用途 |
|------|------|------|
| `/api/device/register` | POST | 设备注册（携带 device_id + pair_code） |
| `/api/reminders` | GET | 同步用药提醒与药品库存 |
| `/api/logs` | POST | 上传服药/紧急/识别日志（含拍照 base64） |
| `/api/drug/query` | POST | OCR 文本查询药品信息 |
| `/api/refill/query` | POST | 查询补货最优价格 |
| `/api/emergency/notify` | POST | 紧急呼叫通知家属 |

> ⚠️ **API 迁移说明**：当前 `m10.py` 使用旧版接口路径，与 `openapi.json` 定义的新版 `/api/v1/public/device/*` 接口存在差异，后续版本将逐步切换。

## 版本与更新

本仓库 [`ha-ji-mi-MAN-BO/eating-medication`](https://github.com/ha-ji-mi-MAN-BO/eating-medication) 维护 `m10.py` 单文件版及其文档。配套网页端位于 [`diaoyunxi/eating-medication`](https://github.com/diaoyunxi/eating-medication)，建议二者同步更新以确保接口协议一致。

## 许可

本项目仅供学习和个人使用，最终解释权归 GitHub 账户 ha-ji-mi-MAN-BO 所有。