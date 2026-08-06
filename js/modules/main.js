/* ============================================================
   main.js  —  Event wiring + app startup
   ------------------------------------------------------------
   This is the "glue" file. It connects all the buttons, clicks,
   and keyboard events to the functions defined in the other
   module files, then starts the app.

   Order matters: this file MUST load after all the other module
   files, because it references their functions (EI.renderResults,
   EI.openPlayerForm, etc.).

   What happens on startup (the init() function at the bottom):
     1. Build the filter chips under the search bar
     2. Check if you're already logged in (session restore)
     3. Load the pilot data from the server
     4. Focus the search box
   ============================================================ */

EI = EI || {};

$(function () {
  "use strict";

  /* ---- Build the filter chip bar ---- */
  function buildFilterChips() {
    var $bar = $("#filterBar");
    EI.QUICK_FILTERS.forEach(function (tag) {
      $bar.append('<button class="filter-chip" data-tag="' + EI.escapeHtml(tag) + '">' +
        EI.escapeHtml(tag) + '</button>');
    });
  }

  /* ---- Search box ---- */
  var searchTimer = null;
  $("#searchInput").on("input", function () {
    var val = $(this).val();
    EI.currentTerm = val;
    $("#searchClear").toggleClass("visible", val.length > 0);
    clearTimeout(searchTimer);
    searchTimer = setTimeout(EI.renderResults, 120);
  });

  $("#searchClear").on("click", function () {
    $("#searchInput").val("").focus();
    EI.currentTerm = "";
    $(this).removeClass("visible");
    EI.renderResults();
  });

  /* ---- Filter chips (toggle on/off) ---- */
  $(document).on("click", ".filter-chip", function () {
    var tag = $(this).data("tag");
    var idx = EI.activeFilters.indexOf(tag);
    if (idx > -1) { EI.activeFilters.splice(idx, 1); $(this).removeClass("active"); }
    else { EI.activeFilters.push(tag); $(this).addClass("active"); }
    EI.renderResults();
  });

  /* ---- Clicking a pilot card in the list ---- */
  $(document).on("click", ".player-card", function () {
    EI.selectedId = $(this).data("id");
    $(".player-card").removeClass("active");
    $(this).addClass("active");
    EI.renderDetail(EI.selectedId);
    if (window.matchMedia("(max-width: 900px)").matches) {
      $("#detailPanel").get(0).scrollIntoView({ behavior: "smooth" });
    }
  });

  /* ---- Escape key: close modals, or clear search/filters ---- */
  $(document).on("keydown", function (e) {
    if (e.key === "Escape") {
      if ($(".modal-overlay.visible").length) {
        $(".modal-overlay.visible").removeClass("visible");
        return;
      }
      if (EI.currentTerm || EI.activeFilters.length) {
        $("#searchInput").val("");
        EI.currentTerm = "";
        EI.activeFilters = [];
        $(".filter-chip").removeClass("active");
        $("#searchClear").removeClass("visible");
        EI.renderResults();
      }
    }
  });

  /* ---- Admin toolbar buttons ---- */
  $("#loginBtn").on("click", EI.openLogin);
  $("#logoutBtn").on("click", EI.doLogout);
  $("#addPlayerBtn").on("click", function () {
    if (!EI.hasAccess("editor")) return;
    EI.openPlayerForm(null);
  });
  $("#changelogBtn").on("click", EI.openChangelogModal);
  $("#usersBtn").on("click", EI.openUsersModal);
  $("#changelogRefreshBtn").on("click", EI.loadChangelog);
  $("#loginSubmit").on("click", EI.doLogin);
  $("#loginPass,#loginUser").on("keydown", function (e) {
    if (e.key === "Enter") EI.doLogin();
  });

  /* ---- Generic modal close (X button + click-outside) ---- */
  $(document).on("click", "[data-close-modal]", function () {
    EI.closeModal($(this).data("close-modal"));
  });
  $(document).on("click", ".modal-overlay", function (e) {
    if (e.target === this) $(this).removeClass("visible");
  });

  /* ---- Player form: tag picker toggle ---- */
  $(document).on("click", ".tag-pick", function () {
    var $t = $(this);
    var name = $t.data("tag");
    var cat = EI.TAG_CATS[name] || { color: "#7f8c8d" };
    if ($t.hasClass("selected")) {
      $t.removeClass("selected").css({ background: "", "border-color": "", color: "" });
    } else {
      $t.addClass("selected").css({
        background: EI.hexA(cat.color, 0.2),
        "border-color": EI.hexA(cat.color, 0.5),
        color: cat.color
      });
    }
  });

  /* ---- Player form: ship editor add/remove ---- */
  $(document).on("click", "#addShipBtn", function () {
    $("#shipEditor").append(EI.shipRowHtml("", "", ""));
  });
  $(document).on("click", ".remove-ship-btn", function () {
    if ($("#shipEditor .ship-edit-row").length > 1) {
      $(this).closest(".ship-edit-row").remove();
    } else {
      $(this).closest(".ship-edit-row").find("input,textarea").val("");
    }
  });

  /* ---- Player form: scrape + apply ---- */
  $(document).on("click", "#scrapeBtn", EI.doScrape);
  $(document).on("click", "#applyScrapeBtn", EI.applyScrapeToForm);

  /* ---- Player form: save + delete ---- */
  $("#playerFormSave").on("click", EI.savePlayerFromForm);
  $("#playerFormDelete").on("click", function () {
    if (EI.editingId) { EI.closeModal("playerFormModal"); EI.askDelete(EI.editingId); }
  });
  $("#confirmDeleteBtn").on("click", EI.confirmDelete);

  /* ---- Detail panel admin buttons (delegated — detail re-renders) ---- */
  $(document).on("click", "#detailEditBtn", function () {
    EI.openPlayerForm($(this).data("id"));
  });
  $(document).on("click", "#detailScrapeBtn", function () {
    EI.scrapeFromDetail($(this).data("id"));
  });
  $(document).on("click", "#detailDeleteBtn", function () {
    EI.askDelete($(this).data("id"));
  });

  /* ---- Bounty: detail panel "Add Bounty" button ---- */
  $(document).on("click", "#detailBountyBtn", function () {
    EI.openBountyForm($(this).data("id"), null);
  });

  /* ---- Bounty: bounty-box add / empty "place a bounty" buttons ---- */
  $(document).on("click", ".bounty-add-btn, .bounty-empty-add", function () {
    EI.openBountyForm($(this).data("id"), null);
  });

  /* ---- Bounty: expand/collapse contributor contact info ---- */
  $(document).on("click", ".bounty-contrib-head", function () {
    var $body = $(this).siblings(".bounty-contrib-body");
    var $toggle = $(this).find(".bounty-contrib-toggle");
    if ($body.is(":visible")) {
      $body.slideUp(150);
      $toggle.html("contact info ▾");
    } else {
      $body.slideDown(150);
      $toggle.html("contact info ▴");
    }
  });

  /* ---- Bounty: edit / delete from contributor list ---- */
  $(document).on("click", "[data-bounty-edit]", function (e) {
    e.stopPropagation();
    EI.openBountyForm($(this).data("player"), $(this).data("bounty-edit"));
  });
  $(document).on("click", "[data-bounty-del]", function (e) {
    e.stopPropagation();
    EI.askDeleteBounty($(this).data("bounty-del"), $(this).data("player"));
  });

  /* ---- Bounty form: masked toggle + save + delete ---- */
  $(document).on("change", "#bfMasked", EI.updateBrokerVisibility);
  $("#bountyFormSave").on("click", EI.saveBountyFromForm);
  $("#bountyFormDelete").on("click", function () {
    if (EI.editingBountyId && EI.bountyFormTargetId) {
      EI.closeModal("bountyFormModal");
      EI.askDeleteBounty(EI.editingBountyId, EI.bountyFormTargetId);
    }
  });

  /* ---- Changelog: revert button (delegated) ---- */
  $(document).on("click", "[data-revert]", function () {
    var id = $(this).attr("data-revert");
    var $btn = $(this);
    if (!confirm("Revert this change? This will restore or remove the affected entity.")) return;
    $btn.prop("disabled", true).text("Reverting…");
    $.ajax({
      type: "POST",
      url: "/api/changelog/" + id + "/revert",
      headers: EI.authHeader({})
    })
      .done(function (resp) {
        if (resp && resp.ok) {
          EI.toast("Change reverted", "success");
          EI.loadChangelog();
          EI.loadData(); // refresh so the UI reflects the reversion
        } else {
          EI.toast((resp && resp.error) || "Revert failed", "error");
          $btn.prop("disabled", false).text("↺ Revert");
        }
      })
      .fail(function (xhr) {
        var msg = "Revert failed.";
        try { var j = JSON.parse(xhr.responseText); if (j && j.error) msg = j.error; } catch (e) {}
        EI.toast(msg, "error");
        $btn.prop("disabled", false).text("↺ Revert");
      });
  });

  /* ---- User management: add user (delegated) ---- */
  $(document).on("click", "#addUserBtn", function () {
    var username = prompt("New username:");
    if (!username) return;
    var password = prompt("Password for " + username + ":");
    if (!password) return;
    var level = prompt("Access level (viewer / editor / admin / master):", "editor");
    if (!level) return;
    $.ajax({
      type: "POST", url: "/api/users",
      contentType: "application/json",
      headers: EI.authHeader({}),
      data: JSON.stringify({ username: username, password: password, access_level: level })
    })
      .done(function (resp) {
        if (resp && resp.ok) { EI.toast("User created", "success"); EI.loadUsers(); }
        else { EI.toast((resp && resp.error) || "Could not create user", "error"); }
      })
      .fail(function (xhr) {
        var msg = "Could not create user.";
        try { var j = JSON.parse(xhr.responseText); if (j && j.error) msg = j.error; } catch (e) {}
        EI.toast(msg, "error");
      });
  });

  /* ---- User management: change access level (delegated) ---- */
  $(document).on("change", "[data-lvl-user]", function () {
    var id = $(this).attr("data-lvl-user");
    var level = $(this).val();
    $.ajax({
      type: "PUT", url: "/api/users/" + id,
      contentType: "application/json",
      headers: EI.authHeader({}),
      data: JSON.stringify({ access_level: level })
    })
      .done(function (resp) {
        if (resp && resp.ok) { EI.toast("Access level updated", "success"); EI.loadUsers(); }
        else { EI.toast((resp && resp.error) || "Update failed", "error"); EI.loadUsers(); }
      })
      .fail(function (xhr) {
        var msg = "Update failed.";
        try { var j = JSON.parse(xhr.responseText); if (j && j.error) msg = j.error; } catch (e) {}
        EI.toast(msg, "error"); EI.loadUsers();
      });
  });

  /* ---- User management: set password (delegated) ---- */
  $(document).on("click", "[data-pw-user]", function () {
    var id = $(this).attr("data-pw-user");
    var pw = prompt("New password:");
    if (!pw) return;
    $.ajax({
      type: "PUT", url: "/api/users/" + id,
      contentType: "application/json",
      headers: EI.authHeader({}),
      data: JSON.stringify({ password: pw })
    })
      .done(function (resp) {
        if (resp && resp.ok) EI.toast("Password updated", "success");
        else EI.toast((resp && resp.error) || "Update failed", "error");
      })
      .fail(function (xhr) {
        var msg = "Update failed.";
        try { var j = JSON.parse(xhr.responseText); if (j && j.error) msg = j.error; } catch (e) {}
        EI.toast(msg, "error");
      });
  });

  /* ---- User management: delete user (delegated) ---- */
  $(document).on("click", "[data-del-user]", function () {
    var id = $(this).attr("data-del-user");
    if (!confirm("Delete this user?")) return;
    $.ajax({
      type: "DELETE", url: "/api/users/" + id,
      headers: EI.authHeader({})
    })
      .done(function (resp) {
        if (resp && resp.ok) { EI.toast("User deleted", "success"); EI.loadUsers(); }
        else EI.toast((resp && resp.error) || "Delete failed", "error");
      })
      .fail(function (xhr) {
        var msg = "Delete failed.";
        try { var j = JSON.parse(xhr.responseText); if (j && j.error) msg = j.error; } catch (e) {}
        EI.toast(msg, "error");
      });
  });

  /* ---- INIT: start the app ---- */
  function init() {
    buildFilterChips();
    EI.checkSession();
    EI.loadData();
    $("#searchInput").focus();
  }

  init();
});
