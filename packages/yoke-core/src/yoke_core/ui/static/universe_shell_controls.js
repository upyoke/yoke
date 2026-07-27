// Interactive controls that belong to the universe frame rather than a view:
// the cross-screen search and the persistent environment/footer strip.

import { buildUniverseRoute } from "./universe_navigation.js";

const DEFAULT_DOCS_URL = "https://github.com/upyoke/yoke/tree/main/docs";
let shellControlSequence = 0;

function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function successfulRows(callResult) {
  if (callResult.status !== 200 || !callResult.envelope?.success) return null;
  return callResult.envelope.result?.rows || [];
}

function itemResult(row) {
  const ref = String(row.public_ref || row.id || "item");
  return {
    href: buildUniverseRoute(
      "items", row.project_id ? String(row.project_id) : null, ref,
    ),
    kind: "Item",
    label: String(row.title || ref),
    meta: [ref, row.project, row.status].filter(Boolean).join(" · "),
    terms: [
      ref, row.title, row.project, row.project_name, row.status, row.owner,
      row.workflow_id,
    ],
  };
}

function sessionResult(row) {
  const sessionId = String(row.session_id || "session");
  return {
    href: buildUniverseRoute(
      "sessions", row.project_id ? String(row.project_id) : null,
    ),
    kind: "Session",
    label: sessionId,
    meta: [
      row.current_item, row.current_item_title, row.actor_label, row.executor,
    ].filter(Boolean).join(" · "),
    terms: [
      sessionId, row.current_item, row.current_item_title, row.actor_label,
      row.executor, row.model, row.project, row.execution_lane,
    ],
  };
}

function createSearch(documentNode, client) {
  const windowNode = documentNode.defaultView;
  const controlId = ++shellControlSequence;
  const host = el(documentNode, "div", "header-search");
  const label = el(
    documentNode, "label", "shell-visually-hidden",
    "Search items and sessions",
  );
  label.htmlFor = `universe-search-input-${controlId}`;
  const input = el(documentNode, "input", "header-search-input");
  input.id = `universe-search-input-${controlId}`;
  input.type = "search";
  input.placeholder = "Search items, sessions…";
  input.setAttribute("aria-label", "Search items and sessions");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute(
    "aria-controls", `universe-search-results-${controlId}`,
  );
  host.appendChild(label);
  host.appendChild(input);
  host.appendChild(el(documentNode, "kbd", "header-search-key", "⌘K"));
  const results = el(documentNode, "div", "header-search-results");
  results.id = `universe-search-results-${controlId}`;
  results.setAttribute("role", "listbox");
  results.hidden = true;
  host.appendChild(results);

  let indexPromise = null;
  let activeIndex = -1;
  let resultLinks = [];
  let renderToken = 0;

  const close = () => {
    results.hidden = true;
    input.setAttribute("aria-expanded", "false");
    activeIndex = -1;
  };
  const open = () => {
    results.hidden = false;
    input.setAttribute("aria-expanded", "true");
  };
  const loadIndex = () => {
    if (!indexPromise) {
      indexPromise = Promise.allSettled([
        client.call({
          function: "items.overview.list", payload: { limit: 500 },
        }),
        client.call({ function: "sessions.list", payload: { limit: 500 } }),
      ]).then((settled) => {
        const calls = settled.map(
          (outcome) => outcome.status === "fulfilled" ? outcome.value : null,
        );
        const itemRows = calls[0] ? successfulRows(calls[0]) : null;
        const sessionRows = calls[1] ? successfulRows(calls[1]) : null;
        if (itemRows === null && sessionRows === null) {
          throw new Error("Search is unavailable");
        }
        return [
          ...(itemRows || []).map(itemResult),
          ...(sessionRows || []).map(sessionResult),
        ];
      });
    }
    return indexPromise;
  };
  const selectResult = (next) => {
    if (!resultLinks.length) return;
    activeIndex = (next + resultLinks.length) % resultLinks.length;
    for (const [index, link] of resultLinks.entries()) {
      link.classList.toggle("active", index === activeIndex);
    }
  };
  const renderMatches = (entries, query) => {
    const needle = query.toLowerCase();
    const matches = entries.filter((entry) => entry.terms.some(
      (term) => String(term || "").toLowerCase().includes(needle),
    )).slice(0, 8);
    resultLinks = [];
    results.replaceChildren();
    if (!matches.length) {
      results.appendChild(el(
        documentNode, "p", "header-search-status",
        `No items or sessions match “${query}”.`,
      ));
    }
    for (const entry of matches) {
      const link = el(documentNode, "a", "header-search-result");
      link.href = entry.href;
      link.setAttribute("role", "option");
      link.appendChild(el(
        documentNode, "span", "header-search-kind", entry.kind,
      ));
      const copy = el(documentNode, "span", "header-search-copy");
      copy.appendChild(el(
        documentNode, "strong", "header-search-label", entry.label,
      ));
      copy.appendChild(el(
        documentNode, "span", "header-search-meta", entry.meta || "—",
      ));
      link.appendChild(copy);
      link.addEventListener("click", close);
      resultLinks.push(link);
      results.appendChild(link);
    }
    activeIndex = -1;
    open();
  };
  const update = async () => {
    const query = input.value.trim();
    const token = ++renderToken;
    if (!query) {
      close();
      return;
    }
    results.replaceChildren(el(
      documentNode, "p", "header-search-status",
      query.length < 2 ? "Type at least two characters." : "Searching…",
    ));
    open();
    if (query.length < 2) return;
    try {
      const entries = await loadIndex();
      if (token === renderToken) renderMatches(entries, query);
    } catch (error) {
      if (token !== renderToken) return;
      results.replaceChildren(el(
        documentNode, "p", "header-search-status",
        error instanceof Error ? error.message : "Search is unavailable",
      ));
      open();
    }
  };
  input.addEventListener("input", update);
  input.addEventListener("focus", () => {
    if (input.value.trim()) update();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      close();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      selectResult(activeIndex + (event.key === "ArrowDown" ? 1 : -1));
      return;
    }
    if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      windowNode.location.hash = resultLinks[activeIndex].href;
      close();
    }
  });
  return { close, host, input };
}

