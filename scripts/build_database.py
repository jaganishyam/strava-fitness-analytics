"""
build_database.py
-----------------
Step 1 of the pipeline: load the raw FitBit CSVs into SQLite, then run the
SQL cleaning script to produce analysis-ready tables.

    python scripts/build_database.py

Input : ./Data Files/*.csv                (raw Fitabase export, 12 Apr - 12 May 2016)
Output: ./database/strava_fitness.db     (clean tables only, small enough for GitHub)

Why Python for the load step?
SQLite has no built-in parser for timestamps like "4/12/2016 7:21:05 AM".
So on load we only convert those strings to ISO format ("2016-04-12 07:21:05").
Every other cleaning rule (duplicates, non-wear days, derived columns,
aggregation, joins) is done in SQL -> sql/01_data_cleaning.sql
"""

import sqlite3
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "Data Files"
DB_PATH = ROOT / "database" / "strava_fitness.db"
CLEANING_SQL = ROOT / "sql" / "01_data_cleaning.sql"

# raw table name -> (csv file, timestamp column, has time-of-day?)
RAW_FILES = {
    "raw_daily_activity":    ("dailyActivity_merged.csv",      "ActivityDate", False),
    "raw_sleep_day":         ("sleepDay_merged.csv",           "SleepDay",     False),
    "raw_weight_log":        ("weightLogInfo_merged.csv",      "Date",         True),
    "raw_hourly_steps":      ("hourlySteps_merged.csv",        "ActivityHour", True),
    "raw_hourly_calories":   ("hourlyCalories_merged.csv",     "ActivityHour", True),
    "raw_hourly_intensities":("hourlyIntensities_merged.csv",  "ActivityHour", True),
    "raw_minute_sleep":      ("minuteSleep_merged.csv",        "date",         True),
    "raw_heartrate_seconds": ("heartrate_seconds_merged.csv",  "Time",         True),
}

DATE_FMT = "%m/%d/%Y"
DATETIME_FMT = "%m/%d/%Y %I:%M:%S %p"


def to_iso(series: pd.Series, has_time: bool) -> pd.Series:
    """Convert '4/12/2016 7:21:05 AM' -> '2016-04-12 07:21:05' (or date only)."""
    if has_time:
        return pd.to_datetime(series, format=DATETIME_FMT).dt.strftime("%Y-%m-%d %H:%M:%S")
    # daily files sometimes carry a '12:00:00 AM' suffix - keep the date part only
    return pd.to_datetime(series.str.split(" ").str[0], format=DATE_FMT).dt.strftime("%Y-%m-%d")


def load_raw(conn: sqlite3.Connection) -> None:
    for table, (csv_name, ts_col, has_time) in RAW_FILES.items():
        path = RAW_DIR / csv_name
        if not path.exists():
            raise FileNotFoundError(f"Missing raw file: {path}")
        start = time.time()
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        rows = 0
        # chunked read keeps memory low for the 2.5M-row heart-rate file
        for chunk in pd.read_csv(path, chunksize=500_000):
            chunk[ts_col] = to_iso(chunk[ts_col].astype(str), has_time)
            chunk.to_sql(table, conn, if_exists="append", index=False)
            rows += len(chunk)
        print(f"  loaded {table:<24} {rows:>10,} rows  ({time.time() - start:.1f}s)")


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    print("1) Loading raw CSVs ...")
    load_raw(conn)

    print("2) Running SQL cleaning script ...")
    conn.executescript(CLEANING_SQL.read_text(encoding="utf-8"))

    print("3) Dropping raw staging tables and compacting ...")
    raw_tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'raw_%'")]
    for t in raw_tables:
        conn.execute(f"DROP TABLE {t}")
    conn.commit()
    conn.execute("VACUUM")

    print("\nClean tables:")
    for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        n = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name:<24} {n:>8,} rows")
    conn.close()
    print(f"\nDone -> {DB_PATH.relative_to(ROOT)} ({DB_PATH.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
