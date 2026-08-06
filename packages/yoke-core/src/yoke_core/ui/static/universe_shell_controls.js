// Interactive controls that belong to the universe frame rather than a view:
// the cross-screen search and the persistent environment/footer strip.

import { buildUniverseRoute } from "./universe_navigation.js";
import { createFooter } from "./universe_shell_footer.js";

// Items are searched on the server, so the cap travels with the query and
// bounds the response. Sessions are still filtered from a cached roster, so
// theirs bounds how much of that roster the browser holds.
const SEARCH_RESULT_LIMIT = 8;
const SESSION_INDEX_LIMIT = 500;
// Exported so a caller waiting for search results waits on the real interval
// rather than a copy of it.
export const SEARCH_DEBOUNCE_MS = 150;
let shellControlSequence = 0;

function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function successfulRows(callResult, key) {
  if (callResult.status !== 200 || !callResult.envelope?.success) return null;
  return callResult.envelope.result?.[key] || [];
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

  let sessionIndexPromise = null;
  let activeIndex = -1;
  let resultLinks = [];
  let renderToken = 0;
  let debounceTimer = null;

  const close = () => {
    // Drop any pending query so a dismissal is not undone by a keystroke that
    // has not been sent yet.
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    renderToken += 1;
    results.hidden = true;
    input.setAttribute("aria-expanded", "false");
    activeIndex = -1;
  };
  const open = () => {
    results.hidden = false;
    input.setAttribute("aria-expanded", "true");
  };
  // Sessions are matched from a cached roster: the read has no keyword
  // filter, and its newest-activity ordering makes the cap a recency window.
  const loadSessionIndex = () => {
    if (!sessionIndexPromise) {
      sessionIndexPromise = client.call({
        function: "sessions.list", payload: { limit: SESSION_INDEX_LIMIT },
      }).then((call) => {
        const rows = successfulRows(call, "rows");
        return rows === null ? null : rows.map(sessionResult);
      });
    }
    return sessionIndexPromise;
  };
  // Items are matched on the server, so the whole backlog stays reachable no
  // matter how far it has grown past any roster the browser could hold.
  const collectMatches = async (query) => {
    const [itemCall, sessionEntries] = await Promise.all([
      client.call({
        function: "items.search.run",
        payload: { keywords: query, limit: SEARCH_RESULT_LIMIT },
      }).catch(() => null),
      loadSessionIndex().catch(() => null),
    ]);
    const itemRows = itemCall === null
      ? null
      : successfulRows(itemCall, "matches");
    if (itemRows === null && sessionEntries === null) {
      throw new Error("Search is unavailable");
    }
    const needle = query.toLowerCase();
    return [
      ...(itemRows || []).map(itemResult),
      ...(sessionEntries || []).filter((entry) => entry.terms.some(
        (term) => String(term || "").toLowerCase().includes(needle),
      )),
    ].slice(0, SEARCH_RESULT_LIMIT);
  };
  const selectResult = (next) => {
    if (!resultLinks.length) return;
    activeIndex = (next + resultLinks.length) % resultLinks.length;
    for (const [index, link] of resultLinks.entries()) {
      link.classList.toggle("active", index === activeIndex);
    }
  };
  const renderMatches = (matches, query) => {
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
      const matches = await collectMatches(query);
      if (token === renderToken) renderMatches(matches, query);
    } catch (error) {
      if (token !== renderToken) return;
      results.replaceChildren(el(
        documentNode, "p", "header-search-status",
        error instanceof Error ? error.message : "Search is unavailable",
      ));
      open();
    }
  };
  // Each keystroke now costs a request, so let a burst of them settle first.
  const scheduleUpdate = () => {
    if (debounceTimer !== null) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      update();
    }, SEARCH_DEBOUNCE_MS);
  };
  input.addEventListener("input", scheduleUpdate);
  input.addEventListener("focus", () => {
    if (input.value.trim()) scheduleUpdate();
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

export function createShellControls({ documentNode, client, options }) {
  const search = createSearch(documentNode, client);
  const { footer, closePanels } = createFooter(documentNode, options);
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
      closePanels();
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
