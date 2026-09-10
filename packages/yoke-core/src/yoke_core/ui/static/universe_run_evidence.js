// The facts a run card or row shows beside a run that the run row itself
// does not carry: the QA checks recorded against it, with their artifacts,
// and the name of the flow it ran.
//
// A run row names its flow by id and carries evidence only inside a pending
// gate. The checks and their screenshots are QA activity rows keyed by the
// run, and the flow's name is on the flow definition, so both are read once
// per project and joined here rather than once per run.

import { settledScopedCalls } from "./universe_view_support.js";

const ACTIVITY_LIMIT = 100;

function groupByRun(rows) {
  const byRun = new Map();
  for (const row of rows) {
    const runId = row.deployment_run_id;
    if (!runId) continue;
    const entry = byRun.get(String(runId)) || { checks: [], artifacts: [] };
    entry.checks.push(row);
    for (const artifact of Array.isArray(row.artifacts) ? row.artifacts : []) {
      entry.artifacts.push({ ...artifact, requirement_id: row.requirement_id });
    }
    byRun.set(String(runId), entry);
  }
  return byRun;
}

function flowNamesOf(results) {
  const names = new Map();
  for (const result of results) {
    for (const flow of result?.flows || []) {
      if (flow?.id && flow.name) names.set(String(flow.id), String(flow.name));
    }
  }
  return names;
}

// `projectIds` are the project buckets in scope. Both reads refuse without a
// project, so an unscoped view passes every roster project.
export async function loadRunFacts(context, projectIds) {
  const buckets = [...new Set((projectIds || []).map(String).filter(Boolean))];
  const calls = buckets.flatMap((project) => [
    { functionId: "qa.activity.list", payload: { project, limit: ACTIVITY_LIMIT } },
    { functionId: "workflows.definition.get", payload: { project } },
  ]);
  const { callResults, failed } = await settledScopedCalls(context, calls);
  const results = callResults.map((callResult) => (
    callResult.status === 200 && callResult.envelope?.success
      ? callResult.envelope.result || {} : null
  ));
  const activity = results.filter((_, index) => index % 2 === 0).filter(Boolean);
  const flows = results.filter((_, index) => index % 2 === 1).filter(Boolean);
  return {
    evidence: groupByRun(activity.flatMap((result) => result.rows || [])),
    flowNames: flowNamesOf(flows),
    failed: failed ? failed.envelope?.error?.message || "QA evidence could not be loaded." : null,
  };
}

export const EMPTY_RUN_FACTS = Object.freeze({
  evidence: new Map(),
  flowNames: new Map(),
  failed: null,
});

export function runEvidence(facts, runId) {
  return facts?.evidence?.get(String(runId)) || { checks: [], artifacts: [] };
}

export function runFlowName(facts, row) {
  const id = String(row?.flow || "");
  return facts?.flowNames?.get(id) || id || "flow unavailable";
}

// The QA reviews still waiting on this reader, keyed by requirement, so a
// verification row or an activity row can point at the Inbox card that
// decides it. Only pending requests are served; a review already answered
// has no request to point at.
export async function loadPendingReviews(context, projectIds) {
  const ids = (projectIds || []).map(Number).filter(Number.isFinite);
  const { callResults, failed } = await settledScopedCalls(context, [{
    functionId: "inbox.list",
    payload: ids.length ? { project_ids: ids } : {},
  }]);
  const byRequirement = new Map();
  if (failed) return byRequirement;
  for (const row of callResults[0].envelope.result?.needs_decision || []) {
    if (row.kind !== "qa_needs_review") continue;
    const requirementId = row.subject_context?.requirement_id;
    if (requirementId != null) byRequirement.set(String(requirementId), row);
  }
  return byRequirement;
}

export const universeRunEvidence = {
  EMPTY_RUN_FACTS,
  loadPendingReviews,
  loadRunFacts,
  runEvidence,
  runFlowName,
};
