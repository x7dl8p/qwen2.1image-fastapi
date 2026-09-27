#!/usr/bin/env bash
# Runs the API under PM2: restarted if it crashes, and started again after a machine/container restart.
#   scripts/pm2.sh      (re)start + save + enable on boot, then print the Swagger link
# Afterwards: pm2 status | pm2 logs qwen-api | pm2 restart qwen-api | pm2 stop qwen-api
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

[ -s /opt/nvm/nvm.sh ] && . /opt/nvm/nvm.sh          # Vast images ship node via nvm
command -v node >/dev/null || { echo "Node.js is required for PM2 (without it use: scripts/start.sh --background)"; exit 1; }
command -v pm2 >/dev/null || { echo "== installing pm2"; npm install -g pm2 >/dev/null; }
NODE_DIR="$(dirname "$(command -v node)")"

echo "== (re)starting qwen-api under pm2"
pm2 delete qwen-api >/dev/null 2>&1 || true
pkill -f "uvicorn app.main:app" 2>/dev/null && sleep 5 || true   # a copy started without pm2
pkill -f "$ROOT/ComfyUI/main.py" 2>/dev/null || true            # its orphaned engine, if any
mkdir -p logs
pm2 start ecosystem.config.js
pm2 save

echo "== start on boot"
if [ -d /run/systemd/system ]; then
    pm2 startup systemd -u "$(id -un)" --hp "$HOME"
elif [ -d /etc/supervisor/conf.d ] && command -v supervisorctl >/dev/null; then
    # Containers without systemd (e.g. Vast.ai): supervisor runs at boot, so let it resurrect pm2.
    cat > /etc/supervisor/conf.d/pm2-resurrect.conf <<EOF
[program:pm2-resurrect]
command=/bin/bash -c 'export PATH="$NODE_DIR:\$PATH"; pm2 resurrect'
autostart=true
autorestart=false
startsecs=0
stdout_logfile=/dev/stdout
redirect_stderr=true
stdout_logfile_maxbytes=0
EOF
    supervisorctl reread >/dev/null && supervisorctl update >/dev/null
    echo "   supervisor will run 'pm2 resurrect' at boot"
else
    echo "   WARNING: no systemd or supervisor found - run 'pm2 resurrect' at boot yourself (e.g. @reboot in crontab)"
fi

scripts/start.sh --wait
