const {test} = require('node:test');
const assert = require('node:assert/strict');
const {nextPreparation, loginCheckDue, setupStep} = require('../webui/static/setup-flow.js');
const state = (setup, job = {state: 'done', action: 'setup-check'}) => ({setup: {state: 'needs_setup', ...setup}, job});

test('fresh device prepares once, then waits for the user to install KakaoTalk', () => {
  assert.equal(nextPreparation(state({}), new Set()), 'prepare');
  assert.equal(nextPreparation(state({}), new Set(['prepare'])), null);
  assert.equal(nextPreparation(state({aurora_installed: true, locale: 'ko-KR'}), new Set()), null);
});

test('installed or imported KakaoTalk automatically configures components', () => {
  for (const setup of [{kakao_installed: true}, {apk_available: true}]) {
    assert.equal(nextPreparation(state(setup), new Set()), 'configure');
  }
  assert.equal(nextPreparation(state({enrolled: true}, {state: 'done', action: 'configure'}), new Set(['configure'])), 'open-kakao');
});

test('signing in to Aurora opens the KakaoTalk listing once', () => {
  const signedIn = state({aurora_installed: true, locale: 'ko-KR', aurora_signed_in: true});
  assert.equal(nextPreparation(signedIn, new Set()), 'open-store');
  assert.equal(nextPreparation(signedIn, new Set(['open-store'])), null);
});

test('existing enrollment and approval are never automatically changed', () => {
  assert.equal(nextPreparation(state({enrolled: true}), new Set()), null);
  assert.equal(nextPreparation({...state({}), sessions: {collection_approval: 'approved'}}, new Set()), null);
  assert.equal(nextPreparation(state({bridge_installed: true}), new Set()), null);
});

test('busy, booting and failed operations never trigger another automatic action', () => {
  for (const job of ['running', 'failed']) assert.equal(nextPreparation(state({}, {state: job}), new Set()), null);
  assert.equal(nextPreparation(state({state: 'booting'}), new Set()), null);
  assert.equal(nextPreparation(state({state: 'offline'}), new Set()), null);
});

test('login is re-inspected while waiting, but never during tablet input or after approval', () => {
  const now = Date.now();
  const waiting = {setup: {enrolled: true}, job: {state: 'done'}, sessions: {checked_at: now / 1000 - 30, collection_approval: 'locked'}};
  assert.equal(loginCheckDue(waiting, now, now - 60000), true);
  assert.equal(loginCheckDue(waiting, now, now - 5000), false);
  assert.equal(loginCheckDue({...waiting, sessions: {...waiting.sessions, checked_at: now / 1000 - 5}}, now, 0), false);
  assert.equal(loginCheckDue({...waiting, sessions: {...waiting.sessions, collection_approval: 'approved'}}, now, 0), false);
  assert.equal(loginCheckDue({...waiting, job: {state: 'running'}}, now, 0), false);
  assert.equal(loginCheckDue({...waiting, setup: {enrolled: false}}, now, 0), false);
});

test('setup shows exactly one step, in order', () => {
  const ready = {state: 'needs_setup', aurora_installed: true, locale: 'ko-KR'};
  const enrolled = {state: 'android_ready', enrolled: true, kakao_installed: true};
  const session = (login, approval = 'locked', reason = 'approval_required') =>
    ({checked_at: 1, collection_approval: approval, approval_reason: reason, kakao: {login}});
  const cases = [
    [{}, 'starting'],
    [{setup: {state: 'booting'}}, 'starting'],
    [{setup: {state: 'needs_setup'}}, 'preparing'],
    [{setup: ready}, 'store-login'],
    [{setup: {...ready, aurora_signed_in: true}}, 'install'],
    [{setup: {...ready, kakao_installed: true}}, 'finishing'],
    [{setup: {state: 'needs_setup', apk_available: true}}, 'finishing'],
    [{setup: enrolled}, 'checking'],
    [{setup: enrolled, sessions: session('unknown', 'unknown', null)}, 'checking'],
    [{setup: enrolled, sessions: session('login_required')}, 'login'],
    [{setup: enrolled, sessions: session('logged_in')}, 'phone'],
    [{setup: enrolled, sessions: session('logged_in', 'approved', null)}, 'done'],
    [{setup: {state: 'offline'}, collector: {state: 'collecting_partial'}}, 'done'],
  ];
  for (const [input, step] of cases) assert.equal(setupStep(input), step, JSON.stringify(input));
});

test('a revoked approval returns to the login or phone step, never the dashboard', () => {
  const enrolled = {state: 'android_ready', enrolled: true, kakao_installed: true};
  for (const reason of ['account_changed', 'android_changed', 'phone_reported_lost']) {
    const sessions = {checked_at: 1, collection_approval: 'locked', approval_reason: reason, kakao: {login: 'logged_in'}};
    assert.equal(setupStep({setup: enrolled, sessions, collector: {state: 'collecting_partial'}}), 'phone');
    assert.equal(setupStep({setup: enrolled, sessions: {...sessions, kakao: {login: 'login_required'}}}), 'login');
  }
});
