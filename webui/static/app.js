'use strict';

const $ = id => document.getElementById(id);
let pairing = new URLSearchParams(location.hash.slice(1)).get('pair') || '';
let passkeyEnrollment = new URLSearchParams(location.hash.slice(1)).get('passkey-setup') || '';
if (location.hash) history.replaceState(null, '', location.pathname + location.search);
// Opening a server-issued link in this existing tab must run login initialization again.
window.addEventListener('hashchange', () => { if (location.hash) location.reload(); });
let collectionBaseline = null, lastObservation = null;
let overviewInitialized = false;
let setupState = null, latestState = null;
let csrf = '', active = false, paused = false, fetching = false, rendering = false;
let frame = null, pointer = null, blobURL = null, busy = false, generation = 0;
let setupInitialized = false, tabletLoggedIn = false, collectionApproved = false;
let loginAlreadyApproved = false;
let loginMode = 'passkey';
const preparationAttempts = new Set();
let setupCheckedAt = 0, lastInteraction = 0;
let inspectionRetries = 0, inspectionTimer = null;
const messages = {
  session_required: '관리자 로그인이 만료되었습니다. 다시 로그인하세요.',
  device_busy: '기기 작업이 진행 중입니다. 잠시 후 다시 시도하세요.',
  invalid_request: '입력 내용을 확인하세요.',
  invalid_csrf: '관리 화면을 다시 여세요.',
  invalid_origin: '같은 HTTPS 주소에서 관리 화면을 여세요.',
  invalid_swipe: '다시 드래그해 보세요.',
  point_outside_screen: '화면 안의 지점을 선택하세요.',
};

function feedback(message) {
  $('feedback').textContent = message;
  $('feedback').hidden = false;
  clearTimeout(feedback.timer);
  feedback.timer = setTimeout(() => { $('feedback').hidden = true; }, 6500);
}

function locked() {
  clearTimeout(inspectionTimer);
  generation++;
  active = false;
  csrf = '';
  frame = pointer = null;
  busy = tabletLoggedIn = collectionApproved = setupInitialized = loginAlreadyApproved = false;
  overviewInitialized = false;
  preparationAttempts.clear();
  $('console').hidden = true;
  $('login-panel').hidden = false;
  $('logout').hidden = true;
  $('connection').textContent = '로그인이 필요합니다';
  $('screen').hidden = true;
  $('screen').removeAttribute('src');
  $('device-text').value = '';
  $('device-text').type = 'password';
  connectionSetup.lock();
  $('event-conversations').replaceChildren();
  $('event-search').value = '';
  $('event-list-status').textContent = '';
  $('more-events').hidden = true;
  ['phone-active', 'phone-rechecked', 'show-text'].forEach(id => { $(id).checked = false; });
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
  }).catch(() => { throw new Error('서버에 연결하지 못했습니다. 네트워크를 확인하고 다시 시도하세요.'); });
  if (!response.ok) {
    let reason = '요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.';
    try {
      const error = await response.json();
      reason = messages[error.detail] || (typeof error.detail === 'string' && /[가-힣]/.test(error.detail) ? error.detail : reason);
    } catch {}
    if (response.status === 401) locked();
    const error = new Error(reason); error.status = response.status; throw error;
  }
  return response.json().catch(() => { throw new Error('서버 응답을 확인하지 못했습니다. 잠시 후 다시 시도하세요.'); });
}

function unlocked(session) {
  inspectionRetries = 0; clearTimeout(inspectionTimer);
  generation++;
  csrf = session.csrf;
  active = true;
  paused = false;
  $('login-panel').hidden = true;
  $('console').hidden = false;
  $('logout').hidden = false;
  $('connection').textContent = session.expires_in > 86400
    ? `관리 · ${Math.ceil(session.expires_in / 86400)}일 남음`
    : `관리 · ${Math.ceil(session.expires_in / 60)}분 남음`;
  $('pause').textContent = '일시 정지';
  $('pause').setAttribute('aria-pressed', 'false');
  $('screen-placeholder').hidden = false;
  action('setup-check');
  refreshConnections();
  connectionSetup.refresh();
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
  if (!active || fetching || pointer || busy || document.hidden || (!force && (paused || !$('tablet-workspace').open))) return;
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
    $('screen-label').textContent = paused ? '일시 정지됨' : `${next.width} × ${next.height}`;
  } catch {
    if (requestedGeneration === generation) {
      frame = null;
      $('screen-label').textContent = '연결 대기 중';
      $('screen-placeholder').hidden = false;
      $('screen').hidden = true;
    }
  } finally {
    if (pendingURL) URL.revokeObjectURL(pendingURL);
    fetching = rendering = false;
  }
}

