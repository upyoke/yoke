// Active renders the exact session-card object used by the Sessions roster,
// from the session roster it shares with Frontier so Ready can omit whatever
// this band already shows as in flight.

import {
  exactSessionAudience,
  openSessionMessageCompose,
} from "./session_message_compose_dialog.js";
import {
  callError,
  sessionsShownInActive,
  successfulResult,
} from "./universe_overview_primitives.js";
import { sessionCard } from "./universe_views_sessions.js";
import {
  sortSessionsSteeringFirst,
  steeringGroupColors,
} from "./universe_sessions_steering.js";
import { el } from "./universe_view_support.js";

export async function loadSessions(context, band, getScope, sessionRoster) {
  const { callResults } = await sessionRoster;
  if (!context.isMounted()) return null;
  const dialogHost = el(
    context.document, "div", "overview-session-dialog-host",
  );
  const onMessage = (sessionId) => openSessionMessageCompose(
    context,
    dialogHost,
    { audience: exactSessionAudience([sessionId]) },
  );
  const paint = () => {
    const result = successfulResult(callResults[0]);
    if (!result) {
      band.renderError(callError(
        callResults[0], "Sessions could not be loaded.",
      ));
      return;
    }
    // A group's color is a pure function of its own id (see
    // steeringGroupColors), so this just needs to know which groups are
    // present to populate the map — any row set that covers them works.
    const groupColors = steeringGroupColors(result.rows || []);
    const rows = sortSessionsSteeringFirst(sessionsShownInActive(
      result.rows || [], getScope(), context.projects(),
    ).sort((left, right) => String(right.activity_at || "").localeCompare(
      String(left.activity_at || ""),
    )));
    band.setCount(rows.length);
    band.renderCards(
      rows.map((row) => sessionCard(
        context.document, row, onMessage, context.projects(), groupColors,
      )),
      "No session is running against this universe.",
      "overview-session-grid session-grid",
    );
    band.body.appendChild(dialogHost);
  };
  paint();
  return paint;
}
