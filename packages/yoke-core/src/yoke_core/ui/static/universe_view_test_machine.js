import {
  callFunction,
  el,
  renderError,
  statePill,
} from "./universe_view_support.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import {
  machineDefinitionList as definitionList,
  machinePanel as panel,
  machineRelativeAge as relativeAge,
  machineVerificationCallout as verificationCallout,
} from "./test_machine_view_primitives.js";
import {
  machineSecretNotes as secretNotes,
  machineSettingsDialog as settingsDialog,
} from "./test_machine_settings_dialog.js";

function secretPanel(documentNode, detail) {
  const built = panel(documentNode, "Credential references");
  built.header.appendChild(el(
    documentNode,
    "span",
    "panel-hint",
    "presence only · values never render",
  ));
  for (const secret of detail.secrets || []) {
    const row = el(documentNode, "div", "test-machine-secret");
    const copy = el(documentNode, "div");
    copy.appendChild(el(documentNode, "strong", "mono", secret.key));
    copy.appendChild(el(
      documentNode,
      "small",
      null,
      secretNotes[secret.key] || "executor-only credential",
    ));
    row.appendChild(copy);
    const pill = statePill(documentNode, secret.stored ? "stored" : "missing");
    if (pill) row.appendChild(pill);
    built.body.appendChild(row);
  }
  return built.root;
}

function semanticReceiptRows(detail) {
  const checks = detail.verification?.checks || [];
  const byName = new Map(checks.map((check) => [check.name, check]));
  const rows = [];
  const connection = byName.get("connection");
  if (connection) {
    rows.push({
      title: "SSH + executor materialization",
      detail: connection.ok
        ? "secret-free receipt"
        : connection.verified_property || "connection verification failed",
      ok: Boolean(connection.ok),
    });
  }
  const terminalBridge = byName.get("terminal_bridge");
  if (terminalBridge) {
    rows.push({
      title: "Terminal + screenshot bridge",
      detail: terminalBridge.ok
        ? "sample artifact discarded after verification"
        : terminalBridge.verified_property || "bridge verification failed",
      ok: Boolean(terminalBridge.ok),
    });
  }
  const baselineNames = detail.host_baselines || [];
  const baselineChecks = baselineNames
    .map((name) => byName.get(name))
    .filter(Boolean);
  if (baselineChecks.length) {
    const complete = baselineChecks.length === baselineNames.length;
    const ok = complete && baselineChecks.every((check) => check.ok);
    rows.push({
      title: "Host baselines reached + verified",
      detail: ok
        ? `${baselineNames.join(" · ")} — asserted the branch-determining state itself, never a proxy`
        : `${baselineNames.join(" · ")} — baseline verification incomplete or failed`,
      ok,
    });
  }
  return rows;
}

function availabilityPanel(documentNode, detail) {
  const built = panel(documentNode, "Availability");
  const active = detail.active_lease;
  const receiptRows = semanticReceiptRows(detail);
  const stateRow = el(
    documentNode, "div", "test-machine-availability-state",
  );
  const state = statePill(documentNode, active ? "in use" : "ready");
  if (state) stateRow.appendChild(state);
  if (active) {
    stateRow.appendChild(el(
      documentNode, "span", "test-machine-lease-bar",
    ));
    stateRow.appendChild(el(
      documentNode,
      "span",
      "muted",
      `${active.session_id} · ${relativeAge(active.acquired_at)}`,
    ));
  }
  built.body.appendChild(stateRow);
  const stats = el(documentNode, "div", "test-machine-stats");
  for (const [label, value] of [
    ["Concurrency", "1 · serial"],
    [
      "Active lease",
      active
        ? `${active.session_id} · ${relativeAge(active.acquired_at)}`
        : "none",
    ],
    [
      "Health",
      `${receiptRows.filter((row) => row.ok).length} / 3 checks`,
    ],
  ]) {
    const card = el(documentNode, "div", "test-machine-stat");
    card.appendChild(el(documentNode, "small", null, label));
    card.appendChild(el(documentNode, "strong", null, value));
    stats.appendChild(card);
  }
  built.body.appendChild(stats);
  return built.root;
}

function methodsPanel(documentNode, detail) {
  const built = panel(documentNode, "Used by methods");
  for (const method of detail.methods || []) {
    const link = el(documentNode, "a", "test-machine-method");
    link.href = buildUniverseRoute(
      "qa",
      String(detail.project_id),
      "methods",
    );
    link.appendChild(el(
      documentNode,
      "span",
      "test-machine-method-icon",
      method.id === "terminal-check" ? "⌨"
        : method.id === "terminal-inspection" ? "⌘" : "≡",
    ));
    const copy = el(documentNode, "span");
    copy.appendChild(el(documentNode, "strong", null, method.name));
    copy.appendChild(el(
      documentNode,
      "small",
      null,
      `Pack-registered · ${method.source_ref || "machine-qa"}`,
    ));
    link.appendChild(copy);
    const ready = statePill(documentNode, "ready");
    if (ready) link.appendChild(ready);
    built.body.appendChild(link);
  }
  return built.root;
}

