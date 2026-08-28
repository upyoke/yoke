import { buildUniverseRoute } from "./universe_navigation.js";
import {
  el,
  statePill,
} from "./universe_view_support.js";
import {
  machinePanel as panel,
  machineRelativeAge as relativeAge,
} from "./test_machine_view_primitives.js";
import {
  machineSecretNotes as secretNotes,
  orderedMachineSecrets,
} from "./test_machine_settings_dialog.js";

export function secretPanel(documentNode, detail) {
  const built = panel(documentNode, "Credential references");
  built.header.appendChild(el(
    documentNode,
    "span",
    "panel-hint",
    "presence only · values never render",
  ));
  for (const secret of orderedMachineSecrets(detail.secrets)) {
    const row = el(documentNode, "div", "secret test-machine-secret");
    const copy = el(documentNode, "div");
    copy.appendChild(el(
      documentNode,
      "strong",
      "mono secret-key",
      secret.key,
    ));
    copy.appendChild(el(
      documentNode,
      "small",
      "secret-note",
      secretNotes[secret.key] || "runner-only credential",
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
      title: "SSH + runner materialization",
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

function availabilityState(detail) {
  const verification = detail.verification || {};
  if (verification.status === "error") return "error";
  if (verification.status !== "verified") return "configured (unverified)";
  return detail.active_lease ? "in use" : "ready";
}

function leaseIdentity(active) {
  if (!active) return "none";
  if (active.item?.ref) return active.item.ref;
  return "active execution";
}

function methodAvailabilityState(detail) {
  const verification = detail.verification || {};
  if (verification.status === "error") return "error";
  if (verification.status !== "verified") return "configured (unverified)";
  return "ready";
}

export function availabilityPanel(documentNode, detail) {
  const built = panel(documentNode, "Availability");
  built.body.classList.add("stack");
  built.body.classList.add("test-machine-availability-body");
  const active = detail.active_lease;
  const receiptRows = semanticReceiptRows(detail);
  const stateRow = el(
    documentNode, "div", "lease test-machine-availability-state",
  );
  const state = statePill(documentNode, availabilityState(detail));
  if (state) stateRow.appendChild(state);
  if (active) {
    const meter = el(documentNode, "span", "bar test-machine-lease-bar");
    meter.appendChild(el(documentNode, "i"));
    stateRow.appendChild(meter);
    stateRow.appendChild(el(
      documentNode,
      "span",
      "muted",
      `${leaseIdentity(active)} · ${relativeAge(active.acquired_at)}`,
    ));
  }
  built.body.appendChild(stateRow);
  const stats = el(
    documentNode,
    "div",
    "mini-grid test-machine-stats",
  );
  for (const [label, value] of [
    ["Concurrency", "1 · serial per machine"],
    [
      "Active lease",
      active
        ? `${leaseIdentity(active)} · ${relativeAge(active.acquired_at)}`
        : "none",
    ],
    [
      "Health",
      `${receiptRows.filter((row) => row.ok).length} / 3 checks`,
    ],
  ]) {
    const card = el(documentNode, "div", "mini test-machine-stat");
    card.appendChild(el(documentNode, "div", "mh", label));
    card.appendChild(el(documentNode, "div", "mv", value));
    stats.appendChild(card);
  }
  built.body.appendChild(stats);
  return built.root;
}

export function methodsPanel(documentNode, detail) {
  const built = panel(documentNode, "Used by methods");
  built.body.classList.add("stack");
  built.body.classList.add("test-machine-methods-body");
  for (const method of detail.methods || []) {
    const link = el(
      documentNode,
      "a",
      "doc-link test-machine-method",
    );
    link.href = buildUniverseRoute(
      "qa",
      String(detail.project_id),
      "methods",
      method.id,
    );
    link.appendChild(el(
      documentNode,
      "span",
      "cc-ico test-machine-method-icon",
      method.id === "terminal-check" ? "⌨"
        : method.id === "terminal-inspection" ? "⌘" : "≡",
    ));
    const copy = el(
      documentNode,
      "span",
      "dl-main test-machine-method-copy",
    );
    copy.appendChild(el(
      documentNode,
      "strong",
      "dl-title",
      method.name,
    ));
    copy.appendChild(el(
      documentNode,
      "small",
      "dl-sub",
      `Pack-registered · ${method.source_ref || "machine-qa"}`,
    ));
    link.appendChild(copy);
    const ready = statePill(documentNode, methodAvailabilityState(detail));
    if (ready) link.appendChild(ready);
    built.body.appendChild(link);
  }
  return built.root;
}

export function receiptPanel(documentNode, detail) {
  const built = panel(documentNode, "Verification receipt");
  built.body.classList.add("timeline");
  built.body.classList.add("test-machine-receipt-body");
  const rows = semanticReceiptRows(detail);
  for (const receipt of rows) {
    const row = el(documentNode, "div", "tl test-machine-check");
    row.appendChild(el(
      documentNode,
      "span",
      "tl-dot timeline-dot",
    ));
    const copy = el(documentNode, "div", "test-machine-check-copy");
    copy.appendChild(el(
      documentNode,
      "strong",
      "tl-title",
      receipt.title,
    ));
    copy.appendChild(el(
      documentNode,
      "small",
      "tl-sub",
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
