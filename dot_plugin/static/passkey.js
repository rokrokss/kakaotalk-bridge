'use strict';

// Small native WebAuthn adapter; no external scripts or credential storage in the page.
window.BridgePasskey = (() => {
  const decode = value => Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4)), c => c.charCodeAt(0));
  const encode = value => btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
  async function run(options, create = false) {
    if (!window.isSecureContext || !window.PublicKeyCredential) throw new Error('패스키를 사용하려면 최신 시스템 브라우저에서 이 주소를 HTTPS로 여세요.');
    const publicKey = {...options, challenge: decode(options.challenge)};
    if (create) publicKey.user = {...options.user, id: decode(options.user.id)};
    for (const field of ['allowCredentials', 'excludeCredentials']) {
      if (options[field]) publicKey[field] = options[field].map(item => ({...item, id: decode(item.id)}));
    }
    let credential;
    try { credential = await navigator.credentials[create ? 'create' : 'get']({publicKey}); }
    catch (error) {
      if (error.name === 'NotAllowedError') throw new Error('패스키 요청이 취소되었거나 시간이 초과되었습니다. 다시 시도하거나 휴대폰 또는 보안 키를 선택하세요.');
      if (error.name === 'InvalidStateError') throw new Error('이 기기에는 이미 패스키가 있습니다. 로그인하거나 다른 기기를 선택하세요.');
      throw new Error('이 브라우저에서 패스키를 사용할 수 없습니다. 시스템 브라우저에서 설정된 주소를 열고 다시 시도하세요.');
    }
    const response = {clientDataJSON: encode(credential.response.clientDataJSON)};
    if (create) {
      response.attestationObject = encode(credential.response.attestationObject);
      response.transports = credential.response.getTransports?.() || [];
    } else {
      response.authenticatorData = encode(credential.response.authenticatorData);
      response.signature = encode(credential.response.signature);
      response.userHandle = credential.response.userHandle ? encode(credential.response.userHandle) : null;
    }
    return {id: credential.id, rawId: encode(credential.rawId), type: credential.type, response,
      clientExtensionResults: credential.getClientExtensionResults()};
  }
  return {run};
})();
