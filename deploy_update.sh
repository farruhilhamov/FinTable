#!/usr/bin/env bash
# ============================================================
# Quick update for FinTable on VPS (one command)
# ============================================================
# Usage:  sudo bash deploy_update.sh
# ============================================================
set -e

# --- Config (keep in sync with deploy_django_ssl.sh) ---
PROJECT_DIR="/root/FinTable"
VENV_DIR="$PROJECT_DIR/venv"
GIT_REMOTE="https://github.com/farruhilhamov/FinTable.git"
# ============================================================

if [[ $EUID -ne 0 ]]; then
   echo "Run as root: sudo bash $0"
   exit 1
fi

if [ ! -d "$PROJECT_DIR/.git" ]; then
   echo "No git repo at $PROJECT_DIR - run deploy_django_ssl.sh first."
   exit 1
fi

echo ">>> [1/5] Pulling latest code..."
cd "$PROJECT_DIR"
git fetch origin
git checkout -f -B main origin/main

echo ">>> [2/5] Installing dependencies..."
source "$VENV_DIR/bin/activate"
if [ -f requirements.txt ]; then
    pip install -r requirements.txt
fi
deactivate

echo ">>> [3/5] Migrations + collectstatic..."
"$VENV_DIR/bin/python" manage.py migrate --noinput || echo "WARNING: migrate failed"
"$VENV_DIR/bin/python" manage.py collectstatic --noinput || echo "WARNING: collectstatic failed"

echo ">>> [4/5] Restarting services..."
systemctl daemon-reload
systemctl restart gunicorn
systemctl reload nginx || systemctl restart nginx

echo ">>> [5/5] Done."
echo "App updated. Visit https://$(hostname -I | awk '{print $1}') or your IP:8443"