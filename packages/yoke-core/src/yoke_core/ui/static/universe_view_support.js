// Shared scaffolding for the read-only workbench views: panel sections,
// tables, state pills, and the scoped-read loaders. View modules own their
// row/detail presentation; this module owns the presentation primitives.

export function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function callFunction(client, functionId, payload, target) {
  const request = { function: functionId, payload: payload || {} };
  // Preserve the local proxy envelope: omit target unless a view supplies
  // one, so global-target reads keep their server-side default.
  if (target) request.target = target;
  return client.call(request);
}

// One titled section with a raw-JSON toggle showing the exact function-call
// response envelope(s) the section rendered from — a lone envelope for a
// single read, the array of them when a scope fanned out into several.
export function section(documentNode, title) {
  const wrap = el(documentNode, "section", "panel");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, title));
  const toggle = el(documentNode, "button", "raw-toggle", "raw JSON");
  toggle.type = "button";
  header.appendChild(toggle);
  wrap.appendChild(header);

  const body = el(documentNode, "div", "panel-body", "loading…");
  wrap.appendChild(body);

  const raw = el(documentNode, "pre", "raw-json");
  raw.hidden = true;
  wrap.appendChild(raw);
  toggle.addEventListener("click", () => { raw.hidden = !raw.hidden; });

  wrap.renderEnvelopes = (callResults, renderBody) => {
    const envelopes = callResults.map((callResult) => callResult.envelope);
    raw.textContent = JSON.stringify(
      envelopes.length === 1 ? envelopes[0] : envelopes, null, 2,
    );
    body.replaceChildren();
    renderBody(body, callResults);
  };
  wrap.renderEnvelope = (callResult, renderBody) => {
    wrap.renderEnvelopes(
      [callResult],
      (bodyNode, callResults) => renderBody(bodyNode, callResults[0]),
    );
  };
  return wrap;
}

// Semantic color family per state value. Status vocabularies belong to
// workflow types, so this map is a coloring hint and never a gate: any value
// it has not seen renders as a neutral idle pill rather than breaking.
const STATE_PILL_FAMILIES = {
  implementing: "run",
  "reviewing-implementation": "run",
  "reviewed-implementation": "run",
  "polishing-implementation": "run",
  release: "run",
  new: "run",
  executing: "run",
  implemented: "good",
  done: "good",
  active: "good",
  succeeded: "good",
  blocked: "crit",
  failed: "crit",
  error: "crit",
  critical: "crit",
  unclear: "warn",
  warn: "warn",
  warning: "warn",
  stale: "warn",
};

// A state value rendered as a tinted lozenge with a leading dot, colored by
// its semantic family. Empty values render nothing at all.
export function statePill(documentNode, value) {
  const text = String(value ?? "");
  if (!text) return null;
  const family = STATE_PILL_FAMILIES[text.toLowerCase()] || "idle";
  const pill = el(documentNode, "span", `pill ${family}`, text);
  pill.setAttribute("data-state", text);
  return pill;
}

export function renderError(body, callResult) {
  const envelope = callResult.envelope || {};
  const detail = (envelope.error && envelope.error.message) ||
    "request failed";
  body.appendChild(el(
    body.ownerDocument, "p", "error",
    `read failed (HTTP ${callResult.status}): ${detail}`,
  ));
}

// Render `rows` as a table whose `columns` each name a header label and a
// per-row cell accessor. Empty rows render the view's own empty message.
// `rowHref`, when given, makes the first cell of each row the link that opens
// that row's drill-in — a real href, so it can be opened in a new tab.
// A column marked `pill: true` renders its value as a state pill; one marked
// `mono: true` renders in the identifier (monospace) cell treatment.
export function renderTable(body, rows, columns, emptyText, rowHref) {
  const documentNode = body.ownerDocument;
  if (rows.length === 0) {
    body.appendChild(el(documentNode, "p", "empty", emptyText));
    return;
  }
  const table = el(documentNode, "table", "items");
  const head = el(documentNode, "tr");
  for (const column of columns) {
    head.appendChild(el(documentNode, "th", null, column.label));
  }
  table.appendChild(head);
  for (const row of rows) {
    const tr = el(documentNode, "tr");
    for (const [index, column] of columns.entries()) {
      const text = String(column.value(row) ?? "");
      const cell = el(documentNode, "td");
      if (column.mono) cell.className = "mono";
      if (rowHref && index === 0) {
        const link = el(documentNode, "a", "row-link", text);
        link.href = rowHref(row);
        cell.appendChild(link);
      } else if (column.pill) {
        const pill = statePill(documentNode, text);
        if (pill) cell.appendChild(pill);
      } else {
        cell.textContent = text;
      }
      tr.appendChild(cell);
    }
    table.appendChild(tr);
  }
  body.appendChild(table);
}

export async function loadSection(
  context, panel, functionId, payload, renderBody, target,
) {
  let callResult;
  try {
    callResult = await callFunction(
      context.client, functionId, payload, target,
    );
  } catch (fetchError) {
    // Network-level failure (server gone, connection refused): status 0
    // marks "no HTTP response" and the panel shows the failure instead
    // of sticking at "loading…".
    callResult = {
      status: 0,
      envelope: { success: false, error: { message: String(fetchError) } },
    };
  }
  if (!context.isMounted()) return;
  const ok = callResult.status === 200 && callResult.envelope.success;
  panel.renderEnvelope(callResult, ok ? renderBody : renderError);
}

// A multi view's scope resolves into per-call project buckets. "all" is one
// unfiltered call (bucket null) when the read serves the whole universe, or
// one call per roster project when the read refuses without one; a project
// set is always one call per member.
export function scopeBuckets(scope, projects, requiresProject) {
  if (scope !== "all") return scope;
  return requiresProject ? projects.map((row) => String(row.id)) : [null];
}

// One call per bucket, rendered once after every call settles. A failed
// bucket fails the whole section — silently dropping one would render a
// partial universe as if it were the whole one.
export async function loadScopedSection(context, panel, calls, renderRows) {
  const callResults = await Promise.all(calls.map(async (call) => {
    try {
      return await callFunction(
        context.client, call.functionId, call.payload, call.target,
      );
    } catch (fetchError) {
      // Network-level failure (server gone, connection refused): status 0
      // marks "no HTTP response" so the panel shows the failure instead
      // of sticking at "loading…".
      return {
        status: 0,
        envelope: { success: false, error: { message: String(fetchError) } },
      };
    }
  }));
  if (!context.isMounted()) return;
  const failed = callResults.find(
    (callResult) => !(callResult.status === 200 && callResult.envelope.success),
  );
  panel.renderEnvelopes(
    callResults,
    failed ? (body) => renderError(body, failed) : renderRows,
  );
}

// Bucket results merged in call order.
export function mergedRows(callResults, extract) {
  return callResults.flatMap(
    (callResult) => extract(callResult.envelope.result || {}) || [],
  );
}

// A table scoped to exactly one project needs no project column; "all" and
// multi-member sets label every row with the project it belongs to. The
// column sits beside the leading identifier so a row link stays the first
// cell.
export function withProjectColumn(columns, scope, valueOf) {
  if (Array.isArray(scope) && scope.length === 1) return columns;
  return [
    columns[0],
    { label: "project", value: valueOf },
    ...columns.slice(1),
  ];
}
