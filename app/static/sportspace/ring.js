const ring = {route:'ring'};
const beforeRingNavigate = navigate;
const beforeRingRender = render;
const ringSections = ['ring', 'discover', 'community'];
const communities = () => arena.data?.communities || [];
const communityFor = sport => communities().find(c => c.sport === sport);
const isRingView = () => ringSections.includes(view);

function ringStories() {
  const community=view==='community'?communities().find(c=>c.id===ring.route.split('/')[1]):null;
  const active = social.stories.filter(s => new Date(s.expiresAt) > new Date()&&(!community||s.sport===community.sport)&&(community||typeof storyScopeMatch!=='function'||storyScopeMatch(s)));
  return `<div class="ring-stories" aria-label="Player stories">
    <button class="ring-story ring-story-add" data-add-story><span class="avatar mine">JD</span>${icon('plus')}<span class="ring-story-name">Your story</span></button>
    ${active.map(s => `<button class="ring-story ${social.seen.includes(s.id)?'seen':''}" data-story="${escape(s.id)}" aria-label="View ${escape(s.name)}'s story"><img src="${escape(s.image)}" alt=""><span class="ring-story-name">${escape(s.name)}</span><span class="ring-story-sport">${escape(s.sport)}</span></button>`).join('')}
  </div>`;
}

postHTML = function(p) {
  const player = arena.data?.players.find(a => a.id === p.authorId);
  const community = communities().find(c=>c.id===p.communityId)||communityFor(p.sport);
  const liked = p.liked ?? state.likes.includes(p.id);
  return `<article class="post">
    <div class="post-heading"><span class="avatar">${escape(p.initials)}</span><div>${player?playerLink(player):`<strong>${escape(p.name)}</strong>`}<small>${community?`<a href="#community/${encodeURIComponent(community.id)}">${escape(community.name)}</a>`:escape(p.sport)} <span> / ${escape(p.time)}${p.state?' / '+escape(p.state):''}${p.country?' / '+escape(p.country):''}</span></small></div>${player?`<a href="#player/${encodeURIComponent(player.id)}/awards" aria-label="${escape(player.name)} rank details">${rankBadge(player.rank)}</a>`:''}</div>
    <p class="post-text">${escape(p.text)}</p>
    ${p.image?`<div class="post-image-wrap"><img class="post-image" src="${escape(p.image)}" alt="${escape(p.sport)} highlight" loading="lazy">${player?.rank?`<a class="ring-image-badge" href="#player/${encodeURIComponent(player.id)}">${icon('star')} ${escape(player.rank)} player <span>${escape(player.city)}</span></a>`:''}</div>`:''}
    <div class="game-reactions" aria-label="React to this moment">${[['fire','🔥','On fire'],['mvp','🏆','MVP'],['clap','👏','Well played']].map(([key,emoji,label])=>`<button type="button" data-game-reaction="${key}" data-game-post="${escape(p.id)}" class="game-reaction ${p.myReaction===key?'selected':''}" aria-pressed="${p.myReaction===key}" aria-label="${label} reaction"><span class="game-emoji" aria-hidden="true">${emoji}</span><span>${label}</span><b>${p.reactionCounts?.[key]||0}</b></button>`).join('')}</div>
    <div class="post-actions"><div class="post-actions-left"><button data-like="${escape(p.id)}" class="${liked?'liked':''}" aria-pressed="${liked}" title="Good game!"><span class="game-emoji" aria-hidden="true">👍</span> GG <span class="reaction-count">${p.likes+Number(liked)}</span></button><button data-comment="${escape(p.id)}" title="Comment">${icon('message-circle')} ${p.comments.length}</button>${player&&player.id!==arena.data.currentUserId?`<button data-support="${escape(player.id)}" class="ring-support ${player.supported?'supported':''}" aria-pressed="${player.supported}" ${arena.busy?'disabled':''} title="${player.supported?'Remove your community star':'Support this player with 0.2 points'}">${icon('star')} ${player.supported?'Starred':'+0.2'}</button>`:''}</div><button data-save="${escape(p.id)}" aria-pressed="${(p.saved??state.saved.includes(p.id))}" title="Save moment" aria-label="Save moment">${icon('bookmark')}</button></div>
    ${p.comments.slice(-2).map(c=>`<div class="comment"><strong>${escape(c.name)}</strong> ${escape(c.text)}</div>`).join('')}
    ${p.comments.length>2?`<button class="text-button" data-all-comments="${escape(p.id)}">View all ${p.comments.length} comments</button>`:''}
    <form class="comment-form" data-post="${escape(p.id)}"><input aria-label="Comment on ${escape(p.name)}'s post" placeholder="Give them some love..." required maxlength="500"><button type="submit">Post</button></form>
  </article>`;
};

