#!/usr/bin/env python3
"""
CNP EPIC-02 — P2-04
migrate.py — V1 → V2 SQLite schema migration CLI.

Usage:
    python migrate.py --source ./codessa_registry.db [--dry-run] [--rollback]

Flags:
    --source PATH     Path to the V1 SQLite database to migrate.
    --dry-run         Print planned DDL, run in a transaction, then ROLLBACK.
                      Validates syntax and reports row counts without writing.
    --rollback        Restore from the snapshot taken by the last run.
    --snapshot PATH   Where to save/load the backup snapshot.
                      Defaults to <source>.snapshot.db
    --verbose         Print each DDL statement before executing.

Exit codes:
    0   Success
    1   Migration failed (details on stderr)
    2   Integrity check failed
    3   Rollback target not found
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MIGRATION_SQL = Path(__file__).parent / "migrations" / "003_v1_to_v2_schema.sql"
_INDENT = "  "


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def _err(msg: str) -> None:
    print(f"[{_now()}] ERROR  {msg}", file=sys.stderr, flush=True)


# ----------------------------------------------------------------
#  Pre-migration row count snapshot
# ----------------------------------------------------------------

def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    for (name,) in cursor.fetchall():
        try:
            (count,) = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()
            counts[name] = count
        except sqlite3.Error:
            counts[name] = -1
    return counts


def _print_counts(pre: dict[str, int], post: dict[str, int]) -> None:
    all_tables = sorted(set(pre) | set(post))
    _log("Per-table row counts:")
    for t in all_tables:
        p = pre.get(t, 0)
        a = post.get(t, p)
        delta = a - p
        delta_str = f" (+{delta})" if delta > 0 else (f" ({delta})" if delta < 0 else "")
        print(f"{_INDENT}{t:<30} {p:>8} → {a:>8}{delta_str}")


# ----------------------------------------------------------------
#  Integrity check
# ----------------------------------------------------------------

def _integrity_check(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("PRAGMA integrity_check").fetchall()
    if rows == [("ok",)]:
        return []
    return [r[0] for r in rows]


def _spot_check(
    conn: sqlite3.Connection,
    pre: dict[str, int],
    post: dict[str, int],
) -> list[str]:
    issues = []
    for table, pre_count in pre.items():
        post_count = post.get(table, 0)
        if post_count < pre_count:
            issues.append(
                f"Table {table}: row count decreased {pre_count} → {post_count}"
            )
    return issues


# ----------------------------------------------------------------
#  Migration runner
# ----------------------------------------------------------------

def _run_migration(
    conn: sqlite3.Connection,
    sql: str,
    verbose: bool,
    dry_run: bool,
) -> None:
    """Execute migration SQL. On dry_run, wraps in a savepoint and rolls back."""
    statements = [s.strip() for s in sql.split(";") if s.strip()]

    if dry_run:
        conn.execute("SAVEPOINT migration_dry_run")

    for stmt in statements:
        if not stmt or stmt.startswith("--"):
            continue
        if verbose:
            print(f"{_INDENT}> {stmt[:120]}{'...' if len(stmt) > 120 else ''}")
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            # ALTER TABLE ADD COLUMN IF NOT EXISTS requires SQLite 3.37+
            # Gracefully skip "duplicate column" errors for older SQLite
            if "duplicate column name" in str(exc).lower():
                if verbose:
                    print(f"{_INDENT}  (column already exists — skipping)")
            else:
                raise

    if dry_run:
        conn.execute("ROLLBACK TO SAVEPOINT migration_dry_run")
        conn.execute("RELEASE SAVEPOINT migration_dry_run")


# ----------------------------------------------------------------
#  CLI entry point
# ----------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="CNP V1 → V2 SQLite schema migration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", required=True, help="Path to V1 SQLite DB")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate and report without writing changes",
    )
    parser.add_argument(
        "--rollback", action="store_true",
        help="Restore from snapshot instead of migrating",
    )
    parser.add_argument("--snapshot", default=None, help="Override snapshot path")
    parser.add_argument("--verbose", action="store_true", help="Print each statement")
    args = parser.parse_args()

    source = Path(args.source)
    snapshot = Path(args.snapshot) if args.snapshot else source.with_suffix(".snapshot.db")

    # ---- Rollback path ----
    if args.rollback:
        if not snapshot.exists():
            _err(f"Snapshot not found: {snapshot}")
            return 3
        _log(f"Rolling back {source} from {snapshot} …")
        shutil.copy2(snapshot, source)
        _log("Rollback complete.")
        return 0

    if not source.exists():
        _err(f"Source database not found: {source}")
        return 1

    if not MIGRATION_SQL.exists():
        _err(f"Migration SQL not found: {MIGRATION_SQL}")
        return 1

    sql = MIGRATION_SQL.read_text(encoding="utf-8")

    # ---- Snapshot (skip on dry-run) ----
    if not args.dry_run:
        _log(f"Creating rollback snapshot → {snapshot}")
        shutil.copy2(source, snapshot)

    conn = sqlite3.connect(str(source))
    conn.row_factory = sqlite3.Row

    pre_counts = _row_counts(conn)
    _log(f"Pre-migration row counts captured ({len(pre_counts)} tables)")

    t0 = time.perf_counter()
    mode = "DRY-RUN" if args.dry_run else "LIVE"
    _log(f"Running migration [{mode}] …")

    try:
        _run_migration(conn, sql, verbose=args.verbose, dry_run=args.dry_run)
        if not args.dry_run:
            conn.commit()
    except Exception as exc:
        _err(f"Migration failed: {exc}")
        conn.close()
        return 1

    elapsed = time.perf_counter() - t0

    post_counts = _row_counts(conn)
    _print_counts(pre_counts, post_counts)

    # ---- Integrity check (skip on dry-run — data was rolled back) ----
    if not args.dry_run:
        _log("Running integrity check …")
        issues = _integrity_check(conn)
        if issues:
            _err(f"Integrity check FAILED: {issues}")
            conn.close()
            return 2

        spot = _spot_check(conn, pre_counts, post_counts)
        if spot:
            _err(f"Row count regression: {spot}")
            conn.close()
            return 2

        _log("Integrity check PASSED.")
    else:
        _log("Dry-run complete — no changes written.")

    conn.close()
    _log(f"Migration finished in {elapsed:.2f}s [{mode}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
