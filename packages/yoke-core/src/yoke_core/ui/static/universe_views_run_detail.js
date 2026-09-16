// One deployment run, in the shape of a page: where it is going, how far it
// has got, what its checks found, what it carries, and the one decision
// that is waiting on someone — if any.
//
// Reached from the Deployments table, the Overview's Shipping cards, and
// an Inbox release request. Everything on it is the run row the paged
// history read serves plus the QA activity recorded against the run.

import { createDecisionResolver } from "./inbox_rows.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import { deploymentRunsHref } from "./universe_navigation.js";
import { reviewRequestCard } from "./review_request_card.js";
import { evidenceStrip } from "./review_evidence_strip.js";
import { KIND_LABELS } from "./review_request_presentation.js";
import { carriedItems } from "./universe_overview_cards.js";
import {
  appendCarriedItemEvidence,
  EMPTY_CARRIED_ITEM_FACTS,
  loadCarriedItemEvidence,
} from "./universe_carried_item_evidence.js";
import { gateAsRequest, runGateStatus, runGates } from "./universe_run_gates.js";
import {
  appendRunAftermath,
  loadRunTarget,
  loadSiblingRuns,
  runIdentityCard,
} from "./universe_run_identity.js";
import { relativeAgePhrase } from "./universe_time.js";
import { RUNS_PAGE_SIZE } from "./universe_deployment_runs_loader.js";
import {
  callFunction,
  el,
  renderError,
  section,
  settledScopedCalls,
} from "./universe_view_support.js";

const STEP_MARKS = { complete: "✓", active: "◔", failed: "✕", stopped: "■" };

function projectFor(context, row, scope) {
  const projects = context.projects();
  return projects.find((candidate) => (
    [candidate.id, candidate.slug, candidate.name].some(
      (value) => String(value) === String(row?.project),
    )
  )) || (Array.isArray(scope) && scope.length === 1
    ? projects.find((candidate) => String(candidate.id) === String(scope[0]))
    : null);
}

function appendSteps(documentNode, host, stages) {
  const steps = el(documentNode, "div", "run-steps");
  (stages || []).forEach((stage, index) => {
    if (index) steps.appendChild(el(documentNode, "span", "run-arrow", "→"));
    const state = String(stage.state || "pending");
    const step = el(documentNode, "span", `run-step is-${state}`);
    step.appendChild(el(documentNode, "i", null, STEP_MARKS[state] || String(index + 1)));
    step.appendChild(el(documentNode, "span", null, String(stage.name)));
    steps.appendChild(step);
  });
  host.appendChild(steps);
}

function outcomeOf(check) {
  return String(check.outcome || "queued").replaceAll("_", " ");
}

// What the run's checks found, and the pictures they took.
function verificationCard(context, checks, artifacts) {
  const documentNode = context.document;
  const card = el(documentNode, "section", "run-card");
  const heading = el(documentNode, "h2", null, "Verification");
  if (checks.length) {
    const passed = checks.filter((check) => check.outcome === "passed").length;
    heading.appendChild(el(
      documentNode,
      `span`,
      `run-verdict ${passed === checks.length ? "is-approved" : "is-rejected"}`,
      `${passed} of ${checks.length} passed`,
    ));
  }
  card.appendChild(heading);
  if (!checks.length) {
    card.appendChild(el(
      documentNode, "p", "run-copy", "No checks were recorded on this run.",
    ));
  }
  for (const check of checks) {
    const line = el(documentNode, "div", `run-check is-${outcomeOf(check).replace(/ /g, "-")}`);
    line.appendChild(el(documentNode, "i", null, check.outcome === "passed" ? "✓" : "✕"));
    line.appendChild(el(
      documentNode, "b", null, [check.case_key, check.method_name].filter(Boolean).join(" · "),
    ));
    line.appendChild(el(documentNode, "span", null, outcomeOf(check)));
    // An agent's reason can run to a paragraph; it folds under the check so
    // the list stays a list and the reason stays one click away.
    if (check.verdict_reason) {
      const reason = el(documentNode, "details", "run-check-reason");
      reason.appendChild(el(documentNode, "summary", null, "What the agent said"));
      reason.appendChild(el(documentNode, "p", null, String(check.verdict_reason)));
      line.appendChild(reason);
    }
    card.appendChild(line);
  }
  const strip = evidenceStrip(context, artifacts, { compact: true });
  if (strip) card.appendChild(strip);
  return card;
}

