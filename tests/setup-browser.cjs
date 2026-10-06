'use strict';
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = 'https://localhost:19449';
(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.CHROME_EXECUTABLE ? {executablePath: process.env.CHROME_EXECUTABLE} : {})});
  try {
    const context = await browser.newContext({ignoreHTTPSErrors: true});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin + '/admin/');
    await page.locator('#recovery-panel:not([hidden]) summary').click();
    await page.locator('#admin-token').fill('preview-only-key-' + '0'.repeat(32));
    await page.locator('#login-form button').click();
    await page.locator('#console:not([hidden])').waitFor();
    await page.waitForFunction(() => document.querySelector('#setup-next').textContent.includes('익명 로그인'), null, {timeout: 20000});
    assert.deepEqual(await (await context.request.get(origin + '/test/calls')).json(), ['prepare']);
    await context.request.post(origin + '/test/install-kakao', {headers: {Origin: origin}});
    await page.waitForFunction(() => document.querySelector('#job').textContent === '카카오톡을 열었습니다.', null, {timeout: 25000});
    assert.deepEqual(await (await context.request.get(origin + '/test/calls')).json(), ['prepare', 'configure', 'open-kakao']);
    assert(await page.locator('#confirm').isDisabled());
    assert(!(await page.locator('#phone-active').isChecked()));
    await page.screenshot({path: 'artifacts/setup-onboarding.png', fullPage: true});
    await page.reload();
    await page.locator('#console:not([hidden])').waitFor();
    await page.waitForFunction(() => document.querySelector('#setup-next').textContent.includes('선택해 로그인하세요'), null, {timeout: 25000});
    // Signing in on the tablet is detected without a button; collection still waits for the phone check.
    await context.request.post(origin + '/test/sign-in', {headers: {Origin: origin}});
    await page.waitForFunction(() => document.querySelector('#setup-next').textContent.includes('태블릿 로그인이 확인되었습니다'), null, {timeout: 40000});
    assert(await page.locator('#confirm').isDisabled());
    await page.evaluate(() => {
      for (let node = document.getElementById('login-setup'); node; node = node.parentElement) if (node.tagName === 'DETAILS') node.open = true;
    });
    await page.locator('#phone-active').check();
    assert(await page.locator('#confirm').isEnabled());
    const calls = await (await context.request.get(origin + '/test/calls')).json();
    assert.deepEqual(calls.filter(name => name !== 'session-check'), ['prepare', 'configure', 'open-kakao']);
    assert.deepEqual(errors, []);
    console.log('PASS: automatic preparation, store-install detection, component setup, KakaoTalk opening, automatic login detection, phone confirmation boundary and reload without reinstallation');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
