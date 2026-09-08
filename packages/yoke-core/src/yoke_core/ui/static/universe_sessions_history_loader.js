import { callFunction, el } from "./universe_view_support.js";

const HISTORY_PAGE_SIZE = 50;
const SEARCH_DEBOUNCE_MS = 250;

function successful(result) {
  return result?.status === 200 && result?.envelope?.success === true;
}

function mergeRows(existing, added) {
  const rows = new Map(existing.map((row) => [String(row.session_id), row]));
  for (const row of added) rows.set(String(row.session_id), {
    ...row, liveness: "ended",
  });
  return [...rows.values()];
}

function mergeFacets(current, added) {
  const projects = new Map((current.projects || []).map(
    (entry) => [String(entry.id), entry],
  ));
  for (const entry of added.projects || []) projects.set(String(entry.id), entry);
  const machines = new Map((current.machines || []).map(
    (entry) => [String(entry.id), entry],
  ));
  for (const entry of added.machines || []) machines.set(String(entry.id), entry);
  return {
    projects: [...projects.values()],
    harnesses: [...new Set([
      ...(current.harnesses || []), ...(added.harnesses || []),
    ])].sort(),
    machines: [...machines.values()],
  };
}

function rowFacets(rows) {
  const projects = new Map();
  const machines = new Map();
  const harnesses = new Set();
  for (const row of rows) {
    if (row.project_id != null) projects.set(String(row.project_id), {
      id: row.project_id, slug: row.project || String(row.project_id),
    });
    if (row.machine_id) machines.set(String(row.machine_id), {
      id: row.machine_id, label: row.machine_name || row.machine_id,
    });
    for (const value of [
      row.executor, row.executor_surface, row.presentation_surface,
    ]) if (value) harnesses.add(String(value));
  }
  return {
    projects: [...projects.values()],
    harnesses: [...harnesses].sort(),
    machines: [...machines.values()],
  };
}

export function appendEndedHistory(documentNode, body, row) {
  const prior = row.recent_item_title || row.focus || row.recent_item;
  if (prior) body.appendChild(el(
    documentNode, "div", "fact-line session-history-prior",
    row.recent_item ? `${prior} · ${row.recent_item}` : prior,
  ));
  const ended = row.ended_cause === "killed" ? "Killed" : "Ended";
  body.appendChild(el(
    documentNode, "div", "fact-line session-history-ended",
    `${ended} ${row.activity_at || row.ended_at || row.terminated_at || "time unavailable"}`,
  ));
  if (row.machine_name || row.machine_id) body.appendChild(el(
    documentNode, "div", "fact-line session-history-machine",
    `Machine: ${row.machine_name || row.machine_id}`,
  ));
  if (row.termination_reason) body.appendChild(el(
    documentNode, "div", "fact-line session-history-reason",
    `Reason: ${row.termination_reason}`,
  ));
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
  return [
    [rows.length, `session${rows.length === 1 ? "" : "s"} shown`],
    [claimedItems.size, `item${claimedItems.size === 1 ? "" : "s"} claimed`],
    [actors.size, `actor${actors.size === 1 ? "" : "s"}`],
  ];
}

export function renderSessionRows(
  documentNode, host, rows, cardFor, filtered = false, historySummary = "",
) {
  const stats = el(documentNode, "div", "stat-row sessions-stats");
  for (const [value, label] of metricFacts(rows)) {
    const tile = el(documentNode, "div", "stat");
    tile.appendChild(el(documentNode, "div", "n", String(value)));
    tile.appendChild(el(documentNode, "div", "l", label));
    stats.appendChild(tile);
  }
  host.replaceChildren(stats);
  if (historySummary) host.appendChild(el(
    documentNode, "p", "sessions-history-status", historySummary,
  ));
  if (!rows.length) {
    host.appendChild(el(
      documentNode, "p", "sessions-empty",
      filtered ? "No sessions match the current filters." : "No sessions in this scope.",
    ));
    return;
  }
  const grid = el(documentNode, "div", "session-grid");
  for (const row of rows) grid.appendChild(cardFor(row));
  host.appendChild(grid);
}

