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
import { caseEvidencePanel } from "./qa_case_evidence_panel.js";
import { qaCaseName } from "./qa_case_name.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import { deploymentRunHref } from "./universe_navigation.js";
import { reviewRequestCard } from "./review_request_card.js";
import { loadPendingReviews } from "./universe_run_evidence.js";
import { relativeAgePhrase } from "./universe_time.js";
import { el } from "./universe_view_support.js";
import { readCase, readOptionalCase, retryCaseButton } from "./qa_case_reads.js";
import {
  detailHead,
  keyValuePanel,
  outcomeNode,
  qaRoute,
  showFailure,
} from "./qa_view_primitives.js";

// Every run this case recorded, with the native-selected attempt first. The activity table joins
// each requirement to its LATEST run alone, so it can say what happened most
// recently and never what happened before that; the case's own run list is
// the complete record, and a repeated execution belongs on the page rather
// than being replaced by the one that followed it.
async function loadExecutions(context, requirementId) {
  const result = await readCase(
    context, "qa.run.list", { requirement_id: Number(requirementId) },
    { kind: "qa_requirement", qa_requirement_id: Number(requirementId) },
  );
  return result?.rows || [];
}

// Artifacts are resolved through the activity read's shared evidence chain,
// which is keyed by subject rather than by requirement. When that read does
// not carry this case, evidence is unavailable — which is a different answer
// from the case never having run, and the page must not confuse them.
async function loadEvidenceRow(context, projects, requirement, requirementId) {
  const payloads = [];
  for (const project of projects) {
    if (requirement?.public_ref) {
      payloads.push({ project, public_refs: [requirement.public_ref] });
    }
    if (requirement?.deployment_run_id) {
      payloads.push({ project, deployment_run_id: String(requirement.deployment_run_id) });
    }
    if (requirement?.deployment_member_public_ref) {
      payloads.push({
        project, public_refs: [requirement.deployment_member_public_ref],
      });
    }
  }
  for (const payload of payloads) {
    const result = await readOptionalCase(context, "qa.activity.list", payload);
    const row = (result?.rows || []).find(
      (candidate) => String(candidate.requirement_id) === String(requirementId),
    );
    if (row) return row;
  }
  return null;
}

// The subject's own id, not a name a reader can use: a requirement carries
// the public item ref, and the public ref that addresses the item lives on
// the item. One read turns the first into the second.
function subjectItemId(requirement, row) {
  const id = row?.public_ref ?? requirement?.public_ref
    ?? row?.deployment_member_public_ref ?? requirement?.deployment_member_public_ref;
  return id ?? null;
}

async function loadSubjectItem(context, project, itemId) {
  if (!itemId) return null;
  const result = await readOptionalCase(
    context, "items.detail.get", {},
    { kind: "item", public_ref: itemId, project_id: String(project) },
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

async function loadQaCaseDetail(
  context, main, project, requirementId, navigation = {},
) {
  context = { ...context, caseReadFailures: [] };
  const documentNode = context.document;
  main.replaceChildren(el(documentNode, "p", "empty", "loading QA case…"));
  const definition = await readCase(
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
  const subjectItem = await loadSubjectItem(
    context, project, subjectItemId(requirement, null),
  );
  if (!context.isMounted()) return;
  // A release carries items from other projects; a carried item's check is
  // read under the item's own project when the page's project lacks it.
  const evidenceProjects = [...new Set([
    String(project), subjectItem?.project?.slug, subjectItem?.project?.id,
  ].filter((value) => value != null && value !== "").map(String))];
  const [executions, row, stages, pending] = await Promise.all([
    loadExecutions(context, requirementId),
    loadEvidenceRow(context, evidenceProjects, requirement, requirementId),
    requirement.deployment_run_id
      ? readOptionalCase(context, "deployment_runs.stages", {}, {
        kind: "workflow_run",
        workflow_run_id: String(requirement.deployment_run_id),
      })
      : Promise.resolve(null),
    loadPendingReviews(context, [project]),
  ]);
  if (!context.isMounted()) return;
  // The newest execution is the case's current answer; the ones before it are
  // its history, and both come from the case's own complete run list rather
  // than from a page of recent activity that may not carry either.
  const latest = executions[0] || null;
  const earlier = executions.slice(1);
  const stage = (stages?.stages || []).find(
    (candidate) => String(candidate.name) === String(requirement.deployment_stage),
  ) || null;
  // The same name the activity table links: what ran, against what.
  const caseName = qaCaseName(
    { ...requirement, ...(row || {}), requirement_id: requirementId },
    subjectItem?.public_ref,
  );
  if (typeof navigation.setDetailLabel === "function") {
    navigation.setDetailLabel(caseName);
  }

  const facts = [
    ["Subject", subjectNode(documentNode, project, requirement, row, subjectItem)],
    ["Scope", requirement.deployment_member_public_ref || requirement.public_ref
      ? "item" : requirement.deployment_run_id ? "release" : "standalone"],
    // The environment the check was pointed at, as its frozen execution
    // target names it. A release check against a run preview registers no
    // environment of its own, and reading the project's current one instead
    // would name a place this case never ran.
    [
      "Environment",
      requirement.execution_environment || requirement.target_env
        || "not recorded",
    ],
    ["Stage execution", stageNode(documentNode, project, requirement, stage)],
    ["Method", row?.method_name || requirement.method_name || requirement.method_id],
    [
      "Outcome",
      latest
        ? outcomeNode(
          documentNode, latest.case_outcome, latest.capture_degraded_reason,
        )
        : "never run",
    ],
    [
      "Recorded",
      latest?.completed_at || latest?.created_at
        ? relativeAgePhrase(latest.completed_at || latest.created_at)
        : "never run",
    ],
  ];
  if (earlier.length) {
    facts.push([
      "Earlier executions",
      `${earlier.length} before this one`,
    ]);
  }
  if (requirement.execution_candidate_revision) {
    facts.push([
      "Candidate", String(requirement.execution_candidate_revision),
    ]);
  }
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

  host.appendChild(caseEvidencePanel(context, { row, latest, requirementId }));
  if (context.caseReadFailures.length) {
    const notice = el(documentNode, "p", "qa-action-error", "Some case details are unavailable. Retry to load them.");
    notice.setAttribute("role", "status");
    host.appendChild(notice);
    host.appendChild(retryCaseButton(context, () => renderQaCaseDetail(context, main, project, requirementId, navigation)));
  }

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

export async function renderQaCaseDetail(context, main, project, requirementId, navigation = {}) {
  try {
    await loadQaCaseDetail(context, main, project, requirementId, navigation);
  } catch (error) {
    if (!context.isMounted()) return;
    showFailure(context.document, main, error.callResult || {
      status: 0,
      envelope: { success: false, error: { message: `QA details unavailable: ${error.message || error}` } },
    });
    main.appendChild(retryCaseButton(context, () => renderQaCaseDetail(context, main, project, requirementId, navigation)));
  }
}
