// Tournament milestones use the signed-in account and server-owned event history.
const progressPreviousRender=render,progressPreviousNavigate=navigate;
const playerProgress={owner:null,request:0,loading:false,error:'',me:null,board:null,season:'',sport:'All sports'};
function progressReset(){
  ++playerProgress.request;
  playerProgress.owner=account.userId;
  playerProgress.loading=false;playerProgress.error='';playerProgress.me=null;playerProgress.board=null;
  playerProgress.season='';playerProgress.sport='All sports';
}
function progressOwner(){if(playerProgress.owner!==account.userId)progressReset();}
async function progressRequest(path){
  const response=await fetch('/api/progression/'+path,{headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(15000)});
  const result=await response.json().catch(()=>null);
  if(!response.ok)throw new Error(result?.error||'Your progress could not be loaded. Try again.');
  if(!result||typeof result!=='object')throw new Error('The progress service returned an unexpected response. Try again.');
  return result;
}
async function progressLoad(){
  await accountReady;
  progressOwner();
  if(view!=='progress'||!account.userId)return;
  const owner=account.userId,request=++playerProgress.request;
  playerProgress.loading=true;playerProgress.error='';render();
  const params=new URLSearchParams();
  if(playerProgress.season)params.set('season',playerProgress.season);
  params.set('sport',playerProgress.sport);
  try{
    const [me,board]=await Promise.all([
      account.accountType==='organisation'?Promise.resolve(null):progressRequest('me'),
      progressRequest('leaderboard?'+params.toString())
    ]);
    if(request!==playerProgress.request||account.userId!==owner||view!=='progress')return;
    if(board.currentUserId!==owner||(me&&me.playerId!==owner))throw new Error('Your account changed. Refresh to load your progress.');
    if(!Array.isArray(board.players)||!Array.isArray(board.seasons)||(me&&!Array.isArray(me.achievements)))throw new Error('The progress service returned incomplete information. Try again.');
    playerProgress.me=me;playerProgress.board=board;playerProgress.season=board.season.id;
  }catch(error){
    if(request===playerProgress.request&&account.userId===owner&&view==='progress'){
      playerProgress.error=error.message||'Could not reach your progress. Try again.';
      playerProgress.me=null;playerProgress.board=null;
    }
  }finally{
    if(request===playerProgress.request&&account.userId===owner&&view==='progress'){playerProgress.loading=false;render();}
  }
}
function progressNumber(value){return Number.isSafeInteger(value)&&value>=0?value:0;}
function progressDate(value){
  try{return new Intl.DateTimeFormat('en-IN',{dateStyle:'medium'}).format(new Date(value));}
  catch{return '';}
}
function progressAvatar(player){
  const avatar=typeof player.avatar==='string'?player.avatar:'';
  const safe=/^https?:\/\/[^\s]+$/i.test(avatar)||/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(avatar);
  return safe?`<img class="progress-avatar" src="${escape(avatar)}" alt="" loading="lazy" referrerpolicy="no-referrer">`:`<span class="progress-avatar" aria-hidden="true">${escape(player.initials||'P')}</span>`;
}
function progressBadgeCard(badge){
  const count=progressNumber(badge.progress),target=Math.max(1,progressNumber(badge.target));
  const percent=Math.round(Math.min(count,target)/target*100);
  return `<article class="progress-badge ${badge.unlocked?'is-earned':''}"><span class="progress-badge-mark" aria-hidden="true">${icon(badge.unlocked?'medal':'star')}</span><div><span class="progress-kicker">${badge.unlocked?'UNLOCKED':'NEXT MILESTONE'}</span><h3>${escape(badge.name)}</h3><p>${escape(badge.description)}</p><div class="progress-meter" role="progressbar" aria-label="${escape(badge.name)}" aria-valuenow="${Math.min(count,target)}" aria-valuemin="0" aria-valuemax="${target}"><span style="width:${percent}%"></span></div><small>${badge.unlocked?`Earned ${escape(progressDate(badge.earnedAt))}`:`${count} / ${target}`}</small></div></article>`;
}
function progressMilestones(){
  const me=playerProgress.me;
  if(!me)return `<div class="progress-note"><h2>Milestones for your players</h2><p>Players earn badges from confirmed registrations and tournaments your organisation completes. Explore the season below.</p></div>`;
  return `<section aria-label="Your tournament achievements"><div class="progress-section-heading"><div><span class="progress-kicker">EARNED THROUGH PLAY</span><h2>Your achievements</h2></div><a href="#tournaments">Find a tournament ↗</a></div><div class="progress-stats"><div><strong>${progressNumber(me.stats?.registeredTournaments)}</strong><span>Tournaments registered</span></div><div><strong>${progressNumber(me.stats?.completedTournaments)}</strong><span>Tournaments completed</span></div><div><strong>${me.achievements.filter(badge=>badge.unlocked).length} / ${me.achievements.length}</strong><span>Badges earned</span></div></div><div class="progress-badges">${me.achievements.map(progressBadgeCard).join('')}</div><p class="progress-help">Badges follow your confirmed team roster. Completion means the organiser marked the tournament completed; it does not certify a match result or win.</p></section>`;
}
function progressLeaderboard(){
  const board=playerProgress.board;
  if(!board)return '';
  const seasons=board.seasons.some(season=>season.id===board.season.id)?board.seasons:[board.season,...board.seasons];
  const rows=board.players.map(player=>`<tr class="${player.playerId===account.userId?'is-you':''}"><td class="progress-rank">${progressNumber(player.rank)}</td><th scope="row"><a class="progress-player" href="#player/${encodeURIComponent(player.playerId)}">${progressAvatar(player)}<span>${escape(player.name)}${player.playerId===account.userId?'<small>You</small>':''}</span></a></th><td>${progressNumber(player.completedTournaments)}</td><td>${progressNumber(player.registeredTournaments)}</td></tr>`).join('');
  return `<section class="progress-season" aria-labelledby="progress-season-heading"><div class="progress-section-heading"><div><span class="progress-kicker">A NEW SEASON. MORE REASONS TO PLAY.</span><h2 id="progress-season-heading">Seasonal rankings</h2><p>${escape(board.season.label)}${board.myRank?` · Your rank: ${progressNumber(board.myRank)}`:''}</p></div><div class="progress-controls"><label>Season<select data-progress-season>${seasons.map(season=>`<option value="${escape(season.id)}" ${season.id===board.season.id?'selected':''}>${escape(season.label)}</option>`).join('')}</select></label><label>Sport<select data-progress-sport>${['All sports',...(board.sports||[])].map(sport=>`<option value="${escape(sport)}" ${sport===board.sport?'selected':''}>${escape(sport)}</option>`).join('')}</select></label></div></div><p class="progress-help">${escape(board.rankingRule)} Seasons use the tournament start date in UTC. Cancelled entries do not count.</p>${rows?`<div class="progress-table-wrap"><table class="progress-table"><caption class="sr-only">Tournament participation rankings for ${escape(board.season.label)}</caption><thead><tr><th scope="col">Rank</th><th scope="col">Player</th><th scope="col">Completed</th><th scope="col">Registered</th></tr></thead><tbody>${rows}</tbody></table></div><p class="progress-help">${progressNumber(board.totalPlayers)>board.players.length?`Showing the first ${board.players.length} of ${progressNumber(board.totalPlayers)} players.`:`${progressNumber(board.totalPlayers)} player${board.totalPlayers===1?'':'s'} this season.`}</p>`:'<div class="progress-empty"><h3>The season is yours to start.</h3><p>Confirmed tournament registrations will appear here. Get your team together and take the first step.</p><a href="#tournaments">Explore tournaments ↗</a></div>'}</section>`;
}
render=function(){
  progressOwner();
  if(view!=='progress'){progressPreviousRender();return;}
  document.body.classList.add('ring-experience','progression-view');
  document.body.classList.remove('ring-home','arena-view','org-service-view');
  if(typeof orgAccountChrome==='function')orgAccountChrome();
  $('.page-heading').hidden=false;$('#eyebrow').textContent='YOUR PROGRESS';$('#title').textContent='Every tournament counts.';
  $('#subtitle').textContent='Earn milestones with your team. Show up for a fresh season.';
  $('#create').hidden=true;$('#filters').hidden=true;$('#filters').innerHTML='';
  $('#search').disabled=true;$('#search').placeholder='Your tournament progress';$('#search').setAttribute('aria-label','Your tournament progress');
  document.querySelectorAll('.sidebar nav button').forEach(button=>{const active=(button.dataset.progressRoute||button.dataset.view)==='progress';button.classList.toggle('active',active);button.setAttribute('aria-current',active?'page':'false');});
  document.querySelectorAll('[data-bottom-route]').forEach(link=>{const active=link.dataset.bottomRoute==='progress';link.classList.toggle('active',active);if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
  let content;
  if(!account.userId)content='<p class="progress-note" role="status">Sign in to see your achievements and seasonal rankings.</p>';
  else if(playerProgress.loading)content='<p class="progress-note" role="status">Loading your achievements and season…</p>';
  else if(playerProgress.error)content=`<div class="progress-note" role="alert"><p>${escape(playerProgress.error)}</p><button class="org-button" data-progress-refresh>Try again</button></div>`;
  else content=progressMilestones()+progressLeaderboard();
  $('#content').innerHTML=`<div class="progress-toolbar"><a href="#tournaments">${icon('trophy')} Tournaments</a><a href="#reminders">Reminders</a><a href="#google-play">Google Play</a><button class="org-button" data-progress-refresh ${playerProgress.loading?'disabled':''}>Refresh progress</button></div><div class="progress-page">${content}</div>`;
};
navigate=function(next){
  if((next||'').split('/')[0]!=='progress'){
    ++playerProgress.request;playerProgress.loading=false;document.body.classList.remove('progression-view');progressPreviousNavigate(next);return;
  }
  view='progress';query='';filter='All sports';$('#search').value='';progressOwner();render();progressLoad();
};
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-progress-refresh],[data-progress-route]');
  if(!button)return;
  event.preventDefault();
  if(button.dataset.progressRoute){location.hash=button.dataset.progressRoute;if(view==='progress')progressLoad();}
  else if(!playerProgress.loading)progressLoad();
});
document.addEventListener('change',event=>{
  if(view!=='progress'||playerProgress.loading)return;
  if(event.target.matches('[data-progress-season]')){playerProgress.season=event.target.value;progressLoad();}
  else if(event.target.matches('[data-progress-sport]')){playerProgress.sport=event.target.value;progressLoad();}
});
accountReady.then(()=>{progressOwner();if(view!=='progress'&&location.hash.slice(1).split('/')[0]==='progress')navigate(location.hash.slice(1));});
