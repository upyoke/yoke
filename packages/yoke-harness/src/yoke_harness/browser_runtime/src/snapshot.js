'use strict';

/**
 * Accessibility snapshot and ref system.
 *
 * Exports:
 *   accessibilitySnapshot(page) -> { tree, refs, url, timestamp }
 *   buildRefMap(page)           -> { [refId]: locatorString }
 *
 * The accessibility tree is captured via page.accessibility.snapshot().
 * Interactive elements are annotated with stable integer ref IDs.
 * Ref assignment priority: data-testid > ARIA role+name > semantic CSS > positional fallback.
 */

/**
 * Roles considered interactive -- elements with these roles receive ref IDs.
 * Non-interactive elements (static text, decorative images, generic groups) are excluded.
 */
const INTERACTIVE_ROLES = new Set([
  'button',
  'link',
  'textbox',
  'checkbox',
  'radio',
  'combobox',
  'listbox',
  'menuitem',
  'menuitemcheckbox',
  'menuitemradio',
  'option',
  'searchbox',
  'slider',
  'spinbutton',
  'switch',
  'tab',
  'treeitem',
]);

/**
 * Roles considered semantically significant -- these also receive ref IDs.
 */
const SEMANTIC_ROLES = new Set([
  'heading',
  'img',
  'navigation',
  'main',
  'banner',
  'contentinfo',
  'complementary',
  'form',
  'region',
  'dialog',
  'alertdialog',
  'alert',
  'status',
  'table',
  'row',
  'cell',
  'columnheader',
  'rowheader',
]);

/**
 * Determine if an accessibility node should receive a ref ID.
 * Interactive elements always get refs. Semantic elements with names get refs.
 * Static text nodes, generic containers, and decorative images do not.
 */
function shouldAssignRef(node) {
  if (!node || !node.role) return false;
  const role = node.role.toLowerCase();

  // Interactive elements always get refs
  if (INTERACTIVE_ROLES.has(role)) return true;

  // Semantic elements get refs only if they have a name
  if (SEMANTIC_ROLES.has(role) && node.name) return true;

  return false;
}

/**
 * Query the DOM for interactive elements and build a mapping from
 * a canonical key to the best Playwright locator string.
 *
 * Ref assignment priority:
 *   1. data-testid   -> [data-testid="value"]
 *   2. ARIA role+name -> role=<role>[name="<name>"]
 *   3. Semantic CSS   -> tag#id or tag.class (if unique)
 *   4. Positional     -> nth= selectors
 *
 * Returns an array of { key, locator } where key is "role::name" for matching
 * against the accessibility tree.
 */
