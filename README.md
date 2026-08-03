# M10 智能服药提醒终端（单文件版）

> UniHiker 行空板 M10 智能药盒配套程序，与 [eating-medication](https://github.com/diaoyunxi/eating-medication) 网页端协同工作。
> 本仓库内为**单文件实现**（`m10.py`），与 `elderly_assistant/` 多文件版并列，互不依赖。

## 项目简介

`m10.py` 是部署在 DFRobot 行空板 M10 上的老人端主程序，承担用药提醒、语音播报、按钮交互、网络同步、紧急呼叫等核心功能。程序使用 Python 标准库 + UniHiker 原生 API（`unihiker` / `pinpong`）+ `pyttsx3` 离线 TTS，**不依赖** `cv2`、`requests`、`schedule` 等第三方库，便于在嵌入式设备上直接运行。

## 核心功能

| 模块 | 功能说明 |
|------|----------|
| 固定时间提醒 | 每日 **09:00 / 13:00 / 17:00** 自动触发服药提醒，跨天自动重置触发记录避免漏触发 |
| 按钮触发提醒 | 按下 **P27（B键）** 随时手动启动一次服药提醒 |
| 已吃药确认 | 按下 **P21（~A键）** 确认服药，停止提醒并返回主页 |
| 紧急呼叫 | 按下 **P28（A键）** 记录紧急呼叫日志（当前版本不鸣叫、不联网呼叫，待后续接入） |
| 主界面时钟 | 主页显示**年月日 + 时分秒**（系统时间），后台线程每秒刷新 |
| 语音播报 | `pyttsx3` 队列播报 + `espeak` 回退，配合 `amixer` 自动检测并控制 USB 扬声器音量 |
| 提醒音量递增 | 触发后每 10 分钟音量递增一档（30 → 100），避免老人忽略 |
| 蜂鸣器提示 | 优先使用 `pinpong` 板载蜂鸣器音效（BA_DING），回退到数字引脚控制 |
| 离线日志队列 | 网络断开时服药日志写入本地队列，恢复后自动回传服务端 |
| 余量监测 | 每 6 小时计算药品剩余天数，低于阈值语音告警并查询补货信息 |
| AI 药品识别 | 通过 `fswebcam` 拍照 + `pytesseract` OCR 识别药品名，并查询服务端药品库 |

## 硬件接线

| 引脚 | 设备 | 电平逻辑 |
|------|------|----------|
| `Pin.P25` | 蜂鸣器 | 优先使用板载音效，回退数字引脚高低电平 |
| `Pin.P21` | 已吃药按钮（~A键） | 按下高电平（1），松开低电平（0） |
| `Pin.P27` | 启动提醒按钮（B键） | 按下低电平（0） |
| `Pin.P28` | 紧急呼叫按钮（A键） | 按下低电平（0），仅记录日志 |

> 显示屏由 `unihiker.GUI` 自动接管，无需手动接线。

## 依赖说明

仅依赖 Python 标准库 + UniHiker 平台库，无需安装额外第三方包（`pyttsx3` 可选，缺失时自动回退到 `espeak`）：

```python
import time
from pinpong.board import Board
from dfrobot_huskylensv2 import *
```

系统级依赖（可选）：
- `fswebcam`：USB 摄像头拍照（缺失则跳过拍照功能）
- `tesseract` + `pytesseract`：药品包装 OCR 识别（缺失则跳过识别）
- `espeak`：TTS 回退引擎（`pyttsx3` 失败时使用）
- `amixer` / `aplay`：USB 扬声器音量控制与设备检测

## 配置项

主要常量集中在 `m10.py` 顶部的「配置区」，按实际环境修改：

```python
# 服务端地址与设备配对码
BASE_URL = "https://my-website.ccwu.cc/eating-medication/family"
PAIR_CODE = "275527387791320"
DEVICE_ID = "m10_" + PAIR_CODE

# WiFi（首次连接用，可被本地配置文件覆盖）
WIFI_SSID = "TP-LINK_5G_36DB"
WIFI_PASSWORD = "15756491077"

# 固定服药提醒时间
FIXED_REMINDER_TIMES = ["09:00", "13:00", "17:00"]

# 提醒音量递增参数
VOLUME_INITIAL = 30   # 初始音量
VOLUME_STEP = 15      # 每档增量
VOLUME_MAX = 100      # 最大音量
SNOOZE_MINUTES = 10   # 贪睡间隔（分钟）
```

运行时配置文件位于 `/root/medication_config.json`，可覆盖 WiFi 与药品库存信息；本地日志写入 `/root/medication_local.log`，离线日志队列写入 `/root/medication_log_queue.json`，服药照片保存到 `/root/medication_photos/`。

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
├── 配置区              # BASE_URL / 引脚 / 音量 / 提醒时间等常量
├── 工具函数            # 日志 / 配置读写 / WiFi / 音量控制
├── TTS 语音播报        # pyttsx3 队列 + espeak 回退
├── 网络通信            # urllib 封装 / 设备注册 / 提醒同步 / 日志上传
├── 提醒核心            # 固定提醒 / 服务端提醒 / 触发循环 / 确认服药
├── AI 药品识别         # 拍照 + OCR + 服务端查询
├── 余量监测            # 剩余天数计算 + 低库存告警
├── GUI 更新            # 主页时钟 / 状态提示 / 提醒界面
├── 按钮处理            # P21 确认 / P27 提醒 / P28 紧急
└── 初始化与主循环      # 硬件初始化 / 网络初始化 / 时钟线程 / 主循环
```

## 工作流程

1. **启动**：初始化硬件 → 初始化 TTS → 连接 WiFi → 注册设备 → 同步提醒 → 进入主界面
2. **主循环**（每秒）：
   - 每分钟检查固定时间提醒（09:00/13:00/17:00）与服务端提醒
   - 每小时同步服务端用药计划
   - 每 6 小时检查药品库存
   - 每 30 分钟回传离线日志队列
   - 每 30 秒探测网络恢复
3. **按钮线程**（每 0.1 秒轮询）：
   - P21 高电平 → 确认服药，停止提醒返回主页
   - P27 低电平 → 手动启动一次服药提醒
   - P28 低电平 → 记录紧急呼叫日志
4. **时钟线程**（每秒）：仅在主页模式刷新年月日时分秒，避免与提醒/状态界面冲突

## 与网页端的关系

`m10.py` 通过 HTTP 与 [eating-medication](https://github.com/diaoyunxi/eating-medication) 服务端通信：

| 接口 | 用途 |
|------|------|
| `POST /api/device/register` | 设备注册（携带 device_id + pair_code） |
| `GET /api/reminders` | 同步用药提醒与药品库存 |
| `POST /api/logs` | 上传服药/紧急/识别日志（含拍照 base64） |
| `POST /api/drug/query` | OCR 文本查询药品信息 |
| `POST /api/refill/query` | 查询补货最优价格 |
| `POST /api/emergency/notify` | 紧急呼叫通知家属 |

> ⚠️ **API 迁移说明**：当前 `m10.py` 使用旧版接口路径，与 `openapi.json` 定义的新版 `/api/v1/public/device/*` 接口存在差异，后续版本将逐步切换。

## 版本与更新

本仓库 [`ha-ji-mi-MAN-BO/eating-medication`](https://github.com/ha-ji-mi-MAN-BO/eating-medication) 维护 `m10.py` 单文件版及其文档。配套网页端位于 [`diaoyunxi/eating-medication`](https://github.com/diaoyunxi/eating-medication)，建议二者同步更新以确保接口协议一致。

## 许可

本项目仅供学习和个人使用，最终解释权归 GitHub 账户 ha-ji-mi-MAN-BO 所有。
