'use strict';
const form = document.getElementById('approval');
const status = document.getElementById('status');
const deadline = Date.now() + 600000;
async function poll() {
  if (Date.now() > deadline) { status.textContent = '요청이 만료되었습니다. 다시 연결하세요.'; return; }
  try {
    const response = await fetch('/authorize/status', {
      method: 'POST', credentials: 'same-origin',
      body: new URLSearchParams(new FormData(form)),
    });
    if (!response.ok) { status.textContent = '요청이 만료되었거나 사용할 수 없습니다. 다시 연결하세요.'; return; }
    const data = await response.json();
    if (data.status === 'approved') { status.textContent = '승인되었습니다. 연결 중…'; form.submit(); return; }
    if (data.status === 'denied') { status.textContent = '연결이 거절되었습니다.'; return; }
  } catch { status.textContent = '연결이 중단되었습니다. 다시 시도 중…'; }
  setTimeout(poll, 5000);
}
poll();
