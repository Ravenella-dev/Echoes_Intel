"""
bounties.py  —  Bounty data access.

Bounties are placed on pilots. Several bounties can target the same
pilot (the "multi-contributor" system), so the total for a target is
the SUM of all its bounty rows.

Functions
---------
* `db_bounty_load_all()`   — every bounty, oldest first.
* `db_bounty_history()`    — {target_name: [{ts, total}, ...]} for charts.
* `db_bounty_add(...)`     — insert a new bounty (+ history point + changelog).
* `db_bounty_get(id)`      — fetch one bounty dict.
* `db_bounty_update(...)`  — edit a bounty (+ history point + changelog).
* `db_bounty_delete(id)`   — remove a bounty (+ history point + changelog).
* `db_bounty_restore(...)` — re-insert a bounty from a snapshot (reversion).
* `_log_bounty_history(cur)` — snapshot the current per-target totals.

Dependencies
------------
Imports `_log_change` from changelog.py for audit logging (skipped when
the actor is the master account).
"""

import json
from datetime import datetime, timezone

from .config import MASTER_LEVEL, _log
from .db_base import _db_conn
from .changelog import _log_change


# The columns we SELECT in order — keeps SELECT lists consistent.
_BOUNTY_COLS = (
    "id, target_player_id, target_name, issuer_name, issuer_corp, "
    "issuer_discord, broker_name, broker_discord, is_masked, amount, "
    "created_at, updated_at"
)


def _row_to_bounty(row):
    """Turn a bounty row tuple into a plain dict."""
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
    """Insert one history row per target_name with the current total bounty.

    Called after any bounty add/update/delete so the history chart has a
    fresh data point. Uses the cursor the caller already has open.
    """
    cur.execute(
        "SELECT target_name, COALESCE(SUM(amount),0) "
        "FROM bounties GROUP BY target_name"
    )
    now = datetime.now(timezone.utc).isoformat()
    for target_name, total in cur.fetchall():
        cur.execute(
            "INSERT INTO bounty_history (target_name, total_amount, logged_at) "
            "VALUES (%s, %s, %s)",
            (target_name, int(total), now),
        )


# The column list + placeholders used by INSERT and UPDATE. Centralising
# these here means add / update / restore never drift out of sync.
_BOUNTY_FIELD_LIST = (
    "target_player_id, target_name, "
    "issuer_name, issuer_corp, issuer_discord, "
    "broker_name, broker_discord, is_masked, amount"
)
_BOUNTY_VALUES_FROM = lambda b: (
    b.get("target_player_id", ""),
    b.get("target_name", ""),
    b.get("issuer_name", ""),
    b.get("issuer_corp", ""),
    b.get("issuer_discord", ""),
    b.get("broker_name", ""),
    b.get("broker_discord", ""),
    1 if b.get("is_masked") else 0,
    int(b.get("amount", 0)),
)


def db_bounty_load_all():
    """Return a list of all bounty dicts (ordered by id)."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT {_BOUNTY_COLS} FROM bounties ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return [_row_to_bounty(r) for r in rows]


def db_bounty_history():
    """Return {target_name: [{ts, total}, ...]} sorted by time."""
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
    """Insert a new bounty, log a history point, and return the bounty dict."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO bounties ({_BOUNTY_FIELD_LIST}, created_at, updated_at) "
        f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (*_BOUNTY_VALUES_FROM(bounty), now, now),
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
    """Update an existing bounty, log a history point, return the bounty dict."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _db_conn()
    cur = conn.cursor()
    before = (db_bounty_get(bounty_id)
              if (actor and actor.get("access_level") != MASTER_LEVEL)
              else None)
    cur.execute(
        f"UPDATE bounties SET {_BOUNTY_FIELD_LIST}, updated_at=%s WHERE id=%s",
        (*_BOUNTY_VALUES_FROM(bounty), now, bounty_id),
    )
    _log_bounty_history(cur)
    if actor and actor.get("access_level") != MASTER_LEVEL:
        after = db_bounty_get(bounty_id)
        if before != after:
            _log_change(cur, "bounty", bounty_id, "edit", before, after,
                        actor["username"], actor["id"])
    conn.close()
    _log(f"Updated bounty #{bounty_id}")
    return db_bounty_get(bounty_id)


def db_bounty_delete(bounty_id, actor=None):
    """Delete a bounty, log a history point. Returns True if a row was deleted."""
    conn = _db_conn()
    cur = conn.cursor()
    before = (db_bounty_get(bounty_id)
              if (actor and actor.get("access_level") != MASTER_LEVEL)
              else None)
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


def db_bounty_restore(bounty_id, bounty_data):
    """Re-insert a bounty from a snapshot (used by reversion).

    Bounty ids are AUTO_INCREMENT, so the re-inserted row gets a NEW id.
    We return that new id so the caller can report it.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO bounties ({_BOUNTY_FIELD_LIST}, created_at, updated_at) "
        f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            *_BOUNTY_VALUES_FROM(bounty_data),
            bounty_data.get("created_at", now),
            bounty_data.get("updated_at", now),
        ),
    )
    new_id = cur.lastrowid
    _log_bounty_history(cur)
    conn.close()
    return new_id
