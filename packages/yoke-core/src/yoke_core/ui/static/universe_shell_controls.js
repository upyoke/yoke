// Interactive controls that belong to the universe frame rather than a view:
// the universe-wide search dialog and the persistent environment/footer strip.

import { createFooter } from "./universe_shell_footer.js";
import { createSearchDialog } from "./universe_search_overlay.js";
import { createSearchHistory } from "./universe_search_history.js";
import {
  SEARCH_DOMAINS, createProjectRoster, searchUniverse,
} from "./universe_search_domains.js";

// Exported so a caller waiting for search results waits on the real interval
// rather than a copy of it.
export const SEARCH_DEBOUNCE_MS = 150;
// One character matches most of a universe; two is the point at which a query
// is about something.
const MIN_QUERY_LENGTH = 2;
const SCOPE_EXPLANATION = "Scoped to the universe you are in. The project "
  + "selector does not narrow it — you search the whole universe, and each "
  + "result says which project it is in.";
let shellControlSequence = 0;

function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function section(documentNode, label) {
  const wrap = el(documentNode, "div", "header-search-section");
  wrap.appendChild(el(documentNode, "div", "header-search-section-label", label));
  return wrap;
}

function status(documentNode, text) {
  return el(documentNode, "p", "header-search-status", text);
}

// The empty state is what search opens on, so it says what search covers and
// what this operator asked for before — never fabricated result rows.
function emptyState(documentNode, recent, onRecent) {
  const nodes = [];
  if (recent.length) {
    const wrap = section(documentNode, "Recent");
    for (const query of recent) {
      const row = el(documentNode, "button", "header-search-row", query);
      row.type = "button";
      row.addEventListener("click", () => onRecent(query));
      wrap.appendChild(row);
    }
    nodes.push(wrap);
  }
  const scopes = section(documentNode, "Searches across");
  const chips = el(documentNode, "div", "header-search-scopes");
  for (const domain of SEARCH_DOMAINS) {
    chips.appendChild(el(
      documentNode, "span", "header-search-chip", domain.label,
    ));
  }
  scopes.appendChild(chips);
  nodes.push(scopes);
  nodes.push(el(documentNode, "p", "header-search-hint", SCOPE_EXPLANATION));
  return nodes;
}

function resultLink(documentNode, domain, entry) {
  const link = el(documentNode, "a", "header-search-result");
  link.href = entry.href;
  link.setAttribute("role", "option");
  const copy = el(documentNode, "span", "header-search-copy");
  copy.appendChild(el(
    documentNode, "strong", "header-search-label", entry.label,
  ));
  copy.appendChild(el(
    documentNode, "span", "header-search-meta", entry.meta || "—",
  ));
  link.appendChild(copy);
  link.appendChild(el(documentNode, "span", "header-search-kind", domain.label));
  return link;
}

