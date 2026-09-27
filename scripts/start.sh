#!/usr/bin/env bash
# Starts the API (which starts ComfyUI itself). Settings come from env vars or a .env file.
#   scripts/start.sh               run in the foreground
#   scripts/start.sh --background  run detached (log: logs/api.log), wait until healthy, print the Swagger link
#   scripts/start.sh --wait        don't start anything; wait until an already-starting API is healthy
#   (to keep it running across crashes and reboots use scripts/pm2.sh instead)
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
export PORT="${PORT:-8000}"

swagger_links() {
    # Vast.ai publishes container port P as $PUBLIC_IPADDR:$VAST_TCP_PORT_P.
    eval "$(grep -E '^(PUBLIC_IPADDR|VAST_TCP_PORT_[0-9]+)=' /etc/environment 2>/dev/null | sed 's/^/export /')"
    local var="VAST_TCP_PORT_$PORT"
    echo "Swagger (on this machine): http://localhost:$PORT/docs"
    if [ -n "${PUBLIC_IPADDR:-}" ] && [ -n "${!var:-}" ]; then
        echo "Swagger (public):          http://$PUBLIC_IPADDR:${!var}/docs"
    fi
}

wait_healthy() {  # $1: pid to watch (optional)
    echo -n "waiting for API on :$PORT "
    for _ in $(seq 1 180); do
        if curl -sf "localhost:$PORT/health" >/dev/null; then echo " up"; swagger_links; exit 0; fi
        [ -z "${1:-}" ] || kill -0 "$1" 2>/dev/null || break
        echo -n "."; sleep 2
    done
    echo " FAILED"; tail -30 logs/api.log logs/pm2-error.log 2>/dev/null; tail -30 logs/comfyui.log 2>/dev/null; exit 1
}

case "${1:-}" in
    --background) mkdir -p logs; nohup "$0" > logs/api.log 2>&1 & wait_healthy $! ;;
    --wait) wait_healthy ;;
esac

swagger_links
# Single worker on purpose: the process owns the ComfyUI engine and the GPU.
exec .venv/bin/uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "$PORT" --workers 1
