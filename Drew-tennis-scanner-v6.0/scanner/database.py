from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict

import pandas as pd

DB_PATH = Path("data/scanner.db")

BASE_COLUMNS = {
    "player": "TEXT",
    "opponent": "TEXT",
    "tournament": "TEXT",
    "event_type": "TEXT",
    "league": "TEXT",
    "competition_group": "TEXT",
    "event_key": "TEXT",
    "api_source": "TEXT",
    "market_price_cents": "REAL",
    "market_volume": "REAL",
    "market_liquidity": "REAL",
    "status": "TEXT",
    "stability_score": "REAL",
    "required_score": "REAL",
    "data_completeness_pct": "REAL DEFAULT 0",
    "core_completeness_pct": "REAL DEFAULT 0",
    "scoring_completeness_pct": "REAL DEFAULT 0",
    "stake_pct": "REAL",
    "stake_amount": "REAL",
    "bankroll": "REAL",
    "ranking": "INTEGER",
    "opponent_ranking": "INTEGER",
    "break_lead": "INTEGER",
    "serving": "INTEGER",
    "serving_for_match": "INTEGER",
    "best_of_sets": "INTEGER",
    "straight_set_closing": "INTEGER",
    "deciding_set": "INTEGER",
    "games_in_set": "INTEGER",
    "opponent_games_in_set": "INTEGER",
    "current_game_score": "TEXT",
    "current_set_breaks_suffered": "INTEGER",
    "service_points_won_pct": "REAL",
    "current_set_service_points_won_pct": "REAL",
    "effective_service_points_won_pct": "REAL",
    "opponent_service_points_won_pct": "REAL",
    "opponent_current_set_service_points_won_pct": "REAL",
    "first_serve_points_won_pct": "REAL",
    "current_set_first_serve_points_won_pct": "REAL",
    "first_serve_in_pct": "REAL",
    "current_set_first_serve_in_pct": "REAL",
    "break_points_created": "INTEGER",
    "break_points_faced": "INTEGER",
    "double_faults_per_service_game": "REAL",
    "notes": "TEXT",
    "source": "TEXT DEFAULT 'manual'",
    "market_title": "TEXT",
    "market_slug": "TEXT",
    "market_side": "TEXT",
    "result": "TEXT DEFAULT 'OPEN'",
    "winner": "TEXT",
    "final_score": "TEXT",
    "pnl": "REAL DEFAULT 0",
}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=20)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=20000")
    return connection


def init_db() -> None:
    definitions = ",\n".join(f"{name} {kind}" for name, kind in BASE_COLUMNS.items())
    with _connect() as connection:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                {definitions}
            )
            """
        )
        existing = {row[1] for row in connection.execute("PRAGMA table_info(recommendations)")}
        for column, column_type in BASE_COLUMNS.items():
            if column not in existing:
                connection.execute(f"ALTER TABLE recommendations ADD COLUMN {column} {column_type}")
        connection.commit()


def save_recommendation(record: Dict) -> int:
    if str(record.get("status") or "").upper() != "TRADE":
        raise ValueError("Version 6.0 records only qualified trades.")
    init_db()
    columns = list(BASE_COLUMNS)
    # Result and PnL retain their database defaults on insert.
    columns = [column for column in columns if column not in {"result", "pnl"}]
    values = [record.get(column) for column in columns]
    with _connect() as connection:
        cursor = connection.execute(
            f"INSERT INTO recommendations ({','.join(columns)}) VALUES ({','.join(['?'] * len(columns))})",
            values,
        )
        connection.commit()
        return int(cursor.lastrowid)


def load_recommendations() -> pd.DataFrame:
    init_db()
    with _connect() as connection:
        return pd.read_sql_query("SELECT * FROM recommendations ORDER BY id DESC", connection)


def update_result(row_id: int, result: str, pnl: float) -> bool:
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE recommendations SET result=?, pnl=? WHERE id=?",
            (result, pnl, row_id),
        )
        connection.commit()
        return cursor.rowcount > 0


def delete_recommendation(row_id: int) -> bool:
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM recommendations WHERE id=?", (row_id,))
        connection.commit()
        return cursor.rowcount > 0
