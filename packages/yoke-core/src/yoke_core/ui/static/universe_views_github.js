// The GitHub screen is one page in every mode. Installations come from the
// project binding-status fan-out and the hosted shell's organization
// list when it passes one (an organization can hold installations no
// project is bound to yet). Bound installations remain visible in both lists. Hosted universes apply GitHub webhooks as they
// arrive, so their installation facts are live; local and self-hosted ones
// have no webhook delivery, so each row says when it was last checked and
// Check now re-verifies every bound project in scope. Personal
// authorization renders only when the mount packet carries it, and project
// mappings come from the same fan-out. No row ever reads "unavailable": a
// fact the page cannot read is not shown.

import { relativeAgePhrase } from "./universe_time.js";
import {
  callFunction,
  el,
  loadScopedPanels,
  portabilityMode,
  renderTable,
  scopeBuckets,
  section,
} from "./universe_view_support.js";
import {
  actionButton,
  githubHost,
  isAction,
  personalPanel,
  statusLine,
} from "./universe_views_github_access.js";

import { projectLabel, renderMappings } from "./universe_views_github_mappings.js";

const TITLE_INSTALLATIONS = "GitHub App installations";
const TITLE_MAPPINGS = "Project mappings with issue-sync";
const CHECK_FUNCTION = "projects.github_binding.check";

function statusResult(callResult) {
  return callResult.envelope.result || {};
}

function boundInstallationRows(callResults) {
  const rows = new Map();
  for (const callResult of callResults) {
    const result = statusResult(callResult);
    const binding = result.binding || {};
    const installation = result.installation;
    const id = String((installation && installation.installation_id)
      || binding.installation_id || "");
    if (!result.bound || !id) continue;
    const existing = rows.get(id);
    if (existing) {
      existing.boundProjects += 1;
      continue;
    }
    rows.set(id, {
      installationId: id,
      accountLogin: installation ? installation.account_login : "",
      accountType: installation ? installation.account_type : "",
      status: installation ? installation.status : "",
      repositorySelection: installation
        ? installation.repository_selection : "",
      lastCheckedAt: installation
        ? installation.last_verified_at : binding.last_verified_at,
      settingsUrl: installation ? installation.settings_url || "" : "",
      missingPermissions: [],
      boundProjects: 1,
      dangling: !installation,
    });
  }
  return [...rows.values()];
}

function hostInstallationRows(installations, boundRows) {
  const rows = installations.map((row) => ({
    installationId: String(row.installationId || ""),
    accountLogin: String(row.accountLogin || ""),
    accountType: String(row.accountType || ""),
    status: String(row.status || ""),
    repositorySelection: String(row.repositorySelection || ""),
    lastCheckedAt: null,
    settingsUrl: String(row.settingsUrl || ""),
    missingPermissions: Array.isArray(row.missingPermissions)
      ? row.missingPermissions.map(String) : [],
    boundProjects: boundRows.find((bound) => bound.installationId ===
      String(row.installationId))?.boundProjects || 0,
    dangling: false,
  }));
  const listed = new Set(rows.map((row) => row.installationId));
  return [
    ...rows,
    ...boundRows.filter((row) => !listed.has(row.installationId))
      .map((row) => ({ ...row, hostMissing: true })),
  ];
}

function installationStatusDetail(row) {
  if (row.hostMissing) {
    return "bound in this universe, but absent from the hosted installation list";
  }
  if (row.dangling) {
    return `the binding names installation ${row.installationId}, ` +
      "but no installation record backs it";
  }
  return row.missingPermissions.length
    ? `missing: ${row.missingPermissions.join(", ")}` : "";
}

function freshnessColumn(hosted) {
  if (hosted) {
    return { label: "updates", value: () => "live", pill: true };
  }
  return {
    label: "last checked",
    value: (row) => (row.lastCheckedAt
      ? relativeAgePhrase(row.lastCheckedAt) : "never"),
    sub: (row) => row.lastCheckedAt || "",
  };
}

function accessColumn(documentNode, host, status) {
  const detach = isAction(host.detachInstallation)
    ? host.detachInstallation : null;
  return {
    label: "repository access",
    value: () => "",
    render(row, cell) {
      const actions = el(documentNode, "div", "capability-actions");
      if (row.settingsUrl) {
        const link = el(
          documentNode, "a", "capability-action", "Manage on GitHub ↗",
        );
        link.href = row.settingsUrl;
        link.target = "_blank";
        link.rel = "noreferrer";
        actions.appendChild(link);
      }
      if (detach) {
        actions.appendChild(actionButton(documentNode, detach, status, {
          option: { id: row.installationId, label: "Detach" },
          disabledReason: row.boundProjects > 0
            ? "Remove this installation's project mappings before detaching it"
            : "",
        }));
      }
      if (actions.children.length) cell.appendChild(actions);
    },
  };
}

