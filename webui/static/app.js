'use strict';

const $ = id => document.getElementById(id);
let pairing = new URLSearchParams(location.hash.slice(1)).get('pair') || '';
let passkeyEnrollment = new URLSearchParams(location.hash.slice(1)).get('passkey-setup') || '';
if (location.hash) history.replaceState(null, '', location.pathname + location.search);
// Opening a server-issued link in this existing tab must run login initialization again.
window.addEventListener('hashchange', () => { if (location.hash) location.reload(); });
let collectionBaseline = null, lastObservation = null, mcpConnected = false;
let setupState = null, latestState = null;
let csrf = '', active = false, paused = false, fetching = false, rendering = false;
let frame = null, pointer = null, blobURL = null, busy = false, generation = 0;
let setupInitialized = false, precheckValid = false, collectionApproved = false;
let loginAlreadyApproved = false;
let loginMode = 'passkey';
const preparationAttempts = new Set();
let setupCheckedAt = 0;
const messages = {
  session_required: 'Your admin session has expired. Sign in again.',
  device_busy: 'A device operation is in progress. Try again shortly.',
  invalid_request: 'Check your input.',
  invalid_csrf: 'Reopen the admin console.',
  invalid_origin: 'Open the admin console at the same HTTPS address.',
  invalid_swipe: 'Try dragging again.',
  point_outside_screen: 'Select a point inside the screen.',
};

function feedback(message) {
  $('feedback').textContent = message;
  $('feedback').hidden = false;
  clearTimeout(feedback.timer);
  feedback.timer = setTimeout(() => { $('feedback').hidden = true; }, 6500);
}

function locked() {
  generation++;
  active = false;
  csrf = '';
  frame = pointer = null;
  busy = precheckValid = collectionApproved = setupInitialized = loginAlreadyApproved = false;
  preparationAttempts.clear();
  $('console').hidden = true;
  $('login-panel').hidden = false;
  $('logout').hidden = true;
  $('connection').textContent = 'Authentication required';
  $('screen').hidden = true;
  $('screen').removeAttribute('src');
  $('device-text').value = '';
  $('device-text').type = 'password';
  ['phone-active', 'tablet-active', 'phone-rechecked', 'show-text'].forEach(id => { $(id).checked = false; });
  if ($('install-dialog').open) $('install-dialog').close('cancel');
  if (blobURL) URL.revokeObjectURL(blobURL);
  blobURL = null;
}

