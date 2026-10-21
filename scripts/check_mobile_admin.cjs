// Optional browser regression check: node scripts/check_mobile_admin.cjs
// Requires Playwright and Chromium. All HTTP/WebAuthn responses are TEST doubles.
// This does not prove physical passkey compatibility or production deployment.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
    args: ['--no-sandbox'],
  });
  try {
    for (const width of [320, 390, 768]) {
      const page = await browser.newPage({ viewport: { width, height: 844 } });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      let rejectOptions = false;
      let rejectLogout = false;
      let approvals = 0;
      await page.addInitScript(() => {
        Object.defineProperty(navigator.credentials, 'get', { value: async () => ({
          id: 'test-id', rawId: new Uint8Array([1]).buffer, type: 'public-key',
          response: { clientDataJSON: new Uint8Array([1]).buffer,
            authenticatorData: new Uint8Array([1]).buffer,
            signature: new Uint8Array([1]).buffer, userHandle: null },
          getClientExtensionResults: () => ({}),
        }) });
      });
      await page.route('https://mymoneyguard.tail56fef5.ts.net/**', async route => {
        const pathname = new URL(route.request().url()).pathname;
        if (pathname.endsWith('/passkey/login')) {
          return route.fulfill({ contentType: 'text/html', body: fs.readFileSync(
            path.join(__dirname, '../src/gaon/runtime/passkey_login.html'), 'utf8') });
        }
        let status = 200;
        let body = {};
        if (pathname.endsWith('/begin')) body = { challenge: 'AQ', allowCredentials: [] };
        else if (pathname.endsWith('/login/finish')) body = { authenticated: true, csrf_token: 'test-csrf' };
        else if (pathname.endsWith('/strategy/options')) {
          status = rejectOptions ? 403 : 200;
          body = { families: [{ family_id: 'long-family-'.repeat(15), versions: [
            { id: 'candidate-version', status: 'apply_ready' },
            { id: 'active-version', status: 'active' },
          ] }], research_candidates: [], crypto_forward_verification: { configured: false } };
        } else if (pathname.endsWith('/logout')) {
          status = rejectLogout ? 503 : 200;
          body = { logged_out: !rejectLogout };
        } else if (pathname.endsWith('/approval/finish')) { approvals++; body = { activated: 'candidate-version' }; }
        else throw Error('Unexpected test request: ' + pathname);
        await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
      });
      await page.goto('https://mymoneyguard.tail56fef5.ts.net/gaon/admin/passkey/login');
      assert(await page.locator('#approve').isDisabled());
      await page.locator('#login').click();
      await page.waitForFunction(() => document.querySelector('#login-state').textContent.includes('로그인 성공'));
      await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
      await page.locator('#family').selectOption({ index: 1 });
      await page.locator('#version').selectOption('candidate-version');
      assert.equal(await page.locator('#version option[value="active-version"]').count(), 0);
      assert.equal(approvals, 0, 'Login and selection must never automatically activate a strategy');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow at ${width}px`);
      rejectOptions = true;
      await page.locator('#refresh').click();
      await page.waitForFunction(() => document.querySelector('#login-state').textContent.includes('세션 만료'));
      assert(await page.locator('#approve').isDisabled());
      assert.equal(await page.locator('#family option').count(), 1);
      rejectOptions = false;
      await page.locator('#login').click();
      await page.waitForFunction(() => !document.querySelector('#logout').disabled);
      rejectLogout = true;
      await page.locator('#logout').click();
      await page.waitForFunction(() => document.querySelector('#login-state').textContent.includes('확인 실패'));
      assert(!(await page.locator('#status').textContent()).includes('로그아웃 완료'));
      assert(await page.locator('#approve').isDisabled());
      assert.deepEqual(errors, []);
      console.log(`PASS ${width}px: layout, no automatic activation, expired session, failed logout`);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