function renderInstallations(body, rows, options) {
  renderTable(body, rows, [
    {
      label: "account",
      value: (row) => row.accountLogin,
      sub: (row) => row.accountType,
    },
    { label: "installation", value: (row) => row.installationId, code: true },
    {
      label: "status",
      value: (row) => row.status,
      pill: true,
      sub: installationStatusDetail,
    },
    { label: "repositories", value: (row) => row.repositorySelection },
    { label: "bound projects", value: (row) => String(row.boundProjects) },
    freshnessColumn(options.hosted),
    accessColumn(body.ownerDocument, options.host, options.status),
  ], "no GitHub App installation backs a project in this scope");
}

function bindingCalls(buckets) {
  return buckets.map((project) => ({
    functionId: "projects.github_binding.status",
    payload: { project: String(project) },
  }));
}

function checkFailureText(projects, project, callResult) {
  const error = callResult.envelope?.error || {};
  return [
    `${projectLabel(projects, project)}: ${error.message || "check failed"}`,
    error.recovery_hint || "",
  ].filter(Boolean).join(" ");
}

// Re-verifies every bound project in scope, then reloads the page's reads.
// Each failure keeps its own named reason and recovery on the status line.
async function checkNow(context, state) {
  const { button, status, projects } = state;
  const bound = state.boundProjects();
  button.disabled = true;
  status.hidden = false;
  status.className = "fact-line";
  status.textContent = `Checking ${bound.length} bound project` +
    `${bound.length === 1 ? "" : "s"} with GitHub…`;
  const results = await Promise.all(bound.map(async (project) => {
    try {
      return await callFunction(
        context.client, CHECK_FUNCTION, { project: String(project) },
      );
    } catch (error) {
      return {
        status: 0,
        envelope: { success: false, error: { message: String(error) } },
      };
    }
  }));
  if (!context.isMounted()) return;
  const failures = results
    .map((callResult, index) => [bound[index], callResult])
    .filter(([, callResult]) => !(
      callResult.status === 200 && callResult.envelope.success
    ));
  status.className = failures.length ? "error" : "fact-line";
  status.setAttribute("role", failures.length ? "alert" : "status");
  status.textContent = failures.length
    ? failures.map(([project, callResult]) => checkFailureText(
      projects, project, callResult,
    )).join(" · ")
    : `Checked ${bound.length} bound project` +
      `${bound.length === 1 ? "" : "s"} with GitHub.`;
  await state.load();
}

function attachCheckNow(context, panel, state) {
  const documentNode = context.document;
  const button = el(documentNode, "button", "capability-action", "Check now");
  button.type = "button";
  button.disabled = true;
  button.addEventListener("click", () => { checkNow(context, state); });
  const [header, body] = panel.children;
  header.appendChild(button);
  panel.insertBefore(state.status, body);
  state.button = button;
}

export function renderGithubView(context, main, scope) {
  const documentNode = context.document;
  const hosted = portabilityMode(context.capabilities) === "hosted";
  const host = githubHost(context.capabilities);
  const projects = context.projects();
  const buckets = scopeBuckets(scope, projects, true);
  const allBuckets = scopeBuckets("all", projects, true);
  const installations = section(documentNode, TITLE_INSTALLATIONS);
  const mappings = section(documentNode, TITLE_MAPPINGS);
  const personal = personalPanel(documentNode, context.capabilities, hosted);
  main.replaceChildren(
    ...[installations, personal, mappings].filter(Boolean),
  );
  let latest = [];
  const state = {
    status: statusLine(documentNode),
    mappingStatus: statusLine(documentNode),
    projects,
    button: null,
    boundProjects: () => latest
      .map((callResult, index) => [allBuckets[index], statusResult(callResult)])
      .filter(([project, result]) => buckets.includes(project) && result.bound)
      .map(([project]) => project),
  };
  mappings.insertBefore(state.mappingStatus, mappings.children[1]);
  state.load = () => loadScopedPanels(context, [
    [installations, (body, callResults) => {
      latest = callResults;
      const boundRows = boundInstallationRows(callResults);
      const rows = hosted && Array.isArray(host.installations)
        ? hostInstallationRows(host.installations, boundRows) : boundRows;
      renderInstallations(body, rows, {
        hosted, host, status: state.status,
      });
      if (state.button) {
        const bound = state.boundProjects().length;
        state.button.disabled = bound === 0;
        state.button.title = bound === 0
          ? "No project in this scope is bound to a GitHub repository" : "";
      }
    }],
    [mappings, (body, callResults) => renderMappings(
      context, body, callResults.filter((_, index) =>
        buckets.includes(allBuckets[index])), projects,
      allBuckets.filter((project) => buckets.includes(project)), state,
    )],
  ], bindingCalls(allBuckets));
  if (hosted) installations.insertBefore(state.status, installations.children[1]);
  else attachCheckNow(context, installations, state);
  state.load();
}
