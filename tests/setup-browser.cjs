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
    const step = name => page.waitForFunction(step => document.querySelector('#console').dataset.step === step, name, {timeout: 40000});
    const calls = async () => (await (await context.request.get(origin + '/test/calls')).json()).filter(name => name !== 'session-check');
    const called = async name => { for (let i = 0; i < 60 && !(await calls()).includes(name); i++) await page.waitForTimeout(500); };
    await page.goto(origin + '/admin/');
    await page.locator('#recovery-panel:not([hidden]) summary').click();
    await page.locator('#admin-token').fill('preview-only-key-' + '0'.repeat(32));
    await page.locator('#login-form button').click();
    await page.locator('#console:not([hidden])').waitFor();
    await step('store-login');
    assert.deepEqual(await calls(), ['prepare']);
    // Setup shows only the current step beside the tablet; the dashboard waits for collection.
    assert(await page.locator('[data-setup="store-login"]').isVisible());
    assert(await page.locator('.device-panel').isVisible());
    for (const hidden of ['.overview', '#text-panel', '[data-setup="login"]']) assert(!(await page.locator(hidden).isVisible()), hidden);
    await context.request.post(origin + '/test/aurora-login', {headers: {Origin: origin}});
    await step('install');
    // Signing in to Aurora opens the KakaoTalk listing without another button.
    await called('open-store');
    assert.deepEqual(await calls(), ['prepare', 'open-store']);
    await context.request.post(origin + '/test/install-kakao', {headers: {Origin: origin}});
    await called('open-kakao');
    assert.deepEqual(await calls(), ['prepare', 'open-store', 'configure', 'open-kakao']);
    await page.screenshot({path: 'artifacts/setup-onboarding.png', fullPage: true});
    await page.reload();
    await page.locator('#console:not([hidden])').waitFor();
    await step('login');
    assert(await page.locator('#text-panel').isVisible());
    await page.waitForFunction(() => document.querySelector('#login-option-status').dataset.state === 'ok', null, {timeout: 25000});
    // Signing in on the tablet is detected without a button; collection still waits for the phone check.
    await context.request.post(origin + '/test/sign-in', {headers: {Origin: origin}});
    await step('phone');
    assert(!(await page.locator('#text-panel').isVisible()));
    assert(await page.locator('#confirm').isDisabled());
    await page.locator('#phone-active').check();
    assert(await page.locator('#confirm').isEnabled());
    assert.deepEqual(await calls(), ['prepare', 'open-store', 'configure', 'open-kakao']);
    await page.locator('#confirm').click();
    await step('done');
    assert(await page.locator('.overview').isVisible());
    assert(!(await page.locator('#setup-card').isVisible()));
    assert.deepEqual(await calls(), ['prepare', 'open-store', 'configure', 'open-kakao', 'approve']);
    assert.deepEqual(errors, []);
    console.log('PASS: automatic preparation, Aurora login detection, store listing, install detection, component setup, KakaoTalk opening, login detection, phone confirmation boundary, reload without reinstallation and dashboard after approval');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
