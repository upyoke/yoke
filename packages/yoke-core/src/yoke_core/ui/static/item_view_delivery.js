// Run roles use the same completion authority as the item done gate.

import {
  deploymentFlowHref,
  deploymentFlowsHref,
  deploymentRunHref,
} from "./universe_navigation.js";
import { relativeAgePhrase } from "./universe_time.js";
import { flowId } from "./universe_item_deployment.js";
import { NO_ENVIRONMENT_LABEL } from "./deployment_environment_copy.js";
import { workflowPanel } from "./workflow_view_primitives.js";
import { callFunction, el, statePill } from "./universe_view_support.js";

// The definition this item would ship through. An explicit selection on the
// item wins; otherwise the effective per-project, per-workflow default the
// mechanics read serves is the answer. Neither is guessed: when the read
// carries no default for this item's workflow and project, the panel says the
// binding is unresolved rather than asserting one applies.
function flowLine(documentNode, item, resolved, deliveredByOtherFlow = false) {
  const line = el(documentNode, "div", "item-delivery-flow");
  line.appendChild(el(documentNode, "span", "item-delivery-label", "Item’s flow"));
  if (resolved?.flowId) {
    const link = el(documentNode, "a", "mono", String(resolved.flowId));
    link.href = deploymentFlowHref(item.project.id, resolved.flowId);
    line.appendChild(link);
    line.appendChild(el(
      documentNode,
      "span",
      "item-delivery-flow-source",
      deliveredByOtherFlow
        ? "not used: delivered by the run above"
        : resolved.source === "item"
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
  if (Object.prototype.hasOwnProperty.call(item, "completion_flow_source")) {
    return {
      flowId: String(item.completion_flow || "") || null,
      source: item.completion_flow_source,
      reason: item.completion_flow_source === "unreadable" ? "unreadable" : "none_declared",
    };
  }
  if (flowId(item.deployment_flow)) {
    return { flowId: flowId(item.deployment_flow), source: "item" };
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

function deliveryRow(documentNode, item, run, completion) {
  const row = el(documentNode, "div", "item-delivery-run");
  const link = el(documentNode, "a", "mono", String(run.id));
  link.href = deploymentRunHref(item.project.id, run.id);
  row.appendChild(link);
  const pill = statePill(documentNode, run.status, run.status);
  if (pill) row.appendChild(pill);
  const closesItem = String(completion?.id || "") === String(run.id);
  const delivered = closesItem && completion.status === "succeeded";
  row.appendChild(el(
    documentNode, "span",
    closesItem ? "item-delivery-role is-release" : "item-delivery-role",
    delivered ? "Delivered by" : closesItem ? "Delivering" : "Also in",
  ));
  const flow = el(documentNode, "div", "item-delivery-run-flow");
  flow.appendChild(el(documentNode, "span", "mono", String(run.flow || "")));
  flow.appendChild(el(documentNode, "span", "", " → "));
  flow.appendChild(el(
    documentNode, "span", "item-delivery-target",
    run.target_environment || run.target_tier || NO_ENVIRONMENT_LABEL,
  ));
  row.appendChild(flow);
  const terminal = ["succeeded", "cancelled", "failed"].includes(run.status);
  const timestamp = terminal ? run.completed_at : run.started_at || run.created_at;
  const when = terminal
    ? `${run.status === "succeeded" ? "finished" : "ended"} ${timestamp
      ? relativeAgePhrase(timestamp) : "time unavailable"}`
    : `${run.current_stage ? `at ${run.current_stage} · ` : ""}started ${timestamp
      ? relativeAgePhrase(timestamp) : "time unavailable"}`;
  row.appendChild(el(documentNode, "span", "item-delivery-when", when));
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
  const runs = el(documentNode, "div", "item-delivery-runs", "loading releases…");
  body.appendChild(runs);
  body.appendChild(flowHost);
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
    // Older serving builds omit completion_run: report participation until
    // authority is available rather than guessing it from a flow name.
    const completion = result.completion_run || null;
    const deliveredRun = rows.find((run) => run.id === completion?.id
      && completion.status === "succeeded");
    if (deliveredRun && String(deliveredRun.flow) === resolved?.flowId) {
      flowHost.replaceChildren();
    } else {
      flowHost.replaceChildren(flowLine(documentNode, item, resolved, Boolean(deliveredRun)));
    }
    if (!rows.length) {
      runs.replaceChildren(el(
        documentNode, "p", "item-muted", "No release has carried this item.",
      ));
      return;
    }
    runs.replaceChildren(
      ...rows.map((run) => deliveryRow(documentNode, item, run, completion)),
    );
  })();
  return panel;
}
