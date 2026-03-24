"""
SQLite → PostgreSQL Data Migration Script

Usage:
    1. Set POSTGRES_URL env var to the target PostgreSQL connection string
    2. Ensure micro_saas.db exists in the project root
    3. Run: python scripts/migrate_sqlite_to_postgres.py

This reads all data from the local SQLite database and inserts it into
the PostgreSQL database. Run Alembic migrations on PostgreSQL FIRST to
create the schema before running this script.

Tables migrated (18 total):
  users, user_preferences, subscriptions, credit_transactions,
  blueprints, audit_jobs, gst_reconciliations, gstr9_reconciliations,
  bank_statement_analyses, capital_gains_analyses, depreciation_analyses,
  advance_tax_computations, clients, client_documents, tax_deadlines,
  user_reminders, notice_jobs, reference_cache, feedbacks
"""

import os
import sys
import sqlite3
import logging
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Order matters: parent tables before children (FK constraints)
TABLES_IN_ORDER = [
    "users",
    "user_preferences",
    "subscriptions",
    "credit_transactions",
    "blueprints",
    "audit_jobs",
    "gst_reconciliations",
    "gstr9_reconciliations",
    "bank_statement_analyses",
    "capital_gains_analyses",
    "depreciation_analyses",
    "advance_tax_computations",
    "clients",
    "client_documents",
    "tax_deadlines",
    "user_reminders",
    "notice_jobs",
    "reference_cache",
    "feedbacks",
]


def get_sqlite_connection(db_path: str) -> sqlite3.Connection:
    if not Path(db_path).exists():
        logger.error(f"SQLite database not found: {db_path}")
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_postgres_connection(pg_url: str):
    """Parse asyncpg-style URL and connect with psycopg2."""
    # Convert asyncpg URL to psycopg2 format
    url = pg_url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def get_table_columns(sqlite_conn: sqlite3.Connection, table: str) -> list[str]:
    cursor = sqlite_conn.execute(f"PRAGMA table_info({table})")
    return [row["name"] for row in cursor.fetchall()]


def migrate_table(sqlite_conn: sqlite3.Connection, pg_conn, table: str) -> int:
    """Migrate a single table from SQLite to PostgreSQL. Returns row count."""
    columns = get_table_columns(sqlite_conn, table)
    if not columns:
        logger.warning(f"  Table '{table}' not found in SQLite — skipping")
        return 0

    # Read all rows from SQLite
    cursor = sqlite_conn.execute(f"SELECT * FROM {table}")
    rows = cursor.fetchall()

    if not rows:
        logger.info(f"  {table}: 0 rows (empty)")
        return 0

    # Convert sqlite3.Row objects to tuples
    data = [tuple(row) for row in rows]

    # Build INSERT query with ON CONFLICT DO NOTHING to handle duplicates
    col_list = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))

    pg_cursor = pg_conn.cursor()

    # Disable triggers temporarily for bulk insert (avoids FK timing issues)
    try:
        pg_cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER ALL")

        insert_sql = f'INSERT INTO {table} ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'
        pg_cursor.executemany(insert_sql, data)

        pg_cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER ALL")

        inserted = pg_cursor.rowcount
        logger.info(f"  {table}: {len(data)} rows read, {inserted} inserted")
        return len(data)
    except Exception as e:
        pg_conn.rollback()
        logger.error(f"  {table}: FAILED — {e}")
        raise


def reset_sequences(pg_conn):
    """Reset PostgreSQL sequences to max(id) + 1 for all tables with serial/identity PKs."""
    pg_cursor = pg_conn.cursor()
    pg_cursor.execute("""
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE column_default LIKE 'nextval%'
          AND table_schema = 'public'
    """)
    for table_name, column_name in pg_cursor.fetchall():
        try:
            pg_cursor.execute(f"SELECT MAX({column_name}) FROM {table_name}")
            max_val = pg_cursor.fetchone()[0]
            if max_val is not None:
                pg_cursor.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table_name}', '{column_name}'), {max_val})"
                )
                logger.info(f"  Sequence for {table_name}.{column_name} reset to {max_val}")
        except Exception as e:
            logger.warning(f"  Could not reset sequence for {table_name}.{column_name}: {e}")


def main():
    sqlite_path = os.getenv("SQLITE_PATH", "micro_saas.db")
    pg_url = os.getenv("POSTGRES_URL")

    if not pg_url:
        logger.error("Set POSTGRES_URL environment variable (e.g., postgresql://user:pass@host/dbname)")
        sys.exit(1)

    logger.info(f"Source: {sqlite_path}")
    logger.info(f"Target: {pg_url.split('@')[0]}@***")  # hide password in logs

    sqlite_conn = get_sqlite_connection(sqlite_path)
    pg_conn = get_postgres_connection(pg_url)

    total_rows = 0
    try:
        for table in TABLES_IN_ORDER:
            total_rows += migrate_table(sqlite_conn, pg_conn, table)

        # Reset auto-increment sequences
        logger.info("Resetting PostgreSQL sequences...")
        reset_sequences(pg_conn)

        pg_conn.commit()
        logger.info(f"\nMigration complete! {total_rows} total rows migrated.")
    except Exception as e:
        pg_conn.rollback()
        logger.error(f"Migration failed: {e}")
        sys.exit(1)
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    main()
