// Active renders the exact session-card object used by the Sessions roster.

import {
  exactSessionAudience,
  openSessionMessageCompose,
} from "./session_message_compose_dialog.js";
import {
  callError,
  rowsInOverviewScope,
  successfulResult,
} from "./universe_overview_primitives.js";
import { sessionCard } from "./universe_views_sessions.js";
import { el, settledScopedCalls } from "./universe_view_support.js";

export async function loadSessions(context, band, getScope) {
  const { callResults } = await settledScopedCalls(context, [{
    functionId: "sessions.list",
    payload: { per_project: true },
  }]);
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
    const rows = rowsInOverviewScope(
      result.rows || [], getScope(), context.projects(),
    ).filter((row) => ["active", "stale"].includes(
      String(row.liveness || "").toLowerCase(),
    )).sort((left, right) => String(right.activity_at || "").localeCompare(
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
