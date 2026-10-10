// Shipping renders deployment runs as first-class cards, including the work
// each release carries, the request each is waiting on, and the QA evidence
// its checks captured.

import { createDecisionResolver } from "./inbox_rows.js";
import {
  carriedItems,
  runProjectId,
  shippingRunCard,
} from "./universe_work_cards.js";
import {
  EMPTY_CARRIED_ITEM_FACTS,
  loadCarriedItemEvidence,
} from "./universe_carried_item_evidence.js";
import {
  callError,
  successfulResult,
} from "./universe_band_primitives.js";
import { EMPTY_RUN_FACTS, loadRunFacts } from "./universe_run_evidence.js";
import { el, settledScopedCalls } from "./universe_view_support.js";

function selectedProjects(projects, scope) {
  if (scope === "all") return projects;
  const wanted = new Set((scope || []).map(String));
  return projects.filter((project) => wanted.has(String(project.id)));
}

function renderRunCards(context, host, rows, scope, cardOptions) {
  const documentNode = context.document;
  if (!rows.length) {
    host.replaceChildren(el(
      documentNode,
      "p",
      "work-band-empty",
      "No deployment run is in flight.",
    ));
    return;
  }
  const grid = el(documentNode, "div", "work-card-grid shipping-run-grid");
  for (const row of rows) {
    grid.appendChild(shippingRunCard(context, row, scope, cardOptions));
  }
  host.replaceChildren(grid);
}

export async function loadDelivery(context, host, getScope) {
  const documentNode = context.document;
  const projects = context.projects();
  const buckets = projects.length ? projects : [{ id: null }];
  // Run rows and the facts beside them (flow names, QA checks) are fanned
  // out together; neither waits on the other.
  const [{ callResults }, facts] = await Promise.all([
    settledScopedCalls(
      context,
      buckets.map((project) => ({
        functionId: "deployment_runs.list",
        payload: project.id === null
          ? { relevance: "overview" }
          : { project: String(project.id), relevance: "overview" },
      })),
    ),
    projects.length
      ? loadRunFacts(context, projects.map((project) => project.id))
      : Promise.resolve(EMPTY_RUN_FACTS),
  ]);
  if (!context.isMounted()) return null;
  // Answering a request changes what the server would send, so the page
  // reloads rather than repainting the rows it already has.
  const resolve = createDecisionResolver(
    context,
    () => loadDelivery(context, host, getScope),
  );
  const onGateAction = (gate, action, wrap, note) => resolve(
    { id: gate.request_id }, action, wrap, note,
  );
  // A review answered inside a carried item is the same act as one answered
  // in the Inbox, so it goes through the same resolver and the page reloads.
  const onItemDecision = (request, action, wrap, note) => resolve(
    request, action, wrap, note,
  );
  let itemFacts = EMPTY_CARRIED_ITEM_FACTS;
  const paint = () => {
    const chosen = projects.length
      ? selectedProjects(projects, getScope()) : buckets;
    const byId = new Map();
    for (const project of chosen) {
      const index = buckets.indexOf(project);
      const result = successfulResult(callResults[index]);
      if (!result) {
        host.replaceChildren(el(
          documentNode,
          "p",
          "error work-band-error",
          callError(callResults[index], "Deployment runs could not be loaded."),
        ));
        return;
      }
      for (const row of result.rows || []) byId.set(String(row.id || row.run_id), row);
    }
    const rows = [...byId.values()];
    rows.sort((left, right) => (
      Number(left.overview_priority ?? 1) - Number(right.overview_priority ?? 1)
      || String(right.created_at || "").localeCompare(String(left.created_at || ""))
    ));
    renderRunCards(context, host, rows, getScope(), {
      onGateAction,
      facts,
      itemFacts,
      onItemDecision,
    });
  };
  paint();
  // What each carried item proved is read for every member a card names,
  // including the ones behind "+N more". Fetching only the first three made
  // the rest look unverified: the production run that surfaced this had
  // twenty members and QA lines on exactly the first three in list order.
  const carried = [];
  const seenRuns = new Set();
  for (const callResult of callResults) {
    const result = successfulResult(callResult);
    for (const row of result?.rows || []) {
      const runId = row.id || row.run_id;
      if (seenRuns.has(String(runId))) continue;
      seenRuns.add(String(runId));
      // Derived carried work names no project; it is the run's own.
      const projectId = runProjectId(context, row, "all");
      for (const item of carriedItems(row)) {
        carried.push({ ...item, project_id: item.project_id ?? projectId, run_id: runId });
      }
    }
  }
  loadCarriedItemEvidence(context, carried).then((loaded) => {
    if (!context.isMounted()) return;
    itemFacts = loaded;
    paint();
  });
  return paint;
}
