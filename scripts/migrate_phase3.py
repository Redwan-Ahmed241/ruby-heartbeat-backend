"""Migration script for Phase 3: Blood Request Schema & Lifecycle Statuses.
Safely adds columns to blood_requests and enum values to request_status_enum.
"""
import os
import sys

sys.path.insert(0, os.path.abspath("."))

from sqlalchemy import create_engine, text, inspect
from app.core.config import Settings

settings = Settings()
engine = create_engine(settings.DATABASE_URL)


def run_migration():
    print("Connecting to database...")

    # 1. Add new enum values to request_status_enum
    # PostgreSQL requires ALTER TYPE ... ADD VALUE to run outside transaction blocks
    new_enum_values = ["OPEN", "ACCEPTED", "PROCESSING"]
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for val in new_enum_values:
            try:
                conn.execute(text(f"ALTER TYPE request_status_enum ADD VALUE IF NOT EXISTS '{val}'"))
                print(f"  Enum value '{val}' ensured in request_status_enum.")
            except Exception as e:
                print(f"  Notice adding enum '{val}': {e}")

    # 2. Add new columns to blood_requests table
    columns_to_add = [
        ("patient_name", "VARCHAR(100)"),
        ("hospital_name", "VARCHAR(150)"),
        ("area_zone", "VARCHAR(100)"),
        ("attendant_phone_number", "VARCHAR(25)"),
        ("volume_ml", "NUMERIC(6, 2)"),
        ("accepted_donor_id", "UUID REFERENCES users(user_id) ON DELETE SET NULL"),
    ]

    with engine.begin() as conn:
        insp = inspect(conn)
        existing_cols = [c["name"] for c in insp.get_columns("blood_requests")]

        for col_name, col_type in columns_to_add:
            if col_name in existing_cols:
                print(f"  Column '{col_name}' already exists in blood_requests.")
            else:
                conn.execute(text(f'ALTER TABLE blood_requests ADD COLUMN IF NOT EXISTS "{col_name}" {col_type};'))
                print(f"  Column '{col_name}' ({col_type}) added successfully.")

    # 3. Verify changes
    with engine.connect() as conn:
        insp = inspect(conn)
        final_cols = [c["name"] for c in insp.get_columns("blood_requests")]
        print("\nVerification - Current columns on 'blood_requests':")
        for col in final_cols:
            print(f"  - {col}")

        res = conn.execute(text(
            "SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_enum.enumtypid = pg_type.oid "
            "WHERE pg_type.typname = 'request_status_enum' ORDER BY enumsortorder"
        )).fetchall()
        print("\nVerification - Current enum values on 'request_status_enum':")
        for r in res:
            print(f"  - {r[0]}")

    print("\nPhase 3 Database Migration Completed Successfully!")


if __name__ == "__main__":
    run_migration()

