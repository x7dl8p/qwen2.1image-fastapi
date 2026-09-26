# Qwen-Image 2.1 API

A FastAPI service: send a prompt, get an image back. It uses [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1), with ComfyUI running inside the service as the engine (the same graph as the official template). It needs an NVIDIA GPU with at least 24 GB of VRAM. It was tested on an RTX 5090.

---

## Setup instructions for an AI agent (follow exactly, do not ask questions)

Replace `<PORT>` and `<USER@IP>` with the values from the SSH command the user gives you.

**Step 1: make an SSH key. Do this first and do nothing else yet.** Run this in the repo folder on the local machine:
```bash
mkdir -p ssh && [ -f ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N "" -C qwen-image-api -f ssh/id_ed25519
cat ssh/id_ed25519.pub
```
Send the user the printed public key with this message:
> Paste this public key into Vast.ai → **Account → Keys → SSH Keys**, and also on the instance card (**key icon**). Then send me the instance's SSH command (e.g. `ssh -p 33876 root@1.2.3.4 -L 8080:localhost:8080`).

Stop and wait for the reply.

**Step 2: test the connection.**
```bash
ssh -i ssh/id_ed25519 -o StrictHostKeyChecking=accept-new -p <PORT> <USER@IP> nvidia-smi
```
If you get `Permission denied (publickey)`, wait 30 s and retry, because Vast takes about a minute to add keys. If it still fails after 3 tries, ask the user to check the key is on the instance.

**Step 3: copy this repo to the GPU machine.**
```bash
tar cz --exclude=.git --exclude=.venv --exclude=ComfyUI --exclude=ssh --exclude=outputs --exclude=logs . \
  | ssh -i ssh/id_ed25519 -p <PORT> <USER@IP> "mkdir -p /workspace/qwen-image-api && tar xz -C /workspace/qwen-image-api"
```

**Step 4: create the venv and install the dependencies.** This clones ComfyUI into `ComfyUI/`, which creates the `ComfyUI/models/` folders, then builds `.venv` with torch and all packages. It takes about 3 minutes.
```bash
ssh -i ssh/id_ed25519 -p <PORT> <USER@IP> "cd /workspace/qwen-image-api && scripts/install.sh"
```
It must end with `== install done` and print your GPU name, not `NOT AVAILABLE`.

