/* ============================================================
   utils.js  —  Small helper functions used everywhere
   ------------------------------------------------------------
   These are the "utility belt" functions. They don't talk to the
   server or change the page — they just format text, escape HTML,
   look up tag info, and do small calculations. Other modules call
   them constantly.

   Key functions:
     formatIsk(value)        -> "1.50 B", "320 K", etc.
     escapeHtml(str)         -> makes text safe to insert into HTML
     highlight(text, term)   -> wraps search matches in a <span>
     threatClass(level)      -> "high" / "med" / "low" (for CSS styling)
     valueClass(tags)        -> "high-value" / "med-value" / "low-value"
     threatFillColor(level)  -> a hex colour for the threat bar
     threatLabel(level)      -> "extreme threat", "low threat", etc.
     hexA(hex, alpha)        -> converts #rrggbb to rgba(r,g,b,a)
     miniTag(tagName)        -> small tag chip HTML (used in the list)
     fullTag(tagName)        -> larger tag chip HTML (used in detail)
     nextId()                -> generates the next pilot id ("p001", "p002"...)
     findPlayer(id)          -> looks up a pilot by id in EI.PLAYERS
   ============================================================ */

EI = EI || {};

// Format a big ISK number into a short, readable string.
EI.formatIsk = function (value) {
  value = Number(value) || 0;
  if (value >= 1e12) return (value / 1e12).toFixed(2) + " T";
  if (value >= 1e9)  return (value / 1e9).toFixed(2) + " B";
  if (value >= 1e6)  return (value / 1e6).toFixed(2) + " M";
  if (value >= 1e3)  return (value / 1e3).toFixed(1) + " K";
  return value.toString();
};

// Escape special characters so text is safe to drop into HTML.
// This prevents XSS if pilot names contain <, >, &, etc.
EI.escapeHtml = function (str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
};

// Escape text, then wrap any part matching the search term in a
// <span class="match-highlight"> so it shows up yellow in the list.
EI.highlight = function (text, term) {
  var safe = EI.escapeHtml(text);
  if (!term) return safe;
  var escTerm = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return safe.replace(new RegExp("(" + escTerm + ")", "gi"),
    '<span class="match-highlight">$1</span>');
};

// Map a threat level (0-10) to a CSS class for colour-coding.
EI.threatClass = function (level) {
  level = Number(level) || 0;
  if (level >= 7) return "high";
  if (level >= 4) return "med";
  return "low";
};

// Look at a pilot's tags and return a value-class string.
EI.valueClass = function (tags) {
  if (tags.indexOf("High Value Target") > -1) return "high-value";
  if (tags.indexOf("Medium Value Target") > -1) return "med-value";
  return "low-value";
};

// Return a hex colour for the threat bar fill.
EI.threatFillColor = function (level) {
  level = Number(level) || 0;
  if (level >= 7) return "#e74c3c";
  if (level >= 4) return "#f39c12";
  return "#27ae60";
};

// Return a human-readable label for a threat level.
EI.threatLabel = function (level) {
  level = Number(level) || 0;
  if (level >= 8) return "extreme threat";
  if (level >= 6) return "high threat";
  if (level >= 4) return "moderate threat";
  if (level >= 2) return "low threat";
  return "minimal threat";
};

// Convert a hex colour (#rrggbb or #rgb) to an rgba() string
// with the given alpha (0-1). Used for semi-transparent backgrounds.
EI.hexA = function (hex, alpha) {
  var h = (hex || "#7f8c8d").replace("#", "");
  if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
  var r = parseInt(h.substring(0, 2), 16);
  var g = parseInt(h.substring(2, 4), 16);
  var b = parseInt(h.substring(4, 6), 16);
  return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
};

// Build a small tag chip (used in the pilot list cards).
EI.miniTag = function (tagName) {
  var cat = EI.TAG_CATS[tagName] || { color: "#7f8c8d", icon: "•" };
  return '<span class="mini-tag" style="color:' + cat.color + ';border-color:' +
    EI.hexA(cat.color, 0.3) + '"><span class="ticon">' + (cat.icon || "") +
    '</span>' + EI.escapeHtml(tagName) + '</span>';
};

// Build a larger tag chip (used in the detail panel).
EI.fullTag = function (tagName) {
  var cat = EI.TAG_CATS[tagName] || { color: "#7f8c8d", icon: "•" };
  return '<span class="full-tag" style="background:' + EI.hexA(cat.color, 0.13) +
    ';border:1px solid ' + EI.hexA(cat.color, 0.4) + ';color:' + cat.color +
    '"><span class="ticon">' + (cat.icon || "") + '</span>' +
    EI.escapeHtml(tagName) + '</span>';
};

// Generate the next sequential pilot id ("p001", "p002", ...).
EI.nextId = function () {
  var max = 0;
  EI.PLAYERS.forEach(function (p) {
    var n = parseInt((p.id || "").replace(/\D/g, ""), 10);
    if (!isNaN(n) && n > max) max = n;
  });
  return "p" + String(max + 1).padStart(3, "0");
};

// Look up a pilot by id. Returns the pilot object or undefined.
EI.findPlayer = function (id) {
  return EI.PLAYERS.find(function (x) { return x.id === id; });
};

// Show a toast notification at the bottom of the screen.
// kind: "" (info), "success", "warn", "error"
EI.toast = function (msg, kind) {
  var $t = $('<div class="toast ' + (kind || "") + '">' + EI.escapeHtml(msg) + "</div>");
  $("#toastStack").append($t);
  setTimeout(function () {
    $t.fadeOut(250, function () { $(this).remove(); });
  }, 3200);
};

// Check if a scraped-at timestamp is older than 7 days (stale).
EI.isStale = function (iso) {
  if (!iso) return false;
  var then = new Date(iso).getTime();
  if (isNaN(then)) return false;
  return (Date.now() - then) > 7 * 24 * 3600 * 1000;
};
