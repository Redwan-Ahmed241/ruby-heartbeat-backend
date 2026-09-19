"""Database snapshot utility for SBDMS Supabase database.
Exports full database schema, enums, and table data to JSON and SQL.
"""
import os
import sys
import json
import uuid

sys.path.insert(0, os.path.abspath("."))

from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import create_engine, text, inspect
from app.core.config import Settings

settings = Settings()
engine = create_engine(settings.DATABASE_URL)

TABLE_ORDER = [
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


class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, bytes):
            return obj.hex()
        return super().default(obj)


def create_snapshot(output_dir: str = "db_snapshots"):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    snapshot_json_path = os.path.join(output_dir, f"snapshot_{timestamp}.json")
    snapshot_latest_json = os.path.join(output_dir, "snapshot_latest.json")
    snapshot_sql_path = os.path.join(output_dir, f"snapshot_{timestamp}.sql")
    snapshot_latest_sql = os.path.join(output_dir, "snapshot_latest.sql")

    insp = inspect(engine)
    db_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "database_url_masked": settings.DATABASE_URL.split("@")[-1],
        "enums": {},
        "tables": {},
        "data": {},
        "row_counts": {},
    }

    with engine.connect() as conn:
        # 1. Fetch all custom enum types
        enum_query = text("""
            SELECT t.typname as enum_name, e.enumlabel as enum_value
            FROM pg_type t
            JOIN pg_enum e ON t.oid = e.enumtypid
            JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
            WHERE n.nspname = 'public'
            ORDER BY t.typname, e.enumsortorder;
        """)
        enums_res = conn.execute(enum_query).fetchall()
        for r in enums_res:
            enum_name = r[0]
            enum_val = r[1]
            if enum_name not in db_data["enums"]:
                db_data["enums"][enum_name] = []
            db_data["enums"][enum_name].append(enum_val)

        # 2. Fetch table schemas and rows
        all_tables = insp.get_table_names()
        # Order tables so parents come first
        ordered_tables = [t for t in TABLE_ORDER if t in all_tables]
        remaining_tables = [t for t in all_tables if t not in ordered_tables]
        tables_to_dump = ordered_tables + remaining_tables

        sql_lines = [
            "-- ============================================================================",
            f"-- LifeDrop (Ruby HeartBeat) Supabase Database Snapshot",
            f"-- Created at: {datetime.utcnow().isoformat()} UTC",
            "-- ============================================================================",
            "BEGIN;\n",
        ]

        for table in tables_to_dump:
            cols = insp.get_columns(table)
            pk = insp.get_pk_constraint(table)
            fks = insp.get_foreign_keys(table)

            db_data["tables"][table] = {
                "columns": [{
                    "name": c["name"],
                    "type": str(c["type"]),
                    "nullable": c.get("nullable", True),
                    "default": str(c.get("default", "")),
                } for c in cols],
                "primary_key": pk.get("constrained_columns", []),
                "foreign_keys": fks,
            }

            # Fetch rows
            rows = conn.execute(text(f'SELECT * FROM "{table}"')).mappings().all()
            row_dicts = [dict(r) for r in rows]
            db_data["data"][table] = row_dicts
            db_data["row_counts"][table] = len(row_dicts)

            # Generate SQL INSERT statements
            sql_lines.append(f"-- Table: {table} ({len(row_dicts)} rows)")
            if row_dicts:
                col_names = [f'"{c["name"]}"' for c in cols]
                cols_str = ", ".join(col_names)

                for r in row_dicts:
                    val_strs = []
                    for c in cols:
                        v = r.get(c["name"])
                        if v is None:
                            val_strs.append("NULL")
                        elif isinstance(v, (int, float, Decimal)):
                            val_strs.append(str(v))
                        elif isinstance(v, bool):
                            val_strs.append("TRUE" if v else "FALSE")
                        elif isinstance(v, (datetime, date)):
                            val_strs.append(f"'{v.isoformat()}'")
                        elif isinstance(v, uuid.UUID):
                            val_strs.append(f"'{str(v)}'")
                        else:
                            # String / text: escape single quotes
                            escaped = str(v).replace("'", "''")
                            val_strs.append(f"'{escaped}'")

                    sql_lines.append(f'INSERT INTO "{table}" ({cols_str}) VALUES ({", ".join(val_strs)}) ON CONFLICT DO NOTHING;')
            sql_lines.append("")

        sql_lines.append("COMMIT;\n")

    # Write JSON files
    with open(snapshot_json_path, "w", encoding="utf-8") as f:
        json.dump(db_data, f, cls=CustomEncoder, indent=2)

    with open(snapshot_latest_json, "w", encoding="utf-8") as f:
        json.dump(db_data, f, cls=CustomEncoder, indent=2)

    # Write SQL files
    with open(snapshot_sql_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sql_lines))

    with open(snapshot_latest_sql, "w", encoding="utf-8") as f:
        f.write("\n".join(sql_lines))

    print("=========================================================")
    print(f"DATABASE SNAPSHOT SAVED SUCCESSFULLY!")
    print(f"JSON Snapshot : {snapshot_json_path}")
    print(f"Latest JSON   : {snapshot_latest_json}")
    print(f"SQL Dump      : {snapshot_sql_path}")
    print(f"Latest SQL    : {snapshot_latest_sql}")
    print("---------------------------------------------------------")
    print("Row counts by table:")
    for t, count in db_data["row_counts"].items():
        print(f"  - {t:<22}: {count:>5} rows")
    total_rows = sum(db_data["row_counts"].values())
    print(f"  TOTAL ROWS            : {total_rows:>5} rows")
    print("=========================================================")
    return snapshot_latest_json


if __name__ == "__main__":
    create_snapshot()
