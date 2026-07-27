from __future__ import annotations

import unittest
from unittest.mock import Mock

from scanner.supabase_dashboard import SupabaseDashboardClient, SupabaseDashboardError


class SupabaseDashboardClientTests(unittest.TestCase):
    def test_read_headers_and_cycle_query(self):
        client = SupabaseDashboardClient(
            "https://example.supabase.co/",
            "sb_secret_test",
        )
        self.assertEqual(client.url, "https://example.supabase.co")
        self.assertEqual(client.session.headers["apikey"], "sb_secret_test")
        self.assertEqual(
            client.session.headers["Authorization"],
            "Bearer sb_secret_test",
        )

        response = Mock()
        response.ok = True
        response.json.return_value = [{"cycle_id": "abc", "status": "SUCCESS"}]
        client.session.get = Mock(return_value=response)

        rows = client.fetch_cycles(limit=25)
        self.assertEqual(rows[0]["cycle_id"], "abc")
        url = client.session.get.call_args.args[0]
        self.assertIn("/rest/v1/scan_cycles?", url)
        self.assertIn("order=started_at.desc", url)
        self.assertIn("limit=25", url)

    def test_trade_status_filter(self):
        client = SupabaseDashboardClient(
            "https://example.supabase.co",
            "sb_secret_test",
        )
        response = Mock()
        response.ok = True
        response.json.return_value = []
        client.session.get = Mock(return_value=response)

        client.fetch_scans(decision_statuses=["TRADE", "WAIT"])
        url = client.session.get.call_args.args[0]
        self.assertIn("decision_status=in.(TRADE,WAIT)", url)

    def test_http_error_is_clear(self):
        client = SupabaseDashboardClient(
            "https://example.supabase.co",
            "sb_secret_test",
        )
        response = Mock()
        response.ok = False
        response.status_code = 401
        response.text = "unauthorized"
        client.session.get = Mock(return_value=response)

        with self.assertRaises(SupabaseDashboardError) as context:
            client.fetch_worker_status()
        self.assertIn("HTTP 401", str(context.exception))


if __name__ == "__main__":
    unittest.main()
