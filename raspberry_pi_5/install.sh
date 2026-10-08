#!/usr/bin/env bash
set -e

echo "==========================================="
echo " SkyGuard Streamer - Raspberry Pi 5 Installer"
echo "==========================================="

# Move to project directory
cd "$(dirname "$0")"

echo "[*] Updating package lists..."
sudo apt-get update

echo "[*] Installing system dependencies..."
sudo apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    v4l-utils \
    gstreamer1.0-tools \
    ffmpeg \
    libffi-dev \
    libssl-dev

echo "[*] Checking camera tools..."

if ! command -v rpicam-hello >/dev/null 2>&1; then
    sudo apt-get install -y rpicam-apps || \
    sudo apt-get install -y rpicam-apps-lite || true
fi

echo "[*] Creating Python virtual environment..."

if [ -d ".venv" ]; then
    rm -rf .venv
fi

python3 -m venv .venv

source .venv/bin/activate

echo "[*] Upgrading pip/setuptools/wheel..."
python -m pip install --upgrade pip setuptools wheel

echo "[*] Installing Python requirements..."

pip install -r requirements.txt

echo "[*] Camera detection test..."

if command -v rpicam-hello >/dev/null 2>&1; then
    rpicam-hello --list-cameras || true
fi

echo "[*] Creating systemd service..."

SERVICE_FILE="/etc/systemd/system/skyguard-streamer.service"
WORK_DIR="$(pwd)"
USER_NAME="$(whoami)"

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=SkyGuard Video Streamer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$WORK_DIR

Environment=PYTHONUNBUFFERED=1

ExecStart=$WORK_DIR/.venv/bin/python $WORK_DIR/run.py

Restart=always
RestartSec=5

SupplementaryGroups=video

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable skyguard-streamer.service

echo ""
echo "==========================================="
echo " Installation Complete!"
echo "==========================================="
echo ""
echo "Python:"
python --version
echo ""
echo "Architecture:"
uname -m
echo ""
echo "Manual start:"
echo "  source .venv/bin/activate"
echo "  python run.py"
echo ""
echo "Service start:"
echo "  sudo systemctl start skyguard-streamer.service"
echo ""
echo "Service status:"
echo "  sudo systemctl status skyguard-streamer.service"
echo ""
echo "Live logs:"
echo "  journalctl -u skyguard-streamer -f"
echo ""
echo "Camera test:"
echo "  rpicam-hello"
echo ""
echo "==========================================="