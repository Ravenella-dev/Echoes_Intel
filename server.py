#!/usr/bin/env python3
"""
EVE Echoes Intel DB — echoes.mobi scraping proxy + persistence server.

Endpoints:
  GET /api/scrape?player=NAME
    -> fetches https://echoes.mobi/killboard/view/player/NAME/summary
       and returns parsed JSON { ok, player, source, data, fetchedAt }

  POST /api/players   (header: X-Admin-Token: echoes2024)
    -> body: { "players": [ ... ] }
       writes the full players array to MySQL (echoes_intel.players table)
       returns { ok, count, savedAt }

  GET /api/health
    -> { ok: true, service: "echoes-proxy" }

Run:  python3 server.py [--port 8000]  (then expose that port)

The server also serves the static frontend files (index.html, css/, js/, data/).
"""

import argparse
import json
import pymysql
import re
import sys
import html as html_lib
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
ECHOES_BASE = "https://echoes.mobi/killboard/view/player"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
# Shared psw for write access — must match ADMIN_PASS in app.js
ADMIN_TOKEN = "echoes2024"


def _log(msg: str) -> None:
    print(f"[echoes-proxy] {msg}", flush=True)


# ---- MySQL config --------------------------------------------------------
# Override via env vars if needed:  ECHOES_DB_HOST, ECHOES_DB_USER, ...
import os
DB_CONFIG = {
    "host":     os.environ.get("ECHOES_DB_HOST", "sql5.freesqldatabase.com"),
    "user":     os.environ.get("ECHOES_DB_USER", "sql5834659"),
    "password": os.environ.get("ECHOES_DB_PASS", "465daY7Eid"),
    "database": os.environ.get("ECHOES_DB_NAME", "sql5834659"),
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


def _db_conn():
    return pymysql.connect(**DB_CONFIG)


def db_init():
    """Create tables if missing and seed example data on first run."""
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id   VARCHAR(64) PRIMARY KEY,
            data JSON NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            `key`   VARCHAR(64) PRIMARY KEY,
            value   LONGTEXT NOT NULL
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
    }
    conn.close()
    return out


def db_save(players):
    """Replace all players in MySQL. Returns savedAt timestamp."""
    saved_at = datetime.now(timezone.utc).isoformat()
    conn = _db_conn()
    cur = conn.cursor()
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
    conn.close()
    _log(f"Saved {len(players)} players to MySQL")
    return saved_at


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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Token")
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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Token")
        self.end_headers()

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return b""
        return self.rfile.read(length)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/players":
            # auth check
            token = self.headers.get("X-Admin-Token", "")
            if token != ADMIN_TOKEN:
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                raw = self._read_body()
                payload = json.loads(raw.decode("utf-8"))
                players = payload.get("players")
                if not isinstance(players, list):
                    self._json(400, {"ok": False, "error": "missing 'players' array"})
                    return
                saved_at = db_save(players)
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

        # static files (frontend)
        if path.startswith("/api/"):
            self._json(404, {"ok": False, "error": "unknown api route"})
            return

        self._static(path)

    def log_message(self, fmt, *args):  # quieter logs
        _log("%s - %s" % (self.address_string(), fmt % args))


def main():
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
