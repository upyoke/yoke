import { el, callFunction } from "./universe_view_support.js";
import { button } from "./workflow_view_primitives.js";

// What actually differs between two workflow definitions, in the vocabulary
// the operator already reads on this page -- stages, gates, policies, entry
// surfaces, skill bindings. A textual JSON diff would be honest and useless:
// key order and nesting depth would dominate, and the reader wants to know
// "a gate moved", not "line 214 changed".

function stageMap(definition) {
  return new Map(
    (definition?.stages || []).map((stage) => [String(stage.id), stage]),
  );
}

function gateIds(stage) {
  return (stage?.gates || []).map((gate) => String(gate.id)).sort();
}

function listDifference(before, after) {
  const beforeSet = new Set(before);
  const afterSet = new Set(after);
  return {
    added: after.filter((value) => !beforeSet.has(value)),
    removed: before.filter((value) => !afterSet.has(value)),
  };
}

function stageChanges(mine, theirs) {
  const changes = [];
  const before = stageMap(mine);
  const after = stageMap(theirs);
  const stages = listDifference([...before.keys()], [...after.keys()]);
  for (const id of stages.added) changes.push(`stage added: ${id}`);
  for (const id of stages.removed) changes.push(`stage removed: ${id}`);
  for (const [id, stage] of before) {
    const other = after.get(id);
    if (!other) continue;
    if (String(stage.label || "") !== String(other.label || "")) {
      changes.push(
        `${id}: label "${stage.label}" → "${other.label}"`,
      );
    }
    const gates = listDifference(gateIds(stage), gateIds(other));
    for (const gate of gates.added) changes.push(`${id}: gate added: ${gate}`);
    for (const gate of gates.removed) {
      changes.push(`${id}: gate removed: ${gate}`);
    }
  }
  return changes;
}

function policyChanges(mine, theirs) {
  const changes = [];
  const before = mine?.policies || {};
  const after = theirs?.policies || {};
  for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
    const left = JSON.stringify(before[key]);
    const right = JSON.stringify(after[key]);
    if (left === right) continue;
    if (left === undefined) changes.push(`policy added: ${key} = ${right}`);
    else if (right === undefined) changes.push(`policy removed: ${key}`);
    else changes.push(`policy ${key}: ${left} → ${right}`);
  }
  return changes;
}

function bindingChanges(mine, theirs) {
  const describe = (definition) =>
    (definition?.skill_bindings || []).map((binding) =>
      `${binding.skill_id}: ${binding.from_stage_id}→${binding.through_stage_id}`
    );
  const changed = listDifference(describe(mine), describe(theirs));
  return [
    ...changed.added.map((value) => `binding added: ${value}`),
    ...changed.removed.map((value) => `binding removed: ${value}`),
  ];
}

export function definitionChanges(mine, theirs) {
  const surfaces = listDifference(
    mine?.entry_surfaces || [], theirs?.entry_surfaces || [],
  );
  return [
    ...stageChanges(mine, theirs),
    ...policyChanges(mine, theirs),
    ...bindingChanges(mine, theirs),
    ...surfaces.added.map((value) => `entry surface added: ${value}`),
    ...surfaces.removed.map((value) => `entry surface removed: ${value}`),
  ];
}

function changeList(documentNode, changes) {
  const list = el(documentNode, "ul", "workflow-diff-list");
  for (const change of changes) {
    list.appendChild(el(documentNode, "li", "workflow-diff-change", change));
  }
  return list;
}

export function renderCanonDiff(documentNode, workflow, actions) {
  const status = workflow.canon_status;
  const behind = status?.state === "update_available" ||
    status?.state === "customized_update_available";
  if (!behind) return null;

  const host = el(documentNode, "div", "workflow-canon-diff");
  const reveal = button(
    documentNode, "See what changed", "workflow-button compact",
  );
  host.appendChild(reveal);

  reveal.addEventListener("click", async () => {
    if (reveal.disabled) return;
    const shown = host.querySelector(".workflow-diff-body");
    if (shown) {
      host.removeChild(shown);
      reveal.textContent = "See what changed";
      return;
    }
    reveal.disabled = true;
    reveal.textContent = "Loading…";
    const body = el(documentNode, "div", "workflow-diff-body");
    const fail = (message) => {
      body.classList.add("error");
      body.textContent = message;
      host.appendChild(body);
      reveal.disabled = false;
      reveal.textContent = "Retry";
    };
    let result;
    try {
      result = await callFunction(
        actions.client, "workflows.canon.get", { workflow_id: workflow.id },
      );
    } catch (failure) {
      fail(String(failure));
      return;
    }
    if (result.status !== 200 || !result.envelope.success) {
      fail(result.envelope?.error?.message || "Could not read the Yoke version.");
      return;
    }
    const theirs = result.envelope.result?.definition || {};
    const changes = definitionChanges(workflow.definition, theirs);
    body.appendChild(el(
      documentNode,
      "p",
      "workflow-diff-heading",
      changes.length
        ? `What Yoke version ${status.latest_canon_version} changes, ` +
          `against what this universe runs:`
        : `Yoke version ${status.latest_canon_version} makes no change this ` +
          `view surfaces — the definitions differ only in detail it does not ` +
          `render.`,
    ));
    if (changes.length) body.appendChild(changeList(documentNode, changes));
    if (status.state === "customized_update_available") {
      // Saying this next to the diff, not only in the status line, because
      // this is the moment someone is deciding whether to take the update.
      body.appendChild(el(
        documentNode,
        "p",
        "workflow-diff-merge-note",
        "This universe has its own edits on top of Yoke version " +
          `${status.derived_from_canon_version}. Taking this update means ` +
          "merging the two, so your edits are preserved rather than replaced.",
      ));
    }
    host.appendChild(body);
    reveal.disabled = false;
    reveal.textContent = "Hide";
  });
  return host;
}
