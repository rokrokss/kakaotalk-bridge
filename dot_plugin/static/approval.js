'use strict';
const form = document.getElementById('approval');
const status = document.getElementById('status');
const deadline = Date.now() + 600000;
async function poll() {
  if (Date.now() > deadline) { status.textContent = 'Request expired. Start the connection again.'; return; }
  try {
    const response = await fetch('/authorize/status', {
      method: 'POST', credentials: 'same-origin',
      body: new URLSearchParams(new FormData(form)),
    });
    if (!response.ok) { status.textContent = 'Request expired or unavailable. Start the connection again.'; return; }
    const data = await response.json();
    if (data.status === 'approved') { status.textContent = 'Approved. Connecting…'; form.submit(); return; }
    if (data.status === 'denied') { status.textContent = 'Connection declined.'; return; }
  } catch { status.textContent = 'Connection interrupted. Retrying…'; }
  setTimeout(poll, 5000);
}
poll();
