from unittest.mock import Mock
from scanner.supabase_store import SupabaseStore


def response(ok, status, text='', payload=None):
    r = Mock()
    r.ok = ok
    r.status_code = status
    r.text = text
    r.content = b'[]' if payload is not None else b''
    r.json.return_value = payload if payload is not None else []
    return r


def test_bad_full_row_uses_compact_fallback():
    store = SupabaseStore('https://example.supabase.co', 'sb_secret_test')
    calls = [
        response(False, 400, '{"code":"22007","message":"invalid date"}'),
        response(False, 400, '{"code":"22007","message":"invalid date"}'),
        response(True, 201, payload=[{'dedupe_key':'abc'}]),
    ]
    store.session.post = Mock(side_effect=calls)
    record = {
        'scanned_at':'2026-07-24T22:00:00+00:00',
        'cycle_id':'ef049d8b-9b8b-4425-8568-000000000000',
        'worker_id':'worker','worker_version':'6.3','event_key':'1',
        'player':'A','opponent':'B','event_date':'bad-date',
        'market_found':True,'market_price_cents':0,'decision_status':'NO TRADE',
        'decision_reason':'No break lead','stability_score':20,'required_score':75,
        'stake_pct':0,'stake_amount':0,'bankroll':100,'paper_trade_status':'NOT_ENTERED',
        'paper_stake_amount':0,'paper_pnl':0,'dedupe_key':'abc'
    }
    result = store.insert_shadow_scans([record])
    assert result.inserted == 1
    fallback_payload = store.session.post.call_args_list[2].kwargs['json'][0]
    assert fallback_payload['decision_reason'] == 'No break lead'
    assert fallback_payload['match_snapshot']['storage_fallback'] is True
    assert fallback_payload['match_snapshot']['original_record']['event_date'] == 'bad-date'
