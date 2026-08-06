"""
HTTP handler — the ``Handler`` class that serves every ``/api/*`` endpoint
and the static frontend files.

All of the database work is delegated to the sibling modules; this file is
purely request-routing, auth checks, and JSON serialization.
"""

import json
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

from .config import (
    ROOT,
    ACCESS_LEVELS,
    MASTER_LEVEL,
    has_access,
    verify_password,
    ECHOES_BASE,
    _log,
)
from .db import db_load, db_save
from .bounties import (
    db_bounty_load_all,
    db_bounty_history,
    db_bounty_add,
    db_bounty_get,
    db_bounty_update,
    db_bounty_delete,
)
from .users import (
    db_user_get_by_username,
    db_user_get_by_id,
    db_user_list,
    db_user_create,
    db_user_update,
    db_user_delete,
    db_session_create,
    db_session_get_user,
    db_session_destroy,
    db_session_destroy_all_for_user,
)
from .changelog import (
    db_changelog_list,
    db_changelog_get,
    db_changelog_mark_reverted,
    _apply_revert,
)
from .scraper import fetch_page, parse_summary


class Handler(BaseHTTPRequestHandler):
    server_version = "echoes-proxy/1.0"

    # ---- helpers ----------------------------------------------------------

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

    # ---- POST -------------------------------------------------------------

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

    # ---- GET --------------------------------------------------------------

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

    # ---- PUT --------------------------------------------------------------

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

    # ---- DELETE -----------------------------------------------------------

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
