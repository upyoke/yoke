// One QA case, as the page an Activity row opens.
//
// A row in the activity table says a case ran and how it came out. What it
// cannot say is what the case was asked to prove, which subject it answers
// for, and — when it ran inside a release — which stage execution decided
// whether a person had to look at it. Those are three different records, so
// the page reads all three and attributes each fact to its own owner.
//
// The verdict policy in particular belongs to the stage execution, not to the
// case definition: the same method, run under two stages, can be agent-judged
// in one and require a named reviewer in the other.

import { createDecisionResolver } from "./inbox_rows.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import { deploymentRunHref } from "./universe_navigation.js";
import { evidenceStrip } from "./review_evidence_strip.js";
import { reviewRequestCard } from "./review_request_card.js";
import { loadPendingReviews } from "./universe_run_evidence.js";
import { relativeAgePhrase } from "./universe_time.js";
import { callFunction, el } from "./universe_view_support.js";
import {
  detailHead,
  keyValuePanel,
  outcomeNode,
  qaRoute,
  showFailure,
} from "./qa_view_primitives.js";

async function read(context, functionId, payload, target) {
  try {
    const result = await callFunction(context.client, functionId, payload, target);
    if (result.status === 200 && result.envelope.success) {
      return result.envelope.result || {};
    }
    return null;
  } catch {
    return null;
  }
}

// The activity read is keyed by subject, not by requirement, so the case's
// own record names the subject to read and the row is picked out of it. A
// standalone case names neither, and falls back to the project's recency
// page — which is where a subject-less case is listed anyway.
async function loadActivityRow(context, project, requirement, requirementId) {
  const payloads = [];
  if (requirement?.item_id) {
    payloads.push({ project, item_ids: [Number(requirement.item_id)] });
  }
  if (requirement?.deployment_run_id) {
    payloads.push({ project, deployment_run_id: String(requirement.deployment_run_id) });
  }
  payloads.push({ project, limit: 200 });
  for (const payload of payloads) {
    const result = await read(context, "qa.activity.list", payload);
    const row = (result?.rows || []).find(
      (candidate) => String(candidate.requirement_id) === String(requirementId),
    );
    if (row) return row;
  }
  return null;
}

// The subject's own id, not a name a reader can use: a requirement carries
// the internal item id, and the public ref that addresses the item lives on
// the item. One read turns the first into the second.
function subjectItemId(requirement, row) {
  const id = row?.item_id ?? requirement?.item_id
    ?? row?.deployment_member_item_id ?? requirement?.deployment_member_item_id;
  const number = Number(id);
  return Number.isFinite(number) && number > 0 ? number : null;
}

async function loadSubjectItem(context, project, itemId) {
  if (!itemId) return null;
  const result = await read(
    context, "items.detail.get", {},
    { kind: "item", item_id: itemId, project_id: String(project) },
  );
  return result?.item || null;
}

function subjectNode(documentNode, project, requirement, row, item) {
  if (item) {
    const href = itemDrillInHref({
      projectId: item.project?.id ?? project,
      publicRef: item.public_ref,
    });
    const node = el(
      documentNode, href ? "a" : "span", "mono", String(item.public_ref),
    );
    if (href) node.href = href;
    const wrap = el(documentNode, "span");
    wrap.appendChild(node);
    if (item.title) wrap.appendChild(el(documentNode, "span", null, ` ${item.title}`));
    return wrap;
  }
  const runId = row?.deployment_run_id || requirement?.deployment_run_id;
  if (runId) {
    const link = el(documentNode, "a", "mono", String(runId));
    link.href = deploymentRunHref(project, runId);
    return link;
  }
  // Standalone QA answers for itself. Saying so keeps it from reading as a
  // release check that happens to be missing its release.
  return "standalone — not bound to an item or a release";
}

function stageNode(documentNode, project, requirement, stage) {
  const runId = requirement?.deployment_run_id;
  const stageName = requirement?.deployment_stage;
  if (!runId || !stageName) return "not part of a release";
  const wrap = el(documentNode, "span");
  const link = el(documentNode, "a", "mono", String(runId));
  link.href = deploymentRunHref(project, runId);
  wrap.appendChild(link);
  wrap.appendChild(el(documentNode, "span", null, ` · ${stageName}`));
  const verdict = stage?.verdict?.mode;
  if (verdict) {
    wrap.appendChild(el(
      documentNode,
      "span",
      "qa-case-stage-policy",
      ` · verdict ${String(verdict).replaceAll("_", " ")} (set by this stage)`,
    ));
  }
  return wrap;
}

