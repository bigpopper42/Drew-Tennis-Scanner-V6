"""Local SQLite diagnostics store, fully independent of external databases.

Trading and order reconciliation do not rely on this optional storage layer.
Store files on a Railway volume to retain diagnostics between redeployments.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Dict, Mapping, Sequence


@dataclass(frozen=True)
class InsertResult:
    attempted: int
    inserted: int

    @property
    def duplicates(self) -> int:
        return max(0, self.attempted - self.inserted)


def json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    return value


def encode(data: Mapping[str, Any]) -> str:
    return json.dumps(json_safe(dict(data)), ensure_ascii=False, allow_nan=False, default=str)


class SQLiteStore:
    """Thread-confined connection, WAL mode, atomic dedupe and upserts."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS worker_status (
              worker_id TEXT PRIMARY KEY, last_seen_at TEXT, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scan_cycles (
              cycle_id TEXT PRIMARY KEY, started_at TEXT, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_cycle_started ON scan_cycles(started_at DESC);
            CREATE TABLE IF NOT EXISTS shadow_scans (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              dedupe_key TEXT NOT NULL UNIQUE,
              scanned_at TEXT, decision_status TEXT,
              paper_trade_status TEXT, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_shadow_scanned ON shadow_scans(scanned_at DESC);
            CREATE INDEX IF NOT EXISTS ix_shadow_open ON shadow_scans(paper_trade_status);
        """)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def verify_tables(self) -> None:
        for table in ("worker_status", "scan_cycles", "shadow_scans"):
            self.db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()

    def upsert_worker_status(self, record: Dict[str, Any]) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO worker_status(worker_id,last_seen_at,payload) VALUES(?,?,?) "
                "ON CONFLICT(worker_id) DO UPDATE SET last_seen_at=excluded.last_seen_at,payload=excluded.payload",
                (record["worker_id"], record.get("last_seen_at"), encode(record)),
            )

    def upsert_cycle(self, record: Dict[str, Any]) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO scan_cycles(cycle_id,started_at,payload) VALUES(?,?,?) "
                "ON CONFLICT(cycle_id) DO UPDATE SET started_at=excluded.started_at,payload=excluded.payload",
                (record["cycle_id"], record.get("started_at"), encode(record)),
            )

    def insert_shadow_scans(self, records: Sequence[Dict[str, Any]]) -> InsertResult:
        added = 0
        with self.db:
            for record in records:
                payload = encode(record)
                key = str(record.get("dedupe_key") or hashlib.sha256(payload.encode()).hexdigest())
                row = self.db.execute(
                    "INSERT OR IGNORE INTO shadow_scans(dedupe_key,scanned_at,decision_status,paper_trade_status,payload) "
                    "VALUES(?,?,?,?,?)",
                    (key, record.get("scanned_at"), record.get("decision_status"),
                     record.get("paper_trade_status"), payload),
                )
                added += max(0, row.rowcount)
        return InsertResult(attempted=len(records), inserted=added)

    def fetch_open_trades(self, *, limit: int = 1000) -> list[dict]:
        rows = self.db.execute(
            "SELECT id,payload FROM shadow_scans WHERE paper_trade_status='OPEN' "
            "ORDER BY scanned_at LIMIT ?", (max(1, int(limit)),)
        ).fetchall()
        return [{**json.loads(payload), "id": row_id} for row_id, payload in rows]

    def resolve_trade(self, row_id: Any, updates: Dict[str, Any]) -> None:
        with self.db:
            row = self.db.execute("SELECT payload FROM shadow_scans WHERE id=?", (row_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown scan id: {row_id}")
            record = json.loads(row[0]); record.update(updates)
            self.db.execute(
                "UPDATE shadow_scans SET paper_trade_status=?, payload=? WHERE id=?",
                (record.get("paper_trade_status"), encode(record), row_id),
            )


@dataclass(frozen=True)
class DashboardData:
    workers: list[dict]
    cycles: list[dict]
    scans: list[dict]


class SQLiteDashboardClient:
    """Read-only access to the worker's database, when both run on a shared disk."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        if not self.path.is_file():
            raise FileNotFoundError(f"Scanner diagnostics database not found: {self.path}")

    def fetch_dashboard_data(self, *, worker_limit: int = 10, cycle_limit: int = 120,
                             scan_limit: int = 500) -> DashboardData:
        # mode=ro protects against accidental modification by Streamlit.
        with sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as db:
            workers = [json.loads(v) for (v,) in db.execute(
                "SELECT payload FROM worker_status ORDER BY last_seen_at DESC LIMIT ?", (worker_limit,))]
            cycles = [json.loads(v) for (v,) in db.execute(
                "SELECT payload FROM scan_cycles ORDER BY started_at DESC LIMIT ?", (cycle_limit,))]
            scans = [dict(json.loads(v), id=idx) for idx,v in db.execute(
                "SELECT id,payload FROM shadow_scans ORDER BY scanned_at DESC LIMIT ?", (scan_limit,))]
        return DashboardData(workers, cycles, scans)