function environmentLabel(options) {
  if (options.environmentLabel) return String(options.environmentLabel);
  const mode = options.capabilities?.data?.portability?.mode;
  if (mode === "hosted") return "hosted universe";
  if (mode === "selfhost") return "self-hosted universe";
  return "local universe";
}

function createFooter(documentNode, options) {
  const footer = el(documentNode, "footer", "app-footer");
  footer.appendChild(el(documentNode, "span", "app-footer-mark", "Yoke"));
  footer.appendChild(el(
    documentNode, "span", "app-footer-environment", environmentLabel(options),
  ));
  const links = el(documentNode, "span", "app-footer-links");
  const docs = el(documentNode, "a", "app-footer-link", "Docs");
  docs.href = String(options.docsUrl || DEFAULT_DOCS_URL);
  docs.target = "_blank";
  docs.rel = "noopener noreferrer";
  links.appendChild(docs);
  const keyboard = el(
    documentNode, "button", "app-footer-link keyboard-help-toggle", "Keyboard",
  );
  keyboard.type = "button";
  keyboard.setAttribute("aria-expanded", "false");
  links.appendChild(keyboard);
  links.appendChild(el(
    documentNode,
    "span",
    "app-footer-version",
    String(options.versionLabel || "version unavailable"),
  ));
  footer.appendChild(links);
  const panel = el(documentNode, "div", "keyboard-help");
  panel.hidden = true;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Keyboard shortcuts");
  for (const [key, action] of [
    ["⌘K / Ctrl K", "Search items and sessions"],
    ["↑ / ↓", "Move through search results"],
    ["Enter", "Open the selected result"],
    ["Esc", "Close search or keyboard help"],
  ]) {
    const row = el(documentNode, "div", "keyboard-help-row");
    row.appendChild(el(documentNode, "kbd", null, key));
    row.appendChild(el(documentNode, "span", null, action));
    panel.appendChild(row);
  }
  footer.appendChild(panel);
  keyboard.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    keyboard.setAttribute("aria-expanded", String(!panel.hidden));
  });
  return { footer, keyboardPanel: panel };
}

export function createShellControls({ documentNode, client, options }) {
  const search = createSearch(documentNode, client);
  const { footer, keyboardPanel } = createFooter(documentNode, options);
  const windowNode = documentNode.defaultView;
  const onWindowKeydown = (event) => {
    const key = String(event.key || "").toLowerCase();
    if ((event.metaKey || event.ctrlKey) && key === "k") {
      event.preventDefault();
      search.input.focus?.();
      if (search.input.value.trim()) {
        search.input.dispatchEvent(new Event("input"));
      }
      return;
    }
    if (event.key === "Escape") {
      search.close();
      keyboardPanel.hidden = true;
    }
  };
  windowNode.addEventListener("keydown", onWindowKeydown);
  return {
    dispose() {
      windowNode.removeEventListener("keydown", onWindowKeydown);
    },
    footer,
    search: search.host,
  };
}
