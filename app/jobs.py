"""In-memory queue: requests wait here and one worker feeds the model the next job as soon as it's free.
Every state change is written to the job store (Postgres), which is what the API reads back."""
import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

log = logging.getLogger("qwen-api")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_job_id() -> str:
    # Sortable and readable; also used as the image file name.
    return _now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(4)


@dataclass
class Job:
    id: str
    request: Any                      # GenerateRequest
    status: str = "queued"            # queued | running | done | failed
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    elapsed_s: float | None = None
    seed: int | None = None
    prompt_used: str | None = None
    file: str | None = None           # image name in storage: "<id>.<ext>"
    error: str | None = None
    # Not stored: lets a synchronous caller wait for the result and grab the bytes.
    done: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    data: bytes | None = field(default=None, repr=False)
    keep_data: bool = field(default=False, repr=False)

    def to_row(self) -> dict:
        r = self.request
        return {"id": self.id, "status": self.status, "prompt": r.prompt,
                "enhanced_prompt": self.prompt_used if r.enhance else None, "negative_prompt": r.negative_prompt,
                "width": r.width, "height": r.height, "steps": r.steps, "cfg": r.cfg,
                "seed": self.seed if self.seed is not None else r.seed, "enhance": r.enhance, "format": r.format,
                "file": self.file, "error": self.error, "elapsed_s": self.elapsed_s,
                "created_at": self.created_at, "started_at": self.started_at, "finished_at": self.finished_at}


class QueueFull(Exception):
    pass


class JobQueue:
    def __init__(self, run: Callable[[Job], Awaitable[None]], store, max_queued: int):
        self.run = run
        self.store = store
        self.max_queued = max_queued
        self.active: dict[str, Job] = {}      # queued + running, in submission order
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.worker: asyncio.Task | None = None

    def start(self) -> None:
        self.worker = asyncio.create_task(self._work(), name="job-worker")

    async def stop(self) -> None:
        if self.worker:
            self.worker.cancel()

    async def submit(self, request, keep_data: bool = False, job_id: str | None = None,
                     created_at: datetime | None = None) -> Job:
        if self.queue.qsize() >= self.max_queued:
            raise QueueFull(f"queue is full ({self.max_queued} waiting), try again later")
        job = Job(id=job_id or new_job_id(), request=request, keep_data=keep_data)
        if created_at:
            job.created_at = created_at
        await self.store.upsert(job.to_row())
        self.active[job.id] = job
        self.queue.put_nowait(job)
        return job

    def position(self, job_id: str) -> int | None:
        """1 = next to run; None if not waiting."""
        pos = 1
        for j in self.active.values():
            if j.id == job_id:
                return pos if j.status == "queued" else None
            pos += j.status == "queued"
        return None

    async def _save(self, job: Job) -> None:
        try:
            await self.store.upsert(job.to_row())
        except Exception as e:  # a DB hiccup must not kill the worker
            log.error("job %s: could not save state %s: %s", job.id, job.status, e)

    async def _work(self) -> None:
        while True:
            job = await self.queue.get()
            job.status, job.started_at = "running", _now()
            await self._save(job)
            log.info("job %s started (%d waiting)", job.id, self.queue.qsize())
            try:
                await self.run(job)
                job.status = "done"
            except Exception as e:  # keep the worker alive whatever happens
                job.status, job.error = "failed", str(e) or e.__class__.__name__
                log.error("job %s failed: %s", job.id, job.error)
            job.finished_at = _now()
            await self._save(job)
            self.active.pop(job.id, None)
            if not job.keep_data:
                job.data = None
            job.done.set()
            self.queue.task_done()
