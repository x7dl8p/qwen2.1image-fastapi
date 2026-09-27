"""In-memory job queue: requests are queued, one worker feeds the model the next job as soon as it's free."""
import asyncio
import logging
import secrets
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

log = logging.getLogger("qwen-api")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_job_id() -> str:
    # Sortable and readable; also used as the image file name.
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(4)


@dataclass
class Job:
    id: str
    request: Any                      # GenerateRequest
    status: str = "queued"            # queued | running | done | failed
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_s: float | None = None
    seed: int | None = None
    prompt_used: str | None = None
    file: str | None = None           # image name in storage: "<id>.<ext>"
    error: str | None = None
    # Not exposed: lets a synchronous caller wait for the result and grab the bytes.
    done: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    data: bytes | None = field(default=None, repr=False)
    keep_data: bool = field(default=False, repr=False)


class QueueFull(Exception):
    pass


class JobQueue:
    def __init__(self, run: Callable[[Job], Awaitable[None]], max_queued: int, keep: int):
        self.run = run
        self.max_queued = max_queued
        self.keep = keep
        self.jobs: "OrderedDict[str, Job]" = OrderedDict()
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.worker: asyncio.Task | None = None

    def start(self) -> None:
        self.worker = asyncio.create_task(self._work(), name="job-worker")

    async def stop(self) -> None:
        if self.worker:
            self.worker.cancel()

    def submit(self, request, keep_data: bool = False) -> Job:
        if self.queue.qsize() >= self.max_queued:
            raise QueueFull(f"queue is full ({self.max_queued} waiting), try again later")
        job = Job(id=new_job_id(), request=request, keep_data=keep_data)
        self.jobs[job.id] = job
        self._evict()
        self.queue.put_nowait(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def position(self, job: Job) -> int | None:
        """1 = next to run."""
        if job.status != "queued":
            return None
        pos = 1
        for j in self.jobs.values():  # insertion order = submission order
            if j is job:
                return pos
            pos += j.status == "queued"
        return None

    def counts(self) -> dict[str, int]:
        c = {"queued": 0, "running": 0, "done": 0, "failed": 0}
        for j in self.jobs.values():
            c[j.status] += 1
        return c

    def _evict(self) -> None:
        # Forget the oldest finished jobs beyond `keep` (their images stay in storage).
        finished = [k for k, j in self.jobs.items() if j.status in ("done", "failed")]
        for k in finished[: max(0, len(self.jobs) - self.keep)]:
            del self.jobs[k]

    async def _work(self) -> None:
        while True:
            job = await self.queue.get()
            job.status, job.started_at = "running", _now()
            log.info("job %s started (%d waiting)", job.id, self.queue.qsize())
            try:
                await self.run(job)
                job.status = "done"
            except Exception as e:  # keep the worker alive whatever happens
                job.status, job.error = "failed", str(e) or e.__class__.__name__
                log.error("job %s failed: %s", job.id, job.error)
            finally:
                job.finished_at = _now()
                if not job.keep_data:
                    job.data = None
                job.done.set()
                self.queue.task_done()
