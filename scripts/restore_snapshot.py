"""Database restore utility for SBDMS Supabase database.
Restores database tables and data from a saved JSON snapshot or SQL dump.
"""
import os
import sys
import json

sys.path.insert(0, os.path.abspath("."))

from sqlalchemy import create_engine, text, inspect
from app.core.config import Settings

settings = Settings()
engine = create_engine(settings.DATABASE_URL)

RESTORE_ORDER = [
    "users",
    "donors",
    "recipients",
    "hospitals",
    "medical_info",
    "blood_requests",
    "donor_match",
    "blood_inventory",
    "donation_history",
    "donation_events",
    "event_participants",
    "campaign_notices",
    "system_logs",
    "communications",
    "inventory_transaction",
    "appointments",
]


def restore_from_json(snapshot_path: str = "db_snapshots/snapshot_latest.json", truncate: bool = False):
    if not os.path.exists(snapshot_path):
        print(f"Error: Snapshot file not found at {snapshot_path}")
        return False

    with open(snapshot_path, "r", encoding="utf-8") as f:
        snapshot = json.load(f)

    print(f"Loaded snapshot created at: {snapshot.get('timestamp')}")
    tables_data = snapshot.get("data", {})

    with engine.begin() as conn:
        if truncate:
            print("Truncating tables with CASCADE...")
            # Truncate in reverse dependency order
            for table in reversed(RESTORE_ORDER):
                try:
                    conn.execute(text(f'TRUNCATE TABLE "{table}" CASCADE;'))
                    print(f"  Truncated {table}")
                except Exception as e:
                    print(f"  Warning truncating {table}: {e}")

        for table in RESTORE_ORDER:
            rows = tables_data.get(table, [])
            if not rows:
                continue

            print(f"Restoring {table} ({len(rows)} rows)...")
            # Get columns from first row
            cols = list(rows[0].keys())
            cols_str = ", ".join([f'"{c}"' for c in cols])
            placeholders = ", ".join([f":{c}" for c in cols])
            stmt = text(f'INSERT INTO "{table}" ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING;')

            for r in rows:
                conn.execute(stmt, r)

    print("Restore completed successfully!")
    return True


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "db_snapshots/snapshot_latest.json"
    truncate = "--truncate" in sys.argv
    restore_from_json(path, truncate=truncate)
