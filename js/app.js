/* ============================================
   EVE Echoes Pilot Intel Database
   Search + detail view + admin CRUD + echoes.mobi scrape
   (jQuery)
   ============================================ */

$(function () {
  "use strict";

  /* ============================================================
     CONFIG
     ============================================================ */
  var DATA_URL = "/api/players";  // served by server.py (MySQL)
  var SCRAPE_URL = "/api/scrape";
  var SAVE_URL = "/api/players";

  // Demo admin credentials (client-side only).
  var ADMIN_USER = "admin";
  var ADMIN_PASS = "echoes2024";
  var SESSION_KEY = "ee_intel_admin_session";
  var STORAGE_KEY = "ee_intel_players_v1";

  /* ============================================================
     STATE
     ============================================================ */
  var DATA = null;
  var TAG_CATS = null;
  var PLAYERS = [];
  var activeFilters = [];
  var currentTerm = "";
  var selectedId = null;
  var isAdmin = false;
  var editingId = null;       // player id being edited (null = adding new)
  var pendingDeleteId = null;
  var lastScrapeData = null;  // echoes.mobi result currently in the form

  var QUICK_FILTERS = [
    "Dangerous", "Weak", "Main Account", "Alt",
    "High Value Target", "Low Value Target",
    "Supercapital Pilot", "Solo PVPer", "Bounty Hunter",
    "Logistics Pilot", "Explorer", "Baiter"
  ];

  /* ============================================================
     UTILITIES
     ============================================================ */
  function formatIsk(value) {
    value = Number(value) || 0;
    if (value >= 1e12) return (value / 1e12).toFixed(2) + " T";
    if (value >= 1e9)  return (value / 1e9).toFixed(2) + " B";
    if (value >= 1e6)  return (value / 1e6).toFixed(2) + " M";
    if (value >= 1e3)  return (value / 1e3).toFixed(1) + " K";
    return value.toString();
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function highlight(text, term) {
    var safe = escapeHtml(text);
    if (!term) return safe;
    var escTerm = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return safe.replace(new RegExp("(" + escTerm + ")", "gi"),
      '<span class="match-highlight">$1</span>');
  }

  function threatClass(level) {
    level = Number(level) || 0;
    if (level >= 7) return "high";
    if (level >= 4) return "med";
    return "low";
  }

  function valueClass(tags) {
    if (tags.indexOf("High Value Target") > -1) return "high-value";
    if (tags.indexOf("Medium Value Target") > -1) return "med-value";
    return "low-value";
  }

  function threatFillColor(level) {
    level = Number(level) || 0;
    if (level >= 7) return "#e74c3c";
    if (level >= 4) return "#f39c12";
    return "#27ae60";
  }

  function threatLabel(level) {
    level = Number(level) || 0;
    if (level >= 8) return "extreme threat";
    if (level >= 6) return "high threat";
    if (level >= 4) return "moderate threat";
    if (level >= 2) return "low threat";
    return "minimal threat";
  }

  function hexA(hex, alpha) {
    var h = (hex || "#7f8c8d").replace("#", "");
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    var r = parseInt(h.substring(0, 2), 16);
    var g = parseInt(h.substring(2, 4), 16);
    var b = parseInt(h.substring(4, 6), 16);
    return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
  }

  function miniTag(tagName) {
    var cat = TAG_CATS[tagName] || { color: "#7f8c8d", icon: "•" };
    return '<span class="mini-tag" style="color:' + cat.color + ';border-color:' +
      hexA(cat.color, 0.3) + '"><span class="ticon">' + (cat.icon || "") +
      '</span>' + escapeHtml(tagName) + '</span>';
  }

  function fullTag(tagName) {
    var cat = TAG_CATS[tagName] || { color: "#7f8c8d", icon: "•" };
    return '<span class="full-tag" style="background:' + hexA(cat.color, 0.13) +
      ';border:1px solid ' + hexA(cat.color, 0.4) + ';color:' + cat.color +
      '"><span class="ticon">' + (cat.icon || "") + '</span>' +
      escapeHtml(tagName) + '</span>';
  }

  function nextId() {
    var max = 0;
    PLAYERS.forEach(function (p) {
      var n = parseInt((p.id || "").replace(/\D/g, ""), 10);
      if (!isNaN(n) && n > max) max = n;
    });
    return "p" + String(max + 1).padStart(3, "0");
  }

  function findPlayer(id) {
    return PLAYERS.find(function (x) { return x.id === id; });
  }

  /* ---------- Toast notifications ---------- */
  function toast(msg, kind) {
    var $t = $('<div class="toast ' + (kind || "") + '">' + escapeHtml(msg) + "</div>");
    $("#toastStack").append($t);
    setTimeout(function () {
      $t.fadeOut(250, function () { $(this).remove(); });
    }, 3200);
  }

  /* ============================================================
     PERSISTENCE (server-side via POST /api/players)
     The server writes changes to data/players.json so they are
     permanent and shared across all users / browsers.
     localStorage is kept as an offline fallback only.
     ============================================================ */
  function loadStoredPlayers() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      var obj = JSON.parse(raw);
      if (obj && Array.isArray(obj.players)) return obj.players;
    } catch (e) { /* ignore */ }
    return null;
  }

  function savePlayers() {
    // 1) always mirror to localStorage as an offline cache
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        players: PLAYERS,
        savedAt: new Date().toISOString()
      }));
    } catch (e) { /* ignore quota errors */ }

    // 2) POST the full players array to the server so it writes players.json
    $.ajax({
      type: "POST",
      url: SAVE_URL,
      contentType: "application/json",
      headers: { "X-Admin-Token": ADMIN_PASS },
      data: JSON.stringify({ players: PLAYERS })
    })
      .done(function (resp) {
        if (resp && resp.ok) {
          toast("Saved to server (" + resp.count + " pilots)", "success");
        }
      })
      .fail(function (xhr) {
        var msg = "Could not save to server (running statically?)";
        try { var j = JSON.parse(xhr.responseText); if (j.error) msg = j.error; } catch (e) {}
        toast(msg + " — kept locally.", "warn");
      });
    return true;
  }

  function resetStoredPlayers() {
    try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
  }

  /* ============================================================
     FILTERING + RESULTS LIST
     ============================================================ */
  function getFilteredPlayers() {
    var term = currentTerm.trim().toLowerCase();
    return PLAYERS.filter(function (p) {
      var passesTags = activeFilters.every(function (f) {
        return (p.tags || []).indexOf(f) > -1;
      });
      if (!passesTags) return false;
      if (!term) return true;
      var hay = [
        p.name, p.corporation, p.alliance || "", p.faction || "",
        p.region || "", (p.tags || []).join(" "),
        (p.typicalShips || []).map(function (s) {
          return s.ship + " " + (s.fitting || []).join(" ");
        }).join(" "),
        p.notes || "", (p.knownAlts || []).join(" ")
      ].join(" ").toLowerCase();
      return hay.indexOf(term) > -1;
    });
  }

  function renderResults() {
    var list = getFilteredPlayers();
    var $list = $("#resultsList");
    var $count = $("#resultsCount");

    $count.html(
      '<span class="num">' + list.length + "</span> pilot" +
      (list.length === 1 ? "" : "s") + " found" +
      (activeFilters.length ? " · " + activeFilters.length + " filter" +
        (activeFilters.length === 1 ? "" : "s") + " active" : "") +
      (isAdmin ? ' · <span style="color:var(--safe)">admin mode</span>' : "")
    );

    if (list.length === 0) {
      var msg = isAdmin
        ? '<div class="admin-empty-hint">No pilots in the database.<br>' +
          '<button class="admin-btn primary" onclick="document.getElementById(\'addPlayerBtn\').click()">+ Add the first pilot</button></div>'
        : '<div class="no-results"><div class="nr-icon">🛰️</div>' +
          "<p>No pilots match your search.<br>Try a different name or clear your filters.</p></div>";
      $list.html(msg);
      return;
    }

    var html = "";
    var term = currentTerm.trim();
    var priorityTags = ["Dangerous", "Supercapital Pilot", "High Value Target",
      "Solo PVPer", "Capital Hotdropper", "Baiter", "Moderate", "Weak",
      "Alt", "Logistics Pilot", "Explorer", "Bounty Hunter"];

    list.forEach(function (p) {
      var vClass = valueClass(p.tags || []);
      var tClass = threatClass(p.threatLevel);
      var isActive = (p.id === selectedId) ? " active" : "";
      var shownTags = [];
      priorityTags.forEach(function (t) {
        if ((p.tags || []).indexOf(t) > -1 && shownTags.length < 3) shownTags.push(t);
      });
      (p.tags || []).forEach(function (t) {
        if (shownTags.indexOf(t) === -1 && shownTags.length < 3) shownTags.push(t);
      });
      var scrapeBadge = p.scrapedAt
        ? '<span class="scraped-badge' + (isStale(p.scrapedAt) ? " stale" : "") +
          '" title="Stats from echoes.mobi · ' + escapeHtml(p.scrapedAt) + '">echoes.mobi</span>'
        : "";

      html +=
        '<div class="player-card ' + vClass + isActive + '" data-id="' + p.id + '">' +
          '<div class="player-card-row">' +
            '<div>' +
              '<div class="player-name">' + highlight(p.name, term) + scrapeBadge + '</div>' +
              '<div class="player-corp">' + highlight(p.corporation || "", term) +
                (p.alliance ? ' · ' + highlight(p.alliance, term) : "") + '</div>' +
            '</div>' +
            '<span class="threat-badge ' + tClass + '">THR ' + (p.threatLevel || 0) + '/10</span>' +
          '</div>' +
          '<div class="player-tags">' + shownTags.map(miniTag).join("") + '</div>' +
          '<div class="player-stats">' +
            '<span><strong>' + (p.killCount || 0).toLocaleString() + '</strong> kills</span>' +
            '<span><strong>' + (p.efficiency || 0).toFixed(1) + '%</strong> eff</span>' +
            '<span><strong>' + formatIsk(p.iskDestroyed || 0) + '</strong> ISK destroyed</span>' +
          '</div>' +
        '</div>';
    });
    $list.html(html);
  }

  function isStale(iso) {
    if (!iso) return false;
    var then = new Date(iso).getTime();
    if (isNaN(then)) return false;
    return (Date.now() - then) > 7 * 24 * 3600 * 1000; // older than 7 days
  }

  /* ============================================================
     DETAIL PANEL
     ============================================================ */
  function statBox(label, value, sub, valueClass) {
    return '<div class="stat-box"><div class="stat-label">' + escapeHtml(label) +
      '</div><div class="stat-value ' + (valueClass || "") + '">' + value + '</div>' +
      (sub ? '<div class="stat-sub">' + escapeHtml(sub) + '</div>' : "") + '</div>';
  }

  function renderDetail(id) {
    var p = findPlayer(id);
    if (!p) {
      $("#detailEmpty").show();
      $("#detailContent").hide();
      return;
    }
    var tClass = threatClass(p.threatLevel);
    var statusClass = (p.status || "").toLowerCase().indexOf("inactive") > -1 ? "inactive" : "active";
    var tagsHtml = (p.tags || []).map(fullTag).join("");
    var scrapeBadge = p.scrapedAt
      ? '<span class="scraped-badge' + (isStale(p.scrapedAt) ? " stale" : "") +
        '" title="Stats scraped from echoes.mobi on ' + escapeHtml(p.scrapedAt) +
        '"> ↻ echoes.mobi · ' + escapeHtml((p.scrapedAt || "").slice(0, 10)) + '</span>'
      : "";

    var statsHtml =
      statBox("Kills", (p.killCount || 0).toLocaleString(), "confirmed killmails", "accent") +
      statBox("Losses", (p.lossCount || 0).toLocaleString(), "ships lost",
        (p.lossCount > p.killCount ? "red" : "")) +
      statBox("Efficiency", (p.efficiency || 0).toFixed(1) + "%", "ISK efficiency",
        ((p.efficiency || 0) >= 75 ? "green" : ((p.efficiency || 0) < 40 ? "red" : ""))) +
      statBox("ISK Destroyed", formatIsk(p.iskDestroyed || 0), "total value killed", "gold") +
      statBox("ISK Lost", formatIsk(p.iskLost || 0), "total value lost", "") +
      statBox("Threat Level", (p.threatLevel || 0) + " / 10", threatLabel(p.threatLevel),
        (p.threatLevel >= 7 ? "red" : (p.threatLevel >= 4 ? "gold" : "green")));

    var shipsHtml = "";
    (p.typicalShips || []).forEach(function (s) {
      var fitHtml = (s.fitting || []).map(function (f) {
        return '<span class="fit-item">' + escapeHtml(f) + '</span>';
      }).join("");
      shipsHtml +=
        '<div class="ship-card"><div class="ship-card-head">' +
        '<span class="ship-name">🚀 ' + escapeHtml(s.ship) + '</span>' +
        '<span class="ship-role">' + escapeHtml(s.role || "") + '</span></div>' +
        '<div class="fitting-list">' + fitHtml + '</div></div>';
    });
    if (!shipsHtml) shipsHtml = '<p style="color:var(--text-faint);font-size:13px;">No ship data on file.</p>';

    var altsHtml;
    if (p.knownAlts && p.knownAlts.length) {
      altsHtml = '<div class="alts-box">' + p.knownAlts.map(function (a) {
        return '<span class="alt-chip"><span class="alt-label">ALT</span>' + escapeHtml(a) + '</span>';
      }).join("") + '</div>';
    } else {
      altsHtml = '<p style="color:var(--text-faint);font-size:13px;">No known alts on file.</p>';
    }

    var bountyHtml = (p.bounty && p.bounty > 0)
      ? '<div class="bounty-box"><span class="bounty-label">🩸 Active Bounty</span>' +
        '<span class="bounty-amount">' + formatIsk(p.bounty) + ' ISK</span></div>'
      : '<div class="bounty-box no-bounty"><span class="bounty-label">Bounty</span>' +
        '<span class="bounty-amount">No active bounty</span></div>';

    // admin-only action row
    var adminActions = isAdmin
      ? '<div class="detail-admin-actions">' +
        '<button class="admin-btn" id="detailEditBtn" data-id="' + p.id + '">✎ Edit Pilot</button>' +
        '<button class="admin-btn" id="detailScrapeBtn" data-id="' + p.id + '">↻ Fetch from echoes.mobi</button>' +
        '<button class="admin-btn danger" id="detailDeleteBtn" data-id="' + p.id + '">🗑 Remove</button>' +
        '</div>'
      : "";

    var html =
      '<div class="detail-header">' +
        '<div class="detail-top">' +
          '<div class="detail-name">' + escapeHtml(p.name) + scrapeBadge + '</div>' +
          '<span class="detail-status ' + statusClass + '">' + escapeHtml(p.status || "Active") + '</span>' +
        '</div>' +
        '<div class="detail-affil">' + escapeHtml(p.corporation || "—") +
          (p.alliance ? ' <span class="sep">›</span> ' + escapeHtml(p.alliance) :
            ' <span class="sep">›</span> <em>no alliance</em>') + '</div>' +
        '<div class="detail-meta">' +
          (p.faction ? 'Faction: ' + escapeHtml(p.faction) + ' · ' : "") +
          'Region: ' + escapeHtml(p.region || "Unknown") +
          ' · Last seen: ' + escapeHtml(p.lastSeen || "Unknown") + '</div>' +
        '<div class="threat-meter"><span>Threat</span>' +
          '<div class="threat-bar"><div class="threat-fill" style="width:' +
          ((p.threatLevel || 0) * 10) + '%;background:' + threatFillColor(p.threatLevel) +
          ';box-shadow:0 0 8px ' + threatFillColor(p.threatLevel) + ';"></div></div>' +
          '<span class="threat-num" style="color:' + threatFillColor(p.threatLevel) + '">' +
          (p.threatLevel || 0) + '/10</span></div>' +
        '<div class="detail-tags">' + tagsHtml + '</div>' +
      '</div>' +
      '<div class="stat-grid">' + statsHtml + '</div>' +
      bountyHtml +
      '<div class="section-heading"><span class="sh-icon">🚀</span> Typical Ships &amp; Fittings</div>' +
      shipsHtml +
      '<div class="section-heading"><span class="sh-icon">👥</span> Known Alts</div>' +
      altsHtml +
      '<div class="section-heading"><span class="sh-icon">📝</span> Field Notes</div>' +
      '<div class="notes-box">' + escapeHtml(p.notes || "No notes on file.") + '</div>' +
      adminActions;

    $("#detailEmpty").hide();
    $("#detailContent").html(html).show();
  }

  /* ============================================================
     ADMIN AUTH
     ============================================================ */
  function checkSession() {
    try {
      var s = sessionStorage.getItem(SESSION_KEY);
      if (s === "1") { setAdmin(true, true); return; }
    } catch (e) {}
    setAdmin(false);
  }

  function setAdmin(on, silent) {
    isAdmin = on;
    if (on) {
      try { sessionStorage.setItem(SESSION_KEY, "1"); } catch (e) {}
      $("#adminStatus").addClass("loggedIn").find(".who").text("admin");
      $("#loginBtn").hide();
      $("#logoutBtn").show();
      $("#addPlayerBtn").show();
    } else {
      try { sessionStorage.removeItem(SESSION_KEY); } catch (e) {}
      $("#adminStatus").removeClass("loggedIn").find(".who").text("Guest");
      $("#loginBtn").show();
      $("#logoutBtn").hide();
      $("#addPlayerBtn").hide();
    }
    renderResults();
    if (selectedId) renderDetail(selectedId);
    if (!silent && on) toast("Logged in as admin", "success");
  }

  function openLogin() {
    $("#loginUser").val("");
    $("#loginPass").val("");
    $("#loginError").removeClass("visible");
    openModal("loginModal");
    setTimeout(function () { $("#loginUser").focus(); }, 100);
  }

  function doLogin() {
    var u = $("#loginUser").val().trim();
    var p = $("#loginPass").val();
    if (u === ADMIN_USER && p === ADMIN_PASS) {
      closeModal("loginModal");
      setAdmin(true);
    } else {
      $("#loginError").addClass("visible");
      $("#loginPass").val("").focus();
    }
  }

  /* ============================================================
     MODAL HELPERS
     ============================================================ */
  function openModal(id) { $("#" + id).addClass("visible"); }
  function closeModal(id) { $("#" + id).removeClass("visible"); }

  /* ============================================================
     PLAYER FORM (add / edit)
     ============================================================ */
  function openPlayerForm(id) {
    editingId = id || null;
    lastScrapeData = null;
    var p = id ? findPlayer(id) : blankPlayer();
    $("#playerFormTitle").html(id
      ? '<span class="mt-icon">✎</span> Edit Pilot'
      : '<span class="mt-icon">＋</span> Add Pilot');
    $("#playerFormDelete").toggle(!!id);
    $("#playerFormBody").html(buildFormHtml(p, !!id));
    // wire tag picker
    renderTagPicker(p.tags || []);
    // wire ship editor
    renderShipEditor(p.typicalShips || []);
    openModal("playerFormModal");
  }

  function blankPlayer() {
    return {
      id: nextId(), name: "", corporation: "", alliance: "", faction: "",
      region: "", tags: [], threatLevel: 5, killCount: 0, lossCount: 0,
      iskDestroyed: 0, iskLost: 0, efficiency: 50, lastSeen: todayStr(),
      status: "Active", typicalShips: [], notes: "", knownAlts: [], bounty: 0,
      scrapedAt: null
    };
  }

  function todayStr() {
    return new Date().toISOString().slice(0, 10);
  }

  function buildFormHtml(p, isEdit) {
    // all known tag names (from categories) sorted
    var tagNames = Object.keys(TAG_CATS).sort();

    return (
      '<div class="echoes-fetch">' +
        '<div style="font-size:13px;font-weight:600;color:var(--accent);margin-bottom:10px;">↻ Auto-fill from echoes.mobi</div>' +
        '<div class="echoes-fetch-head">' +
          '<div class="form-field">' +
            '<label>Pilot name on echoes.mobi</label>' +
            '<input type="text" id="scrapeName" placeholder="Enter a pilot..." value="' + escapeHtml(isEdit ? p.name : "") + '" />' +
          '</div>' +
          '<button class="admin-btn primary" id="scrapeBtn" style="height:38px;margin-bottom:0;">Fetch stats</button>' +
        '</div>' +
        '<div class="echoes-fetch-status" id="scrapeStatus"></div>' +
        '<div class="echoes-preview" id="scrapePreview"></div>' +
      '</div>' +

      '<div class="form-row">' +
        '<div class="form-field"><label>Pilot name <span class="req">*</span></label>' +
          '<input type="text" id="fName" value="' + escapeHtml(p.name) + '" /></div>' +
        '<div class="form-field"><label>Corporation</label>' +
          '<input type="text" id="fCorp" value="' + escapeHtml(p.corporation || "") + '" /></div>' +
      '</div>' +
      '<div class="form-row">' +
        '<div class="form-field"><label>Alliance</label>' +
          '<input type="text" id="fAlliance" value="' + escapeHtml(p.alliance || "") + '" placeholder="(leave blank if none)" /></div>' +
        '<div class="form-field"><label>Faction</label>' +
          '<input type="text" id="fFaction" value="' + escapeHtml(p.faction || "") + '" /></div>' +
      '</div>' +
      '<div class="form-row">' +
        '<div class="form-field"><label>Region</label>' +
          '<input type="text" id="fRegion" value="' + escapeHtml(p.region || "") + '" /></div>' +
        '<div class="form-field"><label>Status</label>' +
          '<select id="fStatus">' +
            ['<option value="Active">Active</option>',
             '<option value="Inactive">Inactive</option>',
             '<option value="Inactive (reported on break)">Inactive (reported on break)</option>']
            .map(function (o) { return o; }).join("").replace(
              'value="' + escapeHtml(p.status) + '"',
              'value="' + escapeHtml(p.status) + '" selected') +
          '</select></div>' +
      '</div>' +

      '<div class="form-field"><label>Tags</label>' +
        '<div class="tag-picker" id="tagPicker"></div>' +
        '<div class="hint">Click tags to toggle. Selected tags get highlighted.</div>' +
      '</div>' +

      '<div class="form-row">' +
        '<div class="form-field"><label>Threat level (0–10)</label>' +
          '<input type="number" id="fThreat" min="0" max="10" step="1" value="' + (p.threatLevel || 0) + '" /></div>' +
        '<div class="form-field"><label>Bounty (ISK)</label>' +
          '<input type="number" id="fBounty" min="0" step="1" value="' + (p.bounty || 0) + '" /></div>' +
      '</div>' +

      '<div class="form-row">' +
        '<div class="form-field"><label>Kills</label>' +
          '<input type="number" id="fKills" min="0" value="' + (p.killCount || 0) + '" /></div>' +
        '<div class="form-field"><label>Losses</label>' +
          '<input type="number" id="fLosses" min="0" value="' + (p.lossCount || 0) + '" /></div>' +
      '</div>' +
      '<div class="form-row">' +
        '<div class="form-field"><label>ISK destroyed</label>' +
          '<input type="number" id="fIskDest" min="0" value="' + (p.iskDestroyed || 0) + '" /></div>' +
        '<div class="form-field"><label>ISK lost</label>' +
          '<input type="number" id="fIskLost" min="0" value="' + (p.iskLost || 0) + '" /></div>' +
      '</div>' +
      '<div class="form-row">' +
        '<div class="form-field"><label>Efficiency (%)</label>' +
          '<input type="number" id="fEff" min="0" max="100" step="0.1" value="' + (p.efficiency || 0) + '" /></div>' +
        '<div class="form-field"><label>Last seen</label>' +
          '<input type="date" id="fLastSeen" value="' + escapeHtml(p.lastSeen || todayStr()) + '" /></div>' +
      '</div>' +

      '<div class="form-field"><label>Typical ships &amp; fittings</label>' +
        '<div class="ship-editor" id="shipEditor"></div>' +
        '<button class="add-ship-btn" id="addShipBtn">+ Add ship</button>' +
      '</div>' +

      '<div class="form-field"><label>Known alts (comma separated)</label>' +
        '<input type="text" id="fAlts" value="' + escapeHtml((p.knownAlts || []).join(", ")) + '" /></div>' +

      '<div class="form-field"><label>Field notes</label>' +
        '<textarea id="fNotes" rows="4">' + escapeHtml(p.notes || "") + '</textarea></div>'
    );
  }

  /* ---- tag picker ---- */
  function renderTagPicker(selected) {
    var $box = $("#tagPicker").empty();
    Object.keys(TAG_CATS).sort().forEach(function (name) {
      var cat = TAG_CATS[name];
      var sel = (selected || []).indexOf(name) > -1 ? " selected" : "";
      var $c = $('<span class="tag-pick' + sel + '" data-tag="' + escapeHtml(name) + '">' +
        '<span>' + (cat.icon || "") + '</span> ' + escapeHtml(name) + '</span>');
      $c.css(sel ? {
        background: hexA(cat.color, 0.2),
        "border-color": hexA(cat.color, 0.5),
        color: cat.color
      } : {});
      $box.append($c);
    });
  }

  $(document).on("click", ".tag-pick", function () {
    var $t = $(this);
    var name = $t.data("tag");
    var cat = TAG_CATS[name] || { color: "#7f8c8d" };
    if ($t.hasClass("selected")) {
      $t.removeClass("selected").css({ background: "", "border-color": "", color: "" });
    } else {
      $t.addClass("selected").css({
        background: hexA(cat.color, 0.2),
        "border-color": hexA(cat.color, 0.5),
        color: cat.color
      });
    }
  });

  function getSelectedTags() {
    var tags = [];
    $("#tagPicker .tag-pick.selected").each(function () {
      tags.push($(this).data("tag"));
    });
    return tags;
  }

  /* ---- ship editor ---- */
  function renderShipEditor(ships) {
    var $ed = $("#shipEditor").empty();
    (ships && ships.length ? ships : []).forEach(function (s) {
      $ed.append(shipRowHtml(s.ship || "", s.role || "", (s.fitting || []).join("\n")));
    });
    if (!ships || !ships.length) {
      $ed.append(shipRowHtml("", "", ""));
    }
  }

  function shipRowHtml(ship, role, fitting) {
    return (
      '<div class="ship-edit-row">' +
        '<div class="ship-edit-row-head">' +
          '<input class="se-ship" placeholder="Ship name (e.g. Naglfar)" value="' + escapeHtml(ship) + '" />' +
          '<input class="se-role ship-edit-role" placeholder="Role (e.g. Dreadnought brawler)" value="' + escapeHtml(role) + '" />' +
          '<button class="remove-ship-btn" title="Remove ship">×</button>' +
        '</div>' +
        '<textarea class="fit-input" placeholder="Fittings — one per line (e.g. 3x 3500mm Railgun I)" rows="3">' +
          escapeHtml(fitting) + '</textarea>' +
      '</div>'
    );
  }

  function collectShips() {
    var ships = [];
    $("#shipEditor .ship-edit-row").each(function () {
      var ship = $(this).find(".se-ship").val().trim();
      var role = $(this).find(".se-role").val().trim();
      var fitting = $(this).find(".fit-input").val();
      var fitArr = fitting.split("\n").map(function (s) { return s.trim(); })
        .filter(function (s) { return s.length; });
      if (ship || role || fitArr.length) {
        ships.push({ ship: ship, role: role, fitting: fitArr });
      }
    });
    return ships;
  }

  /* ---- echoes.mobi fetch ---- */
  function doScrape() {
    var name = $("#scrapeName").val().trim();
    var $st = $("#scrapeStatus");
    var $pv = $("#scrapePreview");
    if (!name) {
      $st.attr("class", "echoes-fetch-status error").text("Enter a pilot name first.");
      return;
    }
    $st.attr("class", "echoes-fetch-status loading").text("Fetching from echoes.mobi…");
    $pv.removeClass("visible").empty();
    $.getJSON(SCRAPE_URL, { player: name })
      .done(function (resp) {
        if (!resp || !resp.ok) {
          $st.attr("class", "echoes-fetch-status error")
            .text("Error: " + ((resp && resp.error) || "unknown"));
          return;
        }
        var d = resp.data;
        lastScrapeData = d;
        lastScrapeData.fetchedAt = resp.fetchedAt;
        $st.attr("class", "echoes-fetch-status success")
          .text("✓ Fetched " + (d.name || name) + " from echoes.mobi. Click \"Apply stats to form\" to fill in.");
        $pv.html(previewHtml(d) +
          '<div style="margin-top:10px;"><button class="admin-btn primary" id="applyScrapeBtn">Apply stats to form</button></div>'
        ).addClass("visible");
        // auto-fill name if form name is empty
        if (!$("#fName").val().trim() && d.name) $("#fName").val(d.name);
      })
      .fail(function (xhr) {
        var msg = "Failed to reach scrape proxy.";
        try { var j = JSON.parse(xhr.responseText); if (j.error) msg = j.error; } catch (e) {}
        $st.attr("class", "echoes-fetch-status error").text("✗ " + msg);
      });
  }

  function previewHtml(d) {
    function item(label, val, cls) {
      return '<div class="ep-item"><div class="ep-label">' + label + '</div>' +
        '<div class="ep-value ' + (cls || "") + '">' + val + '</div></div>';
    }
    var ships = (d.topShipsByKills || []).map(function (s) {
      return escapeHtml(s.ship) + " (" + s.count + ")";
    }).join(", ");
    return (
      '<div style="color:var(--text-dim);margin-bottom:4px;">Preview of scraped data:</div>' +
      '<div class="ep-grid">' +
        item("Kills", (d.killedShips || 0).toLocaleString(), "accent") +
        item("Losses", (d.lostShips || 0).toLocaleString(), "red") +
        item("ISK destroyed", formatIsk(d.iskDestroyed || 0), "gold") +
        item("ISK lost", formatIsk(d.iskLost || 0), "") +
        item("ISK efficiency", (d.iskEfficiencyDangerous || 0) + "%",
          ((d.iskEfficiencyDangerous || 0) >= 75 ? "green" : "red")) +
        item("Kill ratio", (100 - d.killRatioDangerous || 0) + "%", "") +
        item("Corporation", escapeHtml(d.corporation || "—"), "") +
        item("Best kill", escapeHtml(d.bestKill || "—") +
          (d.bestKillIsk ? " · " + formatIsk(d.bestKillIsk) : ""), "") +
      '</div>' +
      (ships ? '<div style="margin-top:8px;font-size:11px;color:var(--text-dim);">' +
        'Top ships by kills: ' + ships + '</div>' : "")
    );
  }

  function applyScrapeToForm() {
    if (!lastScrapeData) return;
    var d = lastScrapeData;
    $("#fKills").val(d.killedShips || 0);
    $("#fLosses").val(d.lostShips || 0);
    $("#fIskDest").val(d.iskDestroyed || 0);
    $("#fIskLost").val(d.iskLost || 0);
    $("#fEff").val((d.iskEfficiencyDangerous || d.efficiency || 0).toFixed(1));
    if (d.corporation && !$("#fCorp").val().trim()) $("#fCorp").val(d.corporation);
    if (d.name && !$("#fName").val().trim()) $("#fName").val(d.name);
    // auto-fill top ship as a typical ship if none present
    var existing = collectShips();
    if ((!existing || !existing.length) && d.topShipsByKills && d.topShipsByKills.length) {
      var $ed = $("#shipEditor").empty();
      d.topShipsByKills.slice(0, 3).forEach(function (s) {
        $ed.append(shipRowHtml(s.ship, "Top flown by kills (echoes.mobi)", ""));
      });
    }
    toast("Scraped stats applied to form", "success");
  }

  /* ---- collect + save ---- */
  function collectForm() {
    var name = $("#fName").val().trim();
    if (!name) { $("#fName").focus(); toast("Pilot name is required", "error"); return null; }
    var altsStr = $("#fAlts").val().trim();
    var alts = altsStr ? altsStr.split(",").map(function (s) { return s.trim(); })
      .filter(function (s) { return s.length; }) : [];
    var p = {
      id: editingId || nextId(),
      name: name,
      corporation: $("#fCorp").val().trim() || null,
      alliance: $("#fAlliance").val().trim() || null,
      faction: $("#fFaction").val().trim() || null,
      region: $("#fRegion").val().trim() || null,
      tags: getSelectedTags(),
      threatLevel: parseInt($("#fThreat").val(), 10) || 0,
      killCount: parseInt($("#fKills").val(), 10) || 0,
      lossCount: parseInt($("#fLosses").val(), 10) || 0,
      iskDestroyed: parseFloat($("#fIskDest").val()) || 0,
      iskLost: parseFloat($("#fIskLost").val()) || 0,
      efficiency: parseFloat($("#fEff").val()) || 0,
      lastSeen: $("#fLastSeen").val() || todayStr(),
      status: $("#fStatus").val() || "Active",
      typicalShips: collectShips(),
      notes: $("#fNotes").val().trim() || "",
      knownAlts: alts,
      bounty: parseFloat($("#fBounty").val()) || 0
    };
    // preserve scrapedAt if we just re-scraped or editing existing
    if (lastScrapeData && lastScrapeData.fetchedAt) {
      p.scrapedAt = lastScrapeData.fetchedAt;
    } else if (editingId) {
      var existing = findPlayer(editingId);
      if (existing && existing.scrapedAt) p.scrapedAt = existing.scrapedAt;
    }
    return p;
  }

  function savePlayerFromForm() {
    var p = collectForm();
    if (!p) return;
    if (editingId) {
      var idx = PLAYERS.findIndex(function (x) { return x.id === editingId; });
      if (idx > -1) PLAYERS[idx] = p;
      toast("Updated pilot: " + p.name, "success");
    } else {
      PLAYERS.push(p);
      toast("Added pilot: " + p.name, "success");
    }
    savePlayers();
    selectedId = p.id;
    closeModal("playerFormModal");
    renderResults();
    renderDetail(p.id);
  }

  /* ---- delete ---- */
  function askDelete(id) {
    var p = findPlayer(id);
    if (!p) return;
    pendingDeleteId = id;
    $("#confirmMsg").html(
      'Remove <span class="confirm-name">' + escapeHtml(p.name) + '</span> from the intel database? ' +
      '<strong>This cannot be undone.</strong>'
    );
    openModal("confirmModal");
  }

  function confirmDelete() {
    if (!pendingDeleteId) return;
    var p = findPlayer(pendingDeleteId);
    PLAYERS = PLAYERS.filter(function (x) { return x.id !== pendingDeleteId; });
    savePlayers();
    if (selectedId === pendingDeleteId) {
      selectedId = null;
      $("#detailEmpty").show();
      $("#detailContent").hide();
    }
    closeModal("confirmModal");
    closeModal("playerFormModal");
    toast("Removed pilot: " + (p ? p.name : ""), "warn");
    pendingDeleteId = null;
    renderResults();
  }

  /* ---- scrape from detail panel ---- */
  function scrapeFromDetail(id) {
    var p = findPlayer(id);
    if (!p) return;
    openPlayerForm(id);
    $("#scrapeName").val(p.name);
    setTimeout(doScrape, 150);
  }

  /* ============================================================
     EVENT WIRING
     ============================================================ */

  // search
  var searchTimer = null;
  $("#searchInput").on("input", function () {
    var val = $(this).val();
    currentTerm = val;
    $("#searchClear").toggleClass("visible", val.length > 0);
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderResults, 120);
  });

  $("#searchClear").on("click", function () {
    $("#searchInput").val("").focus();
    currentTerm = "";
    $(this).removeClass("visible");
    renderResults();
  });

  // filter chips
  function buildFilterChips() {
    var $bar = $("#filterBar");
    QUICK_FILTERS.forEach(function (tag) {
      $bar.append('<button class="filter-chip" data-tag="' + escapeHtml(tag) + '">' +
        escapeHtml(tag) + '</button>');
    });
  }

  $(document).on("click", ".filter-chip", function () {
    var tag = $(this).data("tag");
    var idx = activeFilters.indexOf(tag);
    if (idx > -1) { activeFilters.splice(idx, 1); $(this).removeClass("active"); }
    else { activeFilters.push(tag); $(this).addClass("active"); }
    renderResults();
  });

  // player card click
  $(document).on("click", ".player-card", function (e) {
    // ignore clicks on the scrape badge (no action)
    selectedId = $(this).data("id");
    $(".player-card").removeClass("active");
    $(this).addClass("active");
    renderDetail(selectedId);
    if (window.matchMedia("(max-width: 900px)").matches) {
      $("#detailPanel").get(0).scrollIntoView({ behavior: "smooth" });
    }
  });

  // Esc clears search/filters
  $(document).on("keydown", function (e) {
    if (e.key === "Escape") {
      if ($(".modal-overlay.visible").length) {
        $(".modal-overlay.visible").removeClass("visible");
        return;
      }
      if (currentTerm || activeFilters.length) {
        $("#searchInput").val("");
        currentTerm = "";
        activeFilters = [];
        $(".filter-chip").removeClass("active");
        $("#searchClear").removeClass("visible");
        renderResults();
      }
    }
  });

  // ---- admin buttons ----
  $("#loginBtn").on("click", openLogin);
  $("#logoutBtn").on("click", function () {
    setAdmin(false);
    toast("Logged out", "warn");
  });
  $("#addPlayerBtn").on("click", function () {
    if (!isAdmin) return;
    openPlayerForm(null);
  });
  $("#loginSubmit").on("click", doLogin);
  $("#loginPass,#loginUser").on("keydown", function (e) {
    if (e.key === "Enter") doLogin();
  });

  // generic modal close
  $(document).on("click", "[data-close-modal]", function () {
    closeModal($(this).data("close-modal"));
  });
  $(document).on("click", ".modal-overlay", function (e) {
    if (e.target === this) $(this).removeClass("visible");
  });

  // player form actions
  $(document).on("click", "#addShipBtn", function () {
    $("#shipEditor").append(shipRowHtml("", "", ""));
  });
  $(document).on("click", ".remove-ship-btn", function () {
    if ($("#shipEditor .ship-edit-row").length > 1) {
      $(this).closest(".ship-edit-row").remove();
    } else {
      $(this).closest(".ship-edit-row").find("input,textarea").val("");
    }
  });
  $(document).on("click", "#scrapeBtn", doScrape);
  $(document).on("click", "#applyScrapeBtn", applyScrapeToForm);
  $("#playerFormSave").on("click", savePlayerFromForm);
  $("#playerFormDelete").on("click", function () {
    if (editingId) { closeModal("playerFormModal"); askDelete(editingId); }
  });
  $("#confirmDeleteBtn").on("click", confirmDelete);

  // detail-panel admin buttons (delegated because detail re-renders)
  $(document).on("click", "#detailEditBtn", function () {
    openPlayerForm($(this).data("id"));
  });
  $(document).on("click", "#detailScrapeBtn", function () {
    scrapeFromDetail($(this).data("id"));
  });
  $(document).on("click", "#detailDeleteBtn", function () {
    askDelete($(this).data("id"));
  });

  /* ============================================================
     INIT
     ============================================================ */
  function init() {
    buildFilterChips();
    checkSession();

    $.getJSON(DATA_URL)
      .done(function (data) {
        DATA = data;
        TAG_CATS = data.tagCategories || {};
        // The server file is the source of truth (edits are written back
        // to players.json by POST /api/players). We only fall back to a
        // localStorage copy if the JSON looks stale/empty (static-host
        // scenario where the backend isn't available).
        var serverPlayers = data.players || [];
        var stored = loadStoredPlayers();
        if (serverPlayers.length > 0) {
          PLAYERS = serverPlayers.slice();
        } else if (stored) {
          PLAYERS = stored;
        } else {
          PLAYERS = serverPlayers.slice();
        }
        renderResults();
        $("#searchInput").focus();
      })
      .fail(function () {
        $("#resultsCount").html(
          '<span style="color:var(--danger)">⚠ Failed to load pilot database.</span><br>' +
          '<span style="font-size:11px;color:var(--text-faint)">' +
          "Serve the project via server.py (python3 server.py) so the JSON loads.</span>"
        );
      });
  }

  init();
});
