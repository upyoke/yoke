'use strict';

/**
 * Assertion action handler.
 *
 * executeAssert(page, step, options, refMap) -> { success: true } or throws.
 *
 * Supports checks: visible, hidden, text_contains, text_equals, count_gte, count_eq.
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
      return { success: true };
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
      const count = await locator.count();
      if (count < step.min_count) {
        throw new Error(
          `Expected at least ${step.min_count} elements, found ${count}`
        );
      }
      return { success: true };
    }

    case 'count_eq': {
      const count = await locator.count();
      if (count !== step.expected) {
        throw new Error(
          `Expected exactly ${step.expected} elements, found ${count}`
        );
      }
      return { success: true };
    }

    default:
      throw new Error(`Unknown assert check: ${check}`);
  }
}

module.exports = { executeAssert };
