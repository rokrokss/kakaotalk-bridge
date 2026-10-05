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
  const labels = {none: 'Keep current setup', stdio: 'Use this configuration', https: 'Configure HTTPS and OAuth',
    tailscale: 'Set up Tailscale and OAuth', 'openai-tunnel': 'Set up and allow tunnel'};
  const descriptions = {none: 'You can return to this page at any time.',
    stdio: 'For desktop AI clients and clients that can start an SSH process.',
    https: 'For AI clients that connect to an existing public HTTPS address.',
    tailscale: 'For a public MCP address without managing your own reverse proxy.',
    'openai-tunnel': 'An outbound connection to ChatGPT. No public MCP address or Tailscale is needed.'};

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
      ? 'A key is saved for this tunnel. Leave blank to reuse it, or paste a replacement.'
      : 'Saved on your server. The key is never returned to this page.';
    el('ai-tailscale-location').textContent = state?.managed_vm
      ? 'On this Mac, web setup runs Tailscale inside Bridge’s Linux VM. It uses that VM’s address.'
      : 'Tailscale will run on the Linux server where Bridge is installed.';
    el('ai-setup-fields').disabled = !state?.available || state?.job?.state === 'running' || sending;
    el('ai-setup-submit').hidden = !el('ai-edit').open && !!connectionGuidance(state, method);
    renderStdio();
  }

  function renderStdio() {
    if (!state?.stdio) return;
    let config = state.stdio;
    const target = el('ai-ssh-target').value.trim();
    const valid = !target || /^(?:[a-zA-Z0-9_][a-zA-Z0-9_.-]*@)?[a-zA-Z0-9][a-zA-Z0-9_.-]*$/.test(target);
    el('ai-ssh-target').setCustomValidity(valid ? '' : 'Use an SSH host alias or user@host, without options or spaces.');
    el('ai-copy-stdio').disabled = !valid;
    if (target && valid) {
      // SSH joins remote arguments into a shell command, so quote every server path.
      const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";
      const client = state.stdio.mcpServers.kakaotalk;
      const remote = [client.command, ...client.args].map(quote).join(' ');
      config = {mcpServers: {kakaotalk: {command: 'ssh', args: ['-T', '-o', 'BatchMode=yes', target, remote]}}};
    }
    el('ai-stdio-config').textContent = valid ? JSON.stringify(config, null, 2) : 'Enter a valid SSH destination.';
  }

  function renderJob() {
    const job = state?.job || {};
    el('ai-job').hidden = !job.state || job.state === 'idle' || (job.state === 'ready' && job.method !== 'check' && job.method !== el('ai-method').value);
    el('ai-job').dataset.state = job.state || 'idle';
    el('ai-job-title').textContent = {running: 'Setting up your connection…', ready: 'Server setup complete',
      failed: 'Setup needs attention', interrupted: 'Setup was interrupted', action_required: 'Your approval is needed'}[job.state] || '';
    if (job.method === 'check' && job.state === 'ready') el('ai-job-title').textContent = 'Server check complete';
    if (job.method === 'check' && job.state === 'running') el('ai-job-title').textContent = 'Checking server services…';
    if (['none', 'stdio'].includes(job.method) && job.state === 'ready') el('ai-job-title').textContent = 'Choice saved';
    el('ai-job-message').textContent = job.message || '';
    const elapsed = job.started_at ? Math.max(0, Math.floor(Date.now() / 1000 - job.started_at)) : 0;
    el('ai-job-time').textContent = job.state === 'running' ? `${Math.floor(elapsed / 60)}m ${elapsed % 60}s elapsed · You can leave this page and return.` : '';
    el('ai-retry').hidden = !['failed', 'interrupted'].includes(job.state);
    el('ai-retry').textContent = job.method === 'check' ? 'Check again' : 'Review and retry';
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
        ? 'This tunnel is configured but access is not allowed. Review and allow it in AI connections above before adding it to ChatGPT.'
        : guide.kind === 'tunnel'
        ? 'Bridge has allowed this personal tunnel. Complete these steps in ChatGPT to use it.'
        : 'Keep this admin page open while you add the connection in your AI client.';
      el('ai-client-label').textContent = guide.kind === 'tunnel' ? 'Tunnel ID' : 'MCP server URL';
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
      el('ai-agent-status').textContent = state.available ? 'Choose where you will use your messages. Existing connections stay available.' : state.message;
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
      if (isActive() && currentEpoch === epoch) el('ai-agent-status').textContent = 'Reconnecting to setup status… Your server keeps running the job. Sign in again if requested.';
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
        el('ai-form-error').textContent = 'Enter your HTTPS address, such as https://bridge.example.com or https://bridge.example.com/mcp.';
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
    try { await navigator.clipboard.writeText(el(id).textContent); feedback('Copied.'); }
    catch { feedback('Copy is unavailable in this browser. Select and copy the displayed text.'); }
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
