// Read-only universe view. Hand-authored vanilla JS: no build step, no
// framework, no external requests — everything ships inside the yoke-core
// wheel and talks only to the loopback server that served it.
//
// Mount contract: `mountUniverseApp(rootNode)` is the single entry point.
// It renders the whole view into the provided DOM node; the caller owns
// the node, decides when to mount, and may wrap this app in any outer
// shell that provides a node. All server communication rides the session
// cookie set by the app-shell response — no tokens in page state.
//
// Two views, hash-routed: `#/items` and `#/strategy`, each carrying the
// selected project as `?project=<id>` so a shared link restores both the
// view and the scope. The left nav is data-driven (see NAV) — adding a
// route is one more array entry, with no per-view branching in the markup.

const CALL_ENDPOINT = "/api/functions/call";

async function callFunction(functionId, payload, target) {
  const request = { function: functionId, payload: payload || {} };
  // Back-compat: omit `target` unless a view supplies one, so
  // organizations.get / items.list.run keep their global-target default.
  if (target) request.target = target;
  const response = await fetch(CALL_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
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

// Render `rows` as a table whose `columns` each name a header label and a
// per-row cell accessor. Empty rows render the view's own empty message.
function renderTable(body, rows, columns, emptyText) {
  if (rows.length === 0) {
    body.appendChild(el("p", "empty", emptyText));
    return;
  }
  const table = el("table", "items");
  const head = el("tr");
  for (const column of columns) head.appendChild(el("th", null, column.label));
  table.appendChild(head);
  for (const row of rows) {
    const tr = el("tr");
    for (const column of columns) {
      tr.appendChild(el("td", null, String(column.value(row) ?? "")));
    }
    table.appendChild(tr);
  }
  body.appendChild(table);
}

async function loadSection(panel, functionId, payload, renderBody, target) {
  let callResult;
  try {
    callResult = await callFunction(functionId, payload, target);
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

function renderItemsView(main, projectId) {
  const panel = section("Items");
  main.replaceChildren(panel);
  loadSection(
    panel,
    "items.list.run",
    { fields: ["id", "title", "status"], project: String(projectId) },
    (body, callResult) => {
      const rows = (callResult.envelope.result || {}).rows || [];
      renderTable(body, rows, [
        { label: "id", value: (row) => row.id },
        { label: "title", value: (row) => row.title },
        { label: "status", value: (row) => row.status },
      ], "no items yet");
    },
  );
}

function renderStrategyView(main, projectId) {
  const panel = section("Strategy");
  main.replaceChildren(panel);
  loadSection(
    panel,
    "strategy.doc.list",
    {},
    (body, callResult) => {
      const docs = (callResult.envelope.result || {}).docs || [];
      renderTable(body, docs, [
        { label: "slug", value: (doc) => doc.slug },
        { label: "updated", value: (doc) => doc.updated_at },
        { label: "status", value: (doc) => (doc.archived ? "archived" : "active") },
      ], "no strategy docs yet");
    },
    // Strategy docs are project-scoped through the target, not the payload.
    { kind: "global", project_id: String(projectId) },
  );
}

// The nav roster. Each entry renders one view into <main>; the markup maps
// over this array, so a future {id:"runs",...} is a one-line addition.
const NAV = [
  { id: "items", label: "Items", render: renderItemsView },
  { id: "strategy", label: "Strategy", render: renderStrategyView },
];

function parseHash() {
  // "#/items?project=3" -> { view: "items", project: "3" }.
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [viewPart, queryPart] = raw.split("?");
  const view = NAV.some((entry) => entry.id === viewPart)
    ? viewPart : NAV[0].id;
  const project = new URLSearchParams(queryPart || "").get("project");
  return { view, project };
}

function buildHash(view, project) {
  const query = project ? `?project=${encodeURIComponent(project)}` : "";
  return `#/${view}${query}`;
}

function emptyUniversePanel() {
  const panel = section("Universe");
  panel.renderEnvelope(
    { status: 200, envelope: { success: true, result: {} } },
    (body) => { body.appendChild(el("p", "empty", "no projects yet")); },
  );
  return panel;
}

export function mountUniverseApp(rootNode) {
  const brand = el("div", "brand");
  brand.style.color = "var(--yoke-ink)";
  const chooser = el("select", "project-chooser");
  const orgContext = el("span", "org-context", "…");
  const contextSide = el("div", "context-side");
  contextSide.appendChild(chooser);
  contextSide.appendChild(orgContext);
  const header = el("header", "topbar");
  header.appendChild(brand);
  header.appendChild(contextSide);

  const navEl = el("nav", "sidenav");
  const main = el("main", "content");
  const shell = el("div", "shell");
  shell.appendChild(navEl);
  shell.appendChild(main);
  rootNode.replaceChildren(header, shell);

  // The mark uses currentColor, so it must live in the DOM (an <img src>
  // would not inherit color); the brand container's ink flips in dark mode.
  fetch("/assets/yoke-wordmark.svg")
    .then((response) => response.text())
    .then((svg) => { brand.innerHTML = svg; })
    .catch(() => { brand.textContent = "Yoke"; });

  callFunction("organizations.get", {})
    .then((callResult) => {
      const org = (callResult.envelope && callResult.envelope.result) || {};
      orgContext.textContent = org.name || "(unnamed org)";
    })
    .catch(() => { orgContext.textContent = ""; });

  const navLinks = new Map();
  for (const entry of NAV) {
    const link = el("a", "nav-link", entry.label);
    navLinks.set(entry.id, link);
    navEl.appendChild(link);
  }

  let projects = [];

  function resolveRoute() {
    const { view, project } = parseHash();
    const known = projects.some((row) => String(row.id) === String(project));
    const resolved = known
      ? project
      : (projects[0] ? String(projects[0].id) : null);
    return { view, project: resolved };
  }

  function renderRoute() {
    const { view, project } = resolveRoute();
    if (chooser.value !== (project || "")) chooser.value = project || "";
    for (const entry of NAV) {
      const link = navLinks.get(entry.id);
      link.href = buildHash(entry.id, project);
      link.classList.toggle("active", entry.id === view);
    }
    if (project === null) {
      main.replaceChildren(emptyUniversePanel());
      return;
    }
    (NAV.find((entry) => entry.id === view) || NAV[0]).render(main, project);
  }

  chooser.addEventListener("change", () => {
    window.location.hash = buildHash(parseHash().view, chooser.value);
  });
  window.addEventListener("hashchange", renderRoute);

  callFunction("projects.list", { fields: ["id", "slug", "name"] })
    .then((callResult) => {
      const result = (callResult.envelope && callResult.envelope.result) || {};
      projects = result.rows || [];
      chooser.replaceChildren();
      chooser.disabled = projects.length === 0;
      for (const project of projects) {
        const option = el("option", null, project.name || project.slug ||
          String(project.id));
        option.value = String(project.id);
        chooser.appendChild(option);
      }
      renderRoute();
    })
    .catch(() => { projects = []; chooser.disabled = true; renderRoute(); });
}
