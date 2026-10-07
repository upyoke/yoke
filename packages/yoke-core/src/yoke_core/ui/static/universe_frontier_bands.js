// The Frontier's bands, painted together from one item roster, one frontier
// read and one session roster: Waiting (the dependency graph), On hold,
// Ready, Active, Release and Done. Which band each item belongs to is decided
// in frontier_band_rows.js; this module reads, filters and draws.
//
// The project filter keeps whole dependency chains: every item in the
// selected projects, plus every item tied to one through any chain, in any
// project. The same kept set applies to every band, and each band counts what
// it drew.

import { buildUniverseRoute } from "./universe_navigation.js";
import {
  BAND_CARD_LIMIT,
  callError,
  successfulResult,
} from "./universe_band_primitives.js";
import { appendItemClaimants } from "./universe_item_claimant.js";
import { appendItemDelivery, deliverySummary } from "./universe_item_deployment.js";
import { workItemCard } from "./universe_work_cards.js";
import { el, settledScopedCalls } from "./universe_view_support.js";
import { finishedAt, frontierBandRows, reference } from "./frontier_band_rows.js";
import { frontierFilter, frontierWaitingSplit } from "./frontier_dependency_model.js";
import { frontierGraphModel } from "./frontier_graph_nodes.js";
import { frontierGraphSection } from "./frontier_graph.js";

// A serving build older than the dependency graph returns no edges. The
// graph is refused by name rather than rebuilt from reason prose.
export const DEPENDENCY_GRAPH_FLOOR_MESSAGE = "Waiting and On hold need "
  + "frontier.list dependency_edges, which this serving build does not return "
  + "(serving floor: next-release). Deploy a build at or above that floor to "
  + "draw the dependency graph.";

// The overflow card is navigation, not a statistic: the band above it already
// carries its own count, so this one says only where the rest of them are.
function seeMoreCard(documentNode, scope) {
  const card = el(documentNode, "a", "work-item-card see-more-card");
  card.href = buildUniverseRoute(
    "items", scope === "all" ? null : scope.join(","),
  );
  card.setAttribute("aria-label", "See more...");
  card.appendChild(el(documentNode, "span", null, "See more..."));
  return card;
}

// The selected projects, matched by id or slug as every band scope is.
function inScope(scope, projects) {
  if (scope === "all") return null;
  const wanted = new Set();
  for (const projectId of scope || []) {
    wanted.add(String(projectId));
    const project = projects.find((row) => String(row.id) === String(projectId));
    if (project?.slug) wanted.add(String(project.slug));
  }
  return (node) => wanted.has(String(node.projectId)) || wanted.has(String(node.project));
}