async function api(path, data) {
  const response = await fetch('/admin/api/' + path, {
    method: data === undefined ? 'GET' : 'POST',
    credentials: 'same-origin', cache: 'no-store',
    headers: data === undefined ? {} : { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  if (!response.ok) {
    let reason = 'The request failed. Try again shortly.';
    try {
      const error = await response.json();
      reason = messages[error.detail] || (typeof error.detail === 'string' && error.detail.trim() ? error.detail : reason);
    } catch {}
    if (response.status === 401) locked();
    throw new Error(reason);
  }
  return response.json();
}

function unlocked(session) {
  generation++;
  csrf = session.csrf;
  active = true;
  paused = false;
  $('login-panel').hidden = true;
  $('console').hidden = false;
  $('logout').hidden = false;
  $('connection').textContent = session.expires_in > 86400
    ? `Admin · ${Math.ceil(session.expires_in / 86400)} days remaining`
    : `Admin · ${Math.ceil(session.expires_in / 60)} min remaining`;
  $('pause').textContent = 'Pause';
  $('pause').setAttribute('aria-pressed', 'false');
  $('screen-placeholder').hidden = false;
  action('setup-check');
  refreshConnections();
  refresh();
}

$('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  const token = $('admin-token').value;
  $('admin-token').value = '';
  try { unlocked(await api('login', { token })); }
  catch (error) { feedback(error.message); }
});
$('logout').addEventListener('click', async () => {
  try { await api('logout', {}); locked(); }
  catch (error) { feedback(error.message); }
});

async function refresh(force = false) {
  if (!active || fetching || pointer || busy || document.hidden || (!force && paused)) return;
  fetching = true;
  const requestedGeneration = generation;
  let pendingURL;
  try {
    const response = await fetch('/admin/api/screen', { credentials: 'same-origin', cache: 'no-store' });
    if (requestedGeneration !== generation) return;
    if (response.status === 401) { locked(); return; }
    if (response.status === 409) return;
    if (!response.ok) throw new Error('screen_unavailable');
    const next = {
      id: response.headers.get('X-Frame-Id'),
      width: Number(response.headers.get('X-Screen-Width')),
      height: Number(response.headers.get('X-Screen-Height')),
    };
    pendingURL = URL.createObjectURL(await response.blob());
    if (!active || requestedGeneration !== generation || pointer || (!force && paused)) return;
    rendering = true;
    $('screen').src = pendingURL;
    await $('screen').decode();
    if (!active || requestedGeneration !== generation) return;
    frame = next;
    if (blobURL) URL.revokeObjectURL(blobURL);
    blobURL = pendingURL;
    pendingURL = null;
    $('screen').hidden = false;
    $('screen-placeholder').hidden = true;
    $('screen-label').textContent = paused ? 'Paused' : `${next.width} × ${next.height}`;
  } catch {
    if (requestedGeneration === generation) {
      frame = null;
      $('screen-label').textContent = 'Waiting for connection';
      $('screen-placeholder').hidden = false;
      $('screen').hidden = true;
    }
  } finally {
    if (pendingURL) URL.revokeObjectURL(pendingURL);
    fetching = rendering = false;
  }
}

const localTime = value => value ? new Date(value * 1000).toLocaleString('en-US') : 'No record';
function renderSessions(s, stale) {
  const fresh = !!s && !stale;
  $('session-inspected').textContent = s
    ? `${localTime(s.checked_at)}${fresh ? ' · Checked' : ' · Check again'}`
    : 'Select “Check status” to inspect the device.';
  const screens = {
    login_required: 'Login screen', main_screen_observed: 'Signed-in screen',
    not_visible: 'KakaoTalk is not open', not_installed: 'KakaoTalk is not installed', unknown: 'Cannot determine from screen',
  };
  $('tablet-status').textContent = fresh
    ? s.device === 'offline' ? 'Disconnected' : s.device === 'booting' ? 'Booting' : screens[s.screen?.state] || 'Not checked'
    : 'Check needed';
  $('tablet-detail').textContent = s?.tablet?.confirmed_at ? `Login manually confirmed: ${localTime(s.tablet.confirmed_at)}` : '';
  const phone = s?.phone;
  const overdue = phone?.confirmed_at && Date.now() / 1000 - phone.confirmed_at > 86400;
  const phoneLabels = {
    operator_confirmed: 'Confirmed active', recheck_due: 'Recheck needed',
    reported_lost: 'Reported signed out', unknown: 'No confirmation record',
  };
  $('phone-status').textContent = phoneLabels[overdue && phone?.state === 'operator_confirmed' ? 'recheck_due' : phone?.state] || 'Not checked';
  $('phone-detail').textContent = phone?.state === 'reported_lost'
    ? `${localTime(phone.reported_at)} · Manually reported`
    : phone?.confirmed_at ? `${localTime(phone.confirmed_at)} · Manually confirmed` : 'Phone status reflects your manual confirmation.';
  $('approval-status').textContent = fresh
    ? ({ approved: 'Approved', locked: 'Awaiting confirmation', unknown: 'Unknown' }[s.collection_approval] || 'Not checked')
    : 'Check needed';
  const proof = s?.precheck;
  // Typing makes the screen snapshot stale, but the precheck retains its own
  // 30-minute deadline. The server revalidates the device and app on approval.
  precheckValid = proof?.state === 'valid' && proof.expires_at > Date.now() / 1000;
  collectionApproved = fresh && s.collection_approval === 'approved';
  loginAlreadyApproved = s?.collection_approval === 'approved';
  $('login-check-help').textContent = loginAlreadyApproved
    ? 'Collection is already approved. Use “Check status” to see the current state.'
    : 'Use only before signing in. Sign in on the tablet within 30 minutes of a successful check.';
  $('approval-detail').textContent = precheckValid
    ? `Confirm both sessions by ${localTime(proof.expires_at)}.`
    : collectionApproved ? 'Approval matches the current app and device.'
    : fresh ? 'Check login options and confirm both sessions.' : '';
  $('setup-summary').textContent = collectionApproved ? 'Confirmed' : precheckValid ? 'Options checked' : '';
  if (fresh && !setupInitialized) {
    $('login-setup').open = s.collection_approval === 'locked';
    setupInitialized = true;
  }
}

function updateControls() {
  document.querySelectorAll('[data-action], [data-key], #install, #send-text').forEach(button => { button.disabled = busy; });
  $('login-check').disabled = busy || loginAlreadyApproved;
  $('confirm').disabled = busy || !precheckValid || !$('phone-active').checked || !$('tablet-active').checked;
  $('phone-recheck').disabled = busy || !collectionApproved || !$('phone-rechecked').checked;
}

async function updateState() {
  if (!active || document.hidden) return;
  const requestedGeneration = generation;
  try {
    const state = await api('state');
    if (!active || requestedGeneration !== generation) return;
    if (latestState?.job.state === 'running' && state.job.state !== 'running') {
      setupCheckedAt = Date.now();
    }
    latestState = state;
    setupState = state.setup;
    lastObservation = state.collector.last_observation_received_at || null;
    renderSetup();
    if (collectionBaseline !== null && lastObservation && Date.parse(lastObservation) > collectionBaseline) {
      $('test-result').textContent = 'A new message row reached the collector. Check it in ChatGPT to confirm the content.';
      collectionBaseline = null;
    }
    busy = state.job.state === 'running';
    $('job').hidden = !state.job.message;
    $('job').textContent = state.job.message;
    $('job').dataset.state = state.job.state;
    const loginJob = ['login-check', 'confirm-secondary'].includes(state.job.action);
    $('login-check-result').hidden = !loginJob || !state.job.message;
    $('login-check-result').textContent = loginJob ? state.job.message : '';
    $('login-check-result').dataset.state = state.job.state;
    $('login-check').textContent = busy && state.job.action === 'login-check' ? 'Checking…' : 'Check login options';
    const collector = state.collector.state;
    $('collector-status').dataset.state = collector;
    $('collector-status').textContent = collector === 'collecting_partial' ? 'Collecting messages'
      : collector === 'unavailable' ? 'Waiting for collection server' : 'Check collection status';
    $('collector-status').title = 'Collects messages received on the tablet. This does not restore the entire chat history.';
    renderSessions(state.sessions, state.sessions_stale);
    updateControls();
    // Decide only after busy/session state is updated. Mark the action before
    // starting it, since action() itself refreshes state.
    const prepare = nextPreparation(state, preparationAttempts);
    if (prepare && !busy) {
      preparationAttempts.add(prepare);
      void action(prepare);
    } else if (!busy && state.job.state !== 'failed' && !state.setup?.enrolled
        && Date.now() - setupCheckedAt > 10000) {
      // Detect store installation finishing without a manual refresh, including
      // while Android transitions from booting to ready.
      setupCheckedAt = Date.now();
      void action('setup-poll');
    }
  } catch {
    if (active && requestedGeneration === generation) {
      $('collector-status').textContent = 'Could not retrieve status';
      $('collector-status').dataset.state = 'unavailable';
      renderSessions(null, true);
      updateControls();
    }
  }
}

async function action(name, extra = {}) {
  if (!active || busy) return;
  if (['setup-check', 'setup-poll'].includes(name)) setupCheckedAt = Date.now();
  busy = true;
  updateControls();
  if (name === 'login-check') {
    $('login-check').textContent = 'Checking…';
    $('login-check-result').textContent = 'Checking tablet settings and login options.';
    $('login-check-result').dataset.state = 'running';
    $('login-check-result').hidden = false;
  }
  try { await api('action', { name, ...extra }); await updateState(); }
  catch (error) {
    busy = false;
    $('login-check').textContent = 'Check login options';
    if (name === 'login-check') {
      $('login-check-result').textContent = error.message;
      $('login-check-result').dataset.state = 'failed';
    }
    updateControls();
    feedback(error.message);
  }
}

document.querySelectorAll('[data-action]').forEach(button => {
  button.addEventListener('click', () => action(button.dataset.action));
});
$('install').addEventListener('click', () => {
  if (active && !busy) { $('install-dialog').returnValue = ''; $('install-dialog').showModal(); }
});
$('install-dialog').addEventListener('close', () => {
  if ($('install-dialog').returnValue === 'install') action('configure');
});
['phone-active', 'tablet-active', 'phone-rechecked'].forEach(id => $(id).addEventListener('change', updateControls));
$('confirm').addEventListener('click', () => {
  action('confirm-secondary', { phone_active: $('phone-active').checked, tablet_active: $('tablet-active').checked });
  $('phone-active').checked = $('tablet-active').checked = false;
  updateControls();
});
$('phone-recheck').addEventListener('click', () => {
  action('phone-active', { phone_active: $('phone-rechecked').checked });
  $('phone-rechecked').checked = false;
  updateControls();
});
$('show-text').addEventListener('change', () => { $('device-text').type = $('show-text').checked ? 'text' : 'password'; });
$('text-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!active || busy) return;
  const text = $('device-text').value;
  $('device-text').value = '';
  try { await api('text', { text }); feedback('Text inserted. Check the tablet screen.'); await refresh(true); }
  catch (error) { feedback(error.message); }
});
document.querySelectorAll('[data-key]').forEach(button => button.addEventListener('click', async () => {
  if (!active || busy) return;
  try { await api('key', { name: button.dataset.key }); await refresh(true); }
  catch (error) { feedback(error.message); }
}));

function coordinates(event, f) {
  // The image has no border or padding; its visible rectangle is the input surface.
  const r = $('screen').getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(f.width - 1, Math.floor((event.clientX - r.left) / r.width * f.width))),
    y: Math.max(0, Math.min(f.height - 1, Math.floor((event.clientY - r.top) / r.height * f.height))),
  };
}
$('screen').addEventListener('pointerdown', event => {
  if (!frame || rendering || paused || busy || event.button !== 0) return;
  pointer = { ...coordinates(event, frame), frame: { ...frame }, time: performance.now(), id: event.pointerId };
  $('screen').setPointerCapture(event.pointerId);
  event.preventDefault();
});
$('screen').addEventListener('pointerup', async event => {
  const start = pointer;
  pointer = null;
  if (!active || !start || start.id !== event.pointerId) return;
  const end = coordinates(event, start.frame);
  const data = { frame: start.frame.id, x: start.x, y: start.y };
  if (Math.hypot(end.x - start.x, end.y - start.y) > 12 || performance.now() - start.time > 550) {
    Object.assign(data, { end_x: end.x, end_y: end.y, duration: Math.max(100, Math.min(2000, Math.round(performance.now() - start.time))) });
  }
  try { await api('pointer', data); await refresh(true); }
  catch (error) { feedback(error.message); }
});
$('screen').addEventListener('pointercancel', () => { pointer = null; });
$('refresh').addEventListener('click', () => refresh(true));
$('pause').addEventListener('click', () => {
  paused = !paused;
  frame = null;
  $('pause').textContent = paused ? 'Resume' : 'Pause';
  $('pause').setAttribute('aria-pressed', String(paused));
  $('screen-label').textContent = paused ? 'Paused' : 'Connecting to screen';
  if (!paused) refresh();
});
document.addEventListener('visibilitychange', () => {
  frame = null;
  if (!document.hidden) { refresh(); updateState(); }
});
setInterval(() => refresh(), 1200);
setInterval(updateState, 3000);
setInterval(() => { if (active && !document.hidden) refreshConnections(); }, 15000);
initLogin();


