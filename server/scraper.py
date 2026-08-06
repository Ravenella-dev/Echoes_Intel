"""
Scraper — fetch a player's summary page from echoes.mobi and parse the
stats we care about (kills, losses, ISK, top ships, corporation, etc.).

This module is deliberately self-contained: it only depends on the
standard library and on a couple of constants from :mod:`config`.
"""

import html as html_lib
import re
import urllib.parse
import urllib.request
import urllib.error

from .config import ECHOES_BASE, USER_AGENT, _log


# ---- small parsing helpers ------------------------------------------------


def _format_isk(raw) -> int:
    """Turn '44,808,482,462,924 ISK' or '0 ISK' or '2,377,760,956,578 ISK'
    into a plain integer."""
    if raw is None:
        return 0
    s = str(raw).replace("ISK", "").replace(",", "").replace(" ", "").strip()
    if s in ("", "-", "\u2014"):
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


# ---- network --------------------------------------------------------------


def fetch_page(player: str) -> str:
    """Download the raw HTML of a player's echoes.mobi summary page."""
    url = f"{ECHOES_BASE}/{urllib.parse.quote(player)}/summary"
    _log(f"Fetching {url}")
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ---- parsing --------------------------------------------------------------


def parse_summary(html: str) -> dict:
    """Extract the interesting fields from a summary-page HTML blob.

    Returns a dict with the keys the frontend expects.  Missing fields
    fall back to sensible defaults (zeros / 50&nbsp;% ratios / empty lists)
    so the UI never crashes on a partial page.
    """

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
        out["corporation"] = None if corp in ("-", "\u2014", "") else corp

    # Best kill
    m = re.search(r"Best kill\s*\n\s*(.+?)\s*\n\s*([\d,]+)\s*ISK", blob)
    if m:
        out["bestKill"] = _clean(m.group(1))
        out["bestKillIsk"] = _format_isk(m.group(2) + " ISK")
    else:
        m = re.search(r"Best kill\s*\n\s*(-|\u2014)")
        if m:
            out["bestKill"] = None
            out["bestKillIsk"] = 0

    # Highest loss
    m = re.search(r"Highest loss\s*\n\s*(.+?)\s*\n\s*([\d,]+)\s*ISK", blob)
    if m:
        out["highestLoss"] = _clean(m.group(1))
        out["highestLossIsk"] = _format_isk(m.group(2) + " ISK")
    else:
        m = re.search(r"Highest loss\s*\n\s*(-|\u2014)")
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
