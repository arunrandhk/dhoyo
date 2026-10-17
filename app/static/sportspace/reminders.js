// Private reminders use the signed-in server account, never browser demo data.
const remindersPreviousRender=render,remindersPreviousNavigate=navigate;
const remindersState={request:0,loading:false,saving:false,error:'',data:null,draft:null,timer:null,owner:null,whatsappCodeSent:false};
const remindersActive=()=>view==='reminders';
const remindersVisible=()=>remindersActive()&&document.visibilityState!=='hidden';
function remindersStop(){clearTimeout(remindersState.timer);remindersState.timer=null;}
function remindersSyncAccount(){
  if(remindersState.owner===account.userId)return;
  ++remindersState.request;remindersStop();remindersState.owner=account.userId;
  remindersState.data=null;remindersState.draft=null;remindersState.error='';
  remindersState.loading=false;remindersState.saving=false;
}
const remindersCurrent=(request,owner)=>request===remindersState.request&&owner===account.userId&&owner===remindersState.owner&&remindersActive();
function remindersSchedule(){
  remindersStop();
  if(remindersVisible())remindersState.timer=setTimeout(()=>remindersLoad(true),60000);
}
async function remindersRequest(path='',method='GET',payload,owner){
  await accountReady;
  if(owner!==account.userId||owner!==remindersState.owner)throw new Error('The signed-in account changed. Refresh reminders.');
  const response=await fetch('/api/reminders'+path,{
    method,cache:'no-store',headers:{'Content-Type':'application/json','X-Dhoyo-Request':'1'},
    body:payload===undefined?undefined:JSON.stringify(payload),signal:AbortSignal.timeout(15000)
  });
  let value;
  try{value=await response.json();}catch{throw new Error('Unable to load reminders. Please try again.');}
  if(!response.ok){
    const error=new Error(value.error||'Unable to load reminders. Please try again.');
    error.clearReminderData=response.status===401||response.status===403;throw error;
  }
  if(value.currentUserId!==owner){const error=new Error('The signed-in account changed. Refresh reminders.');error.clearReminderData=true;throw error;}
  return value;
}
function remindersTime(value){
  try{return new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short',timeZoneName:undefined}).format(new Date(value));}
  catch{return 'Date unavailable';}
}
function remindersRelative(value){
  const milliseconds=new Date(value).getTime()-Date.now();
  if(!Number.isFinite(milliseconds))return '';
  if(milliseconds<=0)return 'Starting now';
  if(milliseconds<60000)return 'In less than a minute';
  const hours=milliseconds/3600000;
  const amount=hours>=24?Math.ceil(hours/24):hours>=1?Math.ceil(hours):Math.ceil(milliseconds/60000);
  const unit=hours>=24?'day':hours>=1?'hour':'minute';
  return `In ${amount} ${unit}${amount===1?'':'s'}`;
}
function remindersCards(){
  const data=remindersState.data;
  if(!data)return remindersState.error?'':'<p class="reminders-empty" role="status">Loading your reminders…</p>';
  if(!data.preferences.inApp)return '<div class="reminders-empty"><h2>In-app reminders are paused.</h2><p>Enable them above to see your upcoming tournaments.</p></div>';
  if(!data.reminders.length)return '<div class="reminders-empty"><h2>You’re all caught up.</h2><p>Join a tournament to see start times and registration deadlines here. Withdrawn teams and cancelled events disappear automatically.</p><a class="org-button" href="#tournaments">Explore tournaments</a></div>';
  return data.reminders.map(item=>`<article class="reminders-card ${item.read?'is-read':'is-unread'}" aria-label="${escape(item.tournamentName)}: ${escape(item.title)}">
    <div class="reminders-card-heading"><span class="reminders-label">${escape(item.title)}</span>${item.read?'':'<span class="reminders-unread">Unread</span>'}</div>
    <h2>${escape(item.tournamentName)}</h2>
    <p>${escape(item.organisationName)}${item.organisationName?' · ':''}${escape(item.sport)}</p>
    <p class="reminders-date"><time datetime="${escape(item.targetAt)}">${escape(remindersTime(item.targetAt))}</time><strong>${escape(remindersRelative(item.targetAt))}</strong></p>
    ${item.kind==='registration_closes'?'<p class="reminders-note">Your team is already registered. Check any team changes before registration closes.</p>':''}
    <div class="reminders-actions"><a class="org-button" href="#tournaments">View tournaments</a><button type="button" class="org-button" data-reminder-read="${escape(item.id)}" data-reminder-read-value="${!item.read}" ${remindersState.saving?'disabled':''}>Mark ${item.read?'unread':'read'}</button><button type="button" class="reminders-dismiss" data-reminder-dismiss="${escape(item.id)}" ${remindersState.saving?'disabled':''}>Dismiss</button></div>
  </article>`).join('');
}
function remindersForm(){
  if(!remindersState.data)return '';
  const prefs=remindersState.draft||remindersState.data.preferences;
  return `<form id="reminders-preferences" class="reminders-preferences"><div><h2>Your reminder preferences</h2><p>Start times and registration deadlines for tournaments you’ve joined.</p></div>
    <label class="reminders-toggle"><input type="checkbox" name="inApp" ${prefs.inApp?'checked':''}>Show in-app reminders</label>
    <label class="reminders-toggle"><input type="checkbox" name="email" ${prefs.email?'checked':''}>Email me tournament reminders</label>
    ${remindersState.data.phoneVerified?`<label class="reminders-toggle"><input type="checkbox" name="whatsapp" ${prefs.whatsapp?'checked':''}>WhatsApp me tournament reminders</label>${remindersState.data.whatsappDeliveryConfigured?'':'<p class="reminders-note">WhatsApp sending is not configured yet. You can turn this preference off here.</p>'}`:remindersState.data.whatsappDeliveryConfigured&&remindersState.data.phonePresent?`<div class="reminders-whatsapp-verify"><p>Verify your account phone to enable WhatsApp reminders. By requesting a code, you agree to receive tournament reminder messages in WhatsApp.</p>${remindersState.whatsappCodeSent?'<label class="reminders-code-label">Six-digit verification code<input name="whatsappCode" type="text" inputmode="numeric" pattern="[0-9]{6}" minlength="6" maxlength="6" autocomplete="one-time-code"></label><button type="button" class="org-button" data-whatsapp-verify>Verify &amp; enable WhatsApp</button>':'<button type="button" class="org-button" data-whatsapp-send>Verify phone &amp; enable WhatsApp</button>'}</div>`:`<p class="reminders-note">WhatsApp reminders are not ready. Configure the WhatsApp Business sender and add a phone number to your account.</p>`}
    <fieldset><legend>Remind me before each deadline</legend><div class="reminders-leads">${[[48,'2 days'],[24,'1 day'],[6,'6 hours'],[1,'1 hour']].map(([hours,label])=>`<label><input type="checkbox" name="leadHours" value="${hours}" ${prefs.leadHours.includes(hours)?'checked':''}>${label}</label>`).join('')}</div></fieldset>
    <p class="reminders-note">Times below use your device’s timezone. Email reminders start enabled for new accounts and can be turned off here. They go only to your verified account address. WhatsApp requires a verified phone and explicit opt-in.</p>
    ${remindersState.data.emailDeliveryConfigured?'':'<p class="reminders-note">Email delivery is not configured yet. You can save your preference for when it is available.</p>'}
    <div class="reminders-actions"><button class="primary" type="submit" ${remindersState.saving?'disabled':''}>${remindersState.saving?'Saving…':'Save preferences'}</button><span role="status" id="reminders-save-status"></span></div>
  </form>`;
}
function remindersRender(){
  // Identity can change while this route stays open. Drop cards and drafts
  // synchronously before writing any markup for the newly signed-in account.
  remindersSyncAccount();
  document.body.classList.add('ring-experience','reminders-view');
  document.body.classList.remove('ring-home','arena-view','org-service-view','progression-view');
  if(typeof orgAccountChrome==='function')orgAccountChrome();
  $('#eyebrow').textContent='YOUR NEXT GAME';$('#title').textContent='Stay ready for game day.';
  $('#subtitle').textContent='Your tournament starts and team deadlines, in one place.';
  $('.page-heading').hidden=false;$('#create').hidden=true;$('#filters').hidden=true;
  $('#search').disabled=true;$('#search').placeholder='Your tournament reminders';
  document.querySelectorAll('.sidebar nav button').forEach(button=>{
    const active=(button.dataset.view||button.dataset.orgRoute)==='reminders';
    button.classList.toggle('active',active);button.setAttribute('aria-current',active?'page':'false');
  });
  document.querySelectorAll('[data-bottom-route]').forEach(link=>{
    const active=link.dataset.bottomRoute==='reminders';link.classList.toggle('active',active);
    if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
  });
  const count=remindersState.data?.unreadCount||0;
  $('#content').innerHTML=`<div class="reminders-workspace"><div class="reminders-toolbar"><p>${count} unread reminder${count===1?'':'s'}</p><div class="reminders-actions"><a class="org-button" href="#progress">Achievements &amp; rankings</a><button type="button" class="org-button" data-reminders-refresh ${remindersState.loading||remindersState.saving?'disabled':''}>${remindersState.loading?'Refreshing…':'Refresh'}</button></div></div>
    ${remindersState.error?`<p class="reminders-error" role="alert">${escape(remindersState.error)}</p>`:''}
    ${remindersForm()}<section class="reminders-list" aria-label="Upcoming tournament reminders">${remindersCards()}</section>
    ${remindersState.data?.totalCount>100?'<p class="reminders-note">Showing the next 100 reminders.</p>':''}</div>`;
}
async function remindersLoad(background=false){
  remindersSyncAccount();
  if(!remindersActive()||remindersState.loading||remindersState.saving)return;
  const request=++remindersState.request,owner=account.userId;
  remindersState.loading=true;
  if(!background)render();
  try{
    const data=await remindersRequest('','GET',undefined,owner);
    if(!remindersCurrent(request,owner))return;
    if(!data||!Array.isArray(data.reminders)||!data.preferences)throw new Error('Unable to read your reminder preferences.');
    remindersState.data=data;remindersState.error='';
  }catch(error){if(remindersCurrent(request,owner)){if(error.clearReminderData){remindersState.data=null;remindersState.draft=null;}remindersState.error=error.message;}}
  finally{
    if(request===remindersState.request){
      remindersState.loading=false;
      if(owner!==account.userId){remindersSyncAccount();if(remindersActive()){render();remindersLoad(true);}return;}
      if(remindersActive())render();remindersSchedule();
    }
  }
}
function remindersDraft(form){
  return {inApp:form.elements.inApp.checked,email:form.elements.email.checked,
    ...(form.elements.whatsapp?{whatsapp:form.elements.whatsapp.checked}:{}),
    leadHours:[...form.querySelectorAll('[name="leadHours"]:checked')].map(input=>Number(input.value))};
}
async function remindersSave(payload,path=''){
  const sameAccount=remindersState.owner===account.userId;
  remindersSyncAccount();
  if(!sameAccount){if(remindersActive()){render();remindersLoad(true);}return;}
  if(remindersState.saving)return;
  const request=++remindersState.request,owner=account.userId;
  remindersState.loading=false;remindersState.saving=true;remindersState.error='';render();
  let saved=false;
  try{
    await remindersRequest(path,'PATCH',payload,owner);
    if(!remindersCurrent(request,owner))return;
    if(path==='/preferences')remindersState.draft=null;
    saved=true;
    toast(path==='/preferences'?'Reminder preferences saved.':'Reminder updated.');
  }catch(error){if(remindersCurrent(request,owner)){if(error.clearReminderData){remindersState.data=null;remindersState.draft=null;}remindersState.error=error.message;}}
  finally{
    if(request===remindersState.request){
      remindersState.saving=false;
      if(owner!==account.userId){remindersSyncAccount();if(remindersActive()){render();remindersLoad(true);}return;}
      if(remindersActive()){render();if(saved)remindersLoad(true);else remindersSchedule();}
    }
  }
}
render=function(){if(remindersActive())remindersRender();else remindersPreviousRender();};
navigate=function(next){
  const route=(next||'ring').split('/')[0];
  remindersStop();
  if(route!=='reminders'){
    ++remindersState.request;remindersState.loading=false;remindersState.saving=false;
    document.body.classList.remove('reminders-view');remindersPreviousNavigate(next);return;
  }
  if(!remindersActive()){
    ++remindersState.request;remindersState.loading=false;remindersState.saving=false;
    remindersState.error='';remindersState.draft=null;
  }
  remindersSyncAccount();
  view='reminders';$('#search').value='';render();remindersLoad();
};
document.addEventListener('click',event=>{
  if(!remindersActive())return;
  const button=event.target.closest('button');if(!button)return;
  if('remindersRefresh' in button.dataset)remindersLoad();
  else if('whatsappSend' in button.dataset)remindersWhatsAppSend();
  else if('whatsappVerify' in button.dataset)remindersWhatsAppVerify();
  else if(button.dataset.reminderRead)remindersSave({read:button.dataset.reminderReadValue==='true'},'/'+encodeURIComponent(button.dataset.reminderRead));
  else if(button.dataset.reminderDismiss)remindersSave({dismissed:true},'/'+encodeURIComponent(button.dataset.reminderDismiss));
});
async function remindersWhatsAppSend(){
  if(remindersState.saving||!remindersState.data?.whatsappDeliveryConfigured)return;
  remindersState.saving=true;render();
  try{await remindersRequest('/whatsapp-verification','POST',{action:'send'},remindersState.owner);remindersState.whatsappCodeSent=true;toast('WhatsApp verification code sent.');}
  catch(error){remindersState.error=error.message;}
  finally{remindersState.saving=false;if(remindersActive())render();}
}
async function remindersWhatsAppVerify(){
  if(remindersState.saving)return;
  const code=document.querySelector('[name="whatsappCode"]')?.value||'';
  if(!/^[0-9]{6}$/.test(code)){remindersState.error='Enter the six-digit code sent to WhatsApp.';render();return;}
  remindersState.saving=true;render();
  try{
    const result=await remindersRequest('/whatsapp-verification','POST',{action:'verify',code},remindersState.owner);
    remindersState.whatsappCodeSent=false;
    if(remindersState.data){remindersState.data.phoneVerified=true;remindersState.data.preferences=result.preferences;}
    toast(result.message||'WhatsApp reminders enabled.');
  }catch(error){remindersState.error=error.message;}
  finally{remindersState.saving=false;if(remindersActive())render();}
}
document.addEventListener('change',event=>{
  const form=event.target.closest('#reminders-preferences');
  if(form)remindersState.draft=remindersDraft(form);
});
document.addEventListener('submit',event=>{
  if(event.target.id!=='reminders-preferences')return;
  event.preventDefault();
  const prefs=remindersDraft(event.target);remindersState.draft=prefs;
  if(!prefs.leadHours.length){remindersState.error='Choose at least one reminder lead time.';render();return;}
  remindersSave(prefs,'/preferences');
});
document.addEventListener('visibilitychange',()=>{if(remindersVisible())remindersLoad(true);else remindersStop();});
accountReady.then(()=>{if(location.hash.split('/')[0]==='#reminders')navigate('reminders');});
