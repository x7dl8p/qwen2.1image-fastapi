#!/usr/bin/env bash
# Downloads Qwen-Image 2.1 files from Comfy-Org/Qwen-Image-2.1 into ComfyUI/models/.
#   SKIP_ENHANCER=1   skip the 9.5 GB prompt-enhancer model (enhance=true won't work)
#   MODEL_SET=bf16    also fetch the full-precision diffusion model + text encoder
#   HF_TOKEN          optional, for faster/authenticated downloads
set -euo pipefail
cd "$(dirname "$0")/.."
COMFY_DIR="${COMFY_DIR:-$PWD/ComfyUI}"
HF="$PWD/.venv/bin/hf"
[ -x "$HF" ] || { echo "run scripts/install.sh first"; exit 1; }

FILES=(
    diffusion_models/qwen_image_2.1_int8_convrot.safetensors      # 7.3 GB
    text_encoders/qwen3vl_8b_int8_convrot.safetensors             # 9.4 GB
    vae/qwen_image_2.1_vae_bf16.safetensors                       # 0.7 GB
)
[ "${SKIP_ENHANCER:-0}" = 1 ] || FILES+=(text_encoders/qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors)  # 9.5 GB
[ "${MODEL_SET:-int8}" = bf16 ] && FILES+=(diffusion_models/qwen_image_2.1_bf16.safetensors text_encoders/qwen3vl_8b_bf16.safetensors)

# Repo layout matches ComfyUI/models/, so download straight into it (already-present files are skipped).
"$HF" download Comfy-Org/Qwen-Image-2.1 "${FILES[@]}" --local-dir "$COMFY_DIR/models"
rm -rf "$COMFY_DIR/models/.cache"
echo "== models ready. Next: scripts/start.sh"
