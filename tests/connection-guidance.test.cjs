const {test} = require('node:test');
const assert = require('node:assert/strict');
const {connectionGuidance, connectionDestination} = require('../webui/static/connection-setup.js');

test('saved connection instructions survive checks, failures and selecting later', () => {
  for (const job of [{state:'idle'}, {method:'check',state:'ready'}, {method:'check',state:'failed'}, {method:'none',state:'ready'}]) {
    const state = {job, tunnel_configured:true, tunnel_id:'tunnel_saved', mcp_url:'https://bridge.test/mcp'};
    assert.deepEqual(connectionGuidance(state,'openai-tunnel'), {kind:'tunnel',value:'tunnel_saved'});
    assert.deepEqual(connectionGuidance(state,'https'), {kind:'https',value:'https://bridge.test/mcp'});
    assert.deepEqual(connectionGuidance(state,'tailscale'), {kind:'https',value:'https://bridge.test/mcp'});
  }
});

test('a successful job alone never invents a configured connection', () => {
  const state = {job:{state:'ready',method:'openai-tunnel'},tunnel_configured:false,tunnel_id:'old'};
  assert.equal(connectionGuidance(state,'openai-tunnel'),null);
  assert.equal(connectionGuidance(state,'https'),null);
  assert.equal(connectionGuidance(null,'https'),null);
});

test('saved choices map back to user purposes', () => {
  assert.equal(connectionDestination('openai-tunnel'),'chatgpt');
  assert.equal(connectionDestination('stdio'),'desktop');
  assert.equal(connectionDestination('https'),'remote');
  assert.equal(connectionDestination('none'),'none');
});
