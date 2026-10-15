const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const vm=require('node:vm');

function page(){
  const nodes=new Map(),listeners=new Map();
  function node(selector){
    if(!nodes.has(selector)){
      const classes=new Set(),attributes=new Map();
      nodes.set(selector,{innerHTML:'',textContent:'',hidden:false,disabled:false,value:'',dataset:{},
        classList:{add(...values){values.forEach(value=>classes.add(value));},remove(...values){values.forEach(value=>classes.delete(value));},toggle(value,on){if(on)classes.add(value);else classes.delete(value);},contains(value){return classes.has(value);}},
        setAttribute(key,value){attributes.set(key,String(value));},removeAttribute(key){attributes.delete(key);}
      });
    }
    return nodes.get(selector);
  }
  const context=vm.createContext({Date,Intl,Set,Promise,URLSearchParams,AbortSignal,encodeURIComponent,
    account:{userId:'player-one',accountType:'player'},accountReady:Promise.resolve(),
    location:{hash:'#ring'},view:'ring',filter:'All sports',query:'',
    document:{body:node('body'),querySelectorAll(){return [];},addEventListener(type,listener){if(!listeners.has(type))listeners.set(type,[]);listeners.get(type).push(listener);}},
    $(selector){return node(selector);},icon(){return '<svg></svg>';},
    render(){context.baseRenders=(context.baseRenders||0)+1;},navigate(next){context.view=next;context.baseNavigations=(context.baseNavigations||0)+1;},
    escape(value){return String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));},
    fetch:async()=>{throw new Error('Unexpected request');}
  });
  context.window=context;
  vm.runInContext(readFileSync(path.join(__dirname,'../static/sportspace/progression.js'),'utf8'),context);
  return {context,node,listeners,run(code){return vm.runInContext(code,context);}};
}

function personal(playerId='player-one'){
  return {playerId,stats:{registeredTournaments:1,completedTournaments:0,sportsCompleted:0},
    achievements:[{id:'first-team',name:'Team ready',description:'Register for your first tournament team.',target:1,progress:1,unlocked:true,earnedAt:'2035-01-01T00:00:00Z'},
      {id:'first-tournament',name:'First finish',description:'Participate in a completed tournament.',target:1,progress:0,unlocked:false,earnedAt:null}]};
}
function board(currentUserId='player-one'){
  const season={id:'2035-Q1',label:'Q1 2035 · UTC'};
  return {currentUserId,season,seasons:[season],sport:'All sports',sports:['Football'],
    players:[{playerId:'player-one',name:'Player One',initials:'PO',avatar:'',rank:1,completedTournaments:0,registeredTournaments:1}],
    totalPlayers:1,myRank:1,rankingRule:'Completed tournaments first, then registered tournaments. Equal totals share a rank.'};
}
function seed(p,me=personal(),ranking=board()){
  p.context.meFixture=me;p.context.boardFixture=ranking;
  p.run("playerProgress.owner=account.userId;playerProgress.me=meFixture;playerProgress.board=boardFixture;view='progress';");
}
function response(body,ok=true){return {ok,json:async()=>body};}
function deferred(){let resolve;return {promise:new Promise(done=>resolve=done),resolve(value){resolve(value);}};}

test('progress renders earned and locked milestones with a quarterly participation board',()=>{
  const p=page();seed(p);p.run('render()');
  const html=p.node('#content').innerHTML;
  assert.match(html,/Your achievements/);
  assert.match(html,/Team ready/);
  assert.match(html,/UNLOCKED/);
  assert.match(html,/NEXT MILESTONE/);
  assert.match(html,/aria-valuenow="0"/);
  assert.match(html,/Seasonal rankings/);
  assert.match(html,/Q1 2035 · UTC/);
  assert.match(html,/Equal totals share a rank/);
  assert.match(html,/Cancelled entries do not count/);
  assert.match(html,/<th scope="col">Completed<\/th>/);
  assert.equal(p.node('#search').disabled,true);
  assert.equal(p.node('#filters').hidden,true);
});

