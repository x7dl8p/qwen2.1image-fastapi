"""Qwen-Image 2.1 text-to-image API.

POST /jobs          queue a prompt -> job id right away (the id is also the image file name)
GET  /jobs/{id}     status of one job + signed image URL when done
GET  /jobs          all jobs + queue counts
POST /generate      queue and wait -> the image itself (handy in Swagger)
"""
import io
import logging
import random
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import RedirectResponse, Response
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field, field_validator

from . import workflow
from .comfy import ComfyEngine
from .config import settings
from .jobs import Job, JobQueue, QueueFull
from .storage import Storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("qwen-api")
engine = ComfyEngine(settings)
storage = Storage(settings)


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000,
                        examples=['A red fox in a snowy birch forest at golden hour, a wooden sign reads "Hello"'])
    negative_prompt: str = Field("", description="only used when cfg > 1")
    width: int = Field(1024, ge=256, le=2048, description="rounded down to a multiple of 16")
    height: int = Field(1024, ge=256, le=2048, description="rounded down to a multiple of 16")
    steps: int = Field(25, ge=1, le=100)
    cfg: float = Field(1.0, ge=0.0, le=20.0, description="1.0 = official setting")
    seed: int | None = Field(None, ge=0, le=2**53, description="random if omitted")
    enhance: bool = Field(False, description="rewrite the prompt with the Qwen3.5-9B prompt enhancer first (~+16 s)")
    format: Literal["png", "jpeg", "webp"] = "png"

    @field_validator("width", "height")
    @classmethod
    def multiple_of_16(cls, v: int) -> int:
        return v // 16 * 16


class JobOut(BaseModel):
    id: str = Field(description="job id = image file name without extension")
    status: Literal["queued", "running", "done", "failed"]
    position: int | None = Field(None, description="place in the queue while queued (1 = next)")
    url: str | None = Field(None, description="image URL when done (signed, expires after R2_URL_EXPIRES)")
    file: str | None = None
    prompt: str
    enhanced_prompt: str | None = None
    width: int
    height: int
    steps: int
    seed: int | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_s: float | None = Field(None, description="generation time")
    error: str | None = None


class JobList(BaseModel):
    counts: dict[str, int]
    jobs: list[JobOut] = Field(description="newest first")


async def run_job(job: Job) -> None:
    """Worker body: generate the image and upload it as <job id>.<ext>."""
    req: GenerateRequest = job.request
    job.seed = req.seed if req.seed is not None else random.randint(0, 2**53)
    graph = workflow.text_to_image(settings, prompt=req.prompt, negative_prompt=req.negative_prompt,
                                   width=req.width, height=req.height, steps=req.steps, cfg=req.cfg,
                                   seed=job.seed, enhance=req.enhance)
    t0 = time.monotonic()
    outputs = await engine.run(graph, timeout=settings.request_timeout)
    data = await engine.fetch_image(outputs[workflow.IMAGE_NODE]["images"][0])
    job.elapsed_s = round(time.monotonic() - t0, 2)
    job.prompt_used = outputs[workflow.ENHANCED_TEXT_NODE]["text"][0] if req.enhance else req.prompt

    if req.format != "png":
        buf = io.BytesIO()
        Image.open(io.BytesIO(data)).convert("RGB").save(buf, req.format.upper(), quality=95)
        data = buf.getvalue()
    name = f"{job.id}.{req.format}"
    await storage.save(name, data, f"image/{req.format}")
    job.file, job.data = name, data
    log.info("job %s done: %dx%d steps=%d seed=%d enhance=%s in %.2fs -> %s",
             job.id, req.width, req.height, req.steps, job.seed, req.enhance, job.elapsed_s, name)


queue = JobQueue(run_job, max_queued=settings.queue_max, keep=settings.jobs_keep)


@asynccontextmanager
async def lifespan(_: FastAPI):
    missing = [f"{k}: {p}" for k, p in settings.model_paths().items() if not p.exists() and not settings.comfy_url]
    if missing:
        log.warning("model files missing (run scripts/download_models.sh):\n  %s", "\n  ".join(missing))
    await engine.start()
    queue.start()
    yield
    await queue.stop()
    await engine.stop()