function communityCard(c) {
  return `<article class="ring-community"><a href="#community/${encodeURIComponent(c.id)}"><img src="${escape(c.image)}" alt="${escape(c.sport)} community"><div class="ring-community-info"><span class="ring-feed-label">${escape(c.sport)} / ${escape(c.city)}</span><h3>${escape(c.name)}</h3><small>${c.memberCount} members${c.joined?' / Joined':''}</small><span class="ring-card-arrow">${icon('arrow-up-right')}</span></div></a></article>`;
}

function ringRail() {
  const players = arena.data?.players.filter(p=>p.rank&&p.id!==arena.data.currentUserId).sort((a,b)=>ranks.indexOf(a.rank)-ranks.indexOf(b.rank)||categoryScore(b,b.rank)-categoryScore(a,a.rank)).slice(0,4)||[];
  return `<aside class="ring-rail"><section class="ring-rail-block"><div class="ring-section-heading"><h2>Find your Arena</h2><a href="#discover" aria-label="Discover all Arenas">${icon('arrow-up-right')}</a></div>${communities().slice(0,3).map(c=>`<a class="ring-arena-row" href="#community/${encodeURIComponent(c.id)}"><img src="${escape(c.image)}" alt=""><span><strong>${escape(c.name)}</strong><small>${escape(c.sport)} / ${c.memberCount} members</small></span>${icon('arrow-up-right')}</a>`).join('')||'<p class="quiet">Communities are loading.</p>'}</section>
    <section class="ring-rail-block"><div class="ring-section-heading"><h2>In the spotlight</h2><span class="ring-feed-label">PLAYERS</span></div>${players.map(p=>`<div class="ring-person">${arenaAvatar(p)}<div>${playerLink(p)}<small>${escape(p.sport)}</small></div>${rankBadge(p.rank)}</div>`).join('')}<div class="ring-rank-links">${ranks.map(t=>`<a href="#rankings/${t}">${rankBadge(t)}</a>`).join('')}</div></section>
    <section class="ring-rail-block ring-next"><span class="ring-feed-label">BEYOND THE SCREEN</span><h2>Make the next<br>moment happen.</h2><a href="#grounds">Find a place to play ${icon('arrow-up-right')}</a><a href="#tournaments">Join a competition ${icon('arrow-up-right')}</a></section>
  </aside>`;
}

function ringFeed(posts, story=true) {
  return `${story?ringStories():''}<div class="composer"><span class="avatar mine">JD</span><button data-compose>What happened in your game?</button><button class="ring-photo-button" data-add-story title="Share a story" aria-label="Share a story">${icon('image')}</button></div>${posts.map(postHTML).join('')||'<div class="ring-empty"><h2>Your next connection starts here.</h2><p>No moments match this view yet.</p><button class="primary" data-compose>Share a moment</button></div>'}`;
}

function ringHome() {
  const posts=social.online?state.posts.filter(matches):demoFeed();
  return `${typeof hubHomeConnections==='function'?hubHomeConnections():''}<div class="ring-layout unified-home"><section class="ring-feed">${ringStories()}<div class="social-feed-heading"><h2>Social feed</h2><button class="ring-interest-button" data-interests>${icon('sliders-horizontal')} Your interests</button></div><div class="filters" role="group" aria-label="Filter feed by sport">${sports.map(s=>`<button class="chip ${filter===s?'active':''}" data-filter="${s}" aria-pressed="${filter===s}">${s}</button>`).join('')}</div>${social.error?`<div class="arena-error" role="alert">${escape(social.error)} <button data-retry>Retry</button></div>`:''}${social.loading?'<p class="feed-status" role="status">Updating your feed…</p>':''}${ringFeed(posts,false)}</section><aside class="home-connections" aria-label="Your connections map">${arena.data?connectionsBaseGraph():'<p>Loading connections…</p>'}<a class="hub-link" href="#connections">View all teams & players ↗</a></aside></div>`;
}

function discoverRing() {
  const list=communities().filter(c=>(filter==='All sports'||filter===c.sport)&&[c.name,c.sport,c.city,c.description].join(' ').toLowerCase().includes(query));
  return `<div class="ring-section-heading"><h2>Find where you belong.</h2><span class="ring-feed-label">${list.length} ARENAS</span></div><div class="ring-community-grid">${list.map(communityCard).join('')||'<p class="empty">No Arenas match your search.</p>'}</div>`;
}

