#!/usr/bin/env python3
"""
EVE Echoes Intel DB — echoes.mobi scraping proxy + persistence server.

Security model
--------------
- User accounts are stored in the MySQL `users` table with bcrypt-hashed
  passwords and an access_level column (master / admin / editor / viewer).
- Authentication is session-based: POST /api/login verifies credentials
  against the DB and returns a session token. That token is sent on every
  subsequent request via the `Authorization: Bearer <token>` header.
- Write endpoints (players, bounties, changelog revert) require a valid
  session with a sufficient access_level.
- On first run a single "master" account is created with a randomly
  generated password. The password is printed once to the server log and
  is never stored in source. The master account can manage other users.
- Every change to players/bounties is recorded in the `change_log` table
  (before/after snapshot, who made the change, timestamp). Reversion is
  supported via POST /api/changelog/<id>/revert. Changes made by the
  master account are NOT logged.

Endpoints
---------
  GET  /api/scrape?player=NAME       (public)
  GET  /api/players                  (public read)
  POST /api/players                  (editor+  — replaces entire player set)
  GET  /api/bounties                 (public read)
  POST /api/bounties                 (editor+  — new bounty)
  PUT  /api/bounties/<id>            (editor+  — edit bounty)
  DELETE /api/bounties/<id>          (editor+  — delete bounty)
  POST /api/login                    (public   — { username, password })
  POST /api/logout                   (auth     — invalidate session)
  GET  /api/session                  (auth     — who am I + access level)
  GET  /api/users                    (master   — list users)
  POST /api/users                    (master   — create user)
  PUT  /api/users/<id>               (master   — update user / level / password)
  DELETE /api/users/<id>             (master   — delete user; cannot delete self/master)
  GET  /api/changelog                (admin+   — list changelog entries)
  POST /api/changelog/<id>/revert    (admin+   — revert an entity to its prior state)
  GET  /api/health                   (public)

Access levels (ascending capability):
  viewer  -> read only
  editor  -> viewer + add/edit/remove players & bounties
  admin   -> editor + view changelog + revert changes
  master  -> admin + manage users + changes by master are not logged

Run:  python3 server.py [--port 8000]  (then expose that port)

The server also serves the static frontend files (index.html, css/, js/, data/).
"""

import argparse
import json
import pymysql
import re
import sys
import secrets
import string
import html as html_lib
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone, timedelta

import bcrypt

ROOT = Path(__file__).resolve().parent
ECHOES_BASE = "https://echoes.mobi/killboard/view/player"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Access levels, ordered lowest -> highest capability.
ACCESS_LEVELS = ["viewer", "editor", "admin", "master"]
ACCESS_RANK = {lvl: i for i, lvl in enumerate(ACCESS_LEVELS)}
MASTER_LEVEL = "master"

# Session tokens live for this long.
SESSION_TTL_HOURS = 12


def _log(msg: str) -> None:
    print(f"[echoes-proxy] {msg}", flush=True)


# ---- Password hashing ----------------------------------------------------

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the plaintext password (utf-8, str-safe)."""
    pw = plain.encode("utf-8")
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plaintext matches the stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def generate_password(length: int = 20) -> str:
    """Generate a strong random password (letters, digits, punctuation subset)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    # secrets.choice is cryptographically secure
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---- Access level helpers ------------------------------------------------

def has_access(user_level: str, required_level: str) -> bool:
    """Return True if user_level >= required_level (by rank)."""
    return ACCESS_RANK.get(user_level, -1) >= ACCESS_RANK.get(required_level, 99)


# ---- MySQL config --------------------------------------------------------
# Database credentials MUST be supplied via environment variables. They are
# never hardcoded in source. The server will refuse to start if the required
# connection parameters are missing.
import os

_DB_HOST = os.environ.get("ECHOES_DB_HOST")
_DB_USER = os.environ.get("ECHOES_DB_USER")
_DB_PASS = os.environ.get("ECHOES_DB_PASS")
_DB_NAME = os.environ.get("ECHOES_DB_NAME")

def _missing_db_env():
    return [k for k, v in {
        "ECHOES_DB_HOST": _DB_HOST,
        "ECHOES_DB_USER": _DB_USER,
        "ECHOES_DB_PASS": _DB_PASS,
        "ECHOES_DB_NAME": _DB_NAME,
    }.items() if not v]

DB_CONFIG = {
    "host":     _DB_HOST,
    "user":     _DB_USER,
    "password": _DB_PASS,
    "database": _DB_NAME,
    "charset":  "utf8mb4",
    "autocommit": True,
}

# Two example pilots seeded on first run (only if the table is empty)
EXAMPLE_PLAYERS = [
    {
        "id": "p001", "name": "Badran", "corporation": "Snuffed Out",
        "alliance": "Snuffed Out", "faction": "", "region": "Fade",
        "tags": ["Dangerous", "Supercapital Pilot", "High Value Target", "Solo PVPer"],
        "threatLevel": 9, "killCount": 4821, "lossCount": 312,
        "iskDestroyed": 18420000000000, "iskLost": 980000000000,
        "efficiency": 94.9, "lastSeen": "2024-08-01", "status": "active",
        "typicalShips": [
            {"ship": "Naglfar", "role": "Dreadnought brawler",
             "fitting": ["3x 3500mm Railgun I", "2x Capital Shield Booster II",
                         "1x Warp Disruptor II", "2x Sensor Booster II"]},
            {"ship": "Thanatos", "role": "Carrier support",
             "fitting": ["3x Fighter Squadrons", "2x Capital Remote Armor Repairer",
                         "1x Drone Damage Amplifier II"]}
        ],
        "notes": "Known supercap hotdropper. Favorable trade record vs dreads.",
        "knownAlts": ["Badran_Alpha", "Badran_Scout"], "bounty": 5000000000
    },
    {
        "id": "p002", "name": "LunaStarlight", "corporation": "Dawn's Embrace",
        "alliance": "Fraternity.", "faction": "", "region": "Vale of the Silent",
        "tags": ["Weak", "Alt", "Logistics Pilot", "Low Value Target"],
        "threatLevel": 2, "killCount": 47, "lossCount": 89,
        "iskDestroyed": 120000000000, "iskLost": 340000000000,
        "efficiency": 22.6, "lastSeen": "2024-07-28", "status": "active",
        "typicalShips": [
            {"ship": "Scimitar", "role": "Logistics cruiser",
             "fitting": ["4x Medium Remote Shield Booster II",
                         "1x Large Shield Extender II", "2x Cap Power Relay II"]}
        ],
        "notes": "Logi alt for a main in Fraternity. Rarely flies solo.",
        "knownAlts": [], "bounty": 0
    },
]

