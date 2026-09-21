'use strict';

/**
 * Assertion action handler.
 *
 * executeAssert(page, step, options, refMap) -> { success: true } or throws.
 *
 * Supports checks: visible, hidden, text_contains, text_equals, count_gte, count_eq.
 *
 * A passing assertion also reports whether it could have failed. Three of
 * those checks are satisfied by a page holding no matching element at all,
 * so the match count is read at the one place that already resolved the
 * locator and travels with the result as `vacuous_absence`.
 */

const {
  isDocumentWideTarget,
  waitForVisibleText,
  truncateForError,
  resolveTarget,
} = require('./target-helpers');

// Default timeout for scenario assertion actions.
const DEFAULT_TIMEOUT_MS = 5000;

/**
 * Whether a check is satisfied by a page that holds no matching element.
 *
 * Playwright reports a detached locator as hidden, and a locator matching
 * nothing counts zero, so `hidden`, `count_eq` of 0 and `count_gte` of 0 all
 * pass on a screen the assertion never observed. The rest of the vocabulary
 * -- `visible`, `text_contains`, `text_equals`, and `count_gte` of one or
 * more -- fails on a zero-match locator, so none of it can pass vacuously.
 *
 * @param {Object} step
 * @returns {boolean}
 */
function isAbsenceShaped(step) {
  switch (step.check) {
    case 'hidden':
      return true;
    case 'count_eq':
      return Number(step.expected) === 0;
    case 'count_gte':
      return Number(step.min_count) === 0;
    default:
      return false;
  }
}

/**
 * The result of an assertion that passed, saying whether it proved anything.
 *
 * An absence-shaped assertion that resolved against zero elements observed
 * nothing: there was no element on the page for it to be wrong about, so it
 * could not have failed. Recording that here, beside the count the check was
 * decided on, is what lets every later reader tell it apart from a real
 * observation of an element that was present and hidden.
 *
 * @param {Object} step
 * @param {number} matched - Elements the step's locator resolved to
 * @returns {{ success: true, vacuous_absence?: Object }}
 */
function assertionResult(step, matched) {
  if (matched > 0 || !isAbsenceShaped(step)) {
    return { success: true };
  }
  return {
    success: true,
    vacuous_absence: {
      check: step.check,
      target: String(step.target || ''),
      matched_elements: matched,
    },
  };
}

/**
 * Poll a locator count until *predicate* holds or *timeout* expires.
 *
 * `locator.count()` is a single snapshot. Waiting assertions such as
 * `visible` already honour `timeout_ms`; count checks have to poll the
 * same budget or a late-painted page fails as `found 0`.
 *
 * @param {import('playwright').Locator} locator
 * @param {import('playwright').Page} page
 * @param {number} timeout
 * @param {(count: number) => boolean} predicate
 * @returns {Promise<number>}
 */
async function waitForCount(locator, page, timeout, predicate) {
  const deadline = Date.now() + timeout;
  const pollInterval = 100;
  let count = await locator.count();
  while (!predicate(count)) {
    const remaining = deadline - Date.now();
    if (remaining <= 0) {
      return count;
    }
    await page.waitForTimeout(Math.min(pollInterval, remaining));
    count = await locator.count();
  }
  return count;
}

/**
 * Execute an assert action.
 * Supports checks: visible, hidden, text_contains, text_equals, count_gte, count_eq
 */
async function executeAssert(page, step, options, refMap) {
  const locator = resolveTarget(page, step.target, refMap);
  const check = step.check;
  const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;

  switch (check) {
    case 'visible':
      await locator.waitFor({ state: 'visible', timeout });
      return { success: true };

    case 'hidden': {
      await locator.waitFor({ state: 'hidden', timeout });
      return assertionResult(step, await locator.count());
    }

    case 'text_contains': {
      // For document-wide targets (body, html), use visible-text path that
      // excludes script/style content and waits for the expected hydrated
      // text. Non-body locators use normal textContent() semantics.
      const expected = String(step.expected).toLowerCase();
      const text = isDocumentWideTarget(step.target)
        ? await waitForVisibleText(
          page,
          timeout,
          value => value.toLowerCase().includes(expected)
        )
        : await locator.textContent({ timeout });
      if (text === null || !text.toLowerCase().includes(expected)) {
        throw new Error(
          `Expected text to contain "${step.expected}", got "${truncateForError(text)}"`
        );
      }
      return { success: true };
    }

    case 'text_equals': {
      // Same visible-text path for document-wide targets, but wait for the
      // exact visible text instead of returning on the first shell.
      const expected = String(step.expected).trim();
      const text = isDocumentWideTarget(step.target)
        ? await waitForVisibleText(
          page,
          timeout,
          value => value.trim() === expected
        )
        : await locator.textContent({ timeout });
      if (text === null || text.trim() !== expected) {
        throw new Error(
          `Expected text to equal "${step.expected}", got "${truncateForError(text)}"`
        );
      }
      return { success: true };
    }

    case 'count_gte': {
      const count = await waitForCount(
        locator,
        page,
        timeout,
        (matched) => matched >= step.min_count
      );
      if (count < step.min_count) {
        throw new Error(
          `Expected at least ${step.min_count} elements, found ${count}`
        );
      }
      return assertionResult(step, count);
    }

    case 'count_eq': {
      const count = await waitForCount(
        locator,
        page,
        timeout,
        (matched) => matched === step.expected
      );
      if (count !== step.expected) {
        throw new Error(
          `Expected exactly ${step.expected} elements, found ${count}`
        );
      }
      return assertionResult(step, count);
    }

    default:
      throw new Error(`Unknown assert check: ${check}`);
  }
}

module.exports = { executeAssert };
