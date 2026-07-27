from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = (5.0, 25.0)


class SupabaseStoreError(RuntimeError):
    """Raised when the shadow worker cannot persist or verify data."""


@dataclass(frozen=True)
class InsertResult:
    attempted: int
    inserted: int

    @property
    def duplicates(self) -> int:
        return max(0, self.attempted - self.inserted)


class SupabaseStore:
    """Small PostgREST client designed for a server-side Railway worker.

    The client accepts either the newer ``sb_secret_...`` key or the legacy
    ``service_role`` JWT. The key is never logged by this module.
    """

    def __init__(
        self,
        url: str,
        key: str,
        *,
        schema: str = "public",
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    ) -> None:
        self.url = str(url or "").strip().rstrip("/")
        self.key = str(key or "").strip()
        self.schema = str(schema or "public").strip() or "public"
        self.timeout = timeout
        if not self.url:
            raise ValueError("SUPABASE_URL is missing.")
        if not self.key:
            raise ValueError("SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY is missing.")
        if not self.url.startswith(("https://", "http://")):
            raise ValueError("SUPABASE_URL must begin with http:// or https://.")
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST", "PATCH"}),
            raise_on_status=False,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8))
        session.mount("http://", HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8))
        session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Accept-Profile": self.schema,
                "Content-Profile": self.schema,
                "User-Agent": "DrewTennisScanner/6.5.4-Railway",
            }
        )
        return session

    def _endpoint(self, table: str, query: str = "") -> str:
        base = f"{self.url}/rest/v1/{table}"
        return f"{base}?{query}" if query else base

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        """Normalize values so Supabase receives strict JSON.

        Live feeds can produce NaN or Infinity in derived metrics. Python's
        JSON encoder permits those tokens, but PostgREST rejects the whole
        batch with HTTP 400. Replace non-finite numbers with JSON null.
        """
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, Mapping):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(item) for item in value]
        return value

    def _raise_for_response(self, response: requests.Response, action: str) -> None:
        if response.ok:
            return
        preview = (response.text or "")[:4000].replace("\n", " ")
        raise SupabaseStoreError(
            f"Supabase {action} failed with HTTP {response.status_code}: {preview}"
        )

    def verify_tables(self) -> None:
        """Fail fast when the SQL schema has not been installed."""
        for table in ("worker_status", "scan_cycles", "shadow_scans"):
            try:
                response = self.session.get(
                    self._endpoint(table, "select=*&limit=1"),
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise SupabaseStoreError(f"Supabase connectivity check failed: {exc}") from exc
            self._raise_for_response(response, f"table check for {table}")

    def upsert_worker_status(self, record: Dict[str, Any]) -> None:
        response = self._post(
            "worker_status",
            [record],
            query="on_conflict=worker_id",
            prefer="resolution=merge-duplicates,return=minimal",
        )
        self._raise_for_response(response, "worker status upsert")

    def upsert_cycle(self, record: Dict[str, Any]) -> None:
        response = self._post(
            "scan_cycles",
            [record],
            query="on_conflict=cycle_id",
            prefer="resolution=merge-duplicates,return=minimal",
        )
        self._raise_for_response(response, "scan cycle upsert")

    def insert_shadow_scans(
        self,
        records: Sequence[Dict[str, Any]],
        *,
        chunk_size: int = 100,
    ) -> InsertResult:
        """Insert diagnostic rows, with a guaranteed compact fallback.

        API Tennis fields occasionally contain values that PostgreSQL cannot
        coerce into a typed column (for example a non-ISO date). A single bad
        value causes PostgREST to reject the entire batch. Version 6.3 first
        attempts the full rows, then isolates failures row-by-row, and finally
        stores a compact diagnostic row containing the raw original payload in
        ``match_snapshot``. This keeps the scanner observable even when one
        optional field is malformed.
        """
        attempted = len(records)
        inserted = 0
        failures: List[str] = []
        size = max(1, int(chunk_size))

        for start in range(0, attempted, size):
            chunk = list(records[start : start + size])
            response = self._post(
                "shadow_scans",
                chunk,
                query="on_conflict=dedupe_key",
                prefer="resolution=ignore-duplicates,return=representation",
            )
            if response.ok:
                inserted += self._inserted_count(response, len(chunk))
                continue

            # Do not lose an entire cycle because one optional field is bad.
            for record in chunk:
                single = self._post(
                    "shadow_scans",
                    [record],
                    query="on_conflict=dedupe_key",
                    prefer="resolution=ignore-duplicates,return=representation",
                )
                if single.ok:
                    inserted += self._inserted_count(single, 1)
                    continue

                compact = self._compact_shadow_record(record, single.text)
                fallback = self._post(
                    "shadow_scans",
                    [compact],
                    query="on_conflict=dedupe_key",
                    prefer="resolution=ignore-duplicates,return=representation",
                )
                if fallback.ok:
                    inserted += self._inserted_count(fallback, 1)
                else:
                    failures.append(
                        f"full={self._response_preview(single)}; "
                        f"fallback={self._response_preview(fallback)}"
                    )

        if failures:
            raise SupabaseStoreError(
                "Supabase shadow scan insert failed after compact fallback: "
                + " | ".join(failures[:3])
            )
        return InsertResult(attempted=attempted, inserted=inserted)

    @staticmethod
    def _response_preview(response: requests.Response) -> str:
        return f"HTTP {response.status_code}: " + (response.text or "")[:4000].replace("\n", " ")

    @staticmethod
    def _inserted_count(response: requests.Response, fallback_count: int) -> int:
        try:
            payload = response.json() if response.content else []
        except ValueError:
            payload = []
        if isinstance(payload, list):
            return len(payload)
        return fallback_count if response.status_code in {200, 201, 204} else 0

    @classmethod
    def _compact_shadow_record(
        cls, record: Mapping[str, Any], original_error: str
    ) -> Dict[str, Any]:
        """Build a schema-safe row while preserving the complete raw record."""
        original = cls._json_safe(dict(record))
        diagnostics = {
            "storage_fallback": True,
            "original_insert_error": (original_error or "")[:4000],
            "original_record": original,
        }
        compact = {
            "scanned_at": record.get("scanned_at"),
            "cycle_id": record.get("cycle_id"),
            "worker_id": str(record.get("worker_id") or "unknown"),
            "worker_version": str(record.get("worker_version") or "6.5.4"),
            "event_key": str(record.get("event_key") or "unknown"),
            "player": str(record.get("player") or "Unknown"),
            "opponent": str(record.get("opponent") or "Unknown"),
            "market_found": bool(record.get("market_found")),
            "market_price_cents": float(record.get("market_price_cents") or 0.0),
            "decision_status": str(record.get("decision_status") or "NO TRADE"),
            "decision_reason": str(record.get("decision_reason") or "Diagnostic fallback row"),
            "stability_score": float(record.get("stability_score") or 0.0),
            "required_score": float(record.get("required_score") or 0.0),
            "stake_pct": float(record.get("stake_pct") or 0.0),
            "stake_amount": float(record.get("stake_amount") or 0.0),
            "bankroll": float(record.get("bankroll") or 0.0),
            "match_snapshot": diagnostics,
            "paper_trade_status": str(record.get("paper_trade_status") or "NOT_ENTERED"),
            "paper_stake_amount": float(record.get("paper_stake_amount") or 0.0),
            "paper_pnl": float(record.get("paper_pnl") or 0.0),
            "dedupe_key": str(record.get("dedupe_key") or ""),
        }
        return cls._json_safe(compact)


    def fetch_open_trades(self, *, limit: int = 1000) -> List[Dict[str, Any]]:
        query = (
            "select=id,event_key,event_date,player,opponent,market_price_cents,"
            "paper_entry_price_cents,paper_stake_amount&paper_trade_status=eq.OPEN"
            f"&limit={max(1, int(limit))}"
        )
        try:
            response = self.session.get(self._endpoint("shadow_scans", query), timeout=self.timeout)
        except requests.RequestException as exc:
            raise SupabaseStoreError(f"Supabase open-trade query failed: {exc}") from exc
        self._raise_for_response(response, "open trade query")
        try:
            payload = response.json() if response.content else []
        except ValueError:
            payload = []
        return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []

    def resolve_trade(self, row_id: Any, updates: Dict[str, Any]) -> None:
        try:
            response = self.session.patch(
                self._endpoint("shadow_scans", f"id=eq.{row_id}"),
                json=updates,
                headers={"Prefer": "return=minimal"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SupabaseStoreError(f"Supabase trade resolution failed: {exc}") from exc
        self._raise_for_response(response, "trade resolution")

    def _post(
        self,
        table: str,
        payload: Iterable[Dict[str, Any]],
        *,
        query: str = "",
        prefer: Optional[str] = None,
    ) -> requests.Response:
        headers = {"Prefer": prefer} if prefer else None
        try:
            safe_payload = self._json_safe(list(payload))
            return self.session.post(
                self._endpoint(table, query),
                json=safe_payload,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SupabaseStoreError(f"Supabase request failed: {exc}") from exc