test('every server-owned label and photo attribute is escaped and active avatar sources fall back',()=>{
  const p=page(),me=personal(),ranking=board();
  me.achievements[0].name='<img src=x onerror=alert(1)>';
  me.achievements[0].description='<script>attack()</script>';
  ranking.players[0].name='<svg onload=alert(1)>';
  ranking.players[0].avatar='javascript:alert(1)';
  ranking.players[0].initials='<i>';
  seed(p,me,ranking);p.run('render()');
  const html=p.node('#content').innerHTML;
  assert.ok(!html.includes('<script>attack'));
  assert.ok(!html.includes('<svg onload='));
  assert.ok(!html.includes('src="javascript:'));
  assert.match(html,/&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(html,/&lt;i&gt;/);
  assert.equal(p.run('progressAvatar({avatar:"data:image/svg+xml;base64,PHN2Zz4=",initials:"A"}).includes("<img")'),false);
});

test('changing identity clears private progress and seasonal selection synchronously',()=>{
  const p=page();seed(p);
  p.run("playerProgress.season='2035-Q1';account.userId='player-two';render();");
  assert.equal(p.run('playerProgress.me'),null);
  assert.equal(p.run('playerProgress.board'),null);
  assert.equal(p.run('playerProgress.season'),'');
  assert.ok(!p.node('#content').innerHTML.includes('Team ready'));
});

test('loader sends encoded filters and verifies the identity on both responses',async()=>{
  const p=page();await Promise.resolve();const calls=[];
  p.context.fetch=async url=>{calls.push(url);return response(url.endsWith('/me')?personal():board());};
  await p.run("view='progress';playerProgress.season='2035-Q1';playerProgress.sport='Football';progressLoad()");
  assert.deepEqual(calls,['/api/progression/me','/api/progression/leaderboard?season=2035-Q1&sport=Football']);
  assert.equal(p.run('playerProgress.me.playerId'),'player-one');
  assert.equal(p.run('playerProgress.loading'),false);
});

test('responses belonging to a different account are not rendered',async()=>{
  const p=page();await Promise.resolve();
  p.context.fetch=async url=>response(url.endsWith('/me')?personal('player-two'):board('player-two'));
  await p.run("view='progress';progressLoad()");
  assert.equal(p.run('playerProgress.me'),null);
  assert.equal(p.run('playerProgress.board'),null);
  assert.match(p.node('#content').innerHTML,/Your account changed/);
});

test('identity change while loading discards delayed responses',async()=>{
  const p=page();await Promise.resolve();const waiting=deferred();
  p.context.fetch=async url=>{await waiting.promise;return response(url.endsWith('/me')?personal():board());};
  const pending=p.run("view='progress';progressLoad()");
  await Promise.resolve();
  p.run("account.userId='player-two';render()");
  waiting.resolve();await pending;
  assert.equal(p.run('playerProgress.me'),null);
  assert.equal(p.run('playerProgress.board'),null);
  assert.ok(!p.node('#content').innerHTML.includes('Player One'));
});

test('leaving progress delegates navigation and invalidates pending loads',async()=>{
  const p=page();await Promise.resolve();const waiting=deferred();
  p.context.fetch=async url=>{await waiting.promise;return response(url.endsWith('/me')?personal():board());};
  const pending=p.run("view='progress';progressLoad()");await Promise.resolve();
  p.run("navigate('tournaments')");waiting.resolve();await pending;
  assert.equal(p.context.view,'tournaments');assert.equal(p.context.baseNavigations,1);
  assert.equal(p.run('playerProgress.me'),null);
  assert.equal(p.node('body').classList.contains('progression-view'),false);
});

test('organisations see the player season without requesting personal player milestones',async()=>{
  const p=page();await Promise.resolve();const calls=[];
  p.context.account.accountType='organisation';
  p.context.fetch=async url=>{calls.push(url);return response(board());};
  await p.run("view='progress';progressLoad()");
  assert.equal(calls.length,1);assert.ok(calls[0].includes('/leaderboard?'));
  assert.match(p.node('#content').innerHTML,/Milestones for your players/);
});

test('load failures replace cached data with a useful retry state',async()=>{
  const p=page();await Promise.resolve();seed(p);
  p.context.fetch=async()=>response({error:'Service temporarily unavailable'},false);
  await p.run('progressLoad()');
  assert.equal(p.run('playerProgress.me'),null);
  assert.equal(p.run('playerProgress.board'),null);
  assert.match(p.node('#content').innerHTML,/role="alert"/);
  assert.match(p.node('#content').innerHTML,/Service temporarily unavailable/);
  assert.match(p.node('#content').innerHTML,/Try again/);
});
