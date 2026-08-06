#!/usr/bin/env python3
"""
EVE Echoes Intel DB — echoes.mobi scraping proxy + persistence server.

The full backend now lives in the :mod:`server` package:

    server/config.py     – environment, constants, password + access helpers
    server/db_base.py    – raw MySQL connection + table creation / seeding
    server/db.py         – player load / save / restore / delete
    server/bounties.py   – bounty CRUD + history logging
    server/users.py      – user accounts + session management
    server/changelog.py  – change-log records + reversion logic
    server/scraper.py    – echoes.mobi page fetch + summary parser
    server/handler.py    – HTTP request handler (all /api endpoints + static)

This file is just the entry point: it initialises the database, prunes
expired sessions, then starts a threaded HTTP server.

Security model
--------------
- User accounts are stored in the MySQL ``users`` table with bcrypt-hashed
  passwords and an access_level column (master / admin / editor / viewer).
- Authentication is session-based: POST /api/login verifies credentials
  against the DB and returns a session token. That token is sent on every
  subsequent request via the ``Authorization: Bearer <token>`` header.
- Write endpoints (players, bounties, changelog revert) require a valid
  session with a sufficient access_level.
- On first run a single "master" account is created with a randomly
  generated password. The password is printed once to the server log and
  is never stored in source. The master account can manage other users.
- Every change to players/bounties is recorded in the ``change_log`` table
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
import sys
from http.server import ThreadingHTTPServer

from server.config import missing_db_env, _log
from server.db_base import db_init
from server.users import db_session_prune
from server.handler import Handler


def main():
    missing = missing_db_env()
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


# Initialise the database (create tables + seed) on import so the module
# is ready to serve as soon as it loads — mirroring the original behaviour.
db_init()


if __name__ == "__main__":
    main()
