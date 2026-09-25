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

// Card field name -> token.yaml key, per card. Mirrors
// core/credential_store.py's CATEGORY_KEYS.
const CARD_KEYS = {
  central: { base_url: "base_url", client_id: "client_id", client_secret: "client_secret" },
  classic: {
    base_url: "apigw_base_url", client_id: "apigw_client_id",
    client_secret: "apigw_client_secret", refresh_token: "apigw_refresh_token",
  },
  ap_ssh: { username: "ap_ssh_username", password: "ap_ssh_password", ap_ip: "ap_ip" },
  uxi: { application_id: "uxi_application_id", region: "uxi_region" },
};

// The account every save/test/wipe on the Credentials screen acts on -
// the same one the top bar's dropdown shows, and the one every other
// screen's API calls use.
let activeAccount = null;

function populateCard(card, entry) {
  const keys = CARD_KEYS[card.dataset.category];
  card.querySelectorAll("[data-field]").forEach((input) => {
    const value = entry ? entry[keys[input.dataset.field]] : undefined;
    input.value = value === undefined || value === null ? "" : value;
  });
}

function renderAccountPicker(accounts, active) {
  const select = document.getElementById("accountSelect");
  select.innerHTML = "";
  const names = Object.keys(accounts);
  if (names.length === 0) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "(no accounts - add one in Credentials)";
    select.appendChild(opt);
    select.disabled = true;
    return;
  }
  select.disabled = false;
  names.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    if (name === active) opt.selected = true;
    select.appendChild(opt);
  });
}

async function loadCredentials() {
  const data = await api().get_credentials();
  activeAccount = data.active;
  renderAccountPicker(data.accounts, data.active);
  document.getElementById("tokenYamlPath").textContent = data.path;
  document.getElementById("activeAccountLabel").textContent = data.active || "(none)";

  const entry = data.active ? data.accounts[data.active] : null;
  document.querySelectorAll(".card[data-category]").forEach((card) => populateCard(card, entry));

  const legacyNote = document.getElementById("legacyNote");
  if (data.migrated && data.migrated.length) {
    legacyNote.className = "save-note ok";
    legacyNote.textContent =
      `Imported ${data.migrated.join(", ")} from the old credentials.json into token.yaml. ` +
      "Once you've confirmed they test OK, you can delete credentials.json.";
    legacyNote.hidden = false;
  } else if (data.legacy_file_present) {
    legacyNote.className = "save-note";
    legacyNote.textContent = "An old credentials.json is still next to the app. It is no longer read, so you can delete it.";
    legacyNote.hidden = false;
  } else {
    legacyNote.hidden = true;
  }
}

function resetAccountScopedState() {
  document.querySelectorAll(".status-pill").forEach((pill) => (pill.className = "status-pill idle"));
  document.querySelectorAll("[data-test-result]").forEach((el) => { el.className = "save-note"; el.textContent = ""; });
  document.getElementById("testResults").innerHTML = "";
  document.getElementById("glcpServicesResult").innerHTML = "";
  // Group/site pick-lists came from the previous account's tenant.
  document.getElementById("groupOptions").innerHTML = "";
  document.getElementById("siteOptions").innerHTML = "";
  // Subscriptions belong to the previous account's workspace.
  pulledSubscriptions = null;
  renderSubscriptions();
  document.getElementById("subscriptionsResult").textContent = "";
}

function wireAccountPicker() {
  document.getElementById("accountSelect").addEventListener("change", async (e) => {
    const result = await api().set_active_account(e.target.value);
    if (!result.ok) {
      showAccountResult(false, result.error);
    }
    resetAccountScopedState();
    await loadCredentials();
  });
}

function showAccountResult(ok, message) {
  const el = document.getElementById("accountResult");
  el.className = "save-note " + (ok ? "ok" : "error");
  el.textContent = message;
}

function wireAddAccount() {
  document.getElementById("addAccountBtn").addEventListener("click", async () => {
    const input = document.getElementById("newAccountName");
    const result = await api().add_account(input.value);
    if (!result.ok) {
      showAccountResult(false, result.error);
      return;
    }
    input.value = "";
    resetAccountScopedState();
    await loadCredentials();
    showAccountResult(true, `Added and selected "${activeAccount}". Fill in its credentials below.`);
  });
}

