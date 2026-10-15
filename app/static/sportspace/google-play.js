// Android uses Play Games' native SDK. Browser accounts approve each sync explicitly.
const playPreviousRender=render,playPreviousNavigate=navigate;
const playState={owner:null,request:0,loading:false,busy:false,error:'',settings:null,status:null,challenge:'',ticket:''};
function playOwner(){
  if(playState.owner===account.userId)return;
  ++playState.request;playState.owner=account.userId;playState.settings=null;playState.status=null;
  playState.error='';playState.loading=false;playState.busy=false;playState.ticket='';
}
async function playRequest(path,body){
  const response=await fetch('/api/play-games/'+path,{method:body?'POST':'GET',cache:'no-store',
    headers:{'Content-Type':'application/json','X-Dhoyo-Request':'1'},
    body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(15000)});
  const result=await response.json().catch(()=>null);
  if(!response.ok)throw new Error(result?.error||'Google Play information could not be loaded. Try again.');
  if(!result||typeof result!=='object')throw new Error('Google Play returned incomplete information. Try again.');
  return result;
}
async function playLoad(){
  await accountReady;playOwner();
  if(view!=='google-play'||!account.userId)return;
  const owner=account.userId,request=++playState.request;
  playState.loading=true;playState.error='';render();
  try{
    const [settings,status]=await Promise.all([playRequest('config'),playRequest('status')]);
    if(request!==playState.request||owner!==account.userId||view!=='google-play')return;
    if(status.currentUserId!==owner)throw new Error('Your account changed. Refresh this page.');
    playState.settings=settings;playState.status=status;
  }catch(error){if(request===playState.request&&owner===account.userId){playState.error=error.message;playState.settings=null;playState.status=null;}}
  finally{if(request===playState.request&&owner===account.userId){playState.loading=false;if(view==='google-play')render();}}
}
function playStoreLink(value){
  try{
    const url=new URL(value);
    return url.protocol==='https:'&&url.hostname==='play.google.com'&&!url.username&&!url.password&&url.pathname==='/store/apps/details'&&/^[a-zA-Z][\w]*(\.[a-zA-Z][\w]*)+$/.test(url.searchParams.get('id')||'')?url.href:'';
  }catch{return '';}
}
function playConsent(){
  if(!playState.challenge)return '';
  if(account.accountType==='organisation')return '<section class="play-consent"><h2>Connect a player account</h2><p>Google Play Games connects a player’s gaming profile. Sign in with your player account to continue.</p></section>';
  if(!playState.settings?.playGamesEnabled)return '<section class="play-consent"><h2>Connection is not available yet</h2><p>The Google Play Games setup must be completed before your Android app can sync.</p></section>';
  if(playState.ticket)return `<section class="play-consent"><h2>Return to Dhoyo for Android</h2><p>Continue in the Android app you used to start this connection. This approval expires in five minutes.</p><a class="primary play-action" href="dhoyo://play-games?ticket=${encodeURIComponent(playState.ticket)}" rel="noreferrer">Continue in Android app ↗</a><p class="play-note">The app will ask Google to verify your Play Games profile before connecting it. No Google password is shared with Dhoyo.</p></section>`;
  return `<section class="play-consent"><span class="play-kicker">APPROVE AND CONTINUE</span><h2>Connect your Google Play Games profile</h2><p>You are signed in as <strong>${escape(account.name||'a Dhoyo player')}</strong>. Approve only if you started this request in Dhoyo for Android.</p><p>Your earned tournament milestones and completed tournament count will be shared with Google Play Games. Your phone number, email and team roster stay private.</p><button type="button" class="primary play-action" data-play-approve ${playState.busy?'disabled':''}>${playState.busy?'Preparing your connection…':'Approve & continue in Android'}</button><a class="play-cancel" href="#google-play">Cancel</a></section>`;
}
function playCards(){
  const settings=playState.settings,status=playState.status,store=playStoreLink(settings?.storeUrl);
  if(!settings||!status)return '';
  const connected=status.linked===true;
  let lastSync='';
  if(status.lastSyncedAt){const date=new Date(status.lastSyncedAt);if(Number.isFinite(date.getTime()))lastSync=date.toLocaleString();}
  return `${playConsent()}<div class="play-cards"><section class="play-card"><span class="play-kicker">GOOGLE PLAY STORE</span><span class="play-status ${store?'is-ready':''}">${store?'Available on Google Play':'Not published yet'}</span><h2>Dhoyo for Android</h2><p>Use your Dhoyo website account to find tournaments, manage your team and keep up with reminders from your Android phone.</p>${store?`<a class="primary play-action" href="${escape(store)}" target="_blank" rel="noopener noreferrer">Get the Android app ↗</a>`:'<p class="play-note">A Google Play download link will appear here after the Android app is published.</p>'}</section><section class="play-card"><span class="play-kicker">GOOGLE PLAY GAMES</span><span class="play-status ${connected?'is-ready':''}">${connected?'Connected':settings.playGamesEnabled?'Ready to connect':'Setup pending'}</span><h2>Your Play Games profile</h2><p>${connected?'Your Dhoyo player account is linked to a verified Google Play Games profile.':settings.playGamesEnabled?'Connect from Dhoyo for Android to sync your earned achievements with Google.':'Google Play Games is not enabled for this service yet. Website badges and seasonal rankings remain available in Dhoyo.'}</p>${lastSync?`<p class="play-note">Last completed sync: ${escape(lastSync)}</p>`:''}${settings.playGamesEnabled&&account.accountType!=='organisation'&&!playState.challenge?'<p class="play-note">Open Dhoyo for Android and choose “Connect & sync with Dhoyo.” Google Play Games achievements and leaderboards open inside the Android app.</p>':''}<a class="play-text-link" href="#progress">View Dhoyo achievements & seasonal rankings ↗</a><p class="play-note">When enabled, the Play Games leaderboard counts lifetime completed tournaments. Dhoyo’s seasonal rankings use their own season rules.</p></section></div>`;
}
render=function(){
  playOwner();
  if(view!=='google-play'){playPreviousRender();return;}
  document.body.classList.add('ring-experience','google-play-view');
  document.body.classList.remove('ring-home','arena-view','org-service-view','progression-view','reminders-view');
  if(typeof orgAccountChrome==='function')orgAccountChrome();
  $('.page-heading').hidden=false;$('#eyebrow').textContent='DHOYO FOR ANDROID';$('#title').textContent='Your Google Play connection.';
  $('#subtitle').textContent='The Android app, your Play Games profile and your Dhoyo account.';
  $('#create').hidden=true;$('#filters').hidden=true;$('#filters').innerHTML='';
  $('#search').disabled=true;$('#search').placeholder='Google Play';$('#search').setAttribute('aria-label','Google Play');
  document.querySelectorAll('.sidebar nav button').forEach(button=>{const active=button.dataset.playRoute==='google-play';button.classList.toggle('active',active);button.setAttribute('aria-current',active?'page':'false');});
  let content=playState.loading?'<p class="play-note" role="status">Checking your Google Play connection…</p>':playState.error?`<p class="play-error" role="alert">${escape(playState.error)}</p>`:playCards();
  if(!account.userId)content='<p class="play-note">Sign in to view your Google Play connection.</p>';
  $('#content').innerHTML=`<div class="play-toolbar"><a href="#progress">Achievements & rankings</a><a href="#reminders">Tournament reminders</a><button type="button" class="org-button" data-play-refresh ${playState.loading||playState.busy?'disabled':''}>Refresh connection</button></div><div class="play-page">${content}</div>`;
};
navigate=function(next){
  if((next||'').split('/')[0]!=='google-play'){
    ++playState.request;playState.ticket='';playState.busy=false;playState.loading=false;document.body.classList.remove('google-play-view');playPreviousNavigate(next);return;
  }
  const parts=(next||'').split('/');
  if(typeof remindersStop==='function')remindersStop();
  playState.challenge=parts.length===3&&parts[1]==='connect'&&/^[A-Za-z0-9_-]{43}$/.test(parts[2])?parts[2]:'';
  playState.ticket='';view='google-play';query='';filter='All sports';$('#search').value='';playOwner();render();playLoad();
};
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-play-route],[data-play-refresh],[data-play-approve]');
  if(!button)return;
  event.preventDefault();
  if(button.dataset.playRoute){location.hash=button.dataset.playRoute;return;}
  if(button.hasAttribute('data-play-refresh')){if(!playState.loading&&!playState.busy)playLoad();return;}
  if(view!=='google-play'||playState.busy||playState.owner!==account.userId||!playState.settings?.playGamesEnabled||!playState.challenge||account.accountType==='organisation')return;
  const owner=account.userId,request=++playState.request;
  playState.busy=true;playState.error='';render();
  try{
    const result=await playRequest('tickets',{challenge:playState.challenge});
    if(request!==playState.request||owner!==account.userId||view!=='google-play')return;
    if(result.currentUserId!==owner)throw new Error('Your account changed. Refresh this page before approving the connection.');
    if(!/^[A-Za-z0-9_-]{43}$/.test(result.ticket||''))throw new Error('Could not prepare your Android connection. Start again from the app.');
    playState.ticket=result.ticket;
  }catch(error){if(request===playState.request&&owner===account.userId)playState.error=error.message;}
  finally{if(request===playState.request&&owner===account.userId){playState.busy=false;if(view==='google-play')render();}}
});
accountReady.then(()=>{if(view!=='google-play'&&location.hash.slice(1).split('/')[0]==='google-play')navigate(location.hash.slice(1));});
