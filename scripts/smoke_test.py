"""Hits a running API: /health, then one image. usage: python scripts/smoke_test.py [http://host:8000] [--enhance]"""
import sys
import time
from pathlib import Path

import httpx

url = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:8000").rstrip("/")
enhance = "--enhance" in sys.argv
headers = {"X-API-Key": k} if (k := __import__("os").environ.get("API_KEY")) else {}

with httpx.Client(base_url=url, headers=headers, timeout=900) as c:
    print("health:", c.get("/health").raise_for_status().json())
    for i in range(2):  # first call includes model load; second shows steady-state speed
        t0 = time.time()
        r = c.post("/generate", json={"prompt": 'A red fox in a snowy birch forest at golden hour, '
                                                'a wooden sign next to it reads "Qwen 2.1"',
                                      "enhance": enhance, "seed": 42 + i})
        r.raise_for_status()
        out = Path("outputs") / f"smoke_{i}.png"
        out.parent.mkdir(exist_ok=True)
        out.write_bytes(r.content)
        print(f"image {i}: {len(r.content) / 1e6:.1f} MB, seed {r.headers['x-seed']}, "
              f"server {r.headers['x-elapsed-seconds']}s, round-trip {time.time() - t0:.1f}s -> {out}")
