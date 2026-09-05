// Shipping renders deployment runs as first-class cards, including the work
// each release carries and the derivation that produced that membership.

import { createDecisionResolver } from "./inbox_rows.js";
import { overviewRunCard } from "./universe_overview_cards.js";
import {
  callError,
  OVERVIEW_CARD_LIMIT,
  successfulResult,
} from "./universe_overview_primitives.js";
import { settledScopedCalls } from "./universe_view_support.js";

function selectedProjects(projects, scope) {
  if (scope === "all") return projects;
  const wanted = new Set((scope || []).map(String));
  return projects.filter((project) => wanted.has(String(project.id)));
}

export async function loadDelivery(context, band, getScope) {
  const projects = context.projects();
  const buckets = projects.length ? projects : [{ id: null }];
  const { callResults } = await settledScopedCalls(
    context,
    buckets.map((project) => ({
      functionId: "deployment_runs.list",
      payload: project.id === null ? {} : { project: String(project.id) },
    })),
  );
  if (!context.isMounted()) return null;
  // Answering a gate changes what the server would send, so the band reloads
  // rather than repainting the rows it already has.
  const resolve = createDecisionResolver(
    context,
    () => loadDelivery(context, band, getScope),
  );
  const onGateAction = (gate, action, wrap) => resolve(
    { id: gate.request_id }, action, wrap,
  );
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
    rows.sort((left, right) => String(right.created_at || "").localeCompare(
      String(left.created_at || ""),
    ));
    band.setCount(rows.length);
    band.renderCards(
      rows.slice(0, OVERVIEW_CARD_LIMIT).map((row) => overviewRunCard(
        context.document, row, getScope(), { onGateAction },
      )),
      "No deployment run is in flight.",
      "overview-run-grid",
    );
  };
  paint();
  return paint;
}
