const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const vm=require('node:vm');

function page(){
  const nodes=new Map(),listeners=new Map(),timers=new Map(),requests=[];
  let timerId=0;
  function node(selector){
    if(!nodes.has(selector)){
      const classes=new Set();
      nodes.set(selector,{innerHTML:'',textContent:'',hidden:false,disabled:false,value:'',dataset:{},
        classList:{add(...values){values.forEach(value=>classes.add(value));},remove(...values){values.forEach(value=>classes.delete(value));},toggle(value,active){if(active)classes.add(value);else classes.delete(value);},contains(value){return classes.has(value);}},
        setAttribute(){},removeAttribute(){}});
    }
    return nodes.get(selector);
  }
  const data={currentUserId:'player-one',preferences:{inApp:true,email:false,leadHours:[24,1]},emailDeliveryConfigured:false,unreadCount:1,totalCount:1,
    reminders:[{id:'reminder-one',title:'Tournament starts',kind:'starts',tournamentName:'<script>alert("bad")</script>',organisationName:'Club',sport:'Football',targetAt:'2099-01-01T12:00:00Z',timezone:'Asia/Kolkata',read:false}]};
  const context=vm.createContext({Promise,Date,Intl,Set,Map,AbortSignal,
    view:'ring',account:{userId:'player-one'},accountReady:Promise.resolve(),location:{hash:'#ring'},
    document:{body:node('body'),visibilityState:'visible',querySelector:node,querySelectorAll(){return [];},addEventListener(type,listener){if(!listeners.has(type))listeners.set(type,[]);listeners.get(type).push(listener);}},
    render(){},navigate(next){context.view=next;},toast(message){context.lastToast=message;},
    $(selector){return node(selector);},
    escape(value){return String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));},
    setTimeout(callback,delay){const id=++timerId;timers.set(id,{callback,delay});return id;},clearTimeout(id){timers.delete(id);},
    async fetch(url,options){
      requests.push({url,options});
      if(context.response)return context.response(url,options);
      if(options.method==='PATCH'){
        const payload=JSON.parse(options.body);
        if(url.endsWith('/preferences'))Object.assign(data.preferences,payload);
        else if('dismissed' in payload){data.reminders=[];data.unreadCount=0;}
        else{data.reminders[0].read=payload.read;data.unreadCount=Number(!payload.read);}
      }
      return {ok:true,status:200,async json(){return structuredClone(data);}};
    }
  });
  context.window=context;
  vm.runInContext(readFileSync(path.join(__dirname,'../static/sportspace/reminders.js'),'utf8')+'\nglobalThis.reminderTest={state:remindersState,load:remindersLoad,save:remindersSave};',context);
  function fire(type,target){for(const listener of listeners.get(type)||[])listener({target,preventDefault(){}});}
  const click=dataset=>fire('click',{closest(){return {dataset};}});
  const settle=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
  return {context,node,timers,requests,data,fire,click,settle};
}

test('reminders render private API data, escape names and poll only while visible',async()=>{
  const p=page();p.context.navigate('reminders');await p.settle();
  const html=p.node('#content').innerHTML;
  assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
  assert.match(html,/1 unread reminder/);assert.match(html,/Email delivery is not configured/);
  assert.match(html,/device’s timezone/);assert.equal(p.requests[0].url,'/api/reminders');
  assert.equal(p.requests[0].options.headers['X-Dhoyo-Request'],'1');
  assert.equal([...p.timers.values()][0].delay,60000);
  p.context.document.visibilityState='hidden';p.fire('visibilitychange');assert.equal(p.timers.size,0);
  p.context.document.visibilityState='visible';p.fire('visibilitychange');await p.settle();assert.equal(p.timers.size,1);
  p.context.navigate('ring');assert.equal(p.timers.size,0);assert.equal(p.context.view,'ring');
});

test('read and dismiss actions persist through PATCH and refresh server data',async()=>{
  const p=page();p.context.navigate('reminders');await p.settle();
  p.click({reminderRead:'reminder-one',reminderReadValue:'true'});await p.settle();
  assert.ok(p.requests.some(item=>item.url==='/api/reminders/reminder-one'&&JSON.parse(item.options.body||'{}').read===true));
  assert.match(p.node('#content').innerHTML,/Mark unread/);assert.match(p.node('#content').innerHTML,/0 unread/);
  p.click({reminderDismiss:'reminder-one'});await p.settle();
  assert.match(p.node('#content').innerHTML,/all caught up/);
});

test('preference form requires a lead time and saves explicit email opt-in',async()=>{
  const p=page();p.context.navigate('reminders');await p.settle();
  const form={id:'reminders-preferences',elements:{inApp:{checked:true},email:{checked:true}},querySelectorAll(){return [];}};
  p.fire('submit',form);await p.settle();
  assert.match(p.node('#content').innerHTML,/Choose at least one/);
  assert.equal(p.requests.filter(item=>item.options.method==='PATCH').length,0);
  form.querySelectorAll=()=>[{value:'24'},{value:'1'}];
  p.fire('submit',form);await p.settle();
  const request=p.requests.find(item=>item.url==='/api/reminders/preferences');
  assert.deepEqual(JSON.parse(request.options.body),{inApp:true,email:true,leadHours:[24,1]});
  assert.equal(p.context.lastToast,'Reminder preferences saved.');
});

