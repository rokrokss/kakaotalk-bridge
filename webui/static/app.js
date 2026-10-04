'use strict';

const $ = id => document.getElementById(id);
let csrf = '', active = false, paused = false, fetching = false, rendering = false;
let frame = null, pointer = null, blobURL = null, busy = false, generation = 0;
let setupInitialized = false, precheckValid = false, collectionApproved = false;
let loginAlreadyApproved = false;
const messages = {
  session_required: '관리자 인증이 만료됐습니다. 키를 다시 입력하세요.',
  device_busy: '기기 작업 중입니다. 잠시 후 다시 시도하세요.',
  invalid_request: '입력 내용을 확인하세요.',
  invalid_csrf: '관리 화면을 새로 열어주세요.',
  invalid_origin: '같은 HTTPS 주소에서 관리 화면을 열어주세요.',
  invalid_swipe: '드래그를 다시 시도하세요.',
  point_outside_screen: '화면 안을 선택하세요.',
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
  $('console').hidden = true;
  $('login-panel').hidden = false;
  $('logout').hidden = true;
  $('connection').textContent = '인증 필요';
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
    let reason = '요청에 실패했습니다. 잠시 후 다시 시도하세요.';
    try {
      const error = await response.json();
      reason = messages[error.detail] || (typeof error.detail === 'string' && /[가-힣]/.test(error.detail) ? error.detail : reason);
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
  $('connection').textContent = `관리자 · ${Math.ceil(session.expires_in / 60)}분 이내 만료`;
  $('pause').textContent = '일시정지';
  $('pause').setAttribute('aria-pressed', 'false');
  $('screen-placeholder').hidden = false;
  updateState();
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
    $('screen-label').textContent = paused ? '일시정지됨' : `${next.width} × ${next.height}`;
  } catch {
    if (requestedGeneration === generation) {
      frame = null;
      $('screen-label').textContent = '연결 대기';
      $('screen-placeholder').hidden = false;
      $('screen').hidden = true;
    }
  } finally {
    if (pendingURL) URL.revokeObjectURL(pendingURL);
    fetching = rendering = false;
  }
}

const localTime = value => value ? new Date(value * 1000).toLocaleString('ko-KR') : '기록 없음';
function renderSessions(s, stale) {
  const fresh = !!s && !stale;
  $('session-inspected').textContent = s
    ? `${localTime(s.checked_at)}${fresh ? ' 확인' : ' · 다시 확인 필요'}`
    : '‘상태 확인’을 눌러 기기를 검사하세요.';
  const screens = {
    login_required: '로그인 화면', main_screen_observed: '로그인 후 화면',
    not_visible: '카카오톡이 열려 있지 않음', not_installed: '카카오톡 미설치', unknown: '화면에서 판별할 수 없음',
  };
  $('tablet-status').textContent = fresh
    ? s.device === 'offline' ? '연결 끊김' : s.device === 'booting' ? '부팅 중' : screens[s.screen?.state] || '확인 전'
    : '확인 필요';
  $('tablet-detail').textContent = s?.tablet?.confirmed_at ? `로그인 직접 확인: ${localTime(s.tablet.confirmed_at)}` : '';
  const phone = s?.phone;
  const overdue = phone?.confirmed_at && Date.now() / 1000 - phone.confirmed_at > 86400;
  const phoneLabels = {
    operator_confirmed: '유지 확인 기록', recheck_due: '재확인 필요',
    reported_lost: '로그아웃 보고됨', unknown: '확인 기록 없음',
  };
  $('phone-status').textContent = phoneLabels[overdue && phone?.state === 'operator_confirmed' ? 'recheck_due' : phone?.state] || '확인 전';
  $('phone-detail').textContent = phone?.state === 'reported_lost'
    ? `${localTime(phone.reported_at)} · 직접 보고`
    : phone?.confirmed_at ? `${localTime(phone.confirmed_at)} · 직접 확인` : '핸드폰 상태는 직접 확인한 기록입니다.';
  $('approval-status').textContent = fresh
    ? ({ approved: '승인됨', locked: '확인 대기', unknown: '확인할 수 없음' }[s.collection_approval] || '확인 전')
    : '확인 필요';
  const proof = s?.precheck;
  // Typing makes the screen snapshot stale, but the precheck retains its own
  // 30-minute deadline. The server revalidates the device and app on approval.
  precheckValid = proof?.state === 'valid' && proof.expires_at > Date.now() / 1000;
  collectionApproved = fresh && s.collection_approval === 'approved';
  loginAlreadyApproved = s?.collection_approval === 'approved';
  $('login-check-help').textContent = loginAlreadyApproved
    ? '이미 수집 승인이 완료되어 검사가 필요 없습니다. 현재 상태는 ‘상태 확인’으로 확인하세요.'
    : '로그인 전에만 사용합니다. 검사 통과 후 30분 안에 태블릿에서 로그인하세요.';
  $('approval-detail').textContent = precheckValid
    ? `${localTime(proof.expires_at)}까지 양쪽 로그인을 확인하세요.`
    : collectionApproved ? '앱과 기기의 승인 기록이 일치합니다.'
    : fresh ? '로그인 옵션 검사와 양쪽 확인이 필요합니다.' : '';
  $('setup-summary').textContent = collectionApproved ? '확인 완료' : precheckValid ? '옵션 검사 완료' : '';
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
    busy = state.job.state === 'running';
    $('job').hidden = !state.job.message;
    $('job').textContent = state.job.message;
    $('job').dataset.state = state.job.state;
    const loginJob = ['login-check', 'confirm-secondary'].includes(state.job.action);
    $('login-check-result').hidden = !loginJob || !state.job.message;
    $('login-check-result').textContent = loginJob ? state.job.message : '';
    $('login-check-result').dataset.state = state.job.state;
    $('login-check').textContent = busy && state.job.action === 'login-check' ? '검사 중…' : '로그인 옵션 검사';
    const collector = state.collector.state;
    $('collector-status').dataset.state = collector;
    $('collector-status').textContent = collector === 'collecting_partial' ? '메시지 수집 중'
      : collector === 'unavailable' ? '수집 서버 연결 대기' : '수집 상태 확인 필요';
    $('collector-status').title = '태블릿에 수신된 메시지를 수집합니다. 전체 대화의 복원을 뜻하지 않습니다.';
    renderSessions(state.sessions, state.sessions_stale);
    updateControls();
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
  busy = true;
  updateControls();
  if (name === 'login-check') {
    $('login-check').textContent = '검사 중…';
    $('login-check-result').textContent = '태블릿 설정과 로그인 옵션을 확인하고 있습니다.';
    $('login-check-result').dataset.state = 'running';
    $('login-check-result').hidden = false;
  }
  try { await api('action', { name, ...extra }); await updateState(); }
  catch (error) {
    busy = false;
    $('login-check').textContent = '로그인 옵션 검사';
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
  if ($('install-dialog').returnValue === 'install') action('bootstrap');
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
  try { await api('text', { text }); feedback('입력했습니다. 태블릿 화면을 확인하세요.'); await refresh(true); }
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
  $('pause').textContent = paused ? '다시 연결' : '일시정지';
  $('pause').setAttribute('aria-pressed', String(paused));
  $('screen-label').textContent = paused ? '일시정지됨' : '화면 연결 중';
  if (!paused) refresh();
});
document.addEventListener('visibilitychange', () => {
  frame = null;
  if (!document.hidden) { refresh(); updateState(); }
});
setInterval(() => refresh(), 1200);
setInterval(updateState, 3000);
api('session').then(unlocked).catch(() => locked());
