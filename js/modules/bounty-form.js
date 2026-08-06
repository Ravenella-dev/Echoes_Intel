/* ============================================================
   bounty-form.js  —  Add / edit bounty form + bounty delete
   ------------------------------------------------------------
   Handles the bounty form modal (separate from the pilot form).
   Bounties have an "issuer" (the person paying) and optionally a
   "broker" (if the client wants to stay anonymous / masked).

   Key functions:
     openBountyForm(playerId, bountyId)  -> open the form (bountyId=null for new)
     blankBounty(playerId, name)         -> fresh empty bounty object
     buildBountyFormHtml(b)              -> build the form fields
     updateBrokerVisibility()            -> show/hide broker fields based on "masked"
     collectBountyForm()                 -> read form into a bounty object
     saveBountyFromForm()                -> save + close
     askDeleteBounty(bountyId, playerId) -> show delete confirmation
     confirmDeleteBounty()               -> actually delete the bounty
   ============================================================ */

EI = EI || {};

// Open the bounty form. Pass bountyId=null to add, or an id to edit.
EI.openBountyForm = function (playerId, bountyId) {
  if (!EI.hasAccess("editor")) return;
  EI.bountyFormTargetId = playerId;
  EI.editingBountyId = bountyId || null;

  var p = EI.findPlayer(playerId);
  if (!p) { EI.toast("Pilot not found", "error"); return; }

  // Existing bounty to edit, or blank
  var b = bountyId
    ? EI.BOUNTIES.find(function (x) { return x.id === bountyId; })
    : EI.blankBounty(playerId, p.name);

  if (bountyId && !b) { EI.toast("Bounty not found", "error"); return; }

  $("#bountyFormTitle").html(bountyId
    ? '<span class="mt-icon">✎</span> Edit Bounty on ' + EI.escapeHtml(p.name)
    : '<span class="mt-icon">🦸</span> Add Bounty on ' + EI.escapeHtml(p.name));
  $("#bountyFormDelete").toggle(!!bountyId);
  $("#bountyFormBody").html(EI.buildBountyFormHtml(b));
  EI.updateBrokerVisibility();
  EI.openModal("bountyFormModal");
};

// Return a fresh, empty bounty object.
EI.blankBounty = function (playerId, playerName) {
  return {
    target_player_id: playerId,
    target_name: playerName,
    issuer_name: "", issuer_corp: "", issuer_discord: "",
    broker_name: "", broker_discord: "",
    is_masked: false, amount: 0
  };
};

// Build all the bounty form fields as HTML.
EI.buildBountyFormHtml = function (b) {
  return (
    '<div class="bounty-form">' +
      '<div class="form-field"><label>Target pilot</label>' +
        '<input type="text" id="bfTarget" value="' + EI.escapeHtml(b.target_name) + '" readonly style="opacity:0.7;" />' +
      '</div>' +
      '<div class="form-row">' +
        '<div class="form-field"><label>Bounty amount (ISK) <span class="req">*</span></label>' +
          '<input type="number" id="bfAmount" min="0" step="1" value="' + (b.amount || 0) + '" /></div>' +
      '</div>' +

      '<div class="bounty-form-divider"></div>' +
      '<div class="bounty-form-section-title">🕵 Issuer (the one paying)</div>' +

      '<div class="form-row">' +
        '<div class="form-field"><label>Issuer name <span class="req">*</span></label>' +
          '<input type="text" id="bfIssuerName" value="' + EI.escapeHtml(b.issuer_name) + '" placeholder="e.g. Dirtnap Jimmy" /></div>' +
        '<div class="form-field"><label>Issuer corp</label>' +
          '<input type="text" id="bfIssuerCorp" value="' + EI.escapeHtml(b.issuer_corp) + '" placeholder="e.g. Hard Knocks Inc." /></div>' +
      '</div>' +
      '<div class="form-field"><label>Issuer Discord username</label>' +
        '<input type="text" id="bfIssuerDiscord" value="' + EI.escapeHtml(b.issuer_discord) + '" placeholder="e.g. dirtnap#0420" /></div>' +

      '<div class="bounty-form-divider"></div>' +
      '<div class="bounty-form-masked-row">' +
        '<label class="bounty-checkbox-row">' +
          '<input type="checkbox" id="bfMasked" ' + (b.is_masked ? "checked" : "") + ' /> ' +
          '<span>Masked / anonymous client</span>' +
        '</label>' +
        '<div class="hint">If checked, the issuer\'s identity is hidden. A broker handles contact &amp; payment instead.</div>' +
      '</div>' +

      '<div class="bounty-form-broker-section" id="brokerSection">' +
        '<div class="bounty-form-section-title">🎯 Broker (contact for masked bounties)</div>' +
        '<div class="form-row">' +
          '<div class="form-field"><label>Broker name</label>' +
            '<input type="text" id="bfBrokerName" value="' + EI.escapeHtml(b.broker_name) + '" placeholder="e.g. Kane Midfield" /></div>' +
          '<div class="form-field"><label>Broker Discord username</label>' +
            '<input type="text" id="bfBrokerDiscord" value="' + EI.escapeHtml(b.broker_discord) + '" placeholder="e.g. kane_mid#7788" /></div>' +
        '</div>' +
      '</div>' +
    '</div>'
  );
};

