#!/usr/bin/env bash
# Stops the API (ComfyUI is shut down with it). Under pm2 it comes back on reboot;
# to remove it for good: pm2 delete qwen-api && pm2 save
[ -s /opt/nvm/nvm.sh ] && . /opt/nvm/nvm.sh
if command -v pm2 >/dev/null && pm2 describe qwen-api >/dev/null 2>&1; then
    pm2 stop qwen-api
else
    pkill -f "uvicorn app.main:app" && echo "stopped" || echo "not running"
fi
