// Delivery target, database, and infrastructure facets. These reads expose
// only facts the engine can currently serve; unavailable steering facts stay
// labelled instead of being inferred from deployment configuration.

import {
  el,
  loadScopedSection,
  mergedRows,
  renderError,
  renderTable,
  scopeBuckets,
  section,
  settledScopedCalls,
  withProjectColumn,
} from "./universe_view_support.js";
import { relativeAge } from "./universe_time.js";

const MIGRATION_MODEL_CAPABILITY = "migration_model";

function projectDirectory(projects) {
  const byKey = new Map();
  for (const project of projects) {
    for (const key of [project.id, project.slug, project.name]) {
      if (key !== null && key !== undefined && String(key)) {
        byKey.set(String(key), project);
      }
    }
  }
  return byKey;
}

function resolvedProject(directory, value) {
  return directory.get(String(value ?? "")) || null;
}

function projectLabel(directory, row) {
  const project = resolvedProject(
    directory, row.project_id ?? row.project_key ?? row.project,
  );
  const label = row.project || project?.slug || project?.name ||
    String(row.project_key || "—");
  return project?.emoji ? `${project.emoji} ${label}` : label;
}

function projectIdentity(directory, row) {
  const project = resolvedProject(
    directory, row.project_id ?? row.project_key ?? row.project,
  );
  return String(project?.id ?? row.project_id ?? row.project_key ??
    row.project ?? "");
}

function infrastructureRows(callResults, key, directory) {
  return callResults.flatMap((callResult) => {
    const result = callResult.envelope.result || {};
    const project = resolvedProject(directory, result.project);
    return (result[key] || []).map((row) => ({
      ...row,
      project_key: result.project,
      project_id: project?.id ?? result.project,
      project: project?.slug || project?.name || result.project,
    }));
  });
}

function deliveryNote(documentNode, title, copy) {
  const note = el(documentNode, "div", "delivery-read-note");
  note.appendChild(el(documentNode, "strong", null, title));
  note.appendChild(el(documentNode, "span", null, copy));
  return note;
}

function deliveryPanel(documentNode, title) {
  const panel = section(documentNode, title);
  panel.classList.add("delivery-facet-panel");
  return panel;
}

function readCalls(functionId, scope, projects, requiresProject) {
  return scopeBuckets(scope, projects, requiresProject).map((bucket) => ({
    functionId,
    payload: bucket === null ? {} : { project: bucket },
  }));
}

function runTimestamp(row) {
  return row
    ? row.completed_at || row.started_at || row.created_at || null
    : null;
}

function latestRunsByEnvironment(rows, directory) {
  const latest = new Map();
  for (const row of rows) {
    const key = `${projectIdentity(directory, row)}:${String(
      row.target_env || "",
    ).toLowerCase()}`;
    const previous = latest.get(key);
    const timestamp = new Date(runTimestamp(row) || 0).getTime();
    const previousTimestamp = previous
      ? new Date(runTimestamp(previous) || 0).getTime()
      : Number.NaN;
    if (
      !previous ||
      (!Number.isNaN(timestamp) && (
        Number.isNaN(previousTimestamp) || timestamp > previousTimestamp
      ))
    ) latest.set(key, row);
  }
  return latest;
}

function branchesByEnvironment(callResults) {
  const branches = new Map();
  for (const callResult of callResults) {
    const result = callResult.envelope.result || {};
    if (!result.environment_id || !result.values) continue;
    const branch = result.values["git.branch"];
    if (branch !== null && branch !== undefined && String(branch).trim()) {
      branches.set(
        `${String(result.project)}:${String(result.environment_id)}`,
        String(branch),
      );
    }
  }
  return branches;
}

