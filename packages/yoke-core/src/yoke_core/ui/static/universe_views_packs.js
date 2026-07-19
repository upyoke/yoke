// Pack catalog, repository-report freshness, and preview-first file inspection.

import {
  el,
  loadSection,
  renderTable,
  section,
  statePill,
} from "./universe_view_support.js";

function packDependencySummary(row, statusBySlug) {
  const dependencies = Array.isArray(row.dependencies) ? row.dependencies : [];
  if (dependencies.length === 0) return "none";
  return dependencies.map((slug) => {
    const dependency = statusBySlug.get(String(slug));
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

function renderPackPreview(context, panel, project, row) {
  const operation = row.status === "available" ? "get" : "update";
  loadSection(
    context,
    panel,
    "packs.bundle.get",
    { project, pack: row.slug },
    (body, callResult) => {
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

function renderPackCatalog(body, result, context, previewPanel, project) {
  const documentNode = body.ownerDocument;
  const rows = Array.isArray(result.packs) ? result.packs : [];
  const report = result.repository_report;
  const statusBySlug = new Map(rows.map((row) => [String(row.slug), row]));

  body.appendChild(el(
    documentNode,
    "p",
    "fact-line",
    "Installed versions come from the project's last repository receipt report; " +
      "the repository receipt remains the authority.",
  ));
  body.appendChild(el(
    documentNode,
    "p",
    report && report.fresh ? "fact-line" : "empty",
    report
      ? `Repository report: ${report.reported_at} (${report.fresh ? "fresh" : "stale"})`
      : "No repository receipt has been reported for this project.",
  ));
  if (rows.length === 0) {
    body.appendChild(el(documentNode, "p", "empty", "no Packs available"));
    return;
  }

  const table = el(documentNode, "table", "items");
  const head = el(documentNode, "tr");
  for (const label of [
    "Pack", "status", "installed", "latest", "dependencies", "files", "guidance", "action",
  ]) {
    head.appendChild(el(documentNode, "th", null, label));
  }
  table.appendChild(head);
  for (const row of rows) {
    const tr = el(documentNode, "tr");
    tr.appendChild(el(documentNode, "td", null, row.name || row.slug));
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
      packDependencySummary(row, statusBySlug),
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
      renderPackPreview(context, previewPanel, project, row);
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
  loadSection(
    context,
    catalog,
    "packs.list",
    { project: scope },
    (body, callResult) => {
      const result = callResult.envelope.result || {};
      catalog.setCount((result.packs || []).length);
      renderPackCatalog(body, result, context, preview, scope);
    },
  );
}
