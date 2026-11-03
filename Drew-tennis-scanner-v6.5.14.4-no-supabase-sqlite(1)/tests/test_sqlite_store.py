from datetime import datetime, timezone
import tempfile
from pathlib import Path

from scanner.sqlite_store import SQLiteDashboardClient, SQLiteStore, json_safe
from scanner.worker_runtime import WorkerConfig, RailwayShadowWorker


def test_sqlite_dedupe_and_reopen():
    with tempfile.TemporaryDirectory() as d:
        path=Path(d)/'scanner.db'
        store=SQLiteStore(path)
        store.verify_tables()
        record={'dedupe_key':'same-event','scanned_at':'2026-10-20T19:00:00+00:00',
                'paper_trade_status':'OPEN','decision_status':'TRADE','event_key':'match-2',
                'player':'A','opponent':'B','event_date':'2026-10-20','paper_stake_amount':10,
                'paper_entry_price_cents':80}
        result=store.insert_shadow_scans([record,record]); assert (result.attempted,result.inserted,result.duplicates)==(2,1,1)
        opened=store.fetch_open_trades();assert len(opened)==1
        idx=opened[0]['id']
        store.resolve_trade(idx, {'paper_trade_status':'RESOLVED','paper_result':'WIN','paper_pnl':2.5})
        assert store.fetch_open_trades()==[]
        store.upsert_worker_status({'worker_id':'test','last_seen_at':'2026-10-20T19:00:00Z','status':'READY'})
        store.upsert_cycle({'cycle_id':'abc','started_at':'2026-10-20T19:00:00Z','status':'SUCCESS'})
        store.close()
        data=SQLiteDashboardClient(path).fetch_dashboard_data()
        assert data.workers[0]['status']=='READY'
        assert data.cycles[0]['status']=='SUCCESS'
        assert data.scans[0]['paper_result']=='WIN'
        assert data.scans[0]['id']==idx


def test_nonfinite_metrics_safe_for_sqlite_json():
    assert json_safe({'bad':float('nan'),'good':float('inf'),'nested':[float('-inf'),4]}) == {'bad':None,'good':None,'nested':[None,4]}


def test_prod_worker_creates_sqlite_not_network():
    with tempfile.TemporaryDirectory() as d:
        cfg=WorkerConfig(api_tennis_key='test',dry_run=False,scanner_data_dir=d)
        worker=RailwayShadowWorker(cfg)
        assert isinstance(worker.store,SQLiteStore)
        worker.verify_startup()
        assert (Path(d)/'scanner.db').exists()
        worker.store.close()
