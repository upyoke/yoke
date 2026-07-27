// Pack catalog, repository-report freshness, and preview-first file inspection.

import {
  el,
  loadScopedSection,
  renderTable,
  section,
  statePill,
} from "./universe_view_support.js";

function packDependencySummary(row, statusByProjectAndSlug) {
  const dependencies = Array.isArray(row.dependencies) ? row.dependencies : [];
  if (dependencies.length === 0) return "none";
  return dependencies.map((slug) => {
    const dependency = statusByProjectAndSlug.get(
      `${row.project_id}:${String(slug)}`,
    );
    if (!dependency || dependency.status === "available") return `${slug}: missing`;
    return `${slug}: ${dependency.status}`;
  }).join(", ");
}

function displayFileMode(mode) {
  if (Number.isInteger(mode) && mode >= 0) {
    return mode.toString(8).padStart(4, "0");
  }
  return String(mode ?? "");
}

function renderPackPreview(context, panel, row) {
  const operation = row.status === "available" ? "get" : "update";
  loadScopedSection(
    context,
    panel,
    [{
      functionId: "packs.bundle.get",
      payload: { project: String(row.project_id), pack: row.slug },
    }],
    (body, callResults) => {
      const callResult = callResults[0];
      const bundle = callResult.envelope.result || {};
      const documentNode = body.ownerDocument;
      panel.setCount((bundle.files || []).length);
      body.appendChild(el(
        documentNode,
        "p",
        "fact-line",
        `Pack code becomes ordinary ${bundle.project_slug || "project"} source. ` +
          "Customize it freely after it lands.",
      ));
      const command = `yoke packs ${operation} ${row.slug} . --project ` +
        `${bundle.project_slug || project}`;
      const commandLine = el(documentNode, "p", "fact-line");
      commandLine.appendChild(el(
        documentNode,
        "span",
        null,
        "Run from the project checkout to preview the exact patch and conflicts; " +
          "add --apply only after reviewing that preview: ",
      ));
      commandLine.appendChild(el(documentNode, "code", null, command));
      body.appendChild(commandLine);
      renderTable(body, bundle.files || [], [
        { label: "file", value: (file) => file.path, code: true },
        { label: "mode", value: (file) => displayFileMode(file.mode), mono: true },
      ], "this Pack contains no project files");
    },
  );
}

function catalogRows(callResults) {
  return callResults.flatMap((callResult) => {
    const result = callResult.envelope.result || {};
    return (result.packs || []).map((row) => ({
      ...row,
      project_id: result.project_id,
      project_slug: result.project_slug,
    }));
  });
}

function renderRepositoryReports(body, callResults) {
  const documentNode = body.ownerDocument;
  body.appendChild(el(
    documentNode,
    "p",
    "fact-line",
    "Installed versions come from each project's last repository receipt report; " +
      "each repository receipt remains authoritative for that project.",
  ));
  for (const callResult of callResults) {
    const result = callResult.envelope.result || {};
    const report = result.repository_report;
    body.appendChild(el(
      documentNode,
      "p",
      report && report.fresh ? "fact-line" : "empty",
      report
        ? `${result.project_slug}: repository report ${report.reported_at} ` +
          `(${report.fresh ? "fresh" : "stale"})`
        : `${result.project_slug || result.project_id}: no repository receipt reported`,
    ));
  }
}

function renderPackCatalog(body, callResults, context, previewPanel) {
  const documentNode = body.ownerDocument;
  const rows = catalogRows(callResults);
  const statusByProjectAndSlug = new Map(rows.map((row) => [
    `${row.project_id}:${String(row.slug)}`, row,
  ]));

  renderRepositoryReports(body, callResults);
  if (rows.length === 0) {
    body.appendChild(el(documentNode, "p", "empty", "no Packs available"));
    return;
  }

  const table = el(documentNode, "table", "items");
  const head = el(documentNode, "tr");
  for (const label of [
    "Pack", "project", "what it does", "status", "installed", "latest", "dependencies", "files", "guidance", "action",
  ]) {
    head.appendChild(el(documentNode, "th", null, label));
  }
  table.appendChild(head);
  for (const row of rows) {
    const tr = el(documentNode, "tr");
    tr.appendChild(el(documentNode, "td", null, row.name || row.slug));
    tr.appendChild(el(
      documentNode, "td", "mono", row.project_slug || row.project_id,
    ));
    tr.appendChild(el(documentNode, "td", null, row.description || "—"));
    const statusCell = el(documentNode, "td");
    const pill = statePill(documentNode, row.status);
    if (pill) statusCell.appendChild(pill);
    tr.appendChild(statusCell);
    tr.appendChild(el(documentNode, "td", "mono", row.installed_version || "—"));
    tr.appendChild(el(documentNode, "td", "mono", row.latest_version));
    tr.appendChild(el(
      documentNode,
      "td",
      null,
      packDependencySummary(row, statusByProjectAndSlug),
    ));
    tr.appendChild(el(documentNode, "td", null, String(row.file_count ?? "")));
    const guidanceCell = el(documentNode, "td");
    guidanceCell.appendChild(el(documentNode, "code", null, row.documentation));
    tr.appendChild(guidanceCell);
    const actionCell = el(documentNode, "td");
    const operation = row.status === "available" ? "get" : "update";
    const button = el(
      documentNode,
      "button",
      "capability-action pack-preview-action",
      `Inspect ${operation}`,
    );
    button.type = "button";
    button.addEventListener("click", () => {
      previewPanel.setCount(null);
      renderPackPreview(context, previewPanel, row);
    });
    actionCell.appendChild(button);
    tr.appendChild(actionCell);
    table.appendChild(tr);
  }
  body.appendChild(table);
}

export function renderPacksView(context, main, scope) {
  const catalog = section(context.document, "Pack catalog");
  const preview = section(context.document, "Pack contents and checkout handoff");
  preview.renderEnvelope(
    { status: 200, envelope: { success: true, result: {} } },
    (body) => body.appendChild(el(
      context.document,
      "p",
      "empty",
      "Choose a Pack to inspect its exact files and checkout command.",
    )),
  );
  main.replaceChildren(catalog, preview);
  loadScopedSection(
    context,
    catalog,
    context.projects().map((project) => ({
      functionId: "packs.list",
      payload: { project: String(project.id) },
    })),
    (body, callResults) => {
      catalog.setCount(catalogRows(callResults).length);
      renderPackCatalog(body, callResults, context, preview);
    },
  );
}