function statusCopy(row, gate) {
  const status = String(row.status || "");
  if (gate) {
    return {
      title: gate.kind === "qa_needs_review" ? "Waiting for a review" : "Waiting for approval",
      copy: "",
    };
  }
  if (status === "failed") {
    return {
      title: "Stopped",
      copy: `The run stopped at ${row.current_stage || "a stage"}.`,
    };
  }
  if (status === "succeeded") {
    return { title: "Succeeded", copy: row.completed_at ? `Completed ${relativeAgePhrase(row.completed_at)}.` : "" };
  }
  if (status === "cancelled") return { title: "Cancelled", copy: "" };
  if (status === "created") return { title: "Not started", copy: "The run is created and has not begun." };
  return { title: "Running", copy: `${row.current_stage || "A stage"} is running. Nothing is waiting on you.` };
}

// What the run carries, and the decision waiting on it. Each carried item
// also shows its own QA and its own waiting review, which belong to the item
// rather than to the release moving it.
function decisionCard(context, row, project, onAct, evidenceShown, itemFacts, onItemDecision) {
  const documentNode = context.document;
  const card = el(documentNode, "section", "run-card");
  const items = carriedItems(row);
  // The member rows are drawn first because the release-level gate is
  // chosen from what they did NOT take: a member-scoped QA review belongs to
  // its member's row, and drawing it again here would offer one decision
  // twice on one page, with two sets of buttons.
  const drawnRequests = new Set();
  const list = el(documentNode, "div", "run-items");
  for (const item of items) {
    const ref = item.ref || item.public_ref || item.item_ref || `item ${item.item_id}`;
    const href = itemDrillInHref({
      projectId: item.project_id ?? project?.id,
      projectSequence: item.project_sequence,
      publicRef: ref,
    });
    const code = el(documentNode, href ? "a" : "code", "mono", ref);
    if (href) code.href = href;
    list.appendChild(code);
    list.appendChild(el(documentNode, "span", null, item.title || ""));
    const drawn = appendCarriedItemEvidence(context, list, {
      item,
      runId: row.id || row.run_id,
      facts: itemFacts,
      onDecide: onItemDecision,
    });
    for (const id of drawn?.requestIds || []) drawnRequests.add(id);
  }
  // Two different questions. The heading asks whether anything on this page
  // is waiting on somebody, which a member's own review answers just as well
  // as a release-level one; the block below asks which request this card
  // still has to draw itself.
  const gates = runGates(row);
  const gate = gates.find(
    (candidate) => !drawnRequests.has(String(candidate.request_id)),
  ) || null;
  const { title, copy } = statusCopy(row, gate || gates[0] || null);
  card.appendChild(el(documentNode, "h2", null, title));
  if (copy) card.appendChild(el(documentNode, "p", "run-copy", copy));
  if (items.length) {
    card.appendChild(list);
  } else if (row.carried_work && row.carried_work.derivation?.contents_known === false) {
    // An unanswered comparison and an empty release look identical once the
    // item list is empty, so the card says which one this is and what would
    // let it be answered.
    const derivation = row.carried_work.derivation;
    card.appendChild(el(
      documentNode,
      "p",
      "run-copy",
      `What this run carries is not known (${derivation.reason || "no reason recorded"}). `
      + (derivation.recovery || ""),
    ));
  } else if (!gate) {
    card.appendChild(el(
      documentNode, "p", "run-copy", "No items are attached to this run.",
    ));
  }
  if (gate) {
    card.appendChild(el(documentNode, "div", "run-request-kind", KIND_LABELS[gate.kind]));
    // A release approval's evidence is the run's own QA screenshots, which
    // the Verification card beside it already shows; a QA review's is its
    // own run's artifacts, so it keeps them.
    card.appendChild(reviewRequestCard(context, gateAsRequest(gate), {
      inline: true,
      evidence: !(evidenceShown && gate.kind === "deployment_stage_approval"),
      onAct: (request, action, node, note) => onAct(gate, action, node, note),
    }));
  }
  return card;
}

async function readRun(context, runId, scope) {
  const page = { page_size: RUNS_PAGE_SIZE, search: runId };
  if (Array.isArray(scope) && scope.length) page.projects = scope.map(String);
  const { callResults, failed } = await settledScopedCalls(context, [
    { functionId: "deployment_runs.list", payload: { page } },
  ]);
  if (failed) return { failed };
  const result = callResults[0].envelope.result || {};
  const row = (result.rows || []).find((candidate) => String(candidate.id) === String(runId));
  const flows = new Map((result.filters?.flows || []).map((flow) => [String(flow.id), flow.label]));
  return { row: row || null, flows };
}