export function renderDeliveryEnvironmentsView(context, main, scope) {
  const documentNode = context.document;
  const projects = context.projects();
  const directory = projectDirectory(projects);
  const panel = deliveryPanel(documentNode, "Environments");
  main.replaceChildren(panel);
  const loadInventory = async () => {
    const infrastructure = await settledScopedCalls(
      context,
      readCalls("projects.infrastructure.list", scope, projects, true),
    );
    if (!context.isMounted()) return;
    if (infrastructure.failed) {
      panel.renderEnvelopes(
        infrastructure.callResults,
        (body) => renderError(body, infrastructure.failed),
      );
      return;
    }
    const environments = infrastructureRows(
      infrastructure.callResults, "environments", directory,
    );
    const details = await settledScopedCalls(context, [
      ...environments.map((row) => ({
        functionId: "projects.environment_settings.get",
        payload: {
          project: projectIdentity(directory, row),
          environment_id: String(row.id),
          paths: ["git.branch"],
        },
      })),
      ...readCalls("deployment_runs.list", scope, projects, false),
    ]);
    if (!context.isMounted()) return;
    const callResults = [
      ...infrastructure.callResults,
      ...details.callResults,
    ];
    panel.renderEnvelopes(
      callResults,
      details.failed ? (body) => renderError(body, details.failed) : (body) => {
        const environments = infrastructureRows(
          callResults, "environments", directory,
        );
        const runs = mergedRows(callResults, (result) => result.rows);
        const branches = branchesByEnvironment(callResults);
        const latestRuns = latestRunsByEnvironment(runs, directory);
        const latestFor = (row) => {
          const project = projectIdentity(directory, row);
          for (const environment of [row.id, row.name]) {
            const latest = latestRuns.get(
              `${project}:${String(environment || "").toLowerCase()}`,
            );
            if (latest) return latest;
          }
          return null;
        };
        panel.setCount(environments.length);
        renderTable(
          body,
          environments,
          withProjectColumn([
            { label: "environment", value: (row) => row.name || row.id },
            {
              label: "branch",
              value: (row) => branches.get(
                `${projectIdentity(directory, row)}:${String(row.id)}`,
              ) || "not exposed",
            },
            { label: "auto-deploy", value: () => "not exposed" },
            {
              label: "status",
              value: (row) => latestFor(row)?.status || "no run record",
              pill: true,
            },
            {
              label: "last deploy",
              value: (row) => {
                const stamp = row.last_deployed_at || runTimestamp(latestFor(row));
                return stamp ? relativeAge(stamp) : "never";
              },
            },
          ], scope, (row) => projectLabel(directory, row)),
          "No environments registered in this scope.",
        );
        body.appendChild(deliveryNote(
          documentNode,
          "Registered targets, grounded by their latest run. ",
          "Environment identity comes from projects.infrastructure.list, branch from the git.branch environment-settings projection, and status from deployment_runs.list. Auto-deploy policy has no published browser read, so that cell stays explicitly unavailable.",
        ));
      },
    );
  };
  void loadInventory();
}

export function renderDeliveryDatabasesView(context, main, scope) {
  const documentNode = context.document;
  const projects = context.projects();
  const directory = projectDirectory(projects);
  const panel = deliveryPanel(documentNode, "Databases");
  main.replaceChildren(panel);
  loadScopedSection(
    context,
    panel,
    readCalls("projects.capabilities.list", scope, projects, false),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows)
        .filter((row) => row.type === MIGRATION_MODEL_CAPABILITY);
      panel.setCount(rows.length);
      renderTable(
        body,
        rows,
        withProjectColumn([
          {
            label: "model",
            value: (row) => row.settings_summary || "declared model",
            mono: true,
          },
          { label: "authority", value: () => "project capability" },
          { label: "posture", value: () => "not exposed" },
          { label: "last apply", value: () => "not exposed" },
          { label: "state", value: (row) => row.state, pill: true },
        ], scope, (row) => projectLabel(directory, row)),
        "No governed database model declared in this scope.",
      );
      body.appendChild(deliveryNote(
        documentNode,
        "Database steering is only partially readable today. ",
        "Declared models and their readiness come from projects.capabilities.list. Per-model authority, migration posture, apply receipts, claims, and leases have no browser read yet, so this view names the gap instead of implying a safe release.",
      ));
    },
  );
}

export function renderDeliveryInfrastructureView(context, main, scope) {
  const documentNode = context.document;
  const projects = context.projects();
  const directory = projectDirectory(projects);
  const panel = deliveryPanel(documentNode, "Infrastructure");
  main.replaceChildren(panel);
  loadScopedSection(
    context,
    panel,
    readCalls("projects.infrastructure.list", scope, projects, true),
    (body, callResults) => {
      const rows = infrastructureRows(
        callResults, "environments", directory,
      );
      panel.setCount(rows.length);
      renderTable(
        body,
        rows,
        [
          { label: "environment", value: (row) => row.name || row.id },
          { label: "project", value: (row) => projectLabel(directory, row) },
          { label: "what backs it", value: () => "not exposed" },
          { label: "code source", value: () => "project-owned" },
          { label: "state", value: () => "declared", pill: true },
        ],
        "No infrastructure targets registered in this scope.",
      );
      body.appendChild(deliveryNote(
        documentNode,
        "Registered metadata is not provider truth. ",
        "projects.infrastructure.list publishes sites, environments, URLs, deploy methods, and health-check addresses. It does not compare live provider state with project-owned infrastructure, so backing resources and drift remain explicitly unavailable.",
      ));
    },
  );
}
