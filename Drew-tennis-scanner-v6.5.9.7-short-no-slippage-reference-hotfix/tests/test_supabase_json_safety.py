import math
from scanner.supabase_store import SupabaseStore


def test_json_safe_replaces_non_finite_numbers_recursively():
    payload = {
        "ok": 12.5,
        "nan": float("nan"),
        "pos_inf": float("inf"),
        "nested": [1.0, {"neg_inf": float("-inf")}],
    }
    safe = SupabaseStore._json_safe(payload)
    assert safe["ok"] == 12.5
    assert safe["nan"] is None
    assert safe["pos_inf"] is None
    assert safe["nested"][1]["neg_inf"] is None
