'use strict';

/**
 * Capture action handler: screenshot.
 *
 * executeScreenshot(page, step, options) -> { success: true, artifacts?: string[] }
 */

const path = require('path');

function screenshotBasename(step) {
  const timestamp = Date.now();
  if (typeof step.label !== 'string') {
    return `screenshot-${timestamp}.png`;
  }
  const slug = step.label
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
  if (!slug) {
    return `screenshot-${timestamp}.png`;
  }
  return `screenshot-${slug}-${timestamp}.png`;
}

/**
 * Execute a screenshot action.
 * Captures a screenshot when capture is true, returns the path in artifacts.
 * `label` names the file so the capture matches the step's own account.
 */
async function executeScreenshot(page, step, options) {
  if (!step.capture) {
    return { success: true };
  }

  const outputDir = options.outputDir || '/tmp';
  const screenshotPath = path.join(outputDir, screenshotBasename(step));
  await page.screenshot({ path: screenshotPath, fullPage: !!step.fullPage });
  return { success: true, artifacts: [screenshotPath] };
}

module.exports = { executeScreenshot };
