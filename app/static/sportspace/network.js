const network = {communityId:null,playerId:null,teamId:null,expanded:true};
const beforeNetworkRender = render;

function networkSelection() {
  const data=arena.data;
  if(!data)return null;
  const community=data.communities.find(c=>c.id===network.communityId)||data.communities[0];
  if(!community)return null;
  network.communityId=community.id;
  const players=data.players.filter(p=>community.memberIds.includes(p.id)||(p.sport===community.sport&&(community.city==='Online'||p.city===community.city)))
    .sort((a,b)=>(ranks.indexOf(a.rank)<0?4:ranks.indexOf(a.rank))-(ranks.indexOf(b.rank)<0?4:ranks.indexOf(b.rank)));
  const player=players.find(p=>p.id===network.playerId)||players.find(p=>data.teams.some(t=>t.ownerId===p.id&&t.sport===community.sport&&t.members.some(id=>id!==p.id)))||players[0];
  network.playerId=player?.id||null;
  const squads=data.teams.filter(t=>t.ownerId===player?.id&&t.sport===community.sport);
  const squad=squads.find(t=>t.id===network.teamId)||squads[0];
  network.teamId=squad?.id||null;
  const members=(squad?.members||[]).filter(id=>id!==player?.id).map(arenaPlayer).filter(Boolean);
  return {community,players,player,squads,squad,members};
}

function networkNode(kind,id,title,subtitle,selected,media='',detail='') {
  return `<button type="button" class="network-node ${selected?'selected':''}" data-network-${kind}="${escape(id)}" aria-pressed="${selected}" ${kind==='player'||kind==='community'?'aria-expanded="'+selected+'"':''}>${media}<span class="network-node-copy"><strong>${escape(title)}</strong><small>${escape(subtitle)}</small>${detail}</span></button>`;
}

function networkHTML() {
  const selected=networkSelection();
  if(!selected)return '';
  const {community,players,player,squads,squad,members}=selected;
  const influence=squad?.influence;
  return `<section class="ring-network" aria-label="Connected dhoyo hierarchy">
    <div class="network-heading"><div><span class="eyebrow">THE RING EFFECT</span><h2>One connection. A wider circle.</h2></div><button class="network-toggle" data-network-toggle aria-expanded="${network.expanded}" aria-controls="network-tree" title="${network.expanded?'Collapse':'Expand'} hierarchy">${icon(network.expanded?'chevron-up':'chevron-down')}<span>${network.expanded?'Collapse':'Explore connections'}</span></button></div>
    <div id="network-tree" ${network.expanded?'':'hidden'}>
      <div class="network-root"><span class="network-root-symbol">R</span><strong>RING</strong><small>Your sporting universe</small></div>
      <div class="network-level"><div class="network-level-label">01 / ARENAS</div><div class="network-nodes">${arena.data.communities.map(c=>networkNode('community',c.id,c.name,c.sport,c.id===community.id,`<img class="network-photo" src="${escape(c.image)}" alt="">`)).join('')}</div></div>
      <div class="network-level"><div class="network-level-label">02 / PLAYERS IN ${escape(community.name.toUpperCase())}<a href="#community/${encodeURIComponent(community.id)}">Enter Arena ${icon('arrow-up-right')}</a></div><div class="network-nodes">${players.map(p=>networkNode('player',p.id,p.name,p.rank?p.rank+' player':'Player',p.id===player?.id,arenaAvatar(p),rankBadge(p.rank))).join('')||'<p class="network-empty">No players in this Arena yet.</p>'}</div></div>
      <div class="network-level"><div class="network-level-label">03 / ${escape(player?.name.toUpperCase()||'PLAYER')}&#39;S SQUADS${player?`<a href="#player/${encodeURIComponent(player.id)}">Player profile ${icon('arrow-up-right')}</a>`:''}</div><div class="network-nodes">${squads.map(t=>networkNode('team',t.id,t.name,t.members.length+' / '+t.capacity+' players',t.id===squad?.id,`<span class="network-squad-icon">${icon('users')}</span>`,`<span class="network-transfer">${t.influence?Number(t.influence.memberBoost).toFixed(2):'0.0'} discovery / member</span>`)).join('')||`<p class="network-empty">This player does not lead a squad here. <a href="#community/${encodeURIComponent(community.id)}/squads">Explore squads</a></p>`}</div></div>
      ${squad?`<div class="network-level network-members"><div class="network-level-label">04 / MEMBERS${influence?.memberBoost?`<span class="network-flow-label">${escape(influence.sourceRank||'Player')} influence flows down ↓</span>`:''}</div><div class="network-nodes">${members.map(p=>`<a class="network-node network-member" href="#player/${encodeURIComponent(p.id)}">${arenaAvatar(p)}<span class="network-node-copy"><strong>${escape(p.name)}</strong><small>${escape(p.rank||'Unranked')} / earned</small><span class="network-transfer">+${Number(influence?.memberBoost||0).toFixed(2)} squad discovery</span></span></a>`).join('')||`<div class="network-empty">No accepted members yet.<a href="#community/${encodeURIComponent(community.id)}/squads">${squad.ownerId===arena.data.currentUserId?'Build your squad':'View squad'}</a></div>`}</div></div>`:''}
      <div class="network-summary"><span>${escape(player?.rank||'Unranked')} leader</span><span>→</span><span>${escape(squad?.name||'No squad')}</span><span>→</span><strong>${members.length} members ${influence?.memberBoost?' / +'+Number(influence.memberBoost).toFixed(2)+' discovery each':''}</strong><button data-network-info title="How discovery influence works">${icon('info')}</button></div>
    </div>
  </section>`;
}