# tagCategories is read from data/players.json on first run (kept as the
# canonical source of tag color/icon metadata).

# Example bounties seeded on first run (only if the bounties table is empty).
# Multiple bounties on the same target demonstrate the multi-contributor system.
EXAMPLE_BOUNTIES = [
    {
        "target_player_id": "p001", "target_name": "Badran",
        "issuer_name": "Dirtnap Jimmy", "issuer_corp": "Hard Knocks Inc.",
        "issuer_discord": "dirtnap#0420",
        "broker_name": "", "broker_discord": "",
        "is_masked": False, "amount": 3000000000,
    },
    {
        "target_player_id": "p001", "target_name": "Badran",
        "issuer_name": "Anonymous Client", "issuer_corp": "",
        "issuer_discord": "",
        "broker_name": "Kane Midfield", "broker_discord": "kane_mid#7788",
        "is_masked": True, "amount": 2000000000,
    },
    {
        "target_player_id": "p002", "target_name": "LunaStarlight",
        "issuer_name": "Vegas Lazer", "issuer_corp": "Snuffed Out",
        "issuer_discord": "vegas_lazer#1133",
        "broker_name": "", "broker_discord": "",
        "is_masked": False, "amount": 500000000,
    },
]


def _db_conn():
    return pymysql.connect(**DB_CONFIG)


def db_init():
    """Create tables if missing and seed example data on first run."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id   VARCHAR(64) PRIMARY KEY,
            data LONGTEXT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            `key`   VARCHAR(64) PRIMARY KEY,
            value   LONGTEXT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bounties (
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
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bounty_history (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            target_name   VARCHAR(128) NOT NULL,
            total_amount  BIGINT NOT NULL DEFAULT 0,
            logged_at     VARCHAR(40) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            username       VARCHAR(64) NOT NULL UNIQUE,
            password_hash  VARCHAR(255) NOT NULL,
            access_level   VARCHAR(16) NOT NULL DEFAULT 'viewer',
            created_at     VARCHAR(40) NOT NULL,
            updated_at     VARCHAR(40) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token        VARCHAR(128) PRIMARY KEY,
            user_id      INT NOT NULL,
            created_at   VARCHAR(40) NOT NULL,
            expires_at   VARCHAR(40) NOT NULL,
            INDEX idx_sessions_user (user_id),
            INDEX idx_sessions_expires (expires_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS change_log (
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
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cur.execute("SELECT COUNT(*) FROM players")
    count = cur.fetchone()[0]
    if count == 0:
        for p in EXAMPLE_PLAYERS:
            cur.execute(
                "INSERT INTO players (id, data) VALUES (%s, %s)",
                (p["id"], json.dumps(p, ensure_ascii=False)),
            )
        # seed tagCategories + savedAt from players.json if available
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

    # seed example bounties if the bounties table is empty
    cur.execute("SELECT COUNT(*) FROM bounties")
    bcount = cur.fetchone()[0]
    if bcount == 0 and EXAMPLE_BOUNTIES:
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
        # log an initial history point for each seeded target
        _log_bounty_history(cur)
        _log(f"Seeded MySQL with {len(EXAMPLE_BOUNTIES)} example bounties")

    # --- seed the master account on first run ---
    cur.execute("SELECT COUNT(*) FROM users")
    ucount = cur.fetchone()[0]
    if ucount == 0:
        now = datetime.now(timezone.utc).isoformat()
        master_pw = generate_password()
        cur.execute(
            "INSERT INTO users (username, password_hash, access_level, "
            "created_at, updated_at) VALUES (%s, %s, %s, %s, %s)",
            ("master", hash_password(master_pw), MASTER_LEVEL, now, now),
        )
        # The generated password is printed once to the server log so the
        # operator can log in and create/manage other users. It is never
        # written to source or to any file.
        _log("=" * 64)
        _log("MASTER ACCOUNT CREATED")
        _log("  username: master")
        _log(f"  password: {master_pw}")
        _log("  (This password is shown only once. Store it safely.)")
        _log("  Log in, then change it or create other users via the UI.")
        _log("=" * 64)
    conn.close()


def db_load():
    """Return {players: [...], tagCategories: {...}, savedAt: ...} from MySQL."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("SELECT data FROM players")
    players = [json.loads(r[0]) for r in cur.fetchall()]

    def meta(k, default):
        cur.execute("SELECT value FROM meta WHERE `key`=%s", (k,))
        row = cur.fetchone()
        if not row:
            return default
        v = row[0]
        return json.loads(v) if (k == "tagCategories" or v[:1] in "{[") else v

    out = {
        "players": players,
        "tagCategories": meta("tagCategories", {}),
        "savedAt": meta("savedAt", None),
        "bounties": db_bounty_load_all(),
        "bountyHistory": db_bounty_history(),
    }
    conn.close()
    return out


