// Central Onboarder - frontend logic. Talks to Python exclusively
// through window.pywebview.api (see central_onboarder/gui/api.py) -
// never touches core/ directly, same "front-end stays thin" boundary
// the sibling AOS8-to-AOS10 Conversion Tool project follows. Vanilla
// JS, no framework - same wireX()/data-screen pattern that project's
// own app.js uses, ported and trimmed to this tool's own screens.

let hints = {};

function api() {
  return window.pywebview.api;
}

// --- working device list (persistent bar, visible on every screen) ----

function renderWorkspace(info) {
  const label = document.getElementById("workspaceLabel");
  if (!info.path) {
    label.textContent = "No working device list set";
    return;
  }
  const filename = info.path.split(/[\\/]/).pop();
  if (info.summary) {
    const { total, added_to_glcp, site_assigned } = info.summary;
    label.textContent = `${filename} — ${total} device(s), ${added_to_glcp} in GLCP, ${site_assigned} site-assigned`;
  } else {
    label.textContent = `${filename} — no devices yet`;
  }
}

async function loadWorkspace() {
  const info = await api().get_working_sheet();
  renderWorkspace(info);
  showWorkspaceError(info.schema_error || null);
}

function showWorkspaceError(message) {
  const el = document.getElementById("workspaceError");
  if (message) {
    el.textContent = message;
    el.hidden = false;
  } else {
    el.hidden = true;
  }
}

function wireChangeSheet() {
  document.getElementById("changeSheetBtn").addEventListener("click", async () => {
    const path = await api().pick_existing_sheet_path();
    if (!path) return;
    const result = await api().set_working_sheet(path);
    if (result.ok) {
      renderWorkspace(result);
      showWorkspaceError(null);
      loadDevices();
    } else {
      showWorkspaceError(result.error);
    }
  });
}

function wireNewSheet() {
  document.getElementById("newSheetBtn").addEventListener("click", async () => {
    const path = await api().pick_new_sheet_path();
    if (!path) return;
    const result = await api().create_new_sheet(path);
    if (result.ok) {
      renderWorkspace(result);
      showWorkspaceError(null);
      loadDevices();
    } else {
      showWorkspaceError(result.error);
    }
  });
}

// --- navigation ---------------------------------------------------------

function showScreen(name) {
  document.querySelectorAll(".screen").forEach((el) => (el.hidden = true));
  document.querySelectorAll(".nav-item").forEach((el) => el.classList.remove("active"));
  const btn = document.querySelector(`.nav-item[data-screen="${name}"]`);
  if (btn) btn.classList.add("active");
  const screen = document.getElementById(`screen-${name}`);
  if (screen) screen.hidden = false;
  if (name === "devicelist") loadDevices();
}

function wireNav() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => showScreen(btn.dataset.screen));
  });
}

// --- home links -----------------------------------------------------------

function wireUserGuideLink() {
  document.getElementById("userGuideLink").addEventListener("click", () => api().open_user_guide());
}

function wireChangelogLink() {
  document.getElementById("changelogLink").addEventListener("click", () => api().open_changelog());
}

async function loadVersion() {
  const { version } = await api().get_version();
  document.getElementById("appVersion").textContent = `v${version}`;
}

// --- credentials: load + populate ----------------------------------------

function fieldsFor(card) {
  const values = {};
  card.querySelectorAll("[data-field]").forEach((input) => {
    values[input.dataset.field] = input.value.trim();
  });
  return values;
}

function populateCard(card, entry) {
  if (!entry) return;
  card.querySelectorAll("[data-field]").forEach((input) => {
    if (entry[input.dataset.field] !== undefined) input.value = entry[input.dataset.field];
  });
}

