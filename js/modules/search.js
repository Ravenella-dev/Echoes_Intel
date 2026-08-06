/* ============================================================
   search.js  —  Search, filtering, and the pilot list
   ------------------------------------------------------------
   This file handles the left side of the screen: the search box,
   the filter chips, and the list of pilot cards that results from
   searching/filtering.

   Key functions:
     getFilteredPlayers()  -> apply search + filters to EI.PLAYERS
     renderResults()       -> draw the filtered pilot cards into #resultsList
   ============================================================ */

EI = EI || {};

// Apply the current search term + active tag filters to the full
// player list and return only the matching pilots.
EI.getFilteredPlayers = function () {
  var term = EI.currentTerm.trim().toLowerCase();
  return EI.PLAYERS.filter(function (p) {
    var passesTags = EI.activeFilters.every(function (f) {
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
};

// Draw the filtered pilot cards into the results list on the left.
EI.renderResults = function () {
  var list = EI.getFilteredPlayers();
  var $list = $("#resultsList");
  var $count = $("#resultsCount");

  $count.html(
    '<span class="num">' + list.length + "</span> pilot" +
    (list.length === 1 ? "" : "s") + " found" +
    (EI.activeFilters.length ? " · " + EI.activeFilters.length + " filter" +
      (EI.activeFilters.length === 1 ? "" : "s") + " active" : "") +
    (EI.isAdmin ? ' · <span style="color:var(--safe)">admin mode</span>' : "")
  );

  if (list.length === 0) {
    var msg = EI.isAdmin
      ? '<div class="admin-empty-hint">No pilots in the database.<br>' +
        '<button class="admin-btn primary" onclick="document.getElementById(\'addPlayerBtn\').click()">+ Add the first pilot</button></div>'
      : '<div class="no-results"><div class="nr-icon">🛰️</div>' +
        "<p>No pilots match your search.<br>Try a different name or clear your filters.</p></div>";
    $list.html(msg);
    return;
  }

  var html = "";
  var term = EI.currentTerm.trim();
  var priorityTags = ["Dangerous", "Supercapital Pilot", "High Value Target",
    "Solo PVPer", "Capital Hotdropper", "Baiter", "Moderate", "Weak",
    "Alt", "Logistics Pilot", "Explorer", "Bounty Hunter"];

  list.forEach(function (p) {
    var vClass = EI.valueClass(p.tags || []);
    var tClass = EI.threatClass(p.threatLevel);
    var isActive = (p.id === EI.selectedId) ? " active" : "";
    var shownTags = [];
    priorityTags.forEach(function (t) {
      if ((p.tags || []).indexOf(t) > -1 && shownTags.length < 3) shownTags.push(t);
    });
    (p.tags || []).forEach(function (t) {
      if (shownTags.indexOf(t) === -1 && shownTags.length < 3) shownTags.push(t);
    });
    var mobiUrl = "https://echoes.mobi/killboard/view/player/" + encodeURIComponent(p.name) + "/summary";
    var scrapeBadge = p.scrapedAt
      ? '<a class="scraped-badge' + (EI.isStale(p.scrapedAt) ? " stale" : "") +
        '" href="' + mobiUrl + '" target="_blank" rel="noopener noreferrer"' +
        ' title="View ' + EI.escapeHtml(p.name) + ' on echoes.mobi · stats scraped ' + EI.escapeHtml(p.scrapedAt) + '">' +
        'echoes.mobi</a>'
      : "";

    var bountyTotal = EI.totalBountyForPlayer(p.id);
    var bountyBadge = bountyTotal > 0
      ? '<span class="card-bounty-badge" title="Active bounty: ' + EI.formatIsk(bountyTotal) + ' ISK">🦸 ' + EI.formatIsk(bountyTotal) + '</span>'
      : "";

    html +=
      '<div class="player-card ' + vClass + isActive + '" data-id="' + p.id + '">' +
        '<div class="player-card-row">' +
          '<div>' +
            '<div class="player-name">' + EI.highlight(p.name, term) + scrapeBadge + bountyBadge + '</div>' +
            '<div class="player-corp">' + EI.highlight(p.corporation || "", term) +
              (p.alliance ? ' · ' + EI.highlight(p.alliance, term) : "") + '</div>' +
          '</div>' +
          '<span class="threat-badge ' + tClass + '">THR ' + (p.threatLevel || 0) + '/10</span>' +
        '</div>' +
        '<div class="player-tags">' + shownTags.map(EI.miniTag).join("") + '</div>' +
        '<div class="player-stats">' +
          '<span><strong>' + (p.killCount || 0).toLocaleString() + '</strong> kills</span>' +
          '<span><strong>' + (p.efficiency || 0).toFixed(1) + '%</strong> eff</span>' +
          '<span><strong>' + EI.formatIsk(p.iskDestroyed || 0) + '</strong> ISK destroyed</span>' +
        '</div>' +
      '</div>';
  });
  $list.html(html);
};
