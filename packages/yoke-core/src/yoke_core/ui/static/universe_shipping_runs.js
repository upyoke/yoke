// Shipping renders deployment runs as first-class cards, including the work
// each release carries, the request each is waiting on, and the QA evidence
// its checks captured.
//
// A non-terminal card also names the project's live deploy lock, because a
// release that cannot start is usually waiting on one. The lock is a
// project-wide fact and says so: the session holding it serializes deploys
// for the whole project and is not a claim to have started this run — or any
// earlier one.

import { createDecisionResolver } from "./inbox_rows.js";
import {
  carriedItems,
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

const DEPLOY_LOCK_PREFIX = "DEPLOY:";

function selectedProjects(projects, scope) {
  if (scope === "all") return projects;
  const wanted = new Set((scope || []).map(String));
  return projects.filter((project) => wanted.has(String(project.id)));
}

// Which session holds each project's deploy serialization claim, read from
// the same current-holdings projection every other surface reads.
export function deployLocksByProject(sessionRows) {
  const locks = new Map();
  for (const row of sessionRows || []) {
    for (const holding of row.holdings?.current || []) {
      if (String(holding.holding_kind || "") !== "coordination") continue;
      const key = String(holding.lease_key || holding.target || "");
      if (!key.startsWith(DEPLOY_LOCK_PREFIX)) continue;
      locks.set(key.slice(DEPLOY_LOCK_PREFIX.length), row);
    }
  }
  return locks;
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

export async function loadDelivery(context, host, getScope, options = {}) {
  const documentNode = context.document;
  const projects = context.projects();
  const buckets = projects.length ? projects : [{ id: null }];
  // Run rows, the facts beside them (flow names, QA checks), and the session
  // roster the deploy lock is read from are fanned out together; none waits
  // on another.
  const [{ callResults }, facts, sessionCalls] = await Promise.all([
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
    settledScopedCalls(context, [{
      functionId: "sessions.list",
      payload: { per_project: true, open: true },
    }]),
  ]);
  if (!context.isMounted()) return null;
  // Answering a request changes what the server would send, so the page
  // reloads rather than repainting the rows it already has.
  const resolve = createDecisionResolver(
    context,
    () => loadDelivery(context, host, getScope, options),
  );
  const onGateAction = (gate, action, wrap, note) => resolve(
    { id: gate.request_id }, action, wrap, note,
  );
  // A review answered inside a carried item is the same act as one answered
  // in the Inbox, so it goes through the same resolver and the page reloads.
  const onItemDecision = (request, action, wrap, note) => resolve(
    request, action, wrap, note,
  );
  const deployLocks = deployLocksByProject(
    successfulResult(sessionCalls.callResults[0])?.rows || [],
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
        host.replaceChildren(el(
          documentNode,
          "p",
          "error work-band-error",
          callError(callResults[index], "Deployment runs could not be loaded."),
        ));
        return;
      }
      rows.push(...(result.rows || []));
    }
    rows.sort((left, right) => (
      Number(left.overview_priority ?? 1) - Number(right.overview_priority ?? 1)
      || String(right.created_at || "").localeCompare(String(left.created_at || ""))
    ));
    renderRunCards(context, host, rows, getScope(), {
      onGateAction,
      facts,
      itemFacts,
      onItemDecision,
      deployLocks,
      renderFullSession: options.renderFullSession,
    });
  };
  paint();
  // What each carried item proved is read for every member a card names,
  // including the ones behind "+N more". Fetching only the first three made
  // the rest look unverified: the production run that surfaced this had
  // twenty members and QA lines on exactly the first three in list order.
  const carried = [];
  for (const callResult of callResults) {
    const result = successfulResult(callResult);
    for (const row of result?.rows || []) {
      const runId = row.id || row.run_id;
      for (const item of carriedItems(row)) {
        carried.push({ ...item, run_id: runId });
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
