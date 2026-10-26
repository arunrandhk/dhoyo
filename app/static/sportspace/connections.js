// Extend the existing Ring graph across squads, profiles, communities and the feed.
const connectionsBaseRender=render, connectionsBaseNavigate=navigate;
const connectionsBaseGraph=networkHTML, connectionsBasePost=postHTML, connectionsBaseCommunity=communityPage;
const connectionNumber=value=>Number(value||0).toFixed(2);
const connectionLink=(kind,id)=>kind==='community'?'#community/'+encodeURIComponent(id)+'/squads':'#player/'+encodeURIComponent(kind==='team'?(arena.data?.teams.find(t=>t.id===id)?.ownerId||arena.data?.currentUserId||'demo-user'):id)+'/moments';
const connectionRules=()=>arena.data?.influenceRules||{tierPoints:{Star:4,Diamond:3,Gold:2,Silver:1},supportCap:1,memberFactor:0.2,memberCap:1,supportersPerPoint:5};
let connectionsAppliedRoute=null;

function chooseConnection(kind,id){
  if(kind==='community'){network.communityId=id;network.playerId=null;network.teamId=null;return;}
  const player=kind==='player'?arenaPlayer(id):null;
  const source=[...(player?.influenceSources||[])].sort((a,b)=>b.boost-a.boost)[0];
  const team=kind==='team'?arena.data.teams.find(t=>t.id===id):arena.data.teams.find(t=>t.ownerId===id)||arena.data.teams.find(t=>t.id===source?.teamId);
  const sport=team?.sport||player?.sport, city=team?.city||player?.city;
  network.communityId=communities().find(c=>c.sport===sport&&(c.city==='Online'||c.city===city))?.id||communities().find(c=>c.sport===sport)?.id||null;
  network.playerId=team?.ownerId||player?.id||null;network.teamId=team?.id||null;
}

function squadInfluenceHTML(team){
  const captain=arenaPlayer(team.ownerId), influence=team.influence;if(!captain||!influence)return '';
  const me=arena.data.currentUserId;
  const status=team.ownerId===me?'You lead this squad':team.members.includes(me)?'Your membership is active':team.requests.some(r=>r.playerId===me&&r.status==='pending')?'Your request is pending — no boost yet':'Visibility begins after captain approval';
  return `<div class="squad-influence"><div><small>CAPTAIN CONNECTION</small><a href="${connectionLink('team',team.id)}">${escape(captain.name)} ${rankBadge(captain.rank)}</a></div><strong>+${connectionNumber(influence.memberBoost)}<small>feed ranking / accepted member</small></strong><p>${escape(status)}. Each player's own awards stay theirs.</p><a href="${connectionLink('team',team.id)}">Explore this squad's circle →</a></div>`;
}