async function loadCredentials() {
  const data = await api().get_credentials();

  const central = data.central || {};
  const firstCentral = Object.keys(central)[0];
  if (firstCentral) {
    const card = document.querySelector('.card[data-category="central"]');
    card.querySelector('[data-field="account"]').value = firstCentral;
    populateCard(card, central[firstCentral]);
  }

  const classic = data.classic || {};
  const firstClassic = Object.keys(classic)[0];
  if (firstClassic) {
    const card = document.querySelector('.card[data-category="classic"]');
    card.querySelector('[data-field="account"]').value = firstClassic;
    populateCard(card, classic[firstClassic]);
  }

  const apSsh = data.ap_ssh || {};
  const firstApSsh = Object.keys(apSsh)[0];
  if (firstApSsh) {
    const card = document.querySelector('.card[data-category="ap_ssh"]');
    card.querySelector('[data-field="account"]').value = firstApSsh;
    populateCard(card, apSsh[firstApSsh]);
    if (apSsh[firstApSsh].ap_ip) document.getElementById("apSshIp").value = apSsh[firstApSsh].ap_ip;
  }
}

// --- hints -----------------------------------------------------------------

async function loadHints() {
  hints = await api().get_hints();
}

function wireHintToggles() {
  document.querySelectorAll(".hint-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const category = btn.dataset.hint;
      const el = document.querySelector(`[data-hint-text="${category}"]`);
      if (el.hidden) {
        el.textContent = hints[category] || "";
        el.hidden = false;
      } else {
        el.hidden = true;
      }
    });
  });
}

function wireRevealToggles() {
  document.querySelectorAll(".reveal-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = btn.previousElementSibling;
      input.type = input.type === "password" ? "text" : "password";
    });
  });
}

// --- save/test/wipe --------------------------------------------------------

function showSaveNote(card, ok, message) {
  let note = card.querySelector(".save-note");
  if (!note) {
    note = document.createElement("p");
    note.className = "save-note";
    card.appendChild(note);
  }
  note.className = "save-note " + (ok ? "ok" : "error");
  note.textContent = message;
}

function wireSaveButtons() {
  document.querySelectorAll(".save-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const category = btn.dataset.save;
      const card = btn.closest(".card");
      const values = fieldsFor(card);
      let result;
      if (category === "central") {
        result = await api().save_central(values.account, values.base_url, values.client_id, values.client_secret);
      } else if (category === "classic") {
        result = await api().save_classic(
          values.account, values.base_url, values.client_id, values.client_secret, values.refresh_token
        );
      } else if (category === "ap_ssh") {
        const apIp = document.getElementById("apSshIp").value.trim() || null;
        result = await api().save_ap_ssh(values.account, values.username, values.password, apIp);
      }
      showSaveNote(card, result.ok, result.ok ? "Saved." : result.error);
    });
  });
}

function setPill(category, state) {
  const pill = document.querySelector(`.status-pill[data-status="${category}"]`);
  if (pill) pill.className = "status-pill " + state;
}

function wireTestAll() {
  document.getElementById("testAllBtn").addEventListener("click", async () => {
    const resultsEl = document.getElementById("testResults");
    resultsEl.textContent = "Testing...";
    const results = await api().test_all();
    resultsEl.innerHTML = "";
    if (results.length === 0) {
      resultsEl.textContent = "No credentials stored yet.";
      return;
    }
    results.forEach((r) => {
      setPill(r.category, r.ok ? "ok" : "fail");
      const row = document.createElement("div");
      row.className = "result-row";
      row.innerHTML = `<span class="key">[${r.category}/${r.key}]</span><span class="detail">${r.detail}</span>`;
      resultsEl.appendChild(row);
    });
  });
}

function wireTestButtons() {
  document.querySelectorAll(".test-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const category = btn.dataset.test;
      const card = btn.closest(".card");
      const resultEl = card.querySelector(`[data-test-result="${category}"]`);
      resultEl.className = "save-note";
      resultEl.textContent = "Testing...";
      const account = card.querySelector('[data-field="account"]').value.trim();
      const result = category === "central" ? await api().test_central(account) : await api().test_classic(account);
      setPill(category, result.ok ? "ok" : "fail");
      resultEl.className = "save-note " + (result.ok ? "ok" : "error");
      resultEl.textContent = result.detail || result.error || "";
    });
  });
}

