"""
db.py  —  Player data access (load / save / restore / delete).

Functions
---------
* `db_load()`              — read all players + tag metadata + bounties
                             (the big "give me everything" call used by
                             GET /api/players).
* `db_save(players, actor)` — replace the entire player set, logging a
                             diff to the changelog (unless the actor is
                             the master account).
* `db_player_get_raw(id)`  — fetch one player's raw dict.
* `db_player_restore(...)` — re-insert one player from a snapshot (used
                             by reversion).
* `db_player_delete(id)`   — delete one player (used by reversion).

Dependencies
------------
Imports `_log_change` from changelog.py to record diffs, and the bounty
load/history helpers from bounties.py for `db_load()`.
"""

import json
from datetime import datetime, timezone

from .config import MASTER_LEVEL, _log
from .db_base import _db_conn
from .changelog import _log_change
from .bounties import db_bounty_load_all, db_bounty_history


def db_load():
    """Return {players, tagCategories, savedAt, bounties, bountyHistory}."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("SELECT data FROM players")
    players = [json.loads(r[0]) for r in cur.fetchall()]

    def meta(key, default):
        cur.execute("SELECT value FROM meta WHERE `key`=%s", (key,))
        row = cur.fetchone()
        if not row:
            return default
        v = row[0]
        return json.loads(v) if (key == "tagCategories" or v[:1] in "{[") else v

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
    """Replace all players in MySQL. Returns the savedAt timestamp.

    `actor` is a dict {id, username, access_level} or None. When the
    actor is NOT the master account, the before/after diff is recorded
    in the change_log table (one entry per added/edited/removed player).
    Master changes are deliberately not logged.
    """
    saved_at = datetime.now(timezone.utc).isoformat()
    conn = _db_conn()
    cur = conn.cursor()

    # Capture the before-state so we can diff it against the new set.
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

    # Replace every row.
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

    # Log the diff (removals, then additions + edits).
    if log_change:
        after_map = {p.get("id") or p.get("name", ""): p for p in players}
        for pid in before_ids:
            if pid not in after_map:
                _log_change(cur, "player", pid, "remove",
                            before_map.get(pid), None,
                            actor["username"], actor["id"])
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


# ---- Single-player helpers (used by the reversion engine) ----------------

def db_player_get_raw(player_id):
    """Return the raw player dict for a given id, or None."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("SELECT data FROM players WHERE id=%s", (player_id,))
    row = cur.fetchone()
    conn.close()
    return json.loads(row[0]) if row else None


def db_player_restore(player_id, player_data):
    """Restore a single player record from a snapshot (upsert)."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO players (id, data) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE data=VALUES(data)",
        (player_id, json.dumps(player_data, ensure_ascii=False)),
    )
    conn.close()


def db_player_delete(player_id):
    """Delete a single player record. Returns True if a row was removed."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM players WHERE id=%s", (player_id,))
    deleted = cur.rowcount > 0
    conn.close()
    return deleted
