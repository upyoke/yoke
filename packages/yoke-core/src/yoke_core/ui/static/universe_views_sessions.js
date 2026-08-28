import { exactSessionAudience, openSessionMessageCompose } from "./session_message_compose_dialog.js";
import {
  presentSessionControlFailure,
  renderSessionControlFailure,
} from "./universe_session_control_data.js";
import { appendHoldings, ownsFocusedItem } from "./universe_sessions_holdings.js";
import {
  callFunction,
  el,
  mergedRows,
  portabilityMode,
  scopeBuckets,
  parkedBadge,
  settledScopedCalls,
  whoColumn,
} from "./universe_view_support.js";
import { relativeAge, relativeTime } from "./universe_time.js";
import { appendSessionDiagnostics } from "./universe_session_diagnostics.js";
import { appendSteeringContext, appendSteeringGroups } from "./universe_sessions_steering.js";
import {
  appendSessionMessaging,
  sessionRosterFilters,
} from "./universe_session_roster_filters.js";
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
// The lane is the job Yoke assigned this session, and it names the session the
// way the fleet does, so it belongs beside the harness that is running it.
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

function operatorLabel(documentNode, row, who, mode) {
  // One machine has one operator, so naming them on every card says nothing.
  if (mode === "local") return null;
  const machine = row.actor_kind === "system";
  const directory = who.label === "member";
  if (machine && directory) {
    return el(documentNode, "span", "session-operator", "machine");
  }
  return el(
    documentNode,
    "span",
    "session-operator",
    who.value(row) || "unattributed",
  );
}

function appendModel(documentNode, body, row) {
  body.appendChild(el(
    documentNode,
    "div",
    "session-model",
    row.model || "model not reported",
  ));
}

function appendAge(documentNode, body, row) {
  const age = el(documentNode, "div", "session-age");
  const add = (prefix, timestamp, now = Date.now()) => {
    const activeNow = prefix === "idle " && relativeAge(timestamp, now) === "now";
    age.appendChild(el(
      documentNode, "span", "session-age-prefix", activeNow ? "active " : prefix,
    ));
    age.appendChild(relativeTime(documentNode, timestamp, now));
  };
  if (row.current_item && ownsFocusedItem(row)) {
    add("claim held ", row.claim_started_at || row.activity_at);
    age.appendChild(el(documentNode, "span", "session-age-separator", " · "));
  } else if (row.current_item) {
    add(row.work_role ? "worktree attached · active " : "attributed · active ", row.activity_at);
    age.appendChild(el(documentNode, "span", "session-age-separator", " · "));
  }
  add("idle ", row.activity_at);
  body.appendChild(age);
}

// Identity, work, health — in that order and nothing else. The harness and its
// lane name the session, the model says what is running it, the holdings say
// what it is doing, and the diagnostics say whether that is going anywhere.
export function sessionCard(
  documentNode, row, who, mode, onMessage, projects = [],
) {
  const card = el(documentNode, "article", "session-card");
  card.setAttribute("data-session-id", String(row.session_id || ""));
  card.setAttribute("data-liveness", row.liveness || "unknown");

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
  top.appendChild(parkedBadge(documentNode, row.mode, row.parked_reason));
  const operator = operatorLabel(documentNode, row, who, mode);
  if (operator) top.appendChild(operator);
  card.appendChild(top);

  const body = el(documentNode, "div", "session-card-body");
  appendModel(documentNode, body, row);
  appendHoldings(documentNode, body, row, projects);
  appendAge(documentNode, body, row);
  appendSessionDiagnostics(documentNode, body, row);
  appendSteeringContext(documentNode, body, row);
  appendSessionMessaging(documentNode, body, row, onMessage);
  card.appendChild(body);
  return card;
}

function metricFacts(rows) {
  const claimedItems = new Set(rows.flatMap(
    (row) => (Array.isArray(row.claims) ? row.claims : [])
      .filter((claim) => claim.target_kind === "item")
      .map((claim) => String(claim.target)),
  ).filter(Boolean));
  const actors = new Set(rows.map(
    (row) => row.actor_id ?? row.actor_label,
  ).filter((value) => value !== null && value !== undefined && value !== ""));
  const actorCount = actors.size;
  return [
    [rows.length, "sessions shown"],
    [claimedItems.size, "items claimed"],
    [actorCount, `actor${actorCount === 1 ? "" : "s"}`],
  ];
}

function renderSessions(
  documentNode, host, rows, who, mode, onMessage, projects, filtered = false,
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
  appendSteeringGroups(documentNode, grid, rows, (row) => sessionCard(
    documentNode, row, who, mode, onMessage, projects,
  ));
  host.appendChild(grid);
}

export function renderSessionsView(context, main, scope, chrome = {}) {
  const documentNode = context.document;
  const view = el(documentNode, "div", "sessions-view");
  const localActions = el(documentNode, "div", "session-control-actions");
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
  let filters;
  const currentRows = () => filters.apply(visibleRows);
  const openMessage = (sessionId) => openSessionMessageCompose(
    context, dialogHost, { audience: exactSessionAudience([sessionId]) },
  );
  const renderRoster = () => {
    const rows = currentRows();
    renderSessions(
      documentNode, content, rows, who, mode, openMessage,
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
  messageAll.addEventListener("click", () => {
    const rows = currentRows();
    if (!rows.length) return;
    openSessionMessageCompose(context, dialogHost, {
      audience: exactSessionAudience(rows, filters.summary()),
    });
  });
  view.appendChild(localActions);
  view.appendChild(actionStatus);
  view.appendChild(filters.host);
  view.appendChild(content);
  view.appendChild(dialogHost);
  main.replaceChildren(view);

  const reclaim = el(documentNode, "button", "item-button", "Reclaim stale");
  reclaim.type = "button";
  reclaim.disabled = true;
  localActions.appendChild(reclaim);
  if (typeof chrome.setPageHead === "function") {
    chrome.setPageHead({
      title: "Sessions",
      summary:
        "Every harness session running against this universe, and what each one holds.",
      actions: [reclaim],
    });
  }

  const buckets = scopeBuckets(scope, context.projects(), false);
  const who = whoColumn(context.capabilities);
  const mode = portabilityMode(context.capabilities);
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