function clearCardFields(card) {
  card.querySelectorAll("[data-field]").forEach((input) => (input.value = ""));
}

function wireWipeButtons() {
  document.querySelectorAll(".wipe-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const category = btn.dataset.wipe;
      const card = btn.closest(".card");
      showConfirmModal(
        "Wipe stored credential",
        `This removes every stored ${category} credential. Cannot be undone.`,
        "WIPE", "Wipe",
        async () => {
          await api().wipe_credentials(category);
          clearCardFields(card);
          setPill(category, "idle");
          showSaveNote(card, true, "Wiped.");
        }
      );
    });
  });
}

function wireWipeAllCredentials() {
  document.getElementById("wipeAllCredentialsBtn").addEventListener("click", () => {
    showConfirmModal(
      "Wipe all credentials", "This removes every stored credential of every kind. Cannot be undone.",
      "WIPE ALL", "Wipe All",
      async () => {
        await api().wipe_all_credentials();
        document.querySelectorAll(".card[data-category]").forEach((card) => clearCardFields(card));
        document.querySelectorAll(".status-pill").forEach((pill) => (pill.className = "status-pill idle"));
        const resultEl = document.getElementById("wipeAllCredentialsResult");
        resultEl.className = "save-note ok";
        resultEl.textContent = "Wiped.";
      }
    );
  });
}

// --- confirmation modal ----------------------------------------------------

let modalConfirmWord = null;
let modalOnConfirm = null;

function showConfirmModal(title, message, confirmWord, confirmLabel, onConfirm) {
  document.getElementById("modalTitle").textContent = title;
  document.getElementById("modalMessage").textContent = message;
  const input = document.getElementById("modalConfirmInput");
  input.value = "";
  input.placeholder = `Type ${confirmWord} to confirm`;
  const confirmBtn = document.getElementById("modalConfirmBtn");
  confirmBtn.textContent = confirmLabel;
  confirmBtn.disabled = true;
  modalConfirmWord = confirmWord;
  modalOnConfirm = onConfirm;
  document.getElementById("confirmModalOverlay").hidden = false;
  input.focus();
}

function hideConfirmModal() {
  document.getElementById("confirmModalOverlay").hidden = true;
  modalOnConfirm = null;
}

function wireConfirmModal() {
  document.getElementById("modalConfirmInput").addEventListener("input", (e) => {
    document.getElementById("modalConfirmBtn").disabled = e.target.value.trim() !== modalConfirmWord;
  });
  document.getElementById("modalCancelBtn").addEventListener("click", hideConfirmModal);
  document.getElementById("modalConfirmBtn").addEventListener("click", () => {
    const callback = modalOnConfirm;
    hideConfirmModal();
    if (callback) callback();
  });
}

// --- device list -------------------------------------------------------

function tick(value) {
  return value ? '<span class="tick">&#10003;</span>' : "";
}