def db_save(players, actor=None):
    """Replace all players in MySQL. Returns savedAt timestamp.

    `actor` is a dict {id, username, access_level} or None. When provided
    and the actor is not the master account, the change is recorded in the
    change_log table (as a diff of the full set).
    """
    saved_at = datetime.now(timezone.utc).isoformat()
    conn = _db_conn()
    cur = conn.cursor()

    # capture before-state for changelog
    log_change = bool(actor) and actor.get("access_level") != MASTER_LEVEL
    before_ids = []
    before_map = {}
    if log_change:
        cur.execute("SELECT id, data FROM players")
        for pid, data in cur.fetchall():
            before_ids.append(pid)
            try:
                before_map[pid] = json.loads(data)
            except Exception:
                before_map[pid] = data

    cur.execute("DELETE FROM players")
    for p in players:
        cur.execute(
            "INSERT INTO players (id, data) VALUES (%s, %s)",
            (p.get("id") or p.get("name", ""), json.dumps(p, ensure_ascii=False)),
        )
    cur.execute(
        "INSERT INTO meta (`key`, value) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE value=VALUES(value)",
        ("savedAt", saved_at),
    )

    if log_change:
        after_map = {p.get("id") or p.get("name", ""): p for p in players}
        after_ids = list(after_map.keys())
        # log removals
        for pid in before_ids:
            if pid not in after_map:
                _log_change(cur, "player", pid, "remove",
                            before_map.get(pid), None,
                            actor["username"], actor["id"])
        # log additions + edits
        for pid, p in after_map.items():
            if pid not in before_map:
                _log_change(cur, "player", pid, "add", None, p,
                            actor["username"], actor["id"])
            elif before_map.get(pid) != p:
                _log_change(cur, "player", pid, "edit",
                            before_map.get(pid), p,
                            actor["username"], actor["id"])

    conn.close()
    _log(f"Saved {len(players)} players to MySQL")
    return saved_at


# ---- Bounty helpers ------------------------------------------------------

_BOUNTY_COLS = (
    "id, target_player_id, target_name, issuer_name, issuer_corp, "
    "issuer_discord, broker_name, broker_discord, is_masked, amount, "
    "created_at, updated_at"
)


def _row_to_bounty(row):
    return {
        "id": row[0],
        "target_player_id": row[1],
        "target_name": row[2],
        "issuer_name": row[3],
        "issuer_corp": row[4],
        "issuer_discord": row[5],
        "broker_name": row[6],
        "broker_discord": row[7],
        "is_masked": bool(row[8]),
        "amount": int(row[9]),
        "created_at": row[10],
        "updated_at": row[11],
    }


def _log_bounty_history(cur):
    """Insert one history row per target_name with the current total bounty."""
    cur.execute(
        "SELECT target_name, COALESCE(SUM(amount),0) FROM bounties GROUP BY target_name"
    )
    now = datetime.now(timezone.utc).isoformat()
    for target_name, total in cur.fetchall():
        cur.execute(
            "INSERT INTO bounty_history (target_name, total_amount, logged_at) "
            "VALUES (%s, %s, %s)",
            (target_name, int(total), now),
        )


def db_bounty_load_all():
    """Return a list of all bounty dicts."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT {_BOUNTY_COLS} FROM bounties ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return [_row_to_bounty(r) for r in rows]


def db_bounty_history():
    """Return { target_name: [ {ts, total}, ... ] } sorted by time."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT target_name, total_amount, logged_at "
        "FROM bounty_history ORDER BY target_name, logged_at"
    )
    out = {}
    for target_name, total, logged_at in cur.fetchall():
        out.setdefault(target_name, []).append({
            "ts": logged_at, "total": int(total),
        })
    conn.close()
    return out


