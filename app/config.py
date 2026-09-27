import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


@dataclass(frozen=True)
class Settings:
    # ComfyUI engine. If COMFY_URL is set, attach to that server instead of spawning one.
    comfy_dir: Path = Path(_env("COMFY_DIR", str(ROOT / "ComfyUI")))
    comfy_url: str = os.environ.get("COMFY_URL", "")
    comfy_port: int = int(_env("COMFY_PORT", "8189"))
    comfy_args: str = os.environ.get("COMFY_ARGS", "")
    comfy_start_timeout: float = float(_env("COMFY_START_TIMEOUT", "300"))

    # API
    api_key: str = os.environ.get("API_KEY", "")
    request_timeout: float = float(_env("REQUEST_TIMEOUT", "600"))
    queue_max: int = int(_env("QUEUE_MAX", "100"))       # max jobs waiting; more -> HTTP 429
    jobs_keep: int = int(_env("JOBS_KEEP", "1000"))      # finished jobs remembered in memory

    # Storage: Cloudflare R2 (any S3-compatible bucket). Unset -> images saved to ./outputs.
    r2_access_key_id: str = os.environ.get("R2_ACCESS_KEY_ID", "")
    r2_secret_access_key: str = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    r2_bucket: str = os.environ.get("R2_BUCKET_NAME", "")
    r2_endpoint: str = os.environ.get("R2_ENDPOINT", "")
    r2_region: str = _env("R2_REGION", "auto")
    r2_prefix: str = os.environ.get("R2_PREFIX", "")                  # e.g. "qwen/" -> qwen/<id>.png
    r2_url_expires: int = int(_env("R2_URL_EXPIRES", "604800"))      # signed URL lifetime, max 7 days
    r2_public_base_url: str = os.environ.get("R2_PUBLIC_BASE_URL", "")  # set if the bucket has a public domain

    # Model files (names inside ComfyUI/models/<folder>/). Defaults = official int8 workflow.
    diffusion_model: str = _env("DIFFUSION_MODEL", "qwen_image_2.1_int8_convrot.safetensors")
    text_encoder: str = _env("TEXT_ENCODER", "qwen3vl_8b_int8_convrot.safetensors")
    enhancer: str = _env("ENHANCER_MODEL", "qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors")
    vae: str = _env("VAE_MODEL", "qwen_image_2.1_vae_bf16.safetensors")

    log_dir: Path = field(default=ROOT / "logs")

    @property
    def base_url(self) -> str:
        return self.comfy_url.rstrip("/") or f"http://127.0.0.1:{self.comfy_port}"

    def model_paths(self) -> dict[str, Path]:
        models = self.comfy_dir / "models"
        return {
            "diffusion_model": models / "diffusion_models" / self.diffusion_model,
            "text_encoder": models / "text_encoders" / self.text_encoder,
            "enhancer": models / "text_encoders" / self.enhancer,
            "vae": models / "vae" / self.vae,
        }


settings = Settings()
