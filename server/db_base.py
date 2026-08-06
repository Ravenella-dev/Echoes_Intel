"""
db_base.py  —  Database connection + table creation / seeding.

This is the shared foundation for every database module. It provides:

* `_db_conn()` — open a MySQL connection using the settings in config.py.
* `db_init()`  — create all tables if missing and seed example data on
                 the very first run (only when a table is empty).

Every other db_* module (db.py, bounties.py, users.py) imports
`_db_conn` from here so the connection logic lives in exactly one place.
"""

import json
from datetime import datetime, timezone

import pymysql

from .config import (
    DB_CONFIG, EXAMPLE_PLAYERS, EXAMPLE_BOUNTIES,
    ACCESS_LEVELS, MASTER_LEVEL,
    generate_password, hash_password, _log,
)


def _db_conn():
    """Open and return a new MySQL connection (autocommit on)."""
    return pymysql.connect(**DB_CONFIG)


# SQL for every table, grouped so the schema is easy to scan.
# Using CREATE TABLE IF NOT EXISTS means this is safe to run on every
# startup — existing tables are left untouched.
_TABLE_SQL = [
    # Pilots are stored as one JSON blob per row (the `data` column).
    """CREATE TABLE IF NOT EXISTS players (
        id   VARCHAR(64) PRIMARY KEY,
        data LONGTEXT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # Generic key/value store (tagCategories, savedAt, etc.).
    """CREATE TABLE IF NOT EXISTS meta (
        `key`   VARCHAR(64) PRIMARY KEY,
        value   LONGTEXT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # Bounties placed on pilots (multiple per target = multi-contributor).
    """CREATE TABLE IF NOT EXISTS bounties (
        id                INT AUTO_INCREMENT PRIMARY KEY,
        target_player_id  VARCHAR(64) NOT NULL,
        target_name       VARCHAR(128) NOT NULL,
        issuer_name       VARCHAR(128) NOT NULL,
        issuer_corp       VARCHAR(128) NOT NULL DEFAULT '',
        issuer_discord    VARCHAR(128) NOT NULL DEFAULT '',
        broker_name       VARCHAR(128) NOT NULL DEFAULT '',
        broker_discord    VARCHAR(128) NOT NULL DEFAULT '',
        is_masked         TINYINT(1) NOT NULL DEFAULT 0,
        amount            BIGINT NOT NULL DEFAULT 0,
        created_at        VARCHAR(40) NOT NULL,
        updated_at        VARCHAR(40) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # Snapshot of total bounty per target, recorded on each change.
    """CREATE TABLE IF NOT EXISTS bounty_history (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        target_name   VARCHAR(128) NOT NULL,
        total_amount  BIGINT NOT NULL DEFAULT 0,
        logged_at     VARCHAR(40) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # User accounts (bcrypt-hashed passwords + access level).
    """CREATE TABLE IF NOT EXISTS users (
        id             INT AUTO_INCREMENT PRIMARY KEY,
        username       VARCHAR(64) NOT NULL UNIQUE,
        password_hash  VARCHAR(255) NOT NULL,
        access_level   VARCHAR(16) NOT NULL DEFAULT 'viewer',
        created_at     VARCHAR(40) NOT NULL,
        updated_at     VARCHAR(40) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # Login sessions (bearer tokens with an expiry).
    """CREATE TABLE IF NOT EXISTS sessions (
        token        VARCHAR(128) PRIMARY KEY,
        user_id      INT NOT NULL,
        created_at   VARCHAR(40) NOT NULL,
        expires_at   VARCHAR(40) NOT NULL,
        INDEX idx_sessions_user (user_id),
        INDEX idx_sessions_expires (expires_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # Audit trail of player/bounty changes (master actions excluded).
    """CREATE TABLE IF NOT EXISTS change_log (
        id             INT AUTO_INCREMENT PRIMARY KEY,
        entity_type    VARCHAR(16) NOT NULL,
        entity_id      VARCHAR(64) NOT NULL,
        action         VARCHAR(16) NOT NULL,
        snapshot_before LONGTEXT,
        snapshot_after  LONGTEXT,
        changed_by     VARCHAR(64) NOT NULL DEFAULT '',
        changed_by_id  INT NULL,
        changed_at     VARCHAR(40) NOT NULL,
        reverted       TINYINT(1) NOT NULL DEFAULT 0,
        INDEX idx_changelog_entity (entity_type, entity_id),
        INDEX idx_changelog_time (changed_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


def _seed_players(cur):
    """Insert example pilots + tag metadata, but only if the table is empty."""
    cur.execute("SELECT COUNT(*) FROM players")
    if cur.fetchone()[0] != 0:
        return
    for p in EXAMPLE_PLAYERS:
        cur.execute(
            "INSERT INTO players (id, data) VALUES (%s, %s)",
            (p["id"], json.dumps(p, ensure_ascii=False)),
        )
    # tagCategories is read from data/players.json (the canonical source
    # of tag colour/icon metadata) when available.
    from .config import ROOT
    data_file = ROOT / "data" / "players.json"
    tc = {}
    if data_file.is_file():
        tc = json.loads(data_file.read_text("utf-8")).get("tagCategories", {})
    cur.execute(
        "INSERT INTO meta (`key`, value) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE value=VALUES(value)",
        ("tagCategories", json.dumps(tc, ensure_ascii=False)),
    )
    cur.execute(
        "INSERT INTO meta (`key`, value) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE value=VALUES(value)",
        ("savedAt", datetime.now(timezone.utc).isoformat()),
    )
    _log(f"Seeded MySQL with {len(EXAMPLE_PLAYERS)} example players")


def _seed_bounties(cur):
    """Insert example bounties, but only if the table is empty."""
    cur.execute("SELECT COUNT(*) FROM bounties")
    if cur.fetchone()[0] != 0 or not EXAMPLE_BOUNTIES:
        return
    # Local import to avoid a circular import at module load
    # (bounties.py imports _db_conn from this module).
    from .bounties import _log_bounty_history
    now = datetime.now(timezone.utc).isoformat()
    for b in EXAMPLE_BOUNTIES:
        cur.execute(
            "INSERT INTO bounties (target_player_id, target_name, "
            "issuer_name, issuer_corp, issuer_discord, "
            "broker_name, broker_discord, is_masked, amount, "
            "created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                b["target_player_id"], b["target_name"],
                b["issuer_name"], b["issuer_corp"], b["issuer_discord"],
                b["broker_name"], b["broker_discord"],
                1 if b["is_masked"] else 0, b["amount"],
                now, now,
            ),
        )
    _log_bounty_history(cur)
    _log(f"Seeded MySQL with {len(EXAMPLE_BOUNTIES)} example bounties")


def _seed_master_user(cur):
    """Create the single master account on first run with a random
    password that is printed once to the log (never stored in source)."""
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] != 0:
        return
    now = datetime.now(timezone.utc).isoformat()
    master_pw = generate_password()
    cur.execute(
        "INSERT INTO users (username, password_hash, access_level, "
        "created_at, updated_at) VALUES (%s, %s, %s, %s, %s)",
        ("master", hash_password(master_pw), MASTER_LEVEL, now, now),
    )
    _log("=" * 64)
    _log("MASTER ACCOUNT CREATED")
    _log("  username: master")
    _log(f"  password: {master_pw}")
    _log("  (This password is shown only once. Store it safely.)")
    _log("  Log in, then change it or create other users via the UI.")
    _log("=" * 64)


def _migrate(cur):
    """Apply small schema fixes for databases created by older versions.

    These are idempotent ALTER statements guarded by an information-schema
    check, so they run harmlessly on every startup whether or not the fix
    is needed.
    """
    # --- users.updated_at was missing in very early deployments ---
    cur.execute(
        """
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'users'
          AND COLUMN_NAME  = 'updated_at'
        """
    )
    if cur.fetchone()[0] == 0:
        _log("Migration: adding users.updated_at column")
        cur.execute(
            "ALTER TABLE users "
            "ADD COLUMN updated_at VARCHAR(40) NOT NULL DEFAULT '' "
            "AFTER created_at"
        )

    # --- bounties.updated_at (same early-deployment issue) ---
    cur.execute(
        """
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'bounties'
          AND COLUMN_NAME  = 'updated_at'
        """
    )
    if cur.fetchone()[0] == 0:
        _log("Migration: adding bounties.updated_at column")
        cur.execute(
            "ALTER TABLE bounties "
            "ADD COLUMN updated_at VARCHAR(40) NOT NULL DEFAULT '' "
            "AFTER created_at"
        )


def db_init():
    """Create tables if missing, run migrations, and seed example data."""
    conn = _db_conn()
    cur = conn.cursor()
    for sql in _TABLE_SQL:
        cur.execute(sql)
    _migrate(cur)
    _seed_players(cur)
    _seed_bounties(cur)
    _seed_master_user(cur)
    conn.close()
