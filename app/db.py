"""Job records: one row per generated image. Postgres when DATABASE_URL is set, else in memory."""
from __future__ import annotations  # a method is named `list`; keep list[...] hints lazy

import logging
import re
from collections import OrderedDict
from typing import Any

from .config import Settings

log = logging.getLogger("qwen-api")

COLUMNS = ["id", "status", "prompt", "enhanced_prompt", "negative_prompt", "width", "height", "steps", "cfg",
           "seed", "enhance", "format", "file", "error", "elapsed_s", "created_at", "started_at", "finished_at"]


class MemoryStore:
    """Fallback without a database: keeps the last `keep` jobs, lost on restart."""

    def __init__(self, keep: int):
        self.keep = keep
        self.rows: "OrderedDict[str, dict]" = OrderedDict()

    async def open(self) -> None:
        log.warning("jobs: DATABASE_URL not set, job history is kept in memory only")

    async def close(self) -> None:
        pass

    async def upsert(self, row: dict) -> None:
        self.rows[row["id"]] = dict(row)
        finished = [k for k, r in self.rows.items() if r["status"] in ("done", "failed")]
        for k in finished[: max(0, len(self.rows) - self.keep)]:
            del self.rows[k]

    async def get(self, job_id: str) -> dict | None:
        return self.rows.get(job_id)

    async def list(self, status: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
        rows = [r for r in reversed(self.rows.values()) if status is None or r["status"] == status]
        return rows[offset: offset + limit], len(rows)

    async def counts(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for r in self.rows.values():
            c[r["status"]] = c.get(r["status"], 0) + 1
        return c

    async def delete(self, job_id: str) -> None:
        self.rows.pop(job_id, None)

    async def unfinished(self) -> list[dict]:
        return []


class PostgresStore:
    def __init__(self, dsn: str, table: str):
        from psycopg_pool import AsyncConnectionPool

        self.t = table
        self.pool = AsyncConnectionPool(dsn, min_size=1, max_size=5, open=False,
                                        check=AsyncConnectionPool.check_connection)  # Neon drops idle conns

    async def open(self) -> None:
        await self.pool.open(wait=True, timeout=30)
        async with self.pool.connection() as c:
            await c.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.t} (
                    id              TEXT PRIMARY KEY,           -- also the image file name
                    status          TEXT NOT NULL,              -- queued | running | done | failed
                    prompt          TEXT NOT NULL,
                    enhanced_prompt TEXT,
                    negative_prompt TEXT NOT NULL DEFAULT '',
                    width INT NOT NULL, height INT NOT NULL, steps INT NOT NULL, cfg REAL NOT NULL,
                    seed BIGINT, enhance BOOLEAN NOT NULL, format TEXT NOT NULL,
                    file            TEXT,                       -- object key in the bucket
                    error           TEXT,
                    elapsed_s       REAL,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                    started_at      TIMESTAMPTZ,
                    finished_at     TIMESTAMPTZ
                )""")
            await c.execute(f"CREATE INDEX IF NOT EXISTS {self.t}_created_idx ON {self.t} (created_at DESC)")
            await c.execute(f"CREATE INDEX IF NOT EXISTS {self.t}_status_idx ON {self.t} (status)")
        log.info("jobs: stored in Postgres table %s", self.t)

    async def close(self) -> None:
        await self.pool.close()

    async def _all(self, sql: str, params: Any = ()) -> list[dict]:
        from psycopg.rows import dict_row

        async with self.pool.connection() as c:
            cur = await c.cursor(row_factory=dict_row).execute(sql, params)
            return await cur.fetchall()

    async def upsert(self, row: dict) -> None:
        cols = ", ".join(COLUMNS)
        vals = ", ".join(f"%({k})s" for k in COLUMNS)
        sets = ", ".join(f"{k} = EXCLUDED.{k}" for k in COLUMNS if k != "id")
        async with self.pool.connection() as c:
            await c.execute(f"INSERT INTO {self.t} ({cols}) VALUES ({vals}) ON CONFLICT (id) DO UPDATE SET {sets}",
                            {k: row.get(k) for k in COLUMNS})

    async def get(self, job_id: str) -> dict | None:
        rows = await self._all(f"SELECT * FROM {self.t} WHERE id = %s", (job_id,))
        return rows[0] if rows else None

    async def list(self, status: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
        where, params = ("WHERE status = %s", [status]) if status else ("", [])
        rows = await self._all(f"SELECT * FROM {self.t} {where} ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                               (*params, limit, offset))
        total = (await self._all(f"SELECT count(*) AS n FROM {self.t} {where}", params))[0]["n"]
        return rows, total

    async def counts(self) -> dict[str, int]:
        return {r["status"]: r["n"] for r in await self._all(f"SELECT status, count(*) AS n FROM {self.t} GROUP BY status")}

    async def delete(self, job_id: str) -> None:
        async with self.pool.connection() as c:
            await c.execute(f"DELETE FROM {self.t} WHERE id = %s", (job_id,))

    async def unfinished(self) -> list[dict]:
        """Jobs cut off by a restart, oldest first, so they can be queued again."""
        return await self._all(f"SELECT * FROM {self.t} WHERE status IN ('queued', 'running') ORDER BY created_at")


def make_store(s: Settings):
    if not s.database_url:
        return MemoryStore(s.jobs_keep)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", s.db_table):
        raise ValueError(f"DB_TABLE must be a plain identifier, got {s.db_table!r}")
    return PostgresStore(s.database_url, s.db_table)
