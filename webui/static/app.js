'use strict';
const $ = id => document.getElementById(id);
let csrf = '', active = false, paused = false, fetching = false, rendering = false, frame = null, pointer = null, blobURL = null, busy = false;
const messages = {session_required:'관리자 인증이 만료됐습니다.',device_busy:'기기 작업 중입니다. 잠시 후 다시 시도하세요.',invalid_request:'입력 형식을 확인하세요.',invalid_csrf:'관리 화면을 새로 열어주세요.',invalid_origin:'같은 HTTPS 주소에서 관리 화면을 열어주세요.'};
function feedback(message) { $('feedback').textContent = message; $('feedback').hidden = false; clearTimeout(feedback.timer); feedback.timer = setTimeout(() => {$('feedback').hidden = true;}, 6500); }
function locked() { active=false; csrf=''; frame=null; $('console').hidden=true; $('login-panel').hidden=false; $('logout').hidden=true; $('connection').textContent='관리자 인증 필요'; $('screen').hidden=true; $('screen').removeAttribute('src'); $('device-text').value=''; $('phone-active').checked=false; $('tablet-active').checked=false; if(blobURL) URL.revokeObjectURL(blobURL); blobURL=null; }
async function api(path, data) {
  const response = await fetch('/admin/api/'+path, {method:data === undefined?'GET':'POST', credentials:'same-origin', cache:'no-store', headers:data === undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:data === undefined?undefined:JSON.stringify(data)});
  if (!response.ok) { let reason='요청에 실패했습니다.'; try { const error=await response.json(); reason=messages[error.detail]||error.detail||reason; } catch {} if(response.status===401) locked(); throw new Error(typeof reason==='string'?reason:'요청에 실패했습니다.'); }
  return response.json();
}
function unlocked(session) {csrf=session.csrf;active=true;paused=false;$('login-panel').hidden=true;$('console').hidden=false;$('logout').hidden=false;$('connection').textContent='관리자 연결됨 · 30분 세션';updateState();refresh();}
$('login-form').addEventListener('submit',async event=>{event.preventDefault();const token=$('admin-token').value;$('admin-token').value='';try{unlocked(await api('login',{token}));}catch(error){feedback(error.message);}});
$('logout').addEventListener('click',async()=>{try{await api('logout',{});locked();}catch(error){feedback(error.message);}});
async function refresh(force=false) {
  if(!active||fetching||pointer||busy||document.hidden||(!force&&paused))return;
  fetching=true;
  try {
    const response=await fetch('/admin/api/screen',{credentials:'same-origin',cache:'no-store'});
    if(response.status===401){locked();return;} if(response.status===409)return;
    if(!response.ok)throw new Error('화면 연결을 기다리고 있습니다. redroid가 실행 중인지 확인하세요.');
    const next={id:response.headers.get('X-Frame-Id'),width:Number(response.headers.get('X-Screen-Width')),height:Number(response.headers.get('X-Screen-Height'))};
    const url=URL.createObjectURL(await response.blob()); if(!active||pointer||(!force&&paused)){URL.revokeObjectURL(url);return;}
    const previous=blobURL;rendering=true;$('screen').src=url;await $('screen').decode();frame=next;blobURL=url;
    if(previous)URL.revokeObjectURL(previous);$('screen').hidden=false;$('screen-placeholder').hidden=true;$('screen-dot').classList.add('active');$('screen-label').textContent=paused?'화면 일시정지':`${next.width} × ${next.height} · 연결됨`;
  }catch(error){frame=null;$('screen-dot').classList.remove('active');$('screen-label').textContent='화면 연결 대기';$('screen-placeholder').hidden=false;$('screen').hidden=true;}
  finally{fetching=false;rendering=false;}
}
const localTime = value => value ? new Date(value * 1000).toLocaleString('ko-KR') : '기록 없음';
function renderSessions(s, stale) {
  const fresh=!!s&&!stale;
  $('session-inspected').textContent=s?`검사: ${localTime(s.checked_at)}${fresh?'':' · 현재 상태를 다시 검사하세요.'}`:'아직 검사하지 않았습니다.';
  const screen=s?.screen?.state;
  const screens={login_required:'로그인 화면 감지',main_screen_observed:'로그인 후 화면 관찰',not_visible:'카카오톡이 화면에 없음',not_installed:'카카오톡 미설치',unknown:'화면으로 판별할 수 없음'};
  $('tablet-status').textContent=fresh?(s.device==='offline'?'redroid 연결 끊김':s.device==='booting'?'redroid 부팅 중':screens[screen]||'로그인 여부 미확인'):'로그인 여부 재검사 필요';
  $('tablet-detail').textContent=`redroid 직접 확인: ${localTime(s?.tablet?.confirmed_at)}. ${screen==='login_required'?'로그인 전 보조 기기 옵션을 확인하세요.':'현재 인증 상태는 기기 화면에서도 확인하세요.'}`;
  const phone=s?.phone;
  const overdue=phone?.confirmed_at && Date.now()/1000-phone.confirmed_at>86400;
  const phoneLabels={operator_confirmed:'유지됨 · 사용자 직접 확인',recheck_due:'핸드폰 재확인 필요',reported_lost:'로그아웃됨 · 사용자 보고',unknown:'핸드폰 상태 미확인'};
  $('phone-status').textContent=fresh?(phoneLabels[overdue&&phone?.state==='operator_confirmed'?'recheck_due':phone?.state]||phoneLabels.unknown):'핸드폰 확인 기록 재조회 필요';
  $('phone-detail').textContent=`마지막 유지 확인: ${localTime(phone?.confirmed_at)}${phone?.state==='reported_lost'?` / 로그아웃 보고: ${localTime(phone.reported_at)}`:''}. 자동 감시 결과가 아닙니다.`;
  $('approval-status').textContent=fresh?({approved:'Iris 수집 승인됨',locked:'Iris 수집 잠김',unknown:'수집 승인 상태 미확인'}[s.collection_approval]||'수집 승인 상태 미확인'):'수집 승인 상태 재검사 필요';
  const proof=s?.precheck;
  const proofValid=proof?.state==='valid' && proof.expires_at>Date.now()/1000;
  $('approval-detail').textContent=proofValid?`보조 옵션 사전 검사 통과 · ${localTime(proof.expires_at)}까지 양쪽 확인을 완료하세요.`:s?.collection_approval==='approved'?'앱 버전·기기와 보조 로그인 승인 기록이 일치합니다.':'유효한 사전 검사와 양쪽 세션 확인이 필요합니다.';
  $('phone-recheck').dataset.approved=String(fresh&&s.collection_approval==='approved');
}
async function updateState(){if(!active||document.hidden)return;try{const state=await api('state');if(!active)return;busy=state.job.state==='running';$('job').textContent=state.job.message||'작업 대기 중';$('collector-status').textContent=state.collector.state==='collecting_partial'?'Iris 수집 중 · 부분 수집':state.collector.state==='unavailable'?'수집 서버 연결 대기':'수집 잠김 또는 확인 필요';renderSessions(state.sessions,state.sessions_stale);document.querySelectorAll('[data-action]').forEach(button=>button.disabled=busy);updateConfirm();}catch(error){if(active){$('collector-status').textContent='상태 확인 실패';renderSessions(null,true);updateConfirm();}}}
async function action(name, extra={}){try{await api('action',{name,...extra});busy=true;await updateState();}catch(error){feedback(error.message);}}
document.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',()=>action(button.dataset.action)));
function updateConfirm(){$('confirm').disabled=busy||!$('phone-active').checked||!$('tablet-active').checked;$('phone-recheck').disabled=busy||!$('phone-active').checked||$('phone-recheck').dataset.approved!=='true';}
['phone-active','tablet-active'].forEach(id=>$(id).addEventListener('change',updateConfirm));
$('confirm').addEventListener('click',()=>{action('confirm-secondary',{phone_active:$('phone-active').checked,tablet_active:$('tablet-active').checked});$('phone-active').checked=false;$('tablet-active').checked=false;updateConfirm();});
$('phone-recheck').addEventListener('click',()=>{action('phone-active',{phone_active:$('phone-active').checked});$('phone-active').checked=false;updateConfirm();});
$('show-text').addEventListener('change',()=>{$('device-text').type=$('show-text').checked?'text':'password';});
$('text-form').addEventListener('submit',async event=>{event.preventDefault();if(!active||busy)return;const text=$('device-text').value;$('device-text').value='';try{await api('text',{text});feedback('선택한 입력칸에 입력했습니다.');await refresh(true);}catch(error){feedback(error.message);}});
document.querySelectorAll('[data-key]').forEach(button=>button.addEventListener('click',async()=>{try{await api('key',{name:button.dataset.key});await refresh(true);}catch(error){feedback(error.message);}}));
function coordinates(event,f){const r=$('screen').getBoundingClientRect();const border=5;return {x:Math.max(0,Math.min(f.width-1,Math.floor((event.clientX-r.left-border)/(r.width-2*border)*f.width))),y:Math.max(0,Math.min(f.height-1,Math.floor((event.clientY-r.top-border)/(r.height-2*border)*f.height)))};}
$('screen').addEventListener('pointerdown',event=>{if(!frame||rendering||paused||busy||event.button!==0)return;pointer={...coordinates(event,frame),frame:{...frame},time:performance.now(),id:event.pointerId};$('screen').setPointerCapture(event.pointerId);event.preventDefault();});
$('screen').addEventListener('pointerup',async event=>{const start=pointer;pointer=null;if(!start||start.id!==event.pointerId)return;const end=coordinates(event,start.frame);const data={frame:start.frame.id,x:start.x,y:start.y};if(Math.hypot(end.x-start.x,end.y-start.y)>12||performance.now()-start.time>550)Object.assign(data,{end_x:end.x,end_y:end.y,duration:Math.max(100,Math.min(2000,Math.round(performance.now()-start.time)))});try{await api('pointer',data);await refresh(true);}catch(error){feedback(error.message);}});
$('screen').addEventListener('pointercancel',()=>{pointer=null;});
$('refresh').addEventListener('click',()=>refresh(true));
$('pause').addEventListener('click',()=>{paused=!paused;frame=null;$('pause').textContent=paused?'화면 다시 연결':'화면 일시정지';$('screen-label').textContent=paused?'화면 일시정지':'화면 연결 중';if(!paused)refresh();});
document.addEventListener('visibilitychange',()=>{frame=null;if(!document.hidden){refresh();updateState();}});
setInterval(()=>refresh(),1200);setInterval(updateState,3000);
api('session').then(unlocked).catch(()=>locked());
