import { callFunction, el } from "./universe_view_support.js";
import { definitionChanges } from "./workflow_view_canon_diff.js";
import { definitionPostureRows } from "./workflow_view_policy.js";
import { readablePolicyValue } from "./workflow_view_primitives.js";

async function fetchDefinition(workflow, version, actions) {
  if (version.definition) return version.definition;
  if (Number(version.version) === Number(workflow.current_version)) {
    return workflow.definition || {};
  }
  const result = await callFunction(
    actions.client,
    "workflows.version.get",
    { workflow_id: workflow.id, version: Number(version.version) },
  );
  if (result.status !== 200 || !result.envelope.success) {
    throw new Error(
      result.envelope?.error?.message || "Version definition read failed.",
    );
  }
  return result.envelope.result?.definition || {};
}

async function versionDefinition(workflow, version, actions) {
  const cache = actions.versionDefinitionCache;
  const key = workflow.id + ":" + version.version;
  if (cache?.has(key)) return cache.get(key);
  const pending = fetchDefinition(workflow, version, actions);
  if (cache) cache.set(key, pending);
  try {
    return await pending;
  } catch (failure) {
    cache?.delete(key);
    throw failure;
  }
}

export function renderVersionDelta(
  documentNode,
  workflow,
  version,
  previous,
  actions,
) {
  const host = el(documentNode, "div", "workflow-version-delta");
  if (!previous) {
    host.textContent = "First published version.";
    return host;
  }
  host.textContent = "Loading changes…";
  Promise.all([
    versionDefinition(workflow, previous, actions),
    versionDefinition(workflow, version, actions),
  ]).then(([before, after]) => {
    const changes = definitionChanges(before, after);
    host.replaceChildren();
    if (!changes.length) {
      host.textContent =
        "No surfaced changes since v" + previous.version + ".";
      return;
    }
    host.appendChild(el(
      documentNode,
      "span",
      "workflow-version-delta-label",
      "Since v" + previous.version + ":",
    ));
    const list = el(documentNode, "ul", "workflow-version-delta-list");
    for (const change of changes) {
      list.appendChild(el(
        documentNode, "li", "workflow-version-delta-change", change,
      ));
    }
    host.appendChild(list);
  }).catch(() => {
    host.textContent = "Change summary unavailable.";
    host.classList.add("error");
  });
  return host;
}

export function renderVersionPolicyGrid(documentNode, result) {
  const section = el(
    documentNode, "section", "workflow-version-policy-section",
  );
  section.appendChild(el(
    documentNode,
    "h3",
    "workflow-version-policy-heading",
    "Policies in v" + result.version,
  ));
  const grid = el(
    documentNode, "div", "workflow-version-policy-grid",
  );
  for (const row of definitionPostureRows(result.definition || {})) {
    const cell = el(documentNode, "div", "workflow-version-policy-cell");
    cell.appendChild(el(
      documentNode, "span", "workflow-version-policy-label", row.label,
    ));
    cell.appendChild(el(
      documentNode,
      "span",
      "workflow-version-policy-value" + (row.declared ? "" : " predates"),
      row.declared
        ? readablePolicyValue(row.key, row.value)
        : "default (predates this version)",
    ));
    grid.appendChild(cell);
  }
  section.appendChild(grid);
  return section;
}
