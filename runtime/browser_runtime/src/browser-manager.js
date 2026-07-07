'use strict';

/**
 * Browser manager -- wraps a single Playwright browser instance.
 *
 * Exports: createBrowserManager(options) -> { getBrowser, getPage, newPage, closeBrowser, isConnected }
 */

const { chromium } = require('playwright');

/**
 * @param {Object} options
 * @param {string} [options.browserType='chromium'] - Browser type (only chromium supported today)
 * @param {boolean} [options.headless=true] - Run headless
 * @returns {Object} Browser manager interface
 */
function createBrowserManager(options = {}) {
  const browserType = options.browserType || 'chromium';
  const headless = options.headless !== false;

  let browser = null;
  let context = null;
  let currentPage = null;

  async function launch() {
    if (browserType !== 'chromium') {
      throw new Error(`Unsupported browser type: ${browserType}. Only chromium is supported.`);
    }
    browser = await chromium.launch({ headless });
    context = await browser.newContext();
    return browser;
  }

  function getBrowser() {
    return browser;
  }

  /**
   * Get the current page, creating one if needed. Navigates to url if provided.
   */
  async function getPage(url) {
    if (!context) {
      throw new Error('Browser not launched. Call launch() first.');
    }
    if (!currentPage || currentPage.isClosed()) {
      currentPage = await context.newPage();
    }
    if (url) {
      await currentPage.goto(url, { waitUntil: 'domcontentloaded' });
    }
    return currentPage;
  }

  /**
   * Always create a new page. Navigates to url if provided.
   */
  async function newPage(url) {
    if (!context) {
      throw new Error('Browser not launched. Call launch() first.');
    }
    currentPage = await context.newPage();
    if (url) {
      await currentPage.goto(url, { waitUntil: 'domcontentloaded' });
    }
    return currentPage;
  }

  async function closeBrowser() {
    if (browser) {
      try {
        await browser.close();
      } catch (_) {
        // Browser may already be disconnected
      }
      browser = null;
      context = null;
      currentPage = null;
    }
  }

  function isConnected() {
    return browser !== null && browser.isConnected();
  }

  return {
    launch,
    getBrowser,
    getPage,
    newPage,
    closeBrowser,
    isConnected,
  };
}

module.exports = { createBrowserManager };
