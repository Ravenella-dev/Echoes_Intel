# EVE Echoes — Pilot Intel Database

A pilot dossier & threat-assessment system for EVE Echoes, with an
echoes.mobi scraping proxy, MySQL persistence, a bounty system, user
authentication with hashed passwords and access levels, and a full
changelog with a reversion system.

## Features

- **Pilot database** with search, filtering, and detailed dossiers (ships, fittings, threat assessment, field notes).
- **Bounty system** with multiple contributors per target and bounty history.
- **echoes.mobi scrape proxy** to fetch and parse pilot killboard stats.
- **Secure authentication** — user accounts stored in MySQL with bcrypt-hashed passwords and access levels. No credentials are stored in source code or client-side JavaScript.
- **Access levels:** `viewer` (read-only), `editor` (add/edit/remove pilots & bounties), `admin` (view & revert changelog), `master` (manage users; changes by master are not logged).
- **Changelog with reversion** — every add/edit/remove of a pilot or bounty by a non-master user is recorded with before/after snapshots, who made the change, and a timestamp. Admins can revert any entry to restore prior state.

## Security model

- Passwords are hashed with **bcrypt** (cost factor 12) and never stored in plaintext.
- Authentication is **session-token based**: `POST /api/login` verifies credentials and returns a bearer token, sent on subsequent requests via the `Authorization: Bearer <token>` header.
- Database credentials are supplied via **environment variables** only — the server refuses to start if any are missing.
- A single **master account** is created automatically on first run with a randomly generated password, printed once to the server log. Use it to create and manage other users.
- The previous hardcoded admin token (`echoes2024`) and client-side credential check have been **removed**.

## Setup

### 1. Prerequisites

- Python 3.8+
- A MySQL database

Install Python dependencies:

```bash
pip install -r requirements.txt
```

### 2. Configure database credentials (environment variables)

The server reads its database connection from environment variables. Set
them before launching — they are **not** stored in source:

```bash
export ECHOES_DB_HOST=your-db-host
export ECHOES_DB_USER=your-db-user
export ECHOES_DB_PASS=your-db-password
export ECHOES_DB_NAME=your-db-name
```

### 3. Run the server

```bash
python3 server.py --port 8000
```

On **first run**, the server creates all required tables (`players`,
`meta`, `bounties`, `bounty_history`, `users`, `sessions`,
`change_log`) and seeds example pilots/bounties. It also creates the
**master account** and prints the generated password to the log:

```
[echoes-proxy] ================================================================
[echoes-proxy] MASTER ACCOUNT CREATED
[echoes-proxy]   username: master
[echoes-proxy]   password: <random 20-char password>
[echoes-proxy]   (This password is shown only once. Store it safely.)
[echoes-proxy]   Log in, then change it or create other users via the UI.
[echoes-proxy] ================================================================
```

**Copy and save this password immediately** — it is not shown again.

### 4. Log in and manage users

1. Open the site in your browser and click **Admin Login**.
2. Log in with `master` and the generated password.
3. Click **Users** to create new accounts and assign access levels
   (`viewer`, `editor`, `admin`, `master`).
4. (Optional) Set a new password for the master account from the Users panel.

## API reference

| Method | Endpoint | Access | Description |
|--------|----------|--------|-------------|
| GET | `/api/health` | public | Health check |
| GET | `/api/players` | public | Load all pilots + bounties + history |
| POST | `/api/players` | editor+ | Replace the full pilot set |
| GET | `/api/scrape?player=NAME` | public | Fetch & parse echoes.mobi stats |
| GET | `/api/bounties` | public | List bounties + bounty history |
| POST | `/api/bounties` | editor+ | Create a bounty |
| PUT | `/api/bounties/<id>` | editor+ | Update a bounty |
| DELETE | `/api/bounties/<id>` | editor+ | Delete a bounty |
| POST | `/api/login` | public | Authenticate, returns session token |
| POST | `/api/logout` | auth | Invalidate current session |
| GET | `/api/session` | auth | Current user + access level |
| GET | `/api/users` | master | List all users |
| POST | `/api/users` | master | Create a user |
| PUT | `/api/users/<id>` | master | Update user / level / password |
| DELETE | `/api/users/<id>` | master | Delete a user (not self/master) |
| GET | `/api/changelog` | admin+ | List changelog entries |
| POST | `/api/changelog/<id>/revert` | admin+ | Revert a change |

### Access levels (ascending)

- **viewer** — read-only.
- **editor** — viewer + add/edit/remove pilots & bounties (logged in changelog).
- **admin** — editor + view changelog + revert changes.
- **master** — admin + manage users. Changes made by the master account are **not** recorded in the changelog.

## Changelog & reversion

Every mutation of a pilot or bounty made by a non-master user is recorded
in the `change_log` table with:

- `entity_type` / `entity_id` — what was changed
- `action` — `add`, `edit`, or `remove`
- `snapshot_before` / `snapshot_after` — JSON snapshots of the entity
- `changed_by` / `changed_by_id` — who made the change
- `changed_at` — timestamp
- `reverted` — whether this entry has been reverted

Admins can open the **Changelog** panel and click **Revert** on any
entry. Reversion restores the entity to its prior state (for
`edit`/`remove`) or removes the entity that was added (for `add`).

## License

See repository for details.
