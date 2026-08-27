// Presentation primitives shared by every view renderer module: titled
// sections with raw-JSON toggles, state pills, table rendering, and the
// scoped loaders that fan a multi-project scope out into per-project calls.
// View modules own what a screen says; this module owns how panels say it.

import { pillFamilyForState } from "./universe_state_pills.js";

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
export function section(documentNode, title, { showRaw = true } = {}) {
  const wrap = el(documentNode, "section", "panel");
  const header = el(documentNode, "div", "panel-header");
  const heading = el(documentNode, "h2", null, title);
  header.appendChild(heading);
  let toggle = null;
  if (showRaw) {
    toggle = el(documentNode, "button", "raw-toggle", "raw JSON");
    toggle.type = "button";
    header.appendChild(toggle);
  }
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

  const raw = showRaw ? el(documentNode, "pre", "raw-json") : null;
  if (raw) {
    raw.hidden = true;
    wrap.appendChild(raw);
    toggle.addEventListener("click", () => { raw.hidden = !raw.hidden; });
  }

  wrap.renderEnvelopes = (callResults, renderBody) => {
    const envelopes = callResults.map((callResult) => callResult.envelope);
    if (raw) {
      raw.textContent = JSON.stringify(
        envelopes.length === 1 ? envelopes[0] : envelopes, null, 2,
      );
    }
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

// A state value rendered as a tinted lozenge with a leading dot, colored by
// its semantic family. Empty values render nothing at all.
export function statePill(documentNode, value, label = value) {
  const text = String(value ?? "");
  if (!text) return null;
  const family = pillFamilyForState(text);
  const pill = el(documentNode, "span", `pill ${family}`, String(label ?? ""));
  pill.setAttribute("data-state", text);
  return pill;
}

// Parked is the only mode the card and overview display. Other modes
// already show as work and last-active; a parked badge is the wait.
export function parkedBadge(documentNode, mode, reason) {
  const parked = String(mode || "").toLowerCase() === "parked";
  const text = parked && reason ? `parked · ${reason}` : "parked";
  const badge = el(
    documentNode,
    "span",
    parked ? "session-parked-badge" : "session-parked-badge session-parked-badge-empty",
    parked ? text : "",
  );
  if (!parked) badge.hidden = true;
  return badge;
}

export function sessionModePill(documentNode, mode, liveness, reason) {
  return parkedBadge(documentNode, mode, reason);
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
  const tableWrap = el(documentNode, "div", "table-wrap");
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
        const href = column.href(row);
        if (href) {
          const link = el(documentNode, "a", "row-link", text);
          link.href = href;
          cell.appendChild(link);
        } else {
          cell.textContent = text;
        }
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
  tableWrap.appendChild(table);
  body.appendChild(tableWrap);
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

// Deployment mode from the host capability bag; an absent or unknown shape
// reads as a local universe. Shared by every view that adapts copy to how
// the universe is hosted.
export function portabilityMode(capabilities) {
  const portability = capabilities?.data?.portability;
  if (!portability || typeof portability !== "object") return "local";
  return ["local", "self-host", "hosted"].includes(portability.mode)
    ? portability.mode : "local";
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

// Who runs a session, mode-shaped by what the host can name. Local callers hide
// this column. A self-hosted universe has actors rather than accounts, so every
// label carries the actor id and machine actors say what they are. Hosted mode
// shows only account mappings; a machine actor has no account and remains the
// explicit, non-person identity "— machine".
export function whoColumn(capabilities) {
  const mode = portabilityMode(capabilities);
  const directory =
    (capabilities && capabilities.data && capabilities.data.memberDirectory) ||
    {};
  const isMachine = (row) => ["machine", "system"].includes(
    String(row.actor_kind || "").toLowerCase(),
  );
  const actorIdentity = (row) => {
    const id = row.actor_id == null ? "" : `#${row.actor_id}`;
    const label = row.actor_label ||
      (row.actor_id == null ? "unattributed" : `actor ${row.actor_id}`);
    return [
      label,
      id,
      isMachine(row) ? "machine" : "",
    ].filter(Boolean).join(" ");
  };
  if (mode !== "hosted") {
    return { label: "actor", value: actorIdentity, isMachine };
  }
  return {
    label: "member",
    value: (row) => {
      if (isMachine(row)) return "— machine";
      return directory[String(row.actor_id)] || "—";
    },
    isMachine,
  };
}
