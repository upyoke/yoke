// The GitHub screen composes with a host beforeScope slot. Hosted universes
// already stand App installations and personal authorization above the
// picker; this view does not duplicate those. Local and self-host render
// all four sections: installations derived from binding-status reads (last
// verified is the attested stamp; there is no webhook column), personal
// authorization named unavailable because no product read exists, then the
// same project mappings and machine authentications. Mapping rows fan out
// `projects.github_binding.status`. Machine rows come from `machine.list`;
// GitHub account and authorization cells say unavailable — the registry
// does not carry those facts. Read-only: no web-callable GitHub write.

import { relativeAge } from "./universe_time.js";
import {
  el,
  loadSection,
  loadScopedPanels,
  portabilityMode,
  renderTable,
  scopeBuckets,
  section,
} from "./universe_view_support.js";

const TITLE_INSTALLATIONS = "GitHub App installations";
const TITLE_PERSONAL = "Personal GitHub authorization";
const TITLE_MAPPINGS = "Project mappings with issue-sync";
const TITLE_MACHINES = "Machine authentications";

function projectLabel(projects, projectId) {
  const row = projects.find((item) => String(item.id) === String(projectId));
  return (row && (row.name || row.slug)) || String(projectId);
}

function installationRows(callResults) {
  const seen = new Map();
  for (const callResult of callResults) {
    const result = callResult.envelope.result || {};
    const binding = result.binding || {};
    const installation = result.installation;
    const id = (installation && installation.installation_id)
      || binding.installation_id;
    if (!id || seen.has(String(id))) continue;
    seen.set(String(id), {
      installation_id: String(id),
      account_login: installation ? installation.account_login : "",
      account_type: installation ? installation.account_type : "",
      status: installation ? installation.status : "",
      last_verified_at: installation
        ? (installation.last_verified_at || "never")
        : (binding.last_verified_at || "never"),
      dangling: !installation,
    });
  }
  return [...seen.values()];
}

function mappingRows(callResults, projects, buckets) {
  return callResults.map((callResult, index) => {
    const result = callResult.envelope.result || {};
    const binding = result.binding || {};
    const permission = result.permission_status || {};
    const automation = result.automation || {};
    const missing = Array.isArray(permission.missing)
      ? permission.missing.join(", ") : "";
    return {
      project: projectLabel(projects, buckets[index]),
      repo: binding.github_repo || result.github_repo || "",
      status: binding.status || "",
      permissions: permission.status || "",
      missing,
      automation: Object.hasOwn(automation, "available")
        ? (automation.available ? "available" : "unavailable") : "",
      reason: automation.reason || "",
      sync_mode: result.github_sync_mode || "",
      last_sync: binding.last_sync_at || "",
      last_sync_outcome: binding.last_sync_outcome || "",
    };
  });
}

function renderPersonalUnavailable(body) {
  body.appendChild(el(
    body.ownerDocument, "p", "empty",
    "unavailable — this universe has no product read for a personal " +
      "GitHub account",
  ));
}

function renderInstallations(body, callResults) {
  renderTable(body, installationRows(callResults), [
    {
      label: "account",
      value: (row) => row.account_login,
      sub: (row) => row.account_type,
    },
    { label: "installation", value: (row) => row.installation_id, code: true },
    {
      label: "status",
      value: (row) => row.status,
      pill: true,
      sub: (row) => (row.dangling
        ? `the binding names installation ${row.installation_id}, ` +
          "but no installation record backs it"
        : ""),
    },
    { label: "last verified", value: (row) => row.last_verified_at },
  ], "no GitHub App installation backs a project in this scope");
}

function renderMappings(body, callResults, projects, buckets) {
  renderTable(body, mappingRows(callResults, projects, buckets), [
    { label: "project", value: (row) => row.project },
    { label: "repository", value: (row) => row.repo, code: true },
    { label: "binding", value: (row) => row.status, pill: true },
    {
      label: "permissions",
      value: (row) => row.permissions,
      pill: true,
      sub: (row) => row.missing,
    },
    {
      label: "automation",
      value: (row) => row.automation,
      pill: true,
      sub: (row) => row.reason,
    },
    {
      label: "issue sync",
      value: (row) => row.sync_mode,
      pill: true,
      sub: (row) => (row.last_sync
        ? `${row.last_sync_outcome} · ${row.last_sync}` : ""),
    },
  ], "no projects in this scope");
}

function renderMachines(body, result) {
  const machines = Array.isArray(result.machines) ? result.machines : [];
  renderTable(body, machines, [
    {
      label: "machine",
      value: (row) => row.name,
      sub: (row) => (row.last_seen_at
        ? `seen ${relativeAge(row.last_seen_at)} ago` : ""),
    },
    { label: "GitHub account", value: () => "unavailable", pill: true },
    { label: "authorization", value: () => "unavailable", pill: true },
  ], "no machines registered");
}

function bindingCalls(buckets) {
  return buckets.map((project) => ({
    functionId: "projects.github_binding.status",
    payload: { project: String(project) },
  }));
}

export function renderGithubView(context, main, scope) {
  const documentNode = context.document;
  const hosted = portabilityMode(context.capabilities) === "hosted";
  const projects = context.projects();
  const buckets = scopeBuckets(scope, projects, true);
  const installations = section(documentNode, TITLE_INSTALLATIONS);
  const personal = section(documentNode, TITLE_PERSONAL);
  const mappings = section(documentNode, TITLE_MAPPINGS);
  const machines = section(documentNode, TITLE_MACHINES);
  if (hosted) {
    main.replaceChildren(mappings, machines);
  } else {
    main.replaceChildren(installations, personal, mappings, machines);
    personal.renderEnvelope(
      { status: 200, envelope: { success: true, result: {} } },
      renderPersonalUnavailable,
    );
  }
  const mappingTargets = hosted
    ? [[mappings, (body, callResults) => renderMappings(
      body, callResults, projects, buckets,
    )]]
    : [
      [installations, renderInstallations],
      [mappings, (body, callResults) => renderMappings(
        body, callResults, projects, buckets,
      )],
    ];
  loadScopedPanels(context, mappingTargets, bindingCalls(buckets));
  loadSection(
    context, machines, "machine.list", {},
    (body, callResult) => renderMachines(body, callResult.envelope.result || {}),
  );
}
