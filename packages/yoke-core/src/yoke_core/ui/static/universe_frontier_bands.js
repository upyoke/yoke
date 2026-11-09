// The Frontier's bands, painted together from one item roster, one frontier
// read and one session roster: Waiting (the dependency graph), On hold,
// Ready, In progress, Release and Done. Which band each item belongs to comes from
// the server; frontier_band_rows.js partitions those projected homes.
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
import { frontierFilter } from "./frontier_dependency_model.js";
import { frontierGraphModel } from "./frontier_graph_nodes.js";
import { frontierGraphSection } from "./frontier_graph.js";

// A serving build older than the dependency graph returns no edges. The
// graph is refused by name rather than rebuilt from reason prose.
export const DEPENDENCY_GRAPH_FLOOR_MESSAGE = "Waiting and On hold need the "
  + "dependency edges frontier.list returns, and the server answering this page "
  + "is an older build that does not return them. Update that server to the "
  + "release these page assets came from, then reload the Frontier.";

// Done always links to the scoped Items view, including when its recent
// window is empty. The band count belongs to finished items, not navigation.
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
  // The graph drawn by the previous paint, released before the next one.
  let graph = null;
  const disposeGraph = () => {
    graph?.dispose();
    graph = null;
  };
  const paint = () => {
    disposeGraph();
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
    let rows;
    try { rows = frontierBandRows({
      items: itemsResult.rows || [],
      readyRows: frontierResult.ready_rows || [],
      blockedRows: frontierResult.blocked_rows || [],
      sessionRows: sessionsResult.rows || [],
    }); } catch (error) {
      for (const band of Object.values(bands)) band.renderError(error.message);
      return;
    }
    const edgeRows = frontierResult.dependency_edges;
    const graphServed = Array.isArray(edgeRows);
    const deploy = (row) => (deploymentsSettled ? deliverySummary(row, deployments) : "");
    const model = frontierFilter(
      frontierGraphModel(
        rows,
        graphServed ? edgeRows : [],
        deploy,
        graphServed ? frontierResult.dependency_cycles : [],
      ),
      inScope(scope, projects),
    );
    const kept = (row) => model.nodes.has(reference(row));

    const renderFullSession = options.renderFullSession || (() => (
      el(documentNode, "p", "empty", "Session detail is unavailable here.")
    ));
    const withClaimants = (card, row) => {
      appendItemClaimants(
        documentNode, card, reference(row), rows.claimants, renderFullSession,
      );
      return card;
    };
    const cardBuilders = new Map();
    const card = (row, build) => {
      cardBuilders.set(reference(row), build);
      return build;
    };

    const waiting = [...rows.waiting, ...rows.held].filter(({ row }) => kept(row));
    for (const { row, reason } of waiting) {
      card(row, () => withClaimants(workItemCard(documentNode, row, scope, {
        flag: reason.flag, timestamp: row.created_at, timeLabel: "filed",
      }), row));
    }
    const active = rows.active.filter(({ row }) => kept(row)).map(({ row }) => card(
      row,
      () => withClaimants(workItemCard(documentNode, row, scope, {
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

    const homeCard = (row) => {
      const built = cardBuilders.get(reference(row))();
      built.id = `frontier-home-${encodeURIComponent(reference(row))}`;
      return built;
    };
    if (graphServed) {
      const held = rows.held.filter(({ row }) => kept(row));
      bands.waiting.setCount(rows.waiting.filter(({ row }) => kept(row)).length);
      if (model.linked.length) {
        graph = frontierGraphSection(documentNode, model, {
          cardFor: (ref) => cardBuilders.get(ref)?.() || null,
          claimantFor: (ref) => {
            const host = el(documentNode, "div");
            appendItemClaimants(
              documentNode, host, ref, rows.claimants, renderFullSession,
            );
            return host.children[0] || null;
          },
        });
        bands.waiting.body.replaceChildren(graph);
      } else {
        bands.waiting.renderCards([], "Nothing is waiting on other work.");
      }
      bands.hold.setCount(held.length);
      bands.hold.renderCards(held.map(({ row }) => homeCard(row)), "Nothing is on hold.");
    } else {
      for (const band of [bands.waiting, bands.hold]) {
        band.setCount(null);
        band.renderError(DEPENDENCY_GRAPH_FLOOR_MESSAGE);
      }
    }

    bands.active.setCount(active.length);
    const progressCards = [];
    for (const [activity, label] of [["working", "Working"], ["waiting", "Waiting"]]) {
      const members = rows.active.filter(({ row }) => kept(row) && row.frontier_group.activity === activity);
      if (!members.length) continue;
      progressCards.push(el(documentNode, "h3", "frontier-progress-heading", `${label} (${members.length})`));
      progressCards.push(...members.map(({ row }) => homeCard(row)));
    }
    bands.active.renderCards(progressCards, "No item is in progress.");
    bands.ready.setCount(ready.length);
    bands.ready.renderCards(rows.ready.filter(kept).map(homeCard), "Nothing is ready to pick up.");

    if (!deploymentsSettled) {
      for (const band of [bands.release, bands.done]) band.setCount(null);
      for (const band of [bands.release, bands.done]) band.renderCards([], "Loading delivery…");
      return;
    }
    // Release shows every unshipped item and has no overflow tile. Done
    // limits recent history, retains linked blockers and always links to Items.
    bands.release.setCount(releasing.length);
    bands.release.renderCards(rows.releasing.filter(kept).map(homeCard), "Nothing is waiting to ship.");
    const doneRows = rows.done.filter(kept);
    const visible = doneRows.filter((row, index) => index < BAND_CARD_LIMIT
      || model.linked.some((node) => node.ref === reference(row))).map(homeCard);
    bands.done.setCount(done.length);
    bands.done.renderCards(
      visible, "Nothing finished in the last 24 hours.", "",
      [seeMoreCard(documentNode, scope)],
    );
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
