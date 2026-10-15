const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function page(){
  const sandbox={console,URLSearchParams,FormData,AbortSignal,location:{hash:''},document:{querySelector(){return null;}},$:()=>({}),escape:value=>String(value).replaceAll('<','&lt;'),toast(){}};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync('app/static/sportspace/organisations.js','utf8').split('function orgPlayerActivationBuilder')[1].replace(/^/, 'function orgPlayerActivationBuilder'),sandbox);
  return sandbox;
}
test('activation form uses saved Pending and Acknowledged status and exact team size',()=>{
  const sandbox=page();
  const builder=vm.runInContext(`orgPlayerActivationBuilder({id:'cup',teamSize:2,requirePlayerEmailVerification:true,playerEmailConfirmation:'activation_link'},{id:'team',playerEmails:[{email:'one@example.invalid',acknowledgementStatus:'acknowledged'},{email:'two@example.invalid',acknowledgementStatus:'pending'}]})`,sandbox);
  assert.match(builder.html,/Acknowledged/);assert.match(builder.html,/Pending/);assert.match(builder.html,/Send activation email/);
  assert.doesNotMatch(builder.html,/Verification code/);
  const data=new FormData();data.set('activationEmail_0',' ONE@example.invalid ');data.set('activationEmail_1','two@example.invalid');
  assert.equal(JSON.stringify(builder.values(data)),JSON.stringify({playerEmails:[{email:'one@example.invalid'},{email:'two@example.invalid'}]}));
  data.set('activationEmail_1','one@example.invalid');assert.throws(()=>builder.values(data),/different email/);
  data.set('activationEmail_1','');assert.throws(()=>builder.values(data),/all 2 players/);
});
test('automatic activation sends only pending players and reports mail failures after saved registration',async()=>{
  const sandbox=page(),calls=[],messages=[];
  sandbox.orgRequest=async(path,method,body)=>{calls.push(body.email);if(body.email==='failed@example.invalid')throw new Error('delivery failed');return {};};
  sandbox.toast=message=>messages.push(message);
  await sandbox.orgSendNewActivationEmails({id:'cup'},{playerEmails:[{email:'done@example.invalid',acknowledgementStatus:'acknowledged'},{email:'pending@example.invalid',acknowledgementStatus:'pending'},{email:'failed@example.invalid',acknowledgementStatus:'pending'}]});
  assert.deepEqual(calls,['pending@example.invalid','failed@example.invalid']);assert.match(messages[0],/Team registered.*could not be sent/);
});
test('email previews cannot acknowledge; explicit recipient click posts token once',async()=>{
  const button={disabled:false,textContent:''},status={textContent:''},requests=[],historyCalls=[];
  const sandbox={location:{hash:'#'+'a'.repeat(43),pathname:'/tournament-acknowledgement'},document:{getElementById:id=>id==='acknowledge'?button:status},history:{replaceState(...args){historyCalls.push(args);}},fetch:async(path,options)=>{requests.push({path,options});return {ok:true,json:async()=>({message:'Your participation has been acknowledged.'})};}};
  vm.createContext(sandbox);vm.runInContext(fs.readFileSync('app/static/sportspace/tournament-acknowledgement.js','utf8'),sandbox);
  assert.equal(requests.length,0);assert.equal(historyCalls.length,1);
  await button.onclick();assert.equal(requests.length,1);assert.equal(button.disabled,true);assert.equal(button.textContent,'Acknowledged');
  assert.equal(JSON.parse(requests[0].options.body).token,'a'.repeat(43));assert.equal(requests[0].options.headers['X-Dhoyo-Request'],'1');
});