def db_bounty_add(bounty, actor=None):
    """Insert a new bounty and log a history point. Returns the bounty dict."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO bounties (target_player_id, target_name, "
        "issuer_name, issuer_corp, issuer_discord, "
        "broker_name, broker_discord, is_masked, amount, "
        "created_at, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            bounty.get("target_player_id", ""),
            bounty.get("target_name", ""),
            bounty.get("issuer_name", ""),
            bounty.get("issuer_corp", ""),
            bounty.get("issuer_discord", ""),
            bounty.get("broker_name", ""),
            bounty.get("broker_discord", ""),
            1 if bounty.get("is_masked") else 0,
            int(bounty.get("amount", 0)),
            now, now,
        ),
    )
    new_id = cur.lastrowid
    _log_bounty_history(cur)
    if actor and actor.get("access_level") != MASTER_LEVEL:
        created = db_bounty_get(new_id)
        _log_change(cur, "bounty", new_id, "add", None, created,
                    actor["username"], actor["id"])
    conn.close()
    _log(f"Added bounty #{new_id} on {bounty.get('target_name')}")
    return db_bounty_get(new_id)


def db_bounty_get(bounty_id):
    """Return a single bounty dict by id, or None."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT {_BOUNTY_COLS} FROM bounties WHERE id=%s", (bounty_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_bounty(row) if row else None


def db_bounty_update(bounty_id, bounty, actor=None):
    """Update an existing bounty and log a history point. Returns the bounty dict."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _db_conn()
    cur = conn.cursor()
    before = db_bounty_get(bounty_id) if (actor and actor.get("access_level") != MASTER_LEVEL) else None
    cur.execute(
        "UPDATE bounties SET "
        "target_player_id=%s, target_name=%s, "
        "issuer_name=%s, issuer_corp=%s, issuer_discord=%s, "
        "broker_name=%s, broker_discord=%s, is_masked=%s, amount=%s, "
        "updated_at=%s WHERE id=%s",
        (
            bounty.get("target_player_id", ""),
            bounty.get("target_name", ""),
            bounty.get("issuer_name", ""),
            bounty.get("issuer_corp", ""),
            bounty.get("issuer_discord", ""),
            bounty.get("broker_name", ""),
            bounty.get("broker_discord", ""),
            1 if bounty.get("is_masked") else 0,
            int(bounty.get("amount", 0)),
            now, bounty_id,
        ),
    )
    _log_bounty_history(cur)
    after = None
    if actor and actor.get("access_level") != MASTER_LEVEL:
        after = db_bounty_get(bounty_id)
        if before != after:
            _log_change(cur, "bounty", bounty_id, "edit", before, after,
                        actor["username"], actor["id"])
    conn.close()
    _log(f"Updated bounty #{bounty_id}")
    return db_bounty_get(bounty_id)


def db_bounty_delete(bounty_id, actor=None):
    """Delete a bounty and log a history point. Returns True if a row was deleted."""
    conn = _db_conn()
    cur = conn.cursor()
    before = db_bounty_get(bounty_id) if (actor and actor.get("access_level") != MASTER_LEVEL) else None
    cur.execute("DELETE FROM bounties WHERE id=%s", (bounty_id,))
    deleted = cur.rowcount > 0
    if deleted:
        _log_bounty_history(cur)
        if actor and actor.get("access_level") != MASTER_LEVEL:
            _log_change(cur, "bounty", bounty_id, "remove", before, None,
                        actor["username"], actor["id"])
        _log(f"Deleted bounty #{bounty_id}")
    conn.close()
    return deleted


# ---- Users / sessions / changelog DB helpers ------------------------------

def db_user_get_by_username(username):
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username, password_hash, access_level, "
                "created_at, updated_at FROM users WHERE username=%s", (username,))
    row = cur.fetchone()
    conn.close()
    return _row_to_user(row) if row else None


def db_user_get_by_id(user_id):
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username, password_hash, access_level, "
                "created_at, updated_at FROM users WHERE id=%s", (user_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_user(row) if row else None


def db_user_list():
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username, password_hash, access_level, "
                "created_at, updated_at FROM users ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    # strip password_hash from public listing
    out = []
    for r in rows:
        u = _row_to_user(r)
        out.append({k: v for k, v in u.items() if k != "password_hash"})
    return out


def _row_to_user(row):
    return {
        "id": row[0],
        "username": row[1],
        "password_hash": row[2],
        "access_level": row[3],
        "created_at": row[4],
        "updated_at": row[5],
    }


def db_user_create(username, plain_password, access_level):
    now = datetime.now(timezone.utc).isoformat()
    conn = _db_conn()
    cur = conn.cursor()
    if access_level not in ACCESS_LEVELS:
        raise ValueError("invalid access level")
    cur.execute(
        "INSERT INTO users (username, password_hash, access_level, "
        "created_at, updated_at) VALUES (%s, %s, %s, %s, %s)",
        (username, hash_password(plain_password), access_level, now, now),
    )
    new_id = cur.lastrowid
    conn.close()
    return db_user_get_by_id(new_id)


def db_user_update(user_id, *, username=None, plain_password=None, access_level=None):
    now = datetime.now(timezone.utc).isoformat()
    conn = _db_conn()
    cur = conn.cursor()
    fields, vals = [], []
    if username is not None:
        fields.append("username=%s"); vals.append(username)
    if plain_password:
        fields.append("password_hash=%s"); vals.append(hash_password(plain_password))
    if access_level is not None:
        if access_level not in ACCESS_LEVELS:
            raise ValueError("invalid access level")
        fields.append("access_level=%s"); vals.append(access_level)
    if not fields:
        conn.close()
        return db_user_get_by_id(user_id)
    fields.append("updated_at=%s"); vals.append(now)
    vals.append(user_id)
    cur.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=%s", vals)
    conn.close()
    return db_user_get_by_id(user_id)


def db_user_delete(user_id):
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
    deleted = cur.rowcount > 0
    # also drop their sessions
    if deleted:
        cur.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
    conn.close()
    return deleted


def db_session_create(user_id):
    token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    created = now.isoformat()
    expires = (now + timedelta(hours=SESSION_TTL_HOURS)).isoformat()
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) "
        "VALUES (%s, %s, %s, %s)",
        (token, user_id, created, expires),
    )
    conn.close()
    return token


def db_session_get_user(token):
    """Return the user dict for a valid, non-expired session token, else None."""
    if not token:
        return None
    conn = _db_conn()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "SELECT user_id FROM sessions WHERE token=%s AND expires_at > %s",
        (token, now),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return db_user_get_by_id(row[0])


def db_session_destroy(token):
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM sessions WHERE token=%s", (token,))
    conn.close()


def db_session_destroy_all_for_user(user_id):
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
    conn.close()


def db_session_prune():
    """Remove expired sessions."""
    conn = _db_conn()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cur.execute("DELETE FROM sessions WHERE expires_at <= %s", (now,))
    conn.close()


# ---- Changelog helpers ---------------------------------------------------

def _log_change(cur, entity_type, entity_id, action, snapshot_before,
                snapshot_after, actor_username, actor_id):
    """Record a change_log entry. Called by the player/bounty mutators.

    Note: the master account is deliberately NOT logged, per requirements.
    The caller is responsible for skipping when actor is master.
    """
    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT INTO change_log (entity_type, entity_id, action, "
        "snapshot_before, snapshot_after, changed_by, changed_by_id, changed_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            entity_type,
            str(entity_id),
            action,
            json.dumps(snapshot_before, ensure_ascii=False) if snapshot_before is not None else None,
            json.dumps(snapshot_after, ensure_ascii=False) if snapshot_after is not None else None,
            actor_username or "",
            actor_id,
            now,
        ),
    )


def db_changelog_list(limit=200, entity_type=None, entity_id=None):
    conn = _db_conn()
    cur = conn.cursor()
    where, vals = [], []
    if entity_type:
        where.append("entity_type=%s"); vals.append(entity_type)
    if entity_id is not None:
        where.append("entity_id=%s"); vals.append(str(entity_id))
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    vals.append(limit)
    cur.execute(
        f"SELECT id, entity_type, entity_id, action, snapshot_before, "
        f"snapshot_after, changed_by, changed_by_id, changed_at, reverted "
        f"FROM change_log {where_sql} ORDER BY id DESC LIMIT %s",
        vals,
    )
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "entity_type": r[1],
            "entity_id": r[2],
            "action": r[3],
            "snapshot_before": json.loads(r[4]) if r[4] else None,
            "snapshot_after": json.loads(r[5]) if r[5] else None,
            "changed_by": r[6],
            "changed_by_id": r[7],
            "changed_at": r[8],
            "reverted": bool(r[9]),
        })
    return out


def db_changelog_get(entry_id):
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, entity_type, entity_id, action, snapshot_before, "
        "snapshot_after, changed_by, changed_by_id, changed_at, reverted "
        "FROM change_log WHERE id=%s",
        (entry_id,),
    )
    r = cur.fetchone()
    conn.close()
    if not r:
        return None
    return {
        "id": r[0], "entity_type": r[1], "entity_id": r[2], "action": r[3],
        "snapshot_before": json.loads(r[4]) if r[4] else None,
        "snapshot_after": json.loads(r[5]) if r[5] else None,
        "changed_by": r[6], "changed_by_id": r[7], "changed_at": r[8],
        "reverted": bool(r[9]),
    }


def db_changelog_mark_reverted(entry_id):
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("UPDATE change_log SET reverted=1 WHERE id=%s", (entry_id,))
    conn.close()


# Snapshot helpers (capture current state of an entity before mutation).

def db_player_get_raw(player_id):
    """Return the raw player dict for a given id, or None."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("SELECT data FROM players WHERE id=%s", (player_id,))
    row = cur.fetchone()
    conn.close()
    return json.loads(row[0]) if row else None


def db_player_restore(player_id, player_data):
    """Restore a single player record from a snapshot."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO players (id, data) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE data=VALUES(data)",
        (player_id, json.dumps(player_data, ensure_ascii=False)),
    )
    conn.close()


def db_player_delete(player_id):
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM players WHERE id=%s", (player_id,))
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def db_bounty_restore(bounty_id, bounty_data):
    """Restore a single bounty record from a snapshot.

    Bounty ids are AUTO_INCREMENT, so on re-insert the id may change. We
    store the original id inside the restored row's target_name reference is
    not reliable; instead we re-insert and report the new id.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO bounties (target_player_id, target_name, "
        "issuer_name, issuer_corp, issuer_discord, "
        "broker_name, broker_discord, is_masked, amount, "
        "created_at, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            bounty_data.get("target_player_id", ""),
            bounty_data.get("target_name", ""),
            bounty_data.get("issuer_name", ""),
            bounty_data.get("issuer_corp", ""),
            bounty_data.get("issuer_discord", ""),
            bounty_data.get("broker_name", ""),
            bounty_data.get("broker_discord", ""),
            1 if bounty_data.get("is_masked") else 0,
            int(bounty_data.get("amount", 0)),
            bounty_data.get("created_at", now),
            bounty_data.get("updated_at", now),
        ),
    )
    new_id = cur.lastrowid
    _log_bounty_history(cur)
    conn.close()
    return new_id


