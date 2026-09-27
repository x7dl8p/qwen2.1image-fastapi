"""End-to-end check of a running API: health, queue 3 jobs, poll them, sync /generate.
usage: .venv/bin/python scripts/smoke_test.py [http://host:port]   (API_KEY env var if the server has one)"""
import os
import sys
import time

import httpx

url = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:8000").rstrip("/")
headers = {"X-API-Key": os.environ["API_KEY"]} if os.environ.get("API_KEY") else {}

with httpx.Client(base_url=url, headers=headers, timeout=900) as c:
    print("health:", c.get("/health").raise_for_status().json())

    ids = []
    for i, p in enumerate(["a red fox in a snowy forest", "a lighthouse at dusk", 'a neon sign reading "OPEN"']):
        job = c.post("/jobs", json={"prompt": p, "seed": 100 + i}).raise_for_status().json()
        print(f"queued {job['id']} position={job['position']}")
        ids.append(job["id"])

    t0 = time.time()
    while True:
        jobs = [c.get(f"/jobs/{i}").raise_for_status().json() for i in ids]
        if all(j["status"] in ("done", "failed") for j in jobs):
            break
        time.sleep(1)
    for j in jobs:
        print(f"{j['id']} {j['status']} {j['elapsed_s']}s {j['error'] or ''}\n   {j['url']}")
    print(f"3 queued jobs finished in {time.time() - t0:.1f}s")
    img = httpx.get(jobs[0]["url"], timeout=60)
    print("download of signed url:", img.status_code, img.headers.get("content-type"), len(img.content), "bytes")

    r = c.post("/generate", json={"prompt": "a cup of coffee on a wooden table"}).raise_for_status()
    print("sync /generate:", r.headers["content-type"], len(r.content), "bytes, job", r.headers["x-job-id"])
    print("all jobs:", c.get("/jobs").raise_for_status().json()["counts"])
