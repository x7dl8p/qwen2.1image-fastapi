#!/usr/bin/env bash
# Stops the API started with scripts/start.sh (ComfyUI is shut down with it).
pkill -f "uvicorn app.main:app" && echo "stopped" || echo "not running"
