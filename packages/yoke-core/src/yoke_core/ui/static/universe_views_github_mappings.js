// Project mapping rows and the explicit destructive unbind confirmation.
import { callFunction, el, renderTable } from "./universe_view_support.js";

function statusResult(callResult) {
  return callResult.envelope.result || {};
}

export function projectLabel(projects, projectId) {
  const row = projects.find((item) => String(item.id) === String(projectId));
  return (row && (row.name || row.slug)) || String(projectId);
}

function confirmUnbind(context, cell, row, state) {
  const documentNode = cell.ownerDocument;
  const warning = el(documentNode, "span", "fact-line",
    `Unbind ${row.project}? This removes its GitHub capability and secrets and turns issue sync off.`);
  const confirm = el(documentNode, "button", "capability-action", "Confirm unbind");
  const cancel = el(documentNode, "button", "capability-action", "Cancel");
  confirm.type = cancel.type = "button";
  cancel.addEventListener("click", () => state.load());
  confirm.addEventListener("click", async () => {
    confirm.disabled = cancel.disabled = true;
    const status = state.mappingStatus;
    status.hidden = false;
    status.className = "fact-line";
    status.textContent = `Unbinding ${row.project}…`;
    try {
      const response = await callFunction(context.client,
        "projects.github_binding.unbind", { project: row.projectId });
      if (!context.isMounted()) return;
      if (!(response.status === 200 && response.envelope.success)) {
        const error = response.envelope.error || {};
        throw new Error([error.code, error.message, error.recovery_hint]
          .filter(Boolean).join(": "));
      }
      status.setAttribute("role", "status");
      status.textContent = `${row.project} unbound. Issue sync was turned off. ` +
        "To turn it back on, bind a repository again, then run " +
        "yoke projects update --slug <slug> --name <Name> --github-sync-mode enabled.";
      await state.load();
    } catch (error) {
      if (!context.isMounted()) return;
      status.className = "error";
      status.setAttribute("role", "alert");
      status.textContent = `Unbind failed: ${error}. Resolve the error and try Unbind again.`;
      confirm.disabled = cancel.disabled = false;
    }
  });
  cell.replaceChildren(warning, confirm, cancel);
}

function mappingRows(callResults, projects, buckets) {
  return callResults.map((callResult, index) => {
    const result = statusResult(callResult);
    const binding = result.binding || {};
    const permission = result.permission_status || {};
    const automation = result.automation || {};
    const missing = Array.isArray(permission.missing)
      ? permission.missing.join(", ") : "";
    return {
      projectId: String(buckets[index]),
      bound: Boolean(result.bound),
      project: projectLabel(projects, buckets[index]),
      repo: binding.github_repo || result.github_repo || "",
      status: binding.status || "",
      permissions: permission.status || "",
      missing,
      automation: Object.hasOwn(automation, "available")
        ? (automation.available ? "available" : "blocked") : "",
      reason: automation.reason || "",
      sync_mode: result.github_sync_mode || "",
      last_sync: binding.last_sync_at || "",
      last_sync_outcome: binding.last_sync_outcome || "",
    };
  }).filter((row) => row.bound || row.repo);
}

export function renderMappings(context, body, callResults, projects, buckets, state) {
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
    {
      label: "actions",
      value: () => "",
      render(row, cell) {
        if (!row.bound) return;
        const button = el(body.ownerDocument, "button", "capability-action", "Unbind");
        button.type = "button";
        button.addEventListener("click", () => confirmUnbind(context, cell, row, state));
        cell.appendChild(button);
      },
    },
  ], "no project mappings in this scope");
}

