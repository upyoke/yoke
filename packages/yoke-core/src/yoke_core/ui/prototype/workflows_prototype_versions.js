// Version history, told as a history: what each version changed, when it
// landed, where it came from, and how many live items are pinned to it.
// Digests move behind Inspect, and a rollback is stated rather than implied.

import {
  button, el, formatDay, panel,
} from "./workflows_prototype_dom.js";
import { renderPolicyGrid } from "./workflows_prototype_policy_grid.js";

// The delta in the vocabulary this page already uses. A textual JSON diff
// would be honest and useless: key order would dominate, and the reader wants
// "a gate moved", not "line 214 changed".
function difference(before, after) {
  const beforeSet = new Set(before);
  const afterSet = new Set(after);
  return {
    added: after.filter((value) => !beforeSet.has(value)),
    removed: before.filter((value) => !afterSet.has(value)),
  };
}

function gateNames(definition) {
  return (definition?.stages || []).flatMap((stage) =>
    (stage.gates || []).map((gate) => `${stage.id}: ${gate.id}`));
}

export function definitionDelta(previous, current) {
  if (!previous) return [];
  const changes = [];
  const stages = difference(
    (previous.stages || []).map((stage) => String(stage.id)),
    (current.stages || []).map((stage) => String(stage.id)),
  );
  for (const id of stages.added) changes.push(`stage added: ${id}`);
  for (const id of stages.removed) changes.push(`stage removed: ${id}`);
  const gates = difference(gateNames(previous), gateNames(current));
  for (const gate of gates.added) changes.push(`gate added — ${gate}`);
  for (const gate of gates.removed) changes.push(`gate removed — ${gate}`);
  const before = previous.policies || {};
  const after = current.policies || {};
  for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
    const left = before[key];
    const right = after[key];
    if (JSON.stringify(left) === JSON.stringify(right)) continue;
    // A list-valued policy reads as what joined and what left. Printing both
    // arrays in full makes the reader diff them by eye, which is the job the
    // row exists to do for them.
    if (Array.isArray(left) && Array.isArray(right)) {
      const members = difference(left, right);
      for (const value of members.added) {
        changes.push(`${key}: ${value} added`);
      }
      for (const value of members.removed) {
        changes.push(`${key}: ${value} removed`);
      }
      continue;
    }
    if (left === undefined) {
      changes.push(`policy added: ${key} = ${JSON.stringify(right)}`);
    } else if (right === undefined) {
      changes.push(`policy removed: ${key}`);
    } else {
      changes.push(
        `policy ${key}: ${JSON.stringify(left)} → ${JSON.stringify(right)}`,
      );
    }
  }
  const bindings = difference(
    (previous.skill_bindings || []).map((entry) => entry.skill_id),
    (current.skill_bindings || []).map((entry) => entry.skill_id),
  );
  for (const value of bindings.added) changes.push(`skill added: ${value}`);
  for (const value of bindings.removed) changes.push(`skill removed: ${value}`);
  const surfaces = difference(
    previous.entry_surfaces || [], current.entry_surfaces || [],
  );
  for (const value of surfaces.added) {
    changes.push(`entry surface added: ${value}`);
  }
  for (const value of surfaces.removed) {
    changes.push(`entry surface removed: ${value}`);
  }
  return changes;
}

function provenanceText(version) {
  const provenance = version.provenance || {};
  if (provenance.kind === "local") {
    return provenance.derived_from_canon_version == null
      ? "edited here"
      : `edited here, starting from Yoke v${
        provenance.derived_from_canon_version}`;
  }
  return `Yoke v${provenance.canon_version ?? version.version}`;
}

function pinnedText(version) {
  const pinned = version.pinned_item_count || 0;
  if (!pinned) return "no live items pinned";
  return `${pinned} live item${pinned === 1 ? "" : "s"} pinned`;
}

// Inspect carries what a reader only occasionally wants: the digest, and this
// version's own policy grid — including the keys it predates.
function inspection(documentNode, workflow, version) {
  const host = el(documentNode, "div", "wp-version-inspection");
  host.appendChild(el(documentNode, "code", "workflow-version-digest",
    version.definition_digest));
  host.appendChild(el(documentNode, "p", "wp-panel-note",
    `Policies as v${version.version} declares them. A key this version ` +
    "predates reads as a default rather than being left out."));
  renderPolicyGrid(
    documentNode, host, workflow, version.definition.policies || {}, null,
  );
  return host;
}

