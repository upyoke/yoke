// Frontier is the work itself, in the four states work is actually in:
// stopped and why, free to pick up, being worked on right now, and finished
// in the last day. Deployment runs are their own page — what is shipping is a
// different question from what is being built.

import { successfulResult, workBand } from "./universe_band_primitives.js";
import { loadFrontier } from "./universe_frontier_bands.js";
import { deploymentsByItemId } from "./universe_item_deployment.js";
import { sessionCard } from "./universe_views_sessions.js";
import {
  exactSessionAudience,
  openSessionMessageCompose,
} from "./session_message_compose_dialog.js";
import { el, settledScopedCalls } from "./universe_view_support.js";

export function renderFrontierView(context, main, scope) {
  const documentNode = context.document;
  const waiting = workBand(
    documentNode, "waiting", "Waiting", "Nothing is stopped.",
  );
  const ready = workBand(
    documentNode, "ready", "Ready", "Nothing is ready to pick up.",
  );
  const active = workBand(
    documentNode,
    "active",
    "Active",
    "No session is running against this universe.",
  );
  const done = workBand(
    documentNode, "done", "Done (24h)", "Nothing finished in the last 24 hours.",
  );
  const dialogHost = el(documentNode, "div", "work-session-dialog-host");
  main.replaceChildren(waiting, ready, active, done, dialogHost);

  let currentScope = scope;
  const getScope = () => currentScope;
  const painters = [];
  const hold = (pending) => Promise.resolve(pending).then((paint) => {
    if (typeof paint === "function") painters.push(paint);
  });
  const onMessage = (sessionId) => openSessionMessageCompose(
    context, dialogHost, { audience: exactSessionAudience([sessionId]) },
  );
  // Active and Ready answer the same question from opposite sides, so they
  // read one session roster: Ready omits every item a live session holds.
  const sessionRoster = settledScopedCalls(context, [{
    functionId: "sessions.list",
    payload: { per_project: true, open: true },
  }]);
  // A revealed session card is tinted by its steering group exactly as it is
  // on Sessions, so the roster's colors are refreshed alongside the read
  // rather than after it.
  const steeringColorsReady = context.refreshSteeringGroupColors();
  const projects = context.projects();
  // Which release carried each finished item. The same 24-hour run window the
  // Done band uses, so a card and the run it names describe one period.
  const runRoster = settledScopedCalls(
    context,
    (projects.length ? projects : [{ id: null }]).map((project) => ({
      functionId: "deployment_runs.list",
      payload: project.id === null
        ? { relevance: "overview" }
        : { project: String(project.id), relevance: "overview" },
    })),
  );
  hold(Promise.all([runRoster, steeringColorsReady]).then(([{ callResults }]) => {
    const runs = callResults.flatMap(
      (callResult) => successfulResult(callResult)?.rows || [],
    );
    return loadFrontier(
      context,
      { waiting, ready, active, done },
      getScope,
      sessionRoster,
      {
        deployments: deploymentsByItemId(runs),
        renderFullSession: (row) => sessionCard(
          documentNode,
          row,
          onMessage,
          context.projects(),
          context.steeringGroupColors(),
        ),
      },
    );
  }));

  return {
    rescope(nextScope) {
      if (!context.isMounted()) return;
      currentScope = nextScope;
      for (const paint of painters) paint();
    },
  };
}