const localTime = value => value ? new Date(value * 1000).toLocaleString('ko-KR') : '기록 없음';
function openPanel(id) {
  const panel = $(id);
  for (let parent = panel.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true;
  panel.open = true; panel.scrollIntoView({behavior:'smooth', block:'start'});
}
document.querySelectorAll('[data-panel]').forEach(button => button.addEventListener('click', () => openPanel(button.dataset.panel)));
$('overview-connect').addEventListener('click', () => openPanel('connections-panel'));
$('overview-phone-action').addEventListener('click', () => openPanel('phone-panel'));
$('tablet-workspace').addEventListener('toggle', () => { if ($('tablet-workspace').open) void refresh(); });
const approvalReasons = {
  not_enrolled: '먼저 ‘설치’에서 구성 요소를 설치하세요.',
  not_tablet: '태블릿 설정이 아니어서 보조 기기 로그인을 사용할 수 없습니다.',
  display_too_small: '화면 크기가 작아 보조 기기 로그인을 사용할 수 없습니다.',
  device_state_unavailable: '태블릿 상태를 읽지 못했습니다. 다시 확인하세요.',
  kakao_login_required: '태블릿 카카오톡에 아직 로그인하지 않았습니다.',
  account_ambiguous: '로그인된 카카오톡 계정을 확인할 수 없습니다. 카카오톡을 열어 확인하세요.',
  account_changed: '승인한 계정과 다른 계정이 로그인되어 있습니다. 휴대폰을 확인하고 다시 승인하세요.',
  android_changed: 'Android가 바뀌었습니다. 두 기기의 로그인을 확인하고 다시 승인하세요.',
  phone_reported_lost: '휴대폰 로그아웃이 기록되었습니다. 두 기기를 확인하고 다시 승인하세요.',
  approval_required: '휴대폰 로그인이 유지되는지 확인하고 수집을 시작하세요.',
};

function renderSessions(s, stale) {
  const fresh = !!s && !stale;
  $('session-inspected').textContent = s
    ? `${localTime(s.checked_at)}${fresh ? ' · 확인됨' : ' · 다시 확인 필요'}`
    : '‘상태 확인’을 눌러 기기를 점검하세요.';
  const screens = {
    login_required: '로그인 화면', main_screen_observed: '로그인된 화면',
    not_visible: '카카오톡이 열려 있지 않음', not_installed: '카카오톡 미설치', unknown: '화면에서 판단할 수 없음',
  };
  const login = s?.kakao?.login;
  $('tablet-status').textContent = fresh
    ? s.device === 'offline' ? '연결 끊김' : s.device === 'booting' ? '시작 중'
      : login === 'logged_in' ? '카카오톡 로그인됨' : screens[s.screen?.state] || '미확인'
    : s ? '점검 결과 갱신 필요' : '아직 점검하지 않음';
  $('tablet-detail').textContent = s?.approved_at ? `수집 승인: ${localTime(s.approved_at)}` : '';
  const phone = s?.phone;
  const overdue = phone?.confirmed_at && Date.now() / 1000 - phone.confirmed_at > 86400;
  const phoneLabels = {
    operator_confirmed: '로그인 유지 확인됨', recheck_due: '재확인 필요',
    reported_lost: '로그아웃 신고됨', unknown: '확인 기록 없음',
  };
  $('phone-status').textContent = phoneLabels[overdue && phone?.state === 'operator_confirmed' ? 'recheck_due' : phone?.state] || '미확인';
  $('phone-detail').textContent = phone?.state === 'reported_lost'
    ? `${localTime(phone.reported_at)} · 직접 신고`
    : phone?.confirmed_at ? `${localTime(phone.confirmed_at)} · 직접 확인` : '휴대폰 상태는 직접 확인한 내용을 표시합니다.';
  $('approval-status').textContent = ({ approved: '승인됨', locked: '확인 대기 중', unknown: '알 수 없음' }[s?.collection_approval] || '미확인') + (!fresh && s ? ' · 마지막 점검 기준' : '');
  tabletLoggedIn = fresh && login === 'logged_in';
  collectionApproved = fresh && s.collection_approval === 'approved';
  loginAlreadyApproved = s?.collection_approval === 'approved';
  $('approval-detail').textContent = collectionApproved
    ? '같은 카카오톡 계정으로 로그인되어 있는 동안 승인이 유지됩니다. 카카오톡이 업데이트되어도 계속 수집합니다.'
    : fresh ? approvalReasons[s.approval_reason] || '' : s ? `마지막 점검: ${localTime(s.checked_at)}. 확인 내용을 변경하기 전에 새로고침하세요.` : '';
  const screen = s?.screen;
  $('login-option-status').textContent = !fresh ? '태블릿 화면을 확인하는 중입니다.'
    : login === 'logged_in' ? '태블릿 카카오톡에 로그인되어 있습니다.'
    : screen?.state === 'login_required' ? (screen.secondary_option === 'selected'
      ? '‘다른 기기와 함께 사용’이 선택되어 있습니다. 이제 로그인하세요.'
      : '‘다른 기기와 함께 사용’이 선택되지 않았습니다. 선택한 뒤 로그인하세요.')
    : '태블릿에서 카카오톡을 열면 로그인 화면을 확인합니다.';
  $('tablet-login-status').textContent = tabletLoggedIn
    ? (loginAlreadyApproved ? '태블릿 로그인과 수집 승인이 확인되었습니다.' : '태블릿 로그인이 확인되었습니다. 휴대폰을 확인하세요.')
    : '태블릿에 로그인하면 자동으로 확인됩니다.';
  $('setup-summary').textContent = loginAlreadyApproved ? '승인됨' : tabletLoggedIn ? '로그인됨' : '';
  $('overview-phone').textContent = $('phone-status').textContent;
  $('overview-phone-detail').textContent = phone?.confirmed_at ? `마지막 직접 확인: ${localTime(phone.confirmed_at)}` : '태블릿 로그인 후 휴대폰에서 직접 확인하세요.';
  if (fresh && !setupInitialized) {
    $('login-setup').open = s.collection_approval === 'locked';
    setupInitialized = true;
  }
}

function updateControls() {
  document.querySelectorAll('[data-action], [data-key], #install, #send-text').forEach(button => { button.disabled = busy; });
  $('confirm').disabled = busy || !tabletLoggedIn || !$('phone-active').checked;
  $('phone-recheck').disabled = busy || !collectionApproved || !$('phone-rechecked').checked;
  $('phone-recheck-help').textContent = busy ? '진행 중인 태블릿 작업이 끝날 때까지 기다리세요.' : !loginAlreadyApproved ? '먼저 카카오톡 로그인과 수집 승인을 완료하세요.' : !collectionApproved ? '휴대폰 확인을 갱신하기 전에 태블릿 점검을 새로고침하세요.' : !$('phone-rechecked').checked ? '휴대폰을 확인한 뒤 위의 확인 항목을 선택하세요.' : '';
  $('phone-inspect').hidden = !loginAlreadyApproved || collectionApproved;
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
      $('test-result').textContent = '새 메시지가 수집되었습니다. ChatGPT에서 내용을 확인하세요.';
      collectionBaseline = null;
    }
    busy = state.job.state === 'running';
    $('job').hidden = !state.job.message;
    $('job').textContent = state.job.message;
    $('job').dataset.state = state.job.state;
    const loginJob = state.job.action === 'approve';
    $('login-result').hidden = !loginJob || !state.job.message;
    $('login-result').textContent = loginJob ? state.job.message : '';
    $('login-result').dataset.state = state.job.state;
    const collector = state.collector.state;
    $('collector-status').dataset.state = collector;
    $('collector-status').textContent = collector === 'collecting_partial' ? '메시지 수집 중'
      : collector === 'unavailable' ? '수집 서버 대기 중' : '수집 상태 확인 필요';
    $('collector-status').title = '태블릿에서 수신한 메시지를 수집합니다. 전체 대화 기록을 복원하지는 않습니다.';
    $('overview-collection').textContent = $('collector-status').textContent;
    $('overview-last').textContent = lastObservation ? `마지막 수집: ${new Date(lastObservation).toLocaleString('ko-KR')} · 일부 기록만 수집` : '아직 수집된 메시지가 없습니다.';
    renderSessions(state.sessions, state.sessions_stale);
    updateControls();
    // Decide only after busy/session state is updated. Mark the action before
    // starting it, since action() itself refreshes state.
    const prepare = nextPreparation(state, preparationAttempts);
    if (prepare && !busy) {
      preparationAttempts.add(prepare);
      void action(prepare);
    } else if (!busy && loginCheckDue(state, Date.now(), lastInteraction)) {
      void action('session-check');
    } else if (!busy && state.job.state !== 'failed' && !state.setup?.enrolled
        && Date.now() - setupCheckedAt > 10000) {
      // Detect store installation finishing without a manual refresh, including
      // while Android transitions from booting to ready.
      setupCheckedAt = Date.now();
      void action('setup-poll');
    }
  } catch {
    if (active && requestedGeneration === generation) {
      $('collector-status').textContent = '상태를 가져오지 못했습니다';
      $('collector-status').dataset.state = 'unavailable';
      renderSessions(null, true);
      updateControls();
    }
  }
}

