import { renderWorkflowItemDetail } from "./item_view_details.js";
import { renderNewItemView } from "./item_view_new.js";
import {
  callFunction,
  renderError,
  section,
} from "./universe_view_support.js";
import { renderBlitzItemDetail } from "./universe_views_blitz.js";

export function renderItemDetailView(
  context,
  main,
  projectId,
  itemRef,
  navigation = {},
) {
  if (String(itemRef).toLowerCase() === "new") {
    if (typeof navigation.setDetailLabel === "function") {
      navigation.setDetailLabel("New item");
    }
    renderNewItemView(context, main, projectId);
    return;
  }
  const loading = section(
    context.document, String(itemRef), { showRaw: false },
  );
  main.replaceChildren(loading);
  const target = {
    kind: "item",
    item_ref: String(itemRef),
    project_id: String(projectId),
  };
  (async () => {
    let callResult;
    try {
      callResult = await callFunction(
        context.client,
        "items.detail.get",
        {},
        target,
      );
    } catch (error) {
      callResult = {
        status: 0,
        envelope: { success: false, error: { message: String(error) } },
      };
    }
    if (!context.isMounted()) return;
    if (callResult.status === 200 && callResult.envelope.success) {
      const item = (callResult.envelope.result || {}).item;
      if (typeof navigation.setDetailLabel === "function") {
        navigation.setDetailLabel(item.public_ref || itemRef);
      }
      if (String(item.workflow?.id || "").toLowerCase() === "blitz") {
        renderBlitzItemDetail(context, main, item);
      } else {
        renderWorkflowItemDetail(context, main, item);
      }
      return;
    }
    loading.renderEnvelope(callResult, (body) => renderError(body, callResult));
  })();
}
