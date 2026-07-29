from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = (5.0, 25.0)


class SupabaseDashboardError(RuntimeError):
    """Raised when the Streamlit dashboard cannot read scanner data."""


@dataclass(frozen=True)
class DashboardData:
    workers: List[Dict[str, Any]]
    cycles: List[Dict[str, Any]]
    scans: List[Dict[str, Any]]


class SupabaseDashboardClient:
    """Read-only PostgREST client for the Streamlit control dashboard.

    This class only issues GET requests. It accepts the same server-side key as
    the Railway worker so the existing private RLS tables do not need to be
    exposed publicly. Keep the key in Streamlit Secrets; never place it in code,
    GitHub, query parameters, logs, or browser-side JavaScript.
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
            raise ValueError(
                "SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY is missing."
            )
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
            backoff_factor=0.4,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        session.mount(
            "https://",
            HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8),
        )
        session.mount(
            "http://",
            HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8),
        )
        session.headers.update(
            {
                "Accept": "application/json",
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Accept-Profile": self.schema,
                "User-Agent": "DrewTennisScanner/6.5.9.1-Dashboard",
            }
        )
        return session

    def _endpoint(self, table: str, params: Mapping[str, Any]) -> str:
        clean = {key: value for key, value in params.items() if value not in (None, "")}
        query = urlencode(clean, safe="*,().:-")
        return f"{self.url}/rest/v1/{table}?{query}"

    def _get_rows(self, table: str, params: Mapping[str, Any]) -> List[Dict[str, Any]]:
        try:
            response = self.session.get(
                self._endpoint(table, params),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SupabaseDashboardError(f"Supabase read request failed: {exc}") from exc

        if not response.ok:
            preview = (response.text or "")[:500].replace("\n", " ")
            raise SupabaseDashboardError(
                f"Supabase read from {table} failed with HTTP "
                f"{response.status_code}: {preview}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SupabaseDashboardError(
                f"Supabase read from {table} returned invalid JSON."
            ) from exc
        if not isinstance(payload, list):
            raise SupabaseDashboardError(
                f"Supabase read from {table} returned an unexpected payload."
            )
        return [dict(row) for row in payload if isinstance(row, Mapping)]

    def fetch_worker_status(self, *, limit: int = 10) -> List[Dict[str, Any]]:
        return self._get_rows(
            "worker_status",
            {
                "select": "*",
                "order": "last_seen_at.desc",
                "limit": max(1, min(int(limit), 100)),
            },
        )

    def fetch_cycles(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        return self._get_rows(
            "scan_cycles",
            {
                "select": "*",
                "order": "started_at.desc",
                "limit": max(1, min(int(limit), 1000)),
            },
        )

    def fetch_scans(
        self,
        *,
        limit: int = 300,
        decision_statuses: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "select": "*",
            "order": "scanned_at.desc",
            "limit": max(1, min(int(limit), 2000)),
        }
        statuses = [str(value).strip() for value in (decision_statuses or []) if str(value).strip()]
        if statuses:
            escaped = [value.replace('"', "") for value in statuses]
            params["decision_status"] = f"in.({','.join(escaped)})"
        return self._get_rows("shadow_scans", params)

    def fetch_dashboard_data(
        self,
        *,
        worker_limit: int = 10,
        cycle_limit: int = 120,
        scan_limit: int = 500,
    ) -> DashboardData:
        return DashboardData(
            workers=self.fetch_worker_status(limit=worker_limit),
            cycles=self.fetch_cycles(limit=cycle_limit),
            scans=self.fetch_scans(limit=scan_limit),
        )
