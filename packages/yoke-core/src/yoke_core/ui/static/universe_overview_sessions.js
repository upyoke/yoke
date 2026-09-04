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
    const rows = sessionsShownInActive(
      result.rows || [], getScope(), context.projects(),
    ).sort((left, right) => String(right.activity_at || "").localeCompare(
      String(left.activity_at || ""),
    ));
    band.setCount(rows.length);
    band.renderCards(
      rows.map((row) => sessionCard(
        context.document, row, onMessage, context.projects(),
      )),
      "No session is running against this universe.",
      "overview-session-grid session-grid",
    );
    band.body.appendChild(dialogHost);
  };
  paint();
  return paint;
}
