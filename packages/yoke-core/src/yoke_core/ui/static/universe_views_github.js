// The GitHub screen: how one project binds to its repository, and how they
// sync — exactly as the engine attests it. One read
// (`projects.github_binding.status`) serves every panel: the binding row,
// the App installation behind it, the permission and automation verdicts,
// and the durable sync receipts. Every status word and reason on screen is
// a served string — this module colors through the shared pill families and
// never judges. The local server exposes no web-callable GitHub write, so
// nothing here is a control: the sync mode renders as read-only text, and an
// unbound project gets an explanation rather than a dead button.

import {
  el,
  loadSection,
  section,
  statePill,
} from "./universe_view_support.js";

// A label/value grid in the item-detail kv dress. A row may render its
// value as a state pill (coloring hint only) or as a `code` element
// (copyable identifier, never a button); a row marked `optional` with an
// empty value does not render at all — a permanently blank "last error"
// line would be noise, not honesty.
function factsTable(documentNode, rows) {
  const table = el(documentNode, "table", "items kv");
  for (const row of rows) {
    const text = String(row.value ?? "");
    if (!text && row.optional) continue;
    const tr = el(documentNode, "tr");
    tr.appendChild(el(documentNode, "th", null, row.label));
    const cell = el(documentNode, "td");
    if (row.pill) {
      const pill = statePill(documentNode, text);
      if (pill) cell.appendChild(pill);
    } else if (row.code) {
      if (text) cell.appendChild(el(documentNode, "code", null, text));
    } else {
      cell.textContent = text;
    }
    tr.appendChild(cell);
    table.appendChild(tr);
  }
  return table;
}

// What a binding is and that this project has none. The explanation is the
// whole affordance: no web-callable bind exists on this read-only surface,
// so no button pretends one does.
function renderUnboundState(body, result) {
  const documentNode = body.ownerDocument;
  body.appendChild(el(
    documentNode, "p", "empty",
    "A repository binding connects this project to one GitHub repository " +
      "through a GitHub App installation — it is what lets Yoke read and " +
      "sync that repository on the project's behalf. This project has no " +
      "binding.",
  ));
  // A project record naming a repo without a binding behind it is a fact
  // worth surfacing, not smoothing over.
  if (result.github_repo) {
    const line = el(
      documentNode, "p", "fact-line", "The project record names ",
    );
    line.appendChild(el(documentNode, "code", null, result.github_repo));
    line.appendChild(el(
      documentNode, "span", null, " without a live binding behind it.",
    ));
    body.appendChild(line);
  }
}

function renderBindingFacts(body, result) {
  const binding = result.binding || {};
  body.appendChild(factsTable(body.ownerDocument, [
    { label: "repository", value: binding.github_repo, code: true },
    { label: "default branch", value: binding.default_branch },
    { label: "api origin", value: binding.api_url, code: true },
    { label: "status", value: binding.status, pill: true },
    // A NULL verification stamp reads as the word "never" —
    // bound-but-never-verified is a fact, not a blank.
    { label: "last verified", value: binding.last_verified_at || "never" },
    { label: "last error", value: binding.last_error, optional: true },
  ]));
}

function renderInstallationFacts(body, result) {
  const documentNode = body.ownerDocument;
  const installation = result.installation;
  if (!installation) {
    const binding = result.binding || {};
    body.appendChild(el(
      documentNode, "p", "empty",
      binding.installation_id
        ? `the binding names installation ${binding.installation_id}, ` +
          "but no installation record backs it"
        : "no installation record backs this binding",
    ));
    return;
  }
  body.appendChild(factsTable(documentNode, [
    { label: "account", value: installation.account_login },
    { label: "account type", value: installation.account_type },
    { label: "installation", value: installation.installation_id, code: true },
    { label: "api origin", value: installation.api_url, code: true },
    { label: "repository access", value: installation.repository_selection },
    { label: "status", value: installation.status, pill: true },
    { label: "last verified", value: installation.last_verified_at || "never" },
    { label: "last error", value: installation.last_error, optional: true },
  ]));
}

// The engine's two verdicts, verbatim: the permission check against the
// App's required repository permissions, and whether automation may act.
// The reason is a served token and renders as text, never re-derived here.
function renderAccessFacts(body, result) {
  const documentNode = body.ownerDocument;
  const permissionInfo = result.permission_status || {};
  const automation = result.automation || {};
  const missing = Array.isArray(permissionInfo.missing)
    ? permissionInfo.missing : [];
  body.appendChild(factsTable(documentNode, [
    { label: "permissions", value: permissionInfo.status, pill: true },
    { label: "missing", value: missing.join(", "), optional: true },
    {
      label: "automation",
      value: automation.available ? "available" : "unavailable",
      pill: true,
    },
    { label: "reason", value: automation.reason },
  ]));
  if (permissionInfo.hint) {
    body.appendChild(el(documentNode, "p", "fact-line", permissionInfo.hint));
  }
}

// The stored sync mode plus the durable receipt of the last project-scoped
// GitHub automation run. The mode is the project's setting rendered as
// read-only text: no web-callable write exists on this surface, so no
// control here could change it — and none pretends to.
function renderSyncFacts(body, result) {
  const documentNode = body.ownerDocument;
  const binding = result.binding || {};
  const rows = [{ label: "sync mode", value: result.github_sync_mode }];
  if (binding.last_sync_at) {
    rows.push(
      { label: "last sync", value: binding.last_sync_at },
      { label: "outcome", value: binding.last_sync_outcome, pill: true },
      { label: "error", value: binding.last_sync_error, optional: true },
    );
  }
  body.appendChild(factsTable(documentNode, rows));
  if (!binding.last_sync_at) {
    body.appendChild(el(
      documentNode, "p", "empty",
      "no sync receipt yet — no project-scoped GitHub automation has " +
        "recorded a terminal outcome",
    ));
  }
}

export function renderGithubView(context, main, scope) {
  const documentNode = context.document;
  const bindingPanel = section(documentNode, "Repository binding");
  main.replaceChildren(bindingPanel);
  loadSection(
    context, bindingPanel,
    "projects.github_binding.status",
    { project: scope },
    (body, callResult) => {
      const result = callResult.envelope.result || {};
      if (!result.bound) {
        renderUnboundState(body, result);
        return;
      }
      renderBindingFacts(body, result);
      // The remaining panels are facets of the same read: each shows the
      // one envelope behind its raw-JSON toggle. They exist only for a
      // bound project — an unbound one has no installation, no permission
      // verdict, and no receipts to stand a panel on.
      for (const [title, renderFacts] of [
        ["App installation", renderInstallationFacts],
        ["Permissions & automation", renderAccessFacts],
        ["Sync", renderSyncFacts],
      ]) {
        const panel = section(documentNode, title);
        main.appendChild(panel);
        panel.renderEnvelope(
          callResult, (panelBody) => renderFacts(panelBody, result),
        );
      }
    },
  );
}