export async function renderQaCaseDetail(
  context, main, project, requirementId, navigation = {},
) {
  const documentNode = context.document;
  main.replaceChildren(el(documentNode, "p", "empty", "loading QA case…"));
  const definition = await read(
    context, "qa.requirement.get", {},
    { kind: "qa_requirement", qa_requirement_id: Number(requirementId) },
  );
  if (!context.isMounted()) return;
  const requirement = definition?.requirement || null;
  if (!requirement) {
    showFailure(documentNode, main, {
      status: 404,
      envelope: {
        success: false,
        error: { message: `There is no QA case ${requirementId} in this project.` },
      },
    });
    return;
  }
  const subjectId = subjectItemId(requirement, null);
  const [row, stages, pending, subjectItem] = await Promise.all([
    loadActivityRow(context, String(project), requirement, requirementId),
    requirement.deployment_run_id
      ? read(context, "deployment_runs.stages", {}, {
        kind: "workflow_run",
        workflow_run_id: String(requirement.deployment_run_id),
      })
      : Promise.resolve(null),
    loadPendingReviews(context, [project]),
    loadSubjectItem(context, project, subjectId),
  ]);
  if (!context.isMounted()) return;
  const stage = (stages?.stages || []).find(
    (candidate) => String(candidate.name) === String(requirement.deployment_stage),
  ) || null;
  const caseName = String(
    row?.case_key || requirement.plan_case_key || `case ${requirementId}`,
  );
  if (typeof navigation.setDetailLabel === "function") {
    navigation.setDetailLabel(caseName);
  }

  const facts = [
    ["Subject", subjectNode(documentNode, project, requirement, row, subjectItem)],
    ["Scope", requirement.deployment_member_item_id || requirement.item_id
      ? "item" : requirement.deployment_run_id ? "release" : "standalone"],
    ["Environment", requirement.target_env || "not recorded"],
    ["Stage execution", stageNode(documentNode, project, requirement, stage)],
    ["Method", row?.method_name || requirement.method_name || requirement.method_id],
    [
      "Outcome",
      row
        ? outcomeNode(documentNode, row.outcome, row.capture_degraded_reason)
        : "no run recorded",
    ],
    ["Recorded", row?.happened_at ? relativeAgePhrase(row.happened_at) : "never run"],
  ];
  if (row?.host_baseline) facts.push(["Host baseline", String(row.host_baseline)]);
  if (requirement.waived_at) {
    facts.push(["Waived", String(requirement.waiver_rationale || requirement.waived_at)]);
  }

  const host = el(documentNode, "div", "qa-case-detail");
  host.appendChild(detailHead(
    documentNode,
    caseName,
    `QA case · plan ${row?.plan || requirement.plan_id || "none"}`,
  ));
  host.appendChild(keyValuePanel(documentNode, "Case", facts));
  host.appendChild(keyValuePanel(documentNode, "What it had to prove", [
    ["Objective", requirement.instructions || "no instruction recorded"],
    ["Expected", requirement.expected_outcome || "no expected outcome recorded"],
  ]));

  const evidence = el(documentNode, "section", "panel qa-case-evidence");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, "Evidence"));
  evidence.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  const strip = evidenceStrip(context, row?.artifacts || [], {
    requirementId: Number(requirementId),
  });
  if (strip) body.appendChild(strip);
  for (const [label, value] of [
    ["What the agent said", row?.verdict_reason],
    ["Capture degraded", row?.capture_degraded_reason],
    ["Blocked on precondition", row?.precondition_reason],
  ]) {
    if (!value) continue;
    const line = el(documentNode, "p", "qa-case-reason");
    line.appendChild(el(documentNode, "strong", null, `${label}: `));
    line.appendChild(el(documentNode, "span", null, String(value)));
    body.appendChild(line);
  }
  if (!strip && !body.children.length) {
    body.appendChild(el(documentNode, "p", "empty", "No evidence was captured."));
  }
  evidence.appendChild(body);
  host.appendChild(evidence);

  const request = pending.get(String(requirementId));
  if (request) {
    const resolve = createDecisionResolver(
      context,
      () => renderQaCaseDetail(context, main, project, requirementId, navigation),
    );
    const review = el(documentNode, "section", "panel qa-case-review");
    const reviewHead = el(documentNode, "div", "panel-header");
    reviewHead.appendChild(el(documentNode, "h2", null, "Waiting on you"));
    review.appendChild(reviewHead);
    const reviewBody = el(documentNode, "div", "panel-body");
    reviewBody.appendChild(reviewRequestCard(context, request, {
      inline: true, onAct: resolve,
    }));
    review.appendChild(reviewBody);
    host.appendChild(review);
  }

  const back = el(documentNode, "a", "review-link", "Back to QA activity");
  back.href = qaRoute(context, "activity", null, project);
  host.appendChild(back);
  main.replaceChildren(host);
}