function wireDeleteAccount() {
  document.getElementById("deleteAccountBtn").addEventListener("click", () => {
    if (!activeAccount) {
      showAccountResult(false, "No account selected.");
      return;
    }
    const name = activeAccount;
    showConfirmModal(
      "Delete account",
      `This removes the account "${name}" and every credential stored under it from token.yaml. Cannot be undone.`,
      "DELETE", "Delete",
      async () => {
        await api().delete_account(name);
        resetAccountScopedState();
        await loadCredentials();
        showAccountResult(true, `Deleted "${name}".`);
      }
    );
  });
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
      const account = activeAccount;
      if (!account) {
        showSaveNote(card, false, "Add an account first (Accounts card above).");
        return;
      }
      let result;
      if (category === "central") {
        result = await api().save_central(account, values.base_url, values.client_id, values.client_secret);
      } else if (category === "classic") {
        result = await api().save_classic(
          account, values.base_url, values.client_id, values.client_secret, values.refresh_token
        );
      } else if (category === "ap_ssh") {
        result = await api().save_ap_ssh(account, values.username, values.password, values.ap_ip || null);
      } else if (category === "uxi") {
        result = await api().save_uxi(account, values.application_id, values.region || null);
      }
      showSaveNote(card, result.ok, result.ok ? `Saved to "${account}".` : result.error);
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
      const account = activeAccount || "";
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
      const account = activeAccount;
      if (!account) {
        showSaveNote(card, false, "No account selected.");
        return;
      }
      showConfirmModal(
        "Wipe stored credential",
        `This removes the ${category} values from account "${account}" (its other credentials stay). Cannot be undone.`,
        "WIPE", "Wipe",
        async () => {
          await api().wipe_credentials(account, category);
          clearCardFields(card);
          setPill(category, "idle");
          showSaveNote(card, true, "Wiped.");
        }
      );
    });
  });
}

