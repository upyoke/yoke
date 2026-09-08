import { el } from "./universe_view_support.js";
import {
  presentSessionControlFailure,
  renderSessionControlFailure,
  scopedProjectRefs,
  sessionControlCall,
  statusRegion,
} from "./universe_session_control_data.js";
import { messageCard } from "./universe_session_message_card.js";
import { sessionMessagePageLoader } from "./universe_session_message_loader.js";

function appendSection(documentNode, host, heading, messages, view, empty) {
  host.appendChild(el(documentNode, "h3", "session-message-heading", heading));
  if (!messages.length) {
    host.appendChild(el(documentNode, "p", "sessions-empty", empty));
    return;
  }
  const list = el(documentNode, "ol", "session-message-list");
  for (const message of messages) {
    list.appendChild(messageCard(documentNode, message, view));
  }
  host.appendChild(list);
}

function renderMessages(documentNode, host, pendingBadge, loader, view) {
  const actionable = loader.actionable();
  const settled = loader.settled();
  pendingBadge.textContent = `${loader.actionableCount()} pending`;
  if (loader.failure() && !actionable.length && !settled.length) {
    renderSessionControlFailure(
      host, loader.failure(), "Session messages could not be loaded.",
    );
    const retry = el(documentNode, "button", "item-button", "Retry");
    retry.type = "button";
    retry.addEventListener("click", () => loader.retry());
    host.appendChild(retry);
    return;
  }
  if (
    !loader.loading()
    && !actionable.length
    && !settled.length
    && loader.actionableCount() === 0
    && loader.settledMatchedCount() === 0
  ) {
    host.replaceChildren(el(
      documentNode,
      "p",
      "sessions-empty",
      "No session messages yet. Send from the Sessions roster.",
    ));
    return;
  }
  host.replaceChildren();
  appendSection(
    documentNode,
    host,
    `Needs attention · ${loader.actionableCount()} matching`,
    actionable,
    view,
    "No messages need attention.",
  );
  appendSection(
    documentNode,
    host,
    `History · ${settled.length} of ${loader.settledMatchedCount()} matching loaded`,
    settled,
    view,
    "No settled messages yet.",
  );
  if (loader.failure()) {
    host.appendChild(el(
      documentNode,
      "p",
      "error",
      presentSessionControlFailure(
        loader.failure(), "More settled messages could not be loaded.",
      ),
    ));
  }
  if (loader.hasMore() || loader.failure()) {
    const more = el(
      documentNode,
      "button",
      "item-button session-message-more",
      loader.failure() ? "Retry" : "Load more",
    );
    more.type = "button";
    more.disabled = loader.loading();
    more.addEventListener(
      "click", () => (loader.failure() ? loader.retry() : loader.loadMore()),
    );
    host.appendChild(more);
  }
}

export function renderSessionMessagesView(context, main, scope, chrome = {}) {
  const documentNode = context.document;
  const projects = scope === "all" ? null : scopedProjectRefs(context, scope);
  const viewNode = el(documentNode, "div", "session-control-view");
  const status = statusRegion(documentNode);
  const pendingBadge = el(documentNode, "span", "pill", "0 pending");
  const content = el(
    documentNode, "div", "session-control-content", "Loading messages…",
  );
  const view = {
    expanded: new Set(),
    details: new Map(),
    detailFailures: new Map(),
    pending: new Set(),
    cancelMessage: null,
    acknowledge: null,
    toggleDetail: null,
  };
  const loader = sessionMessagePageLoader(
    context,
    projects,
    () => renderMessages(documentNode, content, pendingBadge, loader, view),
  );
  viewNode.appendChild(status);
  viewNode.appendChild(pendingBadge);
  viewNode.appendChild(content);
  main.replaceChildren(viewNode);

  if (typeof chrome.setPageHead === "function") {
    chrome.setPageHead({ title: "Session messages" });
  }

  const ensureDetail = async (messageId) => {
    if (view.details.has(messageId) || view.pending.has(messageId)) return;
    view.pending.add(messageId);
    try {
      const result = await sessionControlCall(
        context, "session_control.message.get", { message_id: messageId },
      );
      view.details.set(messageId, result.message || {});
      view.detailFailures.delete(messageId);
    } catch (error) {
      view.detailFailures.set(messageId, error);
    } finally {
      view.pending.delete(messageId);
    }
    if (context.isMounted() && view.expanded.has(messageId)) {
      renderMessages(documentNode, content, pendingBadge, loader, view);
    }
  };
  view.toggleDetail = (messageId) => {
    if (view.expanded.has(messageId)) {
      view.expanded.delete(messageId);
      renderMessages(documentNode, content, pendingBadge, loader, view);
      return;
    }
    view.expanded.add(messageId);
    view.detailFailures.delete(messageId);
    renderMessages(documentNode, content, pendingBadge, loader, view);
    return ensureDetail(messageId);
  };
  const reloadAfterMutation = () => {
    view.expanded.clear();
    view.details.clear();
    view.detailFailures.clear();
    return loader.reload();
  };
  view.cancelMessage = async (messageId, button) => {
    button.disabled = true;
    status.hidden = false;
    status.textContent = "Cancelling message…";
    try {
      await sessionControlCall(context, "session_control.message.cancel", {
        message_id: messageId,
      });
      status.textContent = "Message cancelled.";
      await reloadAfterMutation();
    } catch (error) {
      status.textContent = presentSessionControlFailure(
        error, "The message could not be cancelled.",
      );
      button.disabled = false;
    }
  };
  view.acknowledge = async (messageId, button) => {
    button.disabled = true;
    status.hidden = false;
    status.textContent = "Acknowledging message…";
    try {
      await sessionControlCall(context, "session_control.message.acknowledge", {
        message_id: messageId,
      });
      status.textContent = "Message acknowledged.";
      await reloadAfterMutation();
    } catch (error) {
      status.textContent = presentSessionControlFailure(
        error, "The message could not be acknowledged.",
      );
      button.disabled = false;
    }
  };
  loader.reload();
}
