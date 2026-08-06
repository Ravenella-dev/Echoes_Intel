/* ============================================================
   auth.js  —  Login, logout, and session management
   ------------------------------------------------------------
   Handles the authentication flow: checking if you're already
   logged in (session token in sessionStorage), showing the login
   form, sending credentials to the server, and logging out.

   The server does the real work (bcrypt password checking, session
   tokens). This file just manages the UI side and stores the token.

   Key functions:
     checkSession()    -> on page load, restore + validate any saved token
     clearSession()    -> wipe the token + cached user from memory + storage
     setAdmin(on)      -> flip the UI between "guest" and "logged in" mode
     openLogin()       -> show the login modal
     doLogin()         -> send username/password to POST /api/login
     doLogout()        -> call POST /api/logout and clear the session
   ============================================================ */

EI = EI || {};

// On page load, restore a cached token and verify it with the server.
EI.checkSession = function () {
  try {
    EI.authToken = sessionStorage.getItem(EI.SESSION_KEY) || null;
    var cached = sessionStorage.getItem(EI.SESSION_USER_KEY);
    if (cached) EI.currentUser = JSON.parse(cached);
  } catch (e) {}

  if (!EI.authToken) { EI.setAdmin(false); return; }

  // Validate the token against the server.
  $.ajax({
    type: "GET",
    url: "/api/session",
    headers: EI.authHeader({})
  })
    .done(function (resp) {
      if (resp && resp.ok && resp.user) {
        EI.currentUser = resp.user;
        EI.setAdmin(true, true);
      } else {
        EI.clearSession();
        EI.setAdmin(false);
      }
    })
    .fail(function () {
      EI.clearSession();
      EI.setAdmin(false);
    });
};

// Wipe the token and cached user from memory and sessionStorage.
EI.clearSession = function () {
  EI.authToken = null;
  EI.currentUser = { username: "", access_level: "" };
  try {
    sessionStorage.removeItem(EI.SESSION_KEY);
    sessionStorage.removeItem(EI.SESSION_USER_KEY);
  } catch (e) {}
};

// Flip the UI between guest mode and logged-in mode.
// on = true  -> show admin buttons, hide login button
// on = false -> show login button, hide admin buttons
// silent = true -> skip the "Logged in" toast (used for session restore)
EI.setAdmin = function (on, silent) {
  EI.isAdmin = on;
  if (on) {
    try {
      sessionStorage.setItem(EI.SESSION_KEY, EI.authToken);
      sessionStorage.setItem(EI.SESSION_USER_KEY, JSON.stringify(EI.currentUser));
    } catch (e) {}
    var whoLabel = EI.currentUser.username || "user";
    if (EI.currentUser.access_level) whoLabel += " · " + EI.currentUser.access_level;
    $("#adminStatus").addClass("loggedIn").find(".who").text(whoLabel);
    $("#loginBtn").hide();
    $("#logoutBtn").show();
    $("#addPlayerBtn").show();
    $("#changelogBtn").toggle(EI.hasAccess("admin"));
    $("#usersBtn").toggle(EI.hasAccess("master"));
  } else {
    try {
      sessionStorage.removeItem(EI.SESSION_KEY);
      sessionStorage.removeItem(EI.SESSION_USER_KEY);
    } catch (e) {}
    $("#adminStatus").removeClass("loggedIn").find(".who").text("Guest");
    $("#loginBtn").show();
    $("#logoutBtn").hide();
    $("#addPlayerBtn").hide();
    $("#changelogBtn").hide();
    $("#usersBtn").hide();
  }
  EI.renderResults();
  if (EI.selectedId) EI.renderDetail(EI.selectedId);
  if (!silent && on) EI.toast("Logged in as " + (EI.currentUser.username || "admin"), "success");
};

// Show the login modal with empty fields.
EI.openLogin = function () {
  $("#loginUser").val("");
  $("#loginPass").val("");
  $("#loginError").removeClass("visible").text("Invalid credentials. Try again.");
  EI.openModal("loginModal");
  setTimeout(function () { $("#loginUser").focus(); }, 100);
};

// Send username + password to the server. If valid, store the token
// and switch to admin mode. If not, show an error.
EI.doLogin = function () {
  var u = $("#loginUser").val().trim();
  var p = $("#loginPass").val();
  if (!u || !p) {
    $("#loginError").addClass("visible");
    return;
  }
  $("#loginSubmit").prop("disabled", true).text("Logging in...");
  $.ajax({
    type: "POST",
    url: "/api/login",
    contentType: "application/json",
    data: JSON.stringify({ username: u, password: p })
  })
    .done(function (resp) {
      $("#loginSubmit").prop("disabled", false).text("Login");
      if (resp && resp.ok && resp.token) {
        EI.authToken = resp.token;
        EI.currentUser = resp.user || { username: u, access_level: "" };
        EI.closeModal("loginModal");
        EI.setAdmin(true);
      } else {
        $("#loginError").addClass("visible");
        $("#loginPass").val("").focus();
      }
    })
    .fail(function (xhr) {
      $("#loginSubmit").prop("disabled", false).text("Login");
      var msg = "Invalid credentials. Try again.";
      try {
        var j = JSON.parse(xhr.responseText);
        if (j && j.error) msg = j.error;
      } catch (e) {}
      $("#loginError").text(msg).addClass("visible");
      $("#loginPass").val("").focus();
    });
};

// Log out: tell the server to destroy the session, then clear locally.
EI.doLogout = function () {
  if (EI.authToken) {
    $.ajax({ type: "POST", url: "/api/logout", headers: EI.authHeader({}) });
  }
  EI.clearSession();
  EI.setAdmin(false);
  EI.toast("Logged out", "info");
};

/* ---- Modal helpers (tiny but used by everything) ---- */
EI.openModal = function (id) { $("#" + id).addClass("visible"); };
EI.closeModal = function (id) { $("#" + id).removeClass("visible"); };
