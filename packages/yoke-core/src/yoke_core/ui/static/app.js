// Read-only universe view. Hand-authored vanilla JS: no build step, no
// framework, no external requests — everything ships inside the yoke-core
// wheel and talks only to the loopback server that served it.
//
// Mount contract: `mountUniverseApp(rootNode)` is the single entry point.
// It renders the whole view into the provided DOM node; the caller owns
// the node, decides when to mount, and may wrap this app in any outer
// shell that provides a node. All server communication rides the session
// cookie set by the app-shell response — no tokens in page state.

const CALL_ENDPOINT = "/api/functions/call";

async function callFunction(functionId, payload) {
  const response = await fetch(CALL_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ function: functionId, payload: payload || {} }),
  });
  // Read text first: an error body may not be JSON (proxy/server failure
  // pages), and an unconditional response.json() would throw and strand
  // the panel at "loading…".
  const text = await response.text();
  let envelope;
  try {
    envelope = JSON.parse(text);
  } catch (parseError) {
    envelope = {
      success: false,
      error: { message: text.trim().slice(0, 200) || "empty non-JSON response" },
    };
  }
  return { status: response.status, envelope };
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// One titled section with a raw-JSON toggle showing the exact function-call
// response envelope the section rendered from.
function section(title) {
  const wrap = el("section", "panel");
  const header = el("div", "panel-header");
  header.appendChild(el("h2", null, title));
  const toggle = el("button", "raw-toggle", "raw JSON");
  toggle.type = "button";
  header.appendChild(toggle);
  wrap.appendChild(header);

  const body = el("div", "panel-body", "loading…");
  wrap.appendChild(body);

  const raw = el("pre", "raw-json");
  raw.hidden = true;
  wrap.appendChild(raw);
  toggle.addEventListener("click", () => { raw.hidden = !raw.hidden; });

  wrap.renderEnvelope = (call_result, renderBody) => {
    raw.textContent = JSON.stringify(call_result.envelope, null, 2);
    body.replaceChildren();
    renderBody(body, call_result);
  };
  return wrap;
}

function renderError(body, callResult) {
  const envelope = callResult.envelope || {};
  const detail = (envelope.error && envelope.error.message) ||
    "request failed";
  body.appendChild(el(
    "p", "error", `read failed (HTTP ${callResult.status}): ${detail}`,
  ));
}

function renderOrgCard(body, callResult) {
  const org = callResult.envelope.result || {};
  body.appendChild(el("h1", "org-name", org.name || "(unnamed org)"));
  body.appendChild(
    el("p", "org-meta", `slug: ${org.slug}  ·  created: ${org.created_at}`),
  );
}

function renderItemsTable(body, callResult) {
  const result = callResult.envelope.result || {};
  const rows = result.rows || [];
  if (rows.length === 0) {
    body.appendChild(el("p", "empty", "no items yet"));
    return;
  }
  const table = el("table", "items");
  const head = el("tr");
  for (const columnName of ["id", "title", "status"]) {
    head.appendChild(el("th", null, columnName));
  }
  table.appendChild(head);
  for (const row of rows) {
    const tr = el("tr");
    for (const columnName of ["id", "title", "status"]) {
      tr.appendChild(el("td", null, String(row[columnName] ?? "")));
    }
    table.appendChild(tr);
  }
  body.appendChild(table);
}

async function loadSection(panel, functionId, payload, renderBody) {
  let callResult;
  try {
    callResult = await callFunction(functionId, payload);
  } catch (fetchError) {
    // Network-level failure (server gone, connection refused): status 0
    // marks "no HTTP response" and the panel shows the failure instead
    // of sticking at "loading…".
    callResult = {
      status: 0,
      envelope: { success: false, error: { message: String(fetchError) } },
    };
  }
  const ok = callResult.status === 200 && callResult.envelope.success;
  panel.renderEnvelope(callResult, ok ? renderBody : renderError);
}

export function mountUniverseApp(rootNode) {
  const orgPanel = section("Organization");
  const itemsPanel = section("Items");
  rootNode.replaceChildren(orgPanel, itemsPanel);
  loadSection(orgPanel, "organizations.get", {}, renderOrgCard);
  loadSection(
    itemsPanel,
    "items.list.run",
    { fields: ["id", "title", "status"] },
    renderItemsTable,
  );
}