async function loadDevices() {
  const result = await api().get_devices();
  const body = document.getElementById("deviceGridBody");
  body.innerHTML = "";
  if (!result.ok) {
    document.getElementById("gridSelectedCount").textContent = result.error || "";
    return;
  }
  document.getElementById("gridSelectedCount").textContent = `${result.devices.length} device(s)`;
  result.devices.forEach((d) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td class="chk-col"><input type="checkbox" data-serial="${d.serial}"></td>` +
      `<td>${d.serial}</td><td>${d.mac || ""}</td><td>${d.device_type || ""}</td>` +
      `<td>${d.target_group || ""}</td><td>${d.target_site || ""}</td><td>${d.subscription_key || ""}</td>` +
      `<td class="tick">${tick(d.added_to_glcp)}</td><td class="tick">${tick(d.subscription_assigned)}</td>` +
      `<td class="tick">${tick(d.service_assigned)}</td><td class="tick">${tick(d.preprovisioned)}</td>` +
      `<td class="tick">${tick(d.site_assigned)}</td>`;
    body.appendChild(tr);
  });
}

function wireRefreshDevices() {
  document.getElementById("refreshDevicesBtn").addEventListener("click", loadDevices);
}

function wireAddDevice() {
  document.getElementById("addDeviceBtn").addEventListener("click", async () => {
    const device = {
      serial: document.getElementById("addSerial").value.trim(),
      mac: document.getElementById("addMac").value.trim(),
      device_type: document.getElementById("addDeviceType").value,
      target_group: document.getElementById("addTargetGroup").value.trim(),
      target_site: document.getElementById("addTargetSite").value.trim(),
      subscription_key: document.getElementById("addSubscriptionKey").value.trim(),
    };
    const resultEl = document.getElementById("addDeviceResult");
    if (!device.serial) {
      resultEl.className = "save-note error";
      resultEl.textContent = "Serial is required.";
      return;
    }
    const result = await api().add_devices_manual([device]);
    resultEl.className = "save-note " + (result.ok ? "ok" : "error");
    resultEl.textContent = result.ok
      ? `Saved (${result.rows_added} added, ${result.rows_updated} updated).`
      : result.error;
    if (result.ok) {
      document.getElementById("addSerial").value = "";
      document.getElementById("addMac").value = "";
      loadWorkspace();
      loadDevices();
    }
  });
}

function wireDownloadCsvTemplate() {
  document.getElementById("downloadCsvTemplateBtn").addEventListener("click", async () => {
    await api().save_csv_template();
  });
}

function wireImportCsv() {
  document.getElementById("importCsvBtn").addEventListener("click", async () => {
    const path = await api().pick_csv_path();
    if (!path) return;
    const resultEl = document.getElementById("importCsvResult");
    resultEl.className = "save-note";
    resultEl.textContent = "Importing...";
    const result = await api().import_csv(path);
    resultEl.className = "save-note " + (result.ok ? "ok" : "error");
    resultEl.textContent = result.ok
      ? `Imported (${result.rows_added} added, ${result.rows_updated} updated` +
        (result.skipped_blank_serial_rows ? `, ${result.skipped_blank_serial_rows} skipped (blank Serial)` : "") + ")."
      : result.error;
    if (result.ok) {
      loadWorkspace();
      loadDevices();
    }
  });
}

function wireLoadDestinations() {
  document.getElementById("loadDestinationsBtn").addEventListener("click", async () => {
    const result = await api().get_central_destinations();
    if (!result.ok) {
      alert(result.error);
      return;
    }
    const groupList = document.getElementById("groupOptions");
    const siteList = document.getElementById("siteOptions");
    groupList.innerHTML = result.groups.map((g) => `<option value="${g}">`).join("");
    siteList.innerHTML = result.sites.map((s) => `<option value="${s}">`).join("");
  });
}

// --- onboard -------------------------------------------------------------

function renderResultsBlock(el, title, resultsObj) {
  if (!resultsObj) return "";
  const lines = resultsObj.results
    .map((r) => `${r.ok ? "OK" : "FAIL"}  ${r.serial}${r.detail ? "  - " + r.detail : ""}`)
    .join("\n");
  return `<h4>${title}</h4>${lines || "(nothing to do)"}`;
}

function wireRunOnboardBatch() {
  document.getElementById("runOnboardBatchBtn").addEventListener("click", async () => {
    const resultEl = document.getElementById("onboardBatchResult");
    resultEl.innerHTML = "Running...";
    const result = await api().run_onboard_batch();
    if (!result.ok) {
      resultEl.innerHTML = `<p class="save-note error">${result.error}</p>`;
      return;
    }
    let html = `<p class="save-note ok">Processed ${result.processed} device(s).</p>`;
    if (result.missing_mac && result.missing_mac.length) {
      html += `<p class="save-note error">Skipped (no MAC): ${result.missing_mac.join(", ")}</p>`;
    }
    html += `<div class="result-block">${renderResultsBlock(resultEl, "Add to GLCP", result.add_device)}\n\n${renderResultsBlock(resultEl, "Assign Service", result.service)}${result.subscription ? "\n\n" + renderResultsBlock(resultEl, "Assign Subscription", result.subscription) : ""}</div>`;
    resultEl.innerHTML = html;
    loadWorkspace();
    loadDevices();
  });
}

function parseIdentifiers(value) {
  return value.split(",").map((s) => s.trim()).filter(Boolean);
}

function wireManualSubscription() {
  document.getElementById("manualAssignSubBtn").addEventListener("click", async () => {
    const identifiers = parseIdentifiers(document.getElementById("manualSubIdentifiers").value);
    const key = document.getElementById("manualSubKey").value.trim();
    const resultEl = document.getElementById("manualSubResult");
    if (!identifiers.length || !key) {
      resultEl.innerHTML = '<p class="save-note error">Serial(s)/MAC(s) and Subscription Key are required.</p>';
      return;
    }
    const result = await api().assign_subscription(identifiers, key);
    resultEl.innerHTML = `<div class="result-block">${renderResultsBlock(resultEl, "Assign Subscription", result)}</div>`;
    loadDevices();
  });

  document.getElementById("manualRemoveSubBtn").addEventListener("click", async () => {
    const identifiers = parseIdentifiers(document.getElementById("manualSubIdentifiers").value);
    const resultEl = document.getElementById("manualSubResult");
    if (!identifiers.length) {
      resultEl.innerHTML = '<p class="save-note error">Serial(s)/MAC(s) are required.</p>';
      return;
    }
    const result = await api().remove_subscription_key(identifiers);
    resultEl.innerHTML = `<div class="result-block">${renderResultsBlock(resultEl, "Remove Subscription", result)}</div>`;
    loadDevices();
  });
}

function wireManualService() {
  document.getElementById("manualAssignServiceBtn").addEventListener("click", async () => {
    const identifiers = parseIdentifiers(document.getElementById("manualServiceIdentifiers").value);
    const appId = document.getElementById("manualServiceAppId").value.trim() || null;
    const resultEl = document.getElementById("manualServiceResult");
    if (!identifiers.length) {
      resultEl.innerHTML = '<p class="save-note error">Serial(s)/MAC(s) are required.</p>';
      return;
    }
    const result = await api().assign_service(identifiers, appId);
    resultEl.innerHTML = `<div class="result-block">${renderResultsBlock(resultEl, "Assign Service", result)}</div>`;
    loadDevices();
  });
}

// --- pre-provision ---------------------------------------------------------

function wireRunPreprovision() {
  document.getElementById("runPreprovisionBtn").addEventListener("click", async () => {
    const resultEl = document.getElementById("preprovisionResult");
    resultEl.textContent = "Running...";
    const result = await api().preprovision();
    if (!result.ok && result.error) {
      resultEl.innerHTML = `<p class="save-note error">${result.error}</p>`;
      return;
    }
    resultEl.innerHTML = `<p class="save-note ${result.failed ? "error" : "ok"}">Provisioned ${result.provisioned}, failed ${result.failed}.</p>`;
    loadDevices();
  });
}

function wireCheckStatus() {
  document.getElementById("checkDeviceGroupBtn").addEventListener("click", async () => {
    const serial = document.getElementById("checkStatusSerial").value.trim();
    const resultEl = document.getElementById("checkStatusResult");
    if (!serial) return;
    const result = await api().check_device_group(serial);
    resultEl.innerHTML = result.ok
      ? `<p class="save-note">Group: ${result.group || "(none)"}</p>`
      : `<p class="save-note error">${result.error}</p>`;
  });

  document.getElementById("checkApStatusBtn").addEventListener("click", async () => {
    const serial = document.getElementById("checkStatusSerial").value.trim();
    const resultEl = document.getElementById("checkStatusResult");
    if (!serial) return;
    const result = await api().check_ap_status(serial);
    if (!result.ok) {
      resultEl.innerHTML = `<p class="save-note error">${result.error}</p>`;
      return;
    }
    resultEl.innerHTML = result.seen
      ? `<p class="save-note">Status: ${result.status}, Group: ${result.group_name || "(none)"}, Site: ${result.site_name || "(none)"}, Firmware: ${result.firmware_version || "(unknown)"}</p>`
      : `<p class="save-note">Not seen yet - hasn't checked into Central.</p>`;
  });
}