export async function loadFrontier(context, bands, getScope, sessionRoster, options = {}) {
  // The item, frontier and session reads decide every band, so they are in
  // flight together and paint together. The run roster only annotates
  // Release and Done with delivery and can be far slower, so those two bands
  // wait for it alone and fill when it settles.
  let deployments;
  let deploymentsSettled = false;
  const [{ callResults }, sessionCalls] = await Promise.all([
    settledScopedCalls(context, [
      { functionId: "items.overview.list", payload: { relevance: "overview" } },
      { functionId: "frontier.list", payload: {} },
    ]),
    sessionRoster,
  ]);
  if (!context.isMounted()) return null;
  const paint = () => {
    const itemsResult = successfulResult(callResults[0]);
    const frontierResult = successfulResult(callResults[1]);
    const sessionsResult = successfulResult(sessionCalls.callResults[0]);
    if (!itemsResult || !frontierResult) {
      const failed = !itemsResult ? callResults[0] : callResults[1];
      const message = callError(failed, "Frontier could not be loaded.");
      for (const band of Object.values(bands)) band.renderError(message);
      return;
    }
    if (!sessionsResult) {
      const message = callError(
        sessionCalls.callResults[0],
        "The frontier needs the session roster to tell which work is in flight.",
      );
      for (const band of Object.values(bands)) band.renderError(message);
      return;
    }
    const scope = getScope();
    const projects = context.projects();
    const documentNode = context.document;
    const rows = frontierBandRows({
      items: itemsResult.rows || [],
      readyRows: frontierResult.ready_rows || [],
      blockedRows: frontierResult.blocked_rows || [],
      sessionRows: sessionsResult.rows || [],
    });
    const edgeRows = frontierResult.dependency_edges;
    const graphServed = Array.isArray(edgeRows);
    const deploy = (row) => (deploymentsSettled ? deliverySummary(row, deployments) : "");
    const model = frontierFilter(
      frontierGraphModel(rows, graphServed ? edgeRows : [], deploy),
      inScope(scope, projects),
    );
    const kept = (row) => model.nodes.has(reference(row));

    const renderFullSession = options.renderFullSession || (() => (
      el(documentNode, "p", "empty", "Session detail is unavailable here.")
    ));
    // Every session chip on this page opens its card as a top-layer popover.
    const withClaimants = (card, row) => {
      appendItemClaimants(
        documentNode, card, reference(row), rows.claimants, renderFullSession,
        { popover: true },
      );
      return card;
    };
    const cardBuilders = new Map();
    const card = (row, build) => {
      cardBuilders.set(reference(row), build);
      return build;
    };

    const waiting = rows.waiting.filter(({ row }) => kept(row));
    for (const { row, reason } of waiting) {
      card(row, () => withClaimants(workItemCard(documentNode, row, scope, {
        flag: reason.flag, timestamp: row.created_at, timeLabel: "filed",
      }), row));
    }
    const active = rows.active.filter(({ row }) => kept(row)).map(({ row, reason }) => card(
      row,
      () => withClaimants(workItemCard(documentNode, row, scope, {
        flag: reason?.flag,
        stages: rows.stages.get(reference(row)) || [],
        timestamp: row.updated_at,
      }), row),
    ));
    const ready = rows.ready.filter(kept).map((row) => card(row, () => workItemCard(
      documentNode,
      row,
      scope,
      {
        flag: {
          label: "Ready",
          text: row.why_ready || "No blocker is holding this item.",
          tone: "ready",
        },
        meta: row.run_command || row.next_step,
        timestamp: row.created_at,
        timeLabel: "filed",
      },
    )));
    const delivered = (row, options) => () => {
      const built = workItemCard(documentNode, row, scope, options);
      if (deploymentsSettled) appendItemDelivery(documentNode, built, row, deployments, projects);
      return withClaimants(built, row);
    };
    const releasing = rows.releasing.filter(kept).map((row) => card(
      row, delivered(row, { timestamp: row.updated_at }),
    ));
    // Terminal status already belongs in the card head. A red exception
    // disclosure made cancelled and stopped work look active again.
    const done = rows.done.filter(kept).map((row) => card(
      row, delivered(row, { tone: "done", timestamp: finishedAt(row), timeLabel: "finished" }),
    ));

    if (graphServed) {
      const { held, graphCount } = frontierWaitingSplit(model);
      bands.waiting.setCount(graphCount);
      if (model.linked.length) {
        bands.waiting.body.replaceChildren(frontierGraphSection(documentNode, model, {
          cardFor: (ref) => cardBuilders.get(ref)?.() || null,
          claimantFor: (ref) => {
            const host = el(documentNode, "div");
            appendItemClaimants(
              documentNode, host, ref, rows.claimants, renderFullSession, { popover: true },
            );
            return host.children[0] || null;
          },
        }));
      } else {
        bands.waiting.renderCards([], "Nothing is waiting on other work.");
      }
      bands.hold.setCount(held.length);
      bands.hold.renderCards(held.map((node) => cardBuilders.get(node.ref)()), "Nothing is on hold.");
    } else {
      for (const band of [bands.waiting, bands.hold]) {
        band.setCount(null);
        band.renderError(DEPENDENCY_GRAPH_FLOOR_MESSAGE);
      }
    }

    bands.active.setCount(active.length);
    bands.active.renderCards(
      active.map((build) => build()),
      "No session is running against this universe.",
    );
    bands.ready.setCount(ready.length);
    bands.ready.renderCards(ready.map((build) => build()), "Nothing is ready to pick up.");

    if (!deploymentsSettled) {
      for (const band of [bands.release, bands.done]) band.setCount(null);
      for (const band of [bands.release, bands.done]) band.renderCards([], "Loading delivery…");
      return;
    }
    // Every card, with no overflow tile: Done is the one band that truncates,
    // because it is a window on finished work that only grows. Release is a
    // queue somebody is waiting to see empty, and a hidden remainder there
    // would understate what is still unshipped.
    bands.release.setCount(releasing.length);
    bands.release.renderCards(releasing.map((build) => build()), "Nothing is waiting to ship.");
    const visible = done.slice(0, BAND_CARD_LIMIT).map((build) => build());
    if (done.length > visible.length) visible.push(seeMoreCard(documentNode, scope));
    bands.done.setCount(done.length);
    bands.done.renderCards(visible, "Nothing finished in the last 24 hours.");
  };
  paint();
  Promise.resolve(options.deployments).catch(() => undefined).then((runs) => {
    deployments = runs;
    deploymentsSettled = true;
    if (context.isMounted()) paint();
  }).catch((error) => [bands.release, bands.done].forEach((band) => band.renderError(
    `Release and Done could not be drawn: ${error?.message || error}. Reload Frontier.`,
  )));
  return paint;
}
