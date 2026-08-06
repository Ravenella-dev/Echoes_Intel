/* ============================================================
   data.js  —  Server communication (bounties + player data)
   ------------------------------------------------------------
   This file handles all the AJAX calls to the server: saving
   players, fetching bounties, and the bounty CRUD operations.

   It also has the localStorage fallback for when the server
   isn't running (e.g. opening index.html directly).

   Key functions:
     bountiesForPlayer(id)      -> all bounties targeting a pilot
     totalBountyForPlayer(id)   -> sum of all bounty amounts on a pilot
     saveBounty(bounty, id)     -> POST (new) or PUT (edit) a bounty
     deleteBountyRemote(id)     -> DELETE a bounty from the server
     refreshBounties(callback)  -> reload bounties + history from server
     loadStoredPlayers()        -> read offline-cached players from localStorage
     savePlayers()              -> POST all players to server (+ localStorage mirror)
     resetStoredPlayers()       -> clear the localStorage cache
     loadData()                 -> GET /api/players and populate everything
   ============================================================ */

EI = EI || {};

// Return all bounties whose target_player_id matches the given player id.
EI.bountiesForPlayer = function (playerId) {
  return EI.BOUNTIES.filter(function (b) { return b.target_player_id === playerId; });
};

// Sum the total bounty amount for a player.
EI.totalBountyForPlayer = function (playerId) {
  return EI.bountiesForPlayer(playerId).reduce(function (sum, b) {
    return sum + (Number(b.amount) || 0);
  }, 0);
};

// Persist a bounty to the server via POST (new) or PUT (existing).
EI.saveBounty = function (bounty, bountyId) {
  var method = bountyId ? "PUT" : "POST";
  var url = bountyId ? EI.BOUNTY_URL + "/" + bountyId : EI.BOUNTY_URL;
  return $.ajax({
    type: method,
    url: url,
    contentType: "application/json",
    headers: EI.authHeader({}),
    data: JSON.stringify({ bounty: bounty })
  });
};

// Delete a bounty from the server via DELETE.
EI.deleteBountyRemote = function (bountyId) {
  return $.ajax({
    type: "DELETE",
    url: EI.BOUNTY_URL + "/" + bountyId,
    headers: EI.authHeader({})
  });
};

// Refresh bounties + history from the server and re-render detail.
EI.refreshBounties = function (then) {
  $.getJSON(EI.BOUNTY_URL)
    .done(function (resp) {
      if (resp && resp.ok) {
        EI.BOUNTIES = resp.bounties || [];
        EI.BOUNTY_HISTORY = resp.bountyHistory || {};
        if (EI.selectedId) EI.renderDetail(EI.selectedId);
        if (then) then();
      }
    })
    .fail(function () {
      if (then) then();
    });
};

/* ---- Player persistence ---- */

// Read the offline-cached players from localStorage (fallback only).
EI.loadStoredPlayers = function () {
  try {
    var raw = localStorage.getItem(EI.STORAGE_KEY);
    if (!raw) return null;
    var obj = JSON.parse(raw);
    if (obj && Array.isArray(obj.players)) return obj.players;
  } catch (e) { /* ignore */ }
  return null;
};

// Save all players: mirror to localStorage, then POST to the server.
EI.savePlayers = function () {
  // 1) always mirror to localStorage as an offline cache
  try {
    localStorage.setItem(EI.STORAGE_KEY, JSON.stringify({
      players: EI.PLAYERS,
      savedAt: new Date().toISOString()
    }));
  } catch (e) { /* ignore quota errors */ }

  // 2) POST the full players array to the server
  $.ajax({
    type: "POST",
    url: EI.SAVE_URL,
    contentType: "application/json",
    headers: EI.authHeader({}),
    data: JSON.stringify({ players: EI.PLAYERS })
  })
    .done(function (resp) {
      if (resp && resp.ok) {
        EI.toast("Saved to server (" + resp.count + " pilots)", "success");
      }
    })
    .fail(function (xhr) {
      var msg = "Could not save to server (running statically?)";
      try { var j = JSON.parse(xhr.responseText); if (j.error) msg = j.error; } catch (e) {}
      EI.toast(msg + " — kept locally.", "warn");
    });
  return true;
};

// Clear the localStorage player cache.
EI.resetStoredPlayers = function () {
  try { localStorage.removeItem(EI.STORAGE_KEY); } catch (e) {}
};

// GET /api/players from the server and populate all state + re-render.
EI.loadData = function () {
  $.getJSON(EI.DATA_URL)
    .done(function (data) {
      EI.DATA = data;
      EI.TAG_CATS = data.tagCategories || {};
      EI.BOUNTIES = data.bounties || [];
      EI.BOUNTY_HISTORY = data.bountyHistory || {};
      var serverPlayers = data.players || [];
      var stored = EI.loadStoredPlayers();
      if (serverPlayers.length > 0) {
        EI.PLAYERS = serverPlayers.slice();
      } else if (stored) {
        EI.PLAYERS = stored;
      } else {
        EI.PLAYERS = serverPlayers.slice();
      }
      EI.renderResults();
      if (EI.selectedId) EI.renderDetail(EI.selectedId);
    })
    .fail(function () {
      $("#resultsCount").html(
        '<span style="color:var(--danger)"><i class="fas fa-triangle-exclamation"></i> Failed to load pilot database.</span><br>' +
        '<span style="font-size:11px;color:var(--text-faint)">' +
        "Serve the project via server.py (python3 server.py) so the JSON loads.</span>"
      );
    });
};
