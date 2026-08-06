/* ============================================================
   app.js  —  Main JavaScript entry point
   ------------------------------------------------------------
   This file used to be one giant 1,800-line file. It's now split
   into small, focused modules under js/modules/.

   You don't need to edit this file. It's kept here as a guide to
   what lives where. The actual code is loaded by index.html via
   separate <script> tags (in order):

     1. jQuery                    (from CDN)
     2. js/modules/core.js        -> shared namespace (EI), config, state
     3. js/modules/utils.js       -> helper functions (formatIsk, escapeHtml, ...)
     4. js/modules/data.js        -> server communication (load/save players, bounties)
     5. js/modules/search.js      -> search box, filter chips, pilot list
     6. js/modules/detail.js      -> pilot detail panel (right side) + bounty chart
     7. js/modules/auth.js        -> login, logout, session management
     8. js/modules/player-form.js -> add/edit pilot form + echoes.mobi scrape
     9. js/modules/bounty-form.js -> add/edit bounty form
    10. js/modules/admin-panels.js-> changelog viewer + user management
    11. js/modules/main.js        -> event wiring + app startup (calls init())

   All modules share one global object called "EI" (Echoes Intel).
   Each module adds its functions to EI, so they can call each other
   like EI.renderResults(), EI.openPlayerForm(), etc.

   The load order matters: core.js must be first (it creates EI),
   and main.js must be last (it wires up events and calls init).
   ============================================================ */