function createSearch(documentNode, client) {
  const windowNode = documentNode.defaultView;
  const controlId = ++shellControlSequence;
  const history = createSearchHistory(client);
  const projectRoster = createProjectRoster(client);
  let dialog = null;
  let activeIndex = -1;
  let resultLinks = [];
  let renderToken = 0;
  let debounceTimer = null;

  const cancelPending = () => {
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    renderToken += 1;
  };
  const setExpanded = (open) => {
    dialog.input.setAttribute("aria-expanded", open ? "true" : "false");
  };
  const showEmptyState = () => {
    resultLinks = [];
    activeIndex = -1;
    setExpanded(false);
    dialog.body.replaceChildren(...emptyState(
      documentNode, history.queries(), (query) => {
        dialog.input.value = query;
        runQuery();
      },
    ));
  };
  const selectResult = (next) => {
    if (!resultLinks.length) return;
    activeIndex = (next + resultLinks.length) % resultLinks.length;
    for (const [index, link] of resultLinks.entries()) {
      link.classList.toggle("active", index === activeIndex);
      if (index === activeIndex) {
        link.scrollIntoView?.({ block: "nearest" });
        dialog.input.setAttribute("aria-activedescendant", link.id);
      }
    }
  };
  const renderResults = ({ groups, unavailable }, query) => {
    resultLinks = [];
    activeIndex = -1;
    const nodes = [];
    for (const group of groups) {
      const wrap = section(documentNode, group.label);
      for (const entry of group.entries) {
        const link = resultLink(documentNode, group, entry);
        link.id = `universe-search-option-${controlId}-${resultLinks.length}`;
        link.addEventListener("click", () => dialog.close());
        resultLinks.push(link);
        wrap.appendChild(link);
      }
      nodes.push(wrap);
    }
    if (!groups.length) {
      nodes.push(status(documentNode, `Nothing matches “${query}”.`));
    }
    // A domain that refused is named rather than silently contributing
    // nothing: an empty group and a failed read look identical otherwise.
    if (unavailable.length) {
      nodes.push(el(
        documentNode, "p", "header-search-hint",
        `Could not search ${unavailable.join(", ")}. `
        + "Those results are missing, not absent.",
      ));
    }
    dialog.body.replaceChildren(...nodes);
    setExpanded(resultLinks.length > 0);
  };
  const runQuery = async () => {
    const query = dialog.input.value.trim();
    const token = ++renderToken;
    if (!query) {
      showEmptyState();
      return;
    }
    if (query.length < MIN_QUERY_LENGTH) {
      resultLinks = [];
      dialog.body.replaceChildren(status(
        documentNode, `Type at least ${MIN_QUERY_LENGTH} characters.`,
      ));
      setExpanded(false);
      return;
    }
    dialog.body.replaceChildren(status(documentNode, "Searching…"));
    setExpanded(false);
    try {
      const projects = await projectRoster();
      const found = await searchUniverse(client, query, projects || []);
      if (token !== renderToken) return;
      renderResults(found, query);
      if (found.groups.length) history.record(query);
    } catch (error) {
      if (token !== renderToken) return;
      resultLinks = [];
      dialog.body.replaceChildren(status(
        documentNode,
        error instanceof Error
          ? `Search failed: ${error.message}` : "Search is unavailable.",
      ));
      setExpanded(false);
    }
  };
  const scheduleQuery = () => {
    if (debounceTimer !== null) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      runQuery();
    }, SEARCH_DEBOUNCE_MS);
  };

  dialog = createSearchDialog(documentNode, controlId, () => {
    cancelPending();
    dialog.input.value = "";
    showEmptyState();
    // The stored list is read on every open, so a query recorded in another
    // tab or on another machine is already there.
    history.load().then(() => {
      if (dialog.isOpen() && !dialog.input.value.trim()) showEmptyState();
    });
  });

  dialog.input.addEventListener("input", scheduleQuery);
  dialog.input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      selectResult(activeIndex + (event.key === "ArrowDown" ? 1 : -1));
      return;
    }
    if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      const href = resultLinks[activeIndex].href;
      windowNode.location.hash = href.slice(href.indexOf("#"));
      dialog.close();
    }
  });
  return {
    close: () => {
      cancelPending();
      dialog.close();
    },
    isOpen: dialog.isOpen,
    open: dialog.open,
    root: dialog.root,
  };
}

export function createShellControls({ documentNode, client, options }) {
  const search = createSearch(documentNode, client);
  const { footer, dispose: disposeFooter } = createFooter(documentNode, options);
  const windowNode = documentNode.defaultView;
  // Both of search's keyboard contracts are window-level, because a modal
  // owns the whole page while it is open: the shortcut reaches it from any
  // screen, and Escape closes it wherever focus happens to sit inside it —
  // the field, a chip, a result, or the backdrop.
  const onWindowKeydown = (event) => {
    const key = String(event.key || "").toLowerCase();
    if (key === "escape") {
      if (!search.isOpen()) return;
      event.preventDefault();
      search.close();
      return;
    }
    if (!(event.metaKey || event.ctrlKey) || key !== "k") return;
    event.preventDefault();
    // The same keys that opened it are the second way out.
    if (search.isOpen()) search.close();
    else search.open(documentNode.activeElement);
  };
  windowNode.addEventListener("keydown", onWindowKeydown);
  return {
    dispose() {
      windowNode.removeEventListener("keydown", onWindowKeydown);
      search.close();
      disposeFooter();
    },
    footer,
    search: search.root,
  };
}