def _apply_revert(entry):
    """Apply a reversion for a changelog entry. Returns a description dict,
    or None if the entry cannot be reverted.

    Reversion logic by action:
      add    -> remove the entity that was added (undo the add)
      remove -> restore the entity from snapshot_before
      edit   -> restore the entity from snapshot_before
    """
    action = entry["action"]
    etype = entry["entity_type"]
    eid = entry["entity_id"]
    before = entry["snapshot_before"]
    after = entry["snapshot_after"]

    if etype == "player":
        if action == "add":
            # undo: delete the player that was added
            if after is None:
                return None
            db_player_delete(eid)
            return {"action": "removed player", "entity_id": eid}
        elif action in ("remove", "edit"):
            # restore prior state
            if before is None:
                return None
            db_player_restore(eid, before)
            return {"action": "restored player", "entity_id": eid}

    elif etype == "bounty":
        if action == "add":
            # undo: delete the bounty that was added
            if after is None:
                return None
            db_bounty_delete(eid)
            return {"action": "removed bounty", "entity_id": eid}
        elif action in ("remove", "edit"):
            if before is None:
                return None
            new_id = db_bounty_restore(eid, before)
            return {"action": "restored bounty", "entity_id": eid, "new_id": new_id}

    return None


db_init()


def _format_isk(raw) -> int:
    """Turn '44,808,482,462,924 ISK' or '0 ISK' or '2,377,760,956,578 ISK'
    into a plain integer."""
    if raw is None:
        return 0
    s = str(raw).replace("ISK", "").replace(",", "").replace(" ", "").strip()
    if s in ("", "-", "—"):
        return 0
    m = re.search(r"-?\d+", s)
    return int(m.group()) if m else 0


def _parse_int(raw) -> int:
    if raw is None:
        return 0
    s = str(raw).replace(",", "").replace("ship(s)", "").replace("ships", "")
    s = s.replace("ship", "").strip()
    m = re.search(r"\d+", s)
    return int(m.group()) if m else 0


def _pct(raw) -> float:
    """Parse a percentage value. Accepts '99.4%', '99.4', or 99.4 (float)."""
    if raw is None:
        return 0.0
    s = str(raw).strip()
    m = re.search(r"([\d.]+)", s)
    return float(m.group(1)) if m else 0.0


def _clean(text: str) -> str:
    return html_lib.unescape(re.sub(r"\s+", " ", text or "").strip())


