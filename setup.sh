#!/bin/bash
set -euo pipefail

DEPLOY_DIR="/opt/m10"
REPO_URL="https://github.com/ha-ji-mi-MAN-BO/eating-medication.git"   # 实际仓库名可调整
SERVICE_NAME="m10"

# 1. 安装系统依赖
apt update -y && apt install -y git python3 python3-venv python3-pip

# 2. 克隆或更新代码
if [ -d "$DEPLOY_DIR/.git" ]; then
    git -C "$DEPLOY_DIR" pull
else
    git clone "$REPO_URL" "$DEPLOY_DIR"
fi

# 3. 创建虚拟环境并安装 m10 依赖（m10 依赖 unihiker, pinpong, pyttsx3 等）
cd "$DEPLOY_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
# 如果 m10.py 有独立的 requirements.txt，请一并安装；没有则手动列出
pip install unihiker pinpong pyttsx3
# 其他可能需要：pytest（测试用，可不装）
deactivate

echo "部署完成！"