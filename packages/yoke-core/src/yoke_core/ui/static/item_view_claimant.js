// The session that actually holds this item's work claim, drawn as the same
// card the Sessions roster draws.
//
// A claim row names an actor and a session id, which is enough to say the
// item is taken and nothing about who is holding it or whether that session
// is still alive. The card the roster already renders answers both, so this
// reads the claimed session and hands it to that renderer rather than
// inventing a smaller one — and when the claim names a session the roster
// does not hold, it says exactly that instead of drawing a card from the
// claim row alone.

import {
  exactSessionAudience,
  openSessionMessageCompose,
} from "./session_message_compose_dialog.js";
import { sessionCard } from "./universe_views_sessions.js";
import { workflowPanel } from "./workflow_view_primitives.js";
import { callFunction, el } from "./universe_view_support.js";

export function itemClaimantPanel(context, item) {
  const documentNode = context.document;
  const claim = item.claim;
  if (!claim?.session_id) return null;
  const { panel, body } = workflowPanel(documentNode, "Claimed by");
  const dialogHost = el(documentNode, "div", "session-control-dialog-host");
  body.appendChild(el(documentNode, "p", "item-muted", "loading session…"));
  (async () => {
    let rows = null;
    try {
      const read = await callFunction(context.client, "sessions.list", {
        session_id: String(claim.session_id),
        project: String(item.project.id),
      });
      if (read.status === 200 && read.envelope.success) {
        rows = read.envelope.result?.rows || [];
      }
    } catch {
      rows = null;
    }
    if (!context.isMounted()) return;
    const row = (rows || []).find(
      (candidate) => String(candidate.session_id) === String(claim.session_id),
    );
    if (!row) {
      body.replaceChildren(el(
        documentNode,
        "p",
        "item-muted",
        `${claim.actor_label || "Someone"} holds this item through session `
          + `${claim.session_id}, which this project's roster does not hold.`,
      ));
      return;
    }
    body.replaceChildren(sessionCard(
      documentNode,
      row,
      (targetId) => openSessionMessageCompose(context, dialogHost, {
        audience: exactSessionAudience([targetId]),
      }),
      context.projects(),
      context.steeringGroupColors(),
    ), dialogHost);
  })();
  return panel;
}
