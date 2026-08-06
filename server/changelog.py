"""
changelog.py  —  Change logging + reversion.

Every mutation to a player or bounty (add / edit / remove) is recorded
in the `change_log` table so an admin can see who changed what and when,
and can revert a change. This module owns:

* `_log_change()`        — the low-level "write one changelog row" helper
                           called by the player/bounty mutators.
* `db_changelog_list()`  — list entries (with optional filters).
* `db_changelog_get()`   — fetch a single entry.
* `db_changelog_mark_reverted()` — flag an entry as reverted.
* `_apply_revert()`      — undo a single change (the reversion engine).

Important rule (per the security requirements):
    Changes made by the MASTER account are NOT logged. The caller of
    `_log_change()` (in db.py / bounties.py) is responsible for
    skipping the call when the actor is master.

Dependency note
---------------
`_apply_revert()` needs to restore or delete players/bounties, whose
functions live in db.py and bounties.py. Those modules also import
`_log_change` from here. To avoid a circular import at load time we
import db.py / bounties.py *inside* `_apply_revert()` (a "lazy import"),
which only runs when a revert actually happens.
"""

import json
from datetime import datetime, timezone

from .config import _log
from .db_base import _db_conn


def _log_change(cur, entity_type, entity_id, action, snapshot_before,
                snapshot_after, actor_username, actor_id):
    """Record one change_log entry.

    `cur` is an already-open cursor (the caller manages the connection
    so this can run inside the same transaction as the mutation).
    Snapshots are JSON-serialised before storing.
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


def _entry_from_row(r):
    """Turn a change_log row tuple into a dict (parses JSON snapshots)."""
    return {
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
    }


_CHANGELOG_COLS = (
    "id, entity_type, entity_id, action, snapshot_before, "
    "snapshot_after, changed_by, changed_by_id, changed_at, reverted"
)


def db_changelog_list(limit=200, entity_type=None, entity_id=None):
    """Return changelog entries, newest first, optionally filtered."""
    conn = _db_conn()
    cur = conn.cursor()
    where, vals = [], []
    if entity_type:
        where.append("entity_type=%s")
        vals.append(entity_type)
    if entity_id is not None:
        where.append("entity_id=%s")
        vals.append(str(entity_id))
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    vals.append(limit)
    cur.execute(
        f"SELECT {_CHANGELOG_COLS} FROM change_log "
        f"{where_sql} ORDER BY id DESC LIMIT %s",
        vals,
    )
    rows = cur.fetchall()
    conn.close()
    return [_entry_from_row(r) for r in rows]


def db_changelog_get(entry_id):
    """Return a single changelog entry dict by id, or None."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(
        f"SELECT {_CHANGELOG_COLS} FROM change_log WHERE id=%s",
        (entry_id,),
    )
    r = cur.fetchone()
    conn.close()
    return _entry_from_row(r) if r else None


def db_changelog_mark_reverted(entry_id):
    """Flag a changelog entry as having been reverted."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("UPDATE change_log SET reverted=1 WHERE id=%s", (entry_id,))
    conn.close()


def _apply_revert(entry):
    """Undo a single changelog entry. Returns a description dict, or
    None if the entry cannot be reverted.

    Reversion logic by action:
      add    -> remove the entity that was added (undo the add)
      remove -> restore the entity from snapshot_before
      edit   -> restore the entity from snapshot_before

    Lazy imports: db.py and bounties.py import _log_change from this
    module, so importing them at the top would be circular. We import
    them here instead — only when a revert is actually performed.
    """
    from . import db as _db
    from . import bounties as _bounties

    action = entry["action"]
    etype = entry["entity_type"]
    eid = entry["entity_id"]
    before = entry["snapshot_before"]
    after = entry["snapshot_after"]

    if etype == "player":
        if action == "add":
            if after is None:
                return None
            _db.db_player_delete(eid)
            return {"action": "removed player", "entity_id": eid}
        elif action in ("remove", "edit"):
            if before is None:
                return None
            _db.db_player_restore(eid, before)
            return {"action": "restored player", "entity_id": eid}

    elif etype == "bounty":
        if action == "add":
            if after is None:
                return None
            _bounties.db_bounty_delete(eid)
            return {"action": "removed bounty", "entity_id": eid}
        elif action in ("remove", "edit"):
            if before is None:
                return None
            new_id = _bounties.db_bounty_restore(eid, before)
            return {"action": "restored bounty", "entity_id": eid, "new_id": new_id}

    return None