function versionRow(documentNode, workflow, version, previous, actions) {
  const current = Number(version.version) === Number(workflow.current_version);
  const row = el(documentNode, "div", "wp-version-row");
  row.appendChild(el(documentNode, "span",
    `workflow-version-dot${current ? " current" : ""}`));
  const summary = el(documentNode, "div", "wp-version-summary");
  const heading = el(documentNode, "div", "wp-version-heading");
  heading.appendChild(el(documentNode, "span", "workflow-version-title",
    `v${version.version}`));
  if (current) {
    heading.appendChild(el(documentNode, "span", "wp-version-badge current",
      "current"));
  }
  heading.appendChild(el(documentNode, "span", "wp-version-facts",
    `${formatDay(version.published_at)} · ${provenanceText(version)} · ${
      pinnedText(version)}`));
  summary.appendChild(heading);
  // A rollback is a fact about this list, so it is stated in the list. Making
  // an older version current again does not republish it or change anything
  // already pinned, and saying so is the only way the two dates make sense.
  if (version.made_current_at) {
    summary.appendChild(el(documentNode, "div", "wp-version-rollback",
      `Made current again on ${formatDay(version.made_current_at)} — newer ` +
      "versions stay readable, and items already underway did not move."));
  }
  const delta = definitionDelta(previous?.definition, version.definition);
  const changes = el(documentNode, "div", "wp-version-delta");
  if (!previous) {
    changes.appendChild(el(documentNode, "p", "wp-version-delta-none",
      "First published version — nothing before it to compare."));
  } else if (!delta.length) {
    changes.appendChild(el(documentNode, "p", "wp-version-delta-none",
      `No change this view renders against v${previous.version}.`));
  } else {
    const list = el(documentNode, "ul", "workflow-diff-list");
    for (const change of delta) {
      list.appendChild(el(documentNode, "li", "workflow-diff-change", change));
    }
    changes.appendChild(list);
  }
  summary.appendChild(changes);
  row.appendChild(summary);

  const controls = el(documentNode, "div", "wp-version-controls");
  const inspect = button(documentNode, "Inspect",
    "workflow-button version-inspect");
  let open = null;
  inspect.addEventListener("click", () => {
    if (open) {
      row.removeChild(open);
      open = null;
      inspect.textContent = "Inspect";
      return;
    }
    open = inspection(documentNode, workflow, version);
    row.appendChild(open);
    inspect.textContent = "Hide";
  });
  controls.appendChild(inspect);
  if (!current) {
    const makeCurrent = button(documentNode, "Make current",
      "workflow-button version-inspect");
    makeCurrent.addEventListener("click", () =>
      actions.makeCurrent(workflow, version));
    controls.appendChild(makeCurrent);
  }
  row.appendChild(controls);
  return row;
}

// Auto-follow: an unmodified derivative of the published workflow takes new
// versions on engine upgrade and reports it afterwards. A universe with its
// own edits keeps the review, because there the update is a merge.
function followControl(documentNode, workflow, actions) {
  const host = el(documentNode, "div", "wp-follow");
  const auto = workflow.canon_follow === "auto";
  const customized = String(workflow.canon_status?.state || "")
    .startsWith("customized");
  host.appendChild(el(documentNode, "div", "wp-follow-state",
    auto
      ? "Following Yoke automatically."
      : "Reviewing Yoke updates manually."));
  host.appendChild(el(documentNode, "p", "wp-follow-note",
    auto
      ? "New published versions are adopted on engine upgrade and reported " +
        "here afterwards. Editing this workflow switches it to manual, " +
        "because from then on an update is a merge."
      : customized
        ? "This universe has its own edits, so an update merges rather than " +
          "replaces. Auto-follow stays off until the edits are gone."
        : "New published versions wait here for review."));
  const toggle = button(documentNode,
    auto ? "Review updates manually" : "Follow Yoke automatically",
    "workflow-button compact");
  toggle.disabled = !auto && customized;
  toggle.addEventListener("click", () => actions.setFollow(
    workflow, auto ? "manual" : "auto",
  ));
  host.appendChild(toggle);
  if (!auto) {
    const takeAll = button(documentNode, "Take all updates",
      "workflow-button primary compact");
    takeAll.addEventListener("click", () => actions.takeAll(workflow));
    host.appendChild(takeAll);
  }
  return host;
}

function adoptionNotice(documentNode, workflow) {
  if (!workflow.adopted) return null;
  const host = el(documentNode, "div", "workflow-canon-status up-to-date");
  host.textContent =
    `Adopted Yoke v${workflow.adopted.version} automatically on ${
      formatDay(workflow.adopted.at)} — this workflow was an unmodified ` +
    "derivative, so nothing needed deciding.";
  return host;
}

export function renderVersions(documentNode, workflow, actions) {
  const ordered = [...(workflow.versions || [])]
    .sort((left, right) => Number(right.version) - Number(left.version));
  const { panel: host, body } = panel(documentNode, "Version history",
    { count: ordered.length, meta: `current · v${workflow.current_version}` });
  body.appendChild(followControl(documentNode, workflow, actions));
  const notice = adoptionNotice(documentNode, workflow);
  if (notice) body.appendChild(notice);
  if (workflow.canon_status?.state === "customized_update_available") {
    body.appendChild(el(documentNode, "div", "workflow-canon-status update",
      `Edited here on top of Yoke v${
        workflow.canon_status.derived_from_canon_version}. Yoke has since ` +
      `published v${workflow.canon_status.latest_canon_version}, so taking ` +
      "it merges the two and keeps your edits."));
  }
  const timeline = el(documentNode, "div", "wp-version-timeline");
  for (const [index, version] of ordered.entries()) {
    timeline.appendChild(versionRow(
      documentNode, workflow, version, ordered[index + 1], actions,
    ));
  }
  if (!ordered.length) {
    timeline.appendChild(el(documentNode, "p", "empty", "No published versions."));
  }
  body.appendChild(timeline);
  return host;
}
