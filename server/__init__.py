"""
Echoes Intel — server package.

The backend was originally a single 1,700-line ``server.py``.  It has been
split into focused modules so that each concern lives in its own file:

    config.py     – environment, constants, password + access helpers
    db_base.py    – raw MySQL connection + table creation / seeding
    db.py         – player load / save / restore / delete
    bounties.py   – bounty CRUD + history logging
    users.py      – user accounts + session management
    changelog.py  – change-log records + reversion logic
    scraper.py    – echoes.mobi page fetch + summary parser
    handler.py    – HTTP request handler (all /api endpoints + static files)

``server.py`` (one level up) is now just a thin entry point that calls
``db_init()`` and starts the threaded HTTP server.
"""
