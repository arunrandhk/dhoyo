const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const vm=require('node:vm');
function page(){
  const nodes=new Map(),listeners=new Map(),timers=new Map();
  let currentTime=Date.now(),nextTimer=0;
  class Clock extends Date {static now(){return currentTime;}}
  function node(selector){
    if(!nodes.has(selector))nodes.set(selector,{innerHTML:'',textContent:'',hidden:false,disabled:false,value:'',
      classList:{add(){},remove(){},toggle(){}},setAttribute(){}});
    return nodes.get(selector);
  }
  const context=vm.createContext({Date:Clock,URL,Promise,AbortSignal,encodeURIComponent,
    setTimeout(callback,delay){const id=++nextTimer;timers.set(id,{callback,delay});return id;},
    clearTimeout(id){timers.delete(id);},
    account:{userId:'player-one',name:'Player One',accountType:'player'},accountReady:Promise.resolve(),
    location:{hash:'#ring'},view:'ring',filter:'All sports',query:'',
    document:{body:node('body'),querySelectorAll(){return [];},addEventListener(type,listener){listeners.set(type,listener);}},
    $(selector){return node(selector);},render(){},navigate(next){context.view=next;},
    escape(value){return String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));},
    fetch:async()=>{throw new Error('Unexpected request');}
  });
  vm.runInContext(readFileSync(path.join(__dirname,'../static/sportspace/google-play.js'),'utf8'),context);
  return {context,node,listeners,timers,advance(milliseconds){currentTime+=milliseconds;},run(code){return vm.runInContext(code,context);}};
}
function fixture(p,enabled=false){
  p.run(`playState.owner=account.userId;view='google-play';playState.settings={playGamesEnabled:${enabled},storeUrl:null};playState.status={currentUserId:account.userId,linked:false};render()`);
}
const response=value=>({ok:true,json:async()=>value});
function deferred(){let resolve;return {promise:new Promise(done=>resolve=done),resolve:()=>resolve()};}