function connectionBreakdown(team){
  const captain=arenaPlayer(team.ownerId), value=team.influence, rules=connectionRules();if(!captain||!value)return '';
  const pending=team.requests.filter(r=>r.status==='pending');
  return `<section class="connection-impact" aria-label="${escape(team.name)} influence breakdown"><div class="connection-section-heading"><div><span class="eyebrow">RECOGNITION → CONNECTION → DISCOVERY</span><h3>${escape(captain.name)} → ${escape(team.name)}</h3><p>See what this direct connection contributes to accepted members' matching-sport posts.</p></div><a href="#player/${encodeURIComponent(captain.id)}">View player →</a></div>
    <div class="connection-equation"><div><strong>${connectionNumber(value.tierPoints)}</strong><span>${escape(value.sourceRank||'No award tier')}</span><small>Captain's award influence</small></div><span aria-hidden="true">+</span><div><strong>${connectionNumber(value.supportPoints)}</strong><span>${captain.communityStars} supporters</span><small>Support capped at ${connectionNumber(rules.supportCap)}</small></div><span aria-hidden="true">=</span><div><strong>${connectionNumber(value.score)}</strong><span>Captain influence</span><small>Own recognition + support</small></div><span aria-hidden="true">→</span><div class="connection-result"><strong>+${connectionNumber(value.memberBoost)}</strong><span>Per accepted member</span><small>${Math.round(rules.memberFactor*100)}% share · cap +${connectionNumber(rules.memberCap)}</small></div></div>
    <div class="connection-status"><span><b>${value.acceptedMemberCount}</b> accepted members can benefit</span><span><b>${pending.length}</b> pending requests receive +0.00</span><span><b>${Math.max(0,team.capacity-team.members.length)}</b> open places</span></div>
    ${pending.length?`<div class="connection-pending"><strong>Waiting for captain approval</strong>${pending.map(r=>`<a href="#player/${encodeURIComponent(r.playerId)}">${escape(arenaPlayer(r.playerId)?.name||'Player')} <span>Pending / +0.00</span></a>`).join('')}</div>`:''}
    <div class="connection-actions">${teamJoin(team)}<a href="#teams">${team.ownerId===arena.data.currentUserId?'Manage members and requests':'Browse squads'} →</a></div>
    <p class="connection-note">Applies to ${escape(team.sport)} posts in Global, Country and State. Following and award standings keep their own ordering. Other feed signals still matter.</p></section>`;
}

networkHTML=function(){
  const html=connectionsBaseGraph(), selected=networkSelection();if(!selected)return html;
  return html.replace('<div id="network-tree"',`<div class="connection-lenses"><span>${icon('medal')} Own awards</span><span>${icon('star')} Community recognition</span><span>${icon('users')} Squad visibility</span><a href="#connections">Explore the full picture →</a></div><div id="network-tree"`)+
    (network.expanded&&selected.squad?connectionBreakdown(selected.squad):'');
};

