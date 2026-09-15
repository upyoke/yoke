// Shipping renders deployment runs as first-class cards, including the work
// each release carries, the request each is waiting on, and the QA evidence
// its checks captured.

import { createDecisionResolver } from "./inbox_rows.js";
import {
  CARRIED_ITEMS_SHOWN,
  carriedItems,
  overviewRunCard,
} from "./universe_overview_cards.js";
import {
  EMPTY_CARRIED_ITEM_FACTS,
  loadCarriedItemEvidence,
} from "./universe_carried_item_evidence.js";
import {
  callError,
  OVERVIEW_CARD_LIMIT,
  successfulResult,
} from "./universe_overview_primitives.js";
import { EMPTY_RUN_FACTS, loadRunFacts } from "./universe_run_evidence.js";
import { settledScopedCalls } from "./universe_view_support.js";

function selectedProjects(projects, scope) {
  if (scope === "all") return projects;
  const wanted = new Set((scope || []).map(String));
  return projects.filter((project) => wanted.has(String(project.id)));
}

export async function loadDelivery(context, band, getScope) {
  const projects = context.projects();
  const buckets = projects.length ? projects : [{ id: null }];
  // Run rows and the facts beside them (flow names, QA checks) are two reads
  // fanned out together; neither waits on the other.
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
  // Answering a request changes what the server would send, so the band
  // reloads rather than repainting the rows it already has.
  const resolve = createDecisionResolver(
    context,
    () => loadDelivery(context, band, getScope),
  );
  const onGateAction = (gate, action, wrap, note) => resolve(
    { id: gate.request_id }, action, wrap, note,
  );
  // A review answered inside a carried item is the same act as one answered
  // in the Inbox, so it goes through the same resolver and the band reloads.
  const onItemDecision = (request, action, wrap, note) => resolve(
    request, action, wrap, note,
  );
  let itemFacts = EMPTY_CARRIED_ITEM_FACTS;
  const paint = () => {
    const chosen = projects.length
      ? selectedProjects(projects, getScope()) : buckets;
    const rows = [];
    for (const project of chosen) {
      const index = buckets.indexOf(project);
      const result = successfulResult(callResults[index]);
      if (!result) {
        band.renderError(callError(
          callResults[index], "Deployment runs could not be loaded.",
        ));
        return;
      }
      rows.push(...(result.rows || []));
    }
    rows.sort((left, right) => (
      Number(left.overview_priority ?? 1) - Number(right.overview_priority ?? 1)
      || String(right.created_at || "").localeCompare(String(left.created_at || ""))
    ));
    band.setCount(rows.length);
    band.renderCards(
      rows.slice(0, OVERVIEW_CARD_LIMIT).map((row) => overviewRunCard(
        context, row, getScope(), { onGateAction, facts, itemFacts, onItemDecision },
      )),
      "No deployment run is in flight.",
      "overview-run-grid",
    );
  };
  paint();
  // What each carried item proved is read for the items these cards are
  // about, which the run rows have to arrive first to name — and only for
  // the entries a card actually lists, not the ones behind its "+N more".
  // The cards paint without it and fill in when it lands, rather than
  // holding the band.
  const carried = [];
  for (const callResult of callResults) {
    const result = successfulResult(callResult);
    for (const row of result?.rows || []) {
      carried.push(...carriedItems(row).slice(0, CARRIED_ITEMS_SHOWN));
    }
  }
  loadCarriedItemEvidence(context, carried).then((loaded) => {
    if (!context.isMounted()) return;
    itemFacts = loaded;
    paint();
  });
  return paint;
}
