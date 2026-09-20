// Frontier is the work itself, in the five states work is actually in:
// stopped and why, free to pick up, being worked on right now, merged and
// waiting on its deployment, and finished in the last day. Deployment runs
// are their own page — what is shipping is a different question from what is
// being built, and Release answers only which items are between the two.

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
  const release = workBand(
    documentNode, "release", "Release", "Nothing is waiting to ship.",
  );
  const done = workBand(
    documentNode, "done", "Done (24h)", "Nothing finished in the last 24 hours.",
  );
  const dialogHost = el(documentNode, "div", "work-session-dialog-host");
  main.replaceChildren(waiting, ready, active, release, done, dialogHost);

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
  // on Sessions. Those colors are ranked from the open roster, which is the
  // read above — so they are taken from it rather than read again.
  sessionRoster.then(({ callResults }) => context.adoptSteeringGroupColors(
    successfulResult(callResults[0])?.rows || [],
  )).catch(() => {});
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
  // The run roster is handed over as a promise, not awaited first. It answers
  // a different question than the item reads do and nothing in them depends
  // on it, so sequencing the two made the screen wait for their sum when the
  // slower of the two is the whole cost.
  const deployments = runRoster.then(({ callResults }) => deploymentsByItemId(
    callResults.flatMap((callResult) => successfulResult(callResult)?.rows || []),
  ));
  hold(loadFrontier(
    context,
    { waiting, ready, active, release, done },
    getScope,
    sessionRoster,
    {
      deployments,
      renderFullSession: (row) => sessionCard(
        documentNode,
        row,
        onMessage,
        context.projects(),
        context.steeringGroupColors(),
      ),
    },
  ));

  return {
    rescope(nextScope) {
      if (!context.isMounted()) return;
      currentScope = nextScope;
      for (const paint of painters) paint();
    },
  };
}