influenceHTML=function(player){
  const sources=player.influenceSources||[], led=arena.data.teams.filter(t=>t.ownerId===player.id);
  const awards=Object.values(player.awards).reduce((total,count)=>total+Number(count),0);
  return `<section class="network-profile-influence"><div><span class="eyebrow">PLAYER CONNECTIONS</span><h2>Recognition. Support. Discovery.</h2><p>Three signals, with a different job for each.</p></div><a href="${connectionLink('player',player.id)}">Explore this player's circle →</a>
    <div class="connection-signals"><div><strong>${awards}</strong><span>Own awards</span><small>${escape(player.rank||'No award tier')} / retained when joining squads</small></div><div><strong>+${Number(player.communityPoints||0).toFixed(1)}</strong><span>Community points</span><small>${player.communityStars} supporters / separate from award tier</small></div><div><strong>+${connectionNumber(player.discoveryBoost)}</strong><span>Strongest squad boost</span><small>Applies only when the post's sport matches</small></div></div>
    ${sources.length?`<ul>${sources.map(source=>`<li><a href="#player/${encodeURIComponent(source.sourcePlayerId)}">${escape(arenaPlayer(source.sourcePlayerId)?.name||'Captain')}</a><a href="${connectionLink('team',source.teamId)}">→ ${escape(arena.data.teams.find(t=>t.id===source.teamId)?.name||'Squad')}</a><span>→ ${escape(player.name)} / ${escape(source.sport)}</span><b>+${connectionNumber(source.boost)}</b></li>`).join('')}</ul>`:'<p class="quiet">No inherited squad boost. Approval activates a member connection; captains do not boost themselves.</p>'}
    ${led.length?`<div class="connection-led"><h3>${escape(player.name)}'s captain connections</h3>${led.map(t=>`<a href="${connectionLink('team',t.id)}"><span>${escape(t.name)} / ${escape(t.sport)}</span><strong>${t.influence.acceptedMemberCount} members / +${connectionNumber(t.influence.memberBoost)} each</strong></a>`).join('')}</div>`:''}
    <p class="connection-note">The strongest matching source applies once. Awards and community points remain separate. Squad visibility never passes onward through another captain.</p></section>`;
};

function connectionRulebook(){
  const rules=[['Recognition starts the connection','The captain’s highest award tier contributes influence: Star 4, Diamond 3, Gold 2, Silver 1.'],['Support has a limit','Each supporter adds 0.2 captain influence, up to 1 extra point. Community points on a profile stay separate.'],['Approval activates visibility','Accepted non-captain members receive 20% of captain influence, capped at +1 feed-ranking point.'],['Your achievements remain yours','Membership preserves your own award tier, award counts and community support.'],['Pending means waiting','An application alone grants no squad boost. It starts after captain approval.'],['A wider circle, one direct boost','Only the strongest matching-sport source applies. Boosts never stack or travel recursively.']];
  return `<section class="connection-rulebook"><span class="eyebrow">HOW YOUR CIRCLE WORKS</span><h2>Every connection has a clear meaning.</h2><div class="connection-rule-grid">${rules.map(([title,copy],i)=>`<article><span>0${i+1}</span><h3>${escape(title)}</h3><p>${escape(copy)}</p></article>`).join('')}</div><p class="connection-note">This beta uses demo profiles and organizer controls. A feed advantage helps ordering; it does not guarantee views, team selection or tournament qualification.</p></section>`;
}

function connectionCalculator(){
  return `<section class="connection-calculator"><div><span class="eyebrow">EXPLORE THE CONNECTION</span><h2>What could a captain share?</h2><p>Preview a direct member's visibility. This preview changes no awards or memberships.</p></div><div class="connection-controls"><label>Captain's award tier<select data-connection-tier><option value="">No awards</option>${ranks.map(t=>`<option value="${t}" ${t==='Gold'?'selected':''}>${t}</option>`).join('')}</select></label><label>Community supporters<input data-connection-support type="number" value="5" min="0" max="10000" step="1" required></label></div><output aria-live="polite" data-connection-preview></output></section>`;
}

function updateConnectionPreview(){
  const tier=document.querySelector('[data-connection-tier]'), supporters=document.querySelector('[data-connection-support]'), output=document.querySelector('[data-connection-preview]');if(!tier||!supporters||!output)return;
  if(!supporters.validity.valid){output.textContent='Choose a whole number of supporters from 0 to 10,000.';return;}
  const rules=connectionRules(), points=rules.tierPoints[tier.value]||0, support=Math.min(Number(supporters.value)/rules.supportersPerPoint,rules.supportCap), score=points+support;
  output.textContent=`${connectionNumber(points)} award influence + ${connectionNumber(support)} support = ${connectionNumber(score)} captain influence → +${connectionNumber(Math.min(rules.memberCap,score*rules.memberFactor))} per accepted member.`;
}

communityPage=function(){
  const html=connectionsBaseCommunity(), c=communities().find(c=>c.id===ring.route.split('/')[1]);if(!c)return html;
  const squads=arena.data.teams.filter(t=>t.sport===c.sport&&(c.city==='Online'||t.city===c.city));
  return html.replace('<div class="ring-layout">',`<div class="connection-community"><div><strong>One Arena. Connected players.</strong><p>${squads.length} squads connect captains, recognition and accepted teammates here.</p></div><a href="${connectionLink('community',c.id)}">Explore these connections →</a></div><div class="ring-layout">`);
};

postHTML=function(post){
  const html=connectionsBasePost(post);if(!post.discoveryBoost||!post.discoverySources?.length)return html;
  return html.replace('<div class="post-actions">',`<button class="connection-post" data-connection-post="${escape(post.id)}">${icon('users')} +${connectionNumber(post.discoveryBoost)} squad visibility <span>Why this connection? →</span></button><div class="post-actions">`);
};

render=function(){
  if(view!=='connections'){connectionsBaseRender();return;}
  document.body.classList.add('ring-experience');document.body.classList.remove('ring-home','arena-view');
  $('.page-heading').hidden=false;$('#eyebrow').textContent='YOUR SPORTING NETWORK';$('#title').textContent='One connection. A wider circle.';$('#subtitle').textContent='Browse teams and players. Select a card to explore their full story and connections.';
  $('#create').hidden=true;$('#filters').hidden=true;$('#search').disabled=true;$('#search').placeholder='Explore connections below';
  const error=arena.error?`<div class="arena-error" role="alert">${escape(arena.error)} <button data-arena-retry>Retry connection</button></div>`:'';
  if(arena.data){
    const route=location.hash.slice(1).split('/');if(route[1]&&route[2]&&connectionsAppliedRoute!==location.hash){chooseConnection(route[1],decodeURIComponent(route[2]));connectionsAppliedRoute=location.hash;}
    const focused=route[1]==='player'?arenaPlayer(decodeURIComponent(route[2]||'')):null;
    $('#content').innerHTML=error+`<div class="connection-overview"><span><strong>${communities().length}</strong> Arenas</span><span><strong>${arena.data.teams.length}</strong> Squads</span><span><strong>${arena.data.players.length}</strong> Player profiles</span><a href="${connectionLink('player',arena.data.currentUserId)}">See my connections →</a></div>`+networkHTML()+(focused?influenceHTML(focused):'')+(route[1]?connectionRulebook()+connectionCalculator()+`<section><div class="section-bar"><h2>Find your next connection</h2><a href="#teams">Squads and applications →</a></div><div class="connection-directory">${arena.data.teams.map(t=>`<article><h3>${escape(t.name)}</h3><p>${escape(t.sport)} / ${escape(t.city)}</p>${squadInfluenceHTML(t)}</article>`).join('')}</div></section>`:'');
    if(route[1])updateConnectionPreview();
  }else $('#content').innerHTML=error+'<p class="empty" role="status">Loading your sporting connections…</p>';
  document.querySelectorAll('nav button').forEach(b=>{const active=b.dataset.ringRoute==='connections';b.classList.toggle('active',active);b.setAttribute('aria-current',active?'page':'false');});
  $('#connection-status').textContent=arena.data?'Shared demo account / RING':'Loading connections';
};
navigate=function(next){
  if((next||'').split('/')[0]!=='connections'){connectionsAppliedRoute=null;return connectionsBaseNavigate(next);}
  view='connections';query='';$('#search').value='';network.expanded=true;render();
};

document.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button)return;
  if('networkInfo'in button.dataset){event.preventDefault();event.stopImmediatePropagation();openModal('The Ring effect',connectionRulebook(),'Got it',()=>{});}
  if(button.dataset.connectionPost){
    const post=state.posts.find(p=>p.id===button.dataset.connectionPost);if(!post)return;
    const paths=post.discoverySources.map(s=>`<p class="modal-note"><a href="#player/${encodeURIComponent(s.sourcePlayerId)}">${escape(arenaPlayer(s.sourcePlayerId)?.name||'Captain')}</a> → <a href="${connectionLink('team',s.teamId)}">${escape(arena.data.teams.find(t=>t.id===s.teamId)?.name||'Squad')}</a> → ${escape(post.name)}<br>+${connectionNumber(s.boost)} for this ${escape(post.sport)} post.</p>`).join('');
    openModal('Why this squad connection?',paths+'<p class="modal-note">Only the strongest matching source applies once. Interests, location, recency and other signals still shape the feed. Earned awards are unchanged.</p>','Got it',()=>{});
    $('#modal-body').querySelectorAll('a').forEach(link=>link.addEventListener('click',()=>$('#modal').close()));
  }
},true);
document.addEventListener('input',event=>{if(event.target.matches('[data-connection-tier], [data-connection-support]'))updateConnectionPreview();});
const connectionsBaseMutation=arenaMutation;
arenaMutation=async function(path,body,organizer=false){const ok=await connectionsBaseMutation(path,body,organizer);if(ok&&social.online&&/\/join$/.test(path))await refreshFeed();return ok;};
navigate(location.hash.slice(1));
