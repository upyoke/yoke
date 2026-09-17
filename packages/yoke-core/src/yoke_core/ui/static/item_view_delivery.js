// How one item ships: the flow it is bound to, and every release that has
// carried it.
//
// An item page could say what the work is and never say whether it had
// shipped, so the reader went to Deployments and searched for the ref. The
// releases are read through the item itself, newest first. A run on the
// selected (or default) flow is this item's release; a same-project run of
// another flow is participation and is labeled as such.

import {
  deploymentFlowHref,
  deploymentFlowsHref,
  deploymentRunHref,
} from "./universe_navigation.js";
import { relativeAgePhrase } from "./universe_time.js";
import { workflowPanel } from "./workflow_view_primitives.js";
import { callFunction, el, statePill } from "./universe_view_support.js";

// The definition this item would ship through. An explicit selection on the
// item wins; otherwise the effective per-project, per-workflow default the
// mechanics read serves is the answer. Neither is guessed: when the read
// carries no default for this item's workflow and project, the panel says the
// binding is unresolved rather than asserting one applies.
function flowLine(documentNode, item, resolved) {
  const line = el(documentNode, "div", "item-delivery-flow");
  line.appendChild(el(documentNode, "span", "item-delivery-label", "Flow"));
  if (resolved?.flowId) {
    const link = el(documentNode, "a", "mono", String(resolved.flowId));
    link.href = deploymentFlowHref(item.project.id, resolved.flowId);
    line.appendChild(link);
    line.appendChild(el(
      documentNode,
      "span",
      "item-delivery-flow-source",
      resolved.source === "item"
        ? "selected on this item"
        : "this project's default for its workflow",
    ));
    return line;
  }
  const unresolved = el(
    documentNode, "a", "item-delivery-default",
    resolved?.reason === "unreadable"
      ? "not selected on this item — its project default could not be read"
      : "not selected on this item, and its project declares no default for "
        + "this workflow",
  );
  unresolved.href = deploymentFlowsHref(item.project.id);
  line.appendChild(unresolved);
  return line;
}

// The effective binding, read from the same delivery defaults the Workflows
// mechanics screen shows. An unreadable read is reported as unreadable.
async function resolveFlow(context, item) {
  if (item.deployment_flow) {
    return { flowId: String(item.deployment_flow), source: "item" };
  }
  let result = null;
  try {
    const read = await callFunction(context.client, "workflows.mechanics.get", {});
    if (read.status === 200 && read.envelope.success) {
      result = read.envelope.result || {};
    }
  } catch {
    result = null;
  }
  if (!result) return { flowId: null, reason: "unreadable" };
  const workflowId = String(item.workflow?.id || "");
  const match = (result.delivery_defaults || []).find((row) => (
    String(row.workflow_id) === workflowId
    && (String(row.project_id) === String(item.project.id)
      || String(row.project) === String(item.project.slug))
  ));
  return match
    ? { flowId: String(match.flow_id), source: "project_default" }
    : { flowId: null, reason: "none_declared" };
}

function deliveryRow(documentNode, item, run, resolved) {
  const row = el(documentNode, "div", "item-delivery-run");
  const link = el(documentNode, "a", "mono", String(run.id));
  link.href = deploymentRunHref(item.project.id, run.id);
  row.appendChild(link);
  const pill = statePill(documentNode, run.status, run.status);
  if (pill) row.appendChild(pill);
  const selectedFlow = resolved?.flowId ? String(resolved.flowId) : "";
  const runFlow = String(run.flow || "");
  const isRelease = Boolean(selectedFlow && runFlow === selectedFlow);
  row.appendChild(el(
    documentNode,
    "span",
    isRelease ? "item-delivery-role is-release" : "item-delivery-role",
    isRelease ? "this item's release" : "also carried",
  ));
  if (runFlow) {
    row.appendChild(el(
      documentNode, "span", "item-delivery-run-flow", runFlow,
    ));
  }
  if (run.current_stage) {
    row.appendChild(el(
      documentNode, "span", "item-delivery-stage", String(run.current_stage),
    ));
  }
  if (run.created_at) {
    row.appendChild(el(
      documentNode,
      "span",
      "item-delivery-when",
      relativeAgePhrase(run.created_at),
    ));
  }
  return row;
}

// Newest first. A run with no timestamp sorts last rather than being dropped:
// the record of the delivery is the fact, its ordering is the convenience.
function newestFirst(rows) {
  return [...rows].sort((left, right) => String(right.created_at || "")
    .localeCompare(String(left.created_at || "")));
}

export function itemDeliveryPanel(context, item) {
  const documentNode = context.document;
  const { panel, body } = workflowPanel(documentNode, "Delivery");
  const flowHost = el(documentNode, "div", "item-delivery-flow-host");
  flowHost.appendChild(el(documentNode, "span", "item-muted", "resolving flow…"));
  body.appendChild(flowHost);
  const runs = el(documentNode, "div", "item-delivery-runs", "loading releases…");
  body.appendChild(runs);
  const resolvedFlow = resolveFlow(context, item);
  resolvedFlow.then((resolved) => {
    if (!context.isMounted()) return;
    flowHost.replaceChildren(flowLine(documentNode, item, resolved));
  });
  (async () => {
    const resolved = await resolvedFlow;
    let result = null;
    try {
      const read = await callFunction(
        context.client, "deployment_runs.find_by_item", {},
        {
          kind: "item",
          public_ref: String(item.public_ref),
          project_id: String(item.project.id),
        },
      );
      if (read.status === 200 && read.envelope.success) {
        result = read.envelope.result || {};
      }
    } catch {
      result = null;
    }
    if (!context.isMounted()) return;
    if (!result) {
      runs.replaceChildren(el(
        documentNode,
        "p",
        "item-muted",
        "Releases for this item could not be read.",
      ));
      return;
    }
    const rows = newestFirst(result.rows || []);
    if (!rows.length) {
      runs.replaceChildren(el(
        documentNode, "p", "item-muted", "No release has carried this item.",
      ));
      return;
    }
    runs.replaceChildren(
      ...rows.map((run) => deliveryRow(documentNode, item, run, resolved)),
    );
  })();
  return panel;
}
