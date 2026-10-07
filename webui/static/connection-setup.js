'use strict';

// Connection instructions depend on saved configuration, never the last job.
function connectionGuidance(state, method) {
  if (method === 'openai-tunnel' && state?.tunnel_configured && state.tunnel_id) return {kind: 'tunnel', value: state.tunnel_id};
  if (['https', 'tailscale'].includes(method) && state?.mcp_url) return {kind: 'https', value: state.mcp_url};
  return null;
}
function connectionDestination(method) {
  return ({'openai-tunnel': 'chatgpt', stdio: 'desktop', https: 'remote', tailscale: 'remote'})[method] || 'none';
}
const serverMethods = ['openai-tunnel', 'https', 'tailscale'];
// While a job runs or waits for provider approval the server accepts no other setup, so show that one.
function activeMethod(state, method) {
  const job = state?.job;
  return ['running', 'action_required'].includes(job?.state) && serverMethods.includes(job.method) ? job.method : method;
}
// The one wizard step to show: pick a use, set up the server, or finish in the AI client.
function connectionStep(state, method, editing) {
  if (!method) return 'choose';
  if (method === 'stdio') return 'finish';
  const job = state?.job;
  if (job?.method === method && ['running', 'action_required', 'failed', 'interrupted'].includes(job.state)) return 'configure';
  return !editing && connectionGuidance(state, method) ? 'finish' : 'configure';
}
if (typeof module !== 'undefined') module.exports = {connectionGuidance, connectionDestination, activeMethod, connectionStep};

