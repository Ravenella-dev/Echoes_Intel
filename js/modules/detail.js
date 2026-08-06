/* ============================================================
   detail.js  —  The pilot detail panel (right side)
   ------------------------------------------------------------
   This is the big "dossier" view that appears when you click a
   pilot in the list. It shows the pilot's name, threat meter,
   stat grid, ships, alts, notes, and the bounty section.

   This is the largest module because the detail panel is the most
   complex part of the UI.

   Key functions:
     statBox(label, value, sub, cls)  -> one stat box in the grid
     buildBountySection(p)            -> the bounty box + contributor list + chart
     drawBountyChart(playerId, name)  -> draws the bounty history line chart on canvas
     renderDetail(id)                 -> draws the entire detail panel for a pilot
   ============================================================ */

EI = EI || {};

// Build a single stat box (used in the 6-box grid on the detail panel).
EI.statBox = function (label, value, sub, valueClass) {
  return '<div class="stat-box"><div class="stat-label">' + EI.escapeHtml(label) +
    '</div><div class="stat-value ' + (valueClass || "") + '">' + value + '</div>' +
    (sub ? '<div class="stat-sub">' + EI.escapeHtml(sub) + '</div>' : "") + '</div>';
};

/* ---- Bounty section (shown inside the detail panel) ----
   Shows total bounty, an expandable contributor list with contact
   info, and a line chart of bounty value history. */

EI.buildBountySection = function (p) {
  var myBounties = EI.bountiesForPlayer(p.id);
  var total = myBounties.reduce(function (s, b) { return s + (Number(b.amount) || 0); }, 0);
  var count = myBounties.length;

  if (total <= 0) {
    var noBountyAdmin = EI.isAdmin
      ? '<button class="admin-btn primary bounty-empty-add" data-id="' + p.id +
        '">🦸 Place a bounty</button>'
      : "";
    return '<div class="bounty-section">' +
      '<div class="bounty-box no-bounty">' +
        '<div class="bounty-box-main">' +
          '<span class="bounty-label">Bounty</span>' +
          '<span class="bounty-amount">No active bounty</span>' +
        '</div>' +
        '<div class="bounty-box-side">' + noBountyAdmin + '</div>' +
      '</div></div>';
  }

  // Build the list of contributors (clickable to reveal contact info)
  var contributorsHtml = myBounties.map(function (b) {
    var contactHtml;
    if (b.is_masked) {
      contactHtml =
        '<div class="bounty-contact masked">' +
          '<span class="contact-name">Anonymous Client</span>' +
          '<span class="contact-label">Identity protected</span>' +
          '<span class="contact-row"><span class="ck">Broker:</span> ' + EI.escapeHtml(b.broker_name || "Unknown") + '</span>' +
          '<span class="contact-row"><span class="ck">Discord:</span> ' + EI.escapeHtml(b.broker_discord || "—") + '</span>' +
        '</div>';
    } else {
      contactHtml =
        '<div class="bounty-contact">' +
          '<span class="contact-name">' + EI.escapeHtml(b.issuer_name || "Unknown") + '</span>' +
          (b.issuer_corp ? '<span class="contact-row"><span class="ck">Corp:</span> ' + EI.escapeHtml(b.issuer_corp) + '</span>' : "") +
          '<span class="contact-row"><span class="ck">Discord:</span> ' + EI.escapeHtml(b.issuer_discord || "—") + '</span>' +
        '</div>';
    }

    var maskedBadge = b.is_masked ? '<span class="masked-badge">MASKED</span>' : "";
    var adminBtns = EI.isAdmin
      ? '<div class="bounty-contrib-actions">' +
        '<button class="admin-btn small" data-bounty-edit="' + b.id + '" data-player="' + p.id + '">✎ Edit</button>' +
        '<button class="admin-btn small danger" data-bounty-del="' + b.id + '" data-player="' + p.id + '">×</button>' +
        '</div>'
      : "";

    return '<div class="bounty-contrib" data-bid="' + b.id + '">' +
      '<div class="bounty-contrib-head">' +
        '<div class="bounty-contrib-left">' +
          '<span class="bounty-contrib-amount">' + EI.formatIsk(b.amount) + ' ISK</span>' +
          maskedBadge +
        '</div>' +
        '<span class="bounty-contrib-toggle">contact info ▾</span>' +
      '</div>' +
      '<div class="bounty-contrib-body" style="display:none;">' +
        contactHtml +
        adminBtns +
      '</div>' +
    '</div>';
  }).join("");

  // Chart container (canvas drawn after render)
  var chartHtml = '<div class="bounty-chart-wrap" id="bountyChartWrap_' + p.id + '">' +
    '<div class="bounty-chart-title">Bounty value over time</div>' +
    '<canvas class="bounty-chart" id="bountyChart_' + p.id + '" width="520" height="140"></canvas>' +
  '</div>';

  var addBtn = EI.isAdmin
    ? '<button class="admin-btn primary bounty-add-btn" data-id="' + p.id + '">+ Add bounty</button>'
    : "";

  return '<div class="bounty-section">' +
    '<div class="bounty-box has-bounty" id="bountyBox_' + p.id + '">' +
      '<div class="bounty-box-main">' +
        '<span class="bounty-label">🦸 Total Bounty</span>' +
        '<span class="bounty-amount">' + EI.formatIsk(total) + ' ISK</span>' +
        '<span class="bounty-contrib-count">' + count + ' contributor' + (count === 1 ? "" : "s") + '</span>' +
      '</div>' +
      '<div class="bounty-box-side">' + addBtn + '</div>' +
    '</div>' +
    '<div class="bounty-contrib-list">' + contributorsHtml + '</div>' +
    chartHtml +
  '</div>';
};

