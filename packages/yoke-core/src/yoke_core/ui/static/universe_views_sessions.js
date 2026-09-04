import { exactSessionAudience, openSessionMessageCompose } from "./session_message_compose_dialog.js";
import {
  presentSessionControlFailure,
  renderSessionControlFailure,
} from "./universe_session_control_data.js";
import { loadMachinesPanel } from "./universe_machines_panel.js";
import { overviewSection } from "./universe_overview_primitives.js";
import { appendHoldings } from "./universe_sessions_holdings.js";
import {
  callFunction,
  el,
  mergedRows,
  scopeBuckets,
  sessionReasonBadge,
  settledScopedCalls,
} from "./universe_view_support.js";
import {
  appendSessionDiagnostics,
  appendSessionMessageLine,
} from "./universe_session_diagnostics.js";
import { appendSessionAge } from "./universe_session_age.js";
import { appendSessionPresentation } from "./universe_session_presentation.js";
import { appendSteeringHoldings } from "./universe_sessions_steering.js";
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
const ROSTER_STATES = new Set(["active", "stale", "ended"]);
function statRow(documentNode, facts) {
  const row = el(documentNode, "div", "stat-row sessions-stats");
  for (const [value, label] of facts) {
    const tile = el(documentNode, "div", "stat");
    tile.appendChild(el(documentNode, "div", "n", String(value)));
    tile.appendChild(el(documentNode, "div", "l", label));
    row.appendChild(tile);
  }
  return row;
}
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
// The lane is the job Yoke assigned this session, named the way the fleet does.
function laneChip(documentNode, row) {
  const laneLabel = row.lane_label || row.execution_lane || "no lane";
  const chip = el(
    documentNode,
    "span",
    "session-lane",
    row.lane_glyph ? `${row.lane_glyph} ${laneLabel}` : laneLabel,
  );
  chip.title = "execution lane — the job Yoke assigned, not the harness";
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

// Identity, work, health — in that order and nothing else. The harness and its
// lane name the session, the model says what is running it, the holdings say
// what it is doing, and the diagnostics say whether that is going anywhere.
// Steering scope is a holding, so on a steering seat it leads the work the
// way a claimed item leads a worker's.
export function sessionCard(
  documentNode, row, onMessage, projects = [],
) {
  const liveness = String(row.liveness || "").toLowerCase();
  const card = el(
    documentNode, "article", liveness === "stale"
      ? "session-card is-stale" : "session-card",
  );
  card.setAttribute("data-session-id", String(row.session_id || ""));
  card.setAttribute("data-liveness", liveness || "unknown");

  const top = el(documentNode, "div", "session-top");
  const harness = harnessIdentity(row);
  top.appendChild(el(
    documentNode,
    "span",
    `session-harness ${harness.className}`,
    harness.mark,
  ));
  top.appendChild(el(documentNode, "span", "session-executor", harness.label));
  if (liveness === "stale") {
    top.appendChild(el(
      documentNode, "span", "pill crit session-stale-pill", "stale",
    ));
  }
  top.appendChild(laneChip(documentNode, row));
  top.appendChild(sessionReasonBadge(documentNode, row.mode, row.quiet_reason));
  const operator = operatorLabel(documentNode, row);
  if (operator) top.appendChild(operator);
  card.appendChild(top);

  const body = el(documentNode, "div", "session-card-body");
  appendModel(documentNode, body, row);
  appendSteeringHoldings(documentNode, body, row, projects);
  appendSessionPresentation(documentNode, body, row);
  appendHoldings(documentNode, body, row, projects);
  if (row.liveness !== "ended") appendSessionAge(documentNode, body, row);
  const messageAction = sessionMessageButton(documentNode, row, onMessage);
  appendSessionRelay(documentNode, body, row);
  appendSessionMessageLine(documentNode, body, row, messageAction);
  appendSessionMessagingBlocker(documentNode, body, row);
  appendSessionDiagnostics(documentNode, body, row);
  card.appendChild(body);
  return card;
}

function metricFacts(rows) {
  const claimedItems = new Set(rows.flatMap(
    (row) => (Array.isArray(row.holdings?.current) ? row.holdings.current : [])
      .filter((claim) => claim.target_kind === "item")
      .map((claim) => String(claim.target)),
  ).filter(Boolean));
  const actors = new Set(rows.map(
    (row) => row.actor_id ?? row.actor_label,
  ).filter((value) => value !== null && value !== undefined && value !== ""));
  const actorCount = actors.size;
  return [
    [rows.length, `session${rows.length === 1 ? "" : "s"} shown`],
    [claimedItems.size, `item${claimedItems.size === 1 ? "" : "s"} claimed`],
    [actorCount, `actor${actorCount === 1 ? "" : "s"}`],
  ];
}

function renderSessions(
  documentNode, host, rows, onMessage, projects, filtered = false,
) {
  host.replaceChildren(statRow(documentNode, metricFacts(rows)));
  if (!rows.length) {
    host.appendChild(el(
      documentNode,
      "p",
      "sessions-empty",
      filtered ? "No sessions match the current filters." : "No sessions in this scope.",
    ));
    return;
  }
  const grid = el(documentNode, "div", "session-grid");
  for (const row of rows) {
    grid.appendChild(sessionCard(documentNode, row, onMessage, projects));
  }
  host.appendChild(grid);
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
  let visibleRows = [];
  const messageAll = el(
    documentNode, "button", "item-button session-filter-action", "Message all",
  );
  messageAll.type = "button";
  messageAll.disabled = true;
  const reclaim = el(
    documentNode, "button", "item-button session-filter-action", "Reclaim stale",
  );
  reclaim.type = "button";
  reclaim.disabled = true;
  let filters;
  const currentRows = () => filters.apply(visibleRows);
  const openMessage = (sessionId) => openSessionMessageCompose(
    context, dialogHost, { audience: exactSessionAudience([sessionId]) },
  );
  const renderRoster = () => {
    const rows = currentRows();
    renderSessions(
      documentNode, content, rows, openMessage,
      context.projects(),
      filters.isRestrictive(),
    );
    messageAll.disabled = rows.length === 0;
    messageAll.title = rows.length
      ? `Message all ${rows.length} shown session${rows.length === 1 ? "" : "s"}`
      : "No sessions match the current filters";
  };
  filters = sessionRosterFilters(documentNode, renderRoster);
  filters.host.appendChild(messageAll);
  filters.host.appendChild(reclaim);
  messageAll.addEventListener("click", () => {
    const rows = currentRows();
    if (!rows.length) return;
    openSessionMessageCompose(context, dialogHost, {
      audience: exactSessionAudience(rows, filters.summary()),
    });
  });
  view.appendChild(actionStatus);
  view.appendChild(filters.host);
  view.appendChild(content);
  view.appendChild(dialogHost);
  roster.body.replaceChildren(view);
  main.replaceChildren(machines, roster);
  loadMachinesPanel(context, machines.body, { showHeading: false });
  if (typeof chrome.hidePageHead === "function") chrome.hidePageHead();

  const buckets = scopeBuckets(scope, context.projects(), false);
  const reclaimPayload = scope === "all"
    ? { confirm: true }
    : {
      confirm: true,
      project_ids: scope.map((value) => Number(value)),
    };
  let staleCount = 0;

  const load = async () => {
    const calls = buckets.flatMap((bucket) => [...ROSTER_STATES].map(
      (liveness) => ({
        functionId: "sessions.list",
        payload: {
          ...(bucket === null ? {} : { project: bucket }),
          liveness,
          limit: 500,
        },
      }),
    ));
    const { callResults, failed } = await settledScopedCalls(
      context,
      calls,
    );
    if (!context.isMounted()) return;
    if (failed) {
      renderSessionControlFailure(
        content, failed, "Sessions could not be loaded.",
      );
      reclaim.disabled = true;
      reclaim.title = "Sessions could not be read";
      return;
    }
    const rowsBySession = new Map();
    for (const row of mergedRows(callResults, (result) => result.rows)) {
      if (ROSTER_STATES.has(String(row.liveness || "").toLowerCase())) {
        rowsBySession.set(String(row.session_id), row);
      }
    }
    visibleRows = [...rowsBySession.values()];
    staleCount = visibleRows.filter((row) => row.liveness === "stale").length;
    reclaim.disabled = staleCount === 0;
    reclaim.title = staleCount
      ? `Recheck and reclaim ${staleCount} stale session${staleCount === 1 ? "" : "s"}`
      : "No stale sessions in this scope";
    renderRoster();
  };

  reclaim.addEventListener("click", async () => {
    if (reclaim.disabled || staleCount === 0) return;
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
    await load();
  });

  load();
}