def fetch_page(player: str) -> str:
    url = f"{ECHOES_BASE}/{urllib.parse.quote(player)}/summary"
    _log(f"Fetching {url}")
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_summary(html: str) -> dict:

    no_script = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    no_style = re.sub(r"<style[\s\S]*?</style>", " ", no_script, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", no_style)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    out = {
        "name": None,
        "killedShips": 0,
        "iskDestroyed": 0,
        "lostShips": 0,
        "iskLost": 0,
        "killRatioDangerous": 50.0,
        "killRatioSnuggly": 50.0,
        "iskEfficiencyDangerous": 50.0,
        "iskEfficiencySnuggly": 50.0,
        "corporation": None,
        "bestKill": None,
        "bestKillIsk": 0,
        "highestLoss": None,
        "highestLossIsk": 0,
        "topShipsByKills": [],
        "topShipsByIsk": [],
        "dangerous": True,
    }

    blob = "\n".join(lines)

    m = re.search(r"Name\s*\n\s*(.+)", blob)
    if m:
        out["name"] = _clean(m.group(1))

    m = re.search(
        r"Killed\s*\n\s*([\d,]+)\s*ship\(s\)\s*\n\s*([\d,]+)\s*ISK", blob
    )
    if m:
        out["killedShips"] = _parse_int(m.group(1))
        out["iskDestroyed"] = _format_isk(m.group(2) + " ISK")
    else:
        # fallback: maybe "0 ship(s)" / "0 ISK"
        m = re.search(r"Killed\s*\n\s*([\d,]+)\s*ship\(s\)\s*\n\s*([\d,]*)\s*ISK", blob)
        if m:
            out["killedShips"] = _parse_int(m.group(1))
            out["iskDestroyed"] = _format_isk(m.group(2) + " ISK")

    # Lost
    m = re.search(
        r"Lost\s*\n\s*([\d,]+)\s*ship\(s\)\s*\n\s*([\d,]+)\s*ISK", blob
    )
    if m:
        out["lostShips"] = _parse_int(m.group(1))
        out["iskLost"] = _format_isk(m.group(2) + " ISK")
    else:
        m = re.search(r"Lost\s*\n\s*([\d,]+)\s*ship\(s\)\s*\n\s*([\d,]*)\s*ISK", blob)
        if m:
            out["lostShips"] = _parse_int(m.group(1))
            out["iskLost"] = _format_isk(m.group(2) + " ISK")

    m = re.search(r"Kill ratio\s*\n\s*Snuggly\s*\n\s*([\d.]+)%\s*\n\s*([\d.]+)%\s*\n\s*Dangerous", blob)
    if m:
        out["killRatioSnuggly"] = _pct(m.group(1))
        out["killRatioDangerous"] = _pct(m.group(2))
        out["dangerous"] = out["killRatioDangerous"] >= 50.0
    else:
        m = re.search(r"Kill ratio[\s\S]{0,80}?([\d.]+)%\s*\n\s*([\d.]+)%", blob)
        if m:
            a, b = _pct(m.group(1)), _pct(m.group(2))
            out["killRatioDangerous"] = max(a, b)
            out["killRatioSnuggly"] = min(a, b)
            out["dangerous"] = out["killRatioDangerous"] >= 50.0

    m = re.search(r"ISK efficiency\s*\n\s*Snuggly\s*\n\s*([\d.]+)%\s*\n\s*([\d.]+)%\s*\n\s*Dangerous", blob)
    if m:
        out["iskEfficiencySnuggly"] = _pct(m.group(1))
        out["iskEfficiencyDangerous"] = _pct(m.group(2))
    else:
        m = re.search(r"ISK efficiency[\s\S]{0,80}?([\d.]+)%\s*\n\s*([\d.]+)%", blob)
        if m:
            a, b = _pct(m.group(1)), _pct(m.group(2))
            out["iskEfficiencyDangerous"] = max(a, b)
            out["iskEfficiencySnuggly"] = min(a, b)

    # Corporation
    m = re.search(r"Corporation\s*\n\s*(.+?)(?=\n\s*(?:Best kill|Highest loss|Top ships|$))", blob)
    if m:
        corp = _clean(m.group(1))
        out["corporation"] = None if corp in ("-", "—", "") else corp

    # Best kill
    m = re.search(r"Best kill\s*\n\s*(.+?)\s*\n\s*([\d,]+)\s*ISK", blob)
    if m:
        out["bestKill"] = _clean(m.group(1))
        out["bestKillIsk"] = _format_isk(m.group(2) + " ISK")
    else:
        m = re.search(r"Best kill\s*\n\s*(-|—)")
        if m:
            out["bestKill"] = None
            out["bestKillIsk"] = 0

    # Highest loss
    m = re.search(r"Highest loss\s*\n\s*(.+?)\s*\n\s*([\d,]+)\s*ISK", blob)
    if m:
        out["highestLoss"] = _clean(m.group(1))
        out["highestLossIsk"] = _format_isk(m.group(2) + " ISK")
    else:
        m = re.search(r"Highest loss\s*\n\s*(-|—)")
        if m:
            out["highestLoss"] = None
            out["highestLossIsk"] = 0

    m = re.search(
        r"Top ships by kills\s*\n([\s\S]*?)(?=\n\s*(?:Corporation|Best kill|Highest loss|Top ships by ISK|$))",
        blob,
    )
    if m:
        block = m.group(1)
        # pair each ship-name line with the following "N kills" line
        for sm in re.finditer(r"([^\n]+?)\s*\n\s*([\d,]+)\s*kills", block):
            ship = _clean(sm.group(1))
            # skip if the "ship name" is actually a number/label artifact
            if ship and not ship.isdigit():
                out["topShipsByKills"].append({
                    "ship": ship,
                    "count": _parse_int(sm.group(2)),
                })

    # Top ships by ISK
    m = re.search(
        r"Top ships by ISK\s*\n([\s\S]*?)(?=\n\s*(?:Dangerous|Snuggly|Kill ratio|$))",
        blob,
    )
    if m:
        block = m.group(1)
        for sm in re.finditer(r"([^\n]+?)\s*\n\s*([\d,]+)\s*ISK", block):
            ship = _clean(sm.group(1))
            if ship and not ship.isdigit():
                out["topShipsByIsk"].append({
                    "ship": ship,
                    "isk": _format_isk(sm.group(2) + " ISK"),
                })

    # derived efficiency as a single number (isk destroyed / (isk destroyed + isk lost))
    total = out["iskDestroyed"] + out["iskLost"]
    if total > 0:
        out["efficiency"] = round(out["iskDestroyed"] / total * 100, 2)
    else:
        out["efficiency"] = out["iskEfficiencyDangerous"]

    return out


# HTTP server


