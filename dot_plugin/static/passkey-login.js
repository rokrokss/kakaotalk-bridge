'use strict';
document.getElementById('passkey-mcp').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget, button = form.querySelector('button');
  const status = document.getElementById('passkey-status');
  button.disabled = true;
  status.textContent = '기기에서 인증하세요…';
  const ticket = form.elements.ticket.value;
  async function call(operation, data) {
    const response = await fetch('/authorize/passkey/' + operation, {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ticket, ...data})});
    if (!response.ok) throw new Error('연결 인증을 완료하지 못했습니다. 다시 시도하세요. 요청이 만료되었다면 처음부터 연결하세요.');
    return response.json();
  }
  try {
    const start = await call('options', {});
    const credential = await BridgePasskey.run(start.options);
    const result = await call('verify', {flow: start.flow, credential});
    location.assign(result.url);
  } catch (error) { status.textContent = /[가-힣]/.test(error.message || '') ? error.message : '연결 인증을 완료하지 못했습니다. 네트워크를 확인하고 다시 시도하세요.'; button.disabled = false; }
});
