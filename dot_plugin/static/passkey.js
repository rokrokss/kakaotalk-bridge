'use strict';

// Small native WebAuthn adapter; no external scripts or credential storage in the page.
window.BridgePasskey = (() => {
  const decode = value => Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4)), c => c.charCodeAt(0));
  const encode = value => btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
  async function run(options, create = false) {
    if (!window.isSecureContext || !window.PublicKeyCredential) throw new Error('Open this address in a current system browser with HTTPS to use passkeys.');
    const publicKey = {...options, challenge: decode(options.challenge)};
    if (create) publicKey.user = {...options.user, id: decode(options.user.id)};
    for (const field of ['allowCredentials', 'excludeCredentials']) {
      if (options[field]) publicKey[field] = options[field].map(item => ({...item, id: decode(item.id)}));
    }
    let credential;
    try { credential = await navigator.credentials[create ? 'create' : 'get']({publicKey}); }
    catch (error) {
      if (error.name === 'NotAllowedError') throw new Error('Passkey request cancelled or timed out. Try again, or choose your phone or security key.');
      if (error.name === 'InvalidStateError') throw new Error('This device already has a passkey. Sign in or choose another device.');
      throw new Error('This browser could not use the passkey. Open the configured address in your system browser and try again.');
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
