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
                "User-Agent": "DrewTennisScanner/6.2-Railway",
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
        attempted = len(records)
        inserted = 0
        for start in range(0, attempted, max(1, int(chunk_size))):
            chunk = list(records[start : start + max(1, int(chunk_size))])
            response = self._post(
                "shadow_scans",
                chunk,
                query="on_conflict=dedupe_key",
                prefer="resolution=ignore-duplicates,return=representation",
            )
            self._raise_for_response(response, "shadow scan insert")
            try:
                payload = response.json() if response.content else []
            except ValueError:
                payload = []
            if isinstance(payload, list):
                inserted += len(payload)
            elif response.status_code in {200, 201, 204}:
                # Defensive fallback. PostgREST normally returns a list when
                # return=representation is requested.
                inserted += len(chunk)
        return InsertResult(attempted=attempted, inserted=inserted)


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
