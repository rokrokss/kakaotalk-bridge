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
    await page.getByRole('button', {name: '패스키 만들기', exact: true}).click();
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
    // Synthetic tunnel responses exercise the send toggle without touching an account.
    let allowSend = false;
    const decisions = [];
    await page.route(admin + '/admin/api/connections', route => route.fulfill({json: {
      pending: [], grants: [], resource: publicOrigin + '/mcp', approval_mode: 'passkey',
      tunnel: {configured:true, tunnel_id:'tunnel_'+'a'.repeat(32), approved:true,
        expires:null, last_tool_at:null, allow_send:allowSend}
    }}));
    await page.route(admin + '/admin/api/tunnel/decision', route => {
      const body = route.request().postDataJSON();
      assert.equal(body.approve, true);
      assert.equal(typeof body.allow_send, 'boolean');
      assert(route.request().headers()['x-csrf-token']);
      allowSend = body.allow_send; decisions.push(allowSend);
      return route.fulfill({json:{ok:true}});
    });
    await page.getByRole('button', {name:'AI 연결', exact:true}).click();
    await page.getByRole('button', {name:'메시지 전송 허용', exact:true}).click();
    await page.getByRole('button', {name:'메시지 전송 권한 해제', exact:true}).waitFor();
    await page.screenshot({path:'artifacts/send-permission.png', fullPage:true});
    await page.getByRole('button', {name:'메시지 전송 권한 해제', exact:true}).click();
    await page.getByRole('button', {name:'메시지 전송 허용', exact:true}).waitFor();
    assert.deepEqual(decisions, [true, false]);
    cdp.on('Fetch.requestPaused', async event => {
      await cdp.send('Fetch.fulfillRequest', {requestId: event.requestId, responseCode: 200,
        responseHeaders: [{name:'Content-Type', value:'text/html'}],
        body: Buffer.from('<h1>Synthetic ChatGPT callback</h1>').toString('base64')});
    });
    await cdp.send('Fetch.enable', {patterns: [{urlPattern: redirect + '*', requestStage:'Request'}]});
    await page.goto(publicOrigin + '/test/start');
    const clientId = new URL(page.url()).searchParams.get('client_id');
    await page.getByRole('button', {name:'패스키로 계속'}).click();
    await page.getByRole('heading', {name:'연결을 허용할까요?'}).waitFor();
    assert(await page.getByText('내 카카오톡 계정으로 기존 대화방에 텍스트 메시지 전송', {exact:true}).isVisible());
    await page.screenshot({path:'artifacts/passkey-consent.png', fullPage:true});
    await page.getByRole('button', {name:'연결 허용', exact:true}).click();
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
    const sendTool = (await tools.json()).result.tools.find(tool => tool.name === 'send_message');
    assert.equal(sendTool.annotations.readOnlyHint, false);
    assert.equal(sendTool.annotations.openWorldHint, true);
    assert.deepEqual(sendTool.securitySchemes[0].scopes, ['kakao.send']);
    assert.equal((await context.request.post(publicOrigin+'/token', {form})).status(), 400);
    const refreshed = await context.request.post(publicOrigin+'/token', {form:{grant_type:'refresh_token', client_id:clientId,
      resource:publicOrigin+'/mcp', refresh_token:tokens.refresh_token}});
    assert.equal(refreshed.status(),200);
    await page.goto(publicOrigin + '/test/start');
    await page.getByRole('button', {name:'패스키로 계속'}).click();
    await page.getByRole('heading', {name:'연결을 허용할까요?'}).waitFor();
    await page.getByRole('button', {name:'취소', exact:true}).click();
    await page.getByRole('heading', {name:'Synthetic ChatGPT callback'}).waitFor();
    assert.equal(new URL(page.url()).searchParams.get('error'),'access_denied');
    const credentials = await cdp.send('WebAuthn.getCredentials', {authenticatorId});
    assert.equal(credentials.credentials.length,1);
    assert(credentials.credentials[0].signCount >= 3);
    assert.deepEqual(errors, []);
    console.log('PASS: native passkey registration, login, tunnel send permission toggle, explicit OAuth send consent, PKCE, refresh, MCP tools, denial and code replay rejection');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode=1;});
