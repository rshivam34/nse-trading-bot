#!/usr/bin/env bash
# NSE Trading Bot - VM bootstrap.
# Runs on a fresh Ubuntu 22.04 ARM/x86 VM. Idempotent (safe to re-run).
# After this finishes, .env + firebase-credentials.json must be SCP'd to /home/ubuntu/nse-trading-bot/backend/

set -euo pipefail

REPO_URL="git@github.com:rshivam34/nse-trading-bot.git"
REPO_HTTPS="https://github.com/rshivam34/nse-trading-bot.git"
HOME_DIR="/home/ubuntu"
REPO_DIR="${HOME_DIR}/nse-trading-bot"
VENV_DIR="${REPO_DIR}/.venv"

echo "==> Setting timezone to Asia/Kolkata"
sudo timedatectl set-timezone Asia/Kolkata

echo "==> Updating apt + installing system packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    python3 python3-pip python3-venv python3-dev \
    git curl ca-certificates \
    build-essential libssl-dev libffi-dev \
    pkg-config

echo "==> Python version on this VM:"
python3 --version

echo "==> Cloning repo (HTTPS, public/private both work via deploy key later)"
if [ ! -d "$REPO_DIR" ]; then
    cd "$HOME_DIR"
    # Try HTTPS first (works for public repos or with PAT)
    git clone "$REPO_HTTPS" || {
        echo "HTTPS clone failed - repo is private. Set up an SSH deploy key on this VM and re-run, or push the repo manually via scp."
        exit 1
    }
fi

echo "==> Creating venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

echo "==> Installing Python deps"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$REPO_DIR/backend/requirements.txt"

echo "==> Creating logs directory"
mkdir -p "$REPO_DIR/backend/logs"

echo "==> Checking for required secrets"
MISSING=0
for f in .env firebase-credentials.json; do
    if [ ! -f "$REPO_DIR/backend/$f" ]; then
        echo "  MISSING: $REPO_DIR/backend/$f - SCP it from the laptop"
        MISSING=1
    fi
done

if [ "$MISSING" -eq 1 ]; then
    echo
    echo "HALTED. Copy these from the laptop, then re-run this script:"
    echo "  scp -i secrets/oracle-vm-private.key backend/.env ubuntu@<VM_IP>:nse-trading-bot/backend/"
    echo "  scp -i secrets/oracle-vm-private.key backend/firebase-credentials.json ubuntu@<VM_IP>:nse-trading-bot/backend/"
    exit 1
fi

echo "==> Installing systemd unit files"
sudo cp "$REPO_DIR/deploy/systemd/"*.service /etc/systemd/system/
sudo cp "$REPO_DIR/deploy/systemd/"*.timer /etc/systemd/system/
sudo systemctl daemon-reload

echo "==> Installing logrotate config"
sudo cp "$REPO_DIR/deploy/logrotate-nse-bot" /etc/logrotate.d/nse-bot

echo "==> Enabling timers (will start firing on schedule)"
sudo systemctl enable nse-bot.timer
sudo systemctl enable nse-bot-stop.timer
sudo systemctl enable nse-eod-report.timer

echo "==> Starting timers now"
sudo systemctl start nse-bot.timer
sudo systemctl start nse-bot-stop.timer
sudo systemctl start nse-eod-report.timer

echo
echo "============================================"
echo "  VM bootstrap complete."
echo "============================================"
echo
echo "Next steps:"
echo "  1. Test paper-mode bot manually:"
echo "     cd $REPO_DIR/backend && $VENV_DIR/bin/python main.py --paper"
echo "  2. Test EOD reporter (after Telegram token is in .env):"
echo "     $VENV_DIR/bin/python $REPO_DIR/backend/eod_report.py --discover"
echo "     $VENV_DIR/bin/python $REPO_DIR/backend/eod_report.py --test"
echo "  3. Check timer schedule:"
echo "     systemctl list-timers --all | grep nse"
echo "  4. View bot logs:"
echo "     tail -f $REPO_DIR/backend/logs/systemd-bot.log"
echo "  5. Manual stop / start:"
echo "     sudo systemctl stop nse-bot.service"
echo "     sudo systemctl start nse-bot.service"
echo