async function initLogin() {
  try {
    const info = await api('auth-info');
    loginMode = info.mode;
    $('passkey-panel').hidden = loginMode !== 'passkey' || !!pairing;
    $('passkeys-panel').hidden = loginMode !== 'passkey';
    if (loginMode === 'passkey') {
      $('passkey-submit').textContent = passkeyEnrollment ? 'Create a passkey' : 'Sign in with a passkey';
      $('passkey-submit').disabled = !info.configured || (!info.owner_registered && !passkeyEnrollment);
      $('passkey-remember').closest('label').hidden = !!passkeyEnrollment;
      $('passkey-help').textContent = passkeyEnrollment
        ? 'Save a passkey to your device or password manager. This setup link works once.'
        : !info.owner_registered ? 'Open the setup link issued by ./bridge passkey-login on your server.'
        : 'Use your device, phone or security key.';
    }
    $('recovery-panel').hidden = loginMode !== 'local';
    $('pair-help').hidden = loginMode !== 'local' && !pairing;
    $('owner-form').hidden = loginMode !== 'local' || !info.configured;
    if (pairing) {
      const passwordNeeded = loginMode === 'local' && !info.configured;
      $('owner-form').hidden = false;
      $('pair-help').textContent = passwordNeeded ? 'Choose an admin password (at least 12 characters).' : 'This server-issued recovery link works once. Access lasts 30 minutes.';
      $('owner-submit').textContent = passwordNeeded ? 'Create password and continue' : 'Recover access';
      $('owner-password').hidden = $('password-label').hidden = !passwordNeeded;
      $('owner-password').required = passwordNeeded;
      $('owner-password').minLength = passwordNeeded ? 12 : 0;
      $('owner-password').autocomplete = passwordNeeded ? 'new-password' : 'current-password';
      $('remember').closest('label').hidden = loginMode !== 'local';
      locked();
    } else if (passkeyEnrollment && loginMode === 'passkey') {
      locked();
    } else {
      $('pair-help').textContent = 'Use your admin password or run ./bridge admin --recovery to pair a browser.';
      try { unlocked(await api('session')); } catch { locked(); }
    }
  } catch (error) { feedback(error.message); }
}
$('passkey-form').addEventListener('submit', async event => {
  event.preventDefault();
  $('passkey-submit').disabled = true;
  $('passkey-status').textContent = 'Confirm with your device…';
  try {
    let session;
    if (passkeyEnrollment) {
      const start = await api('passkeys/register-options', {enrollment: passkeyEnrollment, label: 'My passkey'});
      const credential = await BridgePasskey.run(start.options, true);
      session = await api('passkeys/register-verify', {flow: start.flow, credential});
      passkeyEnrollment = '';
      $('passkeys-panel').open = true;
      $('passkey-submit').textContent = 'Sign in with a passkey';
      $('passkey-remember').closest('label').hidden = false;
    } else session = await authenticatePasskey('login');
    $('passkey-status').textContent = '';
    unlocked(session);
    await refreshPasskeys();
  } catch (error) { $('passkey-status').textContent = error.message; }
  finally { $('passkey-submit').disabled = false; }
});
async function authenticatePasskey(purpose) {
  const start = await api('passkeys/login-options', {purpose, remember: $('passkey-remember').checked});
  const credential = await BridgePasskey.run(start.options);
  return api('passkeys/login-verify', {flow: start.flow, credential, purpose, context: start.context});
}
$('passkey-add').addEventListener('click', async () => {
  $('passkey-add').disabled = true;
  try {
    const {proof} = await authenticatePasskey('manage');
    const start = await api('passkeys/register-options', {proof, label: $('passkey-label').value.trim() || 'Backup passkey'});
    const credential = await BridgePasskey.run(start.options, true);
    const session = await api('passkeys/register-verify', {flow: start.flow, credential});
    csrf = session.csrf;
    await refreshPasskeys();
    feedback('Backup passkey added.');
  } catch (error) { feedback(error.message); }
  finally { $('passkey-add').disabled = false; }
});
$('passkeys-panel').addEventListener('toggle', refreshPasskeys);
async function refreshPasskeys() {
  if (!active || loginMode !== 'passkey' || !$('passkeys-panel').open) return;
  try {
    const {items} = await api('passkeys/credentials', {});
    $('passkeys-list').replaceChildren(...items.map(row => {
      const card = document.createElement('div'); card.className = 'connection-card';
      card.append(paragraph(row.label), paragraph(`Added ${localTime(row.created)} · Last used ${localTime(row.last_used)}`));
      if (items.length > 1) card.append(button('Remove', async () => {
        const {proof} = await authenticatePasskey('manage');
        await api('passkeys/remove', {proof, identity: row.id});
        locked();
        feedback('Passkey removed. Sign in again with a remaining passkey.');
      }));
      return card;
    }));
  } catch (error) { feedback(error.message); }
}
$('owner-form').addEventListener('submit', async event => {
  event.preventDefault();
  const password = $('owner-password').value;
  $('owner-password').value = '';
  try {
    const session = await api('owner-login', { password, pair: pairing, remember: $('remember').checked });
    pairing = '';
    $('owner-form').hidden = loginMode !== 'local';
    $('pair-help').hidden = loginMode !== 'local';
    $('owner-password').hidden = $('password-label').hidden = false;
    $('owner-password').required = true;
    $('owner-password').autocomplete = 'current-password';
    $('owner-submit').textContent = 'Sign in';
    $('pair-help').textContent = 'Use your admin password or run ./bridge admin --recovery to pair a browser.';
    unlocked(session);
  } catch (error) { feedback(error.message); }
});