function receiptPanel(documentNode, detail) {
  const built = panel(documentNode, "Verification receipt");
  const rows = semanticReceiptRows(detail);
  for (const receipt of rows) {
    const row = el(documentNode, "div", "test-machine-check");
    row.appendChild(el(documentNode, "span", "timeline-dot"));
    const copy = el(documentNode, "div");
    copy.appendChild(el(
      documentNode,
      "strong",
      null,
      receipt.title,
    ));
    copy.appendChild(el(
      documentNode,
      "small",
      null,
      receipt.detail,
    ));
    row.appendChild(copy);
    const result = statePill(documentNode, receipt.ok ? "pass" : "failed");
    if (result) row.appendChild(result);
    built.body.appendChild(row);
  }
  if (!rows.length) {
    built.body.appendChild(el(
      documentNode,
      "p",
      "empty",
      "Run verification to produce a secret-free receipt.",
    ));
  }
  return built.root;
}

function renderDetail(context, main, detail, reload) {
  const documentNode = context.document;
  const header = el(documentNode, "div", "test-machine-head");
  const copy = el(documentNode, "div");
  copy.appendChild(el(documentNode, "h2", null, "Test Mac"));
  copy.appendChild(el(
    documentNode,
    "p",
    "muted",
    `test-machine capability · composite · ${detail.project}`,
  ));
  header.appendChild(copy);
  const actions = el(documentNode, "div", "test-machine-actions");
  const edit = el(documentNode, "button", "btn", "Edit settings");
  edit.type = "button";
  edit.addEventListener("click", () => {
    const modal = settingsDialog(
      context,
      detail,
      () => main.removeChild(modal),
      reload,
    );
    main.appendChild(modal);
  });
  actions.appendChild(edit);
  const verify = el(documentNode, "button", "btn primary", "Verify now");
  verify.type = "button";
  verify.addEventListener("click", async () => {
    verify.disabled = true;
    const result = await callFunction(
      context.client,
      "test_machine.verify",
      { project: detail.project },
    );
    if (!result.envelope.success) {
      verify.disabled = false;
      renderError(main, result);
      return;
    }
    reload();
  });
  actions.appendChild(verify);
  header.appendChild(actions);
  const columns = el(documentNode, "div", "test-machine-columns");
  const left = el(documentNode, "div", "test-machine-stack");
  const connection = panel(documentNode, "Connection and behavior");
  connection.body.appendChild(definitionList(documentNode, [
    ["Resource name", detail.settings.resource_name],
    ["Host", detail.settings.host],
    ["User", detail.settings.user],
    ["Features", detail.features.join(" · ")],
    [
      "Host baselines",
      `${detail.host_baselines.join(" · ")} — registered operations on ${
        detail.executor_id
      }, run inside the lease; each verifies the branch-determining state it promises and emits that verification as evidence`,
    ],
    ["Operating notes", detail.settings.operating_notes],
  ]));
  left.appendChild(connection.root);
  left.appendChild(secretPanel(documentNode, detail));
  const right = el(documentNode, "div", "test-machine-stack");
  right.appendChild(availabilityPanel(documentNode, detail));
  right.appendChild(methodsPanel(documentNode, detail));
  right.appendChild(receiptPanel(documentNode, detail));
  columns.appendChild(left);
  columns.appendChild(right);
  main.replaceChildren(
    header,
    verificationCallout(documentNode, detail),
    columns,
  );
}

export async function renderTestMachineDetail(context, main, project) {
  const documentNode = context.document;
  const reload = () => renderTestMachineDetail(context, main, project);
  main.replaceChildren(el(documentNode, "p", "empty", "loading Test Mac…"));
  const result = await callFunction(
    context.client,
    "test_machine.get",
    { project },
  );
  if (!context.isMounted()) return;
  if (!result.envelope.success) {
    const message = result.envelope?.error?.message || "";
    if (message.includes("has no test-machine capability")) {
      const missing = panel(documentNode, "Test Mac");
      missing.body.appendChild(el(
        documentNode,
        "p",
        "empty",
        "Test Mac is not configured for this project.",
      ));
      const back = el(
        documentNode, "a", "btn", "Back to capabilities",
      );
      back.href = buildUniverseRoute("capabilities", project);
      missing.body.appendChild(back);
      main.replaceChildren(missing.root);
    } else {
      main.replaceChildren();
      renderError(main, result);
    }
    return;
  }
  renderDetail(context, main, result.envelope.result, reload);
}
