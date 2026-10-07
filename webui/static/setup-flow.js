'use strict';

// Only preparation and store navigation are automatic. Login, phone confirmation and
// consent always require the user's existing authenticated controls.
function nextPreparation(state, attempted) {
  const setup = state?.setup;
  if (!setup || ['offline', 'booting'].includes(setup.state)
      || ['running', 'failed'].includes(state.job?.state)) return null;
  if (state.sessions?.collection_approval === 'approved') return null;
  let action = null;
  if (!setup.enrolled) {
    if (setup.kakao_installed || setup.apk_available) action = 'configure';
    else if (!setup.bridge_installed && (!setup.aurora_installed || setup.locale !== 'ko-KR')) action = 'prepare';
    // Once the user signs in to Aurora, take them straight to the KakaoTalk listing.
    else if (setup.aurora_signed_in) action = 'open-store';
  } else if (attempted.has('configure') && state.job?.action === 'configure'
      && state.job.state === 'done') action = 'open-kakao';
  return action && !attempted.has(action) ? action : null;
}

// While waiting for the tablet login, re-inspect the screen so the login is detected
// without a button. Pause while the user is operating the tablet.
function loginCheckDue(state, now, lastInteraction) {
  const session = state?.sessions;
  if (!state?.setup?.enrolled || session?.collection_approval === 'approved'
      || state.job?.state === 'running') return false;
  const age = session ? now / 1000 - session.checked_at : Infinity;
  return age > 15 && now - lastInteraction > 20000;
}

// The one setup step the admin screen shows. 'done' means everyday management.
function setupStep(state) {
  const setup = state?.setup, session = state?.sessions, approval = session?.collection_approval;
  // A tablet inspection that found approval revoked outranks a lagging collector heartbeat.
  if (approval === 'approved' || (approval !== 'locked' && state?.collector?.state === 'collecting_partial')) return 'done';
  if (!setup || ['offline', 'booting'].includes(setup.state)) return 'starting';
  if (!setup.enrolled) {
    if (setup.kakao_installed || setup.apk_available) return 'finishing';
    if (!setup.aurora_installed) return 'preparing';
    return setup.aurora_signed_in ? 'install' : 'store-login';
  }
  // Unknown approval means the tablet could not be read; wait for the next inspection.
  if (!session || session.collection_approval === 'unknown') return 'checking';
  return session.kakao?.login === 'logged_in' ? 'phone' : 'login';
}

if (typeof module !== 'undefined') module.exports = { nextPreparation, loginCheckDue, setupStep };