function renderSetup() {
  const s = setupState;
  const session = latestState?.sessions;
  const ready = !!s && !['offline', 'booting'].includes(s.state);
  const enrolled = !!s?.enrolled;
  const approved = session?.collection_approval === 'approved';
  const collecting = latestState?.collector.state === 'collecting_partial';
  const steps = [enrolled, approved, collecting && mcpConnected];
  const labels = ['Prepare', 'Sign in', 'Connect AI'];
  $('setup-progress').replaceChildren(...labels.map((label, i) => {
    const item = document.createElement('li'); item.textContent = label;
    item.dataset.complete = String(steps[i]); return item;
  }));
  let next = ['Server readiness is being checked.', '', ''];
  if (s && !ready) next = ['Your private device is starting. This page will continue automatically.', '', ''];
  else if (ready && !s.kakao_installed) next = s.aurora_installed
    ? ['Choose anonymous sign-in in the store and install KakaoTalk by Kakao Corp. Setup continues automatically.', 'open-store', 'Open store']
    : ['Preparing your device and the app store…', 'prepare', 'Retry preparation'];
  else if (ready && !enrolled) next = ['Finishing preparation for KakaoTalk sign-in…', 'configure', 'Retry preparation'];
  else if (enrolled && !approved) next = ['Open KakaoTalk. Check “Use with other devices” before login, then confirm both phone and tablet sessions below.', 'open-kakao', 'Open KakaoTalk'];
  else if (approved && !collecting) next = ['Both sessions were confirmed. Waiting for the collector; refresh status if needed.', 'session-check', 'Check status'];
  else if (collecting && !mcpConnected) next = ['Collection is running. Send a test message, then connect ChatGPT under Connections.', '', ''];
  else if (collecting && mcpConnected) next = ['Setup complete. Phone session health still requires your manual confirmation.', '', ''];
  if (latestState?.job.state === 'failed') next[0] = latestState.job.message || 'Preparation stopped. Check the result below and retry.';
  $('setup-next').textContent = next[0];
  $('setup-next-button').hidden = !next[1];
  $('setup-next-button').textContent = next[2];
  $('setup-next-button').onclick = () => action(next[1]);
  $('setup-next-button').disabled = latestState?.job.state === 'running';
}