test('failed saves keep the draft and show errors instead of claiming success',async()=>{
  const p=page();p.context.navigate('reminders');await p.settle();
  p.context.response=async(url,options)=>({ok:false,status:503,json:async()=>({error:'Mail preference unavailable'})});
  p.context.reminderTest.state.draft={inApp:true,email:true,leadHours:[1]};
  await p.context.reminderTest.save({email:true},'/preferences');await p.settle();
  assert.match(p.node('#content').innerHTML,/Mail preference unavailable/);
  assert.equal(p.context.reminderTest.state.draft.email,true);assert.equal(p.context.lastToast,undefined);
});

test('stale responses after navigation cannot overwrite the next page',async()=>{
  const p=page();let resolve;
  p.context.response=()=>new Promise(done=>resolve=done);
  p.context.navigate('reminders');await p.settle();
  p.context.navigate('ring');p.node('#content').innerHTML='Your Ring page';
  resolve({ok:true,status:200,json:async()=>p.data});await p.settle();
  assert.equal(p.node('#content').innerHTML,'Your Ring page');assert.equal(p.timers.size,0);
});

test('expired sessions clear private cards and changing accounts clears cached preferences',async()=>{
  const p=page();p.context.navigate('reminders');await p.settle();
  p.context.response=async()=>({ok:false,status:401,json:async()=>({error:'Sign in to continue'})});
  await p.context.reminderTest.load();await p.settle();
  assert.match(p.node('#content').innerHTML,/Sign in to continue/);assert.doesNotMatch(p.node('#content').innerHTML,/Club/);
  p.context.navigate('ring');p.context.account.userId='new-player';p.context.navigate('reminders');
  assert.equal(p.context.reminderTest.state.data,null);
});

test('an old-account GET response cannot repopulate cards after identity changes on the same route',async()=>{
  const p=page();p.context.navigate('reminders');await p.settle();
  let resolve;
  p.context.response=()=>new Promise(done=>resolve=done);
  const loading=p.context.reminderTest.load(true);await p.settle();
  p.context.account.userId='player-two';p.context.render();
  assert.doesNotMatch(p.node('#content').innerHTML,/Club/);assert.equal(p.context.reminderTest.state.data,null);
  resolve({ok:true,status:200,json:async()=>p.data});await loading;await p.settle();
  assert.doesNotMatch(p.node('#content').innerHTML,/Club/);assert.equal(p.context.reminderTest.state.data,null);
});

test('an old-account PATCH completion cannot show success or reuse its preferences after identity changes',async()=>{
  const p=page();p.context.navigate('reminders');await p.settle();
  let resolve;
  p.context.response=()=>new Promise(done=>resolve=done);
  p.context.reminderTest.state.draft={inApp:true,email:true,leadHours:[1]};
  const saving=p.context.reminderTest.save({email:true},'/preferences');await p.settle();
  p.context.account.userId='player-two';p.context.render();
  assert.equal(p.context.reminderTest.state.draft,null);
  resolve({ok:true,status:200,json:async()=>({currentUserId:'player-one',preferences:{email:true}})});
  await saving;await p.settle();
  assert.equal(p.context.lastToast,undefined);assert.equal(p.context.reminderTest.state.data,null);
  assert.doesNotMatch(p.node('#content').innerHTML,/Club/);
});

test('responses identify the cookie owner before any reminder data is displayed',async()=>{
  const p=page();p.data.currentUserId='different-cookie-owner';p.context.navigate('reminders');await p.settle();
  assert.match(p.node('#content').innerHTML,/signed-in account changed/);
  assert.doesNotMatch(p.node('#content').innerHTML,/Club/);assert.equal(p.context.reminderTest.state.data,null);
});

test('account changes without a render also reject old GET results and load the new account',async()=>{
  const p=page();p.context.navigate('reminders');await p.settle();
  let resolve;
  p.context.response=()=>new Promise(done=>resolve=done);
  const loading=p.context.reminderTest.load(true);await p.settle();
  p.context.account.userId='player-two';
  const newData={...p.data,currentUserId:'player-two',reminders:[],unreadCount:0,totalCount:0};
  p.context.response=async()=>({ok:true,status:200,json:async()=>newData});
  resolve({ok:true,status:200,json:async()=>p.data});await loading;await p.settle();
  assert.equal(p.context.reminderTest.state.data.currentUserId,'player-two');
  assert.doesNotMatch(p.node('#content').innerHTML,/Club/);assert.match(p.node('#content').innerHTML,/all caught up/);
});

test('a form submitted from an obsolete account cannot change the new account preferences',async()=>{
  const p=page();p.context.navigate('reminders');await p.settle();
  p.context.account.userId='player-two';
  await p.context.reminderTest.save({email:true},'/preferences');await p.settle();
  assert.equal(p.requests.filter(item=>item.options.method==='PATCH').length,0);
  assert.equal(p.context.lastToast,undefined);
});
