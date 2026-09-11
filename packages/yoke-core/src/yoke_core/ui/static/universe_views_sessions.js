import { exactSessionAudience, openSessionMessageCompose } from "./session_message_compose_dialog.js";
import {
  presentSessionControlFailure,
  renderSessionControlFailure,
} from "./universe_session_control_data.js";
import { loadMachinesPanel } from "./universe_machines_panel.js";
import { overviewSection } from "./universe_overview_primitives.js";
import { appendHoldings } from "./universe_sessions_holdings.js";
import { attachTooltip, tooltipHost } from "./universe_tooltip.js";
import { callFunction, el } from "./universe_view_support.js";
import {
  renderSessionRows,
  sessionsHistoryLoader,
} from "./universe_sessions_history_loader.js";
import {
  appendSessionMessageLine,
  appendSessionPrimaryStatus,
  sessionPrimaryStatus,
} from "./universe_session_diagnostics.js";
import { appendSessionAge } from "./universe_session_age.js";
import { appendSessionPresentation } from "./universe_session_presentation.js";
import { appendSessionUsage } from "./universe_session_usage.js";
import {
  appendSteeringHoldings,
  sortSessionsSteeringFirst,
} from "./universe_sessions_steering.js";
import {
  appendSessionMessagingBlocker,
  appendSessionRelay,
  sessionMessageButton,
  sessionRosterFilters,
} from "./universe_session_roster_filters.js";
import {
  displaySessionModel,
  sessionModelFactTags,
  sessionModelIsRequested,
} from "./session_model_display.js";
function harnessIdentity(row) {
  const executor = String(row.executor_surface || row.executor || "unreported");
  const normalized = executor.toLowerCase();
  if (row.actor_kind === "system" && normalized.includes("ci")) {
    return { mark: "⚙", className: "h-machine", label: executor };
  }
  if (row.executor_mark && row.executor_class_name) {
    return {
      mark: row.executor_mark,
      className: row.executor_class_name,
      label: executor,
    };
  }
  return {
    mark: executor.slice(0, 1).toUpperCase() || "?",
    className: "h-other",
    label: executor,
  };
}
function laneChip(documentNode, row) {
  const laneLabel = row.lane_label || row.execution_lane || "no lane";
  const chip = el(
    documentNode,
    "span",
    "session-lane",
    row.lane_glyph ? `${row.lane_glyph} ${laneLabel}` : laneLabel,
  );
  attachTooltip(
    documentNode, chip,
    "execution lane — the job Yoke assigned, not the harness",
  );
  return chip;
}
function operatorLabel(documentNode, row) {
  const label = String(row.actor_label || "").trim();
  if (!label || /^[-–—]+$/.test(label)) return null;
  return el(documentNode, "span", "session-operator", label);
}
function appendModel(documentNode, body, row) {
  const line = el(documentNode, "div", "session-model-line");
  const modelClass = sessionModelIsRequested(row)
    ? "session-model is-requested"
    : "session-model";
  line.appendChild(el(
    documentNode, "span", modelClass, displaySessionModel(row),
  ));
  for (const fact of sessionModelFactTags(row)) {
    const tagClass = fact.requested
      ? "session-model-tag is-requested"
      : "session-model-tag";
    const tag = el(documentNode, "span", tagClass, fact.label);
    tag.setAttribute("data-model-fact", fact.kind);
    line.appendChild(tag);
  }
  body.appendChild(line);
}
export function sessionCard(
  documentNode, row, onMessage, projects = [], groupColors = new Map(),
) {
  const liveness = String(row.liveness || "").toLowerCase();
  const primary = sessionPrimaryStatus(row);
  const classes = ["session-card"];
  if (primary.state === "stale") classes.push("is-stale");
  if (row.steering_group_session_id) classes.push("is-steering-associated");
  const card = el(documentNode, "article", classes.join(" "));
  card.setAttribute("data-session-id", String(row.session_id || ""));
  card.setAttribute("data-liveness", liveness || "unknown");
  if (row.steering_group_session_id) {
    card.setAttribute(
      "data-steering-group", String(row.steering_group_session_id),
    );
    // Every steering-region rule below reads this custom property with the
    // universal accent as its fallback, so a group's color reaches the
    // steering lead, the outer tint, and every covered worker's card from
    // this one assignment. `groupColors` is computed once per render pass
    // across the caller's whole known roster, so this lookup never collides
    // a distinct group onto the color another visible group already has.
    const color = groupColors.get(String(row.steering_group_session_id));
    if (color) card.style.setProperty("--session-steering-color", color);
  }

  // Two header rows, each answering one question. Who is running this and
  // under whose name, then what state it is in and on what model: the status
  // pill used to sit in the middle of the identity row, where it competed
  // with a harness name and a lane for the same eye.
  const top = el(documentNode, "div", "session-top");
  const harness = harnessIdentity(row);
  top.appendChild(el(
    documentNode,
    "span",
    `session-harness ${harness.className}`,
    harness.mark,
  ));
  top.appendChild(el(documentNode, "span", "session-executor", harness.label));
  top.appendChild(laneChip(documentNode, row));
  const operator = operatorLabel(documentNode, row);
  if (operator) top.appendChild(operator);
  card.appendChild(top);

  const body = el(documentNode, "div", "session-card-body");
  const state = el(documentNode, "div", "session-state-line");
  appendSessionPrimaryStatus(documentNode, state, row);
  appendModel(documentNode, state, row);
  body.appendChild(state);
  appendSessionUsage(documentNode, body, row);
  // One section sequence for every card. An ended session reaches each
  // section with the facts it actually has, and a section with nothing to
  // say stays silent — the card is never rebuilt in a simpler shape, so an
  // ended session reads against a live one without translation.
  appendSteeringHoldings(documentNode, body, row, projects);
  appendSessionPresentation(documentNode, body, row);
  appendHoldings(documentNode, body, row, projects);
  appendSessionAge(documentNode, body, row);
  const messageAction = sessionMessageButton(documentNode, row, onMessage);
  appendSessionRelay(documentNode, body, row);
  appendSessionMessageLine(documentNode, body, row, messageAction);
  appendSessionMessagingBlocker(documentNode, body, row);
  card.appendChild(body);
  return card;
}

