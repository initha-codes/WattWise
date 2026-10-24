import os
import sqlite3
from pathlib import Path

from .data import generate_readings

ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = Path(os.getenv("WATTWISE_DATABASE", ROOT / "data" / "wattwise.db"))


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    return db


def initialize() -> None:
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS readings (
              timestamp TEXT NOT NULL, location_id TEXT NOT NULL, kwh REAL NOT NULL,
              interval_minutes INTEGER NOT NULL DEFAULT 60, quality TEXT NOT NULL DEFAULT 'valid',
              PRIMARY KEY (timestamp, location_id)
            );
            CREATE TABLE IF NOT EXISTS anomaly_states (
              event_id TEXT PRIMARY KEY, status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS recommendation_states (
              recommendation_id TEXT PRIMARY KEY, status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
            );
        """)
        if db.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO readings(timestamp, location_id, kwh, interval_minutes, quality) VALUES (?, ?, ?, ?, ?)",
                [(row["timestamp"], row["location_id"], row["kwh"], row["interval_minutes"], row["quality"]) for row in generate_readings()],
            )


def fetch_readings() -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT timestamp, location_id, kwh, interval_minutes, quality FROM readings ORDER BY timestamp, location_id").fetchall()
    return [dict(row) for row in rows]


def set_state(table: str, key_name: str, key: str, status: str, note: str) -> dict:
    if table not in {"anomaly_states", "recommendation_states"}:
        raise ValueError("Unsupported state table")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        db.execute(
            f"INSERT INTO {table}({key_name}, status, note, updated_at) VALUES (?, ?, ?, ?) "
            f"ON CONFLICT({key_name}) DO UPDATE SET status=excluded.status, note=excluded.note, updated_at=excluded.updated_at",
            (key, status, note, now),
        )
    return {"status": status, "note": note, "updated_at": now}


def get_states(table: str) -> dict[str, dict]:
    with connect() as db:
        rows = db.execute(f"SELECT * FROM {table}").fetchall()
    return {row[0]: {"status": row[1], "note": row[2], "updated_at": row[3]} for row in rows}


def insert_readings(rows: list[dict]) -> int:
    with connect() as db:
        before = db.total_changes
        db.executemany(
            "INSERT OR IGNORE INTO readings(timestamp, location_id, kwh, interval_minutes, quality) VALUES (?, ?, ?, ?, ?)",
            [(row["timestamp"], row["location_id"], row["kwh"], row.get("interval_minutes", 60), row.get("quality", "valid")) for row in rows],
        )
        return db.total_changes - before


def restore_demo() -> None:
    with connect() as db:
        db.execute("DELETE FROM readings")
        db.execute("DELETE FROM anomaly_states")
        db.execute("DELETE FROM recommendation_states")
        db.executemany(
            "INSERT INTO readings(timestamp, location_id, kwh, interval_minutes, quality) VALUES (?, ?, ?, ?, ?)",
            [(row["timestamp"], row["location_id"], row["kwh"], row["interval_minutes"], row["quality"]) for row in generate_readings()],
        )