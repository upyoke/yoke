import { labelledFact } from "./universe_secondary_primitives.js";
import {
  el,
  loadScopedSection,
  mergedRows,
  section,
} from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";

// The one event name that records an action taken ON a session rather than
// BY it. Its actor is the actor who acted, so "done by" is a read of the
// row's own source label.
const SESSION_ACTION_EVENT = "SessionActionPerformed";

export function actionFact(documentNode, row) {
  // The server already projects the event's own `action` context key into
  // context_label, so the panel reads one field rather than re-parsing the
  // stored envelope. A refused action is worth as much as a completed one:
  // it says somebody tried.
  const action = String(row.context_label || "action");
  const label = row.event_outcome === "failed" ? `${action} — refused` : action;
  const who = el(
    documentNode,
    "span",
    "labelled-fact-value",
    `by ${row.source_label || "unknown"} · `,
  );
  who.appendChild(relativeTime(documentNode, row.created_at));
  return labelledFact(documentNode, label, who);
}

// Everything a session does for itself already reads as its own history.
// This panel is the other half: who messaged, woke, held alive, terminated,
// or launched THIS session, and when.
export function renderSessionActions(context, host, sessionId, project) {
  const documentNode = context.document;
  const panel = section(documentNode, "Actions taken on this session");
  host.appendChild(panel);
  loadScopedSection(
    context,
    panel,
    [{
      functionId: "events.query.run",
      payload: {
        session_id: sessionId,
        event_name: SESSION_ACTION_EVENT,
        ...(project ? { project } : {}),
      },
    }],
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      if (!rows.length) {
        body.appendChild(el(
          documentNode,
          "p",
          "empty",
          "nobody has acted on this session",
        ));
        return;
      }
      const grid = el(documentNode, "div", "project-settings-grid");
      for (const row of rows) grid.appendChild(actionFact(documentNode, row));
      body.appendChild(grid);
    },
  );
}

export default renderSessionActions;