app = FastAPI(title="Qwen-Image 2.1 API", version="2.0", lifespan=lifespan,
              description="Text-to-image with Qwen-Image 2.1.\n\n"
                          "* **POST /jobs** queues a prompt and returns its id immediately; "
                          "poll **GET /jobs/{id}** until `status` is `done` and open `url`.\n"
                          "* **POST /generate** does the same but waits and returns the image "
                          "(Try it out → Execute shows it here).\n\n"
                          "If an API key is set, click **Authorize** first.")
if not storage.is_bucket:
    app.mount("/files", StaticFiles(directory=storage.local_dir), name="files")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_key(key: str | None = Security(api_key_header)) -> None:
    if settings.api_key and not secrets.compare_digest(key or "", settings.api_key):
        raise HTTPException(401, "invalid or missing API key (X-API-Key header)")


def job_out(job: Job, request: Request) -> JobOut:
    r: GenerateRequest = job.request
    url = None
    if job.file:
        url = storage.url(job.file)
        if url.startswith("/"):
            url = str(request.base_url).rstrip("/") + url
    return JobOut(id=job.id, status=job.status, position=queue.position(job), url=url, file=job.file,
                  prompt=r.prompt, enhanced_prompt=job.prompt_used if r.enhance else None,
                  width=r.width, height=r.height, steps=r.steps, seed=job.seed,
                  created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at,
                  elapsed_s=job.elapsed_s, error=job.error)


def submit(req: GenerateRequest, keep_data: bool = False) -> Job:
    try:
        return queue.submit(req, keep_data=keep_data)
    except QueueFull as e:
        raise HTTPException(429, str(e))


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/docs")


@app.get("/health")
async def health():
    if not await engine.alive():
        raise HTTPException(503, "ComfyUI not reachable")
    dev = (await engine.system_stats())["devices"][0]
    return {"status": "ok", "gpu": dev["name"], "vram_total_gb": round(dev["vram_total"] / 2**30, 1),
            "vram_free_gb": round(dev["vram_free"] / 2**30, 1), "queue": queue.counts(),
            "storage": f"r2:{settings.r2_bucket}" if storage.is_bucket else "local:outputs/",
            "models": {k: p.exists() for k, p in settings.model_paths().items()}}


@app.post("/jobs", response_model=JobOut, status_code=202, dependencies=[Depends(require_key)],
          summary="Queue a prompt, get the job id back immediately")
async def create_job(req: GenerateRequest, request: Request):
    return job_out(submit(req), request)


@app.get("/jobs/{job_id}", response_model=JobOut, dependencies=[Depends(require_key)],
         summary="One job: status, and the image URL once done")
async def get_job(job_id: str, request: Request):
    job = queue.get(job_id)
    if not job:
        raise HTTPException(404, f"job {job_id} not found")
    return job_out(job, request)


@app.get("/jobs", response_model=JobList, dependencies=[Depends(require_key)], summary="All jobs, newest first")
async def list_jobs(request: Request, status: Literal["queued", "running", "done", "failed"] | None = None,
                    limit: int = 100):
    jobs = [j for j in reversed(queue.jobs.values()) if status is None or j.status == status][:limit]
    return JobList(counts=queue.counts(), jobs=[job_out(j, request) for j in jobs])


@app.post("/generate", response_class=Response, dependencies=[Depends(require_key)],
          responses={200: {"description": "The generated image",
                           "content": {"image/png": {}, "image/jpeg": {}, "image/webp": {}}}},
          summary="Queue a prompt and wait: returns the image itself")
async def generate(req: GenerateRequest, request: Request):
    job = submit(req, keep_data=True)
    await job.done.wait()
    data, job.data = job.data, None
    if job.status == "failed" or data is None:
        raise HTTPException(500, job.error or "generation failed")
    out = job_out(job, request)
    return Response(data, media_type=f"image/{req.format}",
                    headers={"X-Job-Id": job.id, "X-Seed": str(job.seed), "X-Elapsed-Seconds": str(job.elapsed_s),
                             "X-Image-Url": out.url or ""})