export async function renderRunDetailView(context, main, scope, runId, navigation = {}) {
  const documentNode = context.document;
  if (typeof navigation.setDetailLabel === "function") navigation.setDetailLabel(String(runId));
  const loading = section(documentNode, String(runId));
  main.replaceChildren(loading);
  const read = await readRun(context, runId, scope);
  if (!context.isMounted()) return;
  if (read.failed) {
    loading.renderEnvelope(read.failed, (body) => renderError(body, read.failed));
    return;
  }
  if (!read.row) {
    loading.renderEnvelopes([], (body) => {
      body.appendChild(el(documentNode, "p", "empty", `There is no run called ${runId} in this scope.`));
      const back = el(documentNode, "a", "review-link", "Back to Deployments");
      back.href = deploymentRunsHref(Array.isArray(scope) ? scope.join(",") : null);
      body.appendChild(back);
    });
    return;
  }
  const row = read.row;
  const project = projectFor(context, row, scope);
  let checks = [];
  let artifacts = [];
  let itemFacts = EMPTY_CARRIED_ITEM_FACTS;
  if (project) {
    let activity;
    // The run's own checks and what its carried items proved on their own
    // are two reads about one page; neither waits on the other.
    const carried = loadCarriedItemEvidence(context, carriedItems(row).map(
      (item) => ({
        ...item,
        project_id: item.project_id ?? project.id,
        run_id: row.id || row.run_id,
      }),
    ));
    try {
      activity = await callFunction(context.client, "qa.activity.list", {
        project: String(project.id), deployment_run_id: String(runId), limit: 100,
      });
    } catch (error) {
      activity = { status: 0, envelope: { success: false, error: { message: String(error) } } };
    }
    if (activity.status === 200 && activity.envelope.success) {
      checks = activity.envelope.result?.rows || [];
      artifacts = checks.flatMap((check) => (check.artifacts || []).map(
        (artifact) => ({ ...artifact, requirement_id: check.requirement_id }),
      ));
    }
    itemFacts = await carried;
  }
  if (!context.isMounted()) return;

  const resolve = createDecisionResolver(
    context, () => renderRunDetailView(context, main, scope, runId, navigation),
  );
  const onAct = (gate, action, node, note) => resolve({ id: gate.request_id }, action, node, note);
  // A carried item's review is answered through the same resolver as the
  // run's own gate, so the page reloads on either.
  const onItemDecision = (request, action, node, note) => resolve(
    request, action, node, note,
  );
  // The run's binding and what else carried its work are two more reads about
  // one page; the aftermath block is the only thing that waits on them.
  const [environment, siblings] = await Promise.all([
    loadRunTarget(context, project, row.target_environment),
    loadSiblingRuns(context, project, carriedItems(row), runId),
  ]);
  if (!context.isMounted()) return;
  const status = runGateStatus(row) || String(row.status || "unknown");
  const items = carriedItems(row);
  const page = el(documentNode, "div", "run-page");
  page.appendChild(el(
    documentNode, "div", "run-eyebrow",
    [project?.slug || row.project, row.target_environment || row.target_tier].filter(Boolean).join(" · "),
  ));
  const head = el(documentNode, "div", "run-head");
  const copy = el(documentNode, "div");
  copy.appendChild(el(
    documentNode, "h1", "run-title", read.flows.get(String(row.flow)) || row.flow || "Deployment run",
  ));
  // The candidate commit lives on the Identity card whole; a truncated copy
  // here read like a second, shorter identity.
  copy.appendChild(el(documentNode, "div", "run-sub", [
    items.length ? `${items.length} item${items.length === 1 ? "" : "s"}` : "no attached items",
    String(row.id),
  ].filter(Boolean).join(" · ")));
  head.appendChild(copy);
  head.appendChild(el(
    documentNode, "span", `run-badge is-${status.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`, status,
  ));
  page.appendChild(head);
  appendSteps(documentNode, page, row.stages);
  const grid = el(documentNode, "div", "run-grid");
  grid.appendChild(runIdentityCard(context, row, environment));
  grid.appendChild(verificationCard(context, checks, artifacts));
  const decision = decisionCard(
    context, row, project, onAct, artifacts.length > 0, itemFacts, onItemDecision,
  );
  appendRunAftermath(context, decision, row, project, siblings);
  grid.appendChild(decision);
  page.appendChild(grid);
  main.replaceChildren(page);
}
