import { el } from "./universe_view_support.js";
import { openSessionLaunchDialog } from "./session_launch_create_dialog.js";
import {
  appendLaunchDetail,
  selectionLabels,
} from "./session_launch_detail_card.js";
import { launchFilters } from "./universe_session_launch_filters.js";
import { sessionLaunchPageLoader } from "./universe_session_launch_history.js";
import {
  formatSessionControlTime,
  presentSessionControlFailure,
  renderSessionControlFailure,
  scopedProjectRefs,
  sessionControlCall,
  statusRegion,
} from "./universe_session_control_data.js";

function stateLabel(launch) {
  const state = String(launch.state || "unknown").replaceAll("_", " ");
  const result = String(launch.result_code || "").replaceAll("_", " ");
  return result ? `${state} (${result})` : state;
}

function machineFact(launch) {
  if (launch.assigned_machine_id) return `${launch.assigned_machine_id} assigned`;
  if (launch.requested_machine_id) {
    return `${launch.requested_machine_id} requested`;
  }
  return "unassigned";
}

function summaryLine(launch) {
  const model = selectionLabels({
    model: launch.resolved_model,
    reasoning_effort: launch.resolved_reasoning_effort,
    context_window_tokens: launch.resolved_context_window_tokens,
  }, "vendor model default");
  return [
    `${launch.requested_surface || "unknown surface"} requested`,
    `${launch.selected_surface || "unselected"} selected`,
    machineFact(launch),
    ...model,
  ].join(" · ");
}

function timingLine(launch) {
  const completed = launch.completed_at
    ? `completed ${formatSessionControlTime(launch.completed_at)}`
    : "not completed";
  return `Created ${formatSessionControlTime(launch.created_at)} · ${completed}`;
}

function launchRow(documentNode, launch, view) {
  const launchId = String(launch.launch_id || "");
  const card = el(documentNode, "article", "panel session-launch-row");
  card.setAttribute("data-launch-id", launchId);
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(
    documentNode, "code", "session-control-id", launchId || "—",
  ));
  header.appendChild(el(
    documentNode, "span", "session-launch-state", stateLabel(launch),
  ));
  card.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  body.appendChild(el(
    documentNode,
    "p",
    "fact-line session-launch-project",
    `Project ${launch.project || launch.project_id || "unknown"}`,
  ));
  body.appendChild(el(
    documentNode, "p", "fact-line session-launch-summary", summaryLine(launch),
  ));
  body.appendChild(el(
    documentNode, "p", "fact-line session-launch-timing", timingLine(launch),
  ));
  if (launch.registered_session_id) {
    body.appendChild(el(
      documentNode,
      "p",
      "fact-line session-launch-registered",
      `Registered session ${launch.registered_session_id}`,
    ));
  }
  const expanded = view.expanded.has(launchId);
  const toggle = el(
    documentNode,
    "button",
    "item-button session-launch-expand",
    expanded ? "Hide details" : "Details",
  );
  toggle.type = "button";
  toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
  toggle.addEventListener("click", () => view.toggleDetail(launchId));
  body.appendChild(toggle);
  if (expanded) appendExpansion(documentNode, body, launchId, view);
  card.appendChild(body);
  return card;
}

function appendExpansion(documentNode, body, launchId, view) {
  const region = el(documentNode, "div", "session-launch-detail");
  const failure = view.detailFailures.get(launchId);
  const detail = view.details.get(launchId);
  if (failure) {
    region.appendChild(el(
      documentNode,
      "p",
      "error",
      presentSessionControlFailure(
        failure, "The launch details could not be loaded.",
      ),
    ));
  } else if (!detail) {
    region.appendChild(el(
      documentNode, "p", "session-launch-guidance", "Loading launch details…",
    ));
  } else {
    appendLaunchDetail(documentNode, region, detail, view.mutate);
  }
  body.appendChild(region);
}

function appendSection(documentNode, host, heading, rows, view, empty) {
  host.appendChild(el(documentNode, "h3", "session-launch-heading", heading));
  if (!rows.length) {
    host.appendChild(el(documentNode, "p", "sessions-empty", empty));
    return;
  }
  const grid = el(documentNode, "div", "session-launch-grid");
  for (const row of rows) grid.appendChild(launchRow(documentNode, row, view));
  host.appendChild(grid);
}