/* ---- Bounty history chart (drawn on a <canvas>, no external libs) ---- */
EI.drawBountyChart = function (playerId, playerName) {
  var canvas = document.getElementById("bountyChart_" + playerId);
  if (!canvas) return;
  var ctx = canvas.getContext("2d");
  var W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  var points = (EI.BOUNTY_HISTORY[playerName] || []).slice();
  if (points.length === 0) {
    ctx.fillStyle = "rgba(159,168,217,0.5)";
    ctx.font = "13px Consolas, monospace";
    ctx.textAlign = "center";
    ctx.fillText("No bounty history yet", W / 2, H / 2);
    return;
  }

  // Sort by timestamp ascending
  points.sort(function (a, b) { return a.ts < b.ts ? -1 : 1; });
  // Always start the chart at zero so the rise is visible
  var pts = [{ ts: points[0].ts, total: 0 }].concat(points);

  var maxVal = Math.max.apply(null, pts.map(function (p) { return p.total; }));
  if (maxVal <= 0) maxVal = 1;

  var padL = 70, padR = 20, padT = 16, padB = 28;
  var plotW = W - padL - padR;
  var plotH = H - padT - padB;

  // Grid + axis labels
  ctx.strokeStyle = "rgba(159,168,217,0.12)";
  ctx.lineWidth = 1;
  ctx.fillStyle = "rgba(159,168,217,0.45)";
  ctx.font = "10px Consolas, monospace";
  ctx.textAlign = "right";
  for (var g = 0; g <= 4; g++) {
    var y = padT + (plotH / 4) * g;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(W - padR, y);
    ctx.stroke();
    var val = maxVal * (1 - g / 4);
    ctx.fillText(EI.formatIsk(val), padL - 6, y + 3);
  }

  // X-axis: time labels (first & last)
  ctx.textAlign = "center";
  if (pts.length >= 1) {
    ctx.fillText((pts[0].ts || "").slice(0, 10), padL + 10, H - 8);
    ctx.fillText((pts[pts.length - 1].ts || "").slice(0, 10), W - padR - 10, H - 8);
  }

  // Line
  var goldFill = ctx.createLinearGradient(0, padT, 0, padT + plotH);
  goldFill.addColorStop(0, "rgba(241,196,15,0.25)");
  goldFill.addColorStop(1, "rgba(241,196,15,0.02)");

  if (pts.length === 1) {
    // single point — draw a dot
    var px = padL + plotW / 2;
    var py = padT + plotH * (1 - pts[0].total / maxVal);
    ctx.fillStyle = "#f1c40f";
    ctx.beginPath();
    ctx.arc(px, py, 4, 0, Math.PI * 2);
    ctx.fill();
  } else {
    // area fill
    ctx.beginPath();
    ctx.moveTo(padL, padT + plotH);
    pts.forEach(function (pt, i) {
      var x = padL + (plotW / (pts.length - 1)) * i;
      var y = padT + plotH * (1 - pt.total / maxVal);
      ctx.lineTo(x, y);
    });
    ctx.lineTo(padL + plotW, padT + plotH);
    ctx.closePath();
    ctx.fillStyle = goldFill;
    ctx.fill();

    // line stroke
    ctx.beginPath();
    pts.forEach(function (pt, i) {
      var x = padL + (plotW / (pts.length - 1)) * i;
      var y = padT + plotH * (1 - pt.total / maxVal);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "#f1c40f";
    ctx.lineWidth = 2;
    ctx.stroke();

    // points
    pts.forEach(function (pt, i) {
      var x = padL + (plotW / (pts.length - 1)) * i;
      var y = padT + plotH * (1 - pt.total / maxVal);
      ctx.fillStyle = "#f1c40f";
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fill();
    });
  }
};

/* ---- Render the full detail panel for one pilot ---- */
EI.renderDetail = function (id) {
  var p = EI.findPlayer(id);
  if (!p) {
    $("#detailEmpty").show();
    $("#detailContent").hide();
    return;
  }
  var tClass = EI.threatClass(p.threatLevel);
  var statusClass = (p.status || "").toLowerCase().indexOf("inactive") > -1 ? "inactive" : "active";
  var tagsHtml = (p.tags || []).map(EI.fullTag).join("");
  var mobiUrl = "https://echoes.mobi/killboard/view/player/" + encodeURIComponent(p.name) + "/summary";
  var scrapeBadge = p.scrapedAt
    ? '<a class="scraped-badge' + (EI.isStale(p.scrapedAt) ? " stale" : "") +
      '" href="' + mobiUrl + '" target="_blank" rel="noopener noreferrer"' +
      ' title="View ' + EI.escapeHtml(p.name) + ' on echoes.mobi · stats scraped ' + EI.escapeHtml(p.scrapedAt) +
      '"> ↻ echoes.mobi · ' + EI.escapeHtml((p.scrapedAt || "").slice(0, 10)) + '</a>'
    : "";

  var statsHtml =
    EI.statBox("Kills", (p.killCount || 0).toLocaleString(), "confirmed killmails", "accent") +
    EI.statBox("Losses", (p.lossCount || 0).toLocaleString(), "ships lost",
      (p.lossCount > p.killCount ? "red" : "")) +
    EI.statBox("Efficiency", (p.efficiency || 0).toFixed(1) + "%", "ISK efficiency",
      ((p.efficiency || 0) >= 75 ? "green" : ((p.efficiency || 0) < 40 ? "red" : ""))) +
    EI.statBox("ISK Destroyed", EI.formatIsk(p.iskDestroyed || 0), "total value killed", "gold") +
    EI.statBox("ISK Lost", EI.formatIsk(p.iskLost || 0), "total value lost", "") +
    EI.statBox("Threat Level", (p.threatLevel || 0) + " / 10", EI.threatLabel(p.threatLevel),
      (p.threatLevel >= 7 ? "red" : (p.threatLevel >= 4 ? "gold" : "green")));

  var shipsHtml = "";
  (p.typicalShips || []).forEach(function (s) {
    var fitHtml = (s.fitting || []).map(function (f) {
      return '<span class="fit-item">' + EI.escapeHtml(f) + '</span>';
    }).join("");
    shipsHtml +=
      '<div class="ship-card"><div class="ship-card-head">' +
      '<span class="ship-name">🚀 ' + EI.escapeHtml(s.ship) + '</span>' +
      '<span class="ship-role">' + EI.escapeHtml(s.role || "") + '</span></div>' +
      '<div class="fitting-list">' + fitHtml + '</div></div>';
  });
  if (!shipsHtml) shipsHtml = '<p style="color:var(--text-faint);font-size:13px;">No ship data on file.</p>';

  var altsHtml;
  if (p.knownAlts && p.knownAlts.length) {
    altsHtml = '<div class="alts-box">' + p.knownAlts.map(function (a) {
      return '<span class="alt-chip"><span class="alt-label">ALT</span>' + EI.escapeHtml(a) + '</span>';
    }).join("") + '</div>';
  } else {
    altsHtml = '<p style="color:var(--text-faint);font-size:13px;">No known alts on file.</p>';
  }

  var bountyHtml = EI.buildBountySection(p);

  // admin-only action row (editor+)
  var canEdit = EI.hasAccess("editor");
  var adminActions = canEdit
    ? '<div class="detail-admin-actions">' +
      '<button class="admin-btn" id="detailEditBtn" data-id="' + p.id + '">✎ Edit Pilot</button>' +
      '<button class="admin-btn" id="detailBountyBtn" data-id="' + p.id + '">🦸 Add Bounty</button>' +
      '<button class="admin-btn" id="detailScrapeBtn" data-id="' + p.id + '">↻ Fetch from echoes.mobi</button>' +
      '<button class="admin-btn danger" id="detailDeleteBtn" data-id="' + p.id + '">🗑 Remove</button>' +
      '</div>'
    : "";

  var html =
    '<div class="detail-header">' +
      '<div class="detail-top">' +
        '<div class="detail-name">' + EI.escapeHtml(p.name) + scrapeBadge + '</div>' +
        '<span class="detail-status ' + statusClass + '">' + EI.escapeHtml(p.status || "Active") + '</span>' +
      '</div>' +
      '<div class="detail-affil">' + EI.escapeHtml(p.corporation || "—") +
        (p.alliance ? ' <span class="sep">›</span> ' + EI.escapeHtml(p.alliance) :
          ' <span class="sep">›</span> <em>no alliance</em>') + '</div>' +
      '<div class="detail-meta">' +
        (p.faction ? 'Faction: ' + EI.escapeHtml(p.faction) + ' · ' : "") +
        'Region: ' + EI.escapeHtml(p.region || "Unknown") +
        ' · Last seen: ' + EI.escapeHtml(p.lastSeen || "Unknown") + '</div>' +
      '<div class="threat-meter"><span>Threat</span>' +
        '<div class="threat-bar"><div class="threat-fill" style="width:' +
        ((p.threatLevel || 0) * 10) + '%;background:' + EI.threatFillColor(p.threatLevel) +
        ';box-shadow:0 0 8px ' + EI.threatFillColor(p.threatLevel) + ';"></div></div>' +
        '<span class="threat-num" style="color:' + EI.threatFillColor(p.threatLevel) + '">' +
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
    '<div class="notes-box">' + EI.escapeHtml(p.notes || "No notes on file.") + '</div>' +
    adminActions;

  $("#detailEmpty").hide();
  $("#detailContent").html(html).show();

  // Draw the bounty history chart if present
  if (EI.bountiesForPlayer(p.id).length > 0) {
    setTimeout(function () { EI.drawBountyChart(p.id, p.name); }, 30);
  }
};
