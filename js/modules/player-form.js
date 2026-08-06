/* ============================================================
   player-form.js  —  Add / edit pilot form + echoes.mobi scrape
   ------------------------------------------------------------
   Handles the "Add Pilot" / "Edit Pilot" modal: building the form
   fields, the tag picker, the ship editor, the echoes.mobi fetch
   button, and collecting/saving the form data.

   Key functions:
     openPlayerForm(id)      -> open the form (id=null for new, id=... for edit)
     blankPlayer()           -> returns a fresh empty pilot object
     todayStr()              -> today's date as "YYYY-MM-DD"
     buildFormHtml(p, edit)  -> builds all the form fields as HTML
     renderTagPicker(tags)   -> draws the clickable tag chips in the form
     getSelectedTags()       -> reads which tags are currently selected
     renderShipEditor(ships) -> draws the ship rows in the form
     shipRowHtml(...)        -> HTML for one ship row
     collectShips()          -> reads all ship rows back into objects
     doScrape()              -> fetches pilot stats from echoes.mobi
     previewHtml(d)          -> shows a preview of scraped data
     applyScrapeToForm()     -> fills form fields from scraped data
     collectForm()           -> reads all form fields into a pilot object
     savePlayerFromForm()    -> saves the pilot (add or update) + closes form
     askDelete(id)           -> shows the "are you sure?" delete dialog
     confirmDelete()         -> actually deletes the pilot
     scrapeFromDetail(id)    -> opens the form + auto-scrapes (from detail panel)
   ============================================================ */

EI = EI || {};

// Open the player form. Pass null to add a new pilot, or an id to edit.
EI.openPlayerForm = function (id) {
  EI.editingId = id || null;
  EI.lastScrapeData = null;
  var p = id ? EI.findPlayer(id) : EI.blankPlayer();
  $("#playerFormTitle").html(id
    ? '<span class="mt-icon">✎</span> Edit Pilot'
    : '<span class="mt-icon">＋</span> Add Pilot');
  $("#playerFormDelete").toggle(!!id);
  $("#playerFormBody").html(EI.buildFormHtml(p, !!id));
  EI.renderTagPicker(p.tags || []);
  EI.renderShipEditor(p.typicalShips || []);
  EI.openModal("playerFormModal");
};

// Return a fresh, empty pilot object with sensible defaults.
EI.blankPlayer = function () {
  return {
    id: EI.nextId(), name: "", corporation: "", alliance: "", faction: "",
    region: "", tags: [], threatLevel: 5, killCount: 0, lossCount: 0,
    iskDestroyed: 0, iskLost: 0, efficiency: 50, lastSeen: EI.todayStr(),
    status: "Active", typicalShips: [], notes: "", knownAlts: [],
    scrapedAt: null
  };
};

// Today's date as a "YYYY-MM-DD" string (for date inputs).
EI.todayStr = function () {
  return new Date().toISOString().slice(0, 10);
};