class Handler(BaseHTTPRequestHandler):
    server_version = "echoes-proxy/1.0"

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Admin-Token")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, rel_path: str):
        rel_path = rel_path.lstrip("/")
        if rel_path == "":
            rel_path = "index.html"
        target = (ROOT / rel_path).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError:
            self._json(403, {"ok": False, "error": "forbidden"})
            return

        if not target.is_file():
            self._json(404, {"ok": False, "error": "not found", "path": rel_path})
            return

        ext = target.suffix.lower()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }.get(ext, "application/octet-stream")

        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self): 
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Admin-Token")
        self.end_headers()

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return b""
        return self.rfile.read(length)

    def _bearer_token(self):
        """Extract session token from Authorization: Bearer <token>."""
        h = self.headers.get("Authorization", "")
        if h.startswith("Bearer "):
            return h[7:].strip()
        # backwards-compat: also accept legacy X-Admin-Token header so old
        # requests fail closed rather than crash. We do NOT honour it.
        return ""

    def _current_user(self):
        """Return the authenticated user dict (id, username, access_level)
        for this request, or None."""
        token = self._bearer_token()
        return db_session_get_user(token)

    def _require(self, required_level):
        """Return (user, None) if authenticated with sufficient access,
        else (None, error_response_already_sent)."""
        user = self._current_user()
        if not user:
            self._json(401, {"ok": False, "error": "unauthorized: login required"})
            return None
        if not has_access(user["access_level"], required_level):
            self._json(403, {"ok": False, "error": "forbidden: insufficient access level"})
            return None
        return user

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # ---- public: login ----
        if path == "/api/login":
            try:
                payload = json.loads(self._read_body().decode("utf-8"))
                username = (payload.get("username") or "").strip()
                password = payload.get("password") or ""
                if not username or not password:
                    self._json(400, {"ok": False, "error": "username and password required"})
                    return
                user = db_user_get_by_username(username)
                if not user or not verify_password(password, user["password_hash"]):
                    self._json(401, {"ok": False, "error": "invalid credentials"})
                    return
                token = db_session_create(user["id"])
                self._json(200, {
                    "ok": True,
                    "token": token,
                    "user": {
                        "id": user["id"],
                        "username": user["username"],
                        "access_level": user["access_level"],
                    },
                })
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON body"})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        # ---- auth: logout ----
        if path == "/api/logout":
            token = self._bearer_token()
            if token:
                db_session_destroy(token)
            self._json(200, {"ok": True})
            return

        # ---- auth+master: create user ----
        if path == "/api/users":
            user = self._require(MASTER_LEVEL)
            if not user:
                return
            try:
                payload = json.loads(self._read_body().decode("utf-8"))
                username = (payload.get("username") or "").strip()
                password = payload.get("password") or ""
                access_level = (payload.get("access_level") or "viewer").strip()
                if not username or not password:
                    self._json(400, {"ok": False, "error": "username and password required"})
                    return
                if access_level not in ACCESS_LEVELS:
                    self._json(400, {"ok": False, "error": f"access_level must be one of {ACCESS_LEVELS}"})
                    return
                if db_user_get_by_username(username):
                    self._json(409, {"ok": False, "error": "username already exists"})
                    return
                created = db_user_create(username, password, access_level)
                self._json(200, {"ok": True, "user": {k: v for k, v in created.items() if k != "password_hash"}})
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON body"})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        # ---- admin+: revert a changelog entry ----
        if path.startswith("/api/changelog/") and path.endswith("/revert"):
            user = self._require("admin")
            if not user:
                return
            try:
                entry_id = int(path.split("/")[-2])
            except ValueError:
                self._json(400, {"ok": False, "error": "invalid changelog id"})
                return
            try:
                entry = db_changelog_get(entry_id)
                if not entry:
                    self._json(404, {"ok": False, "error": "changelog entry not found"})
                    return
                if entry["reverted"]:
                    self._json(409, {"ok": False, "error": "entry already reverted"})
                    return
                result = _apply_revert(entry)
                if result is None:
                    self._json(409, {"ok": False, "error": "cannot revert this entry (no restorable snapshot)"})
                    return
                db_changelog_mark_reverted(entry_id)
                self._json(200, {"ok": True, "reverted": entry_id, "result": result})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if path == "/api/players":
            # auth check: editor+ required
            user = self._require("editor")
            if not user:
                return
            try:
                raw = self._read_body()
                payload = json.loads(raw.decode("utf-8"))
                players = payload.get("players")
                if not isinstance(players, list):
                    self._json(400, {"ok": False, "error": "missing 'players' array"})
                    return
                saved_at = db_save(players, actor=user)
                self._json(200, {
                    "ok": True,
                    "count": len(players),
                    "savedAt": saved_at,
                })
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON body"})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if path == "/api/bounties":
            user = self._require("editor")
            if not user:
                return
            try:
                raw = self._read_body()
                payload = json.loads(raw.decode("utf-8"))
                bounty = payload.get("bounty")
                if not isinstance(bounty, dict):
                    self._json(400, {"ok": False, "error": "missing 'bounty' object"})
                    return
                if not bounty.get("target_name"):
                    self._json(400, {"ok": False, "error": "bounty requires target_name"})
                    return
                created = db_bounty_add(bounty, actor=user)
                self._json(200, {"ok": True, "bounty": created})
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON body"})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if path.startswith("/api/"):
            self._json(404, {"ok": False, "error": "unknown api route"})
            return

        self._json(405, {"ok": False, "error": "method not allowed"})

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/api/health":
            self._json(200, {"ok": True, "service": "echoes-proxy",
                             "time": datetime.now(timezone.utc).isoformat()})
            return

        if path == "/api/session":
            user = self._current_user()
            if not user:
                self._json(401, {"ok": False, "error": "not authenticated"})
                return
            self._json(200, {"ok": True, "user": {
                "id": user["id"],
                "username": user["username"],
                "access_level": user["access_level"],
            }})
            return

        if path == "/api/users":
            user = self._require(MASTER_LEVEL)
            if not user:
                return
            try:
                self._json(200, {"ok": True, "users": db_user_list(),
                                 "access_levels": ACCESS_LEVELS})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if path == "/api/changelog":
            user = self._require("admin")
            if not user:
                return
            try:
                qs2 = urllib.parse.parse_qs(parsed.query)
                etype = (qs2.get("entity_type") or [None])[0]
                eid = (qs2.get("entity_id") or [None])[0]
                try:
                    limit = int((qs2.get("limit") or ["200"])[0])
                except ValueError:
                    limit = 200
                limit = max(1, min(limit, 1000))
                entries = db_changelog_list(limit=limit, entity_type=etype, entity_id=eid)
                self._json(200, {"ok": True, "entries": entries,
                                 "count": len(entries)})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if path == "/api/players":
            try:
                self._json(200, db_load())
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if path == "/api/scrape":
            player = (qs.get("player") or [""])[0].strip()
            if not player:
                self._json(400, {"ok": False, "error": "missing 'player' param"})
                return
            try:
                html = fetch_page(player)
                data = parse_summary(html)
                self._json(200, {
                    "ok": True,
                    "player": player,
                    "source": f"{ECHOES_BASE}/{player}/summary",
                    "fetchedAt": datetime.now(timezone.utc).isoformat(),
                    "data": data,
                })
            except urllib.error.HTTPError as e:
                self._json(e.code, {"ok": False, "error": f"echoes.mobi returned {e.code}",
                                    "player": player})
            except urllib.error.URLError as e:
                self._json(502, {"ok": False, "error": f"upstream error: {e.reason}",
                                 "player": player})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e), "player": player})
            return

        if path == "/api/bounties":
            try:
                self._json(200, {
                    "ok": True,
                    "bounties": db_bounty_load_all(),
                    "bountyHistory": db_bounty_history(),
                })
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        # static files (frontend)
        if path.startswith("/api/"):
            self._json(404, {"ok": False, "error": "unknown api route"})
            return

        self._static(path)

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # /api/users/<id>  (master only — update user / level / password)
        if path.startswith("/api/users/"):
            user = self._require(MASTER_LEVEL)
            if not user:
                return
            try:
                target_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self._json(400, {"ok": False, "error": "invalid user id"})
                return
            try:
                target = db_user_get_by_id(target_id)
                if not target:
                    self._json(404, {"ok": False, "error": "user not found"})
                    return
                payload = json.loads(self._read_body().decode("utf-8"))
                updated = db_user_update(
                    target_id,
                    username=(payload.get("username") or None),
                    plain_password=(payload.get("password") or None),
                    access_level=(payload.get("access_level") or None),
                )
                # if access level changed for a user, drop their other sessions
                if payload.get("access_level"):
                    db_session_destroy_all_for_user(target_id)
                self._json(200, {"ok": True, "user": {
                    k: v for k, v in updated.items() if k != "password_hash"}})
            except ValueError as e:
                self._json(400, {"ok": False, "error": str(e)})
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON body"})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        # /api/bounties/<id>
        if path.startswith("/api/bounties/"):
            user = self._require("editor")
            if not user:
                return
            try:
                bounty_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self._json(400, {"ok": False, "error": "invalid bounty id"})
                return
            try:
                raw = self._read_body()
                payload = json.loads(raw.decode("utf-8"))
                bounty = payload.get("bounty")
                if not isinstance(bounty, dict):
                    self._json(400, {"ok": False, "error": "missing 'bounty' object"})
                    return
                if not bounty.get("target_name"):
                    self._json(400, {"ok": False, "error": "bounty requires target_name"})
                    return
                existing = db_bounty_get(bounty_id)
                if not existing:
                    self._json(404, {"ok": False, "error": "bounty not found"})
                    return
                updated = db_bounty_update(bounty_id, bounty, actor=user)
                self._json(200, {"ok": True, "bounty": updated})
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON body"})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if path.startswith("/api/"):
            self._json(404, {"ok": False, "error": "unknown api route"})
            return

        self._json(405, {"ok": False, "error": "method not allowed"})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # /api/users/<id>  (master only; cannot delete self or the master account)
        if path.startswith("/api/users/"):
            user = self._require(MASTER_LEVEL)
            if not user:
                return
            try:
                target_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self._json(400, {"ok": False, "error": "invalid user id"})
                return
            target = db_user_get_by_id(target_id)
            if not target:
                self._json(404, {"ok": False, "error": "user not found"})
                return
            if target["access_level"] == MASTER_LEVEL:
                self._json(403, {"ok": False, "error": "cannot delete a master account"})
                return
            if target_id == user["id"]:
                self._json(403, {"ok": False, "error": "cannot delete your own account"})
                return
            try:
                deleted = db_user_delete(target_id)
                self._json(200, {"ok": True, "id": target_id})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        # /api/bounties/<id>
        if path.startswith("/api/bounties/"):
            user = self._require("editor")
            if not user:
                return
            try:
                bounty_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self._json(400, {"ok": False, "error": "invalid bounty id"})
                return
            try:
                deleted = db_bounty_delete(bounty_id, actor=user)
                if not deleted:
                    self._json(404, {"ok": False, "error": "bounty not found"})
                    return
                self._json(200, {"ok": True, "id": bounty_id})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if path.startswith("/api/"):
            self._json(404, {"ok": False, "error": "unknown api route"})
            return

        self._json(405, {"ok": False, "error": "method not allowed"})

    def log_message(self, fmt, *args):  # quieter logs
        _log("%s - %s" % (self.address_string(), fmt % args))


def main():
    missing = _missing_db_env()
    if missing:
        _log("ERROR: missing required environment variables: " + ", ".join(missing))
        _log("Set ECHOES_DB_HOST, ECHOES_DB_USER, ECHOES_DB_PASS, ECHOES_DB_NAME "
             "before starting the server.")
        sys.exit(1)

    try:
        db_session_prune()
    except Exception as e:
        _log(f"Warning: could not prune sessions: {e}")

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    _log(f"Serving frontend + /api on http://{args.host}:{args.port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        _log("Shutting down.")
        srv.shutdown()


if __name__ == "__main__":
    main()