function paragraph(text) { const p = document.createElement('p'); p.textContent = text; return p; }
function button(text, fn) {
  const b = document.createElement('button'); b.textContent = text;
  b.addEventListener('click', async () => {
    b.disabled = true;
    try { await fn(); } catch (error) { feedback(error.message); }
    finally { b.disabled = false; }
  }); return b;
}
let connectionsLoading = false, connectionSignature = '';
async function refreshConnections() {
  if (!active || connectionsLoading) return;
  connectionsLoading = true;
  try {
    const data = await api('connections');
    if (!active) return;
    mcpConnected = data.grants.length > 0 || !!data.tunnel?.approved;
    $('mcp-address').textContent = data.resource;
    $('connection-help').textContent = data.approval_mode === 'passkey'
      ? 'Add this MCP address in ChatGPT and choose OAuth. Confirm with your passkey, review access, then allow the connection. You can disconnect it here.'
      : data.approval_mode === 'key'
        ? 'This server uses legacy connection-key approval. Enter its connection key in the connecting browser.'
        : 'Add this MCP address in ChatGPT and choose OAuth. Approve only the request whose code matches that browser.';
    if (data.tunnel?.configured && data.resource.includes('.invalid/')) {
      $('mcp-address').textContent = 'Public OAuth connection is not configured.';
      $('connection-help').textContent = 'Connect your personal OpenAI tunnel below. Public HTTPS connections remain available when configured.';
    }
    $('pending-count').textContent = data.pending.length ? `(${data.pending.length} pending)` : '';
    renderSetup();
    const signature = JSON.stringify(data);
    if (signature === connectionSignature) return;
    connectionSignature = signature;
    const tunnel = data.tunnel;
    const tunnelPanel = $('tunnel-connection');
    tunnelPanel.hidden = !tunnel?.configured;
    if (tunnel?.configured) {
      const card = document.createElement('div'); card.className = 'connection-card';
      card.append(paragraph('OpenAI personal tunnel'), paragraph(tunnel.tunnel_id));
      card.append(paragraph(tunnel.approved
        ? `${tunnel.expires === null ? 'Access allowed with no automatic expiration.' : `Access allowed until ${localTime(tunnel.expires)}.`} In ChatGPT, choose Tunnel and select this ID. No OAuth login is needed.`
        : 'Allow this personal tunnel to read collected messages and manage event subscriptions you request. Use a tunnel accessible only to you. Approval has no automatic expiration; you can disconnect it here.'));
      if (tunnel.approved && tunnel.expires !== null) {
        card.append(button('Remove approval expiration', async () => {
          await api('tunnel/decision', {tunnel_id: tunnel.tunnel_id, approve: true});
          connectionSignature = ''; await refreshConnections();
        }));
      }
      card.append(button(tunnel.approved ? 'Disconnect tunnel' : 'Allow personal tunnel', async () => {
        await api('tunnel/decision', {tunnel_id: tunnel.tunnel_id, approve: !tunnel.approved});
        connectionSignature = ''; await refreshConnections();
      }));
      tunnelPanel.replaceChildren(card);
    }
    const nodes = data.pending.map(row => {
      const card = document.createElement('div'); card.className = 'connection-card';
      card.append(paragraph(`${row.client_name} · ${row.client_id}`), paragraph(`Callback: ${row.redirect_origin}`), paragraph(`Permissions: ${row.scope}`));
      const label = document.createElement('label'); label.textContent = 'Enter the 8-character code shown in the connecting browser';
      const input = document.createElement('input'); input.maxLength = 8; input.autocomplete = 'off'; input.spellcheck = false;
      label.append(input); card.append(label);
      card.append(button('Approve connection', async () => {
        const code = input.value.trim().toUpperCase();
        if (!/^[A-F0-9]{8}$/.test(code)) throw new Error('Enter the code from the connecting browser.');
        await api(`connections/${row.id}/decide`, {code, approve: true}); await refreshConnections();
      }), button('Decline', async () => {
        await api(`connections/${row.id}/decide`, {code: row.code, approve: false}); await refreshConnections();
      }));
      card.append(paragraph('Client names are self-reported. Check the callback and code before approving.'));
      return card;
    });
    for (const row of data.grants) {
      const card = document.createElement('div'); card.className = 'connection-card';
      card.append(paragraph(row.client_id), paragraph(`${row.scope} · Expires ${localTime(row.expires)}`), button('Disconnect', async () => {
        await api(`connections/${row.id}/revoke`, {}); await refreshConnections();
      })); nodes.push(card);
    }
    $('connections-list').replaceChildren(...(nodes.length ? nodes : [paragraph('No pending or connected clients.')]));
  } catch { if (active) $('mcp-address').textContent = 'Connection service unavailable. Run ./bridge connect --url https://your-address.'; }
  finally { connectionsLoading = false; }
}
$('refresh-connections').addEventListener('click', refreshConnections);
$('connections-panel').addEventListener('toggle', () => { if ($('connections-panel').open) refreshConnections(); });
$('browsers-panel').addEventListener('toggle', refreshBrowsers);
async function refreshBrowsers() {
  if (!active || !$('browsers-panel').open) return;
  try {
    const data = await api('browsers');
    $('browsers-list').replaceChildren(...data.items.map(row => {
      const card = document.createElement('div'); card.className = 'connection-card';
      card.append(paragraph(row.current ? 'This browser' : row.label), paragraph(`Expires ${localTime(row.expires)}`), button('Sign out', async () => {
        await api(`browsers/${row.id}/revoke`, {});
        if (row.current) locked(); else await refreshBrowsers();
      })); return card;
    }));
  } catch (error) { feedback(error.message); }
}
$('test-collection').addEventListener('click', async () => {
  try {
    await updateState();
    collectionBaseline = Math.max((latestState?.checked_at || Date.now() / 1000) * 1000, lastObservation ? Date.parse(lastObservation) : 0);
    $('test-result').textContent = 'Now send yourself a message from your phone. Waiting for a new collected row…';
  } catch (error) { feedback(error.message); }
});
