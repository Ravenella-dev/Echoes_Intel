"""
config.py  —  Configuration, constants, and small helpers.

This is the "ground floor" of the server. Every other module imports
from here, but this module imports from nobody. That keeps the
dependency chain one-directional and easy to follow:

    config.py   (no imports from our own code)
        ^
        |  (imported by)
    db.py, bounties.py, users.py, changelog.py, scraper.py, handler.py

What lives here
---------------
* Paths and URLs (ROOT, ECHOES_BASE, USER_AGENT).
* Access-level definitions (viewer < editor < admin < master).
* Database connection settings read from environment variables / .env.
* Password helpers (hash / verify / generate) using bcrypt.
* The `has_access()` permission check.
* Example seed data (EXAMPLE_PLAYERS, EXAMPLE_BOUNTIES) for first run.
* `_log()` — a tiny print() wrapper so every log line is tagged.
"""

import os
import sys
import string
import secrets
from pathlib import Path

import bcrypt


# ---- Paths & URLs --------------------------------------------------------

# The folder that contains the server/ package's PARENT (the project
# root). Every static file path is resolved relative to this.
ROOT = Path(__file__).resolve().parent.parent

# Try to auto-load a .env file from the project root so database
# credentials can live there instead of being exported in the shell.
# python-dotenv is optional — if it isn't installed, plain env vars
# still work fine.
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# echoes.mobi player summary URL pattern. A player name is URL-quoted
# and inserted where {player} appears (see server/scraper.py).
ECHOES_BASE = "https://echoes.mobi/killboard/view/player"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


# ---- Access levels -------------------------------------------------------

# Ordered lowest -> highest capability. The index in this list IS the
# rank used by has_access() below.
ACCESS_LEVELS = ["viewer", "editor", "admin", "master"]
ACCESS_RANK = {level: i for i, level in enumerate(ACCESS_LEVELS)}
MASTER_LEVEL = "master"

# Session tokens live for this many hours before they expire.
SESSION_TTL_HOURS = 12


# ---- Logging -------------------------------------------------------------

def _log(msg: str) -> None:
    """Print a timestamped, tagged log line (flushed immediately)."""
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
    """Generate a strong random password (letters, digits, safe punctuation)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---- Access-level helpers ------------------------------------------------

def has_access(user_level: str, required_level: str) -> bool:
    """Return True if user_level >= required_level (compared by rank).

    Unknown levels rank -1 (below everyone), so an unknown required
    level (rank 99) can never be satisfied — fail closed.
    """
    return ACCESS_RANK.get(user_level, -1) >= ACCESS_RANK.get(required_level, 99)


# ---- Database config -----------------------------------------------------
# Credentials MUST come from environment variables (never hardcoded).
# The server refuses to start if any are missing (see server.py main()).

_DB_HOST = os.environ.get("ECHOES_DB_HOST")
_DB_USER = os.environ.get("ECHOES_DB_USER")
_DB_PASS = os.environ.get("ECHOES_DB_PASS")
_DB_NAME = os.environ.get("ECHOES_DB_NAME")

DB_CONFIG = {
    "host": _DB_HOST,
    "user": _DB_USER,
    "password": _DB_PASS,
    "database": _DB_NAME,
    "charset": "utf8mb4",
    "autocommit": True,
}


def missing_db_env():
    """Return a list of required DB env vars that are not set."""
    return [k for k, v in {
        "ECHOES_DB_HOST": _DB_HOST,
        "ECHOES_DB_USER": _DB_USER,
        "ECHOES_DB_PASS": _DB_PASS,
        "ECHOES_DB_NAME": _DB_NAME,
    }.items() if not v]


# ---- Seed data (first run only) -----------------------------------------
# These are inserted only when their tables are completely empty, so
# they never overwrite real data. See db_init() in server/db.py.

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

# Example bounties (multiple contributors on the same target show off
# the multi-contributor bounty system).
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