test('Google Play page states publication and setup honestly without inventing a download link',()=>{
  const p=page();fixture(p);
  assert.match(p.node('#content').innerHTML,/Not published yet/);
  assert.match(p.node('#content').innerHTML,/Setup pending/);
  assert.doesNotMatch(p.node('#content').innerHTML,/href="https:\/\/play.google.com|data-play-approve/);
});
test('store links allow only real Google Play detail URLs',()=>{
  const p=page();
  for(const link of ['javascript:alert(1)','https://play.google.com.evil.example/store/apps/details?id=com.dhoyo.app','https://evil.example/','https://user@play.google.com/store/apps/details?id=com.dhoyo.app']){
    p.context.linkFixture=link;assert.equal(p.run('playStoreLink(linkFixture)'),'');
  }
  assert.equal(p.run("playStoreLink('https://play.google.com/store/apps/details?id=com.dhoyo.app')"),'https://play.google.com/store/apps/details?id=com.dhoyo.app');
});
test('a native challenge requires an explicit approval before requesting a ticket',async()=>{
  const p=page();await Promise.resolve();fixture(p,true);
  const calls=[];
  p.context.fetch=async(url,options)=>{calls.push({url,options});return response({ticket:'t'.repeat(43),currentUserId:'player-one',expiresIn:300});};
  p.run("playState.challenge='c'.repeat(43);render()");
  assert.equal(calls.length,0);assert.match(p.node('#content').innerHTML,/Approve & continue in Android/);
  const button={dataset:{},hasAttribute:()=>false};
  await p.listeners.get('click')({target:{closest:()=>button},preventDefault(){}});
  assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/play-games/tickets');
  assert.deepEqual(JSON.parse(calls[0].options.body),{challenge:'c'.repeat(43)});
  assert.match(p.node('#content').innerHTML,/href="dhoyo:\/\/play-games\?ticket=t{43}"/);
  assert.doesNotMatch(p.node('#content').innerHTML,/data-play-approve/);
});
test('organisation accounts cannot approve a player gaming connection',async()=>{
  const p=page();await Promise.resolve();fixture(p,true);
  p.run("account.accountType='organisation';playState.challenge='c'.repeat(43);render()");
  assert.match(p.node('#content').innerHTML,/Connect a player account/);
  assert.doesNotMatch(p.node('#content').innerHTML,/data-play-approve/);
  await p.listeners.get('click')({target:{closest:()=>({dataset:{},hasAttribute:()=>false})},preventDefault(){}});
  assert.equal(p.run('playState.ticket'),'');
});
test('responses for a different browser account never show private connection data',async()=>{
  const p=page();await Promise.resolve();fixture(p);
  p.context.fetch=async url=>response(url.endsWith('config')?{playGamesEnabled:true}:{currentUserId:'player-two',linked:true,lastSyncedAt:'2030-01-01'});
  await p.run('playLoad()');
  assert.equal(p.run('playState.status'),null);
  assert.match(p.node('#content').innerHTML,/Your account changed/);
});
test('switching identity invalidates an in-flight approval ticket',async()=>{
  const p=page();await Promise.resolve();fixture(p,true);const wait=deferred();
  p.context.fetch=async()=>{await wait.promise;return response({ticket:'t'.repeat(43),currentUserId:'player-one',expiresIn:300});};
  p.run("playState.challenge='c'.repeat(43)");
  const approval=p.listeners.get('click')({target:{closest:()=>({dataset:{},hasAttribute:()=>false})},preventDefault(){}});
  await Promise.resolve();p.run("account.userId='player-two';render()");wait.resolve();await approval;
  assert.equal(p.run('playState.ticket'),'');assert.doesNotMatch(p.node('#content').innerHTML,/ticket=/);
});
test('a cookie changed in another tab cannot approve a different account under the old name',async()=>{
  const p=page();await Promise.resolve();fixture(p,true);
  p.context.fetch=async()=>response({ticket:'t'.repeat(43),currentUserId:'player-two'});
  p.run("playState.challenge='c'.repeat(43)");
  await p.listeners.get('click')({target:{closest:()=>({dataset:{},hasAttribute:()=>false})},preventDefault(){}});
  assert.equal(p.run('playState.ticket'),'');
  assert.match(p.node('#content').innerHTML,/Your account changed/);
  assert.doesNotMatch(p.node('#content').innerHTML,/ticket=/);
});

async function approve(p){
  await p.listeners.get('click')({target:{closest:()=>({dataset:{},hasAttribute:()=>false})},preventDefault(){}});
}
test('expired approvals lose their Android link and require a fresh explicit approval',async()=>{
  const p=page();await Promise.resolve();fixture(p,true);let calls=0;
  p.context.fetch=async()=>{calls++;return response({ticket:String(calls).repeat(43),currentUserId:'player-one',expiresIn:300});};
  p.run("playState.challenge='c'.repeat(43)");await approve(p);
  assert.match(p.node('#content').innerHTML,/ticket=1{43}/);
  const expiry=[...p.timers.values()][0];p.advance(300001);expiry.callback();
  assert.doesNotMatch(p.node('#content').innerHTML,/ticket=/);
  assert.match(p.node('#content').innerHTML,/approval link expired/);
  assert.match(p.node('#content').innerHTML,/data-play-approve/);
  assert.equal(calls,1,'Expiry must not silently approve another link');
  await approve(p);
  assert.match(p.node('#content').innerHTML,/ticket=2{43}/);assert.equal(calls,2);
});
test('returning to a backgrounded page removes an expired link even before its timer fires',async()=>{
  const p=page();await Promise.resolve();fixture(p,true);
  p.context.fetch=async()=>response({ticket:'t'.repeat(43),currentUserId:'player-one',expiresIn:300});
  p.run("playState.challenge='c'.repeat(43)");await approve(p);p.advance(300001);
  p.context.document.visibilityState='visible';p.listeners.get('visibilitychange')();
  assert.equal(p.run('playState.ticket'),'');assert.equal(p.timers.size,0);
  assert.doesNotMatch(p.node('#content').innerHTML,/ticket=/);
});
test('leaving the approval page cancels expiry callbacks and clears the link',async()=>{
  const p=page();await Promise.resolve();fixture(p,true);
  p.context.fetch=async()=>response({ticket:'t'.repeat(43),currentUserId:'player-one',expiresIn:300});
  p.run("playState.challenge='c'.repeat(43)");await approve(p);
  assert.equal(p.timers.size,1);p.run("navigate('ring')");
  assert.equal(p.run('playState.ticket'),'');assert.equal(p.timers.size,0);
});
test('approval links without a trustworthy expiry are not shown',async()=>{
  for(const expiresIn of [undefined,0,-1,301,'300']){
    const p=page();await Promise.resolve();fixture(p,true);
    p.context.fetch=async()=>response({ticket:'t'.repeat(43),currentUserId:'player-one',expiresIn});
    p.run("playState.challenge='c'.repeat(43)");await approve(p);
    assert.equal(p.run('playState.ticket'),'');assert.doesNotMatch(p.node('#content').innerHTML,/ticket=/);
  }
});