function influenceHTML(player) {
  const sources=player.influenceSources||[];
  return `<section class="network-profile-influence"><div><span class="eyebrow">YOUR CONNECTIONS</span><h2>Squad discovery</h2><p>Earned awards stay yours. Your squad adds visibility.</p></div><strong>+${Number(player.discoveryBoost||0).toFixed(2)}</strong>${sources.length?`<ul>${sources.map(source=>`<li><a href="#player/${encodeURIComponent(source.sourcePlayerId)}">${escape(arenaPlayer(source.sourcePlayerId)?.name||'Captain')}</a><span>→ ${escape(arena.data.teams.find(t=>t.id===source.teamId)?.name||'Squad')} → you</span><b>+${Number(source.boost).toFixed(2)}</b></li>`).join('')}</ul>`:'<p class="quiet">No inherited squad boost. Captains do not boost themselves.</p>'}</section>`;
}

render=function(){
  beforeNetworkRender();
  // The home screen leads with posts. Connections live on profiles and My connections.
  if(view==='player'&&arena.data&&typeof playerHub==='undefined'){const player=arenaPlayer(arena.route.split('/')[1]);if(player)$('#content').insertAdjacentHTML('beforeend',influenceHTML(player));}
};

document.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button)return;
  const d=button.dataset;
  if('networkToggle'in d){network.expanded=!network.expanded;render();}
  else if(d.networkCommunity){network.communityId=d.networkCommunity;network.playerId=null;network.teamId=null;render();}
  else if(d.networkPlayer){network.playerId=d.networkPlayer;network.teamId=null;render();}
  else if(d.networkTeam){network.teamId=d.networkTeam;render();}
  else if('networkInfo'in d)openModal('The dhoyo effect','<p class="modal-note">An organizer-awarded captain gives their accepted squad members a small discovery boost. Star, Diamond, Gold and Silver captains start with 4, 3, 2 and 1 influence. Community support adds up to 1 more.</p><p class="modal-note">Members receive 20% of that influence, capped at +1.0. Only the strongest squad boost applies to a matching sport. Pending requests do not count. Awards and community points are never transferred.</p>','Got it',()=>{});
});
const beforeInfluenceMutation=arenaMutation;
arenaMutation=async function(path,body,organizer=false){
  const ok=await beforeInfluenceMutation(path,body,organizer);
  if(ok&&social.online&&(/\/support$|^\/awards$|\/members$|\/requests\//).test(path))await refreshFeed();
  return ok;
};
render();