// Build all the form fields as HTML. p = pilot object, isEdit = true if editing.
EI.buildFormHtml = function (p, isEdit) {
  var tagNames = Object.keys(EI.TAG_CATS).sort();

  return (
    '<div class="echoes-fetch">' +
      '<div style="font-size:13px;font-weight:600;color:var(--accent);margin-bottom:10px;">↻ Auto-fill from echoes.mobi</div>' +
      '<div class="echoes-fetch-head">' +
        '<div class="form-field">' +
          '<label>Pilot name on echoes.mobi</label>' +
          '<input type="text" id="scrapeName" placeholder="Enter a pilot..." value="' + EI.escapeHtml(isEdit ? p.name : "") + '" />' +
        '</div>' +
        '<button class="admin-btn primary" id="scrapeBtn" style="height:38px;margin-bottom:0;">Fetch stats</button>' +
      '</div>' +
      '<div class="echoes-fetch-status" id="scrapeStatus"></div>' +
      '<div class="echoes-preview" id="scrapePreview"></div>' +
    '</div>' +

    '<div class="form-row">' +
      '<div class="form-field"><label>Pilot name <span class="req">*</span></label>' +
        '<input type="text" id="fName" value="' + EI.escapeHtml(p.name) + '" /></div>' +
      '<div class="form-field"><label>Corporation</label>' +
        '<input type="text" id="fCorp" value="' + EI.escapeHtml(p.corporation || "") + '" /></div>' +
    '</div>' +
    '<div class="form-row">' +
      '<div class="form-field"><label>Alliance</label>' +
        '<input type="text" id="fAlliance" value="' + EI.escapeHtml(p.alliance || "") + '" placeholder="(leave blank if none)" /></div>' +
      '<div class="form-field"><label>Faction</label>' +
        '<input type="text" id="fFaction" value="' + EI.escapeHtml(p.faction || "") + '" /></div>' +
    '</div>' +
    '<div class="form-row">' +
      '<div class="form-field"><label>Region</label>' +
        '<input type="text" id="fRegion" value="' + EI.escapeHtml(p.region || "") + '" /></div>' +
      '<div class="form-field"><label>Status</label>' +
        '<select id="fStatus">' +
          ['<option value="Active">Active</option>',
           '<option value="Inactive">Inactive</option>',
           '<option value="Inactive (reported on break)">Inactive (reported on break)</option>']
          .map(function (o) { return o; }).join("").replace(
            'value="' + EI.escapeHtml(p.status) + '"',
            'value="' + EI.escapeHtml(p.status) + '" selected') +
        '</select></div>' +
    '</div>' +

    '<div class="form-field"><label>Tags</label>' +
      '<div class="tag-picker" id="tagPicker"></div>' +
      '<div class="hint">Click tags to toggle. Selected tags get highlighted.</div>' +
    '</div>' +

    '<div class="form-field"><label>Threat level (0–10)</label>' +
      '<input type="number" id="fThreat" min="0" max="10" step="1" value="' + (p.threatLevel || 0) + '" /></div>' +
    '<div class="hint" style="margin-bottom:12px;">Bounties are managed separately — add or edit them from the pilot\'s profile page.</div>' +

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
        '<input type="date" id="fLastSeen" value="' + EI.escapeHtml(p.lastSeen || EI.todayStr()) + '" /></div>' +
    '</div>' +

    '<div class="form-field"><label>Typical ships &amp; fittings</label>' +
      '<div class="ship-editor" id="shipEditor"></div>' +
      '<button class="add-ship-btn" id="addShipBtn">+ Add ship</button>' +
    '</div>' +

    '<div class="form-field"><label>Known alts (comma separated)</label>' +
      '<input type="text" id="fAlts" value="' + EI.escapeHtml((p.knownAlts || []).join(", ")) + '" /></div>' +

    '<div class="form-field"><label>Field notes</label>' +
      '<textarea id="fNotes" rows="4">' + EI.escapeHtml(p.notes || "") + '</textarea></div>'
  );
};

/* ---- Tag picker (clickable chips that toggle on/off) ---- */
EI.renderTagPicker = function (selected) {
  var $box = $("#tagPicker").empty();
  Object.keys(EI.TAG_CATS).sort().forEach(function (name) {
    var cat = EI.TAG_CATS[name];
    var sel = (selected || []).indexOf(name) > -1 ? " selected" : "";
    var $c = $('<span class="tag-pick' + sel + '" data-tag="' + EI.escapeHtml(name) + '">' +
      '<span>' + (cat.icon || "") + '</span> ' + EI.escapeHtml(name) + '</span>');
    $c.css(sel ? {
      background: EI.hexA(cat.color, 0.2),
      "border-color": EI.hexA(cat.color, 0.5),
      color: cat.color
    } : {});
    $box.append($c);
  });
};

// Read which tags are currently selected in the picker.
EI.getSelectedTags = function () {
  var tags = [];
  $("#tagPicker .tag-pick.selected").each(function () {
    tags.push($(this).data("tag"));
  });
  return tags;
};

/* ---- Ship editor (add/remove rows of ship + role + fittings) ---- */
EI.renderShipEditor = function (ships) {
  var $ed = $("#shipEditor").empty();
  (ships && ships.length ? ships : []).forEach(function (s) {
    $ed.append(EI.shipRowHtml(s.ship || "", s.role || "", (s.fitting || []).join("\n")));
  });
  if (!ships || !ships.length) {
    $ed.append(EI.shipRowHtml("", "", ""));
  }
};

// HTML for one ship row in the editor.
EI.shipRowHtml = function (ship, role, fitting) {
  return (
    '<div class="ship-edit-row">' +
      '<div class="ship-edit-row-head">' +
        '<input class="se-ship" placeholder="Ship name (e.g. Naglfar)" value="' + EI.escapeHtml(ship) + '" />' +
        '<input class="se-role ship-edit-role" placeholder="Role (e.g. Dreadnought brawler)" value="' + EI.escapeHtml(role) + '" />' +
        '<button class="remove-ship-btn" title="Remove ship">×</button>' +
      '</div>' +
      '<textarea class="fit-input" placeholder="Fittings — one per line (e.g. 3x 3500mm Railgun I)" rows="3">' +
        EI.escapeHtml(fitting) + '</textarea>' +
    '</div>'
  );
};

