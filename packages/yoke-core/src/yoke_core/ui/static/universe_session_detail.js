import {
  exactSessionAudience,
  openSessionMessageCompose,
} from "./session_message_compose_dialog.js";
import { renderSessionControlFailure } from "./universe_session_control_data.js";
import { renderSessionActions } from "./universe_session_actions.js";
import { sessionCard } from "./universe_views_sessions.js";
import {
  el,
  mergedRows,
  scopeBuckets,
  settledScopedCalls,
} from "./universe_view_support.js";


export function renderRegisteredSessionDetail(
  context,
  main,
  scope,
  sessionId,
  navigation = {},
) {
  const documentNode = context.document;
  const view = el(documentNode, "div", "sessions-view session-detail-view");
  const content = el(
    documentNode, "div", "sessions-content", "Loading registered session…",
  );
  const dialogHost = el(documentNode, "div", "session-control-dialog-host");
  view.appendChild(content);
  view.appendChild(dialogHost);
  main.replaceChildren(view);

  const load = async () => {
    const calls = scopeBuckets(scope, context.projects(), false).map((project) => ({
      functionId: "sessions.list",
      payload: {
        session_id: sessionId,
        ...(project === null ? {} : { project }),
      },
    }));
    const { callResults, failed } = await settledScopedCalls(context, calls);
    if (!context.isMounted()) return;
    if (failed) {
      renderSessionControlFailure(
        content, failed, "The registered session could not be loaded.",
      );
      return;
    }
    const rows = mergedRows(callResults, (result) => result.rows);
    const row = rows.find((candidate) => String(candidate.session_id) === sessionId);
    if (!row) {
      content.replaceChildren(el(
        documentNode,
        "p",
        "sessions-empty",
        `Session ${sessionId} is not registered in this project scope.`,
      ));
      return;
    }
    if (typeof navigation.setDetailLabel === "function") {
      navigation.setDetailLabel(String(row.session_id));
    }
    const openMessage = (targetId) => openSessionMessageCompose(
      context, dialogHost, { audience: exactSessionAudience([targetId]) },
    );
    content.replaceChildren(sessionCard(
      documentNode,
      row,
      openMessage,
      context.projects(),
    ));
    // Who acted on this session, as opposed to what it did itself.
    renderSessionActions(context, content, sessionId, row.project);
  };
  load();
}
