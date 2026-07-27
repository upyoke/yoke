// Installed and available Packs, repository-report freshness, and preview-first
// file inspection.

import {
  el,
  loadScopedSection,
  loadScopedPanels,
  renderTable,
  section,
  statePill,
} from "./universe_view_support.js";

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
        `${bundle.project_slug || row.project_slug || row.project_id}`;
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
    "pack-installed-note",
    "Updates preview as a three-way merge against the installed baseline — " +
      "project-local customizations stay yours, and apply is a separate step.",
  ));
  for (const callResult of callResults) {
    const result = callResult.envelope.result || {};
    const report = result.repository_report;
    body.appendChild(el(
      documentNode,
      "p",
      report && report.fresh
        ? "pack-repository-report"
        : "pack-repository-report stale",
      report
        ? `${result.project_slug}: repository report ${report.reported_at} ` +
          `(${report.fresh ? "fresh" : "stale"})`
        : `${result.project_slug || result.project_id}: no repository receipt reported`,
    ));
  }
}

function previewButton(documentNode, label, onClick) {
  const button = el(
    documentNode,
    "button",
    "capability-action pack-preview-action",
    label,
  );
  button.type = "button";
  button.addEventListener("click", onClick);
  return button;
}

function openPreview(context, previewPanel, row) {
  previewPanel.hidden = false;
  previewPanel.setCount(null);
  renderPackPreview(context, previewPanel, row);
}

function installedPackRows(callResults) {
  return catalogRows(callResults).filter(
    (row) => row.status !== "available" && row.installed_version,
  );
}

function availablePackRows(callResults) {
  return catalogRows(callResults).filter(
    (row) => row.status === "available" || !row.installed_version,
  );
}

function renderInstalledPacks(
  body, callResults, context, previewPanel, panel,
) {
  const documentNode = body.ownerDocument;
  const rows = installedPackRows(callResults);
  panel.setCount(rows.length);
  if (!rows.length) body.appendChild(el(
    documentNode, "p", "empty", "No Packs installed.",
  ));
  const table = el(documentNode, "table", "items");
  const head = el(documentNode, "tr");
  for (const label of [
    "Pack", "Project", "Installed", "Latest", "State",
    "Update — preview first",
  ]) {
    head.appendChild(el(documentNode, "th", null, label));
  }
  table.appendChild(head);
  for (const row of rows) {
    const tr = el(documentNode, "tr");
    tr.appendChild(el(documentNode, "td", "mono", row.slug));
    tr.appendChild(el(
      documentNode, "td", "mono", row.project_slug || row.project_id,
    ));
    tr.appendChild(el(
      documentNode, "td", "mono", row.installed_version || "—",
    ));
    tr.appendChild(el(documentNode, "td", "mono", row.latest_version || "—"));
    const statusCell = el(documentNode, "td");
    const updateAvailable = row.status === "stale" ||
      row.installed_version !== row.latest_version;
    const pill = statePill(
      documentNode,
      updateAvailable ? "stale" : "ready",
      updateAvailable ? "update available" : "current",
    );
    if (pill) statusCell.appendChild(pill);
    tr.appendChild(statusCell);
    const actionCell = el(documentNode, "td");
    if (updateAvailable) {
      actionCell.appendChild(previewButton(
        documentNode,
        "Inspect update",
        () => openPreview(context, previewPanel, row),
      ));
    } else {
      actionCell.appendChild(el(documentNode, "span", "secondary-muted", "—"));
    }
    tr.appendChild(actionCell);
    table.appendChild(tr);
  }
  if (rows.length) body.appendChild(table);
  renderRepositoryReports(body, callResults);
}

function renderAvailablePacks(
  body, callResults, context, previewPanel, panel,
) {
  const documentNode = body.ownerDocument;
  const rows = availablePackRows(callResults);
  panel.setCount(rows.length);
  if (!rows.length) {
    body.appendChild(el(
      documentNode, "p", "empty", "No additional Packs available.",
    ));
    return;
  }
  for (const row of rows) {
    const pack = el(documentNode, "div", "pack-available-row");
    const info = el(documentNode, "div", "pack-available-info");
    info.appendChild(el(
      documentNode, "div", "pack-available-title mono", row.slug,
    ));
    info.appendChild(el(
      documentNode,
      "div",
      "pack-available-description",
      row.description || "No description published.",
    ));
    info.appendChild(el(
      documentNode,
      "div",
      "pack-available-meta",
      `${row.project_slug || row.project_id} · latest ${row.latest_version || "not exposed"}`,
    ));
    pack.appendChild(info);
    pack.appendChild(previewButton(
      documentNode,
      "Inspect get",
      () => openPreview(context, previewPanel, row),
    ));
    body.appendChild(pack);
  }
}

export function renderPacksView(context, main, scope) {
  const installed = section(context.document, "Installed");
  const available = section(context.document, "Available");
  const preview = section(context.document, "Pack contents and checkout handoff");
  const stack = el(context.document, "div", "packs-stack");
  preview.renderEnvelope(
    { status: 200, envelope: { success: true, result: {} } },
    (body) => body.appendChild(el(
      context.document,
      "p",
      "empty",
      "Choose a Pack to inspect its exact files and checkout command.",
    )),
  );
  preview.hidden = true;
  stack.appendChild(installed);
  stack.appendChild(available);
  stack.appendChild(preview);
  main.replaceChildren(stack);
  loadScopedPanels(
    context,
    [
      [installed, (body, callResults) => renderInstalledPacks(
        body, callResults, context, preview, installed,
      )],
      [available, (body, callResults) => renderAvailablePacks(
        body, callResults, context, preview, available,
      )],
    ],
    context.projects().map((project) => ({
      functionId: "packs.list",
      payload: { project: String(project.id) },
    })),
  );
}
