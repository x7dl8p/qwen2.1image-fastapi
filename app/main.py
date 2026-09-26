"""Qwen-Image 2.1 text-to-image API. Send a prompt, get an image back."""
import base64
import io
import logging
import random
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.responses import RedirectResponse, Response
from fastapi.security import APIKeyHeader
from PIL import Image
from pydantic import BaseModel, Field, field_validator

from . import workflow
from .comfy import ComfyEngine, ComfyError
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("qwen-api")
engine = ComfyEngine(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    missing = [f"{k}: {p}" for k, p in settings.model_paths().items() if not p.exists() and not settings.comfy_url]
    if missing:
        log.warning("model files missing (run scripts/download_models.sh):\n  %s", "\n  ".join(missing))
    await engine.start()
    yield
    await engine.stop()


app = FastAPI(title="Qwen-Image 2.1 API", version="1.0", lifespan=lifespan,
              description="Text-to-image with Qwen-Image 2.1. Open **POST /generate → Try it out**, "
                          "edit the prompt, press Execute: the image appears in the response.")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_key(key: str | None = Security(api_key_header)) -> None:
    if settings.api_key and not secrets.compare_digest(key or "", settings.api_key):
        raise HTTPException(401, "invalid or missing API key (X-API-Key header)")


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000,
                        examples=['A red fox in a snowy birch forest at golden hour, a wooden sign reads "Hello"'])
    negative_prompt: str = Field("", description="only used when cfg > 1")
    width: int = Field(1024, ge=256, le=2048, description="rounded down to a multiple of 16")
    height: int = Field(1024, ge=256, le=2048, description="rounded down to a multiple of 16")
    steps: int = Field(25, ge=1, le=100)
    cfg: float = Field(1.0, ge=0.0, le=20.0, description="1.0 = official setting")
    seed: int | None = Field(None, ge=0, le=2**53, description="random if omitted; returned in X-Seed")
    enhance: bool = Field(False, description="rewrite the prompt with the Qwen3.5-9B prompt enhancer first (~+16 s)")
    format: Literal["png", "jpeg", "webp"] = "png"

    @field_validator("width", "height")
    @classmethod
    def multiple_of_16(cls, v: int) -> int:
        return v // 16 * 16


class GenerateJSON(BaseModel):
    seed: int
    elapsed_s: float
    width: int
    height: int
    prompt: str = Field(description="the prompt actually used (the enhanced one if enhance=true)")
    format: str
    image_base64: str


IMAGE_RESPONSE = {200: {"description": "The generated image",
                        "content": {"image/png": {}, "image/jpeg": {}, "image/webp": {}}}}


async def _generate(req: GenerateRequest) -> tuple[bytes, str, int, float, str]:
    seed = req.seed if req.seed is not None else random.randint(0, 2**53)
    graph = workflow.text_to_image(settings, prompt=req.prompt, negative_prompt=req.negative_prompt,
                                   width=req.width, height=req.height, steps=req.steps, cfg=req.cfg,
                                   seed=seed, enhance=req.enhance)
    t0 = time.monotonic()
    try:
        outputs = await engine.run(graph, timeout=settings.request_timeout)
        png = await engine.fetch_image(outputs[workflow.IMAGE_NODE]["images"][0])
    except ComfyError as e:
        log.error("%s", e)
        raise HTTPException(500, str(e))
    elapsed = round(time.monotonic() - t0, 2)
    used_prompt = outputs[workflow.ENHANCED_TEXT_NODE]["text"][0] if req.enhance else req.prompt
    log.info("generated %dx%d steps=%d seed=%d enhance=%s in %.2fs",
             req.width, req.height, req.steps, seed, req.enhance, elapsed)

    if req.format == "png":
        return png, "image/png", seed, elapsed, used_prompt
    buf = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(buf, req.format.upper(), quality=95)
    return buf.getvalue(), f"image/{req.format}", seed, elapsed, used_prompt


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/docs")


@app.get("/health")
async def health():
    if not await engine.alive():
        raise HTTPException(503, "ComfyUI not reachable")
    dev = (await engine.system_stats())["devices"][0]
    return {"status": "ok", "gpu": dev["name"], "vram_total_gb": round(dev["vram_total"] / 2**30, 1),
            "vram_free_gb": round(dev["vram_free"] / 2**30, 1),
            "models": {k: p.exists() for k, p in settings.model_paths().items()}}


@app.post("/generate", response_class=Response, responses=IMAGE_RESPONSE, dependencies=[Depends(require_key)],
          summary="Prompt in, image out")
async def generate(req: GenerateRequest):
    data, media, seed, elapsed, _ = await _generate(req)
    return Response(data, media_type=media, headers={"X-Seed": str(seed), "X-Elapsed-Seconds": str(elapsed)})


@app.post("/generate/json", response_model=GenerateJSON, dependencies=[Depends(require_key)],
          summary="Same, but the image comes back base64 in JSON")
async def generate_json(req: GenerateRequest):
    data, _, seed, elapsed, used_prompt = await _generate(req)
    return GenerateJSON(seed=seed, elapsed_s=elapsed, width=req.width, height=req.height, prompt=used_prompt,
                        format=req.format, image_base64=base64.b64encode(data).decode())


@app.get("/generate", response_class=Response, responses=IMAGE_RESPONSE, dependencies=[Depends(require_key)],
         summary="Quick test from a browser address bar")
async def generate_get(prompt: str = Query(min_length=1), width: int = 1024, height: int = 1024,
                       steps: int = 25, seed: int | None = None, enhance: bool = False):
    return await generate(GenerateRequest(prompt=prompt, width=width, height=height,
                                          steps=steps, seed=seed, enhance=enhance))
