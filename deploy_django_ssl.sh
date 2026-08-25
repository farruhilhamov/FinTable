#!/usr/bin/env bash
# ============================================================
# Django VPS Deploy Script (root user, self-signed SSL, 8443->8000)
# ============================================================
# Run as root:  sudo bash deploy_django_ssl.sh
#
# EDIT THESE 4 VARIABLES BEFORE RUNNING
# ============================================================
PROJECT_DIR="/root/FinTable"        # folder containing manage.py
PROJECT_NAME="FinTable"             # python package containing wsgi.py
WSGI_MODULE="fintable.wsgi:application"   # module:attribute for gunicorn (lowercase package name!)
DOMAIN_OR_IP="185.118.133.79"        # server IP or domain (for cert CN + ALLOWED_HOSTS)
GIT_REMOTE="https://github.com/farruhilhamov/FinTable.git"   # or "" to skip git
VENV_DIR="$PROJECT_DIR/venv"
# ============================================================

set -e

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root. Use: sudo bash $0"
   exit 1
fi

echo ">>> [1/9] Updating system and installing packages..."
apt update -y
apt install -y python3-pip python3-venv python3-dev libpq-dev nginx openssl curl git

echo ">>> [2/9] Cloning / pulling code from GitHub..."
cd "$PROJECT_DIR" 2>/dev/null || { mkdir -p "$PROJECT_DIR"; cd "$PROJECT_DIR"; }
if [ -n "$GIT_REMOTE" ]; then
    if [ -d "$PROJECT_DIR/.git" ]; then
        git fetch origin
        git checkout -f -B main origin/main
    else
        git init
        git remote add origin "$GIT_REMOTE"
        git fetch origin
        git checkout -f -B main origin/main
    fi
    echo "   Code updated from: $GIT_REMOTE (branch main)"
else
    echo "   GIT_REMOTE empty - skipping git, using files as-is."
fi

echo ">>> [3/9] Creating virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install django gunicorn
if [ -f "$PROJECT_DIR/requirements.txt" ]; then
    pip install -r "$PROJECT_DIR/requirements.txt"
fi
deactivate

echo ">>> [4/9] Running Django migrations and collectstatic..."
cd "$PROJECT_DIR"
"$VENV_DIR/bin/python" manage.py migrate --noinput || echo "WARNING: migrate failed, check DB settings"
"$VENV_DIR/bin/python" manage.py collectstatic --noinput || echo "WARNING: collectstatic failed"

echo ">>> [5/9] Generating self-signed SSL certificate..."
mkdir -p /etc/nginx/ssl
if [ ! -f /etc/nginx/ssl/selfsigned.crt ]; then
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/selfsigned.key \
        -out /etc/nginx/ssl/selfsigned.crt \
        -subj "/C=XX/ST=State/L=City/O=SelfSigned/CN=${DOMAIN_OR_IP}"
    chmod 600 /etc/nginx/ssl/selfsigned.key
fi

echo ">>> [6/9] Creating systemd service for Gunicorn (running as root)..."
cat > /etc/systemd/system/gunicorn.service <<EOF
[Unit]
Description=Gunicorn daemon for ${PROJECT_NAME}
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=${PROJECT_DIR}
ExecStart=${VENV_DIR}/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 ${WSGI_MODULE}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo ">>> [7/9] Creating Nginx config (8443 SSL -> 8000, static from staticfiles/)..."
cat > /etc/nginx/sites-available/${PROJECT_NAME} <<EOF
server {
    listen 8443 ssl;
    server_name ${DOMAIN_OR_IP};

    ssl_certificate /etc/nginx/ssl/selfsigned.crt;
    ssl_certificate_key /etc/nginx/ssl/selfsigned.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    client_max_body_size 20M;

    location /static/ {
        alias ${PROJECT_DIR}/staticfiles/;
    }

    location /media/ {
        alias ${PROJECT_DIR}/media/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/${PROJECT_NAME} /etc/nginx/sites-enabled/${PROJECT_NAME}
rm -f /etc/nginx/sites-enabled/default

echo ">>> [8/9] Opening firewall port 8443..."
if command -v ufw >/dev/null 2>&1; then
    ufw allow 8443/tcp
    ufw --force enable
fi

echo ">>> [9/9] Starting services..."
nginx -t
systemctl daemon-reload
systemctl enable gunicorn
systemctl restart gunicorn
systemctl enable nginx
systemctl restart nginx

echo ""
echo "============================================================"
echo " Deployment complete."
echo " Visit: https://${DOMAIN_OR_IP}:8443"
echo " Browser will show a security warning (self-signed cert) -"
echo " this is expected. Click 'Advanced -> Proceed' to continue."
echo ""
echo " Useful commands:"
echo "   systemctl status gunicorn"
echo "   systemctl status nginx"
echo "   journalctl -u gunicorn -f"
echo ""
echo " Next updates: run  bash deploy_update.sh  (one command)"
echo "============================================================"