// Show or hide the broker section depending on the "masked" checkbox.
EI.updateBrokerVisibility = function () {
  var masked = $("#bfMasked").is(":checked");
  if (masked) {
    $("#brokerSection").show();
  } else {
    $("#brokerSection").hide();
  }
};

// Read the bounty form fields into a bounty object. Returns null on error.
EI.collectBountyForm = function () {
  var amount = parseFloat($("#bfAmount").val()) || 0;
  var issuerName = $("#bfIssuerName").val().trim();
  var masked = $("#bfMasked").is(":checked");

  if (amount <= 0) { $("#bfAmount").focus(); EI.toast("Bounty amount must be greater than 0", "error"); return null; }
  if (!masked && !issuerName) { $("#bfIssuerName").focus(); EI.toast("Issuer name is required (or check masked)", "error"); return null; }
  if (masked && !issuerName) issuerName = "Anonymous Client";

  var p = EI.findPlayer(EI.bountyFormTargetId);
  return {
    target_player_id: EI.bountyFormTargetId,
    target_name: p ? p.name : $("#bfTarget").val().trim(),
    issuer_name: issuerName,
    issuer_corp: $("#bfIssuerCorp").val().trim(),
    issuer_discord: $("#bfIssuerDiscord").val().trim(),
    broker_name: $("#bfBrokerName").val().trim(),
    broker_discord: $("#bfBrokerDiscord").val().trim(),
    is_masked: masked,
    amount: amount
  };
};

// Save the bounty (add or update) and close the form.
EI.saveBountyFromForm = function () {
  var b = EI.collectBountyForm();
  if (!b) return;
  EI.saveBounty(b, EI.editingBountyId)
    .done(function (resp) {
      if (resp && resp.ok) {
        EI.toast(EI.editingBountyId ? "Updated bounty" : "Added bounty on " + b.target_name, "success");
        EI.closeModal("bountyFormModal");
        EI.refreshBounties();
      } else {
        EI.toast("Error: " + ((resp && resp.error) || "unknown"), "error");
      }
    })
    .fail(function (xhr) {
      var msg = "Could not save bounty";
      try { var j = JSON.parse(xhr.responseText); if (j.error) msg = j.error; } catch (e) {}
      EI.toast(msg, "error");
    });
};

// Show the "are you sure?" dialog for deleting a bounty.
EI.askDeleteBounty = function (bountyId, playerId) {
  var p = EI.findPlayer(playerId);
  EI.pendingDeleteId = playerId; // reuse confirm modal
  $("#confirmMsg").html(
    'Remove this bounty' + (p ? ' on <span class="confirm-name">' + EI.escapeHtml(p.name) + '</span>' : "") +
    '? <strong>This cannot be undone.</strong>' +
    '<input type="hidden" id="confirmBountyId" value="' + bountyId + '" />'
  );
  EI.openModal("confirmModal");
};

// Actually delete the bounty from the server.
EI.confirmDeleteBounty = function () {
  var bountyId = parseInt($("#confirmBountyId").val(), 10);
  if (!bountyId) { EI.confirmDelete(); return; } // fall through to player delete if no bounty id
  EI.deleteBountyRemote(bountyId)
    .done(function () {
      EI.toast("Removed bounty", "warn");
      EI.closeModal("confirmModal");
      EI.refreshBounties();
    })
    .fail(function (xhr) {
      var msg = "Could not delete bounty";
      try { var j = JSON.parse(xhr.responseText); if (j.error) msg = j.error; } catch (e) {}
      EI.toast(msg, "error");
    });
};