function communityPlayers(c,tier) {
  const players=arena.data.players.filter(p=>p.sport===c.sport&&(c.city==='Online'||p.city===c.city)&&(!tier||p.awards[tier]>0)&&[p.name,p.sport,p.city].join(' ').toLowerCase().includes(query)).sort((a,b)=>tier?categoryScore(b,tier)-categoryScore(a,tier):ranks.indexOf(a.rank)-ranks.indexOf(b.rank));
  return `<div class="ring-rank-links"><a href="#community/${encodeURIComponent(c.id)}/players" class="text-button">All players</a>${ranks.map(t=>`<a href="#community/${encodeURIComponent(c.id)}/players/${t}" ${tier===t?'aria-current="page"':''}>${rankBadge(t)}</a>`).join('')}</div><div class="leaderboard">${players.map((p,i)=>`<div class="athlete-row"><div class="athlete-identity"><span class="position">${i+1}</span>${arenaAvatar(p)}<div>${playerLink(p)}<small>${p.gamesPlayed} games / ${p.wins} wins</small></div></div><div class="award-number">${rankBadge(tier||p.rank)} ${p.awards[tier||p.rank]||0}</div><div class="community-number">+${p.communityPoints.toFixed(1)}<small>Community</small></div><strong class="score-number">${categoryScore(p,tier||p.rank).toFixed(1)}</strong></div>`).join('')||'<p class="empty">No players in this category yet.</p>'}</div>`;
}

function communityPage() {
  const [,id,requestedTab,requestedTier]=ring.route.split('/');
  const c=communities().find(c=>c.id===id);
  if(!c)return '<p class="empty">Arena not found. <a href="#discover">Explore Arenas</a></p>';
  const tab=['players','squads'].includes(requestedTab)?requestedTab:'highlights';
  const tier=ranks.includes(requestedTier)?requestedTier:null;
  const posts=state.posts.filter(p=>(p.communityId?p.communityId===c.id:p.sport===c.sport&&(c.city==='Online'||p.city===c.city))&&matches(p));
  const oldFilter=filter;
  let content;
  if(tab==='players')content=communityPlayers(c,tier);
  else if(tab==='squads'){filter=c.sport;content=teamsPage();filter=oldFilter;}
  else content=ringFeed(posts);
  return `<div class="ring-breadcrumb"><a href="#ring">dhoyo</a><span>/</span><a href="#discover">Arenas</a><span>/</span><strong>${escape(c.name)}</strong></div><div class="ring-community-cover"><img src="${escape(c.image)}" alt="${escape(c.sport)}"><div class="ring-community-title"><span class="ring-feed-label">${escape(c.sport)} / ${escape(c.city)}</span><h1>${escape(c.name)}</h1><p>${escape(c.description)}</p></div></div><div class="ring-community-meta"><span>${c.memberCount} members <span class="quiet">/ ${escape(c.sport)}</span></span><button class="primary ring-join" data-community-join="${escape(c.id)}" aria-pressed="${c.joined}" ${arena.busy?'disabled':''}>${c.joined?'Joined / Leave':'Join Arena'}</button></div><div class="ring-community-tabs" role="group" aria-label="Arena sections">${[['highlights','Highlights'],['players','Players & awards'],['squads','Squads']].map(([value,label])=>`<a href="#community/${encodeURIComponent(c.id)}/${value}" class="${tab===value?'active':''}" ${tab===value?'aria-current="page"':''}>${label}</a>`).join('')}</div><div class="ring-layout"><section>${content}</section>${ringRail()}</div>`;
}

