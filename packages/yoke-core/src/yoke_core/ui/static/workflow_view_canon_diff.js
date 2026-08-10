import { el, callFunction } from "./universe_view_support.js";
import {
  button,
  readablePolicyValue,
} from "./workflow_view_primitives.js";

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

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.keys(value).sort().map((key) => [key, canonicalValue(value[key])]),
  );
}

function sameValue(left, right) {
  return JSON.stringify(canonicalValue(left)) ===
    JSON.stringify(canonicalValue(right));
}

function gateMap(stage) {
  return new Map(
    (stage?.gates || []).map((gate) => [String(gate.id), gate]),
  );
}

function stageChanges(mine, theirs) {
  const changes = [];
  const before = stageMap(mine);
  const after = stageMap(theirs);
  const stages = listDifference([...before.keys()], [...after.keys()]);
  for (const id of stages.added) changes.push(`stage added: ${id}`);
  for (const id of stages.removed) changes.push(`stage removed: ${id}`);
  if (!stages.added.length && !stages.removed.length && !sameValue(
    [...before.keys()], [...after.keys()],
  )) {
    changes.push(`stage order: ${[...before.keys()].join(" → ")} → ` +
      [...after.keys()].join(" → "));
  }
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
    const beforeGates = gateMap(stage);
    const afterGates = gateMap(other);
    for (const [gateId, gate] of beforeGates) {
      if (afterGates.has(gateId) && !sameValue(gate, afterGates.get(gateId))) {
        changes.push(`${id}: gate changed: ${gateId}`);
      }
    }
    const stageDetails = (value) => {
      const { id: _id, label: _label, gates: _gates, ...details } = value;
      return details;
    };
    if (!sameValue(stageDetails(stage), stageDetails(other))) {
      changes.push(`${id}: stage details changed`);
    }
  }
  return changes;
}

function policyChanges(mine, theirs) {
  const changes = [];
  const before = mine?.policies || {};
  const after = theirs?.policies || {};
  for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
    const leftValue = before[key];
    const rightValue = after[key];
    if (sameValue(leftValue, rightValue)) continue;
    const label = key.replaceAll("_", " ");
    const describe = (value) => {
      if (value && typeof value === "object" && !Array.isArray(value)) {
        const count = Object.keys(value).length;
        return count ? count + " configured" : "none configured";
      }
      return readablePolicyValue(key, value);
    };
    if (leftValue === undefined) {
      changes.push(`policy added: ${label} = ${describe(rightValue)}`);
    } else if (rightValue === undefined) {
      changes.push(`policy removed: ${label}`);
    } else {
      changes.push(
        `policy ${label}: ${describe(leftValue)} → ${describe(rightValue)}`,
      );
    }
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
    if (actions.takeUpdate) {
      body.appendChild(takeUpdateControl(documentNode, workflow, actions));
    }
    host.appendChild(body);
    reveal.disabled = false;
    reveal.textContent = "Hide";
  });
  return host;
}

// The update is offered next to the diff and only after the merge has been
// previewed, so nothing is ever applied that the operator has not seen. A
// conflicted merge offers nothing to click: there is no correct automatic
// resolution, and pretending otherwise would silently pick a side.
function takeUpdateControl(documentNode, workflow, actions) {
  const wrap = el(documentNode, "div", "workflow-diff-apply");
  const take = button(documentNode, "Take this update", "workflow-button primary");
  const note = el(documentNode, "p", "workflow-diff-apply-note");
  wrap.appendChild(take);
  wrap.appendChild(note);

  take.addEventListener("click", async () => {
    take.disabled = true;
    take.textContent = "Checking…";
    note.textContent = "";
    note.classList.remove("error");
    let preview;
    try {
      preview = await callFunction(
        actions.client,
        "workflows.canon_update.preview",
        { workflow_id: workflow.id },
      );
    } catch (failure) {
      note.textContent = String(failure);
      note.classList.add("error");
      take.disabled = false;
      take.textContent = "Retry";
      return;
    }
    const merged = preview.envelope?.result;
    if (preview.status !== 200 || !preview.envelope.success) {
      note.textContent =
        preview.envelope?.error?.message || "Could not preview the update.";
      note.classList.add("error");
      take.disabled = false;
      take.textContent = "Retry";
      return;
    }
    if (!merged.clean) {
      note.textContent =
        "This update and your edits both change: " +
        merged.conflicts.map((conflict) => conflict.path).join(", ") +
        ". Resolve those by editing the workflow, then take the update.";
      note.classList.add("error");
      // Stays clickable: the operator resolves the conflict by editing, and
      // needs to be able to check again without reloading the page.
      take.disabled = false;
      take.textContent = "Check again";
      return;
    }
    take.textContent = "Applying…";
    const applied = await actions.takeUpdate(workflow, merged);
    if (applied?.error) {
      note.textContent = applied.error;
      note.classList.add("error");
      take.disabled = false;
      take.textContent = "Retry";
      return;
    }
    take.textContent = "Applied";
    note.textContent = merged.kept.length
      ? `Your edits were preserved: ${merged.kept.join(", ")}.`
      : "";
  });
  return wrap;
}
