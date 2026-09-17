// Interactive controls that belong to the universe frame rather than a view:
// the universe-wide search dialog and the persistent environment/footer strip.

import { createFooter } from "./universe_shell_footer.js";
import { createSearchDialog } from "./universe_search_overlay.js";
import { createSearchHistory } from "./universe_search_history.js";
import {
  SEARCH_DOMAINS, createUniverseSearch,
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

function resultLink(documentNode, entry) {
  const link = el(documentNode, "a", "header-search-result");
  link.href = entry.href;
  link.setAttribute("role", "option");
  // The group heading above already names the domain, so a per-row kind
  // label would repeat it once per result.
  link.appendChild(el(
    documentNode, "strong", "header-search-label", entry.label,
  ));
  link.appendChild(el(
    documentNode, "span", "header-search-meta", entry.meta || "—",
  ));
  return link;
}

function createSearch(documentNode, client) {
  const windowNode = documentNode.defaultView;
  const controlId = ++shellControlSequence;
  const history = createSearchHistory(client);
  const search = createUniverseSearch(client);
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
  // Domains answer one at a time, so the panel is rebuilt from what is known
  // so far rather than held blank until the slowest read lands.
  const renderProgress = (query, answers) => {
    resultLinks = [];
    activeIndex = -1;
    const nodes = [];
    const unavailable = [];
    let pending = 0;
    for (const domain of SEARCH_DOMAINS) {
      if (!answers.has(domain.key)) {
        pending += 1;
        continue;
      }
      const entries = answers.get(domain.key);
      if (entries === null) {
        unavailable.push(domain.label);
        continue;
      }
      if (!entries.length) continue;
      const wrap = section(documentNode, domain.label);
      for (const entry of entries) {
        const link = resultLink(documentNode, entry);
        link.id = `universe-search-option-${controlId}-${resultLinks.length}`;
        link.addEventListener("click", () => dialog.close());
        resultLinks.push(link);
        wrap.appendChild(link);
      }
      nodes.push(wrap);
    }
    if (pending) {
      nodes.push(status(documentNode, "Searching…"));
    } else if (!nodes.length && !unavailable.length) {
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
    const answers = new Map();
    renderProgress(query, answers);
    await search(query, (domain, entries) => {
      if (token !== renderToken) return;
      answers.set(domain.key, entries);
      renderProgress(query, answers);
    });
    if (token !== renderToken) return;
    // Remembering a query that found nothing would offer it back as though
    // it had worked.
    if (resultLinks.length) history.record(query);
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
    // Reading the catalogues starts when the dialog opens rather than on the
    // first keystroke: the operator spends a second typing either way, and
    // the alternative is a blank panel while a universe-wide fan-out runs.
    search.warm();
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
  // A dialog that outlives the screen it was opened over becomes an invisible
  // click-blocker: the backdrop keeps swallowing pointer events on a page the
  // operator never opened it from, and nothing on screen says why. So a route
  // change the dialog did not make — Back, a pasted link, any navigation from
  // elsewhere in the shell — closes it, exactly as Escape does. Choosing a
  // result already closes it before navigating, and closing twice is a no-op,
  // so this is a second guarantee rather than a second behaviour.
  const onRouteChange = () => {
    if (search.isOpen()) search.close();
  };
  windowNode.addEventListener("hashchange", onRouteChange);
  return {
    dispose() {
      windowNode.removeEventListener("keydown", onWindowKeydown);
      windowNode.removeEventListener("hashchange", onRouteChange);
      search.close();
      disposeFooter();
    },
    footer,
    search: search.root,
  };
}