render = function() {
  $('#filters').hidden=false;
  document.body.classList.add('ring-experience');
  document.body.classList.toggle('ring-home',view==='ring');
  if(!isRingView()) {
    beforeRingRender();
    if(view==='player'){
      $('#subtitle').textContent='The player. The moments. The recognition.';
      const previous=communities().find(c=>c.id===ring.lastCommunity);
      if(previous&&$('.back-link')){$('.back-link').href='#community/'+previous.id+'/players';$('.back-link').textContent='← '+previous.name+' players';}
    }
  } else {
    document.body.classList.remove('arena-view');
    const heading={ring:['YOUR SPORTING UNIVERSE','dhoyo.','Your people. Your game. Your next moment.'],discover:['dhoyo / ARENAS','Discover your Arena.','Big passions. Closer communities.'],community:['dhoyo / YOUR COMMUNITY','Your Arena','']}[view];
    $('#eyebrow').textContent=heading[0];$('#title').textContent=heading[1];$('#subtitle').textContent=heading[2];
    $('.page-heading').hidden=view==='community';
    $('#filters').hidden=view==='community';
    $('#create').hidden=view==='discover';$('#create').textContent='+ Share a moment';
    $('#search').disabled=false;$('#search').placeholder=view==='discover'?'Find your Arena':'Search dhoyo';
    $('#filters').innerHTML=view==='community'?'':sports.map(s=>`<button class="chip ${filter===s?'active':''}" data-filter="${s}" aria-pressed="${filter===s}">${s}</button>`).join('');
    const error=arena.error?`<div class="arena-error" role="alert">${escape(arena.error)} <button data-arena-retry>Retry</button></div>`:'';
    $('#content').innerHTML=error+(view==='ring'?ringHome():!arena.data?'<p class="empty">Loading your communities...</p>':view==='discover'?discoverRing():communityPage());
  }
  if(view!=='community')$('.page-heading').hidden=false;
  document.querySelectorAll('nav button').forEach(b=>{const active=b.dataset.ringRoute===view||(b.dataset.ringRoute==='discover'&&view==='community')||(b.dataset.ringRoute==='player/demo-user'&&view==='player')||b.dataset.view===view;b.classList.toggle('active',active);b.setAttribute('aria-current',active?'page':'false');});
  $('#ring-memberships').innerHTML=`<div class="workspace-label">YOUR ARENAS</div>${communities().filter(c=>c.joined).map(c=>`<a class="ring-membership" href="#community/${encodeURIComponent(c.id)}"><img src="${escape(c.image)}" alt=""><span>${escape(c.name)}</span><span class="ring-membership-dot"></span></a>`).join('')||'<a class="ring-membership" href="#discover">Explore communities →</a>'}`;
  $('#connection-status').textContent=arena.data?'Shared demo account / RING':'Browser preview / RING';
};

navigate = function(next) {
  let route=next||'ring';
  if(route==='arena')route='discover';
  if(route==='feed')route='ring';
  ring.route=route;
  const section=route.split('/')[0];
  if(ringSections.includes(section)) {
    view=section;filter='All sports';query='';$('#search').value='';
    if(section==='community'){ring.lastCommunity=route.split('/')[1];}
    render();
    if(social.online)refreshFeed();
  } else beforeRingNavigate(route);
};

document.addEventListener('click',async event=>{
  const button=event.target.closest('button');
  if(!button)return;
  if(button.dataset.ringRoute)location.hash=button.dataset.ringRoute;
  if(button.dataset.communityJoin)await arenaMutation('/communities/'+encodeURIComponent(button.dataset.communityJoin)+'/membership');
});

const globalCompose=compose;
compose=function(){
  const c=view==='community'?communities().find(c=>c.id===ring.route.split('/')[1]):null;
  if(!c){globalCompose();return;}
  openSocialForm('Share in '+c.name,`<p class="modal-note">${escape(c.sport)} / ${escape(c.city)}</p><label class="field">Your moment<textarea name="text" required maxlength="2000" placeholder="What happened in your game?"></textarea></label>`,'Share moment',async data=>{
    const ok=await mutation('/posts',{text:data.get('text').trim(),sport:c.sport,communityId:c.id});
    if(ok)toast('Shared in '+c.name+'.');
    return ok;
  });
};
const globalAddStory=addStory;
addStory=function(){globalAddStory();const c=view==='community'?communities().find(c=>c.id===ring.route.split('/')[1]):null;if(c&&$('#modal [name="sport"]'))$('#modal [name="sport"]').value=c.sport;};
navigate(location.hash.slice(1));

const pendingGameReactions=new Set();
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-game-reaction]');if(!button)return;
  const id=button.dataset.gamePost;if(pendingGameReactions.has(id))return;
  pendingGameReactions.add(id);button.disabled=true;
  try{const result=await api('/posts/'+encodeURIComponent(id)+'/reaction','POST',{reaction:button.dataset.gameReaction});
    const post=state.posts.find(p=>p.id===id);if(post)Object.assign(post,{reactionCounts:result.reactionCounts,myReaction:result.myReaction});
    if(typeof playerHub!=='undefined')for(const profile of playerHub.profiles.values()){const p=profile.posts.find(p=>p.id===id);if(p)Object.assign(p,{reactionCounts:result.reactionCounts,myReaction:result.myReaction});}
    render();if(result.myReaction)toast(({fire:'🔥 On fire!',mvp:'🏆 MVP energy!',clap:'👏 Well played!'})[result.myReaction]);
  }catch(error){toast(error.message);}finally{pendingGameReactions.delete(id);button.disabled=false;}
});