// --- assign site -------------------------------------------------------

function wireRunAssignSite() {
  document.getElementById("runAssignSiteBtn").addEventListener("click", async () => {
    const resultEl = document.getElementById("assignSiteResult");
    resultEl.textContent = "Running...";
    const result = await api().assign_site();
    if (!result.ok && result.error) {
      resultEl.innerHTML = `<p class="save-note error">${result.error}</p>`;
      return;
    }
    let html = `<p class="save-note ${result.failed ? "error" : "ok"}">Assigned ${result.assigned}, failed ${result.failed}.</p>`;
    if (result.unresolved_sites && result.unresolved_sites.length) {
      html += `<p class="save-note error">Site name(s) not found in Classic Central: ${result.unresolved_sites.join(", ")}</p>`;
    }
    if (result.unrecognized_types && result.unrecognized_types.length) {
      html += `<p class="save-note error">Device Type not recognized (must be AP/Switch/Gateway): ${result.unrecognized_types.join(", ")}</p>`;
    }
    resultEl.innerHTML = html;
    loadDevices();
  });
}

// --- tools ---------------------------------------------------------------

function wireCreateSite() {
  document.getElementById("createSiteBtn").addEventListener("click", async () => {
    const resultEl = document.getElementById("createSiteResult");
    const result = await api().create_site(
      document.getElementById("createSiteName").value.trim(),
      document.getElementById("createSiteAddress").value.trim(),
      document.getElementById("createSiteCity").value.trim(),
      document.getElementById("createSiteState").value.trim(),
      document.getElementById("createSiteZip").value.trim(),
      document.getElementById("createSiteCountry").value.trim() || "United States",
      document.getElementById("createSiteTimezone").value.trim() || "America/Chicago"
    );
    resultEl.innerHTML = result.ok
      ? '<p class="save-note ok">Site created.</p>'
      : `<p class="save-note error">${result.error}</p>`;
  });
}

