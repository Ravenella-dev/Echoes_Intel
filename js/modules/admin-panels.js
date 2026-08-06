/* ============================================================
   admin-panels.js  —  Changelog viewer + User management
   ------------------------------------------------------------
   These are the two admin pop-ups:

   1. CHANGELOG VIEWER (admin+)
      Shows a table of every change made to pilots/bounties, who
      made it, and when. Each row has a "Revert" button that undoes
      the change. Changes made by the master account are not logged.

   2. USER MANAGEMENT (master only)
      Shows a table of all users with their access levels. The master
      can add users, change access levels, set passwords, and delete
      users.

   Key functions:
     openChangelogModal()   -> show the changelog pop-up
     loadChangelog()        -> GET /api/changelog and render the table
     renderChangelog(entries) -> build the changelog table HTML
     openUsersModal()       -> show the user management pop-up
     loadUsers()            -> GET /api/users and render the table
     renderUsers(users, levels) -> build the users table HTML
   ============================================================ */

EI = EI || {};

/* ---- CHANGELOG VIEWER (admin+) ---- */

EI.openChangelogModal = function () {
  if (!EI.hasAccess("admin")) return;
  EI.openModal("changelogModal");
  EI.loadChangelog();
};

EI.loadChangelog = function () {
  var $body = $("#changelogBody");
  $body.html('<p style="color:var(--text-faint)">Loading changelog…</p>');
  $.ajax({
    type: "GET",
    url: "/api/changelog?limit=200",
    headers: EI.authHeader({})
  })
    .done(function (resp) {
      if (!resp || !resp.ok) {
        $body.html('<p style="color:var(--danger)">Failed to load changelog.</p>');
        return;
      }
      EI.renderChangelog(resp.entries || []);
    })
    .fail(function (xhr) {
      var msg = "Failed to load changelog.";
      try { var j = JSON.parse(xhr.responseText); if (j && j.error) msg = j.error; } catch (e) {}
      $body.html('<p style="color:var(--danger)">' + EI.escapeHtml(msg) + '</p>');
    });
};

EI.renderChangelog = function (entries) {
  var $body = $("#changelogBody");
  if (!entries.length) {
    $body.html('<p style="color:var(--text-faint)">No changes have been logged yet. Changes made by the master account are not recorded.</p>');
    return;
  }
  var rows = entries.map(function (e) {
    var actionLabel = {
      add: '<span style="color:var(--safe)">added</span>',
      edit: '<span style="color:var(--warn)">edited</span>',
      remove: '<span style="color:var(--danger)">removed</span>'
    }[e.action] || EI.escapeHtml(e.action);
    var who = e.changed_by ? EI.escapeHtml(e.changed_by) : "<em>unknown</em>";
    var when = EI.escapeHtml((e.changed_at || "").replace("T", " ").slice(0, 19));
    var entType = EI.escapeHtml(e.entity_type);
    var entId = EI.escapeHtml(String(e.entity_id));
    var revertedTag = e.reverted
      ? ' <span style="color:var(--text-faint)">(reverted)</span>'
      : '';
    var revertBtn = (!e.reverted)
      ? '<button class="admin-btn small" data-revert="' + e.id + '">↺ Revert</button>'
      : "";
    var summary = "";
    if (e.action === "edit" && e.snapshot_after) {
      var nameA = e.snapshot_after.name || e.snapshot_after.target_name || entId;
      summary = EI.escapeHtml(String(nameA));
    } else if (e.snapshot_after) {
      var nameB = e.snapshot_after.name || e.snapshot_after.target_name || entId;
      summary = EI.escapeHtml(String(nameB));
    } else if (e.snapshot_before) {
      var nameC = e.snapshot_before.name || e.snapshot_before.target_name || entId;
      summary = EI.escapeHtml(String(nameC));
    }
    return '<tr>' +
      '<td style="white-space:nowrap">' + when + '</td>' +
      '<td>' + entType + '</td>' +
      '<td>' + summary + '</td>' +
      '<td>' + actionLabel + revertedTag + '</td>' +
      '<td>' + who + '</td>' +
      '<td>' + revertBtn + '</td>' +
      '</tr>';
  }).join("");
  $body.html(
    '<table class="changelog-table" style="width:100%;border-collapse:collapse;font-size:13px;">' +
    '<thead><tr style="text-align:left;color:var(--text-faint);border-bottom:1px solid var(--border);">' +
    '<th>When</th><th>Type</th><th>Entity</th><th>Action</th><th>By</th><th></th>' +
    '</tr></thead><tbody>' + rows + '</tbody></table>'
  );
};

/* ---- USER MANAGEMENT (master only) ---- */

EI.openUsersModal = function () {
  if (!EI.hasAccess("master")) return;
  EI.openModal("usersModal");
  EI.loadUsers();
};

EI.loadUsers = function () {
  var $body = $("#usersBody");
  $body.html('<p style="color:var(--text-faint)">Loading users…</p>');
  $.ajax({ type: "GET", url: "/api/users", headers: EI.authHeader({}) })
    .done(function (resp) {
      if (!resp || !resp.ok) {
        $body.html('<p style="color:var(--danger)">Failed to load users.</p>');
        return;
      }
      EI.renderUsers(resp.users || [], resp.access_levels || EI.ACCESS_LEVELS);
    })
    .fail(function (xhr) {
      var msg = "Failed to load users.";
      try { var j = JSON.parse(xhr.responseText); if (j && j.error) msg = j.error; } catch (e) {}
      $body.html('<p style="color:var(--danger)">' + EI.escapeHtml(msg) + '</p>');
    });
};

EI.renderUsers = function (users, levels) {
  var $body = $("#usersBody");
  var rows = users.map(function (u) {
    var isSelf = (u.username === EI.currentUser.username);
    var isMaster = (u.access_level === "master");
    var delBtn = (!isMaster && !isSelf)
      ? '<button class="admin-btn small danger" data-del-user="' + u.id + '">×</button>'
      : '<span style="color:var(--text-faint)">—</span>';
    var pwBtn = '<button class="admin-btn small" data-pw-user="' + u.id + '">Set password</button>';
    var lvlSelect = '<select data-lvl-user="' + u.id + '"' +
      (isMaster ? ' disabled' : '') + '>' +
      levels.map(function (l) {
        return '<option value="' + l + '"' + (l === u.access_level ? ' selected' : '') + '>' + l + '</option>';
      }).join("") + '</select>';
    return '<tr>' +
      '<td>' + EI.escapeHtml(u.username) + (isSelf ? ' <em>(you)</em>' : '') + '</td>' +
      '<td>' + lvlSelect + '</td>' +
      '<td>' + pwBtn + '</td>' +
      '<td>' + delBtn + '</td>' +
      '</tr>';
  }).join("");
  $body.html(
    '<div style="margin-bottom:12px;">' +
    '<button class="admin-btn primary" id="addUserBtn">+ Add user</button>' +
    '</div>' +
    '<table class="users-table" style="width:100%;border-collapse:collapse;font-size:13px;">' +
    '<thead><tr style="text-align:left;color:var(--text-faint);border-bottom:1px solid var(--border);">' +
    '<th>Username</th><th>Access level</th><th>Password</th><th></th>' +
    '</tr></thead><tbody>' + rows + '</tbody></table>'
  );
};
