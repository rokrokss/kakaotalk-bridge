'use strict';
document.getElementById('passkey-mcp').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget, button = form.querySelector('button');
  const status = document.getElementById('passkey-status');
  button.disabled = true;
  status.textContent = 'Confirm with your device…';
  const ticket = form.elements.ticket.value;
  async function call(operation, data) {
    const response = await fetch('/authorize/passkey/' + operation, {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ticket, ...data})});
    if (!response.ok) throw new Error('Connection verification did not complete. Retry, or restart the connection if this request expired.');
    return response.json();
  }
  try {
    const start = await call('options', {});
    const credential = await BridgePasskey.run(start.options);
    const result = await call('verify', {flow: start.flow, credential});
    location.assign(result.url);
  } catch (error) { status.textContent = error.message; button.disabled = false; }
});