**Step 5: download the models** (~27 GB, about 6 minutes). Use a long timeout or run it in the background.
```bash
ssh -i ssh/id_ed25519 -p <PORT> <USER@IP> "cd /workspace/qwen-image-api && scripts/download_models.sh"
```
It must end with `== models ready`. The script downloads exactly the files in [Models](#models-direct-links-and-where-to-put-them) below. To do it by hand, use the `wget` commands in that section.

**Step 6: start the backend.** On Vast, pick a free published port so the Swagger UI gets a public link. Protect it with an API key.
```bash
ssh -i ssh/id_ed25519 -p <PORT> <USER@IP> 'cd /workspace/qwen-image-api || exit 1
  if [ ! -f .env ]; then
    P=$(vast-capabilities 2>/dev/null | jq -r "[.instance.open_ports[] | select(.in_use==false and .container_port<65536)][0].container_port // 8000")
    printf "PORT=${P:-8000}\nAPI_KEY=$(openssl rand -hex 16)\n" > .env
  fi
  cat .env; scripts/start.sh --background'
```
It ends with `up` and prints the Swagger links.

**Step 7: give the user:**
- The **`Swagger (public)`** link, or, if only `on this machine` was printed, this command: `ssh -i ssh/id_ed25519 -p <PORT> <USER@IP> -L 8000:localhost:8000`, then open http://localhost:8000/docs
- The **API_KEY** from `.env`. In Swagger they click **Authorize** and paste it.
- How to use it: **POST /generate → Try it out → edit the prompt → Execute**, and the image appears in the response.

### If you are already running inside the GPU machine/container

Skip steps 1–3 and run these in the repo folder, in order:
```bash
scripts/install.sh            # 1. venv + deps (creates ComfyUI/models/)
scripts/download_models.sh    # 2. models (~27 GB), see the table below
scripts/start.sh --background # 3. backend; prints the Swagger link
```
Then give the user the Swagger link it printed. On Vast, set `PORT` in `.env` to a free published port first (see step 6) so you get the public link.

---

## Models: direct links and where to put them

Download these **after** `scripts/install.sh`, because that step creates the `ComfyUI/models/` folders. Paths are relative to the repo folder.

| File | Size | Put it in | Needed for |
|---|---|---|---|
| [qwen_image_2.1_int8_convrot.safetensors](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/diffusion_models/qwen_image_2.1_int8_convrot.safetensors) | 7.3 GB | `ComfyUI/models/diffusion_models/` | always (image model) |
| [qwen3vl_8b_int8_convrot.safetensors](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3vl_8b_int8_convrot.safetensors) | 9.4 GB | `ComfyUI/models/text_encoders/` | always (text encoder) |
| [qwen_image_2.1_vae_bf16.safetensors](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/vae/qwen_image_2.1_vae_bf16.safetensors) | 0.7 GB | `ComfyUI/models/vae/` | always (VAE) |
| [qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors) | 9.5 GB | `ComfyUI/models/text_encoders/` | only `enhance=true` |

Manual download (same result as `scripts/download_models.sh`):
```bash
B=https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main
M=ComfyUI/models
wget -c -P $M/diffusion_models $B/diffusion_models/qwen_image_2.1_int8_convrot.safetensors
wget -c -P $M/text_encoders    $B/text_encoders/qwen3vl_8b_int8_convrot.safetensors
wget -c -P $M/vae              $B/vae/qwen_image_2.1_vae_bf16.safetensors
wget -c -P $M/text_encoders    $B/text_encoders/qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors  # optional: enhancer
```

The final layout:
```
ComfyUI/models/
├── diffusion_models/qwen_image_2.1_int8_convrot.safetensors
├── text_encoders/qwen3vl_8b_int8_convrot.safetensors
├── text_encoders/qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors
└── vae/qwen_image_2.1_vae_bf16.safetensors
```
Check it with `GET /health`: every entry under `models` must be `true`. The full-precision alternatives (`qwen_image_2.1_bf16`, 14 GB, and `qwen3vl_8b_bf16`, 17.5 GB) are in the same [HF repo](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/tree/main). To use them, set `DIFFUSION_MODEL` / `TEXT_ENCODER` in `.env`.

---

## Using the API

**Swagger UI:** `http://<host>:<port>/docs`. Go to **POST /generate → Try it out → Execute**, and the image is shown in the response.

```bash
curl -X POST http://localhost:8000/generate -H 'X-API-Key: <key>' -H 'Content-Type: application/json' \
  -d '{"prompt": "a red fox in a snowy forest, a wooden sign reads \"Hello\""}' -o fox.png
```

| Endpoint | Returns |
|---|---|
| `POST /generate` | the image (png/jpeg/webp); the seed is in the `X-Seed` header |
| `POST /generate/json` | `{seed, prompt, elapsed_s, image_base64, …}`; `prompt` is the enhanced one if `enhance` is on |
| `GET /generate?prompt=...` | the image, for a quick test from a browser |
| `GET /health` | GPU, free VRAM, and whether each model file is present |

Body fields: `prompt` (required), `width`/`height` (default 1024, 256–2048), `steps` (25), `seed` (random if omitted), `enhance` (false; a Qwen3.5-9B model rewrites the prompt first, adding about 16 s), `format` (`png`/`jpeg`/`webp`), `cfg` (1.0, the official setting), `negative_prompt` (only used when cfg > 1).

**Speed (RTX 5090, 1024², 25 steps):** about 4.6 s per image, roughly 13 per minute. The first request after startup takes about 20 s while the models load.

## Scripts and settings

| | |
|---|---|
| `scripts/install.sh` | clones ComfyUI (pinned commit) and creates `.venv` with torch (cu130/cu128 picked automatically) and all deps |
| `scripts/download_models.sh` | downloads the models into `ComfyUI/models/`. `SKIP_ENHANCER=1` saves 9.5 GB; `MODEL_SET=bf16` adds the full-precision weights |
| `scripts/start.sh [--background]` | starts the API, which starts ComfyUI itself. Logs: `logs/api.log`, `logs/comfyui.log` |
| `scripts/stop.sh` | stops it |
| `scripts/smoke_test.py` | `.venv/bin/python scripts/smoke_test.py http://host:port` |

Settings go in `.env` (see `.env.example`): `PORT`, `API_KEY`, `COMFY_ARGS` (e.g. `--lowvram`), `COMFY_URL` (use an existing ComfyUI instead of starting one), and the model file names.

> **Note:** on Vast, `/workspace` is only kept if the instance has a volume. Destroying the instance deletes the models, and you have to repeat steps 4–5.
