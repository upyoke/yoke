// What this operator searched for before, held by the control plane rather
// than by this browser: the same actor-scoped preference storage the screen
// selections use, so the list follows the person across machines.
//
// A read that refuses answers with an empty list — the dialog then shows its
// scope explanation and nothing else, which is the truthful empty state. It
// never shows example queries: a Recent list nobody searched asserts a
// history the product does not have.

const LIST_FUNCTION = "ui_preferences.search_history.list";
const RECORD_FUNCTION = "ui_preferences.search_history.record";

function queriesOf(callResult) {
  if (!callResult || callResult.status !== 200) return [];
  if (!callResult.envelope?.success) return [];
  const queries = callResult.envelope.result?.queries;
  return Array.isArray(queries) ? queries.filter((q) => typeof q === "string") : [];
}

export function createSearchHistory(client) {
  let queries = [];
  return {
    // Reading is cheap and the answer changes when the operator searches, so
    // the dialog refreshes it each time it opens rather than caching a list
    // that goes stale behind them.
    async load() {
      try {
        queries = queriesOf(await client.call({
          function: LIST_FUNCTION, payload: {},
        }));
      } catch {
        queries = [];
      }
      return queries;
    },
    // Recording is a side effect of searching, never something the operator
    // waits on: a refusal here must not cost them their results.
    record(query) {
      const trimmed = String(query || "").trim();
      if (!trimmed) return;
      queries = [trimmed, ...queries.filter((q) => q !== trimmed)];
      client.call({
        function: RECORD_FUNCTION, payload: { query: trimmed },
      }).catch(() => {});
    },
    queries: () => queries,
  };
}