// All setup requests go through the authenticated admin API. Credentials are
// submitted once, cleared immediately, and never put in browser storage or URLs.
function BridgeConnectionSetup({api, isActive, onChange, feedback}) {
  const el = id => document.getElementById(id);
  let state = null, timer = null, loading = false, sending = false, epoch = 0, prefilled = false, connections = null;
  // undefined: decide from the next status. null: let the user choose a use.
  let method, destination = null, editing = false, formError = '', checkError = '', checkRequested = false;
  const destinations = {chatgpt: ['openai-tunnel', 'https', 'tailscale'], desktop: ['stdio'], remote: ['https', 'tailscale']};
  const labels = {https: 'HTTPS 및 OAuth 설정', tailscale: 'Tailscale 설정', 'openai-tunnel': '터널 연결'};
  const pending = ['running', 'action_required', 'interrupted', 'failed'];

  function initialMethod() {
    const job = state?.job;
    if (pending.includes(job?.state) && labels[job.method]) return job.method;
    return connectionGuidance(state, state?.preferred_method) ? state.preferred_method : null;
  }

  function choose(next, nextDestination = connectionDestination(next)) {
    method = next; destination = next ? nextDestination : null;
    editing = false; formError = '';
    el('ai-api-key').value = '';
    render();
  }

  function render() {
    if (method === undefined && state?.available) method = initialMethod();
    const pinned = activeMethod(state, method ?? null);
    if (pinned !== (method ?? null)) { method = pinned; destination = connectionDestination(pinned); }
    if (method && !destinations[destination]?.includes(method)) destination = connectionDestination(method);
    const step = connectionStep(state, method ?? null, editing);
    el('ai-choose').hidden = step !== 'choose';
    el('ai-setup-form').hidden = step !== 'configure';
    el('ai-finish').hidden = step !== 'finish';
    el('ai-choose').querySelectorAll('button').forEach(button => { button.disabled = !state?.available; });
    const used = step === 'finish' && renderFinish();
    if (step === 'configure') renderForm();
    const stage = {choose: 0, configure: 1, finish: 2}[step];
    [...el('ai-progress').children].forEach((item, i) => {
      item.dataset.state = i < stage || (i === stage && used) ? 'done' : i === stage ? 'current' : 'todo';
      if (i === stage) item.setAttribute('aria-current', 'step'); else item.removeAttribute('aria-current');
    });
  }

  function renderForm() {
    const job = state?.job || {};
    const mine = job.method === method;
    const choices = destinations[destination] || [method];
    el('ai-methods').hidden = choices.length < 2;
    el('ai-methods').querySelectorAll('[data-method]').forEach(label => {
      label.hidden = !choices.includes(label.dataset.method);
      label.querySelector('input').checked = label.dataset.method === method;
    });
    document.querySelectorAll('[data-ai-method]').forEach(panel => {
      panel.hidden = panel.dataset.aiMethod !== method;
      panel.querySelectorAll('input, button').forEach(input => { input.disabled = panel.hidden; });
    });
    el('ai-public-url').required = method === 'https';
    el('ai-tunnel-id').required = method === 'openai-tunnel';
    el('ai-tunnel-approve').required = method === 'openai-tunnel';
    el('ai-tailscale-allow').required = method === 'tailscale';
    const reuse = state?.runtime_key_saved && el('ai-tunnel-id').value.trim() === state.tunnel_id;
    el('ai-api-key').required = method === 'openai-tunnel' && !reuse;
    el('ai-key-help').textContent = reuse
      ? '이 터널에 저장된 키가 있습니다. 그대로 쓰려면 비워 두고, 바꾸려면 새 키를 붙여 넣으세요.'
      : '서버에만 저장되며 이 화면에 다시 표시되지 않습니다.';
    el('ai-tailscale-location').textContent = state?.managed_vm
      ? '이 Mac에서는 Bridge의 Linux VM 안에서 Tailscale을 실행하고 그 VM의 주소를 사용합니다.'
      : 'Bridge가 설치된 Linux 서버에서 Tailscale을 실행합니다.';
    const busy = mine && ['running', 'action_required'].includes(job.state);
    const failed = mine && ['failed', 'interrupted'].includes(job.state);
    el('ai-setup-fields').disabled = !state?.available || job.state === 'running' || sending;
    el('ai-setup-submit').hidden = el('ai-back').hidden = busy;
    el('ai-setup-submit').textContent = failed ? '다시 시도' : labels[method];
    const error = formError || (failed ? (/[가-힣]/.test(job.message || '') ? job.message : '설정을 완료하지 못했습니다. 입력값을 확인하고 다시 시도하세요.') : '');
    el('ai-form-error').hidden = !error;
    el('ai-form-error').textContent = error;
    // Job progress replaces the buttons while the server works or waits for the provider.
    el('ai-job').hidden = !(busy || (mine && job.state === 'ready'));
    el('ai-job').dataset.state = job.state || 'idle';
    el('ai-job-message').className = job.state === 'running' ? 'setup-wait' : '';
    el('ai-job-message').textContent = /[가-힣]/.test(job.message || '') ? job.message
      : job.state === 'action_required' ? '아래 승인 페이지에서 연결을 허용하세요.' : '연결을 준비하고 있습니다.';
    const elapsed = job.started_at ? Math.max(0, Math.floor(Date.now() / 1000 - job.started_at)) : 0;
    el('ai-job-time').textContent = job.state === 'running' ? `${Math.floor(elapsed / 60)}분 ${elapsed % 60}초 경과 · 이 화면을 닫아도 계속됩니다.` : '';
    let actionURL = '';
    try {
      const url = new URL(job.action_url);
      if (url.origin === 'https://login.tailscale.com' && !url.username && !url.password) actionURL = url.href;
    } catch {}
    el('ai-provider-action').hidden = !(job.state === 'action_required' && actionURL);
    if (actionURL) el('ai-provider-action').href = actionURL;
    else el('ai-provider-action').removeAttribute('href');
    el('ai-continue').hidden = job.state !== 'action_required' || job.method !== 'tailscale';
  }

  // Returns whether a remote AI request has succeeded through this connection.
  function renderFinish() {
    const guide = method === 'stdio' ? {kind: 'stdio', value: ''} : connectionGuidance(state, method);
    const kind = guide?.kind, tunnel = connections?.tunnel;
    const unapproved = kind === 'tunnel' && !!connections && !tunnel?.approved;
    el('ai-finish-help').textContent = unapproved
      ? '터널은 설정되었지만 아직 허용되지 않았습니다. 허용하면 연결을 해제할 때까지 이 개인 터널이 수집된 메시지를 읽고 이벤트 구독을 관리할 수 있습니다.'
      : kind === 'tunnel' ? '개인 터널 연결이 허용되어 있습니다. ChatGPT에 추가하세요.'
      : kind === 'https' ? 'AI 서비스에서 연결하는 동안 이 화면을 열어 두세요.' : '';
    el('ai-finish-help').hidden = !el('ai-finish-help').textContent;
    el('ai-approve-tunnel').hidden = !unapproved;
    el('ai-client').hidden = !guide || kind === 'stdio';
    el('ai-client-label').textContent = kind === 'tunnel' ? '터널 ID' : 'MCP 서버 URL';
    el('ai-client-value').textContent = guide?.value || '';
    el('ai-finish-tunnel').hidden = kind !== 'tunnel' || unapproved;
    el('ai-finish-https').hidden = kind !== 'https';
    el('ai-stdio').hidden = el('ai-finish-stdio').hidden = el('ai-ssh').hidden = kind !== 'stdio';
    if (kind === 'stdio') renderStdio();
    const waiting = connections?.pending?.length || 0;
    el('ai-https-approve').textContent = connections?.approval_mode === 'admin'
      ? `이 화면 위의 승인 요청에서 연결 창의 코드와 같은지 확인하고 연결 승인을 누르세요.${waiting ? ` 지금 ${waiting}개가 기다리고 있습니다.` : ''}`
      : connections?.approval_mode === 'key' ? '연결 창에 서버의 연결 키를 입력하세요.'
      : '연결 창에서 패스키로 인증하고 연결을 허용하세요.';
    const allowed = kind === 'tunnel' ? (tunnel?.approved ? [tunnel] : []) : kind === 'https' ? connections?.grants || [] : [];
    const last = Math.max(0, ...allowed.map(row => row.last_tool_at || 0));
    el('ai-verify').hidden = unapproved;
    el('ai-activity').hidden = kind === 'stdio' || !connections || unapproved;
    el('ai-activity').dataset.state = last ? 'ok' : '';
    el('ai-activity').textContent = last ? `✓ ${new Date(last * 1000).toLocaleString('ko-KR')}에 AI 요청이 성공했습니다.`
      : allowed.length ? '아직 AI 요청 기록이 없습니다.' : '아직 허용된 연결이 없습니다.';
    el('ai-check').hidden = el('ai-edit-method').hidden = kind === 'stdio';
    const job = state?.job || {};
    const check = checkError || (checkRequested && job.method === 'check'
      ? job.state === 'running' ? '서버 서비스를 확인하고 있습니다…' : job.message || '' : '');
    el('ai-check-result').hidden = !check;
    el('ai-check-result').textContent = check;
    el('ai-check-result').dataset.state = checkError || (job.method === 'check' && job.state === 'failed') ? 'failed' : '';
    return !!last;
  }

  function renderStdio() {
    if (!state?.stdio) return;
    let config = state.stdio;
    const target = el('ai-ssh-target').value.trim();
    const valid = !target || /^(?:[a-zA-Z0-9_][a-zA-Z0-9_.-]*@)?[a-zA-Z0-9][a-zA-Z0-9_.-]*$/.test(target);
    el('ai-ssh-target').setCustomValidity(valid ? '' : '옵션이나 공백 없이 SSH 호스트 별칭 또는 user@host를 입력하세요.');
    el('ai-copy-stdio').disabled = !valid;
    if (target && valid) {
      // SSH joins remote arguments into a shell command, so quote every server path.
      const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";
      const client = state.stdio.mcpServers.kakaotalk;
      const remote = [client.command, ...client.args].map(quote).join(' ');
      config = {mcpServers: {kakaotalk: {command: 'ssh', args: ['-T', '-o', 'BatchMode=yes', target, remote]}}};
    }
    el('ai-stdio-config').textContent = valid ? JSON.stringify(config, null, 2) : '올바른 SSH 접속 대상을 입력하세요.';
  }

  function show() {
    el('connections-panel').open = true;
    el('ai-setup').hidden = false;
    el('open-ai-setup').hidden = true;
  }

  async function refresh() {
    if (!isActive() || loading) return;
    loading = true;
    const currentEpoch = epoch;
    clearTimeout(timer);
    try {
      const next = await api('connection-setup');
      if (!isActive() || currentEpoch !== epoch) return;
      const previous = state?.job;
      state = next;
      el('ai-agent-status').hidden = !!state.available;
      el('ai-agent-status').textContent = state.available ? '' : state.message;
      if (state.available && !prefilled) {
        prefilled = true;
        el('ai-tunnel-id').value = state.tunnel_id || '';
        el('ai-public-url').value = (state.mcp_url || '').replace(/\/mcp$/, '');
        if (pending.includes(state.job?.state) && labels[state.job.method]) show();
      }
      if (previous && previous.state !== 'ready' && state.job?.state === 'ready') {
        if (state.job.method === 'openai-tunnel') el('ai-tunnel-id').value = state.tunnel_id || '';
        if (['https', 'tailscale'].includes(state.job.method)) el('ai-public-url').value = (state.mcp_url || '').replace(/\/mcp$/, '');
        if (state.job.method === method) editing = false;
      }
      render();
      if (previous?.state === 'running' && state.job?.state !== 'running') void onChange();
    } catch {
      if (isActive() && currentEpoch === epoch) {
        el('ai-agent-status').hidden = false;
        el('ai-agent-status').textContent = '설정 상태에 다시 연결하는 중… 서버에서는 작업이 계속됩니다. 요청이 표시되면 다시 로그인하세요.';
      }
    } finally {
      loading = false;
      if (isActive() && currentEpoch === epoch) timer = setTimeout(refresh, state?.job?.state === 'running' ? 2000 : 10000);
    }
  }

  async function submit(requested = method) {
    if (sending || !state?.available || state?.job?.state === 'running') return;
    const data = {method: requested, request_id: crypto.randomUUID()};
    formError = checkError = '';
    if (requested === 'https') {
      try {
        const url = new URL(el('ai-public-url').value.trim());
        if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || !['', '/', '/mcp', '/mcp/'].includes(url.pathname)) throw new Error();
        data.url = url.origin; el('ai-public-url').value = url.origin;
      } catch {
        formError = 'HTTPS 주소를 입력하세요. 예: https://bridge.example.com 또는 https://bridge.example.com/mcp';
        render(); el('ai-public-url').focus(); return;
      }
    }
    if (requested !== 'check' && !el('ai-setup-form').checkValidity()) { render(); el('ai-setup-form').reportValidity(); return; }
    if (requested === 'openai-tunnel') {
      Object.assign(data, {tunnel_id: el('ai-tunnel-id').value.trim(), api_key: el('ai-api-key').value.trim(), approve: el('ai-tunnel-approve').checked});
      el('ai-api-key').value = '';
    }
    if (requested === 'tailscale') data.install_tailscale = el('ai-tailscale-allow').checked;
    if (requested === 'check') checkRequested = true;
    sending = true; render();
    const currentEpoch = epoch;
    try {
      const job = await api('connection-setup', data);
      if (!isActive() || currentEpoch !== epoch) return;
      state.job = job;
    } catch (error) {
      if (isActive() && currentEpoch === epoch) {
        if (requested === 'check') checkError = error.message; else formError = error.message;
      }
    } finally {
      delete data.api_key;
      sending = false;
      if (isActive() && currentEpoch === epoch) { render(); await refresh(); }
    }
  }

  async function copy(id) {
    try { await navigator.clipboard.writeText(el(id).textContent); feedback('복사했습니다.'); }
    catch { feedback('이 브라우저에서는 자동 복사를 사용할 수 없습니다. 표시된 텍스트를 선택해 복사하세요.'); }
  }
  el('ai-setup-form').noValidate = true;
  el('ai-setup-form').addEventListener('submit', event => { event.preventDefault(); void submit(); });
  // Picking a use means adding something, so show its methods even if the default one is already set up.
  document.querySelectorAll('[data-destination]').forEach(button => button.addEventListener('click', () => {
    const methods = destinations[button.dataset.destination];
    choose(methods[0], button.dataset.destination);
    editing = methods.length > 1; render();
  }));
  // Switching methods inside an edit stays in the form instead of jumping to saved guidance.
  el('ai-methods').addEventListener('change', event => { const keep = editing; choose(event.target.value, destination); editing = keep; render(); });
  el('ai-back').addEventListener('click', () => choose(null));
  el('ai-restart').addEventListener('click', () => choose(null));
  el('ai-edit-method').addEventListener('click', () => { editing = true; formError = ''; render(); });
  el('ai-close').addEventListener('click', () => { el('ai-setup').hidden = true; el('open-ai-setup').hidden = false; });
  el('ai-tunnel-id').addEventListener('input', render);
  el('ai-ssh-target').addEventListener('input', renderStdio);
  el('ai-copy-stdio').addEventListener('click', () => copy('ai-stdio-config'));
  el('ai-copy-value').addEventListener('click', () => copy('ai-client-value'));
  el('ai-check').addEventListener('click', () => submit('check'));
  el('ai-continue').addEventListener('click', () => { el('ai-tailscale-allow').checked = true; void submit('tailscale'); });
  el('ai-approve-tunnel').addEventListener('click', async () => {
    el('ai-approve-tunnel').disabled = true;
    try { await api('tunnel/decision', {tunnel_id: connections.tunnel.tunnel_id, approve: true}); await onChange(); }
    catch (error) { feedback(error.message); }
    finally { el('ai-approve-tunnel').disabled = false; }
  });
  return {
    refresh,
    setConnections(value) { connections = value; render(); },
    open(next) {
      show();
      if (next) choose(next); else { method = undefined; destination = null; editing = false; render(); }
      el('ai-setup').scrollIntoView({behavior: 'smooth', block: 'start'});
      void refresh();
    },
    lock() {
      epoch++; clearTimeout(timer); state = connections = null; prefilled = false;
      method = undefined; destination = null; editing = checkRequested = false; formError = checkError = '';
      el('ai-setup-form').reset(); el('ai-api-key').value = ''; el('ai-ssh-target').value = '';
      el('ai-provider-action').removeAttribute('href');
      el('ai-setup').hidden = true; el('open-ai-setup').hidden = false;
      el('ai-stdio-config').textContent = el('ai-client-value').textContent = '';
      render();
    },
  };
}
