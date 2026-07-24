from __future__ import annotations

import unittest
from unittest.mock import Mock

from scanner.supabase_store import SupabaseStore


class SupabaseStoreTests(unittest.TestCase):
    def test_headers_and_ignore_duplicate_insert(self):
        store = SupabaseStore("https://example.supabase.co/", "sb_secret_test")
        self.assertEqual(store.url, "https://example.supabase.co")
        self.assertEqual(store.session.headers["apikey"], "sb_secret_test")
        self.assertEqual(store.session.headers["Authorization"], "Bearer sb_secret_test")

        response = Mock()
        response.ok = True
        response.status_code = 201
        response.content = b'[{"dedupe_key":"a"}]'
        response.json.return_value = [{"dedupe_key": "a"}]
        store.session.post = Mock(return_value=response)

        result = store.insert_shadow_scans(
            [{"dedupe_key": "a"}, {"dedupe_key": "a"}]
        )
        self.assertEqual(result.attempted, 2)
        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.duplicates, 1)
        _, kwargs = store.session.post.call_args
        self.assertIn("on_conflict=dedupe_key", store.session.post.call_args.args[0])
        self.assertIn("ignore-duplicates", kwargs["headers"]["Prefer"])


if __name__ == "__main__":
    unittest.main()