// Read all ship rows from the editor back into an array of objects.
EI.collectShips = function () {
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
};

/* ---- echoes.mobi fetch (auto-fill from killboard) ---- */
EI.doScrape = function () {
  var name = $("#scrapeName").val().trim();
  var $st = $("#scrapeStatus");
  var $pv = $("#scrapePreview");
  if (!name) {
    $st.attr("class", "echoes-fetch-status error").text("Enter a pilot name first.");
    return;
  }
  $st.attr("class", "echoes-fetch-status loading").text("Fetching from echoes.mobi…");
  $pv.removeClass("visible").empty();
  $.getJSON(EI.SCRAPE_URL, { player: name })
    .done(function (resp) {
      if (!resp || !resp.ok) {
        $st.attr("class", "echoes-fetch-status error")
          .text("Error: " + ((resp && resp.error) || "unknown"));
        return;
      }
      var d = resp.data;
      EI.lastScrapeData = d;
      EI.lastScrapeData.fetchedAt = resp.fetchedAt;
      $st.attr("class", "echoes-fetch-status success")
        .text("✓ Fetched " + (d.name || name) + " from echoes.mobi. Click \"Apply stats to form\" to fill in.");
      $pv.html(EI.previewHtml(d) +
        '<div style="margin-top:10px;"><button class="admin-btn primary" id="applyScrapeBtn">Apply stats to form</button></div>'
      ).addClass("visible");
      if (!$("#fName").val().trim() && d.name) $("#fName").val(d.name);
    })
    .fail(function (xhr) {
      var msg = "Failed to reach scrape proxy.";
      try { var j = JSON.parse(xhr.responseText); if (j.error) msg = j.error; } catch (e) {}
      $st.attr("class", "echoes-fetch-status error").text("✗ " + msg);
    });
};

// Build the preview grid showing what was scraped.
EI.previewHtml = function (d) {
  function item(label, val, cls) {
    return '<div class="ep-item"><div class="ep-label">' + label + '</div>' +
      '<div class="ep-value ' + (cls || "") + '">' + val + '</div></div>';
  }
  var ships = (d.topShipsByKills || []).map(function (s) {
    return EI.escapeHtml(s.ship) + " (" + s.count + ")";
  }).join(", ");
  return (
    '<div style="color:var(--text-dim);margin-bottom:4px;">Preview of scraped data:</div>' +
    '<div class="ep-grid">' +
      item("Kills", (d.killedShips || 0).toLocaleString(), "accent") +
      item("Losses", (d.lostShips || 0).toLocaleString(), "red") +
      item("ISK destroyed", EI.formatIsk(d.iskDestroyed || 0), "gold") +
      item("ISK lost", EI.formatIsk(d.iskLost || 0), "") +
      item("ISK efficiency", (d.iskEfficiencyDangerous || 0) + "%",
        ((d.iskEfficiencyDangerous || 0) >= 75 ? "green" : "red")) +
      item("Kill ratio", (100 - d.killRatioDangerous || 0) + "%", "") +
      item("Corporation", EI.escapeHtml(d.corporation || "—"), "") +
      item("Best kill", EI.escapeHtml(d.bestKill || "—") +
        (d.bestKillIsk ? " · " + EI.formatIsk(d.bestKillIsk) : ""), "") +
    '</div>' +
    (ships ? '<div style="margin-top:8px;font-size:11px;color:var(--text-dim);">' +
      'Top ships by kills: ' + ships + '</div>' : "")
  );
};

// Fill the form fields from the scraped data.
EI.applyScrapeToForm = function () {
  if (!EI.lastScrapeData) return;
  var d = EI.lastScrapeData;
  $("#fKills").val(d.killedShips || 0);
  $("#fLosses").val(d.lostShips || 0);
  $("#fIskDest").val(d.iskDestroyed || 0);
  $("#fIskLost").val(d.iskLost || 0);
  $("#fEff").val((d.iskEfficiencyDangerous || d.efficiency || 0).toFixed(1));
  if (d.corporation && !$("#fCorp").val().trim()) $("#fCorp").val(d.corporation);
  if (d.name && !$("#fName").val().trim()) $("#fName").val(d.name);
  // auto-fill top ship as a typical ship if none present
  var existing = EI.collectShips();
  if ((!existing || !existing.length) && d.topShipsByKills && d.topShipsByKills.length) {
    var $ed = $("#shipEditor").empty();
    d.topShipsByKills.slice(0, 3).forEach(function (s) {
      $ed.append(EI.shipRowHtml(s.ship, "Top flown by kills (echoes.mobi)", ""));
    });
  }
  EI.toast("Scraped stats applied to form", "success");
};

