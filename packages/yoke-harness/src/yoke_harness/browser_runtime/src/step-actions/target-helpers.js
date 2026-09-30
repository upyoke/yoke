'use strict';

/**
 * Target resolution and visible-text helpers shared by the step-runner
 * dispatcher and the per-action sibling modules.
 *
 * Exports (CommonJS):
 *   resolveTarget(page, target, refMap) -> Locator
 *   resolvePresenceTarget(page, target, refMap) -> Locator
 *   isDocumentWideTarget(target) -> boolean
 *   getVisibleText(page) -> Promise<string>
 *   waitForVisibleText(page, timeout, matches) -> Promise<string>
 *   truncateForError(text) -> string
 *   MAX_ERROR_TEXT_LENGTH (number)
 */

// Maximum characters of actual text to include in assertion error messages.
const MAX_ERROR_TEXT_LENGTH = 200;

/**
 * Check whether a target selector refers to the document body or an equivalent
 * document-wide scope. These targets are susceptible to script/style tag
 * contamination via textContent() on SSR/RSC pages.
 *
 * @param {string} target
 * @returns {boolean}
 */
function isDocumentWideTarget(target) {
  if (!target) return false;
  const normalized = target.trim().toLowerCase();
  return normalized === 'body' || normalized === 'html' || normalized === 'html body';
}

/**
 * Read visible (rendered) text from the document body, excluding script and
 * style tag content. This mirrors what a user can actually see on the page.
 *
 * @param {import('playwright').Page} page
 * @returns {Promise<string>}
 */
async function getVisibleText(page) {
  return page.evaluate(() => {
    // innerText reflects only rendered/visible text — excludes <script>,
    // <style>, and hidden elements. This avoids RSC flight data payloads.
    return document.body ? document.body.innerText : '';
  });
}

/**
 * Poll visible document text until the current assertion's match condition is
 * satisfied or the timeout budget is exhausted. This keeps body/document-wide
 * assertions from failing early on pages that render an initial shell like
 * "Loading..." before hydration produces the expected text.
 *
 * @param {import('playwright').Page} page
 * @param {number} timeout - Maximum wait time in milliseconds
 * @param {(text: string) => boolean} matches
 * @returns {Promise<string>} The matching visible text, or the last observed text on timeout
 */
async function waitForVisibleText(page, timeout, matches) {
  const deadline = Date.now() + timeout;
  const pollInterval = 100;
  let text = '';

  while (true) {
    text = await getVisibleText(page);

    if (matches(text)) {
      return text;
    }

    const remaining = deadline - Date.now();
    if (remaining <= 0) {
      return text || '';
    }

    await page.waitForTimeout(Math.min(pollInterval, remaining));
  }
}

/**
 * Truncate text for error messages to avoid dumping large RSC payloads.
 *
 * @param {string|null} text
 * @returns {string}
 */
function truncateForError(text) {
  if (text === null) return 'null';
  if (text.length <= MAX_ERROR_TEXT_LENGTH) return text;
  return text.substring(0, MAX_ERROR_TEXT_LENGTH) + `... (${text.length} chars total)`;
}

/**
 * Resolve a target to a Playwright locator.
 *
 * If the target looks like a ref (e.g. "ref:7"), look it up in the ref map.
 * Otherwise, treat it as a CSS selector.
 *
 * @param {import('playwright').Page} page
 * @param {string} target
 * @param {Object|null} refMap - Optional ref map from buildRefMap
 * @returns {import('playwright').Locator}
 */
function resolveTarget(page, target, refMap) {
  if (!target) {
    throw new Error('No target specified for action');
  }

  // Check for ref-based target (e.g. "ref:7")
  const refMatch = target.match(/^ref:(\d+)$/);
  if (refMatch && refMap) {
    const refId = refMatch[1];
    const locatorStr = refMap[refId];
    if (!locatorStr) {
      throw new Error(`Ref ${refId} not found in ref map`);
    }
    return page.locator(locatorStr);
  }

  // CSS or role-based selector
  return page.locator(target);
}

/**
 * Resolve a target for a question about presence rather than identity.
 *
 * Playwright's waiting operations are strict: a locator resolving to more
 * than one element refuses instead of answering. That is the right rule for
 * acting on an element or reading its text -- an ambiguous click or an
 * ambiguous `text_equals` is a case that does not know what it is about --
 * but it is the wrong rule for asking whether a screen shows something. A
 * selector naming a repeated component (`.shipping-run-card` on a page
 * holding a dozen of them) is a correct way to ask "did the cards render",
 * and under strict mode it failed for matching too well.
 *
 * Presence questions therefore ask the first match. "At least one" is what
 * the question means, and it is what a count check would have to be written
 * as anyway.
 *
 * @param {import('playwright').Page} page
 * @param {string} target
 * @param {Object|null} refMap
 * @returns {import('playwright').Locator}
 */
function resolvePresenceTarget(page, target, refMap) {
  return resolveTarget(page, target, refMap).first();
}

module.exports = {
  MAX_ERROR_TEXT_LENGTH,
  isDocumentWideTarget,
  getVisibleText,
  waitForVisibleText,
  truncateForError,
  resolveTarget,
  resolvePresenceTarget,
};