function wireResetToDefault() {
  document.getElementById("resetToDefaultBtn").addEventListener("click", () => {
    showConfirmModal(
      "Reset to default", "This clears the working device list pointer and every stored credential. Cannot be undone.",
      "RESET", "Reset",
      async () => {
        await api().reset_to_default();
        const resultEl = document.getElementById("resetToDefaultResult");
        resultEl.className = "save-note ok";
        resultEl.textContent = "Reset.";
        loadWorkspace();
        loadCredentials();
        document.querySelectorAll(".status-pill").forEach((pill) => (pill.className = "status-pill idle"));
      }
    );
  });
}

// --- bootstrap -------------------------------------------------------------

async function init() {
  wireNav();
  wireUserGuideLink();
  wireChangelogLink();
  wireChangeSheet();
  wireNewSheet();
  wireHintToggles();
  wireRevealToggles();
  wireSaveButtons();
  wireTestAll();
  wireTestButtons();
  wireWipeButtons();
  wireWipeAllCredentials();
  wireConfirmModal();
  wireRefreshDevices();
  wireAddDevice();
  wireDownloadCsvTemplate();
  wireImportCsv();
  wireLoadDestinations();
  wireRunOnboardBatch();
  wireManualSubscription();
  wireManualService();
  wireRunPreprovision();
  wireCheckStatus();
  wireRunAssignSite();
  wireCreateSite();
  wireResetToDefault();

  await loadVersion();
  await loadWorkspace();
  await loadCredentials();
  await loadHints();
}

window.addEventListener("pywebviewready", init);
