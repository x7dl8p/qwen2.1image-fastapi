"""Runs ComfyUI as a child process and talks to its HTTP API."""
import asyncio
import logging
import shlex
import subprocess
import sys
import time
import uuid

import httpx

from .config import Settings

log = logging.getLogger("qwen-api")


class ComfyError(RuntimeError):
    pass


class ComfyEngine:
    def __init__(self, s: Settings):
        self.s = s
        self.proc: subprocess.Popen | None = None
        self.http = httpx.AsyncClient(base_url=s.base_url, timeout=30)
        self.client_id = str(uuid.uuid4())

    # --- lifecycle -------------------------------------------------------------------------
    async def start(self) -> None:
        if await self.alive():
            log.info("attaching to running ComfyUI at %s", self.s.base_url)
            return
        if self.s.comfy_url:
            raise ComfyError(f"COMFY_URL={self.s.comfy_url} is not reachable")
        main_py = self.s.comfy_dir / "main.py"
        if not main_py.exists():
            raise ComfyError(f"{main_py} not found - run scripts/install.sh first")

        self.s.log_dir.mkdir(exist_ok=True)
        logfile = open(self.s.log_dir / "comfyui.log", "ab")
        cmd = [sys.executable, str(main_py), "--listen", "127.0.0.1", "--port", str(self.s.comfy_port),
               "--disable-auto-launch", *shlex.split(self.s.comfy_args)]
        log.info("starting ComfyUI: %s (log: logs/comfyui.log)", " ".join(cmd))
        self.proc = subprocess.Popen(cmd, cwd=self.s.comfy_dir, stdout=logfile, stderr=subprocess.STDOUT)

        deadline = time.monotonic() + self.s.comfy_start_timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise ComfyError(f"ComfyUI exited with code {self.proc.returncode}, see logs/comfyui.log")
            if await self.alive():
                log.info("ComfyUI ready")
                return
            await asyncio.sleep(1)
        raise ComfyError("ComfyUI did not come up in time, see logs/comfyui.log")

    async def stop(self) -> None:
        await self.http.aclose()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    async def alive(self) -> bool:
        try:
            return (await self.http.get("/api/system_stats")).status_code == 200
        except httpx.HTTPError:
            return False

    async def system_stats(self) -> dict:
        return (await self.http.get("/api/system_stats")).raise_for_status().json()

    # --- execution -------------------------------------------------------------------------
    async def run(self, graph: dict, timeout: float) -> dict:
        """Queue a graph, wait for it to finish, return its outputs keyed by node id."""
        r = await self.http.post("/prompt", json={"prompt": graph, "client_id": self.client_id})
        if r.status_code != 200:
            raise ComfyError(f"ComfyUI rejected the workflow: {r.text[:2000]}")
        prompt_id = r.json()["prompt_id"]

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            entry = (await self.http.get(f"/history/{prompt_id}")).json().get(prompt_id)
            status = (entry or {}).get("status", {})
            if status.get("completed") is not None:
                if status.get("status_str") != "success":
                    errors = [m[1] for m in status.get("messages", []) if m[0] == "execution_error"]
                    detail = errors[0].get("exception_message", errors) if errors else status
                    raise ComfyError(f"generation failed: {detail}")
                return entry["outputs"]
            await asyncio.sleep(0.25)
        await self.http.post("/interrupt")
        raise ComfyError(f"generation timed out after {timeout:.0f}s")

    async def fetch_image(self, image: dict) -> bytes:
        r = await self.http.get("/view", params={"filename": image["filename"],
                                                 "subfolder": image.get("subfolder", ""),
                                                 "type": image.get("type", "temp")})
        return r.raise_for_status().content
