// Presentation primitives shared by every view renderer module: titled
// sections with raw-JSON toggles, state pills, table rendering, and the
// scoped loaders that fan a multi-project scope out into per-project calls.
// View modules own what a screen says; this module owns how panels say it.

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
  const heading = el(documentNode, "h2", null, title);
  header.appendChild(heading);
  const toggle = el(documentNode, "button", "raw-toggle", "raw JSON");
  toggle.type = "button";
  header.appendChild(toggle);
  wrap.appendChild(header);

  // The muted count beside the title. Numbers are facts the engine owns: a
  // view passes the total its read served when it carries one, the length
  // of a complete row set it just fetched otherwise, and null when neither
  // holds — a panel with no honest number shows none.
  let countNode = null;
  wrap.setCount = (count) => {
    if (count === null || count === undefined) {
      if (countNode) {
        heading.removeChild(countNode);
        countNode = null;
      }
      return;
    }
    if (!countNode) {
      countNode = el(documentNode, "span", "panel-count");
      heading.appendChild(countNode);
    }
    countNode.textContent = `· ${count}`;
  };

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
  pass: "good",
  fail: "crit",
  skip: "idle",
  // Dependency gate points: an activation gate stops work from starting,
  // an integration gate only orders the landing, a closure gate merely
  // holds the closeout milestone.
  activation: "crit",
  integration: "warn",
  closure: "idle",
  // Capability vocabulary. A capability someone configured but nothing has
  // ever verified must read as loudly as a broken one — warn, never idle.
  provider_access: "run",
  declared_model: "idle",
  verified: "good",
  configured_unverified: "warn",
  declared: "idle",
  // GitHub repository-binding vocabulary: binding and installation
  // lifecycle states, permission verdicts, automation availability, and
  // sync outcomes. A suspended or deleted installation is a severed
  // credential channel and must read as loudly as a failure.
  pending: "warn",
  unavailable: "warn",
  suspended: "crit",
  deleted: "crit",
  satisfied: "good",
  missing: "crit",
  unknown: "warn",
  available: "good",
  success: "good",
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
// A column with its own `href` accessor links that cell the same way (for
// views whose linking cell is not the first). A column marked `pill: true`
// renders its value as a state pill; `mono: true` renders it in the code
// face (stored identifiers, not prose); `code: true` renders it as a `code`
// element — deliberately copyable text, never a button.
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
      const cell = el(documentNode, "td", column.mono ? "mono" : null);
      if (rowHref && index === 0) {
        const link = el(documentNode, "a", "row-link", text);
        link.href = rowHref(row);
        cell.appendChild(link);
      } else if (column.href) {
        const link = el(documentNode, "a", "row-link", text);
        link.href = column.href(row);
        cell.appendChild(link);
      } else if (column.pill) {
        const pill = statePill(documentNode, text);
        if (pill) cell.appendChild(pill);
      } else if (column.code) {
        if (text) cell.appendChild(el(documentNode, "code", null, text));
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

// One call per bucket, settled together. A failed bucket fails the whole
// read — silently dropping one would render a partial universe as if it
// were the whole one.
export async function settledScopedCalls(context, calls) {
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
  const failed = callResults.find(
    (callResult) => !(callResult.status === 200 && callResult.envelope.success),
  );
  return { callResults, failed };
}

// One fan-out serving several panels: each panel shows the same envelopes
// behind its raw-JSON toggle, and a failed bucket fails them all — the
// panels are facets of one read, so none can honestly render rows while
// another shows the failure.
export async function loadScopedPanels(context, panelRenderers, calls) {
  const { callResults, failed } = await settledScopedCalls(context, calls);
  if (!context.isMounted()) return;
  for (const [panel, renderRows] of panelRenderers) {
    panel.renderEnvelopes(
      callResults,
      failed ? (body) => renderError(body, failed) : renderRows,
    );
  }
}

export async function loadScopedSection(context, panel, calls, renderRows) {
  return loadScopedPanels(context, [[panel, renderRows]], calls);
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

// Who runs a session, mode-shaped by what the host can name. The engine models
// an actor as an id and a kind and nothing else — a human actor has no name
// there, because a name belongs to an account and accounts are the host's. So
// the column's identity follows the host's `data.memberDirectory` capability:
// an actor-id → account-label map a host supplies only where accounts exist
// (it rides the same opaque `capabilities.data` bag as portability).
//   * absent (a local or self-hosted universe has actors, not accounts) — the
//     column is "actor" and shows the engine's honest label, a system actor
//     marked so it never reads as a person;
//   * present (a hosted org, whose members map to actors at first sign-in) —
//     the column is "member" and shows the account, falling back to the actor
//     label for a machine actor (a CI token) the directory does not name.
// The directory never invents a mapping: an unnamed actor keeps its engine
// identity rather than borrowing someone else's.
export function whoColumn(capabilities) {
  const directory =
    (capabilities && capabilities.data && capabilities.data.memberDirectory) ||
    null;
  const named = directory && Object.keys(directory).length > 0;
  const actorLabel = (row) => {
    const label = row.actor_label ||
      (row.actor_id == null ? "" : `actor ${row.actor_id}`);
    return row.actor_kind === "system" ? `${label} · system` : label;
  };
  if (!named) return { label: "actor", value: actorLabel };
  return {
    label: "member",
    value: (row) => directory[String(row.actor_id)] || actorLabel(row),
  };
}