function renderLaunches(documentNode, host, loader, view, filtered) {
  const operational = loader.operational();
  const history = loader.history();
  host.replaceChildren();
  if (loader.failure()) {
    renderSessionControlFailure(
      host, loader.failure(), "Session launches could not be loaded.",
    );
    return;
  }
  appendSection(
    documentNode,
    host,
    `Needs attention · ${loader.operationalCount()} unfinished or actionable`,
    operational,
    view,
    filtered
      ? "No unfinished or actionable launch matches these filters."
      : "No unfinished or actionable launches.",
  );
  appendSection(
    documentNode,
    host,
    `History · ${history.length} of ${loader.historyMatchedCount()} matching loaded`,
    history,
    view,
    filtered
      ? "No completed launch matches these filters."
      : "No completed launches yet.",
  );
  if (loader.hasMore()) {
    const more = el(documentNode, "button", "item-button session-launch-more", "Load more");
    more.type = "button";
    more.disabled = loader.loading();
    more.addEventListener("click", () => loader.loadMore());
    host.appendChild(more);
  }
}

export function renderSessionLaunchesView(context, main, scope, chrome = {}) {
  const documentNode = context.document;
  const projects = scopedProjectRefs(context, scope);
  const view = el(documentNode, "div", "session-control-view");
  const status = statusRegion(documentNode);
  const content = el(documentNode, "div", "session-control-content", "Loading launches…");
  const dialogHost = el(documentNode, "div", "session-control-dialog-host");
  const create = el(documentNode, "button", "item-button", "Create session");
  create.type = "button";
  create.disabled = projects.length === 0;
  const actions = el(documentNode, "div", "session-control-actions");
  actions.appendChild(create);
  const state = {
    expanded: new Set(),
    details: new Map(),
    detailFailures: new Map(),
    pending: new Set(),
    mutate: null,
    toggleDetail: null,
  };
  const filters = launchFilters(documentNode, () => loader.reload());
  const loader = sessionLaunchPageLoader(
    context, projects, () => filters.criteria(), () => render(),
  );
  const render = () => {
    const rows = [...loader.operational(), ...loader.history()];
    filters.offer(rows);
    renderLaunches(
      documentNode,
      content,
      loader,
      state,
      Object.keys(filters.criteria()).length > 0,
    );
  };
  view.appendChild(actions);
  view.appendChild(filters.host);
  view.appendChild(status);
  view.appendChild(content);
  view.appendChild(dialogHost);
  main.replaceChildren(view);
  if (typeof chrome.setPageHead === "function") {
    chrome.setPageHead({ title: "Session launches", actions: [create] });
  }
  // One fetch per expanded row: the compact list carries no timeline, evidence,
  // or actions, and a second click while the first is in flight must not
  // duplicate the request or let an older answer overwrite a newer one.
  const ensureDetail = async (launchId) => {
    if (state.details.has(launchId) || state.pending.has(launchId)) return;
    state.pending.add(launchId);
    try {
      const result = await sessionControlCall(
        context, "session_control.launch.get", { launch_id: launchId },
      );
      state.details.set(launchId, result.launch || {});
      state.detailFailures.delete(launchId);
    } catch (error) {
      state.detailFailures.set(launchId, error);
    } finally {
      state.pending.delete(launchId);
    }
    if (context.isMounted() && state.expanded.has(launchId)) render();
  };
  state.toggleDetail = (launchId) => {
    if (state.expanded.has(launchId)) {
      state.expanded.delete(launchId);
      render();
      return;
    }
    state.expanded.add(launchId);
    state.detailFailures.delete(launchId);
    render();
    return ensureDetail(launchId);
  };
  state.mutate = async (operation, launchId, button, extraPayload = {}) => {
    button.disabled = true;
    status.hidden = false;
    const progress = {
      cancel: "Cancelling", reconcile: "Reconciling", retry: "Retrying",
    };
    const outcome = {
      cancel: "cancelled", reconcile: "reconciled", retry: "retried",
    };
    status.textContent = `${progress[operation]} ${launchId}…`;
    try {
      await sessionControlCall(
        context,
        `session_control.launch.${operation}`,
        { launch_id: launchId, ...extraPayload },
      );
      status.textContent = `${launchId} ${outcome[operation]}.`;
      state.details.delete(launchId);
      await loader.reload();
      if (state.expanded.has(launchId)) await ensureDetail(launchId);
    } catch (error) {
      status.textContent = presentSessionControlFailure(
        error, `The launch could not be ${outcome[operation]}.`,
      );
      button.disabled = false;
    }
  };
  const launchCreated = async (result) => {
    const launchId = result?.launch?.launch_id || "Session launch";
    status.hidden = false;
    status.textContent = `${launchId} created. Tracking registration below.`;
    await loader.reload();
  };
  create.addEventListener("click", async () => {
    try {
      await openSessionLaunchDialog(context, dialogHost, projects, launchCreated);
    } catch (error) {
      status.hidden = false;
      status.textContent = presentSessionControlFailure(
        error, "The launch dialog could not be opened.",
      );
    }
  });
  loader.reload();
}
