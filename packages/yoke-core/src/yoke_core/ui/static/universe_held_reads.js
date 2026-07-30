// The Overview holds its reads for the lifetime of one mount: each read is
// issued once over the widest bucket set, and a project-selection change
// re-renders the held envelopes with no refetch. These helpers own that
// fetch-once/render-per-scope split; the scoped fetch/render primitives they
// build on live in universe_view_support.js.

import { renderError, settledScopedCalls } from "./universe_view_support.js";

// Fetch the widest bucket set once, hold the envelopes, and return a
// re-runnable paint() that renders the subset the current scope names from the
// held results — no refetch on a scope change. `getScope` is read live on
// every paint, so a scope change re-renders held data; `renderRows` receives
// (body, heldCallResults, scope, selectedBuckets). Returns null when the mount
// unmounted before the reads settled.
export async function holdScopedSection(
  context, panel, buckets, calls, getScope, renderRows,
) {
  const { callResults } = await settledScopedCalls(context, calls);
  if (!context.isMounted()) return null;
  const paint = () => {
    const scope = getScope();
    const picked = selectForScope(buckets, callResults, scope);
    // Failure is scoped to the in-scope buckets: one failed per-project read
    // must not poison a scope that excludes it.
    const pickedFailed = picked.callResults.find(
      (result) => !(result.status === 200 && result.envelope.success),
    );
    panel.renderEnvelopes(
      picked.callResults,
      pickedFailed
        ? (body) => renderError(body, pickedFailed)
        : (body, held) => renderRows(body, held, scope, picked.buckets),
    );
  };
  paint();
  return paint;
}

// Which held buckets a scope names. A universe-hold read (buckets === [null])
// and an "all" scope keep every held envelope; a narrower scope keeps only the
// held (bucket, envelope) pairs whose bucket id it names, kept aligned.
function selectForScope(buckets, callResults, scope) {
  if (buckets.length === 1 && buckets[0] === null) {
    return { callResults, buckets };
  }
  if (scope === "all") return { callResults, buckets };
  const wanted = new Set(scope.map(String));
  const keptResults = [];
  const keptBuckets = [];
  buckets.forEach((bucket, index) => {
    if (wanted.has(String(bucket))) {
      keptResults.push(callResults[index]);
      keptBuckets.push(bucket);
    }
  });
  return { callResults: keptResults, buckets: keptBuckets };
}

// Rows from a universe-hold read narrowed to the scope's projects: an "all"
// scope keeps every row; a narrower scope keeps rows whose project (id or slug)
// the scope names. Projectless rows appear only under "all".
export function rowsInScope(rows, scope, projects) {
  if (scope === "all") return rows;
  const wanted = new Set();
  for (const id of scope) {
    wanted.add(String(id));
    const project = projects.find((row) => String(row.id) === String(id));
    if (project && project.slug) wanted.add(String(project.slug));
  }
  return rows.filter((row) => wanted.has(String(row.project)));
}
