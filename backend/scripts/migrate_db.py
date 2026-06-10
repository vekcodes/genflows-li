"""Copy the Raw Lake between databases — e.g. local SQLite -> hosted Postgres (Neon/Supabase).

One-shot, run from backend/ with the venv python:

  .venv\\Scripts\\python.exe scripts\\migrate_db.py ^
      --source "sqlite:///./brain.db" ^
      --target "postgresql://USER:PASSWORD@HOST/dbname?sslmode=require"

Copies every table in FK-safe order, preserving ids, then bumps Postgres sequences past the
copied max ids so future inserts don't collide. --wipe clears target tables first (safe to
re-run). Requires psycopg2-binary in the venv:  .venv\\Scripts\\pip install psycopg2-binary
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import Integer, create_engine, text  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app import models  # noqa: E402, F401 - registers all tables on SQLModel.metadata

BATCH = 1000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, help="source DB URL (e.g. sqlite:///./brain.db)")
    ap.add_argument("--target", required=True, help="target DB URL (e.g. postgresql://...)")
    ap.add_argument("--wipe", action="store_true", help="delete existing target rows first")
    args = ap.parse_args()

    src = create_engine(args.source)
    dst = create_engine(args.target)
    SQLModel.metadata.create_all(dst)

    tables = SQLModel.metadata.sorted_tables  # FK-safe insert order
    with src.connect() as s:
        if args.wipe:
            with dst.begin() as d:
                for table in reversed(tables):
                    d.execute(table.delete())

        for table in tables:
            rows = [dict(r._mapping) for r in s.execute(table.select())]
            with dst.begin() as d:
                for i in range(0, len(rows), BATCH):
                    d.execute(table.insert(), rows[i : i + BATCH])
            print(f"{table.name}: {len(rows)} rows")

    # Postgres keeps autoincrement state in sequences; advance them past the copied ids.
    if args.target.startswith(("postgres", "postgresql")):
        with dst.begin() as d:
            for table in tables:
                pks = list(table.primary_key.columns)
                if len(pks) == 1 and isinstance(pks[0].type, Integer):
                    col = pks[0].name
                    try:
                        d.execute(text(
                            f"SELECT setval(pg_get_serial_sequence('{table.name}', '{col}'), "
                            f"COALESCE((SELECT MAX({col}) FROM {table.name}), 1))"
                        ))
                    except Exception as exc:  # noqa: BLE001 - non-serial int PKs have no sequence
                        print(f"  (sequence skip for {table.name}.{col}: {exc})")
        print("sequences advanced")

    print("done — point BRAIN_DATABASE_URL at the target and restart/redeploy")


if __name__ == "__main__":
    main()
