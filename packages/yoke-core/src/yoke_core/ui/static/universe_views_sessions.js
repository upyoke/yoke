import { itemDrillInHref } from "./universe_item_routes.js";
import {
  callFunction,
  el,
  mergedRows,
  portabilityMode,
  renderError,
  scopeBuckets,
  sessionModePill,
  settledScopedCalls,
  statePill,
  whoColumn,
} from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";
const LIVE_STATES = new Set(["active", "stale"]);
const WORKTREE_ROLES = new Set(["integration", "worker"]);
function sessionItemHref(row) {
  return itemDrillInHref({
    projectId: row.current_item_project_id,
    projectSequence: row.current_item_project_sequence,
    publicRef: row.current_item,
  });
}
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
function appendAssignment(documentNode, body, row) {
  const work = el(documentNode, "div", "session-work");
  if (!row.current_item) {
    work.appendChild(el(
      documentNode,
      "span",
      "session-unassigned",
      row.current_item_title || "No actionable work right now",
    ));
    body.appendChild(work);
    return;
  }

  const marker = el(
    documentNode,
    "span",
    `session-lock${row.owns_current_item ? "" : " attached"}`,
    row.owns_current_item ? "🔒" : "↳",
  );
  marker.title = row.owns_current_item
    ? "this session owns the item claim"
    : "worktree lane on the owning session's item; holds no item claim";
  work.appendChild(marker);
  const href = sessionItemHref(row);
  const item = el(documentNode, href ? "a" : "span", "session-item-link");
  item.textContent = String(row.current_item);
  if (href) item.href = href;
  work.appendChild(item);
  if (row.current_item_title) {
    work.appendChild(el(
      documentNode,
      "span",
      "session-item-title",
      `· ${row.current_item_title}`,
    ));
  }
  work.appendChild(el(
    documentNode,
    "span",
    "session-work-role",
    row.work_role || (row.owns_current_item ? "item" : "attached"),
  ));
  body.appendChild(work);
}
function appendRuntime(documentNode, body, row) {
  const runtime = el(documentNode, "div", "session-runtime");
  const laneLabel = row.lane_label || row.execution_lane || "no lane";
  const laneText = row.lane_glyph ? `${row.lane_glyph} ${laneLabel}` : laneLabel;
  const lane = el(
    documentNode,
    "span",
    "session-lane",
    laneText,
  );
  lane.title = "execution lane — the job Yoke assigned, not the harness";
  runtime.appendChild(lane);
  runtime.appendChild(el(
    documentNode,
    "span",
    "session-model",
    row.model || "model not reported",
  ));
  body.appendChild(runtime);
}
function appendAge(documentNode, body, row) {
  const age = el(documentNode, "div", "session-age");
  let lead = "idle ";
  let timestamp = row.activity_at;
  if (row.current_item && row.owns_current_item) {
    lead = "claim held ";
    timestamp = row.claim_started_at || row.activity_at;
  } else if (row.current_item) {
    lead = "worktree attached · active ";
  }
  age.appendChild(el(documentNode, "span", "session-age-prefix", lead));
  age.appendChild(relativeTime(documentNode, timestamp));
  body.appendChild(age);
}
function footerIdentity(row, who, mode) {
  if (mode === "local") {
    return { local: true, label: "this machine", machine: false };
  }
  const machine = row.actor_kind === "system";
  const directory = who.label === "member";
  return {
    local: false,
    label: machine && directory ? "—" : (who.value(row) || "unattributed"),
    machine: machine && directory,
  };
}
function appendFooter(documentNode, card, row, who, mode) {
  const footer = el(documentNode, "div", "session-foot");
  const identity = footerIdentity(row, who, mode);
  if (identity.local) {
    footer.appendChild(el(documentNode, "span", "session-local-mark", "◍"));
  } else {
    const avatar = el(
      documentNode,
      "span",
      "session-actor-avatar",
      identity.machine
        ? "⚙"
        : String(identity.label).slice(0, 1).toUpperCase(),
    );
    footer.appendChild(avatar);
  }
  footer.appendChild(el(
    documentNode,
    "span",
    "session-operator",
    identity.label,
  ));
  if (identity.machine) {
    footer.appendChild(el(documentNode, "span", "session-machine", "machine"));
  }
  footer.appendChild(el(documentNode, "span", "session-footer-separator", "·"));
  footer.appendChild(el(documentNode, "span", null, "session"));
  footer.appendChild(el(
    documentNode,
    "span",
    "session-id",
    String(row.session_id || "unreported"),
  ));
  card.appendChild(footer);
}
function sessionCard(documentNode, row, who, mode) {
  const card = el(documentNode, "article", "session-card");
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
  top.appendChild(sessionModePill(documentNode, row.mode, row.liveness));
  card.appendChild(top);

  const body = el(documentNode, "div", "session-card-body");
  appendAssignment(documentNode, body, row);
  appendRuntime(documentNode, body, row);
  appendAge(documentNode, body, row);
  card.appendChild(body);
  appendFooter(documentNode, card, row, who, mode);
  return card;
}

