import { callFunction } from "./universe_view_support.js";
import { SEARCH_DEBOUNCE_MS } from "./universe_shell_controls.js";

// One page of matching entries. The timeline reads a retained history whose
// newest fifty rows can cover seconds, so it loads a page at a time instead
// of asking for a window and calling it the timeline.
export const EVENTS_PAGE_SIZE = 50;

// Every criterion the timeline sends. Server-side each one narrows the rows
// the page is cut from, so a filtered first page is the newest matches
// rather than whatever matched inside an unfiltered page.
export const EVENT_CRITERIA = ["min_severity", "event_name", "source_type", "since"];

// The severity ladder the engine ranks `min_severity` against, lowest first.
export const SEVERITY_CHOICES = [
  "DEBUG", "INFO", "STATUS", "WARN", "ERROR", "FATAL",
];

// Relative windows the engine's `since` parser accepts, with the label each
// one wears in the control.
export const SINCE_CHOICES = [
  ["", "Any time"],
  ["1 hour ago", "Last hour"],
  ["24 hours ago", "Last 24 hours"],
  ["7 days ago", "Last 7 days"],
];

function payloadFor(bucket, criteria, cursor) {
  const filters = {};
  for (const key of EVENT_CRITERIA) {
    const value = String(criteria[key] || "").trim();
    if (value) filters[key] = value;
  }
  return {
    ...(bucket === null || bucket === undefined ? {} : { project: String(bucket) }),
    ...filters,
    history: { limit: EVENTS_PAGE_SIZE, ...(cursor ? { cursor } : {}) },
  };
}

function failureFrom(callResult) {
  if (callResult.status !== 200 || !callResult.envelope.success) return callResult;
  return null;
}

// Buckets are read independently, so their pages have to be ordered against
// each other here. Time decides; a tie falls back to the raw stamp and then
// to bucket and arrival order, so the same pages always merge the same way.
function mergeLanes(lanes) {
  const entries = lanes.flatMap((lane, bucket) => lane.rows.map((row, arrival) => ({
    row,
    bucket,
    arrival,
  })));
  entries.sort((left, right) => {
    const byTime = (Date.parse(right.row.created_at) || 0)
      - (Date.parse(left.row.created_at) || 0);
    if (byTime) return byTime;
    const leftStamp = String(left.row.created_at || "");
    const rightStamp = String(right.row.created_at || "");
    if (leftStamp !== rightStamp) return leftStamp < rightStamp ? 1 : -1;
    return left.bucket - right.bucket || left.arrival - right.arrival;
  });
  return entries.map((entry) => entry.row);
}

/**
 * Owns the Events timeline's criteria, per-bucket cursors, and freshness.
 *
 * Each authorized project bucket keeps its own cursor: the fan-out is what
 * makes an all-project scope readable without asking the server for rows the
 * reader may not see, and a cursor is only meaningful inside the sequence it
 * was issued for.
 *
 * A criteria change starts a new sequence — loaded rows and every cursor are
 * dropped, and only the newest request may render, so a slow reply cannot
 * overwrite criteria the reader has already moved past. `Load more` extends
 * the current sequence instead: a page that fails leaves the entries already
 * on screen exactly where they are, and the control retryable.
 */
export function createEventsHistoryLoader({ context, buckets, onChange }) {
  const criteria = Object.fromEntries(EVENT_CRITERIA.map((key) => [key, ""]));
  const lanes = buckets.map((bucket) => ({ bucket, cursor: null, rows: [] }));
  let sequence = 0;
  let rows = [];
  let loading = false;
  let failure = null;
  let loaded = false;
  let debounceTimer = null;

  const state = () => ({
    criteria: { ...criteria },
    rows,
    loading,
    failure,
    loaded,
    hasMore: lanes.some((lane) => lane.cursor !== null),
  });

  const publish = () => {
    if (typeof onChange === "function") onChange(state());
  };

  const request = async ({ append }) => {
    const pending = append
      ? lanes.filter((lane) => lane.cursor !== null)
      : lanes;
    if (append && !pending.length) return;
    sequence += 1;
    const token = sequence;
    if (!append) {
      for (const lane of lanes) {
        lane.cursor = null;
        lane.rows = [];
      }
      rows = [];
      loaded = false;
    }
    loading = true;
    failure = null;
    publish();
    const callResults = await Promise.all(pending.map(async (lane) => {
      try {
        return await callFunction(
          context.client,
          "events.query.run",
          payloadFor(lane.bucket, criteria, append ? lane.cursor : null),
        );
      } catch (fetchError) {
        // No HTTP response at all: status 0 marks it so the panel reports
        // the failure instead of sticking at "loading…".
        return {
          status: 0,
          envelope: { success: false, error: { message: String(fetchError) } },
        };
      }
    }));
    // A newer sequence already owns the view, or the view is gone.
    if (token !== sequence || !context.isMounted()) return;
    loading = false;
    const failed = callResults.map(failureFrom).find(Boolean);
    if (failed) {
      // One bucket short is a partial universe rendered as a whole one, so
      // the whole read fails rather than quietly dropping that bucket.
      failure = failed;
      publish();
      return;
    }
    callResults.forEach((callResult, index) => {
      const result = callResult.envelope.result || {};
      const lane = pending[index];
      lane.rows = [...lane.rows, ...(result.rows || [])];
      lane.cursor = result.next_cursor || null;
    });
    rows = mergeLanes(lanes);
    loaded = true;
    publish();
  };

  return {
    state,
    start: () => request({ append: false }),
    loadMore: () => request({ append: true }),
    retry: () => request({ append: failure !== null && loaded }),
    // Selecting a criterion restarts the sequence at once: a filter is a
    // deliberate act and should not wait out a text debounce.
    setCriterion: (key, value) => {
      criteria[key] = value;
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      return request({ append: false });
    },
    // Typing costs a request per bucket, so let a burst of keystrokes settle.
    setTypedCriterion: (key, value) => {
      criteria[key] = value;
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        debounceTimer = null;
        request({ append: false });
      }, SEARCH_DEBOUNCE_MS);
    },
    destroy: () => {
      sequence += 1;
      if (debounceTimer !== null) clearTimeout(debounceTimer);
    },
  };
}
