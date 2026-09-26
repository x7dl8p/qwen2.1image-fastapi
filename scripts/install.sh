#!/usr/bin/env bash
# Installs ComfyUI (pinned) + all Python deps into ./.venv.
#   COMFYUI_REF   ComfyUI commit/branch to use (default: the tested commit below)
#   TORCH_INDEX   override the PyTorch wheel index (auto: cu130 if driver supports CUDA 13, else cu128)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

COMFYUI_REF="${COMFYUI_REF:-88ab4a06566454ad89db8f0bedb970d6c08cd1b7}"   # tested 2026-09-25
COMFY_DIR="${COMFY_DIR:-$ROOT/ComfyUI}"
VENV="$ROOT/.venv"

echo "== ComfyUI @ $COMFYUI_REF -> $COMFY_DIR"
[ -d "$COMFY_DIR/.git" ] || git clone -q https://github.com/Comfy-Org/ComfyUI "$COMFY_DIR"
git -C "$COMFY_DIR" fetch -q origin
git -C "$COMFY_DIR" checkout -q "$COMFYUI_REF"
git -C "$COMFY_DIR" log -1 --format='   %h %cd'

echo "== venv -> $VENV"
if command -v uv >/dev/null; then
    [ -x "$VENV/bin/python" ] || uv venv -q --python 3.12 "$VENV"
    PIP=(uv pip install -q --python "$VENV/bin/python")
else
    [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
    "$VENV/bin/python" -m pip install -q --upgrade pip
    PIP=("$VENV/bin/python" -m pip install -q)
fi

if [ -z "${TORCH_INDEX:-}" ]; then
    DRIVER_CUDA=$(nvidia-smi 2>/dev/null | grep -oP 'CUDA Version: \K[0-9]+' || echo 0)
    if [ "$DRIVER_CUDA" -ge 13 ]; then TORCH_INDEX=https://download.pytorch.org/whl/cu130
    else TORCH_INDEX=https://download.pytorch.org/whl/cu128; fi
fi
echo "== torch from $TORCH_INDEX"
"${PIP[@]}" torch torchvision torchaudio --index-url "$TORCH_INDEX"

echo "== ComfyUI + API requirements"
"${PIP[@]}" -r "$COMFY_DIR/requirements.txt" -r "$ROOT/requirements.txt"

"$VENV/bin/python" -c 'import torch; ok = torch.cuda.is_available(); print("   torch", torch.__version__, "| GPU:", torch.cuda.get_device_name(0) if ok else "NOT AVAILABLE")'
echo "== install done. Next: scripts/download_models.sh"