function wireListGlcpServices() {
  document.getElementById("listGlcpServicesBtn").addEventListener("click", async () => {
    const resultEl = document.getElementById("glcpServicesResult");
    resultEl.innerHTML = '<p class="save-note">Looking up...</p>';
    const result = await api().list_glcp_services();
    if (!result.ok) {
      resultEl.innerHTML = `<p class="save-note error">${result.error}</p>`;
      return;
    }
    if (!result.services.length) {
      resultEl.innerHTML = '<p class="save-note">No services found in this workspace.</p>';
      return;
    }
    resultEl.innerHTML = "";
    result.services.forEach((svc) => {
      const row = document.createElement("button");
      row.className = "link-btn";
      row.style.display = "block";
      row.style.margin = "4px 0";
      row.textContent = `${svc.name || "(unnamed)"} - ${svc.id}`;
      row.addEventListener("click", () => {
        document.querySelector('.card[data-category="uxi"] [data-field="application_id"]').value = svc.id;
      });
      resultEl.appendChild(row);
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
        resetAccountScopedState();
        await loadCredentials();
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
      `<td>${d.serial}</td><td>${d.mac || ""}</td><td>${d.device_type || ""}</td>` +
      `<td>${d.target_group || ""}</td><td>${d.target_site || ""}</td><td>${d.subscription_key || ""}</td>` +
      `<td>${d.hostname || ""}</td>` +
      `<td class="tick">${tick(d.added_to_glcp)}</td><td class="tick">${tick(d.subscription_assigned)}</td>` +
      `<td class="tick">${tick(d.service_assigned)}</td><td class="tick">${tick(d.preprovisioned)}</td>` +
      `<td class="tick">${tick(d.site_assigned)}</td><td class="tick">${tick(d.hostname_set)}</td>`;
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
      hostname: document.getElementById("addHostname").value.trim(),
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
    let html = "";
    if (result.add_device.missing_mac && result.add_device.missing_mac.length) {
      html += `<p class="save-note error">Skipped (no MAC): ${result.add_device.missing_mac.join(", ")}</p>`;
    }
    html += `<div class="result-block">${renderResultsBlock(resultEl, "Add to GLCP", result.add_device)}\n\n${renderResultsBlock(resultEl, "Assign Service", result.service)}\n\n${renderResultsBlock(resultEl, "Assign Subscription", result.subscription)}</div>`;
    const pp = result.preprovision;
    if (pp) {
      html += pp.skipped
        ? `<p class="save-note">Pre-Provision skipped: ${pp.skipped}</p>`
        : `<p class="save-note ${pp.failed ? "error" : "ok"}">Pre-Provision: provisioned ${pp.provisioned}, failed ${pp.failed}.</p>`;
    }
    resultEl.innerHTML = html;
    loadWorkspace();
    loadDevices();
  });
}

function parseIdentifiers(value) {
  return value.split(",").map((s) => s.trim()).filter(Boolean);
}

function wireManualAddToGlcp() {
  document.getElementById("manualAddToGlcpBtn").addEventListener("click", async () => {
    const resultEl = document.getElementById("manualGlcpResult");
    const pullFromCsv = document.getElementById("manualGlcpPullFromCsv").checked;

    let result;
    if (pullFromCsv) {
      resultEl.textContent = "Running...";
      result = await api().run_add_to_glcp();
    } else {
      const serials = parseIdentifiers(document.getElementById("manualGlcpSerials").value);
      const macs = parseIdentifiers(document.getElementById("manualGlcpMacs").value);
      if (!serials.length || !macs.length) {
        resultEl.innerHTML = '<p class="save-note error">Serial(s) and MAC(s) are required.</p>';
        return;
      }
      result = await api().add_devices_to_glcp(serials, macs);
    }

    resultEl.innerHTML = result.error
      ? `<p class="save-note error">${result.error}</p>`
      : `<div class="result-block">${renderResultsBlock(resultEl, "Add to GLCP", result)}</div>`;
    loadDevices();
  });
}

function wireManualSubscription() {
  document.getElementById("manualAssignSubBtn").addEventListener("click", async () => {
    const resultEl = document.getElementById("manualSubResult");
    const pullFromCsv = document.getElementById("manualSubPullFromCsv").checked;

    let result;
    if (pullFromCsv) {
      resultEl.textContent = "Running...";
      result = await api().run_assign_subscription();
    } else {
      const identifiers = parseIdentifiers(document.getElementById("manualSubIdentifiers").value);
      const key = document.getElementById("manualSubKey").value.trim();
      if (!identifiers.length || !key) {
        resultEl.innerHTML = '<p class="save-note error">Serial(s)/MAC(s) and Subscription Key are required.</p>';
        return;
      }
      result = await api().assign_subscription(identifiers, key);
    }

    resultEl.innerHTML = result.error
      ? `<p class="save-note error">${result.error}</p>`
      : `<div class="result-block">${renderResultsBlock(resultEl, "Assign Subscription", result)}</div>`;
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
    const resultEl = document.getElementById("manualServiceResult");
    const pullFromCsv = document.getElementById("manualServicePullFromCsv").checked;

    let result;
    if (pullFromCsv) {
      resultEl.textContent = "Running...";
      result = await api().run_assign_service();
    } else {
      const identifiers = parseIdentifiers(document.getElementById("manualServiceIdentifiers").value);
      const appId = document.getElementById("manualServiceAppId").value.trim() || null;
      if (!identifiers.length) {
        resultEl.innerHTML = '<p class="save-note error">Serial(s)/MAC(s) are required.</p>';
        return;
      }
      result = await api().assign_service(identifiers, appId);
    }

    resultEl.innerHTML = result.error
      ? `<p class="save-note error">${result.error}</p>`
      : `<div class="result-block">${renderResultsBlock(resultEl, "Assign Service", result)}</div>`;
    loadDevices();
  });

  document.getElementById("manualRemoveServiceBtn").addEventListener("click", async () => {
    const identifiers = parseIdentifiers(document.getElementById("manualServiceIdentifiers").value);
    const resultEl = document.getElementById("manualServiceResult");
    if (!identifiers.length) {
      resultEl.innerHTML = '<p class="save-note error">Serial(s)/MAC(s) are required.</p>';
      return;
    }
    const result = await api().remove_service(identifiers);
    resultEl.innerHTML = `<div class="result-block">${renderResultsBlock(resultEl, "Remove Service", result)}</div>`;
    loadDevices();
  });
}

// --- pre-provision ---------------------------------------------------------

function wireManualPreprovision() {
  document.getElementById("manualPreprovisionBtn").addEventListener("click", async () => {
    const resultEl = document.getElementById("manualPreprovisionResult");
    const pullFromCsv = document.getElementById("manualPreprovisionPullFromCsv").checked;

    let result;
    if (pullFromCsv) {
      resultEl.textContent = "Running...";
      result = await api().preprovision();
    } else {
      const identifiers = parseIdentifiers(document.getElementById("manualPreprovisionIdentifiers").value);
      const group = document.getElementById("manualPreprovisionGroup").value.trim();
      if (!identifiers.length || !group) {
        resultEl.innerHTML = '<p class="save-note error">Serial(s)/MAC(s) and Group are required.</p>';
        return;
      }
      result = await api().preprovision_manual(identifiers, group);
    }

    resultEl.innerHTML = result.error
      ? `<p class="save-note error">${result.error}</p>`
      : `<p class="save-note ${result.failed ? "error" : "ok"}">Provisioned ${result.provisioned}, failed ${result.failed}.</p>`;
    loadDevices();
  });
}

function wireCheckStatus() {
  document.getElementById("checkFullStatusBtn").addEventListener("click", async () => {
    const identifier = document.getElementById("checkStatusSerial").value.trim();
    const resultEl = document.getElementById("checkStatusResult");
    if (!identifier) return;
    resultEl.textContent = "Checking...";
    const result = await api().check_full_status(identifier);
    if (!result.ok) {
      resultEl.innerHTML = `<p class="save-note error">${result.error}</p>`;
      return;
    }
    const g = result.glcp || {};
    const c = result.classic || {};
    let glcpLine;
    if (g.skipped) glcpLine = `GLCP: skipped (${g.skipped})`;
    else if (g.error) glcpLine = `GLCP: error (${g.error})`;
    else if (!g.in_glcp) glcpLine = "GLCP: not added";
    else {
      const sub = g.subscription_tier ? `${g.subscription_tier}${g.subscription_end ? " until " + g.subscription_end : ""}` : "(none)";
      glcpLine = `GLCP: added, Service: ${g.service_assigned ? "assigned" : "not assigned"}, Subscription: ${sub}`;
    }
    let classicLine;
    if (c.skipped) classicLine = `Classic Central: skipped (${c.skipped})`;
    else if (c.error) classicLine = `Classic Central: error (${c.error})`;
    else if (!c.checked_in) classicLine = "Classic Central: not seen yet - hasn't checked into Central";
    else classicLine = `Classic Central${c.device_type ? ` (${c.device_type})` : ""}: Status ${c.status}, Group: ${c.group || "(none)"}, Site: ${c.site || "(none)"}`;
    resultEl.innerHTML = `<p class="save-note">${glcpLine}</p><p class="save-note">${classicLine}</p>`;
  });
}

// --- set hostname (Post Onboard) ---------------------------------------

function wireManualSetHostname() {
  document.getElementById("manualSetHostnameBtn").addEventListener("click", async () => {
    const resultEl = document.getElementById("manualSetHostnameResult");
    const pullFromCsv = document.getElementById("manualHostnamePullFromCsv").checked;
    const classic = document.getElementById("manualHostnameClassic").checked;

    let result;
    if (pullFromCsv) {
      resultEl.textContent = "Running...";
      result = await api().run_set_hostname(classic);
    } else {
      const serials = parseIdentifiers(document.getElementById("manualHostnameSerials").value);
      const hostnames = parseIdentifiers(document.getElementById("manualHostnameNames").value);
      if (!serials.length || !hostnames.length) {
        resultEl.innerHTML = '<p class="save-note error">Serial(s) and Hostname(s) are required.</p>';
        return;
      }
      resultEl.textContent = "Running...";
      result = await api().set_hostname_manual(serials, hostnames, classic);
    }

    resultEl.innerHTML = result.error
      ? `<p class="save-note error">${result.error}</p>`
      : `<div class="result-block">${renderResultsBlock(resultEl, classic ? "Set Hostname (Classic Central)" : "Set Hostname (New Central)", result)}</div>`;
    loadDevices();
  });
}

// --- assign site -------------------------------------------------------

function renderAssignSiteResult(resultEl, result) {
  if (result.error) {
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
}

function wireManualAssignSite() {
  document.getElementById("manualAssignSiteBtn").addEventListener("click", async () => {
    const resultEl = document.getElementById("manualAssignSiteResult");
    const pullFromCsv = document.getElementById("manualSitePullFromCsv").checked;

    let result;
    if (pullFromCsv) {
      resultEl.textContent = "Running...";
      result = await api().assign_site();
    } else {
      const identifiers = parseIdentifiers(document.getElementById("manualSiteSerials").value);
      const deviceType = document.getElementById("manualSiteDeviceType").value;
      const siteName = document.getElementById("manualSiteName").value.trim();
      if (!identifiers.length || !siteName) {
        resultEl.innerHTML = '<p class="save-note error">Serial(s) and Site Name are required.</p>';
        return;
      }
      result = await api().assign_site_manual(identifiers, deviceType, siteName);
    }

    renderAssignSiteResult(resultEl, result);
    loadDevices();
  });

  document.getElementById("pullClassicSitesBtn").addEventListener("click", async () => {
    const resultEl = document.getElementById("manualAssignSiteResult");
    const result = await api().get_classic_sites();
    if (!result.ok) {
      resultEl.innerHTML = `<p class="save-note error">${result.error}</p>`;
      return;
    }
    const datalist = document.getElementById("manualSiteOptions");
    datalist.innerHTML = "";
    result.sites.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      datalist.appendChild(option);
    });
    resultEl.innerHTML = `<p class="save-note ok">Pulled ${result.sites.length} site(s) from Classic Central.</p>`;
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

// --- subscriptions (Tools) -------------------------------------------------

// Last pull, kept so the Show expired / Show fully used checkboxes can
// re-filter without calling GreenLake again. Cleared on account switch.
let pulledSubscriptions = null;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function renderSubscriptions() {
  const wrap = document.getElementById("subscriptionsGridWrap");
  const body = document.getElementById("subscriptionsGridBody");
  const note = document.getElementById("subscriptionsResult");
  body.innerHTML = "";
  if (!pulledSubscriptions) {
    wrap.hidden = true;
    return;
  }
  const showExpired = document.getElementById("subsShowExpired").checked;
  const showUsedUp = document.getElementById("subsShowUsedUp").checked;
  const afterToggles = pulledSubscriptions.filter(
    (s) => (showExpired || !s.expired) && (showUsedUp || !s.used_up)
  );
  // Category options come from what the checkboxes leave; Type options
  // additionally narrow to the chosen Category.
  const category = fillFilterSelect("subsFilterCategory", afterToggles.map((s) => s.label));
  const inCategory = afterToggles.filter((s) => !category || s.label === category);
  const type = fillFilterSelect("subsFilterType", inCategory.map((s) => s.type));
  const visible = inCategory.filter((s) => !type || s.type === type);

  const hidden = pulledSubscriptions.length - visible.length;
  note.className = "save-note";
  note.textContent = `${visible.length} shown` + (hidden ? `, ${hidden} hidden by the filters` : "") + ".";
  if (visible.length === 0) {
    body.innerHTML = '<tr><td colspan="6" class="fine-print">No subscriptions match these filters.</td></tr>';
  }
  visible.forEach((s) => {
    const tr = document.createElement("tr");
    const status = s.expired ? " (expired)" : "";
    tr.innerHTML =
      `<td class="mono">${escapeHtml(s.key)}</td><td>${escapeHtml(s.label)}</td><td>${escapeHtml(s.type)}</td>` +
      `<td>${s.available}/${s.quantity}</td><td>${escapeHtml(s.end_date)}${status}</td>` +
      `<td>${s.is_eval ? "Eval" : ""}</td>`;
    body.appendChild(tr);
  });
  wrap.hidden = false;
}

// Rebuilds a column-filter <select> from the given values ("All" +
// each distinct value, sorted), keeping the current choice if it's
// still offered. Returns the effective selection ("" = All).
function fillFilterSelect(id, values) {
  const select = document.getElementById(id);
  const current = select.value;
  const options = [...new Set(values.filter(Boolean))].sort();
  select.innerHTML = '<option value="">All</option>';
  options.forEach((v) => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    select.appendChild(opt);
  });
  select.value = options.includes(current) ? current : "";
  return select.value;
}

function wireSubscriptions() {
  document.getElementById("pullSubscriptionsBtn").addEventListener("click", async () => {
    const note = document.getElementById("subscriptionsResult");
    note.className = "save-note";
    note.textContent = "Pulling...";
    const result = await api().list_subscriptions();
    if (!result.ok) {
      pulledSubscriptions = null;
      renderSubscriptions();
      note.className = "save-note error";
      note.textContent = result.error;
      return;
    }
    pulledSubscriptions = result.subscriptions;
    renderSubscriptions();
  });
  document.getElementById("subsShowExpired").addEventListener("change", renderSubscriptions);
  document.getElementById("subsShowUsedUp").addEventListener("change", renderSubscriptions);
  document.getElementById("subsFilterCategory").addEventListener("change", renderSubscriptions);
  document.getElementById("subsFilterType").addEventListener("change", renderSubscriptions);
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
  wireAccountPicker();
  wireAddAccount();
  wireDeleteAccount();
  wireHintToggles();
  wireRevealToggles();
  wireSaveButtons();
  wireTestAll();
  wireTestButtons();
  wireWipeButtons();
  wireListGlcpServices();
  wireWipeAllCredentials();
  wireConfirmModal();
  wireRefreshDevices();
  wireAddDevice();
  wireDownloadCsvTemplate();
  wireImportCsv();
  wireLoadDestinations();
  wireRunOnboardBatch();
  wireManualAddToGlcp();
  wireManualSubscription();
  wireManualService();
  wireManualPreprovision();
  wireCheckStatus();
  wireManualAssignSite();
  wireManualSetHostname();
  wireCreateSite();
  wireSubscriptions();
  wireResetToDefault();

  await loadVersion();
  await loadWorkspace();
  await loadCredentials();
  await loadHints();
}

window.addEventListener("pywebviewready", init);
