'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = 'https://localhost:19450';
(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.CHROME_EXECUTABLE ? {executablePath: process.env.CHROME_EXECUTABLE} : {})});
  try {
    const context = await browser.newContext({ignoreHTTPSErrors: true, colorScheme: 'dark', locale: 'ko-KR', timezoneId: 'Asia/Seoul', viewport: {width:1168, height:748}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin + '/admin/');
    assert.equal(await page.locator('html').getAttribute('lang'), 'ko');
    await page.locator('#recovery-panel:not([hidden]) summary').click();
    await page.locator('#admin-token').fill('preview-only-key-' + '0'.repeat(32));
    await page.locator('#login-form button').click();
    await page.locator('#console:not([hidden])').waitFor();
    await page.waitForFunction(() => document.querySelector('#overview-ai').textContent === '도구 호출 성공 기록 있음');
    await page.waitForFunction(() => document.querySelector('#overview-phone').textContent === '로그인 유지 확인됨');
    await page.screenshot({path: 'docs/assets/admin-overview.png'});
    await page.getByRole('button', {name:'AI 연결', exact:true}).click();
    await page.locator('#open-ai-setup').click();
    await page.locator('#ai-finish:not([hidden])').waitFor();
    assert.match(await page.locator('#ai-finish-help').textContent(), /개인 터널/);
    for (const width of [390, 1168]) {
      await page.setViewportSize({width, height:900});
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `UI overflow at ${width}`);
    }
    await page.route('**/admin/api/connection-setup', route => route.fulfill({status:503,
      contentType:'application/json', body:JSON.stringify({detail:'Internal setup failure'})}));
    await page.locator('#ai-check').click();
    await page.getByText('요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.', {exact:true}).waitFor();
    assert(!(await page.locator('body').innerText()).includes('Internal setup failure'));
    const svgPage = await context.newPage();
    const overflow = [];
    fs.mkdirSync('artifacts/localization', {recursive:true});
    for (const file of fs.readdirSync('docs/assets').filter(file => file.endsWith('.svg'))) {
      await svgPage.goto(origin + '/preview-assets/' + file);
      const dimensions = await svgPage.locator('svg').evaluate(svg => ({width:svg.viewBox.baseVal.width, height:svg.viewBox.baseVal.height}));
      await svgPage.setViewportSize(dimensions);
      await svgPage.reload();
      await svgPage.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const outside = await svgPage.locator('svg').evaluate(svg => [...svg.querySelectorAll('text')].filter(text => {
        const box = text.getBoundingClientRect();
        return box.left < -1 || box.right > svg.getBoundingClientRect().right + 1;
      }).map(text => text.textContent));
      overflow.push(...outside.map(text => `${file}: ${text}`));
      await svgPage.screenshot({path:path.join('artifacts/localization', file + '.png')});
    }
    assert.deepEqual(overflow, []);
    assert.deepEqual(errors, []);
    console.log('PASS: Korean admin, connection guidance, mobile layout, README capture and SVG canvas bounds');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode=1;});
