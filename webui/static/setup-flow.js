'use strict';

// Only preparation is automatic. Login, phone confirmation and consent always
// require the user's existing authenticated controls.
function nextPreparation(state, attempted) {
  const setup = state?.setup;
  if (!setup || ['offline', 'booting'].includes(setup.state)
      || ['running', 'failed'].includes(state.job?.state)) return null;
  if (state.sessions?.collection_approval === 'approved') return null;
  let action = null;
  if (!setup.enrolled) {
    if (setup.kakao_installed || setup.apk_available) action = 'configure';
    else if (!setup.bridge_installed && (!setup.aurora_installed || setup.locale !== 'ko-KR')) action = 'prepare';
  } else if (attempted.has('configure') && state.job?.action === 'configure'
      && state.job.state === 'done') action = 'open-kakao';
  return action && !attempted.has(action) ? action : null;
}

if (typeof module !== 'undefined') module.exports = { nextPreparation };