export function sessionsHistoryLoader(context, scope, filters, onChange) {
  const scopeProjects = scope === "all" ? [] : scope.map(String);
  let openRows = [];
  let historyRows = [];
  let historyFacets = { projects: [], harnesses: [], machines: [] };
  let matchedCount = 0;
  let nextCursor = null;
  let historyLoaded = false;
  let historyLoading = false;
  let openError = null;
  let historyError = null;
  let generation = 0;
  let searchTimer = null;

  const emit = () => {
    if (context.isMounted()) onChange();
  };
  const historyVisible = () => filters.state() !== "active";
  const resetHistory = () => {
    generation += 1;
    if (searchTimer) clearTimeout(searchTimer);
    historyRows = [];
    matchedCount = 0;
    nextCursor = null;
    historyLoaded = false;
    historyLoading = false;
    historyError = null;
  };

  const loadOpen = async () => {
    let result;
    try {
      result = await callFunction(context.client, "sessions.list", {
        open: true,
        ...(scopeProjects.length ? { projects: scopeProjects } : {}),
      });
    } catch (error) {
      openError = error;
      emit();
      return false;
    }
    if (!successful(result)) {
      openError = result;
      emit();
      return false;
    }
    openRows = (result.envelope.result?.rows || []).filter(
      (row) => row.liveness === "active" || row.liveness === "stale",
    );
    openError = null;
    filters.setFacets(mergeFacets(rowFacets(openRows), historyFacets));
    emit();
    return true;
  };

  const loadHistory = async (append = false) => {
    if (append && !nextCursor) return false;
    const requestGeneration = generation;
    historyLoading = true;
    historyError = null;
    emit();
    let result;
    try {
      result = await callFunction(context.client, "sessions.list", {
        history: {
          limit: HISTORY_PAGE_SIZE,
          cursor: append ? nextCursor : null,
          ...filters.historyCriteria(scopeProjects),
        },
      });
    } catch (error) {
      if (requestGeneration !== generation) return false;
      historyLoading = false;
      historyError = error;
      emit();
      return false;
    }
    if (requestGeneration !== generation) return false;
    historyLoading = false;
    if (!successful(result)) {
      historyError = result;
      emit();
      return false;
    }
    const payload = result.envelope.result || {};
    historyRows = mergeRows(append ? historyRows : [], payload.rows || []);
    matchedCount = Number(payload.matched_count) || 0;
    nextCursor = payload.next_cursor || null;
    historyFacets = mergeFacets(historyFacets, payload.facets || {});
    filters.setFacets(mergeFacets(rowFacets(openRows), historyFacets));
    historyLoaded = true;
    historyError = null;
    emit();
    return true;
  };

  const filtersChanged = (key) => {
    if (key === "state") {
      if (historyVisible() && !historyLoaded && !historyLoading) loadHistory();
      else {
        if (!historyVisible()) {
          generation += 1;
          historyLoading = false;
          if (searchTimer) clearTimeout(searchTimer);
        }
        emit();
      }
      return;
    }
    resetHistory();
    if (!historyVisible()) {
      emit();
      return;
    }
    if (searchTimer) clearTimeout(searchTimer);
    if (key === "search") {
      searchTimer = setTimeout(() => loadHistory(), SEARCH_DEBOUNCE_MS);
    } else {
      loadHistory();
    }
    emit();
  };

  return {
    loadOpen,
    loadMore: () => loadHistory(historyLoaded),
    filtersChanged,
    rows() {
      const state = filters.state();
      const visibleOpen = filters.apply(openRows);
      if (state === "active") return visibleOpen;
      if (state === "ended") return historyRows;
      return [...visibleOpen, ...historyRows];
    },
    openRows: () => openRows,
    bulkRows: () => filters.applyOpen(openRows),
    openError: () => openError,
    historyError: () => historyError,
    historyLoading: () => historyLoading,
    historyLoaded: () => historyLoaded,
    matchedCount: () => matchedCount,
    nextCursor: () => nextCursor,
    historyVisible,
    destroy() {
      generation += 1;
      if (searchTimer) clearTimeout(searchTimer);
    },
  };
}

export { HISTORY_PAGE_SIZE, SEARCH_DEBOUNCE_MS };
