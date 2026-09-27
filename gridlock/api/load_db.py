from __future__ import annotations

import argparse
import csv
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "gridlock.db"


def load_csv(conn: sqlite3.Connection, table: str, path: Path) -> None:
    if not path.exists():
        if table == "briefs":
            rows = []
            columns = [
                "overlap_id",
                "shared_corridor_mi",
                "row_width_ft",
                "shared_acres",
                "land_cost_per_acre_usd",
                "est_land_savings_usd",
                "assumptions_note",
                "narrative",
            ]
        else:
            raise FileNotFoundError(path)
    else:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            columns = reader.fieldnames or []

    conn.execute(f"DROP TABLE IF EXISTS {table}")
    column_sql = ", ".join([f'"{col}" TEXT' for col in columns])
    conn.execute(f"CREATE TABLE {table} ({column_sql})")
    if rows:
        placeholders = ", ".join(["?"] * len(columns))
        quoted = ", ".join([f'"{col}"' for col in columns])
        conn.executemany(
            f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})",
            [[row.get(col, "") for col in columns] for row in rows],
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["fixtures", "processed"], default="fixtures")
    args = parser.parse_args()

    source_dir = ROOT / "data" / args.source
    # Build the new database beside the live one and swap it in, so readers never see half-loaded tables.
    tmp_path = DB_PATH.with_name(DB_PATH.name + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    try:
        conn = sqlite3.connect(tmp_path)
        try:
            with conn:
                load_csv(conn, "projects", source_dir / "projects.csv")
                load_csv(conn, "overlaps", source_dir / "overlaps.csv")
                load_csv(conn, "briefs", source_dir / "briefs.csv")
        finally:
            conn.close()
        os.replace(tmp_path, DB_PATH)
    except BaseException:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    print(f"Loaded {args.source} CSVs into {DB_PATH}")


if __name__ == "__main__":
    main()
