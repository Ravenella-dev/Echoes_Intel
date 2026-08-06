/* ============================================================
   core.js  —  Shared namespace, config, and global state
   ------------------------------------------------------------
   This file creates the "EI" object (short for "Echoes Intel").
   Every other file in js/modules/ hangs its functions off this
   object, so they can all talk to each other without anything
   being truly global (only EI is global).

   Think of EI as a big shared box. This file sets up the box and
   puts the config values and state variables inside it. The other
   module files then add their functions to the box.

   THIS FILE MUST LOAD FIRST.  (index.html puts it first.)
   ============================================================ */

var EI = EI || {};

/* ---- Config: API endpoints ----
   These are the URLs the frontend talks to on the server. */
EI.DATA_URL   = "/api/players";
EI.SCRAPE_URL = "/api/scrape";
EI.SAVE_URL   = "/api/players";
EI.BOUNTY_URL = "/api/bounties";

/* ---- Auth config ----
   Authentication is handled server-side. The frontend stores a
   session token returned by POST /api/login and sends it via the
   Authorization: Bearer header. No credentials live in the code. */
EI.SESSION_KEY      = "ee_intel_admin_session";    // holds the bearer token
EI.SESSION_USER_KEY = "ee_intel_session_user";     // cached {username, access_level}
EI.STORAGE_KEY      = "ee_intel_players_v1";

/* ---- Access levels ----
   Must match server.py. Higher index = more capability.
   Order: viewer < editor < admin < master */
EI.ACCESS_LEVELS = ["viewer", "editor", "admin", "master"];

/* ---- Global state ----
   These variables hold the app's current data and UI state.
   They start empty and get filled in as the app runs. */
EI.DATA              = null;
EI.TAG_CATS          = null;   // tag -> {color, icon} lookup
EI.PLAYERS           = [];     // all pilot objects
EI.BOUNTIES          = [];     // all bounty objects from the server
EI.BOUNTY_HISTORY    = {};     // {"PlayerName": [{ts, total}, ...]}
EI.activeFilters     = [];     // currently active tag filters
EI.currentTerm       = "";     // current search text
EI.selectedId        = null;   // id of the pilot shown in the detail panel
EI.currentUser       = { username: "", access_level: "" };
EI.isAdmin           = false;  // convenience alias for "can edit"
EI.authToken         = null;   // bearer token for API requests
EI.editingId         = null;         // player id being edited (null = adding)
EI.pendingDeleteId   = null;
EI.lastScrapeData    = null;         // echoes.mobi result currently in the form
EI.editingBountyId   = null;         // bounty id being edited (null = adding)
EI.bountyFormTargetId = null;        // player id the bounty form targets

/* Quick-filter chips shown under the search bar. */
EI.QUICK_FILTERS = [
  "Dangerous", "Weak", "Main Account", "Alt",
  "High Value Target", "Low Value Target",
  "Supercapital Pilot", "Solo PVPer", "Bounty Hunter",
  "Logistics Pilot", "Explorer", "Baiter"
];

/* ---- Access-level helpers ----
   These are used everywhere to check what the current user is
   allowed to do. */

// Returns a rank number (0-3) for a level string, or -1 if unknown.
EI.accessRank = function (level) {
  var i = EI.ACCESS_LEVELS.indexOf(level);
  return i < 0 ? -1 : i;
};

// Returns true if the current user has at least the given level.
EI.hasAccess = function (level) {
  return EI.accessRank(EI.currentUser.access_level) >= EI.accessRank(level);
};

// Builds the Authorization header for an AJAX request.
// Pass your other headers as the argument; the token is added in.
EI.authHeader = function (extra) {
  var h = extra || {};
  if (EI.authToken) h["Authorization"] = "Bearer " + EI.authToken;
  return h;
};