async function action(name, extra = {}) {
  if (!active || busy) return;
  if (['open-kakao', 'open-store', 'prepare', 'configure'].includes(name)) openPanel('tablet-workspace');
  if (['setup-check', 'setup-poll'].includes(name)) setupCheckedAt = Date.now();
  busy = true;
  updateControls();
  try { await api('action', { name, ...extra }); await updateState(); }
  catch (error) {
    busy = false;
    updateControls();
    if (name === 'setup-check' && error.status === 409 && inspectionRetries++ < 3) {
      const retryGeneration = generation;
      inspectionTimer = setTimeout(() => { if (active && generation === retryGeneration) void action('setup-check'); }, 1500);
      return;
    }
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
['phone-active', 'phone-rechecked'].forEach(id => $(id).addEventListener('change', updateControls));
$('confirm').addEventListener('click', () => {
  action('approve', { phone_active: $('phone-active').checked });
  $('phone-active').checked = false;
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
  lastInteraction = Date.now();
  try { await api('text', { text }); feedback('텍스트를 입력했습니다. 태블릿 화면을 확인하세요.'); await refresh(true); }
  catch (error) { feedback(error.message); }
});
document.querySelectorAll('[data-key]').forEach(button => button.addEventListener('click', async () => {
  if (!active || busy) return;
  lastInteraction = Date.now();
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
  lastInteraction = Date.now();
  try { await api('pointer', data); await refresh(true); }
  catch (error) { feedback(error.message); }
});
$('screen').addEventListener('pointercancel', () => { pointer = null; });
$('refresh').addEventListener('click', () => refresh(true));
$('pause').addEventListener('click', () => {
  paused = !paused;
  frame = null;
  $('pause').textContent = paused ? '재개' : '일시 정지';
  $('pause').setAttribute('aria-pressed', String(paused));
  $('screen-label').textContent = paused ? '일시 정지됨' : '화면 연결 중';
  if (!paused) refresh();
});
document.addEventListener('visibilitychange', () => {
  frame = null;
  if (!document.hidden) { refresh(); updateState(); }
});
const connectionSetup = BridgeConnectionSetup({api, isActive: () => active, onChange: refreshConnections, feedback});
$('open-ai-setup').addEventListener('click', () => connectionSetup.open());
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
      $('passkey-submit').textContent = passkeyEnrollment ? '패스키 만들기' : '패스키로 로그인';
      $('passkey-submit').disabled = !info.configured || (!info.owner_registered && !passkeyEnrollment);
      $('passkey-remember').closest('label').hidden = !!passkeyEnrollment;
      $('passkey-help').textContent = passkeyEnrollment
        ? '기기나 비밀번호 관리자에 패스키를 저장하세요. 이 설정 링크는 한 번만 사용할 수 있습니다.'
        : !info.owner_registered ? '서버에서 ./bridge passkey-login으로 발급한 설정 링크를 여세요.'
        : '기기, 휴대폰 또는 보안 키로 인증하세요.';
    }
    $('recovery-panel').hidden = loginMode !== 'local';
    $('pair-help').hidden = loginMode !== 'local' && !pairing;
    $('owner-form').hidden = loginMode !== 'local' || !info.configured;
    if (pairing) {
      const passwordNeeded = loginMode === 'local' && !info.configured;
      $('owner-form').hidden = false;
      $('pair-help').textContent = passwordNeeded ? '관리자 비밀번호를 정하세요(12자 이상).' : '서버에서 발급한 일회용 복구 링크입니다. 접근 권한은 30분 동안 유효합니다.';
      $('owner-submit').textContent = passwordNeeded ? '비밀번호 생성 후 계속' : '접근 권한 복구';
      $('owner-password').hidden = $('password-label').hidden = !passwordNeeded;
      $('owner-password').required = passwordNeeded;
      $('owner-password').minLength = passwordNeeded ? 12 : 0;
      $('owner-password').autocomplete = passwordNeeded ? 'new-password' : 'current-password';
      $('remember').closest('label').hidden = loginMode !== 'local';
      locked();
    } else if (passkeyEnrollment && loginMode === 'passkey') {
      locked();
    } else {
      $('pair-help').textContent = '관리자 비밀번호를 사용하거나 ./bridge admin --recovery로 브라우저를 연결하세요.';
      try { unlocked(await api('session')); } catch { locked(); }
    }
  } catch (error) { feedback(error.message); }
}
$('passkey-form').addEventListener('submit', async event => {
  event.preventDefault();
  $('passkey-submit').disabled = true;
  $('passkey-status').textContent = '기기에서 인증하세요…';
  try {
    let session;
    if (passkeyEnrollment) {
      const start = await api('passkeys/register-options', {enrollment: passkeyEnrollment, label: '내 패스키'});
      const credential = await BridgePasskey.run(start.options, true);
      session = await api('passkeys/register-verify', {flow: start.flow, credential});
      passkeyEnrollment = '';
      $('passkeys-panel').open = true;
      $('passkey-submit').textContent = '패스키로 로그인';
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
    const start = await api('passkeys/register-options', {proof, label: $('passkey-label').value.trim() || '백업 패스키'});
    const credential = await BridgePasskey.run(start.options, true);
    const session = await api('passkeys/register-verify', {flow: start.flow, credential});
    csrf = session.csrf;
    await refreshPasskeys();
    feedback('백업 패스키를 추가했습니다.');
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
      card.append(paragraph(row.label), paragraph(`추가: ${localTime(row.created)} · 마지막 사용: ${localTime(row.last_used)}`));
      if (items.length > 1) card.append(button('삭제', async () => {
        const {proof} = await authenticatePasskey('manage');
        await api('passkeys/remove', {proof, identity: row.id});
        locked();
        feedback('패스키를 삭제했습니다. 남아 있는 패스키로 다시 로그인하세요.');
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
    $('owner-submit').textContent = '로그인';
    $('pair-help').textContent = '관리자 비밀번호를 사용하거나 ./bridge admin --recovery로 브라우저를 연결하세요.';
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
  $('setup-store-guide').hidden = !ready || !!s.kakao_installed || !s.aurora_installed;
  const steps = [enrolled, approved, collecting];
  const labels = ['준비', '로그인', '수집'];
  $('guide-summary').textContent = collecting ? '수집 실행 중' : '설정 계속';
  if (!overviewInitialized && s) {
    overviewInitialized = true;
    $('setup-guide').open = !collecting;
    $('tablet-workspace').open = !collecting;
  }
  if (latestState?.job.state === 'failed') $('setup-guide').open = true;
  $('setup-progress').replaceChildren(...labels.map((label, i) => {
    const item = document.createElement('li'); item.textContent = label;
    item.dataset.complete = String(steps[i]); return item;
  }));
  let next = ['서버 준비 상태를 확인하고 있습니다.', '', ''];
  if (s && !ready) next = ['개인 기기를 시작하고 있습니다. 준비되면 자동으로 계속됩니다.', '', ''];
  else if (ready && !s.kakao_installed) next = s.aurora_installed
    ? ['스토어에서 익명 로그인을 마친 뒤 스토어 열기를 다시 누르고 카카오톡을 설치하세요. 설정은 자동으로 계속됩니다.', 'open-store', '스토어 열기']
    : ['기기와 앱 스토어 준비 중…', 'prepare', '준비 다시 시도'];
  else if (ready && !enrolled) next = ['카카오톡 로그인 준비 마무리 중…', 'configure', '준비 다시 시도'];
  else if (enrolled && !approved) next = session?.kakao?.login === 'logged_in'
    ? ['태블릿 로그인이 확인되었습니다. 휴대폰의 카카오톡 로그인이 유지되는지 확인하고 아래에서 수집을 시작하세요.', 'session-check', '상태 확인']
    : ['카카오톡을 열고 ‘다른 기기와 함께 사용’을 선택해 로그인하세요. 로그인은 자동으로 확인됩니다.', 'open-kakao', '카카오톡 열기'];
  else if (approved && !collecting) next = ['수집이 승인되었습니다. 수집기를 기다리는 중입니다. 필요하면 상태를 새로고침하세요.', 'session-check', '상태 확인'];
  else if (collecting) next = ['카카오톡 수집이 준비되었습니다. AI 연결은 선택 사항이며 필요할 때 추가할 수 있습니다.', '', ''];
  if (latestState?.job.state === 'failed') next[0] = latestState.job.message || '준비가 중단되었습니다. 아래 결과를 확인하고 다시 시도하세요.';
  $('setup-next').textContent = next[0];
  $('setup-next-button').hidden = !next[1];
  $('setup-next-button').textContent = next[2];
  $('setup-next-button').onclick = () => next[1] === 'connect-ai' ? connectionSetup.open() : action(next[1]);
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
    connectionSetup.setConnections(data);
    const activity = Math.max(0, ...data.grants.map(row => row.last_tool_at || 0), data.tunnel?.approved ? data.tunnel.last_tool_at || 0 : 0);
    const allowed = data.grants.length + (data.tunnel?.approved ? 1 : 0);
    $('overview-ai').textContent = activity ? '도구 호출 성공 기록 있음' : allowed ? '첫 AI 요청 대기 중' : '허용된 AI 연결 없음';
    $('overview-ai-detail').textContent = activity ? `마지막 성공: ${localTime(activity)} · 현재 연결 가능 여부는 별도 확인이 필요합니다.` : allowed ? '접근이 허용되었습니다. AI에 수집 상태 확인을 요청하세요.' : '선택 사항입니다. 로컬 클라이언트는 stdio 설정도 사용할 수 있습니다.';
    $('mcp-address').textContent = data.resource;
    $('connection-help').textContent = data.approval_mode === 'passkey'
      ? 'ChatGPT에 이 MCP 주소를 추가하고 OAuth를 선택하세요. 패스키로 인증하고 접근 권한을 확인한 뒤 연결을 허용하세요. 여기에서 연결을 해제할 수 있습니다.'
      : data.approval_mode === 'key'
        ? '이 서버는 기존 연결 키 승인 방식을 사용합니다. 연결 중인 브라우저에 연결 키를 입력하세요.'
        : 'ChatGPT에 이 MCP 주소를 추가하고 OAuth를 선택하세요. 브라우저의 코드와 일치하는 요청만 승인하세요.';
    if (data.resource.includes('.invalid/')) {
      $('mcp-address').textContent = '공개 OAuth 연결이 설정되지 않았습니다.';
      $('connection-help').textContent = data.tunnel?.configured
        ? '아래에서 개인 OpenAI 터널을 승인하세요. 나중에 다른 연결도 추가할 수 있습니다.'
        : 'AI 연결 없이도 수집할 수 있습니다. ‘연결 추가 또는 변경’에서 AI를 연결하세요.';
    }
    $('pending-count').textContent = data.pending.length ? `승인 대기 ${data.pending.length}개` : `허용 ${allowed}개`;
    renderSetup();
    const signature = JSON.stringify(data);
    if (signature === connectionSignature) return;
    connectionSignature = signature;
    const tunnel = data.tunnel;
    const tunnelPanel = $('tunnel-connection');
    tunnelPanel.hidden = !tunnel?.configured;
    if (tunnel?.configured) {
      const card = document.createElement('div'); card.className = 'connection-card';
      card.append(paragraph('OpenAI 개인 터널'), paragraph(tunnel.tunnel_id));
      card.append(paragraph(tunnel.last_tool_at && tunnel.approved ? `마지막 도구 호출 성공: ${localTime(tunnel.last_tool_at)}` : '이 승인 이후 성공한 도구 호출 기록이 없습니다.'));
      card.append(paragraph(tunnel.approved
        ? `${tunnel.expires === null ? '자동 만료 없이 접근이 허용됩니다.' : `${localTime(tunnel.expires)}까지 접근이 허용됩니다.`} ChatGPT에서 터널(Tunnel)을 선택하고 이 ID를 지정하세요. OAuth 로그인은 필요하지 않습니다.`
        : '이 개인 터널이 수집된 메시지를 읽고 요청한 이벤트 구독을 관리하도록 허용합니다. 본인만 접근할 수 있는 터널을 사용하세요. 승인은 자동 만료되지 않으며 여기에서 연결을 해제할 수 있습니다.'));
      if (tunnel.approved && tunnel.expires !== null) {
        card.append(button('승인 만료 기한 없애기', async () => {
          await api('tunnel/decision', {tunnel_id: tunnel.tunnel_id, approve: true});
          connectionSignature = ''; await refreshConnections();
        }));
      }
      if (tunnel.approved) {
        card.append(paragraph(tunnel.allow_send
          ? '이 터널의 AI가 내 계정으로 기존 카카오톡 대화방에 텍스트를 보낼 수 있습니다.'
          : '메시지 전송을 허용하면 이 터널의 AI가 내 계정으로 기존 대화방에 텍스트를 보낼 수 있습니다.'));
        card.append(button(tunnel.allow_send ? '메시지 전송 권한 해제' : '메시지 전송 허용', async () => {
          await api('tunnel/decision', {tunnel_id: tunnel.tunnel_id, approve: true, allow_send: !tunnel.allow_send});
          connectionSignature = ''; await refreshConnections();
        }));
      }
      card.append(button(tunnel.approved ? '터널 연결 해제' : '개인 터널 허용', async () => {
        await api('tunnel/decision', {tunnel_id: tunnel.tunnel_id, approve: !tunnel.approved});
        connectionSignature = ''; await refreshConnections();
      }));
      card.append(button('연결 안내', () => connectionSetup.open('openai-tunnel')));
      tunnelPanel.replaceChildren(card);
    }
    const nodes = data.pending.map(row => {
      const card = document.createElement('div'); card.className = 'connection-card';
      card.append(paragraph(`${row.client_name} · ${row.client_id}`), paragraph(`돌아갈 주소: ${row.redirect_origin}`), paragraph(`권한: ${row.scope}`));
      const label = document.createElement('label'); label.textContent = '연결 중인 브라우저에 표시된 8자리 코드 입력';
      const input = document.createElement('input'); input.maxLength = 8; input.autocomplete = 'off'; input.spellcheck = false;
      label.append(input); card.append(label);
      card.append(button('연결 승인', async () => {
        const code = input.value.trim().toUpperCase();
        if (!/^[A-F0-9]{8}$/.test(code)) throw new Error('연결 중인 브라우저의 코드를 입력하세요.');
        await api(`connections/${row.id}/decide`, {code, approve: true}); await refreshConnections();
      }), button('거절', async () => {
        await api(`connections/${row.id}/decide`, {code: row.code, approve: false}); await refreshConnections();
      }));
      card.append(paragraph('클라이언트 이름은 해당 클라이언트가 제공한 값입니다. 승인 전에 돌아갈 주소와 코드를 확인하세요.'));
      return card;
    });
    for (const row of data.grants) {
      const card = document.createElement('div'); card.className = 'connection-card';
      card.append(paragraph(row.last_tool_at ? `마지막 도구 호출 성공: ${localTime(row.last_tool_at)}` : '접근 허용됨 · 첫 도구 호출 성공 대기 중'));
      card.append(paragraph(row.client_id), paragraph(`${row.scope} · 만료: ${localTime(row.expires)}`), button('연결 해제', async () => {
        await api(`connections/${row.id}/revoke`, {}); await refreshConnections();
      })); nodes.push(card);
    }
    $('connections-list').replaceChildren(...(nodes.length ? nodes : [paragraph('대기 중이거나 승인된 OAuth 클라이언트가 없습니다.')]));
  } catch { if (active) { $('mcp-address').textContent = '연결 상태를 가져올 수 없습니다. ‘연결 새로고침’을 눌러 보세요.'; $('overview-ai').textContent = 'AI 상태를 가져오지 못했습니다'; $('overview-ai-detail').textContent = '‘AI 연결’을 열고 새로고침하세요.'; } }
  finally { connectionsLoading = false; }
}
$('refresh-connections').addEventListener('click', refreshConnections);
$('connections-panel').addEventListener('toggle', () => { if ($('connections-panel').open) refreshConnections(); });
let eventCursor = null, eventQuery = '', eventsLoading = false;
function eventRoom(row) {
  const card = document.createElement('div'); card.className = 'event-room';
  const info = document.createElement('div'); info.className = 'event-room-info';
  const name = row.name || '이름 없는 대화';
  const title = paragraph(name);
  const ref = document.createElement('details'); const refLabel = document.createElement('summary'); refLabel.textContent = '대화 식별자'; const refCode = document.createElement('code'); refCode.textContent = row.ref; ref.append(refLabel, refCode);
  const status = paragraph(''); status.className = 'hint';
  const toggle = button('', async () => {
    const requestedGeneration = generation;
    const enabled = !row.enabled;
    await api('events/conversations', {conversation_ref: row.ref, enabled});
    if (!active || requestedGeneration !== generation) return;
    row.enabled = enabled; render();
    feedback(enabled ? `${name} 대화의 이벤트를 켰습니다. 클라이언트에서도 구독해야 합니다.` : `${name} 대화의 이벤트를 껐습니다. 대기 중인 이벤트가 취소되었습니다.`);
  });
  toggle.className = 'event-switch';
  toggle.setAttribute('role', 'switch');
  toggle.setAttribute('aria-label', `${name} 대화 이벤트 (${row.ref})`);
  function render() {
    toggle.textContent = row.enabled ? '허용' : '꺼짐';
    toggle.setAttribute('aria-checked', String(row.enabled));
    status.textContent = !row.enabled ? '이벤트 꺼짐' : row.subscriptions
      ? `등록된 구독 ${row.subscriptions}개 · 수신 확인이 AI 알림을 보장하지는 않습니다`
      : '허용됨 · 아직 AI 구독이 없습니다. 연결된 AI에 이 대화의 새 메시지 구독을 요청하세요.';
  }
  render(); info.append(title, ref, status); card.append(info, toggle); return card;
}
async function refreshEvents(reset = true) {
  if (!active || eventsLoading) return;
  eventsLoading = true;
  const requestedGeneration = generation;
  if (reset) {
    eventCursor = null; eventQuery = $('event-search').value.trim();
    $('event-conversations').replaceChildren(); $('more-events').hidden = true;
  }
  ['event-search-button', 'refresh-events', 'more-events'].forEach(id => { $(id).disabled = true; });
  $('event-list-status').textContent = '대화 불러오는 중…';
  try {
    const query = new URLSearchParams();
    if (eventQuery) query.set('q', eventQuery);
    if (eventCursor) query.set('cursor', eventCursor);
    const data = await api('events/conversations?' + query);
    if (!active || requestedGeneration !== generation) return;
    $('event-conversations').append(...data.items.map(eventRoom));
    eventCursor = data.next_cursor;
    $('more-events').hidden = !(data.has_more && eventCursor);
    $('event-list-status').textContent = $('event-conversations').childElementCount
      ? '수집기에 보관된 대화만 표시됩니다. 설정은 연결된 모든 AI 클라이언트에 적용됩니다.'
      : eventQuery ? '이 이름과 일치하는 대화가 없습니다.' : '아직 수집된 대화가 없습니다. 메시지를 보낸 뒤 새로고침하세요.';
  } catch (error) {
    if (active && requestedGeneration === generation) $('event-list-status').textContent = error.message;
  } finally {
    eventsLoading = false;
    ['event-search-button', 'refresh-events', 'more-events'].forEach(id => { $(id).disabled = false; });
  }
}
$('events-panel').addEventListener('toggle', () => { if ($('events-panel').open) refreshEvents(); });
$('event-search-form').addEventListener('submit', event => { event.preventDefault(); refreshEvents(); });
$('refresh-events').addEventListener('click', () => refreshEvents());
$('more-events').addEventListener('click', () => refreshEvents(false));
$('browsers-panel').addEventListener('toggle', refreshBrowsers);
async function refreshBrowsers() {
  if (!active || !$('browsers-panel').open) return;
  try {
    const data = await api('browsers');
    $('browsers-list').replaceChildren(...data.items.map(row => {
      const card = document.createElement('div'); card.className = 'connection-card';
      card.append(paragraph(row.current ? '현재 브라우저' : row.label), paragraph(`만료: ${localTime(row.expires)}`), button('로그아웃', async () => {
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
    $('test-result').textContent = '휴대폰에서 나에게 메시지를 보내세요. 새 메시지 수집 대기 중…';
  } catch (error) { feedback(error.message); }
});