/* ---- Collect all form fields into a pilot object ---- */
EI.collectForm = function () {
  var name = $("#fName").val().trim();
  if (!name) { $("#fName").focus(); EI.toast("Pilot name is required", "error"); return null; }
  var altsStr = $("#fAlts").val().trim();
  var alts = altsStr ? altsStr.split(",").map(function (s) { return s.trim(); })
    .filter(function (s) { return s.length; }) : [];
  var p = {
    id: EI.editingId || EI.nextId(),
    name: name,
    corporation: $("#fCorp").val().trim() || null,
    alliance: $("#fAlliance").val().trim() || null,
    faction: $("#fFaction").val().trim() || null,
    region: $("#fRegion").val().trim() || null,
    tags: EI.getSelectedTags(),
    threatLevel: parseInt($("#fThreat").val(), 10) || 0,
    killCount: parseInt($("#fKills").val(), 10) || 0,
    lossCount: parseInt($("#fLosses").val(), 10) || 0,
    iskDestroyed: parseFloat($("#fIskDest").val()) || 0,
    iskLost: parseFloat($("#fIskLost").val()) || 0,
    efficiency: parseFloat($("#fEff").val()) || 0,
    lastSeen: $("#fLastSeen").val() || EI.todayStr(),
    status: $("#fStatus").val() || "Active",
    typicalShips: EI.collectShips(),
    notes: $("#fNotes").val().trim() || "",
    knownAlts: alts
  };
  // preserve scrapedAt if we just re-scraped or editing existing
  if (EI.lastScrapeData && EI.lastScrapeData.fetchedAt) {
    p.scrapedAt = EI.lastScrapeData.fetchedAt;
  } else if (EI.editingId) {
    var existing = EI.findPlayer(EI.editingId);
    if (existing && existing.scrapedAt) p.scrapedAt = existing.scrapedAt;
  }
  return p;
};

// Save the pilot from the form (add new or update existing), then close.
EI.savePlayerFromForm = function () {
  var p = EI.collectForm();
  if (!p) return;
  if (EI.editingId) {
    var idx = EI.PLAYERS.findIndex(function (x) { return x.id === EI.editingId; });
    if (idx > -1) EI.PLAYERS[idx] = p;
    EI.toast("Updated pilot: " + p.name, "success");
  } else {
    EI.PLAYERS.push(p);
    EI.toast("Added pilot: " + p.name, "success");
  }
  EI.savePlayers();
  EI.selectedId = p.id;
  EI.closeModal("playerFormModal");
  EI.renderResults();
  EI.renderDetail(p.id);
};

/* ---- Delete a pilot ---- */
EI.askDelete = function (id) {
  var p = EI.findPlayer(id);
  if (!p) return;
  EI.pendingDeleteId = id;
  $("#confirmMsg").html(
    'Remove <span class="confirm-name">' + EI.escapeHtml(p.name) + '</span> from the intel database? ' +
    '<strong>This cannot be undone.</strong>'
  );
  EI.openModal("confirmModal");
};

EI.confirmDelete = function () {
  // If this is a bounty deletion (confirmBountyId hidden field present), route there
  if ($("#confirmBountyId").length) {
    EI.confirmDeleteBounty();
    return;
  }
  if (!EI.pendingDeleteId) return;
  var p = EI.findPlayer(EI.pendingDeleteId);
  EI.PLAYERS = EI.PLAYERS.filter(function (x) { return x.id !== EI.pendingDeleteId; });
  EI.savePlayers();
  if (EI.selectedId === EI.pendingDeleteId) {
    EI.selectedId = null;
    $("#detailEmpty").show();
    $("#detailContent").hide();
  }
  EI.closeModal("confirmModal");
  EI.closeModal("playerFormModal");
  EI.toast("Removed pilot: " + (p ? p.name : ""), "warn");
  EI.pendingDeleteId = null;
  EI.renderResults();
};

// Open the form and auto-scrape (used by the detail panel's fetch button).
EI.scrapeFromDetail = function (id) {
  var p = EI.findPlayer(id);
  if (!p) return;
  EI.openPlayerForm(id);
  $("#scrapeName").val(p.name);
  setTimeout(EI.doScrape, 150);
};
