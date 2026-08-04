import { el } from "./universe_view_support.js";
import { callFunction } from "./universe_view_support.js";
import { relativeAge } from "./universe_time.js";
import { button, workflowPanel } from "./workflow_view_primitives.js";

function inspectionNode(row) {
  return Array.from(row.children).find(
    (node) => node.classList.contains("workflow-version-inspection"),
  );
}

function renderInspection(documentNode, row, result, makeCurrent) {
  const inspection = el(
    documentNode, "div", "workflow-version-inspection",
  );
  inspection.appendChild(el(
    documentNode,
    "code",
    "workflow-version-digest",
    result.definition_digest || "digest unavailable",
  ));
  const stages = (result.definition?.stages || [])
    .map((stage) => stage.label || stage.id)
    .join(" → ");
  if (stages) {
    inspection.appendChild(el(
      documentNode, "p", "workflow-version-stages", stages,
    ));
  }
  if (makeCurrent) {
    const makeCurrentButton = button(
      documentNode, "Make current", "workflow-button compact",
    );
    makeCurrentButton.addEventListener("click", makeCurrent);
    inspection.appendChild(makeCurrentButton);
  }
  row.appendChild(inspection);
}

function inspectButton(documentNode, row, workflow, version, actions) {
  const inspect = button(
    documentNode, "Inspect", "workflow-button version-inspect",
  );
  inspect.setAttribute("aria-expanded", "false");
  inspect.addEventListener("click", async () => {
    if (inspect.disabled) return;
    const existing = inspectionNode(row);
    if (existing && !existing.classList.contains("error")) {
      row.removeChild(existing);
      row.classList.remove("inspecting");
      inspect.setAttribute("aria-expanded", "false");
      inspect.textContent = "Inspect";
      return;
    }
    if (existing) row.removeChild(existing);
    row.classList.add("inspecting");
    inspect.setAttribute("aria-expanded", "true");
    inspect.disabled = true;
    inspect.textContent = "Inspecting…";
    const loading = el(
      documentNode,
      "div",
      "workflow-version-inspection loading",
      "Loading version…",
    );
    row.appendChild(loading);
    const showFailure = (message) => {
      loading.textContent = message;
      loading.classList.remove("loading");
      loading.classList.add("error");
      inspect.disabled = false;
      inspect.textContent = "Retry";
    };
    let callResult;
    try {
      callResult = await callFunction(
        actions.client,
        "workflows.version.get",
        { workflow_id: workflow.id, version: Number(version.version) },
      );
    } catch (failure) {
      showFailure(String(failure));
      return;
    }
    const ok = callResult.status === 200 && callResult.envelope.success;
    if (!ok) {
      showFailure(
        callResult.envelope?.error?.message || "Version read failed.",
      );
      return;
    }
    row.removeChild(loading);
    renderInspection(
      documentNode,
      row,
      callResult.envelope.result || {},
      actions.makeCurrent ? () => actions.makeCurrent(version) : null,
    );
    inspect.disabled = false;
    inspect.textContent = "Hide";
  });
  return inspect;
}

function provenanceNote(documentNode, workflow, version) {
  // Only built-in workflows have a canon to be recognized against; one
  // authored here is local by definition rather than by failing to match.
  const provenance = version.provenance;
  if (!provenance || workflow.source !== "built_in") {
    return null;
  }
  if (provenance.kind === "local") {
    return el(
      documentNode,
      "div",
      "workflow-version-provenance local",
      "Customized here — not a published Yoke version.",
    );
  }
  // A recognized version gets no note at all, including when the canon
  // numbers it differently. This universe's number IS the number; the canon's
  // is an implementation detail of how recognition works, and showing both
  // hands the reader two competing identities for one thing while implying a
  // discrepancy where there is none. Customization is the only state here
  // worth a line, because it is the only one that changes what an update does.
  return null;
}


function versionRow(documentNode, workflow, version, actions) {
  const current = Number(version.version) ===
    Number(workflow.current_version);
  const row = el(documentNode, "div", "workflow-version-row");
  row.appendChild(el(
    documentNode,
    "span",
    `workflow-version-dot${current ? " current" : ""}`,
  ));
  const summary = el(documentNode, "div", "workflow-version-summary");
  summary.appendChild(el(
    documentNode,
    "div",
    "workflow-version-title",
    `v${version.version}${current ? " · current" : ""}`,
  ));
  summary.appendChild(el(
    documentNode,
    "div",
    "workflow-version-description",
    current
      ? version.published_by_actor_id != null
        ? "edited here"
        : "New items pin this version."
      : "Readable and eligible to become current again.",
  ));
  const provenance = provenanceNote(documentNode, workflow, version);
  if (provenance) {
    summary.appendChild(provenance);
  }
  row.appendChild(summary);
  if (current) {
    const published = el(
      documentNode,
      "time",
      "workflow-version-when",
      relativeAge(version.published_at),
    );
    if (version.published_at) {
      published.setAttribute("datetime", version.published_at);
      published.setAttribute("title", version.published_at);
    }
    row.appendChild(published);
  } else {
    row.appendChild(inspectButton(
      documentNode, row, workflow, version, actions,
    ));
  }
  return row;
}

function canonStatusLine(documentNode, workflow) {
  const status = workflow.canon_status;
  if (!status || status.state === "not_applicable") {
    return null;
  }
  // "Up to date" is stated rather than left to silence. On the boot path
  // silence correctly means nothing is wrong, but this is a screen someone
  // opened to ask -- and there, saying nothing is indistinguishable from
  // never having checked.
  if (status.state === "up_to_date") {
    return el(
      documentNode,
      "div",
      "workflow-canon-status up-to-date",
      "Up to date with the published Yoke workflow.",
    );
  }
  if (status.state === "customized") {
    return el(
      documentNode,
      "div",
      "workflow-canon-status customized",
      "Customized here. Updates will preserve your changes.",
    );
  }
  return el(
    documentNode,
    "div",
    "workflow-canon-status update",
    `Yoke has published a newer version of this workflow ` +
      `(${status.latest_canon_version}).`,
  );
}


export function renderVersionHistory(documentNode, workflow, actions) {
  const versions = [...(workflow.versions || [])].sort(
    (left, right) => Number(right.version) - Number(left.version),
  );
  const { panel, body } = workflowPanel(documentNode, "Version history");
  const status = canonStatusLine(documentNode, workflow);
  if (status) {
    body.appendChild(status);
  }
  const timeline = el(documentNode, "div", "workflow-version-timeline");
  for (const version of versions) {
    timeline.appendChild(versionRow(
      documentNode, workflow, version, actions,
    ));
  }
  if (!versions.length) {
    timeline.appendChild(el(
      documentNode, "p", "empty", "No published versions.",
    ));
  } else if (versions.length === 1) {
    timeline.appendChild(el(
      documentNode,
      "p",
      "workflow-first-version",
      "First published version.",
    ));
  }
  body.appendChild(timeline);
  return panel;
}