function metricFacts(rows) {
  const claimedItems = new Set(rows.filter(
    (row) => row.owns_current_item && row.current_item,
  ).map((row) => row.current_item));
  const worktreeLanes = rows.filter(
    (row) =>
      String(row.current_item_workflow_id || "").toLowerCase() === "blitz"
      && WORKTREE_ROLES.has(String(row.work_role || "").toLowerCase()),
  ).length;
  const actors = new Set(rows.map(
    (row) => row.actor_id ?? row.actor_label,
  ).filter((value) => value !== null && value !== undefined && value !== ""));
  const actorCount = actors.size;
  return [
    [rows.length, "live sessions"],
    [claimedItems.size, "items claimed"],
    [worktreeLanes, "Blitz worktree lanes"],
    [actorCount, `actor${actorCount === 1 ? "" : "s"}`],
  ];
}

function renderSessions(documentNode, host, rows, who, mode) {
  host.replaceChildren(statRow(documentNode, metricFacts(rows)));
  if (!rows.length) {
    host.appendChild(el(
      documentNode,
      "p",
      "sessions-empty",
      "No live sessions in this scope.",
    ));
    return;
  }
  const grid = el(documentNode, "div", "session-grid");
  for (const row of rows) {
    grid.appendChild(sessionCard(documentNode, row, who, mode));
  }
  host.appendChild(grid);
}

export function renderSessionsView(context, main, scope, chrome = {}) {
  const documentNode = context.document;
  const view = el(documentNode, "div", "sessions-view");
  const actionStatus = el(documentNode, "p", "sessions-action-status");
  actionStatus.hidden = true;
  actionStatus.setAttribute("role", "status");
  const content = el(documentNode, "div", "sessions-content", "loading sessions…");
  view.appendChild(actionStatus);
  view.appendChild(content);
  main.replaceChildren(view);

  const reclaim = el(documentNode, "button", "item-button", "Reclaim stale");
  reclaim.type = "button";
  reclaim.disabled = true;
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
    const calls = buckets.flatMap((bucket) => [...LIVE_STATES].map(
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
      content.replaceChildren();
      renderError(content, failed);
      reclaim.disabled = true;
      reclaim.title = "Sessions could not be read";
      return;
    }
    const rowsBySession = new Map();
    for (const row of mergedRows(callResults, (result) => result.rows)) {
      if (LIVE_STATES.has(String(row.liveness || "").toLowerCase())) {
        rowsBySession.set(String(row.session_id), row);
      }
    }
    const rows = [...rowsBySession.values()];
    staleCount = rows.filter((row) => row.liveness === "stale").length;
    reclaim.disabled = staleCount === 0;
    reclaim.title = staleCount
      ? `Recheck and reclaim ${staleCount} stale session${staleCount === 1 ? "" : "s"}`
      : "No stale sessions in this scope";
    renderSessions(documentNode, content, rows, who, mode);
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
      actionStatus.textContent = `Cleanup failed: ${String(error)}`;
      reclaim.disabled = false;
      return;
    }
    const ok = result.status === 200 && result.envelope.success;
    if (!ok) {
      actionStatus.textContent =
        (result.envelope.error || {}).message || "Cleanup failed";
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
