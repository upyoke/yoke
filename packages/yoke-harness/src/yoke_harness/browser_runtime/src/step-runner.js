'use strict';

/**
 * Scenario step runner.
 *
 * Maps scenario step schema objects to Playwright API calls.
 *
 * Exports:
 *   executeStep(page, step, options) -> { success, duration_ms, viewport, url, error?, artifacts? }
 *   resolveUrl(route, baseUrl) -> string
 *
 * Supported actions: navigate, click, fill_form, wait_for, delay, assert,
 *   screenshot, scroll, hover, type, select
 */

const { buildRefMap } = require('./snapshot');
const nav = require('./step-actions/navigation');
const inter = require('./step-actions/interaction');
const assertions = require('./step-actions/assertion');
const capture = require('./step-actions/capture');

// resolveUrl is owned by the navigation sibling and re-exported here so the
// public module surface (executeStep, resolveUrl) stays stable.
const { resolveUrl } = nav;

/**
 * What the page actually was when the step finished.
 *
 * Every step reports this, pass or fail, because it is the only first-hand
 * account of the screen the step ran against: the route a case asked for and
 * the width it asked for are requests, and evidence that records the request
 * can never disagree with it. Reading either can throw on a page that closed
 * under the step, which is itself part of the account rather than a second
 * failure.
 *
 * @param {import('playwright').Page} page
 * @returns {{ viewport: ?{width: number, height: number}, url: string }}
 */
function observedState(page) {
  let viewport = null;
  let url = '';
  try {
    viewport = page.viewportSize();
  } catch (_) {
    viewport = null;
  }
  try {
    url = page.url();
  } catch (_) {
    url = '';
  }
  return { viewport, url };
}

/**
 * Execute a single browser scenario step.
 *
 * @param {import('playwright').Page} page - Playwright Page instance
 * @param {Object} step - Step schema object
 * @param {string} step.route - URL route (relative or absolute)
 * @param {string} step.action - Action to execute
 * @param {string} [step.target] - Target element selector or ref
 * @param {Object} [step.fields] - Fields for fill_form
 * @param {string} [step.check] - Assert check type
 * @param {*} [step.expected] - Expected value for asserts
 * @param {number} [step.min_count] - Minimum count for count_gte
 * @param {number} [step.timeout_ms] - Per-step timeout
 * @param {boolean} [step.capture] - Whether to capture screenshot
 * @param {{width: number, height: number}} [step.viewport] - Resize before the
 *   step, and leave it resized for the steps that follow
 * @param {Object} options
 * @param {string} options.baseUrl - Base URL to prepend to relative routes
 * @param {number} [options.timeout] - Default timeout
 * @param {string} [options.outputDir] - Output directory for artifacts
 * @returns {Promise<{ success: boolean, duration_ms: number, error?: string, artifacts?: string[] }>}
 */
async function executeStep(page, step, options) {
  const startTime = Date.now();

  if (!step || !step.action) {
    return {
      success: false,
      duration_ms: Date.now() - startTime,
      error: 'Step must have an action field',
    };
  }

  if (!options || !options.baseUrl) {
    return {
      success: false,
      duration_ms: Date.now() - startTime,
      error: 'options.baseUrl is required',
    };
  }

  try {
    // Validate that scenarios use the current step schema.
    const legacyFields = [];
    if (step.url !== undefined) {
      legacyFields.push('"url" (use "route" instead)');
    }
    if (step.selector !== undefined) {
      legacyFields.push('"selector" (use "target" instead)');
    }
    if (step.action === 'wait') {
      legacyFields.push('"action":"wait" (use "delay" or "wait_for" instead)');
    }
    if (legacyFields.length > 0) {
      throw new Error(
        `Stale browser scenario schema detected. Legacy fields: ${legacyFields.join(', ')}. ` +
        'Update stored scenarios to use canonical vocabulary (route, target, delay/wait_for).'
      );
    }

    // A step may state the width it is about. Responsive behaviour is only
    // provable by resizing the real viewport — constraining an element inside
    // a wide window proves the element, not the product — and the width has
    // to be set before the step runs so the assertions and the capture that
    // follow both see it. It stays set, so a case reads as a walk down the
    // widths rather than a width repeated on every step.
    if (step.viewport) {
      const { width, height } = step.viewport;
      if (!Number.isFinite(width) || !Number.isFinite(height)) {
        throw new Error(
          'step.viewport needs numeric width and height, '
          + `got ${JSON.stringify(step.viewport)}`
        );
      }
      await page.setViewportSize({ width, height });
    }

    // Build ref map for ref-based target resolution
    let refMap = null;
    if (step.target && step.target.startsWith('ref:')) {
      refMap = await buildRefMap(page);
    }
    // Also build ref map for fill_form if any field uses ref:
    if (step.action === 'fill_form' && step.fields) {
      const hasRefField = Object.keys(step.fields).some(k => k.startsWith('ref:'));
      if (hasRefField && !refMap) {
        refMap = await buildRefMap(page);
      }
    }

    let result;
    switch (step.action) {
      case 'navigate':
        result = await nav.executeNavigate(page, step, options);
        break;
      case 'click':
        result = await inter.executeClick(page, step, options, refMap);
        break;
      case 'fill_form':
        result = await inter.executeFillForm(page, step, options, refMap);
        break;
      case 'wait_for':
        result = await inter.executeWaitFor(page, step, options, refMap);
        break;
      case 'delay':
        result = await inter.executeDelay(page, step);
        break;
      case 'assert':
        result = await assertions.executeAssert(page, step, options, refMap);
        break;
      case 'screenshot':
        result = await capture.executeScreenshot(page, step, options);
        break;
      case 'scroll':
        result = await nav.executeScroll(page, step, options, refMap);
        break;
      case 'hover':
        result = await nav.executeHover(page, step, options, refMap);
        break;
      case 'type':
        result = await inter.executeType(page, step, options, refMap);
        break;
      case 'select':
        result = await inter.executeSelect(page, step, options, refMap);
        break;
      default:
        throw new Error(`Unknown action: ${step.action}`);
    }

    const duration_ms = Date.now() - startTime;
    return {
      success: true,
      duration_ms,
      ...observedState(page),
      ...(result.artifacts ? { artifacts: result.artifacts } : {}),
    };
  } catch (err) {
    const duration_ms = Date.now() - startTime;
    return {
      success: false,
      duration_ms,
      ...observedState(page),
      error: err.message || String(err),
    };
  }
}

module.exports = { executeStep, resolveUrl };