async function queryInteractiveElements(page) {
  return page.evaluate(() => {
    const interactiveSelectors = [
      'button', 'a', 'input', 'select', 'textarea',
      '[role="button"]', '[role="link"]', '[role="textbox"]',
      '[role="checkbox"]', '[role="radio"]', '[role="combobox"]',
      '[role="listbox"]', '[role="menuitem"]', '[role="option"]',
      '[role="searchbox"]', '[role="slider"]', '[role="spinbutton"]',
      '[role="switch"]', '[role="tab"]', '[role="treeitem"]',
      '[role="heading"]', '[role="navigation"]', '[role="main"]',
      '[role="banner"]', '[role="contentinfo"]', '[role="complementary"]',
      '[role="form"]', '[role="region"]', '[role="dialog"]',
      '[role="alertdialog"]', '[role="alert"]', '[role="status"]',
      '[role="img"]', '[role="table"]',
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'nav', 'main', 'form',
      'img[alt]', 'table',
    ];

    const selector = interactiveSelectors.join(', ');
    const elements = Array.from(document.querySelectorAll(selector));
    const results = [];
    const seenLocators = new Set();

    for (const el of elements) {
      // Compute the accessibility role
      const explicitRole = el.getAttribute('role');
      let computedRole = explicitRole;
      if (!computedRole) {
        const tag = el.tagName.toLowerCase();
        const typeAttr = el.getAttribute('type');
        if (tag === 'button') computedRole = 'button';
        else if (tag === 'a') computedRole = 'link';
        else if (tag === 'input' && typeAttr === 'checkbox') computedRole = 'checkbox';
        else if (tag === 'input' && typeAttr === 'radio') computedRole = 'radio';
        else if (tag === 'input' && (typeAttr === 'text' || typeAttr === 'email' || typeAttr === 'password' || typeAttr === 'search' || typeAttr === 'tel' || typeAttr === 'url' || !typeAttr)) computedRole = 'textbox';
        else if (tag === 'input' && typeAttr === 'number') computedRole = 'spinbutton';
        else if (tag === 'input' && typeAttr === 'range') computedRole = 'slider';
        else if (tag === 'textarea') computedRole = 'textbox';
        else if (tag === 'select') computedRole = 'combobox';
        else if (/^h[1-6]$/.test(tag)) computedRole = 'heading';
        else if (tag === 'nav') computedRole = 'navigation';
        else if (tag === 'main') computedRole = 'main';
        else if (tag === 'form') computedRole = 'form';
        else if (tag === 'img') computedRole = 'img';
        else if (tag === 'table') computedRole = 'table';
        else computedRole = tag;
      }

      // Compute accessible name
      const ariaLabel = el.getAttribute('aria-label');
      const ariaLabelledBy = el.getAttribute('aria-labelledby');
      let name = '';
      if (ariaLabelledBy) {
        const labelEl = document.getElementById(ariaLabelledBy);
        if (labelEl) name = labelEl.textContent.trim();
      } else if (ariaLabel) {
        name = ariaLabel;
      } else if (el.tagName.toLowerCase() === 'img') {
        name = el.getAttribute('alt') || '';
      } else if (el.tagName.toLowerCase() === 'input') {
        // Check for associated label
        const id = el.getAttribute('id');
        if (id) {
          const label = document.querySelector(`label[for="${id}"]`);
          if (label) name = label.textContent.trim();
        }
        if (!name) name = el.getAttribute('placeholder') || '';
      } else {
        name = el.textContent.trim();
      }

      // Build locator -- priority: data-testid > role+name > semantic CSS > positional
      const testId = el.getAttribute('data-testid');
      let locator;
      if (testId) {
        locator = `[data-testid="${testId}"]`;
      } else if (computedRole && name) {
        locator = `role=${computedRole}[name="${name}"]`;
      } else if (el.id) {
        locator = `#${el.id}`;
      } else if (computedRole) {
        // Positional fallback: count same-role siblings
        const sameRole = results.filter(r => r.computedRole === computedRole && !r.testId);
        locator = `role=${computedRole} >> nth=${sameRole.length}`;
      } else {
        continue;
      }

      // Deduplicate
      if (seenLocators.has(locator)) continue;
      seenLocators.add(locator);

      const key = `${computedRole}::${name}`;
      results.push({ key, locator, computedRole, name, testId });
    }

    return results;
  });
}

/**
 * Build the ref map for a page.
 * Returns { [refId: string]: string } mapping ref ID to Playwright locator string.
 */
async function buildRefMap(page) {
  const elements = await queryInteractiveElements(page);
  const refs = {};
  let nextId = 1;

  for (const el of elements) {
    refs[String(nextId)] = el.locator;
    nextId++;
  }

  return refs;
}

/**
 * Annotate an accessibility tree with ref IDs.
 * Walks the tree recursively, matching nodes to the ref map by role+name.
 *
 * @param {Object} tree - Playwright accessibility snapshot tree
 * @param {Array} elements - Array from queryInteractiveElements
 * @param {Object} refsByKey - Map of "role::name" -> refId
 * @returns {Object} Annotated tree
 */
function annotateTree(node, refsByKey) {
  if (!node) return node;

  const result = { ...node };
  const role = (node.role || '').toLowerCase();
  const name = node.name || '';
  const key = `${role}::${name}`;

  if (shouldAssignRef(node) && refsByKey[key] !== undefined) {
    result.refId = refsByKey[key];
  }

  if (node.children && Array.isArray(node.children)) {
    result.children = node.children.map(child => annotateTree(child, refsByKey));
  }

  return result;
}

/**
 * Take an accessibility snapshot of the current page.
 *
 * @param {import('playwright').Page} page
 * @returns {Promise<{ tree: Object[], refs: Object, url: string, timestamp: string }>}
 */
async function accessibilitySnapshot(page) {
  // Capture the accessibility tree
  const snapshot = await page.accessibility.snapshot();

  // Query DOM for interactive elements and build ref map
  const elements = await queryInteractiveElements(page);

  const refs = {};
  const refsByKey = {};
  let nextId = 1;

  for (const el of elements) {
    const refId = nextId++;
    refs[String(refId)] = el.locator;
    const key = `${el.computedRole}::${el.name}`;
    // First occurrence wins for the key -> refId mapping
    if (refsByKey[key] === undefined) {
      refsByKey[key] = refId;
    }
  }

  // Annotate the accessibility tree with ref IDs
  const annotatedTree = snapshot ? annotateTree(snapshot, refsByKey) : null;
  const tree = annotatedTree && annotatedTree.children ? annotatedTree.children : [];

  return {
    tree,
    refs,
    url: page.url(),
    timestamp: new Date().toISOString(),
  };
}

module.exports = { accessibilitySnapshot, buildRefMap };
