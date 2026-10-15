// Persistent ground booking and tournaments share the signed-in Ring identity.
// Loaded last so existing social and player-profile renderers remain intact.
const orgPreviousRender=render,orgPreviousNavigate=navigate;
const orgServiceRoutes=['organisation','grounds','tournaments','activity'];
const orgDashboardTabs=['overview','grounds','tournaments','bookings'];
const orgService={route:'',request:0,loading:false,error:'',tab:'overview',status:'all',syncedAt:null,organisation:null,grounds:[],bookings:[],tournaments:[],payments:null,busy:new Set()};
const orgIsOrganisation=()=>account.accountType==='organisation';
const orgIsService=()=>orgServiceRoutes.includes(view);
const orgSports=['Football','Cricket','Basketball','Badminton','Tennis','Running','Esports','Swimming','Volleyball'];
const orgDeviceTimezone=()=>Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';
const orgPrice=(amount,currency='INR')=>new Intl.NumberFormat('en-IN',{style:'currency',currency,maximumFractionDigits:0}).format(Number(amount)||0);
function orgTime(value,timezone='UTC'){
  try{return new Intl.DateTimeFormat('en-IN',{dateStyle:'medium',timeStyle:'short',timeZone:timezone}).format(new Date(value));}
  catch{return 'Date unavailable';}
}
function orgDateInTimezone(timezone){
  const parts=new Intl.DateTimeFormat('en-CA',{year:'numeric',month:'2-digit',day:'2-digit',timeZone:timezone}).formatToParts(new Date());
  const value=type=>parts.find(part=>part.type===type).value;
  return `${value('year')}-${value('month')}-${value('day')}`;
}
const orgFuture=value=>new Date(value).getTime()>Date.now();
const orgBadge=value=>`<span class="org-status" data-status="${escape(String(value).toLowerCase())}">${escape(value)}</span>`;
const orgEmpty=(title,text,action='')=>`<div class="org-empty"><h3>${escape(title)}</h3><p>${escape(text)}</p>${action}</div>`;
const orgSportOptions=(selected='Football')=>orgSports.map(s=>`<option value="${escape(s)}" ${s===selected?'selected':''}>${escape(s)}</option>`).join('');
const orgFormats={single_elimination:'Single elimination',round_robin:'Round robin',groups_knockout:'Groups + knockout',custom:'Custom format'};
const orgFormatName=event=>orgFormats[event.format]||orgFormats.single_elimination;
const orgSectionHeader=(number,title,description='')=>number===null?`<h3>${escape(title)}</h3>${description?`<p class="org-help">${escape(description)}</p>`:''}`:`<div class="org-section-header"><span class="org-section-number" aria-hidden="true">${number}</span><div><h3>${escape(title)}</h3>${description?`<p class="org-help">${escape(description)}</p>`:''}</div></div>`;
const orgTextField=(label,name,value,max,placeholder='',rows=3)=>`<label class="field">${escape(label)}<textarea name="${name}" rows="${rows}" maxlength="${max}" placeholder="${escape(placeholder)}">${escape(value||'')}</textarea></label>`;
const orgInputField=(label,name,value,max,placeholder='')=>`<label class="field">${escape(label)}<input name="${name}" value="${escape(value||'')}" maxlength="${max}" placeholder="${escape(placeholder)}"></label>`;
const orgPaymentMethods={arrange_with_organiser:'Arrange with organiser',cash:'Cash',upi:'UPI',bank_transfer:'Bank transfer'};
const orgPaymentLabels={unpaid:'Payment due',paid:'Paid',not_required:'No payment required',refund_due:'Refund due',refunded:'Refunded',cancelled:'Payment cancelled'};
const orgPaymentBadge=record=>`<span class="org-status org-payment-status" data-status="${escape(record.paymentStatus||'unpaid')}">${escape(orgPaymentLabels[record.paymentStatus]||'Payment due')}</span>`;
const orgAmount=record=>Number(record.totalAmount??record.entryFee??record.price)||0;
function orgMoneyFields(item,kind,number){
  const ground=kind==='ground';
  return `<section class="org-form-section">${orgSectionHeader(number,'Money & payment terms',ground?'Set the hourly rate and any refundable booking deposit.':'Set the team entry fee and cash prize pool.')}<div class="org-form-grid"><label class="field">${ground?'Price per hour':'Entry fee per team'} (INR)<input name="${ground?'pricePerHour':'entryFee'}" type="number" min="0" max="100000" step="1" value="${escape((ground?item.pricePerHour:item.entryFee)??0)}" required><span class="org-field-hint">Enter 0 for ${ground?'free bookings':'free entry'}.</span></label><label class="field">${ground?'Refundable deposit per booking':'Cash prize pool'} (INR)<input name="${ground?'deposit':'prizePool'}" type="number" min="0" max="${ground?'100000':'10000000'}" step="1" value="${escape((ground?item.deposit:item.prizePool)??0)}" required><span class="org-field-hint">${ground?'Added once to each booking. Explain when it is returned below.':'Total cash prizes offered across the competition.'}</span></label><label class="field">Payment method<select name="paymentMethod">${Object.entries(orgPaymentMethods).map(([value,label])=>`<option value="${value}" ${(item.paymentMethod||'arrange_with_organiser')===value?'selected':''}>${label}</option>`).join('')}</select></label>${ground?'':orgInputField('Prizes & rewards','prize',item.prize,300,'e.g. Winner ₹5,000, runner-up ₹2,000 and trophies')}</div>${orgTextField('Payment instructions','paymentInstructions',item.paymentInstructions,1000,'Where and when to pay; contact or payment details')}${orgTextField('Cancellation & refund policy','refundPolicy',item.refundPolicy,1000,ground?'Cancellation deadline and how the deposit is returned':'Withdrawal deadline and refund arrangements')}<p class="org-field-hint">Paid cancellations are tracked as a full refund due until you record that the money was returned.</p><p class="org-payment-note">Payments are made directly to the organiser. Received payments and completed refunds can be recorded in your workspace.</p></section>`;
}
function orgMoneyInformation(data,kind){
  const payload={};
  for(const key of ['paymentMethod','paymentInstructions','refundPolicy'])if(data.has(key))payload[key]=String(data.get(key)||'').trim();
  if(payload.paymentMethod&&!Object.hasOwn(orgPaymentMethods,payload.paymentMethod))throw new Error('Choose a supported payment method.');
  for(const key of kind==='ground'?['pricePerHour','deposit']:['entryFee','prizePool'])if(data.has(key)){
    const raw=String(data.get(key)??'').trim(),amount=Number(raw),maximum=key==='prizePool'?10000000:100000;
    if(!raw||!Number.isInteger(amount)||amount<0||amount>maximum)throw new Error('Enter a whole-number amount from 0 to '+maximum.toLocaleString('en-IN')+' INR.');
    payload[key]=amount;
  }
  return payload;
}
function orgMoneyPanel(item,kind,snapshot=null){
  const ground=kind==='ground',amount=ground?Number(item.pricePerHour)||0:Number(item.entryFee)||0,deposit=ground?Number(item.deposit)||0:0;
  const record=snapshot||item,currency=record.currency||item.currency||'INR';
  const values=snapshot?[[ground?'Ground hire':'Team entry',ground?Number(record.price)||0:Number(record.entryFee??record.totalAmount)||0],...(ground&&Number(record.deposit)>0?[['Refundable deposit',Number(record.deposit)]]:[]),...(!ground?[['Cash prize pool',Number(item.prizePool)||0]]:[]),['Agreed total',orgAmount(record)]]:ground?[['Ground hire / hour',amount],['Refundable deposit',deposit],['Total for one hour',amount+deposit]]:[['Entry / team',amount],['Cash prize pool',Number(item.prizePool)||0]];
  const method=record.paymentMethod||item.paymentMethod||'arrange_with_organiser';
  const instructions=snapshot?record.paymentInstructions:item.paymentInstructions,policy=snapshot?record.refundPolicy:item.refundPolicy;
  return `<section aria-label="Money details"><dl class="org-details">${values.map(([label,value])=>`<div><dt>${escape(label)}</dt><dd>${escape(orgPrice(value,currency))}</dd></div>`).join('')}</dl>${record.paymentStatus?orgPaymentBadge(record):''}<p class="org-help">${escape(orgPaymentMethods[method]||orgPaymentMethods.arrange_with_organiser)} · Pay directly to the organiser.</p>${instructions?`<p class="org-help org-detail-copy">${escape(instructions)}</p>`:''}${policy?`<p class="org-help org-detail-copy">Cancellation & refunds: ${escape(policy)}</p>`:''}${record.paymentReference?`<p class="org-help">Payment reference: ${escape(record.paymentReference)}</p>`:''}</section>`;
}
function orgPaymentActions(record,kind,eventId=''){
  if(!orgIsOrganisation()||orgAmount(record)<=0||record.purpose==='tournament')return '';
  const action=record.paymentStatus==='unpaid'&&['confirmed','registered'].includes(record.status)?'paid':record.paymentStatus==='refund_due'&&record.status==='cancelled'?'refunded':kind==='booking'&&record.paymentStatus==='paid'&&record.status==='confirmed'&&Number(record.deposit)>0&&!record.depositRefunded&&!orgFuture(record.endsAt)?'deposit_refunded':null;
  if(!action)return '';
  return `<button type="button" class="org-button" data-org-payment="${escape(record.id)}" data-org-payment-kind="${kind}" data-org-payment-event="${escape(eventId)}" data-org-payment-status="${action}">${action==='paid'?'Record payment':action==='deposit_refunded'?'Record deposit refund':'Record refund'}</button>`;
}
function orgLocalInput(value,timezone){
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value));
  const part=type=>parts.find(item=>item.type===type).value;
  return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}`;
}
function orgLocalInstant(value,timezone){
  if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value))throw new Error('Enter a valid date and time.');
  const wall=Date.parse(value+'Z');
  if(!Number.isFinite(wall)||new Date(wall).toISOString().slice(0,16)!==value)throw new Error('Enter a valid date and time.');
  const offsets=new Set();
  try{
    for(let hours=-36;hours<=36;hours+=6){
      const probe=wall+hours*3600000;
      offsets.add(Date.parse(orgLocalInput(probe,timezone)+'Z')-probe);
    }
  }catch{throw new Error('Choose a valid IANA timezone, such as Asia/Kolkata.');}
  const matches=[...offsets].map(offset=>wall-offset).filter(candidate=>orgLocalInput(candidate,timezone)===value);
  if(matches.length===0)throw new Error('This local time does not exist because the clocks change. Choose another time.');
  if(matches.length>1)throw new Error('This local time occurs twice when the clocks change. Choose an unambiguous time.');
  return new Date(matches[0]).toISOString();
}
const orgChronological=items=>[...items].sort((a,b)=>new Date(a.startsAt)-new Date(b.startsAt));
const orgUpcomingBookings=()=>orgChronological(orgService.bookings.filter(booking=>booking.status==='confirmed'&&orgFuture(booking.endsAt)));
const orgActiveEvents=()=>orgChronological(orgService.tournaments.filter(event=>['open','live'].includes(event.status)&&orgFuture(event.endsAt)));
async function orgRequest(path,method='GET',body,timeout=15000){
  await accountReady;
  let response;
  try{response=await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(timeout)});}
  catch{throw new Error('Could not reach the service. Check your connection and try again.');}
  const value=await response.json().catch(()=>null);
  if(!response.ok)throw new Error(value?.error||'The request could not be completed. Try again.');
  if(!value||typeof value!=='object')throw new Error('The service returned an unexpected response. Try again.');
  return value;
}
function orgResult(value,key,status){
  const item=value?.[key];
  if(!item||typeof item.id!=='string'||(status&&item.status!==status))throw new Error('The service did not confirm this action. Refresh your activity before trying again.');
  return item;
}
async function orgLoad(route=view){
  if(!orgServiceRoutes.includes(route))return;
  const request=++orgService.request;
  orgService.route=route;orgService.loading=true;orgService.error='';render();
  try{
    await accountReady;
    if(request!==orgService.request||view!==route||!account.userId)return;
    if(route==='organisation'){
      if(!orgIsOrganisation()){orgService.organisation=null;return;}
      const result=await orgRequest('organisations/me');
      if(request!==orgService.request||view!==route)return;
      orgService.organisation=result.organisation;orgService.grounds=result.grounds||[];orgService.bookings=result.bookings||[];orgService.tournaments=result.tournaments||[];orgService.payments=result.payments||null;
    }else if(route==='grounds'){
      const [result,owned]=await Promise.all([orgRequest('grounds'),orgIsOrganisation()?orgRequest('organisations/me'):Promise.resolve(null)]);
      if(request!==orgService.request||view!==route)return;
      orgService.grounds=result.grounds||[];
      if(owned){orgService.organisation=owned.organisation;orgService.bookings=owned.bookings||[];orgService.payments=owned.payments||null;}
    }else if(route==='tournaments'){
      const [events,owned]=await Promise.all([orgRequest('tournaments'),orgIsOrganisation()?orgRequest('organisations/me'):Promise.resolve(null)]);
      if(request!==orgService.request||view!==route)return;
      orgService.tournaments=events.tournaments||[];
      if(owned){orgService.organisation=owned.organisation;orgService.grounds=owned.grounds||[];}
    }else{
      const [reservations,events]=await Promise.all([orgRequest('bookings'),orgRequest('tournaments')]);
      if(request!==orgService.request||view!==route)return;
      orgService.bookings=reservations.bookings||[];orgService.tournaments=events.tournaments||[];
    }
  }catch(error){if(request===orgService.request&&view===route)orgService.error=error.message;}
  finally{if(request===orgService.request&&view===route){orgService.loading=false;if(!orgService.error)orgService.syncedAt=new Date();render();}}
}
function orgNavigation(){
  const routes=orgIsOrganisation()?[['organisation','Organisation workspace'],['grounds','Ground directory'],['tournaments','Discover tournaments']]:[['grounds','Book a ground'],['tournaments','Tournaments'],['activity','Saved & activity']];
  return `<nav class="org-service-nav" aria-label="Grounds and tournaments">${routes.map(([route,label])=>`<a href="#${route}" ${view===route?'aria-current="page"':''}>${escape(label)}</a>`).join('')}<button type="button" class="org-button org-refresh" data-org-retry ${orgService.loading?'disabled':''}>Refresh</button></nav>`;
}
function orgGroundCard(ground){
  const owned=orgIsOrganisation()&&ground.organisationId===account.organisationId;
  const description=ground.description?`<p class="org-event-description">${escape(ground.description.length>180?ground.description.slice(0,177)+'…':ground.description)}</p>`:'';
  const tags=[ground.surface,...(ground.amenities||[]).slice(0,4)].filter(Boolean);
  return `<article class="org-card org-ground-card"><div class="org-event-top"><div class="org-card-symbol" aria-hidden="true">${icon('map-pin')}</div>${owned?orgBadge('Your ground'):''}</div><span class="org-kicker">${escape(ground.sport)} / ${escape(ground.city)}</span><h2>${escape(ground.name)}</h2><p>${escape(ground.address)}</p><p class="org-owner">Managed by ${escape(ground.organisationName||orgService.organisation?.name||'your organisation')}</p>${description}${tags.length?`<div class="org-event-tags">${tags.map(tag=>`<span>${escape(tag)}</span>`).join('')}</div>`:''}<dl class="org-details"><div><dt>Opening hours</dt><dd>${escape(ground.opensAt)}–${escape(ground.closesAt)}</dd></div><div><dt>Venue timezone</dt><dd>${escape(ground.timezone)}</dd></div><div><dt>Player capacity</dt><dd>${escape(ground.capacity||22)}</dd></div></dl><div class="org-card-footer"><div><strong>${escape(orgPrice(ground.pricePerHour,ground.currency))}</strong><small>per hour · 60-minute slots</small>${ground.deposit?`<small>+ ${escape(orgPrice(ground.deposit,ground.currency))} refundable deposit</small>`:''}</div>${!orgIsOrganisation()?`<button class="primary" data-org-book="${escape(ground.id)}">Choose a slot</button>`:owned?`<button class="org-button" data-org-edit-ground="${escape(ground.id)}">Edit ground</button>`:orgBadge('Organisation ground')}</div><div class="org-actions"><button class="org-button" data-org-ground-details="${escape(ground.id)}">View ground details</button></div></article>`;
}
function orgTournamentCard(event){
  const owner=orgIsOrganisation()&&event.organisationId===account.organisationId;
  const activeRegistration=event.myRegistration?.status==='registered';
  const joinable=event.status==='open'&&orgFuture(event.registrationClosesAt)&&event.spotsLeft>0;
  const disabled=orgService.busy.has(event.id)?'disabled':'';
  let actions='';
  if(owner){
    const buttons=[];
    if(event.status==='draft')buttons.push(['publish','Publish event',!orgFuture(event.registrationClosesAt)]);
    if(event.status==='open')buttons.push(['start','Start tournament',orgFuture(event.startsAt)||!orgFuture(event.endsAt)||event.registrationCount<2]);
    if(event.status==='live')buttons.push(['complete','Complete tournament']);
    if(['draft','open'].includes(event.status))buttons.push(['cancel','Cancel event']);
    actions=(event.status==='draft'?`<button class="org-button" data-org-edit-event="${escape(event.id)}">Edit draft</button>`:event.status==='open'&&orgFuture(event.startsAt)?`<button class="org-button" data-org-edit-details="${escape(event.id)}">Edit details</button>`:'')+buttons.map(([action,label,unavailable])=>`<button class="${action==='cancel'?'org-button org-danger':'primary'}" data-org-event-action="${action}" data-org-event-id="${escape(event.id)}" ${disabled||unavailable?'disabled':''}>${label}</button>`).join('')+`<button class="org-button" data-org-roster="${escape(event.id)}">View teams</button>`;
  }else if(!orgIsOrganisation()){
    if(activeRegistration)actions=orgBadge('Team registered')+(event.status==='open'&&orgFuture(event.registrationClosesAt)?`<button class="org-button" data-org-edit-registration="${escape(event.id)}" ${disabled}>Edit team</button>`:'')+(event.status==='open'&&orgFuture(event.startsAt)?`<button class="org-button" data-org-withdraw="${escape(event.id)}" ${disabled}>Withdraw team</button>`:'');
    else if(event.isParticipant)actions=orgBadge('Already registered as a team member');
    else if(joinable)actions=`<button class="primary" data-org-register="${escape(event.id)}">Register team</button>`;
    else actions=orgBadge(event.status==='open'?(event.spotsLeft<=0?'Full':'Registration closed'):event.status);
  }
  const published=event.publishedAt===undefined?['open','live','completed'].includes(event.status):Boolean(event.publishedAt);
  const visibility=owner?`<p class="org-visibility ${published?'org-visible':'org-private'}">${published?'Published · Visible in player accounts':event.status==='draft'?'Private draft · Only your organisation can see this. Publish event to make it visible in player accounts.':'Private event · This event was never published.'}</p>`:'';
  const progress=Math.max(0,Math.min(100,Number(event.registrationCount)/Math.max(1,Number(event.capacity))*100))||0;
  actions+=`<button class="org-button" data-org-event-details="${escape(event.id)}">View details</button>`;
  const description=event.description?`<p class="org-event-description">${escape(event.description.length>180?event.description.slice(0,177)+'…':event.description)}</p>`:'';
  const tags=`<div class="org-event-tags"><span>${escape(orgFormatName(event))}</span><span>${escape(event.teamSize||5)} players / team</span><span>${event.entryFee?escape(orgPrice(event.entryFee))+' entry / team':'Free entry'}</span>${event.prizePool?`<span>${escape(orgPrice(event.prizePool))} cash prize pool</span>`:event.prize?'<span>Prizes available</span>':''}</div>${activeRegistration?`<div class="org-payment-note">Your entry: ${escape(orgPrice(orgAmount(event.myRegistration),event.myRegistration.currency||'INR'))} ${orgPaymentBadge({...event.myRegistration,paymentStatus:event.myRegistration.paymentStatus||(event.entryFee?'unpaid':'not_required')})}</div>`:''}`;
  return `<article class="org-card org-event"><div class="org-event-top"><span class="org-kicker">${escape(event.sport)} / ${event.eventType==='online'?'ONLINE':'ON THE FIELD'}</span>${orgBadge(event.status)}</div><h2>${escape(event.name)}</h2>${visibility}<p class="org-owner">Hosted by ${escape(event.organisationName||orgService.organisation?.name||'your organisation')}</p>${description}${tags}<dl class="org-details"><div><dt>Starts</dt><dd>${escape(orgTime(event.startsAt,event.timezone))}</dd></div><div><dt>Ends</dt><dd>${escape(orgTime(event.endsAt,event.timezone))}</dd></div><div><dt>Timezone</dt><dd>${escape(event.timezone)}</dd></div><div><dt>Venue</dt><dd>${escape(event.eventType==='online'?event.onlinePlatform||'Online':event.groundName||'Ground unavailable')}</dd></div><div><dt>Registration closes</dt><dd>${escape(orgTime(event.registrationClosesAt,event.timezone))}</dd></div></dl><div class="org-capacity"><strong>${escape(event.registrationCount)} / ${escape(event.capacity)} teams</strong><span>${escape(event.spotsLeft)} spots left</span></div><div class="org-capacity-track" aria-hidden="true"><span style="width:${progress}%"></span></div>${activeRegistration?`<p class="org-registration">Your team: ${escape(event.myRegistration.teamName)}</p>${event.playerEmailConfirmation==='activation_link'?`<p class="org-help">${(event.myRegistration.playerEmails||[]).filter(player=>player.acknowledgementStatus==='acknowledged').length} / ${(event.myRegistration.playerEmails||[]).length} players Acknowledged · ${(event.myRegistration.playerEmails||[]).filter(player=>player.acknowledgementStatus!=='acknowledged').length} Pending</p>`:''}`:''}${owner&&event.status==='draft'?`<p class="org-help">${orgFuture(event.registrationClosesAt)?'Publishing opens registration and reserves the venue.':'Registration deadline has passed. Edit the draft dates before publishing.'}</p>`:''}${owner&&event.status==='open'?`<p class="org-help">${!orgFuture(event.endsAt)?'The scheduled time has ended. Cancel this event to close registration.':event.registrationCount<2?'At least two registered teams are needed before you can start.':orgFuture(event.startsAt)?'Ready to go. Start becomes available at the scheduled time.':'Your teams are ready. You can start this tournament now.'}</p>`:''}<div class="org-actions">${actions}</div></article>`;
}
function orgBookingRow(booking){
  const cancellable=!orgIsOrganisation()&&booking.status==='confirmed'&&booking.purpose==='player'&&orgFuture(booking.startsAt);
  const ground=orgService.grounds.find(item=>item.id===booking.groundId),owned=orgIsOrganisation()&&ground?.organisationId===account.organisationId;
  const money=booking.purpose!=='tournament',answers=(booking.bookingQuestions||ground?.bookingQuestions||[]).filter(question=>typeof booking.answers?.[question.id]==='string'&&booking.answers[question.id]).map(question=>`<div><dt>${escape(question.label)}</dt><dd>${escape(booking.answers[question.id])}</dd></div>`).join('');
  return `<article class="org-booking"><div><div class="org-event-top"><h3>${escape(booking.groundName)}</h3>${orgBadge(booking.status)}</div><p>${escape(orgTime(booking.startsAt,booking.timezone))} · ${escape(booking.timezone)}</p><small>${escape(orgPrice(booking.purpose==='tournament'?booking.price:orgAmount(booking),booking.currency))} · ${booking.purpose==='tournament'?'Tournament reservation':orgIsOrganisation()?escape(booking.playerName||'Player reservation'):'60-minute booking'}</small>${money?`<p class="org-payment-note">Ground hire ${escape(orgPrice(booking.price,booking.currency))}${booking.deposit?` + deposit ${escape(orgPrice(booking.deposit,booking.currency))}`:''}</p>${orgPaymentBadge({...booking,paymentStatus:booking.paymentStatus||(orgAmount(booking)>0?'unpaid':'not_required')})}${booking.paymentInstructions?`<p class="org-payment-note org-detail-copy">${escape(booking.paymentInstructions)}</p>`:''}${booking.refundPolicy?`<p class="org-payment-note org-detail-copy">Cancellation & refunds: ${escape(booking.refundPolicy)}</p>`:''}${booking.paymentReference?`<p class="org-payment-note">Payment reference: ${escape(booking.paymentReference)}</p>`:''}${booking.depositRefunded?`<p class="org-payment-note">Deposit returned: ${escape(orgPrice(booking.deposit,booking.currency))}${booking.depositRefundReference?' · '+escape(booking.depositRefundReference):''}</p>`:''}${booking.paymentStatus==='refund_due'?'<p class="org-payment-note">Contact the organiser for your refund. Cancelling a reservation does not transfer money.</p>':''}`:''}${answers?`<dl class="org-booking-answers org-detail-list">${answers}</dl>`:''}${booking.notes?`<p class="org-detail-copy">${escape(booking.notes)}</p>`:''}</div><div class="org-actions org-payment-actions">${owned?orgPaymentActions(booking,'booking'):''}${cancellable?`<button class="org-button org-danger" data-org-cancel-booking="${escape(booking.id)}" ${orgService.busy.has(booking.id)?'disabled':''}>Cancel booking</button>`:''}</div></article>`;
}
function orgFinanceSummary(){
  const payments=orgService.payments;if(!payments)return '';
  const values=[['Ground payments received',payments.groundCollected],['Ground payments due',payments.groundOutstanding],['Tournament entries received',payments.tournamentCollected],['Tournament entries due',payments.tournamentOutstanding],['Refunds due',payments.refundDue],['Deposits awaiting return',payments.depositReturnDue]];
  return `<details><summary>Payment totals</summary><dl class="org-details">${values.map(([label,value])=>`<div><dt>${label}</dt><dd>${escape(orgPrice(value,payments.currency||'INR'))}</dd></div>`).join('')}</dl><p class="org-help">Record received payments in Reservations or View teams. Refunds stay due until you record that they were returned.</p></details>`;
}
function orgSection(title,subtitle,content,action=''){
  return `<section class="org-section"><div class="org-section-heading"><div><h2>${escape(title)}</h2><p>${escape(subtitle)}</p></div>${action}</div>${content}</section>`;
}
function orgDashboard(){
  if(!orgIsOrganisation())return orgEmpty('Organisation account required','Create an organisation account to add grounds and organise tournaments. Player accounts can book grounds and register their teams.','<a class="org-button" href="#grounds">Find a ground</a>');
  const organisation=orgService.organisation;
  if(!organisation)return orgEmpty('Organisation unavailable','Your organisation could not be found. Retry loading your dashboard.','<button class="org-button" data-org-retry>Try again</button>');
  const activeEvents=orgActiveEvents(),upcomingBookings=orgUpcomingBookings();
  const teams=activeEvents.reduce((total,event)=>total+event.registrationCount,0);
  const drafts=orgService.tournaments.filter(event=>event.status==='draft').length;
  const initials=organisation.name.split(/\s+/).filter(Boolean).slice(0,2).map(word=>word[0]).join('').toUpperCase();
  const metrics=[['grounds','map-pin',orgService.grounds.length,'Bookable grounds','Listed for hourly booking'],['tournaments','trophy',activeEvents.length,'Active tournaments',`${drafts} ${drafts===1?'draft':'drafts'} in preparation`],['bookings','bookmark',upcomingBookings.length,'Upcoming reservations','Player and tournament slots'],['tournaments','users',teams,'Registered teams','Across open and live events']];
  const tabs=[['overview','Overview',null],['grounds','Your grounds',orgService.grounds.length],['tournaments','Your tournaments',orgService.tournaments.length],['bookings','Reservations',upcomingBookings.length]];
  let content;
  if(orgService.tab==='grounds'){
    const list=orgService.grounds.filter(orgMatches);
    content=orgManagerHeading('Your grounds','Edit venue details, prices and opening hours.','<button class="primary" data-org-create-ground>+ Add ground</button>')+`<div class="org-grid">${list.map(orgGroundCard).join('')||orgEmpty(query?'No grounds match your search':'List your first ground',query?'Try a different ground name, sport or location.':'Set up your venue once. Players can then reserve its available hourly slots.',query?'':'<button class="primary" data-org-create-ground>Add a ground</button>')}</div>`;
  }else if(orgService.tab==='tournaments'){
    const list=orgChronological(orgService.tournaments.filter(event=>orgMatches(event)&&(orgService.status==='all'||event.status===orgService.status)));
    content=orgManagerHeading('Your tournaments','From first draft to final whistle. Manage every stage here.','<button class="primary" data-org-create-event>+ Create tournament</button>')+orgStatusFilters([['all','All'],['draft','Draft'],['open','Open'],['live','Live'],['completed','Completed'],['cancelled','Cancelled']])+`<div class="org-grid">${list.map(orgTournamentCard).join('')||orgEmpty(orgService.tournaments.length?'No tournaments in this view':'Create your first tournament',orgService.tournaments.length?'Choose another status or clear your search.':'Start with a draft. You decide when to open registration.',orgService.tournaments.length?'':'<button class="primary" data-org-create-event>Create tournament</button>')}</div>`;
  }else if(orgService.tab==='bookings'){
    const list=orgChronological(orgService.bookings.filter(booking=>{
      const upcoming=booking.status==='confirmed'&&orgFuture(booking.endsAt);
      const matches=!query||[booking.groundName,booking.playerName,booking.purpose].join(' ').toLowerCase().includes(query);
      return matches&&(orgService.status==='all'||(orgService.status==='upcoming'&&upcoming)||(orgService.status==='past'&&booking.status==='confirmed'&&!orgFuture(booking.endsAt))||(orgService.status==='cancelled'&&booking.status==='cancelled'));
    }));
    content=orgManagerHeading('Ground reservations','See who is coming and which ground they have reserved.')+orgStatusFilters([['upcoming','Upcoming'],['past','Past'],['cancelled','Cancelled'],['all','All reservations']])+(list.length?list.map(orgBookingRow).join(''):orgEmpty('No reservations in this view','Player bookings and published tournament reservations appear here. Try another filter if you are looking for an older booking.'));
  }else content=orgOverview(activeEvents,upcomingBookings);
  return `<section class="org-workspace"><div class="org-workspace-identity"><span class="org-monogram" aria-hidden="true">${escape(initials)}</span><div class="org-workspace-copy"><span class="org-kicker">YOUR ORGANISATION</span><h2>${escape(organisation.name)}</h2><p>${escape([organisation.city,organisation.state,organisation.country].filter(Boolean).join(', '))} · ${escape(organisation.sport)}</p></div></div><div class="org-workspace-actions"><button class="org-button" data-org-edit-profile>Edit profile</button><button class="primary" data-org-create-event>+ Create tournament</button></div><div class="org-workspace-summary"><p>${escape(organisation.description||'Bring players together. Add your venues, organise your competitions and keep the day running smoothly.')}</p>${orgBadge(organisation.verificationStatus||'unverified')}</div></section><div class="org-metrics">${metrics.map(([tab,symbol,count,label,detail])=>`<button type="button" data-org-tab="${tab}" aria-label="${escape(label)}: ${count}. Open ${tab}."><span class="org-metric-icon" aria-hidden="true">${icon(symbol)}</span><strong>${count}</strong><span>${label}</span><small>${escape(detail)}</small></button>`).join('')}</div><nav class="org-dashboard-tabs" aria-label="Organisation management">${tabs.map(([tab,label,count])=>`<button type="button" data-org-tab="${tab}" class="${orgService.tab===tab?'active':''}" ${orgService.tab===tab?'aria-current="page"':''}>${label}${count!==null?`<span>${count}</span>`:''}</button>`).join('')}</nav><div class="org-dashboard-panel" id="org-dashboard-panel">${content}</div>`;
}
function orgManagerHeading(title,description,action=''){
  return `<div class="org-manager-toolbar"><div><h2>${escape(title)}</h2><p>${escape(description)}</p></div>${action}</div>`;
}
function orgStatusFilters(choices){
  return `<div class="org-status-filters" role="group" aria-label="Filter by status">${choices.map(([value,label])=>`<button type="button" data-org-status="${value}" class="${orgService.status===value?'active':''}" aria-pressed="${orgService.status===value}">${label}</button>`).join('')}</div>`;
}
function orgDateTile(value,timezone,className='org-agenda-date'){
  const date=new Date(value);
  return `<div class="${className}" aria-hidden="true"><span>${escape(new Intl.DateTimeFormat('en-IN',{timeZone:timezone,month:'short'}).format(date))}</span><strong>${escape(new Intl.DateTimeFormat('en-IN',{timeZone:timezone,day:'2-digit'}).format(date))}</strong></div>`;
}
function orgOverview(events,bookings){
  const next=events[0],drafts=orgService.tournaments.filter(event=>event.status==='draft');
  const tasks=[];
  if(!orgService.organisation.description)tasks.push(['Tell players about your organisation','Add a short introduction to your organisation profile.','Edit profile','data-org-edit-profile']);
  if(!orgService.grounds.length)tasks.push(['Open your first ground for bookings','Set a venue, opening hours and an hourly price.','Add ground','data-org-create-ground']);
  if(!orgService.tournaments.length)tasks.push(['Plan your first competition','Create an online or physical tournament as a draft.','Create draft','data-org-create-event']);
  for(const event of drafts.slice(0,2))tasks.push([event.name,orgFuture(event.registrationClosesAt)?'Your draft is ready to review before publishing.':'The deadline has passed. Update the dates to publish.', 'Review draft',`data-org-review-event="${escape(event.id)}"`]);
  if(next&&next.status==='open'&&next.registrationCount<2)tasks.push(['Check your tournament roster',`${next.name} needs at least two teams to start.`,'View teams',`data-org-roster="${escape(next.id)}"`]);
  const playerValue=bookings.filter(booking=>booking.purpose==='player').reduce((total,booking)=>total+booking.price,0);
  const featured=next?`<article class="org-next-event">${orgDateTile(next.startsAt,next.timezone,'org-event-date')}<div class="org-event-summary"><div class="org-event-top"><span class="org-kicker">${next.status==='live'?'HAPPENING NOW':'NEXT TOURNAMENT'}</span>${orgBadge(next.status)}</div><h3>${escape(next.name)}</h3><p>${escape(orgTime(next.startsAt,next.timezone))} · ${escape(next.timezone)}</p><p>${escape(next.groundName||'Online')} · ${next.registrationCount} / ${next.capacity} teams</p><div class="org-actions"><button class="primary" data-org-review-event="${escape(next.id)}">Manage tournament</button><button class="org-button" data-org-roster="${escape(next.id)}">View teams</button></div></div></article>`:orgEmpty('Make room for your next competition','Create a draft and publish it when you are ready to welcome teams.','<button class="primary" data-org-create-event>Create tournament</button>');
  const agenda=bookings.slice(0,5).map(booking=>`<article class="org-agenda-row">${orgDateTile(booking.startsAt,booking.timezone)}<div class="org-agenda-copy"><h3>${escape(booking.groundName)}</h3><p>${escape(orgTime(booking.startsAt,booking.timezone))} · ${escape(booking.timezone)}</p><small>${escape(booking.playerName)} · ${booking.purpose==='tournament'?'Tournament reservation':'Player booking'}</small></div>${orgBadge(booking.purpose==='tournament'?'Tournament':'Player')}</article>`).join('');
  return `<div class="org-overview-layout"><div>${orgSection('Next on the calendar','Your nearest open or live competition.',featured)}${orgSection('Upcoming reservations','In order of start time, using each venue’s timezone.',agenda?`<div class="org-agenda">${agenda}</div>`:orgEmpty('Your calendar is clear','Confirmed reservations will appear here when players book or you publish a physical tournament.'),'<button class="org-button" data-org-tab="bookings">View reservations →</button>')}</div><aside class="org-overview-aside">${orgSection(tasks.length?'Next steps':'Everything is up to date',tasks.length?'A few useful things to move your organisation forward.':'Your profile and venues are ready for players.',`<div class="org-task-list">${tasks.map(([title,text,label,attrs],index)=>`<article class="org-task"><span class="org-task-number" aria-hidden="true">${index+1}</span><div><h3>${escape(title)}</h3><p>${escape(text)}</p><button class="org-button" ${attrs}>${label} →</button></div></article>`).join('')||'<p class="org-help">Keep an eye on reservations and team registrations as your next event approaches.</p>'}</div>`)}<div class="org-value-note"><span class="org-kicker">UPCOMING GROUND HIRE</span><strong>${escape(orgPrice(playerValue))}</strong><p>Scheduled ground hire, excluding refundable deposits.</p>${orgFinanceSummary()}</div></aside></div>`;
}
function orgMatches(item){
  return (filter==='All sports'||filter===item.sport)&&[item.name,item.sport,item.city,item.address,item.organisationName,item.groundName].filter(Boolean).join(' ').toLowerCase().includes(query);
}
function orgGroundsPage(){
  const list=orgService.grounds.filter(orgMatches);
  return `${orgIsOrganisation()?'<div class="org-list-actions"><p class="org-help">List a ground with facilities, booking questions and payment terms. Manage your reservations in the <a href="#organisation/bookings">organisation workspace</a>.</p><button class="primary" data-org-create-ground>+ Add ground</button></div>':''}<div class="org-grid">${list.map(orgGroundCard).join('')||orgEmpty(orgService.grounds.length?'No grounds match your search':'No grounds listed yet',orgService.grounds.length?'Try another sport or search.':'Organisation accounts can add grounds from their dashboard.')}</div>`;
}
function orgTournamentsPage(){
  const list=orgService.tournaments.filter(orgMatches);
  return `${orgIsOrganisation()?'<div class="org-list-actions"><p class="org-help">Only your organisation can manage its tournaments. Draft events are visible to their organiser.</p><button class="primary" data-org-create-event>+ Create tournament</button></div>':''}<div class="org-grid">${list.map(orgTournamentCard).join('')||orgEmpty(orgService.tournaments.length?'No tournaments match your search':'The next competition starts with you',orgService.tournaments.length?'Try another sport or search.':orgIsOrganisation()?'Create your first tournament draft.':'Published tournaments will appear here when organisers open registration.')}</div>`;
}
function orgActivity(){
  const joined=orgService.tournaments.filter(event=>event.myRegistration?.status==='registered'||event.isParticipant);
  const history=orgService.tournaments.flatMap(event=>(event.myRegistrationHistory||[]).map(registration=>({event,registration})));
  const pastEntries=!orgIsOrganisation()&&history.length?orgSection('Past entries & refunds','Your cancelled tournament entries and their payment status.',history.map(({event,registration})=>`<article class="org-booking"><div><div class="org-event-top"><h3>${escape(event.name)}</h3>${orgBadge(registration.status)}</div><p>${escape(registration.teamName)} · ${escape(orgPrice(orgAmount(registration),registration.currency||'INR'))}</p>${orgPaymentBadge(registration)}${registration.paymentStatus==='refund_due'?'<p class="org-payment-note">Contact the organiser for your refund. Withdrawal does not transfer money.</p>':''}${registration.paymentReference?`<p class="org-payment-note">Payment reference: ${escape(registration.paymentReference)}</p>`:''}${registration.refundPolicy?`<p class="org-payment-note org-detail-copy">${escape(registration.refundPolicy)}</p>`:''}</div></article>`).join('')):'';
  // Preserve saved social posts without showing browser-local demo reservations.
  const saved=state.posts.filter(post=>post.saved??state.saved.includes(post.id));
  return `${orgSection(orgIsOrganisation()?'Ground reservations':'My bookings','Reservations saved by the booking service.',orgService.bookings.length?orgService.bookings.map(orgBookingRow).join(''):orgEmpty('No bookings yet',orgIsOrganisation()?'Reservations for your grounds will appear here.':'Choose an available slot to make your first booking.','<a class="org-button" href="#grounds">Explore grounds</a>'))}${!orgIsOrganisation()?orgSection('My tournament teams','Your current registrations with tournament organisers.',`<div class="org-grid">${joined.map(orgTournamentCard).join('')||orgEmpty('Your next competition is waiting','Find an open tournament and register your team.','<a class="org-button" href="#tournaments">Find a tournament</a>')}</div>`):'<p class="org-help"><a href="#organisation">Open your organisation dashboard</a> to manage tournaments.</p>'}${pastEntries}${orgSection('Saved moments',social.online?'Saved posts from your Ring feed.':'Posts currently saved in this browser preview.',saved.map(postHTML).join('')||orgEmpty('No saved moments yet','Save a post in Ring to keep it here.'))}`;
}
function orgAccountChrome(){
  document.querySelectorAll('[data-org-route="organisation"]').forEach(button=>button.hidden=!orgIsOrganisation()||!account.userId);
  const home=document.querySelector('[data-bottom-route="ring"], [data-bottom-route="organisation"]');
  if(home){home.href=orgIsOrganisation()?'#organisation':'#ring';home.dataset.bottomRoute=orgIsOrganisation()?'organisation':'ring';home.querySelector('span').textContent=orgIsOrganisation()?'Workspace':'Home';}
  if(account.userId){
    if(account.name&&(orgIsService()||orgIsOrganisation()))document.querySelector('.sidebar-bottom strong').textContent=account.name;
    document.querySelector('.sidebar-bottom small').textContent=orgIsOrganisation()?'Organisation administrator':'Your player account';
    if(orgIsService())$('#connection-status').textContent=orgService.loading?'Syncing your workspace…':orgService.error?'Unable to sync · Try again':orgService.syncedAt?'Last synced '+new Intl.DateTimeFormat('en-IN',{hour:'numeric',minute:'2-digit'}).format(orgService.syncedAt):'Signed in';
  }
}
render=function(){
  if(!orgIsService()){orgPreviousRender();orgAccountChrome();return;}
  document.body.classList.add('ring-experience','org-service-view');
  document.body.classList.remove('ring-home','arena-view');
  const headings={organisation:['ORGANISATION WORKSPACE','Run a great day of sport.','Your venues, competitions and reservations at a glance.'],grounds:['FIND YOUR FIELD','Make time for play.','Book a real available slot at a ground managed by an organisation.'],tournaments:['THE COMPETITION','Bring your best game.','Discover published tournaments and register your team.'],activity:['YOUR NEXT MOVES','Your games, saved.','Your bookings, tournament teams and moments worth keeping.']}[view];
  $('#eyebrow').textContent=headings[0];$('#title').textContent=headings[1];$('#subtitle').textContent=headings[2];
  $('.page-heading').hidden=false;$('#create').hidden=true;
  const canFilter=['grounds','tournaments'].includes(view);
  const dashboardSearch=view==='organisation'&&orgService.tab!=='overview';
  $('#search').disabled=!(canFilter||dashboardSearch);$('#search').placeholder=dashboardSearch?'Search your '+(orgService.tab==='bookings'?'reservations':orgService.tab):canFilter?'Search '+view:'Your '+(view==='organisation'?'organisation overview':'activity');
  $('#search').setAttribute('aria-label',$('#search').placeholder);
  $('#filters').hidden=!canFilter;
  const choices=['All sports',...new Set((view==='grounds'?orgService.grounds:orgService.tournaments).map(item=>item.sport))];
  $('#filters').innerHTML=canFilter?choices.map(s=>`<button class="chip ${filter===s?'active':''}" data-org-filter="${escape(s)}" aria-pressed="${filter===s}">${escape(s)}</button>`).join(''):'';
  document.querySelectorAll('.sidebar nav button').forEach(button=>{
    const active=(button.dataset.orgRoute||button.dataset.view)===view;button.classList.toggle('active',active);button.setAttribute('aria-current',active?'page':'false');
  });
  document.querySelectorAll('[data-bottom-route]').forEach(link=>{const active=link.dataset.bottomRoute===view;link.classList.toggle('active',active);if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
  let content;
  if(orgService.loading||orgService.route!==view)content='<div class="org-skeleton" role="status"><span>Loading your '+(view==='organisation'?'organisation':view==='activity'?'activity':view)+'…</span><div></div><div></div><div></div></div>';
  else if(orgService.error)content=`<div class="org-error" role="alert"><p>${escape(orgService.error)}</p><button class="org-button" data-org-retry>Try again</button></div>`;
  else content=({organisation:orgDashboard,grounds:orgGroundsPage,tournaments:orgTournamentsPage,activity:orgActivity}[view])();
  $('#content').innerHTML=orgNavigation()+content;orgAccountChrome();
  if(orgService.focusEvent&&!orgService.loading&&!orgService.error){
    const card=[...document.querySelectorAll('[data-org-roster]')].find(button=>button.dataset.orgRoster===orgService.focusEvent)?.closest('.org-card');
    if(card){card.tabIndex=-1;card.focus();card.scrollIntoView({block:'center',behavior:'auto'});}
    orgService.focusEvent=null;
  }
};
navigate=function(next){
  const [route,tab,eventId]=(next||'ring').split('/');
  if(!orgServiceRoutes.includes(route)){++orgService.request;document.body.classList.remove('org-service-view');orgPreviousNavigate(next);return;}
  const sameDashboard=view==='organisation'&&route==='organisation'&&orgService.route===route&&!orgService.error&&!orgService.loading;
  if(route==='organisation'){
    const nextTab=orgDashboardTabs.includes(tab)?tab:'overview';
    if(nextTab!==orgService.tab)orgService.status=nextTab==='bookings'?'upcoming':'all';
    orgService.tab=nextTab;
    orgService.focusEvent=nextTab==='tournaments'?eventId:null;
  }
  view=route;filter='All sports';query='';$('#search').value='';
  if(sameDashboard)render();else orgLoad(route);
};
function orgOpenForm(title,body,label,submit){
  let pending=false;
  const submitLabel=()=>typeof label==='function'?label():label;
  const action=data=>{
    if(pending)return false;
    pending=true;
    const button=$('#submit-modal'),error=$('#modal .org-form-error');
    button.disabled=true;button.textContent='Saving…';error.textContent='';
    const current=()=>modalAction===action&&$('#modal').open&&error.isConnected;
    (async()=>{
      try{
        await submit(data);
        if(current())$('#modal').close();
        if(orgIsService())await orgLoad();
      }catch(failure){if(current()){error.textContent=failure.message;error.focus();}}
      finally{pending=false;if(current()){button.disabled=false;button.textContent=submitLabel();}}
    })();
    return false;
  };
  openModal(title,`<div class="org-form-context">${body}<p class="org-form-error" role="alert" tabindex="-1"></p></div>`,submitLabel(),action);
  $('#modal').classList.add('org-modal');$('#modal').setAttribute('aria-labelledby','modal-title');$('#submit-modal').disabled=false;$('#submit-modal').textContent=submitLabel();
  return {isCurrent:()=>modalAction===action&&$('#modal').open};
}
function orgEditProfile(){
  const organisation=orgService.organisation;
  if(!orgIsOrganisation()||!organisation)return;
  orgOpenForm('Edit organisation profile',`<p class="org-form-intro">Help players recognise your organisation. These details appear on your grounds and tournaments.</p><label class="field">Organisation name<input name="name" value="${escape(organisation.name)}" required maxlength="100" autocomplete="organization"></label><label class="field">About your organisation<textarea name="description" rows="4" maxlength="1000" placeholder="Tell players about your club, venues and sporting community">${escape(organisation.description||'')}</textarea><span class="org-field-hint">Up to 1,000 characters.</span></label><div class="org-form-grid"><label class="field">Primary sport<select name="sport">${orgSportOptions(organisation.sport)}</select></label><label class="field">City<input name="city" value="${escape(organisation.city)}" required maxlength="80" autocomplete="address-level2"></label><label class="field">State<input name="state" value="${escape(organisation.state)}" required maxlength="80" autocomplete="address-level1"></label><label class="field">Country<input name="country" value="${escape(organisation.country)}" required maxlength="80" autocomplete="country-name"></label></div>`,'Save profile',async data=>{
    const payload=Object.fromEntries(data);
    for(const key of Object.keys(payload))payload[key]=payload[key].trim();
    orgResult(await orgRequest('organisations/me','PATCH',payload),'organisation');
    toast('Organisation profile updated.');
  });
}
const orgDefaultTimezone=()=>orgService.organisation?.country?.toLowerCase()==='india'?'Asia/Kolkata':orgDeviceTimezone();
function orgHourOptions(selected,closing=false){
  return Array.from({length:closing?25:24},(_,hour)=>`${String(hour).padStart(2,'0')}:00`).map(value=>`<option value="${value}" ${value===selected?'selected':''}>${value}</option>`).join('');
}
function orgCreateGround(id=null){
  if(!orgIsOrganisation())return;
  const existing=id?orgService.grounds.find(ground=>ground.id===id&&ground.organisationId===account.organisationId):null;
  if(id&&!existing)return;
  const ground=existing||{name:'',sport:orgService.organisation?.sport||'Football',city:orgService.organisation?.city||'',address:'',timezone:orgDefaultTimezone(),pricePerHour:0,opensAt:'07:00',closesAt:'22:00'};
  const builder=orgTournamentBuilder(ground,true,null,'ground');
  const context=orgOpenForm(existing?'Edit '+ground.name:'Add a bookable ground',`<div class="org-ground-form"><p class="org-form-intro">${existing?'Update your venue. Existing bookings keep their agreed price and payment terms. Hours and sport must fit upcoming reservations.':'Give players everything they need to choose your ground, book a slot and understand the cost.'}</p>
    <section class="org-form-section">${orgSectionHeader(null,'Ground basics','Introduce your venue and where to find it.')}<label class="field">Ground name<input name="name" value="${escape(ground.name)}" required maxlength="100" placeholder="e.g. Northside football ground"></label>${orgTextField('About this ground','description',ground.description,2000,'Describe the venue, playing area and what makes it a great place to play')}<div class="org-form-grid"><label class="field">Sport<select name="sport">${orgSportOptions(ground.sport)}</select></label><label class="field">City<input name="city" value="${escape(ground.city)}" required maxlength="80"></label></div><label class="field">Address<input name="address" value="${escape(ground.address)}" required maxlength="200" placeholder="Street, area and postcode"></label></section>
    <section class="org-form-section">${orgSectionHeader(null,'Facilities & availability','Describe the playing surface and set your bookable hours.')}<div class="org-form-grid">${orgInputField('Playing surface','surface',ground.surface,100,'e.g. Natural grass, turf, hard court')}<label class="field">Player capacity<input name="capacity" type="number" min="1" max="200" step="1" value="${escape(ground.capacity||22)}" required></label><label class="field">Venue timezone<input name="timezone" value="${escape(ground.timezone)}" required maxlength="64" placeholder="Asia/Kolkata"><span class="org-field-hint">An IANA timezone, such as Asia/Kolkata.</span></label><label class="field">Opens at<select name="opensAt">${orgHourOptions(ground.opensAt)}</select></label><label class="field">Closes at<select name="closesAt">${orgHourOptions(ground.closesAt,true)}</select></label></div>${orgTextField('Facilities & amenities (one per line)','amenities',(ground.amenities||[]).join('\n'),971,'Floodlights\nParking\nChanging rooms\nDrinking water')}<p class="org-help">Add up to 12 facilities. Bookings last one hour and use the venue timezone. Closing must be after opening on the same day.</p></section>
    ${orgMoneyFields(ground,'ground',null)}
    <section class="org-form-section">${orgSectionHeader(null,'Rules & contact','Help players prepare for their visit.')}<div class="org-form-grid">${orgInputField('Venue contact','contact',ground.contact,200,'Email, phone or contact instructions')}</div>${orgTextField('Ground rules','rules',ground.rules,3000,'Footwear, equipment, arrival time and conduct',4)}</section>${builder.html}</div>`,existing?'Save ground':'Add ground',async data=>{
    const payload={};
    for(const key of ['name','sport','city','address','timezone','opensAt','closesAt','description','surface','rules','contact'])if(data.has(key))payload[key]=String(data.get(key)||'').trim();
    Object.assign(payload,orgMoneyInformation(data,'ground'),builder.values(data));
    if(data.has('capacity')){payload.capacity=Number(data.get('capacity'));if(!Number.isInteger(payload.capacity)||payload.capacity<1||payload.capacity>200)throw new Error('Player capacity must be between 1 and 200.');}
    if(data.has('amenities')){
      payload.amenities=String(data.get('amenities')||'').split(/\r?\n/).map(value=>value.trim()).filter(Boolean);
      if(payload.amenities.length>12||payload.amenities.some(value=>value.length>80))throw new Error('Add up to 12 facilities, with at most 80 characters each.');
    }
    if(payload.closesAt<=payload.opensAt)throw new Error('Closing time must be after opening time.');
    orgResult(await orgRequest(existing?'grounds/'+encodeURIComponent(id):'grounds',existing?'PATCH':'POST',payload),'ground');
    if(view==='organisation'){orgService.tab='grounds';orgService.status='all';location.hash='organisation/grounds';}
    toast(existing?'Ground updated.':'Ground added. Players can now choose available slots.');
  });
  builder.bind(context);
}
function orgGroundDetails(id){
  const ground=orgService.grounds.find(item=>item.id===id);if(!ground)return;
  const copy=(title,value)=>value?`<section class="org-detail-section"><h3>${escape(title)}</h3><p class="org-detail-copy">${escape(value)}</p></section>`:'';
  const basics=[['Sport',ground.sport],['Address',ground.address],['Opening hours',ground.opensAt+'–'+ground.closesAt],['Venue timezone',ground.timezone],['Playing surface',ground.surface||'Ask the venue'],['Player capacity',ground.capacity||22]];
  const questions=ground.bookingQuestions||[];
  orgOpenForm(ground.name,`<div class="org-ground-details"><p class="org-form-intro">Managed by ${escape(ground.organisationName||orgService.organisation?.name||'your organisation')} · ${escape(ground.city)}</p>${copy('About the ground',ground.description)}<dl class="org-detail-list">${basics.map(([label,value])=>`<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>${ground.amenities?.length?`<section class="org-detail-section"><h3>Facilities & amenities</h3><div class="org-event-tags">${ground.amenities.map(value=>`<span>${escape(value)}</span>`).join('')}</div></section>`:''}${orgMoneyPanel(ground,'ground')}${copy('Ground rules',ground.rules)}${copy('Contact the venue',ground.contact)}${ground.customDetails?.length?`<section class="org-detail-section"><h3>More ground information</h3><dl class="org-detail-list">${ground.customDetails.map(detail=>`<div><dt>${escape(detail.label)}</dt><dd class="org-detail-copy">${escape(detail.value)}</dd></div>`).join('')}</dl></section>`:''}${questions.length?`<section class="org-detail-section"><h3>What you’ll need to book</h3><ul>${questions.map(question=>`<li>${escape(question.label)} ${question.required?'<strong>(required)</strong>':'(optional)'}</li>`).join('')}</ul></section>`:''}</div>`,'Close',async()=>{});
}
function orgTournamentBuilder(event,includeQuestions=true,detailNumber=5,kind='tournament'){
  const isGround=kind==='ground',questionField=isGround?'bookingQuestions':'registrationQuestions';
  let sequence=0;
  let details=(event.customDetails||[]).map(detail=>({...detail,key:'d'+sequence++}));
  let questions=(includeQuestions?event[questionField]||[]:[]).map(question=>({...question,key:'q'+sequence++}));
  const detailRow=detail=>`<div class="org-builder-row org-custom-detail-row" data-org-detail-row="${detail.key}"><div class="org-builder-row-heading"><strong>Custom detail</strong><button type="button" class="org-button org-danger" data-org-remove-detail="${detail.key}" aria-label="Remove custom detail">Remove</button></div><div class="org-form-grid"><label class="field">Detail label<input name="detail_${detail.key}_label" value="${escape(detail.label||'')}" maxlength="80" required placeholder="e.g. What to bring"></label><label class="field">Detail value<textarea name="detail_${detail.key}_value" rows="2" maxlength="500" required placeholder="Add the information players need">${escape(detail.value||'')}</textarea></label></div></div>`;
  const questionRow=question=>`<div class="org-builder-row org-question-row" data-org-question-row="${question.key}"><div class="org-builder-row-heading"><strong>${isGround?'Booking question':'Registration question'}</strong><button type="button" class="org-button org-danger" data-org-remove-question="${question.key}" aria-label="Remove ${isGround?'booking':'registration'} question">Remove</button></div><label class="field">Question for players<input name="question_${question.key}_label" value="${escape(question.label||'')}" maxlength="160" required placeholder="e.g. Captain’s contact number"></label><div class="org-form-grid"><label class="field">Answer type<select name="question_${question.key}_type" data-org-question-type="${question.key}"><option value="text" ${question.type==='select'?'':'selected'}>Written answer</option><option value="select" ${question.type==='select'?'selected':''}>Choose from a list</option></select></label><label class="org-checkbox-field"><input name="question_${question.key}_required" type="checkbox" value="1" ${question.required?'checked':''}>Answer required to ${isGround?'book':'register'}</label></div><label class="field org-question-options" data-org-question-options="${question.key}" ${question.type==='select'?'':'hidden'}>Available choices<textarea name="question_${question.key}_options" rows="3" maxlength="1619" ${question.type==='select'?'required':'disabled'} placeholder="One choice per line">${escape((question.options||[]).join('\n'))}</textarea><span class="org-field-hint">One choice per line. Up to 20 choices, 80 characters each.</span></label></div>`;
  const html=`<input type="hidden" name="tournamentOptions" value="1"><section class="org-form-section org-builder-section">${orgSectionHeader(detailNumber,'Add your own details',isGround?'Add kit requirements, parking instructions or anything else players should know.':'Make this event your own: kit requirements, parking, sponsors or anything else players should know.')}<div class="org-builder-list org-builder-detail-list">${details.map(detailRow).join('')}</div><p class="org-builder-empty org-details-empty" ${details.length?'hidden':''}>No extra details yet. Add a label and the information you want to share.</p><div class="org-builder-toolbar"><button type="button" class="org-button" data-org-add-detail>+ Add custom detail</button><span class="org-help org-detail-count">${details.length} / 12 details</span></div></section>${includeQuestions?`<section class="org-form-section org-builder-section">${orgSectionHeader(isGround?null:6,isGround?'Build your booking form':'Build your registration form',isGround?'Ask players for the information you need before confirming a booking.':'Ask teams for the information you need. Players can update their answers before registration closes.')}<div class="org-builder-list org-builder-question-list">${questions.map(questionRow).join('')}</div><p class="org-builder-empty org-questions-empty" ${questions.length?'hidden':''}>${isGround?'The booking slot is included. Add questions about players, equipment or requests.':'Team name is included. Add your own questions for captains and participants.'}</p><div class="org-builder-toolbar"><button type="button" class="org-button" data-org-add-question>+ Add ${isGround?'booking':'registration'} question</button><span class="org-help org-question-count">${questions.length} / 8 questions</span></div></section>`:''}`;
  const bind=context=>{
    const form=$('#modal');
    const update=()=>{
      form.querySelector('[data-org-add-detail]').disabled=details.length>=12;
      form.querySelector('.org-detail-count').textContent=details.length+' / 12 details';
      form.querySelector('.org-details-empty').hidden=details.length>0;
      if(includeQuestions){
        form.querySelector('[data-org-add-question]').disabled=questions.length>=8;
        form.querySelector('.org-question-count').textContent=questions.length+' / 8 questions';
        form.querySelector('.org-questions-empty').hidden=questions.length>0;
      }
    };
    form.addEventListener('click',click=>{
      if(!context.isCurrent()||$('#submit-modal').disabled)return;
      const button=click.target.closest('button');if(!button)return;
      const data=button.dataset;
      if('orgAddDetail' in data&&details.length<12){
        const detail={key:'d'+sequence++,label:'',value:''};details.push(detail);
        form.querySelector('.org-builder-detail-list').insertAdjacentHTML('beforeend',detailRow(detail));
        form.querySelector(`[name="detail_${detail.key}_label"]`).focus();
      }else if(data.orgRemoveDetail&&details.some(detail=>detail.key===data.orgRemoveDetail)){
        details=details.filter(detail=>detail.key!==data.orgRemoveDetail);
        form.querySelector(`[data-org-detail-row="${data.orgRemoveDetail}"]`).remove();
        form.querySelector('[data-org-add-detail]').focus();
      }else if(includeQuestions&&'orgAddQuestion' in data&&questions.length<8){
        const question={key:'q'+sequence++,id:'question_'+Date.now().toString(36)+'_'+sequence+'_'+Math.random().toString(36).slice(2,10),label:'',type:'text',required:false};questions.push(question);
        form.querySelector('.org-builder-question-list').insertAdjacentHTML('beforeend',questionRow(question));
        form.querySelector(`[name="question_${question.key}_label"]`).focus();
      }else if(includeQuestions&&data.orgRemoveQuestion&&questions.some(question=>question.key===data.orgRemoveQuestion)){
        questions=questions.filter(question=>question.key!==data.orgRemoveQuestion);
        form.querySelector(`[data-org-question-row="${data.orgRemoveQuestion}"]`).remove();
        form.querySelector('[data-org-add-question]').focus();
      }else return;
      click.preventDefault();update();
    });
    form.addEventListener('change',change=>{
      if(!context.isCurrent())return;
      const key=change.target.dataset?.orgQuestionType;
      if(!key||!questions.some(question=>question.key===key))return;
      const select=change.target.value==='select',label=form.querySelector(`[data-org-question-options="${key}"]`),input=form.querySelector(`[name="question_${key}_options"]`);
      label.hidden=!select;input.disabled=!select;input.required=select;
    });
    update();
  };
  const values=data=>{
    const payload={};
    if(data.has('tournamentOptions')||details.length||Array.isArray(event.customDetails)){
      payload.customDetails=details.map(detail=>{
        const label=String(data.get(`detail_${detail.key}_label`)||'').trim(),value=String(data.get(`detail_${detail.key}_value`)||'').trim();
        if(!label||!value)throw new Error('Fill in the label and value for each custom detail, or remove the empty row.');
        return {label,value};
      });
    }
    if(includeQuestions&&(data.has('tournamentOptions')||questions.length||Array.isArray(event[questionField]))){
      payload[questionField]=questions.map(question=>{
        const label=String(data.get(`question_${question.key}_label`)||'').trim(),type=data.get(`question_${question.key}_type`)||'text';
        if(!label)throw new Error('Write each question, or remove the empty row.');
        const item={id:question.id,label,type,required:data.has(`question_${question.key}_required`)};
        if(type==='select'){
          const options=String(data.get(`question_${question.key}_options`)||'').split(/\r?\n/).map(value=>value.trim()).filter(Boolean);
          if(!options.length||options.length>20||options.some(option=>option.length>80)||new Set(options).size!==options.length)throw new Error('Give each choice question 1–20 different choices, up to 80 characters each.');
          item.options=options;
        }else if(type!=='text')throw new Error('Choose a supported answer type for each question.');
        return item;
      });
    }
    return payload;
  };
  return {html,bind,values};
}
function orgTournamentInformation(data){
  const payload={};
  for(const key of ['description','format','formatDetails','prize','eligibility','rules','contact','onlinePlatform'])if(data.has(key))payload[key]=String(data.get(key)||'').trim();
  for(const key of ['teamSize'])if(data.has(key))payload[key]=Number(data.get(key));
  Object.assign(payload,orgMoneyInformation(data,'tournament'));
  if(data.has('playerEmailConfirmation'))payload.playerEmailConfirmation=data.get('playerEmailConfirmation');
  if(data.has('playerEmailVerificationOptions')||data.has('requirePlayerEmailVerification'))payload.requirePlayerEmailVerification=data.has('requirePlayerEmailVerification');
  return payload;
}
function orgParticipationFields(event,number=4){
  return `<section class="org-form-section">${orgSectionHeader(number,'Participation & communication','Give players clear expectations before they join. All fields are optional.')}<div class="org-form-grid">${orgInputField('Organiser contact','contact',event.contact,200,'Email, phone or contact instructions')}${orgInputField('Online platform / meeting point','onlinePlatform',event.onlinePlatform,100,'e.g. Discord, game server or meeting point')}</div>${orgTextField('Who can take part?','eligibility',event.eligibility,1000,'Age group, skill level, region or entry requirements')}${orgTextField('Tournament rules','rules',event.rules,3000,'Match rules, scoring, equipment and conduct',4)}</section>`;
}
function orgCreateEvent(id=null){
  if(!orgIsOrganisation())return;
  const existing=id?orgService.tournaments.find(event=>event.id===id&&event.organisationId===account.organisationId&&event.status==='draft'):null;
  if(id&&!existing)return;
  const owned=orgService.grounds.filter(ground=>ground.organisationId===account.organisationId);
  const event=existing||{name:'',sport:orgService.organisation?.sport||'Football',eventType:'online',timezone:orgDefaultTimezone(),startsAt:'',registrationClosesAt:'',capacity:8,durationHours:2,groundId:null};
  const duration=existing?(new Date(event.endsAt)-new Date(event.startsAt))/3600000:2;
  const initialZone=event.eventType==='physical'?(owned.find(ground=>ground.id===event.groundId)?.timezone||event.timezone):event.timezone;
  const start=event.startsAt?orgLocalInput(event.startsAt,initialZone):'';
  const deadline=event.registrationClosesAt?orgLocalInput(event.registrationClosesAt,initialZone):'';
  const creationLabel=()=>$('#modal [name="publication"]')?.value==='draft'?'Save draft':'Create & publish';
  const builder=orgTournamentBuilder(event);
  const context=orgOpenForm(existing?'Edit tournament draft':'Create a tournament',`<div class="org-tournament-form"><p class="org-form-intro">${existing?'Update the details before publishing.':'Publish to make this tournament visible in player accounts, or save a private draft for later.'} Publishing a physical event also reserves the venue.</p>
    ${existing?'':'<label class="field">Visibility<select name="publication"><option value="publish" selected>Publish for players — visible and open for registration</option><option value="draft">Save private draft — only your organisation can see it</option></select></label>'}
    <section class="org-form-section">${orgSectionHeader(1,'Event basics','Set the tone for your competition.')}<label class="field">Tournament name<input name="name" value="${escape(event.name)}" required maxlength="100" placeholder="e.g. Sunday football cup"></label>${orgTextField('About this tournament','description',event.description,2000,'Tell players what makes this tournament special')}
    <div class="org-form-grid"><label class="field">Sport<select name="sport">${orgSportOptions(event.sport)}</select></label><label class="field">Competition format<select name="format">${Object.entries(orgFormats).map(([value,label])=>`<option value="${value}" ${(event.format||'single_elimination')===value?'selected':''}>${label}</option>`).join('')}</select></label></div>${orgInputField('Format details (optional)','formatDetails',event.formatDetails,200,'e.g. Four groups, top two teams advance')}</section>
    <section class="org-form-section">${orgSectionHeader(2,'Schedule & venue','Choose where and when teams will compete.')}<div class="org-form-grid"><label class="field">Event type<select name="eventType"><option value="online" ${event.eventType==='online'?'selected':''}>Online</option><option value="physical" ${event.eventType==='physical'?'selected':''} ${owned.length?'':'disabled'}>At a ground${owned.length?'':' — add a ground first'}</option></select></label><label class="field org-event-ground" ${event.eventType==='physical'?'':'hidden'}>Your ground<select name="groundId" ${event.eventType==='physical'?'required':'disabled'}><option value="">Choose a ground</option>${owned.map(ground=>`<option value="${escape(ground.id)}" ${event.groundId===ground.id?'selected':''}>${escape(ground.name)} · ${escape(ground.sport)}</option>`).join('')}</select></label></div><p class="org-help">${owned.length?'Physical tournaments use your selected ground’s sport and timezone.':'Want to host at a venue? Add your first ground from the Grounds tab.'}</p>
    <label class="field">Event timezone<input name="timezone" value="${escape(initialZone)}" required maxlength="64" placeholder="Asia/Kolkata"><span class="org-field-hint">All times below use this timezone.</span></label><p class="org-time-note">Enter local times in <strong class="org-selected-timezone">${escape(initialZone)}</strong>.</p><div class="org-form-grid"><label class="field">Tournament starts<input name="startsAt" value="${escape(start)}" type="datetime-local" step="60" required></label><label class="field">Registration closes<input name="registrationClosesAt" value="${escape(deadline)}" type="datetime-local" step="60" required></label><label class="field">Duration (hours)<input name="durationHours" type="number" min="1" max="12" step="1" value="${duration}" required></label></div><p class="org-help">Both dates must be in the future, within 180 days. Registration closes by the start. Physical events begin on an hourly venue slot.</p></section>
    <section class="org-form-section">${orgSectionHeader(3,'Teams & rewards','Set the size of your competition, entry price and rewards.')}<div class="org-form-grid"><label class="field">Team capacity<input name="capacity" type="number" min="2" max="128" step="1" value="${escape(event.capacity)}" required></label><label class="field">Players per team<input name="teamSize" type="number" min="1" max="50" step="1" value="${escape(event.teamSize||5)}" required></label></div><input type="hidden" name="playerEmailVerificationOptions" value="1"><label class="org-checkbox-field"><input name="requirePlayerEmailVerification" type="checkbox" value="1" ${(!existing||event.requirePlayerEmailVerification)?'checked':''}>Require an email for every player</label><label class="field">Player email confirmation<select name="playerEmailConfirmation"><option value="activation_link" ${(!existing||event.playerEmailConfirmation==='activation_link')?'selected':''}>Activation link · Pending / Acknowledged</option><option value="code" ${(existing&&event.playerEmailConfirmation!=='activation_link')?'selected':''}>Six-digit verification code</option></select></label><p class="org-help">The captain enters player emails. Activation links let players acknowledge participation themselves; codes are verified by the captain.</p></section>${orgMoneyFields(event,'tournament','₹')}
    ${orgParticipationFields(event)}${builder.html}</div>`,existing?'Save draft':creationLabel,async data=>{
    const payload={};
    for(const key of ['name','sport','eventType','timezone','groundId','startsAt','registrationClosesAt','capacity','durationHours'])if(data.has(key))payload[key]=data.get(key);
    Object.assign(payload,orgTournamentInformation(data),builder.values(data));
    payload.name=payload.name.trim();payload.timezone=payload.timezone.trim();
    delete payload.publication;
    if(!existing)payload.publish=data.get('publication')==='publish';
    if(payload.eventType==='physical'){
      const ground=owned.find(ground=>ground.id===payload.groundId);
      if(!ground)throw new Error('Choose one of your organisation’s grounds.');
      payload.timezone=ground.timezone;payload.sport=ground.sport;
    }else delete payload.groundId;
    payload.startsAt=orgLocalInstant(payload.startsAt,payload.timezone);
    payload.registrationClosesAt=orgLocalInstant(payload.registrationClosesAt,payload.timezone);
    if(!orgFuture(payload.startsAt)||!orgFuture(payload.registrationClosesAt))throw new Error('Choose future dates for the start and registration deadline.');
    if(new Date(payload.registrationClosesAt)>new Date(payload.startsAt))throw new Error('Registration must close by the tournament start.');
    payload.capacity=Number(payload.capacity);payload.durationHours=Number(payload.durationHours);
    const saved=orgResult(await orgRequest(existing?'tournaments/'+encodeURIComponent(id):'tournaments',existing?'PATCH':'POST',payload),'tournament',payload.publish?'open':'draft');
    orgService.tab='tournaments';orgService.status='all';orgService.focusEvent=saved.id;
    location.hash='organisation/tournaments/'+encodeURIComponent(saved.id);
    toast(saved.status==='open'?'Tournament saved and published. Players can now find it in Tournaments.':existing?'Tournament draft saved. Publish it to make it visible in player accounts.':'Private draft saved. Publish event to make it visible in player accounts.');
  });
  builder.bind(context);
  const form=$('#modal'),type=form.querySelector('[name="eventType"]'),ground=form.querySelector('[name="groundId"]'),timezone=form.querySelector('[name="timezone"]'),sport=form.querySelector('[name="sport"]');
  if(!existing){
    const publication=form.querySelector('[name="publication"]');
    publication.addEventListener('change',()=>{if(context.isCurrent()&&!$('#submit-modal').disabled)$('#submit-modal').textContent=creationLabel();});
  }
  let onlineZone=event.timezone;
  const update=()=>{
    if(!context.isCurrent())return;
    const physical=type.value==='physical',selected=owned.find(item=>item.id===ground.value);
    ground.disabled=!physical;ground.required=physical;
    form.querySelector('.org-event-ground').hidden=!physical;
    timezone.readOnly=physical;
    if(physical){timezone.value=selected?.timezone||initialZone;if(selected)sport.value=selected.sport;}
    else timezone.value=onlineZone;
    form.querySelector('.org-selected-timezone').textContent=timezone.value||'the event timezone';
  };
  type.addEventListener('change',update);ground.addEventListener('change',update);
  timezone.addEventListener('input',()=>{if(type.value==='online')onlineZone=timezone.value;form.querySelector('.org-selected-timezone').textContent=timezone.value||'the event timezone';});
  update();
}
function orgEditEventDetails(id){
  const event=orgService.tournaments.find(item=>item.id===id);
  if(!orgIsOrganisation()||!event||event.organisationId!==account.organisationId||event.status!=='open'||!orgFuture(event.startsAt))return;
  const builder=orgTournamentBuilder(event,false,3);
  const context=orgOpenForm('Edit tournament details',`<div class="org-tournament-form"><p class="org-form-intro">Keep players informed before the tournament starts. Update the event description, rules, contact information and your custom details.</p><div class="org-detail-highlight"><strong>${escape(orgFormatName(event))} · ${escape(event.teamSize||5)} players / team · ${escape(event.capacity)} teams</strong><p>${escape(orgTime(event.startsAt,event.timezone))} · ${escape(event.timezone)} · ${escape(event.eventType==='online'?'Online':event.groundName||'Ground')}</p><p class="org-help">The schedule, entry fee, team settings and registration questions are fixed after publication.</p></div><section class="org-form-section">${orgSectionHeader(1,'Event information')}<label class="field">Tournament name<input name="name" value="${escape(event.name)}" maxlength="100" required></label>${orgTextField('About this tournament','description',event.description,2000)}${orgInputField('Format details','formatDetails',event.formatDetails,200)}${orgInputField('Prizes & rewards','prize',event.prize,300)}${orgTextField('Payment instructions','paymentInstructions',event.paymentInstructions,1000)}${orgTextField('Cancellation & refund policy','refundPolicy',event.refundPolicy,1000)}</section>${orgParticipationFields(event,2)}${builder.html}</div>`,'Save details',async data=>{
    const payload={name:String(data.get('name')||'').trim(),...orgTournamentInformation(data),...builder.values(data)};
    for(const key of ['format','teamSize','entryFee','prizePool','paymentMethod','requirePlayerEmailVerification','playerEmailConfirmation'])delete payload[key];
    if(!payload.name)throw new Error('Enter your tournament name.');
    orgResult(await orgRequest('tournaments/'+encodeURIComponent(id),'PATCH',payload),'tournament','open');
    toast('Tournament details saved. Players can see the updated information.');
  });
  builder.bind(context);
}
function orgEventDetails(id){
  const event=orgService.tournaments.find(item=>item.id===id);if(!event)return;
  const copy=(title,value)=>value?`<section class="org-detail-section"><h3>${escape(title)}</h3><p class="org-detail-copy">${escape(value)}</p></section>`:'';
  const questions=event.registrationQuestions||[];
  const basics=[['Format',orgFormatName(event)],['Players per team',event.teamSize||5],['Player email verification',event.requirePlayerEmailVerification?'Required for every player':'Optional'],['Entry fee per team',event.entryFee?orgPrice(event.entryFee):'Free'],['Starts',orgTime(event.startsAt,event.timezone)],['Ends',orgTime(event.endsAt,event.timezone)],['Registration closes',orgTime(event.registrationClosesAt,event.timezone)],['Timezone',event.timezone],['Venue',event.eventType==='online'?event.onlinePlatform||'Online':event.groundName||'Ground unavailable']];
  orgOpenForm(event.name,`<div class="org-tournament-details"><p class="org-form-intro">Hosted by ${escape(event.organisationName||orgService.organisation?.name||'your organisation')} · ${escape(event.sport)}</p><div class="org-detail-highlight">${orgBadge(event.status)}<strong>${escape(event.registrationCount)} / ${escape(event.capacity)} teams registered</strong><span>${escape(event.spotsLeft)} spots left</span></div>${copy('About the tournament',event.description)}<dl class="org-detail-list">${basics.map(([label,value])=>`<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>${orgMoneyPanel(event,'tournament',event.myRegistration)}${copy('How the competition works',event.formatDetails)}${copy('Prizes & rewards',event.prize)}${copy('Who can take part',event.eligibility)}${copy('Tournament rules',event.rules)}${copy('Contact the organiser',event.contact)}${event.eventType!=='online'?copy('Meeting point',event.onlinePlatform):''}${(event.customDetails||[]).length?`<section class="org-detail-section"><h3>More event information</h3><dl class="org-detail-list">${event.customDetails.map(detail=>`<div><dt>${escape(detail.label)}</dt><dd class="org-detail-copy">${escape(detail.value)}</dd></div>`).join('')}</dl></section>`:''}${questions.length?`<section class="org-detail-section"><h3>What you’ll need to register</h3><p class="org-help">Along with your team name, the organiser asks for:</p><ul>${questions.map(question=>`<li>${escape(question.label)} ${question.required?'<strong>(required)</strong>':'(optional)'}</li>`).join('')}</ul></section>`:''}</div>`,'Close',async()=>{});
}
function orgBook(id){
  if(orgIsOrganisation()){location.hash='organisation';return;}
  const ground=orgService.grounds.find(item=>item.id===id);
  if(!ground){location.hash='grounds';return;}
  let slots=[],loadToken=0,availabilityReady=false,bookingGround=ground,quoteToken=null;
  const context=orgOpenForm('Book '+ground.name,`<p class="modal-note"><span class="org-booking-location">${escape(ground.city)}</span> · one-hour booking.<br>Dates and slot labels use the venue timezone: <strong class="org-booking-timezone">${escape(ground.timezone)}</strong>.</p><div class="org-booking-money">${orgMoneyPanel(ground,'ground')}</div><label class="field">Date at the venue<input name="date" type="date" min="${orgDateInTimezone(ground.timezone)}" value="${orgDateInTimezone(ground.timezone)}" required></label><label class="field">Available start time<select name="startsAt" required disabled><option value="">Loading slots…</option></select></label><p class="org-slot-status" role="status"></p><div class="org-booking-information">${orgRegistrationFields({registrationQuestions:ground.bookingQuestions||[]},{},'booking')}</div>`,'Confirm booking',async data=>{
    const selected=slots.find(slot=>slot.startsAt===data.get('startsAt')&&slot.available);
    if(!availabilityReady||!selected)throw new Error('Choose an available slot before booking.');
    try{orgResult(await orgRequest('bookings','POST',{...orgBookingPayload(bookingGround,data),startsAt:selected.startsAt,...(quoteToken?{quoteToken}:{})}),'booking','confirmed');}
    catch(error){await updateSlots();throw error;}
    toast('Booking confirmed. Your reservation is saved in activity.');
  });
  const modal=$('#modal'),date=modal.querySelector('[name="date"]'),select=modal.querySelector('[name="startsAt"]'),status=modal.querySelector('.org-slot-status');
  const updateSlots=async()=>{
    const token=++loadToken;availabilityReady=false;quoteToken=null;select.disabled=true;$('#submit-modal').disabled=true;select.innerHTML='<option value="">Loading slots…</option>';status.textContent='Checking current availability…';
    try{
      const result=await orgRequest('grounds/'+encodeURIComponent(id)+'/availability?date='+encodeURIComponent(date.value));
      if(token!==loadToken||!context.isCurrent())return;
      let changed=false;
      if(result.ground?.id===id){
        const fresh=result.ground;
        changed=JSON.stringify([bookingGround.pricePerHour,bookingGround.deposit,bookingGround.paymentMethod,bookingGround.paymentInstructions,bookingGround.refundPolicy])!==JSON.stringify([fresh.pricePerHour,fresh.deposit,fresh.paymentMethod,fresh.paymentInstructions,fresh.refundPolicy]);
        if(JSON.stringify(bookingGround.bookingQuestions||[])!==JSON.stringify(fresh.bookingQuestions||[])){
          const notes=modal.querySelector('[name="notes"]')?.value||'';changed=true;
          modal.querySelector('.org-booking-information').innerHTML=orgRegistrationFields({registrationQuestions:fresh.bookingQuestions||[]},{notes},'booking');
        }
        bookingGround=fresh;
        modal.querySelector('.org-booking-money').innerHTML=orgMoneyPanel(fresh,'ground');
        modal.querySelector('.org-booking-location').textContent=fresh.city;
        modal.querySelector('.org-booking-timezone').textContent=fresh.timezone;
        date.min=orgDateInTimezone(fresh.timezone);
      }
      quoteToken=typeof result.quoteToken==='string'?result.quoteToken:null;
      slots=result.slots||[];const available=slots.filter(slot=>slot.available);
      select.innerHTML=available.length?'<option value="">Choose a start time</option>'+slots.map(slot=>`<option value="${escape(slot.startsAt)}" ${slot.available?'':'disabled'}>${escape(slot.label)}${slot.available?'':' · Unavailable'}</option>`).join(''):'<option value="">No available slots</option>';
      select.disabled=!available.length;availabilityReady=available.length>0;status.textContent=(changed?'Venue details changed. Review the updated price and booking questions. ':'')+(available.length?available.length+' available one-hour slots.':'No available slots on this date. Choose another date.');
    }catch(error){if(token===loadToken&&context.isCurrent()){slots=[];select.innerHTML='<option value="">Availability unavailable</option>';status.textContent=error.message;}}
  };
  date.addEventListener('change',()=>{modal.querySelector('.org-form-error').textContent='';updateSlots();});
  select.addEventListener('change',()=>{$('#submit-modal').disabled=!availabilityReady||!select.value;});
  updateSlots();
}
function orgPlayerEmailBuilder(event,registration={}){
  if(event.playerEmailConfirmation==='activation_link')return orgPlayerActivationBuilder(event,registration);
  const required=Boolean(event.requirePlayerEmailVerification),count=Math.min(50,Math.max(1,Number(event.teamSize)||5));
  const saved=Array.isArray(registration.playerEmails)?registration.playerEmails:[];
  const normalise=value=>String(value||'').trim().toLowerCase();
  const rows=Array.from({length:count},(_,index)=>({email:normalise(saved[index]?.email),savedEmail:normalise(saved[index]?.email),existingVerified:saved[index]?.verified===true,verified:saved[index]?.verified===true,challengeId:null,busy:false,request:0}));
  let form=null,context=null,sendingAll=false;
  const current=()=>Boolean(context?.isCurrent());
  const field=(index,type)=>form?.querySelector(`[name="player${type}_${index}"]`);
  const status=index=>form?.querySelector(`[data-org-player-email-status="${index}"]`);
  const read=(index,data)=>normalise(data?.has(`playerEmail_${index}`)?data.get(`playerEmail_${index}`):field(index,'Email')?.value??rows[index].email);
  const refresh=index=>{
    if(!form)return;
    const row=rows[index],send=form.querySelector(`[data-org-send-player-code="${index}"]`),verify=form.querySelector(`[data-org-verify-player-code="${index}"]`),code=field(index,'Code');
    send.disabled=row.busy;send.textContent=row.busy?'Please wait…':row.verified?'Send new code':row.challengeId?'Resend code':'Send code';
    verify.disabled=row.busy||row.verified||!row.challengeId;
    code.disabled=row.verified||!row.challengeId;
    if(row.verified)status(index).textContent='Email verified.';
  };
  const sync=(index,data)=>{
    const email=read(index,data),row=rows[index];
    if(email!==row.email){
      row.email=email;row.verified=false;row.existingVerified=false;row.challengeId=null;row.request++;
      if(form){field(index,'Code').value='';status(index).textContent=email?'Send a code to verify this email.':'';refresh(index);}
    }
    return email;
  };
  const validated=(data,requireAll=required)=>{
    const emails=rows.map((row,index)=>({email:sync(index,data),index}));
    if(requireAll&&emails.some(item=>!item.email))throw new Error('Enter an email for each of the '+count+' players.');
    const entered=emails.filter(item=>item.email);
    if(entered.some(item=>item.email.length>254||!/^([^\s@<>]+)@([^\s@<>]+)\.([^\s@<>]+)$/.test(item.email)))throw new Error('Enter a valid email address for each player.');
    if(new Set(entered.map(item=>item.email)).size!==entered.length)throw new Error('Use a different email address for each player.');
    return entered;
  };
  const send=async index=>{
    if(!current()||rows[index].busy)return;
    let email;
    try{validated(null,false);email=sync(index);if(!email)throw new Error('Enter this player’s email first.');}
    catch(error){status(index).textContent=error.message;return;}
    const row=rows[index],token=++row.request;row.busy=true;refresh(index);status(index).textContent='Sending verification code…';
    try{
      const result=await orgRequest('tournaments/'+encodeURIComponent(event.id)+'/player-emails/request-code','POST',{email},45000);
      if(!current()||token!==row.request||sync(index)!==email)return;
      if(normalise(result.email)!==email||typeof result.challengeId!=='string'||!result.challengeId)throw new Error('The service did not confirm sending a verification code. Try again.');
      row.challengeId=result.challengeId;row.verified=false;row.existingVerified=false;field(index,'Code').value='';status(index).textContent='Code sent to '+email+'. Ask the player for their six-digit code. It expires in 10 minutes.';
    }catch(error){if(current()&&token===row.request)status(index).textContent=error.message;}
    finally{row.busy=false;if(current())refresh(index);}
  };
  const verify=async index=>{
    if(!current()||rows[index].busy)return;
    const row=rows[index],email=sync(index),code=String(field(index,'Code')?.value||'').trim();
    if(!row.challengeId){status(index).textContent='Send a verification code for this email first.';return;}
    if(!/^[0-9]{6}$/.test(code)){status(index).textContent='Enter the six-digit code sent to this player.';return;}
    const token=++row.request,challengeId=row.challengeId;row.busy=true;refresh(index);status(index).textContent='Checking verification code…';
    try{
      const result=await orgRequest('tournaments/'+encodeURIComponent(event.id)+'/player-emails/verify-code','POST',{email,challengeId,code});
      if(!current()||token!==row.request||sync(index)!==email)return;
      if(result.verified!==true||normalise(result.email)!==email||result.challengeId!==challengeId)throw new Error('The service did not confirm this email. Try again.');
      row.verified=true;field(index,'Code').value='';status(index).textContent='Email verified.';
    }catch(error){if(current()&&token===row.request)status(index).textContent=error.message;}
    finally{row.busy=false;if(current())refresh(index);}
  };
  const html=`<input type="hidden" name="playerEmailOptions" value="1"><section class="org-form-section"><h3>Player emails${required?'':' (optional)'}</h3><p class="org-help">${required?'Enter a different email for each of the '+count+' players.':'You can add up to '+count+' player emails.'} Each entered address receives its own verification code. Ask each player for their code, then verify it here. Emails are shared only with your team captain and organiser.</p><div class="org-actions"><button type="button" class="org-button" data-org-send-all-player-codes>Send all codes</button></div><p class="org-help" data-org-player-email-summary role="status"></p>${rows.map((row,index)=>`<div><label class="field">Player ${index+1} email<input type="email" name="playerEmail_${index}" value="${escape(row.email)}" maxlength="254" autocomplete="off" ${required?'required':''} data-org-player-email-index="${index}"></label><div class="org-form-grid"><label class="field">Verification code<input type="text" name="playerCode_${index}" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" placeholder="Six-digit code" disabled></label><div class="org-actions"><button type="button" class="org-button" data-org-send-player-code="${index}">Send code</button><button type="button" class="org-button" data-org-verify-player-code="${index}" disabled>Verify code</button></div></div><p class="org-help" data-org-player-email-status="${index}" role="status">${row.verified?'Email verified.':''}</p></div>`).join('')}</section>`;
  const bind=value=>{
    context=value;form=$('#modal');rows.forEach((row,index)=>refresh(index));
    form.addEventListener('input',change=>{
      if(!current())return;
      const index=change.target.dataset?.orgPlayerEmailIndex;
      if(index!==undefined&&/^\d+$/.test(index)&&Number(index)<rows.length)sync(Number(index));
    });
    form.addEventListener('click',async click=>{
      if(!current()||$('#submit-modal').disabled)return;
      const button=click.target.closest('button');if(!button||button.disabled)return;
      const data=button.dataset;
      if('orgSendAllPlayerCodes' in data){
        click.preventDefault();if(sendingAll)return;
        const summary=form.querySelector('[data-org-player-email-summary]');let entered;
        try{entered=validated();if(!entered.length)throw new Error('Enter the player emails before sending codes.');}
        catch(error){summary.textContent=error.message;return;}
        const pending=entered.filter(item=>!rows[item.index].verified);if(!pending.length){summary.textContent='All entered player emails are verified.';return;}
        sendingAll=true;button.disabled=true;summary.textContent='Sending a separate code to each player…';
        try{
          let cursor=0;
          await Promise.all(Array.from({length:Math.min(2,pending.length)},async()=>{while(cursor<pending.length){const item=pending[cursor++];await send(item.index);}}));
          if(current())summary.textContent='Check each player’s email status below. Verify every entered address before registering.';
        }finally{sendingAll=false;if(current())button.disabled=false;}
      }else{
        const sendIndex=data.orgSendPlayerCode,verifyIndex=data.orgVerifyPlayerCode,index=sendIndex??verifyIndex;
        if(index===undefined||!/^\d+$/.test(index)||Number(index)>=rows.length)return;
        click.preventDefault();if(sendIndex!==undefined)await send(Number(index));else await verify(Number(index));
      }
    });
  };
  const values=data=>{
    const entered=validated(data);
    if(!entered.length)return saved.length?{playerEmails:[]}:{};
    if(sendingAll||rows.some(row=>row.busy))throw new Error('Wait for player email verification to finish.');
    if(entered.some(item=>!rows[item.index].verified))throw new Error('Verify every entered player email before registering your team.');
    const original=saved.filter(item=>item.verified).map(item=>normalise(item.email)).sort();
    if(entered.length===original.length&&entered.map(item=>item.email).sort().every((email,index)=>email===original[index]))return {};
    return {playerEmails:entered.map(({email,index})=>({email,...(rows[index].existingVerified?{}:{challengeId:rows[index].challengeId})}))};
  };
  return {html,bind,values};
}
function orgRegistrationFields(event,registration={},kind='registration'){
  const questions=event.registrationQuestions||[],answers=registration.answers||{};
  const fields=questions.map(question=>{
    const name='answer_'+question.id,value=typeof answers[question.id]==='string'?answers[question.id]:'',required=question.required?'required':'';
    return `<label class="field">${escape(question.label)} ${question.required?'<span class="org-field-hint">Required</span>':'<span class="org-field-hint">Optional</span>'}${question.type==='select'?`<select name="${escape(name)}" ${required}><option value="">Choose an answer</option>${(question.options||[]).map(option=>`<option value="${escape(option)}" ${value===option?'selected':''}>${escape(option)}</option>`).join('')}</select>`:`<textarea name="${escape(name)}" rows="2" maxlength="500" ${required}>${escape(value)}</textarea>`}</label>`;
  }).join('');
  return `${fields?`<section class="org-form-section"><h3>Information for the organiser</h3><p class="org-help">${kind==='booking'?'Your answers are shared privately with the venue for this booking.':'Your answers are shared with the organiser and can be updated before registration closes.'}</p>${fields}</section>`:''}<section class="org-form-section"><h3>${kind==='booking'?'Add a booking note':'Add something of your own'}</h3>${orgTextField('Anything else the organiser should know? (optional)','notes',registration.notes,1000,'Share a request, team information or other details you choose')}<p class="org-help">Your note is visible to you and the organiser.</p></section>`;
}
function orgRegistrationPayload(event,data){
  const teamName=String(data.get('teamName')||'').trim();if(!teamName)throw new Error('Enter your team name.');
  return {teamName,...orgQuestionPayload(event.registrationQuestions||[],data)};
}
function orgBookingPayload(ground,data){
  return {groundId:ground.id,...orgQuestionPayload(ground.bookingQuestions||[],data)};
}
function orgQuestionPayload(questions,data){
  const payload={};
  if(questions.length){
    const answers=Object.create(null);
    for(const question of questions){
      const value=String(data.get('answer_'+question.id)||'').trim();
      if(question.required&&!value)throw new Error('Answer the required question: '+question.label);
      if(value.length>500)throw new Error('Keep each registration answer within 500 characters.');
      if(value&&question.type==='select'&&!(question.options||[]).includes(value))throw new Error('Choose an available answer for: '+question.label);
      if(value)answers[question.id]=value;
    }
    payload.answers=answers;
  }
  if(data.has('notes'))payload.notes=String(data.get('notes')||'').trim();
  return payload;
}
function orgRegister(id){
  if(orgIsOrganisation()){location.hash='organisation';return;}
  const event=orgService.tournaments.find(item=>item.id===id);
  if(!event){location.hash='tournaments';return;}
  if(event.myRegistration?.status==='registered'||event.isParticipant){location.hash='activity';return;}
  const playerEmails=orgPlayerEmailBuilder(event);
  const context=orgOpenForm('Register for '+event.name,`<p class="modal-note">${escape(orgTime(event.startsAt,event.timezone))} · ${escape(event.timezone)}<br>Hosted by ${escape(event.organisationName)}. Your team is registered only after the service confirms your place.</p><div class="org-event-tags"><span>${escape(event.teamSize||5)} players / team</span><span>${event.entryFee?escape(orgPrice(event.entryFee))+' entry / team':'Free entry'}</span></div>${orgMoneyPanel(event,'tournament')}<label class="field">Team name<input name="teamName" required maxlength="60" placeholder="Your team name"></label>${playerEmails.html}${orgRegistrationFields(event)}`,'Register team',async data=>{
    const registration=orgResult(await orgRequest('tournaments/'+encodeURIComponent(id)+'/registrations','POST',{...orgRegistrationPayload(event,data),...playerEmails.values(data)}),'registration','registered');
    if(event.playerEmailConfirmation==='activation_link')await orgSendNewActivationEmails(event,registration);
    else toast('Team registered. Your place is saved in activity.');
  });
  playerEmails.bind(context);
}
function orgEditRegistration(id){
  if(orgIsOrganisation())return;
  const event=orgService.tournaments.find(item=>item.id===id);
  if(!event||event.myRegistration?.status!=='registered'||event.status!=='open'||!orgFuture(event.registrationClosesAt))return;
  const playerEmails=orgPlayerEmailBuilder(event,event.myRegistration);
  const context=orgOpenForm('Edit your team · '+event.name,`<p class="modal-note">Update your team details before registration closes on ${escape(orgTime(event.registrationClosesAt,event.timezone))}. Your registered place stays reserved.</p><label class="field">Team name<input name="teamName" value="${escape(event.myRegistration.teamName)}" required maxlength="60" autocomplete="off"></label>${playerEmails.html}${orgRegistrationFields(event,event.myRegistration)}`,'Save team',async data=>{
    orgResult(await orgRequest('tournaments/'+encodeURIComponent(id)+'/registrations/me','PATCH',{...orgRegistrationPayload(event,data),...playerEmails.values(data)}),'registration','registered');
    toast('Team details saved. Your registered place is unchanged.');
  });
  playerEmails.bind(context);
}
function orgConfirmAction(title,body,label,path,message){
  orgOpenForm(title,`<p class="modal-note">${escape(body)}</p>`,label,async()=>{
    const key=path.startsWith('bookings/')?'booking':path.includes('/registrations/')?'registration':'tournament';
    orgResult(await orgRequest(path,'POST',{}),key,'cancelled');toast(message);
  });
}
async function orgEventAction(id,action,button){
  const event=orgService.tournaments.find(item=>item.id===id);
  if(!event||event.organisationId!==account.organisationId||orgService.busy.has(id))return;
  if(action==='cancel'){
    orgConfirmAction('Cancel '+event.name+'?','This closes the event and releases its future ground reservation.','Cancel event','tournaments/'+encodeURIComponent(id)+'/cancel','Tournament cancelled.');return;
  }
  orgService.busy.add(id);button.disabled=true;
  try{orgResult(await orgRequest('tournaments/'+encodeURIComponent(id)+'/'+action,'POST',{}),'tournament',({publish:'open',start:'live',complete:'completed'})[action]);toast(({publish:'Tournament published. Registration is open.',start:'Tournament started.',complete:'Tournament completed.'})[action]);if(orgIsService())await orgLoad();}
  catch(error){toast(error.message);}
  finally{orgService.busy.delete(id);if(orgIsService())render();}
}
function orgRecordPayment(id,kind,eventId,status){
  if(!orgIsOrganisation()||!['paid','refunded','deposit_refunded'].includes(status))return;
  let record,path,key;
  if(kind==='booking'){
    record=orgService.bookings.find(item=>item.id===id);
    const ground=record&&orgService.grounds.find(item=>item.id===record.groundId);
    if(!ground||ground.organisationId!==account.organisationId||record.purpose==='tournament')return;
    path='bookings/'+encodeURIComponent(id)+'/payment';key='booking';
  }else if(kind==='registration'){
    const event=orgService.tournaments.find(item=>item.id===eventId&&item.organisationId===account.organisationId);
    record=event?.registrations?.find(item=>item.id===id);
    if(!record)return;
    path='tournaments/'+encodeURIComponent(eventId)+'/registrations/'+encodeURIComponent(id)+'/payment';key='registration';
  }else return;
  const depositRefund=status==='deposit_refunded';
  if(orgAmount(record)<=0||(status==='paid'&&(record.paymentStatus!=='unpaid'||!['confirmed','registered'].includes(record.status)))||(status==='refunded'&&(record.paymentStatus!=='refund_due'||record.status!=='cancelled'))||(depositRefund&&(kind!=='booking'||record.paymentStatus!=='paid'||record.status!=='confirmed'||Number(record.deposit)<=0||record.depositRefunded||orgFuture(record.endsAt))))return;
  const label=status==='paid'?'Record received payment':depositRefund?'Record returned deposit':'Record completed refund',amount=depositRefund?Number(record.deposit):orgAmount(record);
  orgOpenForm(label,`<p class="org-form-intro">${status==='paid'?'Confirm the payment you have received directly from the player.':depositRefund?'Confirm the refundable deposit has been returned to the player.':'Confirm the money has been returned to the player.'}</p><p class="org-help">${escape(record.teamName||record.groundName)} · ${escape(orgPrice(amount,record.currency||'INR'))}</p>${orgInputField('Payment / refund reference (optional)','paymentReference','',200,'Receipt number, UPI reference or a note')}<p class="org-payment-note">This records a completed transaction. It does not transfer money.</p>`,status==='paid'?'Mark paid':depositRefund?'Mark deposit returned':'Mark refunded',async data=>{
    const reference=String(data.get('paymentReference')||'').trim();
    if(reference.length>200)throw new Error('Keep the payment reference within 200 characters.');
    const saved=orgResult(await orgRequest(path,'PATCH',{paymentStatus:status,paymentReference:reference}),key);
    if(depositRefund?!saved.depositRefunded:saved.paymentStatus!==status)throw new Error('The service did not confirm the payment update. Refresh before trying again.');
    toast(status==='paid'?'Payment recorded.':depositRefund?'Deposit refund recorded.':'Refund recorded.');
  });
}
async function orgRoster(id){
  const event=orgService.tournaments.find(item=>item.id===id);
  if(!event||event.organisationId!==account.organisationId)return;
  const context=orgOpenForm('Teams · '+event.name,'<div class="org-roster-content" role="status">Loading registered teams…</div>','Close',async()=>{});
  try{
    const result=await orgRequest('tournaments/'+encodeURIComponent(id)+'/registrations');
    if(!context.isCurrent())return;
    event.registrations=result.registrations||[];
    $('#modal .org-roster-content').innerHTML=event.registrations.map(registration=>{
      const answers=(event.registrationQuestions||[]).filter(question=>typeof registration.answers?.[question.id]==='string'&&registration.answers[question.id]).map(question=>`<div><dt>${escape(question.label)}</dt><dd>${escape(registration.answers[question.id])}</dd></div>`).join('');
      return `<div class="org-roster-row"><strong>${escape(registration.teamName)}</strong><small>${escape(registration.playerName)} · ${escape(registration.status)}</small>${registration.playerEmails?.length?`<dl class="org-roster-answers">${registration.playerEmails.map((player,index)=>`<div><dt>Player ${index+1} email</dt><dd>${escape(player.email)} · ${player.acknowledgementStatus?(player.acknowledgementStatus==='acknowledged'?'Acknowledged':'Pending'):(player.verified?'Verified':'Unverified')}</dd></div>`).join('')}</dl>`:''}${answers?`<dl class="org-roster-answers">${answers}</dl>`:''}${registration.notes?`<div class="org-roster-note"><strong>Note from the team</strong><p class="org-detail-copy">${escape(registration.notes)}</p></div>`:''}<div class="org-payment-note"><strong>${escape(orgPrice(orgAmount(registration),registration.currency||'INR'))}</strong> ${orgPaymentBadge({...registration,paymentStatus:registration.paymentStatus||(orgAmount(registration)>0?'unpaid':'not_required')})}${registration.paymentReference?`<p>Payment reference: ${escape(registration.paymentReference)}</p>`:''}</div><div class="org-actions org-payment-actions">${orgPaymentActions(registration,'registration',id)}</div></div>`;
    }).join('')||'<p class="org-help">No teams registered yet.</p>';
  }catch(error){if(context.isCurrent())$('#modal .org-roster-content').textContent=error.message;}
}
document.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button)return;
  const data=button.dataset;
  if(data.orgRoute){location.hash=data.orgRoute;}
  else if(data.orgTab){
    if(!orgDashboardTabs.includes(data.orgTab))return;
    location.hash='organisation/'+data.orgTab;
  }
  else if(data.orgStatus){orgService.status=data.orgStatus;render();}
  else if(data.orgFilter){filter=data.orgFilter;render();}
  else if('orgRetry' in data){orgLoad();}
  else if('orgCreateGround' in data){orgCreateGround();}
  else if('orgCreateEvent' in data){orgCreateEvent();}
  else if('orgEditProfile' in data){orgEditProfile();}
  else if(data.orgEditGround){orgCreateGround(data.orgEditGround);}
  else if(data.orgGroundDetails){orgGroundDetails(data.orgGroundDetails);}
  else if(data.orgPayment){orgRecordPayment(data.orgPayment,data.orgPaymentKind,data.orgPaymentEvent,data.orgPaymentStatus);}
  else if(data.orgEditEvent){orgCreateEvent(data.orgEditEvent);}
  else if(data.orgEditDetails){orgEditEventDetails(data.orgEditDetails);}
  else if(data.orgEventDetails){orgEventDetails(data.orgEventDetails);}
  else if(data.orgReviewEvent){
    orgService.status='all';location.hash='organisation/tournaments/'+data.orgReviewEvent;
  }
  else if(data.orgBook){orgBook(data.orgBook);}
  else if(data.orgRegister){orgRegister(data.orgRegister);}
  else if(data.orgEditRegistration){orgEditRegistration(data.orgEditRegistration);}
  else if(data.orgRoster){orgRoster(data.orgRoster);}
  else if(data.orgEventAction){orgEventAction(data.orgEventId,data.orgEventAction,button);}
  else if(data.orgCancelBooking){orgConfirmAction('Cancel this booking?','This releases your reserved slot for other players. Your cancelled booking remains in activity.','Cancel booking','bookings/'+encodeURIComponent(data.orgCancelBooking)+'/cancel','Booking cancelled.');}
  else if(data.orgWithdraw){orgConfirmAction('Withdraw your team?','Your team’s spot will become available to another player.','Withdraw team','tournaments/'+encodeURIComponent(data.orgWithdraw)+'/registrations/me/cancel','Team withdrawn.');}
});
$('#modal').addEventListener('close',()=>$('#modal').classList.remove('org-modal'));
// Older social-side calls now lead to the persistent service directory.
book=orgBook;register=orgRegister;
accountReady.then(()=>{orgAccountChrome();navigate(location.hash.slice(1));});
if(orgServiceRoutes.includes(location.hash.slice(1).split('/')[0]))navigate(location.hash.slice(1));

function orgPlayerActivationBuilder(event,registration={}){
  const count=Math.min(50,Math.max(1,Number(event.teamSize)||5)),required=Boolean(event.requirePlayerEmailVerification);
  const saved=registration.playerEmails||[];
  const html=`<section class="org-form-section"><h3>Player emails${required?'':' (optional)'}</h3><p class="org-help">Enter each player's email. Registering your team sends activation emails. Reopen Edit team to resend an email. Players open their link and acknowledge participation; their status stays Pending until they confirm. Reopen this form to refresh statuses.</p>${Array.from({length:count},(_,i)=>`<label class="field">Player ${i+1} email<input name="activationEmail_${i}" type="email" maxlength="254" value="${escape(saved[i]?.email||'')}" ${required?'required':''}></label><p class="org-help" data-activation-status="${i}" role="status">${saved[i]?.acknowledgementStatus==='acknowledged'?'Acknowledged':'Pending'}${saved[i]?.activationSentAt?' · Email sent':''}</p>${registration.id?`<button type="button" class="org-button" data-send-activation="${i}" ${saved[i]?.acknowledgementStatus==='acknowledged'?'disabled':''}>Send activation email</button>`:''}`).join('')}</section>`;
  return {html,values(data){
    const emails=Array.from({length:count},(_,i)=>String(data.get(`activationEmail_${i}`)||'').trim().toLowerCase()).filter(Boolean);
    if(required&&emails.length!==count)throw new Error(`Enter an email for all ${count} players.`);
    if(new Set(emails).size!==emails.length)throw new Error('Each player must have a different email address.');
    return {playerEmails:emails.map(email=>({email}))};
  },bind(context){
    const form=document.querySelector('[name="activationEmail_0"]')?.form;
    if(!form)return;
    form.querySelectorAll('[data-send-activation]').forEach(button=>button.onclick=async()=>{
      const i=Number(button.dataset.sendActivation),email=form.querySelector(`[name="activationEmail_${i}"]`).value.trim().toLowerCase(),status=form.querySelector(`[data-activation-status="${i}"]`);
      if(email!==saved[i]?.email){status.textContent='Save your changed email before sending an activation link.';return;}
      button.disabled=true;
      try{
        const result=await orgRequest('tournaments/'+encodeURIComponent(event.id)+'/player-emails/send-activation','POST',{email});
        if(context.isCurrent())status.textContent=result.acknowledgementStatus==='acknowledged'?'Acknowledged':'Pending · Activation email sent';
      }catch(error){if(context.isCurrent())status.textContent=error.message;}
      finally{if(context.isCurrent())button.disabled=false;}
    });
  }};
}

async function orgSendNewActivationEmails(event,registration){
  const queue=(registration.playerEmails||[]).filter(player=>player.acknowledgementStatus!=='acknowledged');
  let failures=0;
  const worker=async()=>{
    while(queue.length){
      const player=queue.shift();
      try{await orgRequest('tournaments/'+encodeURIComponent(event.id)+'/player-emails/send-activation','POST',{email:player.email});}
      catch{failures++;}
    }
  };
  await Promise.all([worker(),worker()]);
  toast(failures?'Team registered. Some activation emails could not be sent; use Edit team to retry.':'Team registered. Activation emails sent; players are Pending until they acknowledge.');
}
