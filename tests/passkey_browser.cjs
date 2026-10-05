'use strict';
// Native browser WebAuthn + a virtual CTAP2 authenticator, with real server verification.
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const local = process.env.LOCAL_ADMIN === '1';
const admin = (local ? 'http' : 'https') + '://localhost:19446', publicOrigin = 'https://localhost:19447';
const redirect = 'https://chatgpt.com/connector_platform_oauth_redirect';
(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.CHROME_EXECUTABLE ? {executablePath: process.env.CHROME_EXECUTABLE} : {})});
  try {
    const context = await browser.newContext({ignoreHTTPSErrors: true});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const cdp = await context.newCDPSession(page);
    await cdp.send('WebAuthn.enable');
    const {authenticatorId} = await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {
      protocol: 'ctap2', transport: 'internal', hasResidentKey: true,
      hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true}});
    await page.goto(admin + '/admin/');
    await page.locator('#passkey-panel:not([hidden])').waitFor();
    assert(await page.locator('#passkey-submit').isDisabled());
    const enrollment = await context.request.post(admin + '/test/enroll', {headers: {Origin: admin}});
    const link = (await enrollment.json()).url;
    await page.goto(link);
    await page.getByRole('button', {name: 'Create a passkey', exact: true}).click();
    await page.locator('#console:not([hidden])').waitFor();
    assert(!page.url().includes('#'));
    await page.screenshot({path: 'artifacts/passkey-admin.png', fullPage: true});
    await page.locator('#logout').click();
    await page.locator('#passkey-remember').check();
    await page.locator('#passkey-submit').click();
    await page.locator('#console:not([hidden])').waitFor();
    assert((await context.cookies(admin + '/admin/')).some(c => c.name === (local ? 'kakao-admin-local-19446' : '__Secure-kakao-admin-v2') && c.path === '/admin' && c.httpOnly && c.secure === !local && c.expires > Date.now()/1000 + 6*86400));
    assert(!(await context.cookies(publicOrigin + '/authorize')).some(c => c.name === '__Secure-kakao-admin-v2'));
    await page.reload();
    await page.locator('#console:not([hidden])').waitFor();

    if (local) {
      assert(await page.evaluate(() => window.isSecureContext));
      const denied = await context.request.post(admin + '/admin/api/logout', {headers:{Origin:'http://localhost:19448'}});
      assert.equal(denied.status(), 403);
      await page.locator('#logout').click();
      await page.locator('#passkey-panel:not([hidden])').waitFor();
      assert(!(await context.cookies(admin + '/admin/')).some(c => c.name === 'kakao-admin-local-19446'));
      assert.deepEqual(errors, []);
      console.log('PASS: localhost HTTP native WebAuthn registration, login, persistent session, reload, Origin rejection and logout');
      return;
    }
    cdp.on('Fetch.requestPaused', async event => {
      await cdp.send('Fetch.fulfillRequest', {requestId: event.requestId, responseCode: 200,
        responseHeaders: [{name:'Content-Type', value:'text/html'}],
        body: Buffer.from('<h1>Synthetic ChatGPT callback</h1>').toString('base64')});
    });
    await cdp.send('Fetch.enable', {patterns: [{urlPattern: redirect + '*', requestStage:'Request'}]});
    await page.goto(publicOrigin + '/test/start');
    const clientId = new URL(page.url()).searchParams.get('client_id');
    await page.getByRole('button', {name:'Continue with a passkey'}).click();
    await page.getByRole('heading', {name:'Allow connection?'}).waitFor();
    await page.screenshot({path:'artifacts/passkey-consent.png', fullPage:true});
    await page.getByRole('button', {name:'Allow connection', exact:true}).click();
    await page.getByRole('heading', {name:'Synthetic ChatGPT callback'}).waitFor();
    const query = new URL(page.url()).searchParams;
    assert.equal(query.get('state'), 'passkey-test');
    assert.equal(query.get('iss'), publicOrigin);
    const form = {grant_type:'authorization_code', code:query.get('code'), client_id:clientId,
      redirect_uri:redirect, resource:publicOrigin+'/mcp', code_verifier:'v'.repeat(64)};
    const token = await context.request.post(publicOrigin+'/token', {form});
    assert.equal(token.status(), 200);
    const tokens = await token.json();
    const tools = await context.request.post(publicOrigin+'/mcp', {headers:{Authorization:'Bearer '+tokens.access_token},
      data:{jsonrpc:'2.0', id:1, method:'tools/list'}});
    assert.equal(tools.status(), 200);
    assert.equal((await context.request.post(publicOrigin+'/token', {form})).status(), 400);
    const refreshed = await context.request.post(publicOrigin+'/token', {form:{grant_type:'refresh_token', client_id:clientId,
      resource:publicOrigin+'/mcp', refresh_token:tokens.refresh_token}});
    assert.equal(refreshed.status(),200);
    await page.goto(publicOrigin + '/test/start');
    await page.getByRole('button', {name:'Continue with a passkey'}).click();
    await page.getByRole('heading', {name:'Allow connection?'}).waitFor();
    await page.getByRole('button', {name:'Cancel', exact:true}).click();
    await page.getByRole('heading', {name:'Synthetic ChatGPT callback'}).waitFor();
    assert.equal(new URL(page.url()).searchParams.get('error'),'access_denied');
    const credentials = await cdp.send('WebAuthn.getCredentials', {authenticatorId});
    assert.equal(credentials.credentials.length,1);
    assert(credentials.credentials[0].signCount >= 3);
    assert.deepEqual(errors, []);
    console.log('PASS: native passkey registration, login, seven-day session, reload, same passkey on both ports, explicit OAuth consent, PKCE, refresh, MCP tools, denial and code replay rejection');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode=1;});
