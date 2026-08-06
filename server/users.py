"""
users.py  —  User accounts + login sessions.

Functions
---------
Users:
* `db_user_get_by_username(name)` — look up a user by username.
* `db_user_get_by_id(id)`         — look up a user by id.
* `db_user_list()`                — list all users (password hashes stripped).
* `db_user_create(...)`           — create a new user (hashed password).
* `db_user_update(id, ...)`       — update username / password / access level.
* `db_user_delete(id)`            — delete a user (also clears their sessions).

Sessions:
* `db_session_create(user_id)`    — create a session token (12h TTL).
* `db_session_get_user(token)`    — resolve a token to a user dict.
* `db_session_destroy(token)`     — invalidate one token.
* `db_session_destroy_all_for_user(id)` — invalidate all of a user's tokens.
* `db_session_prune()`            — delete expired sessions.

Dependencies
------------
Imports password + access helpers from config.py. No dependency on the
changelog (user management is master-only and not audited).
"""

import secrets
from datetime import datetime, timezone, timedelta

from .config import (
    ACCESS_LEVELS, SESSION_TTL_HOURS,
    hash_password, _log,
)
from .db_base import _db_conn


_USER_COLS = "id, username, password_hash, access_level, created_at, updated_at"


def _row_to_user(row):
    """Turn a user row tuple into a plain dict."""
    return {
        "id": row[0],
        "username": row[1],
        "password_hash": row[2],
        "access_level": row[3],
        "created_at": row[4],
        "updated_at": row[5],
    }


# ---- Users ---------------------------------------------------------------

def db_user_get_by_username(username):
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT {_USER_COLS} FROM users WHERE username=%s", (username,))
    row = cur.fetchone()
    conn.close()
    return _row_to_user(row) if row else None


def db_user_get_by_id(user_id):
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT {_USER_COLS} FROM users WHERE id=%s", (user_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_user(row) if row else None


def db_user_list():
    """List all users, with password_hash stripped out."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT {_USER_COLS} FROM users ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        u = _row_to_user(r)
        out.append({k: v for k, v in u.items() if k != "password_hash"})
    return out


def db_user_create(username, plain_password, access_level):
    if access_level not in ACCESS_LEVELS:
        raise ValueError("invalid access level")
    now = datetime.now(timezone.utc).isoformat()
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (username, password_hash, access_level, "
        "created_at, updated_at) VALUES (%s, %s, %s, %s, %s)",
        (username, hash_password(plain_password), access_level, now, now),
    )
    new_id = cur.lastrowid
    conn.close()
    return db_user_get_by_id(new_id)


def db_user_update(user_id, *, username=None, plain_password=None, access_level=None):
    """Update whichever of username / password / access_level are provided."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _db_conn()
    cur = conn.cursor()
    fields, vals = [], []
    if username is not None:
        fields.append("username=%s")
        vals.append(username)
    if plain_password:
        fields.append("password_hash=%s")
        vals.append(hash_password(plain_password))
    if access_level is not None:
        if access_level not in ACCESS_LEVELS:
            raise ValueError("invalid access level")
        fields.append("access_level=%s")
        vals.append(access_level)
    if not fields:
        conn.close()
        return db_user_get_by_id(user_id)
    fields.append("updated_at=%s")
    vals.append(now)
    vals.append(user_id)
    cur.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=%s", vals)
    conn.close()
    return db_user_get_by_id(user_id)


def db_user_delete(user_id):
    """Delete a user and all their sessions. Returns True if a row was deleted."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
    deleted = cur.rowcount > 0
    if deleted:
        cur.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
    conn.close()
    return deleted


# ---- Sessions ------------------------------------------------------------

def db_session_create(user_id):
    """Create a session token for a user (expires after SESSION_TTL_HOURS)."""
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
    """Return the user dict for a valid, non-expired token, else None."""
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
    """Remove expired sessions (called once on startup)."""
    conn = _db_conn()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cur.execute("DELETE FROM sessions WHERE expires_at <= %s", (now,))
    conn.close()
