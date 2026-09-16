// Shipping is the release side of the work: every deployment run in flight or
// recently finished, as its own card, with the stages it is moving through,
// the items it carries, the evidence those items proved, and the approvals it
// is waiting on.
//
// A run's detail is a sub-screen of this page rather than a band that folds
// open inside it: a run detail is a page's worth of stages, logs and
// evidence, and reaching it should leave the operator somewhere they can come
// back from.

import {
  exactSessionAudience,
  openSessionMessageCompose,
} from "./session_message_compose_dialog.js";
import { loadDelivery } from "./universe_shipping_runs.js";
import { el } from "./universe_view_support.js";
import { sessionCard } from "./universe_views_sessions.js";

export function renderShippingView(context, main, scope) {
  const documentNode = context.document;
  const host = el(documentNode, "div", "shipping-runs");
  const dialogHost = el(documentNode, "div", "work-session-dialog-host");
  main.replaceChildren(host, dialogHost);

  let currentScope = scope;
  const getScope = () => currentScope;
  const painters = [];
  const onMessage = (sessionId) => openSessionMessageCompose(
    context, dialogHost, { audience: exactSessionAudience([sessionId]) },
  );
  const renderFullSession = (row) => sessionCard(
    documentNode,
    row,
    onMessage,
    context.projects(),
    context.steeringGroupColors(),
  );
  Promise.all([
    context.refreshSteeringGroupColors(),
  ]).then(() => loadDelivery(context, host, getScope, { renderFullSession }))
    .then((paint) => {
      if (typeof paint === "function") painters.push(paint);
    });

  return {
    rescope(nextScope) {
      if (!context.isMounted()) return;
      currentScope = nextScope;
      for (const paint of painters) paint();
    },
  };
}