export function renderSessionsView(context, main, scope, chrome = {}) {
  const documentNode = context.document;
  const view = el(documentNode, "div", "sessions-view");
  const machines = overviewSection(documentNode, "machines", "Machines");
  const roster = overviewSection(documentNode, "sessions", "Sessions");
  const actionStatus = el(documentNode, "p", "sessions-action-status");
  actionStatus.hidden = true;
  actionStatus.setAttribute("role", "status");
  const content = el(documentNode, "div", "sessions-content", "loading sessions…");
  const dialogHost = el(documentNode, "div", "session-control-dialog-host");
  let machinesPanel = Promise.resolve(null);
  const messageAll = el(
    documentNode, "button", "item-button session-filter-action", "Message all",
  );
  messageAll.type = "button";
  messageAll.disabled = true;
  const messageAllHost = tooltipHost(documentNode, messageAll, "");
  const reclaim = el(
    documentNode, "button", "item-button session-filter-action", "Reclaim stale",
  );
  reclaim.type = "button";
  reclaim.disabled = true;
  const reclaimHost = tooltipHost(documentNode, reclaim, "");
  const loadMore = el(
    documentNode, "button", "item-button session-filter-action", "Load more",
  );
  loadMore.type = "button";
  loadMore.hidden = true;
  let filters;
  let loader;
  const currentRows = () => loader?.rows() || [];
  const openMessage = (sessionId) => openSessionMessageCompose(
    context, dialogHost, { audience: exactSessionAudience([sessionId]) },
  );
  const renderRoster = () => {
    const openError = loader?.openError();
    if (openError && loader.openRows().length === 0) {
      renderSessionControlFailure(content, openError, "Sessions could not be loaded.");
      messageAll.disabled = true;
      reclaim.disabled = true;
      loadMore.hidden = true;
      return;
    }
    const rows = sortSessionsSteeringFirst(currentRows());
    // context.steeringGroupColors() is the app-wide roster's colors, shared
    // by every view, so the color here agrees with Overview and the detail
    // view too.
    const groupColors = context.steeringGroupColors();
    let historySummary = "";
    if (loader?.historyVisible()) {
      const historyError = loader.historyError();
      if (historyError) {
        historySummary = presentSessionControlFailure(
          historyError, "Session history could not be loaded.",
        );
      } else if (loader.historyLoading() && !loader.historyLoaded()) {
        historySummary = "Loading ended session history…";
      }
      // A loaded page needs no sentence of its own: the sessions-shown tile
      // already carries how much of the match is on screen.
    }
    renderSessionRows(
      documentNode, content, rows,
      (row) => sessionCard(
        documentNode, row, openMessage, context.projects(), groupColors,
      ),
      filters.isRestrictive(), historySummary, loader?.matchedTotal() || 0,
    );
    machinesPanel.then((panel) => panel?.redraw()).catch(() => {});
    const bulkRows = loader?.bulkRows() || [];
    messageAll.disabled = bulkRows.length === 0;
    messageAllHost.tooltip.set(bulkRows.length
      ? `Message all ${bulkRows.length} open session${bulkRows.length === 1 ? "" : "s"}`
      : "No open sessions match the current filters");
    const historyError = loader?.historyError();
    loadMore.hidden = !loader?.historyVisible()
      || (!historyError && !loader.nextCursor());
    loadMore.disabled = loader?.historyLoading() || false;
    loadMore.textContent = historyError
      ? (loader.historyLoaded() ? "Retry load more" : "Retry history")
      : "Load more";
    const staleCount = (loader?.openRows() || []).filter(
      (row) => row.liveness === "stale",
    ).length;
    reclaim.disabled = staleCount === 0;
    reclaimHost.tooltip.set(staleCount
      ? `Recheck and reclaim ${staleCount} stale session${staleCount === 1 ? "" : "s"}`
      : "No stale sessions in this scope");
  };
  filters = sessionRosterFilters(documentNode, (key) => loader?.filtersChanged(key));
  loader = sessionsHistoryLoader(context, scope, filters, renderRoster);
  filters.actions.appendChild(messageAllHost);
  filters.actions.appendChild(reclaimHost);
  filters.actions.appendChild(loadMore);
  messageAll.addEventListener("click", () => {
    const rows = loader.bulkRows();
    if (!rows.length) return;
    openSessionMessageCompose(context, dialogHost, {
      audience: exactSessionAudience(rows, filters.summary()),
    });
  });
  loadMore.addEventListener("click", () => loader.loadMore());
  view.appendChild(actionStatus);
  view.appendChild(filters.host);
  view.appendChild(content);
  view.appendChild(dialogHost);
  roster.body.replaceChildren(view);
  main.replaceChildren(machines, roster);
  machinesPanel = loadMachinesPanel(context, machines.body, {
    showHeading: false,
    sessions: () => filters.applyOpen(loader.openRows()),
  });
  if (typeof chrome.hidePageHead === "function") chrome.hidePageHead();

  const reclaimPayload = scope === "all"
    ? { confirm: true }
    : {
      confirm: true,
      project_ids: scope.map((value) => Number(value)),
    };
  reclaim.addEventListener("click", async () => {
    if (reclaim.disabled) return;
    reclaim.disabled = true;
    actionStatus.hidden = false;
    actionStatus.textContent = "Rechecking liveness before reclaim…";
    let result;
    try {
      result = await callFunction(
        context.client,
        "sessions.reclaim_stale",
        reclaimPayload,
      );
    } catch (error) {
      actionStatus.textContent = presentSessionControlFailure(
        error, "Session cleanup could not run.",
      );
      reclaim.disabled = false;
      return;
    }
    const ok = result.status === 200 && result.envelope.success;
    if (!ok) {
      actionStatus.textContent = presentSessionControlFailure(
        result, "Session cleanup could not run.",
      );
      reclaim.disabled = false;
      return;
    }
    const reclaimed = Number(
      (result.envelope.result || {}).total_reclaimed,
    ) || 0;
    actionStatus.textContent =
      `${reclaimed} stale session${reclaimed === 1 ? "" : "s"} reclaimed`;
    if (!await loader.loadOpen()) {
      actionStatus.textContent += `; ${presentSessionControlFailure(
        loader.openError(), "open-session refresh failed; retry reclaim",
      )}`;
    }
  });

  // Parallel with the loader's own fetch, not after it: refreshing
  // steering colors costs no serial latency, and keeps a group that
  // started steering mid-session from staying untinted once this page is
  // next visited (a fresh mount, e.g. re-navigating here), not just at
  // app boot.
  context.refreshSteeringGroupColors()
    .then(() => { if (context.isMounted()) renderRoster(); });
  loader.loadOpen();
}
