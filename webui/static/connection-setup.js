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
if (typeof module !== 'undefined') module.exports = {connectionGuidance, connectionDestination};

// All setup requests go through the authenticated admin API. Credentials are
// submitted once, cleared immediately, and never put in browser storage or URLs.
function BridgeConnectionSetup({api, isActive, onChange, feedback}) {
  const el = id => document.getElementById(id);
  let state = null, timer = null, loading = false, sending = false, epoch = 0, initialized = false, connections = null;
  const labels = {none: '현재 설정 유지', stdio: '이 설정 사용', https: 'HTTPS 및 OAuth 설정',
    tailscale: 'Tailscale 및 OAuth 설정', 'openai-tunnel': '터널 설정 및 허용'};
  const descriptions = {none: '언제든 이 화면으로 돌아올 수 있습니다.',
    stdio: '데스크톱 AI 클라이언트 또는 SSH 프로세스를 실행할 수 있는 클라이언트에서 사용합니다.',
    https: '기존 공개 HTTPS 주소에 연결하는 AI 클라이언트에서 사용합니다.',
    tailscale: '리버스 프록시를 직접 관리하지 않고 공개 MCP 주소를 만들 수 있습니다.',
    'openai-tunnel': '서버에서 ChatGPT로 연결합니다. 공개 MCP 주소나 Tailscale이 필요하지 않습니다.'};

  function renderMethod() {
    const method = el('ai-method').value;
    const choices = {none:['none'], chatgpt:['openai-tunnel', 'https', 'tailscale'], desktop:['stdio'], remote:['https', 'tailscale']}[el('ai-destination').value];
    for (const option of el('ai-method').options) { option.hidden = !!choices && !choices.includes(option.value); option.disabled = option.hidden; }
    document.querySelectorAll('[data-ai-method]').forEach(panel => {
      panel.hidden = panel.dataset.aiMethod !== method;
      panel.querySelectorAll('input, button').forEach(input => { input.disabled = panel.hidden; });
    });
    el('ai-method-help').textContent = descriptions[method];
    el('ai-setup-submit').textContent = labels[method];
    el('ai-public-url').required = method === 'https';
    el('ai-tunnel-id').required = method === 'openai-tunnel';
    el('ai-tunnel-approve').required = method === 'openai-tunnel';
    el('ai-tailscale-allow').required = method === 'tailscale';
    const reuse = state?.runtime_key_saved && el('ai-tunnel-id').value.trim() === state.tunnel_id;
    el('ai-api-key').required = method === 'openai-tunnel' && !reuse;
    el('ai-key-help').textContent = reuse
      ? '이 터널에 저장된 키가 있습니다. 그대로 사용하려면 비워 두고, 바꾸려면 새 키를 붙여 넣으세요.'
      : '서버에 저장됩니다. 저장한 키는 이 화면에 다시 표시되지 않습니다.';
    el('ai-tailscale-location').textContent = state?.managed_vm
      ? '이 Mac에서는 Bridge의 Linux VM 안에서 Tailscale을 실행하며 해당 VM의 주소를 사용합니다.'
      : 'Bridge가 설치된 Linux 서버에서 Tailscale을 실행합니다.';
    el('ai-setup-fields').disabled = !state?.available || state?.job?.state === 'running' || sending;
    el('ai-setup-submit').hidden = !el('ai-edit').open && !!connectionGuidance(state, method);
    renderStdio();
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

  function renderJob() {
    const job = state?.job || {};
    el('ai-job').hidden = !job.state || job.state === 'idle' || (job.state === 'ready' && job.method !== 'check' && job.method !== el('ai-method').value);
    el('ai-job').dataset.state = job.state || 'idle';
    el('ai-job-title').textContent = {running: '연결 설정 중…', ready: '서버 설정 완료',
      failed: '설정 확인 필요', interrupted: '설정 중단됨', action_required: '승인이 필요합니다'}[job.state] || '';
    if (job.method === 'check' && job.state === 'ready') el('ai-job-title').textContent = '서버 확인 완료';
    if (job.method === 'check' && job.state === 'running') el('ai-job-title').textContent = '서버 서비스 확인 중…';
    if (['none', 'stdio'].includes(job.method) && job.state === 'ready') el('ai-job-title').textContent = '선택 저장됨';
    el('ai-job-message').textContent = /[가-힣]/.test(job.message || '') ? job.message : ({running: '선택한 연결을 준비하고 있습니다.', ready: '설정을 완료했습니다. 아래 연결 안내를 확인하세요.', failed: '설정을 완료하지 못했습니다. 입력값을 확인하고 다시 시도하세요.', interrupted: '이전 설정이 중단되었습니다. 내용을 확인한 뒤 다시 시도하세요.', action_required: '아래 승인 페이지에서 연결을 허용하세요.'}[job.state] || '');
    const elapsed = job.started_at ? Math.max(0, Math.floor(Date.now() / 1000 - job.started_at)) : 0;
    el('ai-job-time').textContent = job.state === 'running' ? `${Math.floor(elapsed / 60)}분 ${elapsed % 60}초 경과 · 화면을 나갔다가 돌아와도 됩니다.` : '';
    el('ai-retry').hidden = !['failed', 'interrupted'].includes(job.state);
    el('ai-retry').textContent = job.method === 'check' ? '다시 확인' : '확인 후 다시 시도';
    let actionURL = '';
    try {
      const url = new URL(job.action_url);
      if (url.origin === 'https://login.tailscale.com' && !url.username && !url.password) actionURL = url.href;
    } catch {}
    el('ai-provider-action').hidden = !(job.state === 'action_required' && actionURL);
    if (actionURL) el('ai-provider-action').href = actionURL;
    else el('ai-provider-action').removeAttribute('href');
    el('ai-continue').hidden = job.state !== 'action_required' || job.method !== 'tailscale';
    const guide = connectionGuidance(state, el('ai-method').value);
    el('ai-finish').hidden = !guide;
    el('ai-finish-tunnel').hidden = guide?.kind !== 'tunnel' || !connections?.tunnel?.approved;
    el('ai-finish-https').hidden = guide?.kind !== 'https';
    if (guide) {
      el('ai-finish-help').textContent = guide.kind === 'tunnel'
        && !connections?.tunnel?.approved
        ? '터널은 설정되었지만 접근이 허용되지 않았습니다. ChatGPT에 추가하기 전에 위 ‘AI 연결’에서 확인하고 허용하세요.'
        : guide.kind === 'tunnel'
        ? '이 개인 터널의 접근이 허용되었습니다. ChatGPT에서 아래 단계에 따라 연결하세요.'
        : 'AI 클라이언트에 연결을 추가하는 동안 이 관리 화면을 열어 두세요.';
      el('ai-client-label').textContent = guide.kind === 'tunnel' ? '터널 ID' : 'MCP 서버 URL';
      el('ai-client-value').textContent = guide.value;
    }
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
      el('ai-agent-status').textContent = state.available ? '메시지를 사용할 곳을 선택하세요. 기존 연결은 유지됩니다.' : state.message;
      if (state.available && !initialized) {
        initialized = true;
        el('ai-tunnel-id').value = state.tunnel_id || '';
        el('ai-public-url').value = (state.mcp_url || '').replace(/\/mcp$/, '');
        const pending = ['running', 'action_required', 'interrupted', 'failed'].includes(state.job?.state);
        el('ai-method').value = pending && labels[state.job.method] ? state.job.method : state.preferred_method || (state.tunnel_configured ? 'openai-tunnel' : state.mcp_url ? 'https' : 'none');
        el('ai-destination').value = connectionDestination(el('ai-method').value);
        el('ai-edit').open = pending || !connectionGuidance(state, el('ai-method').value);
        if (pending) { el('connections-panel').open = true; el('ai-setup').open = true; }
      }
      if (previous?.state === 'running' && state.job?.state === 'ready') {
        if (state.job.method === 'openai-tunnel') el('ai-tunnel-id').value = state.tunnel_id || '';
        if (['https', 'tailscale'].includes(state.job.method)) el('ai-public-url').value = (state.mcp_url || '').replace(/\/mcp$/, '');
        if (state.job.method !== 'check' && connectionGuidance(state, el('ai-method').value)) el('ai-edit').open = false;
      }
      renderMethod(); renderJob();
      if (previous?.state === 'running' && state.job?.state !== 'running') void onChange();
    } catch {
      if (isActive() && currentEpoch === epoch) el('ai-agent-status').textContent = '설정 상태에 다시 연결하는 중… 서버에서는 작업이 계속됩니다. 요청이 표시되면 다시 로그인하세요.';
    } finally {
      loading = false;
      if (isActive() && currentEpoch === epoch) timer = setTimeout(refresh, state?.job?.state === 'running' ? 2000 : 10000);
    }
  }

  async function submit(method = el('ai-method').value) {
    if (sending || !state?.available || state?.job?.state === 'running') return;
    const data = {method, request_id: crypto.randomUUID()};
    el('ai-form-error').hidden = true;
    if (method === 'https') {
      try {
        const url = new URL(el('ai-public-url').value.trim());
        if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || !['', '/', '/mcp', '/mcp/'].includes(url.pathname)) throw new Error();
        data.url = url.origin; el('ai-public-url').value = url.origin;
      } catch {
        el('ai-form-error').textContent = 'HTTPS 주소를 입력하세요. 예: https://bridge.example.com 또는 https://bridge.example.com/mcp';
        el('ai-form-error').hidden = false; el('ai-edit').open = true; el('ai-public-url').focus(); return;
      }
    }
    if (method !== 'check' && !el('ai-setup-form').checkValidity()) {
      el('ai-edit').open = true; el('ai-setup-form').reportValidity(); return;
    }
    if (method === 'openai-tunnel') {
      Object.assign(data, {tunnel_id: el('ai-tunnel-id').value.trim(), api_key: el('ai-api-key').value.trim(), approve: el('ai-tunnel-approve').checked});
      el('ai-api-key').value = '';
    }
    if (method === 'tailscale') data.install_tailscale = el('ai-tailscale-allow').checked;
    sending = true; renderMethod();
    const currentEpoch = epoch;
    try {
      const job = await api('connection-setup', data);
      if (!isActive() || currentEpoch !== epoch) return;
      state.job = job;
      renderJob();
    } catch (error) {
      if (isActive() && currentEpoch === epoch) { el('ai-form-error').textContent = error.message; el('ai-form-error').hidden = false; }
    } finally {
      delete data.api_key;
      sending = false;
      if (isActive() && currentEpoch === epoch) { renderMethod(); await refresh(); }
    }
  }

  async function copy(id) {
    try { await navigator.clipboard.writeText(el(id).textContent); feedback('복사했습니다.'); }
    catch { feedback('이 브라우저에서는 자동 복사를 사용할 수 없습니다. 표시된 텍스트를 선택해 복사하세요.'); }
  }
  el('ai-setup-form').noValidate = true;
  el('ai-setup-form').addEventListener('submit', event => { event.preventDefault(); void submit(); });
  function selectMethod(method) {
    el('ai-method').value = method; el('ai-api-key').value = '';
    el('ai-form-error').hidden = true;
    el('ai-edit').open = !connectionGuidance(state, method);
    renderMethod(); renderJob();
  }
  el('ai-destination').addEventListener('change', () => {
    const destination = el('ai-destination').value;
    if (destination !== 'advanced') selectMethod(({chatgpt:'openai-tunnel', desktop:'stdio', remote:'https', none:'none'})[destination]);
  });
  el('ai-method').addEventListener('change', () => { el('ai-destination').value = connectionDestination(el('ai-method').value); selectMethod(el('ai-method').value); });
  el('ai-edit').addEventListener('toggle', renderMethod);
  el('ai-tunnel-id').addEventListener('input', renderMethod);
  el('ai-ssh-target').addEventListener('input', renderStdio);
  el('ai-copy-stdio').addEventListener('click', () => copy('ai-stdio-config'));
  el('ai-copy-value').addEventListener('click', () => copy('ai-client-value'));
  el('ai-check').addEventListener('click', () => submit('check'));
  el('ai-retry').addEventListener('click', () => {
    if (state?.job?.method === 'check') { void submit('check'); return; }
    if (labels[state?.job?.method]) selectMethod(state.job.method);
    el('ai-edit').open = true; el('ai-edit').scrollIntoView({block:'center'});
  });
  el('ai-continue').addEventListener('click', () => {
    el('ai-method').value = 'tailscale'; el('ai-tailscale-allow').checked = true; void submit('tailscale');
  });
  el('ai-setup').addEventListener('toggle', () => { if (el('ai-setup').open) void refresh(); });
  return {
    refresh,
    setConnections(value) { connections = value; renderJob(); },
    open(method) { el('connections-panel').open = true; el('ai-setup').open = true; if (method) { el('ai-destination').value = connectionDestination(method); selectMethod(method); } el('ai-setup').scrollIntoView({behavior: 'smooth', block: 'start'}); void refresh(); },
    lock() {
      epoch++; clearTimeout(timer); state = connections = null; initialized = false;
      el('ai-setup-form').reset(); el('ai-api-key').value = '';
      el('ai-provider-action').removeAttribute('href'); el('ai-job').hidden = el('ai-finish').hidden = true;
      el('ai-stdio-config').textContent = el('ai-client-value').textContent = '';
      renderMethod();
    },
  };
}
