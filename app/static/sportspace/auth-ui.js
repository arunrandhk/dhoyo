// Hold account-specific API calls until a session has been established.
const nativeFetch=window.fetch.bind(window);
let releaseAccount;
const accountReady=new Promise(resolve=>releaseAccount=resolve);
const account={userId:null,name:'',accountType:'player',organisationId:null,email:'',phone:'',emailVerified:false,googleLinked:false};
const accountFeatureRoutes=new Set(['progress','reminders','tournaments','activity','grounds','organisation','google-play']);
function accountSafeRoute(route){return accountFeatureRoutes.has(route)||/^google-play\/connect\/[A-Za-z0-9_-]{43}$/.test(route);}
let accountReturnRoute=accountSafeRoute(location.hash.slice(1))?location.hash.slice(1):'';
const accountSignupRequested=['#signup','#register'].includes(location.hash);
function accountDestination(identity=account){
  return '/ring#'+(accountReturnRoute||(identity.accountType==='organisation'?'organisation':'ring'));
}
function setAccountIdentity(value){
  account.userId=value.userId||null;
  account.name=value.name||'';
  account.accountType=value.accountType==='organisation'?'organisation':'player';
  account.organisationId=value.organisationId||null;
  account.email=value.email||'';
  account.phone=value.phone||'';
  account.emailVerified=value.emailVerified===true;
  account.googleLinked=value.googleLinked===true;
}
let accountResetToken=new URLSearchParams(location.hash.slice(1)).get('reset-token')||'';
let accountActivationToken=new URLSearchParams(location.hash.slice(1)).get('activate-token')||'';
let accountRecoveryChallenge='',accountRecoveryEmail='',accountRecoveryReturnToProfile=false;
const accountRecoveryRequested=location.hash==='#forgot-password';
if(accountResetToken||accountActivationToken||accountRecoveryRequested)history.replaceState(null,'',location.pathname+location.search+'#ring');
window.fetch=async function(input,options={}){
  const url=typeof input==='string'?input:input.url;
  if(['/api/arena','/api/social','/api/messages','/api/friends','/api/organisations','/api/grounds','/api/bookings','/api/tournaments'].some(path=>url.startsWith(path)))await accountReady;
  if(url.startsWith('/api/'))options={...options,headers:{...options.headers,'X-Dhoyo-Request':'1'}};
  const result=await nativeFetch(input,options);
  if(result.status===401&&!url.startsWith('/api/auth/')&&!document.body.classList.contains('account-visible')){
    setAccountIdentity({});
    showAccountForm('login','Your session has expired. Sign in again.');
  }
  return result;
};
function requireAccountSecureTransport(){
  const local=['localhost','127.0.0.1','::1','[::1]'].includes(location.hostname);
  if(location.protocol==='http:'&&!local)throw new Error('Open this site using HTTPS before signing in or changing your password.');
}
async function accountRequest(path,payload){
  requireAccountSecureTransport();
  const encrypted=payload?(path==='logout'?payload:await encryptAccountPayload(path,payload)):undefined;
  let response;
  try{response=await nativeFetch('/api/auth/'+path,{method:payload?'POST':'GET',headers:{'Content-Type':'application/json','X-Dhoyo-Request':'1'},body:encrypted?JSON.stringify(encrypted):undefined});}
  catch{throw new Error('Could not reach the account service. Check your connection and try again.');}
  const value=await response.json().catch(()=>null);
  if(!response.ok){const error=new Error(value?.error||'The account service is temporarily unavailable. Try again.');error.response=value;throw error;}
  if(!value||typeof value!=='object')throw new Error('The account service returned an unexpected response. Try again.');
  return value;
}
async function rememberAccountPassword(payload){
  if(!window.isSecureContext||typeof window.PasswordCredential!=='function'||typeof navigator.credentials?.store!=='function')return;
  try{
    const credential=new PasswordCredential({id:payload.email.trim(),password:payload.password,...(payload.name?{name:payload.name.trim()}:{})});
    await navigator.credentials.store(credential);
  }catch{
    // Browser password saving is optional; declining it must still allow sign-in.
  }
}
function accountIcon(name){
  const paths={
    arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>',
    eye:'<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    eyeOff:'<path d="m3 3 18 18M10.6 5.1A12 12 0 0 1 12 5c6.5 0 10 7 10 7a18 18 0 0 1-3.2 4M6.2 6.2A18 18 0 0 0 2 12s3.5 7 10 7a13 13 0 0 0 5.8-1.4M10 10a3 3 0 0 0 4 4"/>',
    gamepad:'<path d="M7 7h10a4 4 0 0 1 4 3l1 7a2 2 0 0 1-3.3 1.8L16 16H8l-2.7 2.8A2 2 0 0 1 2 17l1-7a4 4 0 0 1 4-3Z"/><path d="M6 11h4m-2-2v4m7-2h.01m3 2h.01"/>',
    flag:'<path d="M5 21V3m0 1c5-4 9 4 14 0v10c-5 4-9-4-14 0"/>',
    shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>'
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]||paths.arrow}</svg>`;
}
function showAccountForm(mode='login',message='',notice=''){
  if(accountSafeRoute(location.hash.slice(1)))accountReturnRoute=location.hash.slice(1);
  const register=mode==='register',forgot=mode==='forgot',code=mode==='code',reset=mode==='reset'||code;
  const path=forgot?'request-password-code':code?'reset-password-code':reset?'reset-password':mode;
  const title=register?'Join the game.':forgot?'Reset your password.':reset?'Choose a new password.':'Welcome back, player.';
  const intro=register?'Complete your required details. We’ll email an activation link to confirm your account before you sign in.':forgot?'Enter your account email. We’ll send a six-digit verification code.':code?'Enter the code from your email and choose a new password. The code expires in 10 minutes.':reset?'Use at least 10 characters, then sign in with your new password.':'Your squad is waiting. Let’s get you back in.';
  const submitLabel=register?'Create my account':forgot?'Send verification code':reset?'Reset password':'Let’s play';
  document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
  let overlay=document.getElementById('account-screen');
  const previousEmail=overlay?.querySelector('[name="email"]')?.value||accountRecoveryEmail;
  if(!overlay){overlay=document.createElement('section');overlay.id='account-screen';overlay.setAttribute('aria-label','Account access');document.body.append(overlay);}
  document.querySelector('.shell').inert=true;document.querySelector('.sidebar').inert=true;document.querySelector('.app-bottom-nav').inert=true;
  document.body.classList.add('account-visible');
  overlay.classList.toggle('account-register',register);
  overlay.innerHTML=`
    <div class="account-scene" aria-hidden="true"></div>
    <header class="account-header">
      <a class="brand account-brand" href="/ring" aria-label="dhoyo home"><span class="account-brand-symbol" aria-hidden="true">d</span>dhoyo<span class="account-brand-dot">.</span></a>
      <span class="account-header-note"><span></span>ONE COMMUNITY. EVERY GAME.</span>
    </header>
    <div class="account-layout">
      <div class="account-welcome">
        <span class="account-kicker"><span></span>THE GAME STARTS HERE</span>
        <h1>Your people.<br><span>Your game.</span></h1>
        <p>Find your squad. Share your highlights.<br>Make every game a story worth telling.</p>
        <div class="account-pills"><span>ON THE FIELD</span><span>ON THE SERVER</span><span>IN GOOD COMPANY</span></div>
        <div class="account-stickers" aria-label="Sports sticker pack">
          <div class="account-sticker-strip"></div>
          <p><strong>Big plays. Bigger reactions.</strong><span>Sign in and send a little good energy to your teammates.</span></p>
        </div>
        <div class="account-quest">${accountIcon('flag')}<div><strong>Great games. Even better company.</strong><span>Your next teammate is out there.</span></div></div>
      </div>
      <form id="account-${mode}-form" class="account-form" method="post" action="/api/auth/${path}" autocomplete="on" aria-labelledby="account-title" aria-busy="false">
        <div class="account-card-top"><span class="account-access">${accountIcon('gamepad')} PLAYER ACCESS</span><span class="account-card-index" aria-hidden="true">${register?'02':'01'} / DH</span></div>
        <div class="account-auth-tabs" role="group" aria-label="Account options">
          <button type="button" data-account-mode="login" class="${mode==='login'?'active':''}" aria-pressed="${mode==='login'}">Log in</button>
          <button type="button" data-account-mode="register" class="${register?'active':''}" aria-pressed="${register}">Sign up</button>
        </div>
        <h2 id="account-title">${title}</h2>
        <p class="account-form-intro">${intro}</p>
        ${mode==='login'||register?'<div class="account-google" hidden></div>':''}
        ${register?`<label for="account-type">Account type<select id="account-type" name="accountType"><option value="player" selected>Player — book grounds and join tournaments</option><option value="organisation">Organisation — manage grounds and tournaments</option></select></label><label for="account-organisation" class="account-organisation-field" hidden>Organisation name<input id="account-organisation" name="organisationName" autocomplete="organization" placeholder="Your organisation or club" maxlength="100" disabled></label><p class="account-role-note" hidden>Use your organisation’s email. Your name below identifies the administrator. Organisation accounts start unverified.</p><label for="account-name">Your name<input id="account-name" name="name" autocomplete="name" placeholder="What should we call you?" maxlength="100" required></label>`:''}
        ${reset?'':'<label for="account-email">Email address<input id="account-email" name="email" type="email" autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="you@example.com" maxlength="254" required></label>'}
        ${code?'<label for="account-code">Verification code<input id="account-code" name="code" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" minlength="6" maxlength="6" placeholder="6-digit code" required></label>':''}
        ${forgot?'':`<label for="account-password">${reset?'New password':'Password'}</label>
        <div class="account-password-field">
          <input id="account-password" name="password" type="password" autocomplete="${register||reset?'new-password':'current-password'}" placeholder="${register||reset?'Create a password':'Enter your password'}" ${register||reset?'aria-describedby="account-password-help" minlength="10"':''} maxlength="128" required>
          <button type="button" class="account-password-toggle" aria-label="Show password" aria-controls="account-password" aria-pressed="false">${accountIcon('eye')}</button>
        </div>`}
        ${register||reset?'<small id="account-password-help" class="account-password-help">Use at least 10 characters.</small>':''}
        ${reset?'<label for="account-password-confirm">Confirm new password<input id="account-password-confirm" name="passwordConfirm" type="password" autocomplete="new-password" minlength="10" maxlength="128" required></label>':''}
        ${register?`
          <label for="account-phone">Phone number<input id="account-phone" name="phone" type="tel" autocomplete="tel" inputmode="tel" placeholder="+91 98765 43210" maxlength="24" required aria-describedby="account-phone-help"></label><small id="account-phone-help" class="account-password-help">Include your country code. Your phone number stays private on your account.</small>
          <div class="account-location"><label for="account-city">City<input id="account-city" name="city" autocomplete="address-level2" placeholder="Your city" maxlength="80" required></label><label for="account-state">State / region<input id="account-state" name="state" autocomplete="address-level1" placeholder="Your state" maxlength="80" required></label></div>
          <div class="account-location"><label for="account-country">Country<input id="account-country" name="country" autocomplete="country-name" placeholder="Your country" maxlength="80" required></label><label for="account-sport">Your sport<select id="account-sport" name="sport">${['Football','Cricket','Basketball','Badminton','Tennis','Running','Esports','Swimming','Volleyball'].map(s=>`<option>${s}</option>`).join('')}</select></label></div>`:''}
        ${mode==='login'||reset?`<button type="button" class="account-forgot">${code?'Send a new code':reset?'Request a new reset link':'Forgot password? Reset password'}</button>`:''}
        <p class="account-error" role="alert"></p>
        <p class="account-notice" role="status"></p>
        <button class="primary account-submit" type="submit"><span>${submitLabel}</span>${accountIcon('arrow')}</button>
        <p class="account-switch-line">${forgot||reset?'':register?'Already on the team?':'New to the game?'} <button type="button" class="account-switch">${forgot||reset?'Back to log in':register?'Log in':'Create an account'}</button></p>
        ${accountRecoveryReturnToProfile&&account.userId?'<button type="button" class="account-return">Back to profile</button>':''}
        <div class="account-card-footer">${accountIcon('shield')}<span>Your profile. Your community. Your next game.</span></div>
      </form>
    </div>
    <footer class="account-footer"><span>BUILT FOR THE LOVE OF THE GAME</span><span>FIND YOUR SQUAD. MAKE YOUR MARK.${accountIcon('arrow')}</span></footer>`;
  document.body.classList.remove('account-pending');
  overlay.querySelector('.account-error').textContent=message;
  overlay.querySelector('.account-notice').textContent=notice;
  const email=overlay.querySelector('[name="email"]');
  if(email)email.value=previousEmail;
  const stickerStrip=overlay.querySelector('.account-sticker-strip');
  RingStickers.ready.then(items=>{
    if(!stickerStrip.isConnected)return;
    for(const sticker of items){
      const image=document.createElement('img');
      image.className='account-sticker';image.src=sticker.image;image.alt=sticker.name;
      image.width=128;image.height=128;stickerStrip.append(image);
    }
    if(!items.length)stickerStrip.closest('.account-stickers').hidden=true;
  });
  overlay.querySelector('.account-switch').onclick=()=>showAccountForm(mode==='login'?'register':'login');
  const forgotButton=overlay.querySelector('.account-forgot');
  if(forgotButton)forgotButton.onclick=()=>showAccountForm('forgot');
  const returnButton=overlay.querySelector('.account-return');
  if(returnButton)returnButton.onclick=()=>location.replace('/ring#player/'+encodeURIComponent(account.userId)+'/moments');
  overlay.querySelectorAll('[data-account-mode]').forEach(button=>button.onclick=()=>{
    if(button.dataset.accountMode!==mode)showAccountForm(button.dataset.accountMode);
  });
  const password=overlay.querySelector('[name="password"]');
  const accountType=overlay.querySelector('[name="accountType"]');
  if(accountType){
    const updateAccountType=()=>{
      const organisation=accountType.value==='organisation';
      const field=overlay.querySelector('[name="organisationName"]');
      field.disabled=!organisation;field.required=organisation;
      overlay.querySelector('.account-organisation-field').hidden=!organisation;
      overlay.querySelector('.account-role-note').hidden=!organisation;
    };
    accountType.onchange=updateAccountType;updateAccountType();
  }
  const passwordToggle=overlay.querySelector('.account-password-toggle');
  if(passwordToggle)passwordToggle.onclick=event=>{
    const button=event.currentTarget,visible=password.type==='password';
    password.type=visible?'text':'password';
    button.setAttribute('aria-label',visible?'Hide password':'Show password');
    button.setAttribute('aria-pressed',String(visible));
    button.innerHTML=accountIcon(visible?'eyeOff':'eye');
  };
  overlay.querySelector('form').onsubmit=async event=>{
    event.preventDefault();
    const form=event.target,button=form.querySelector('[type=submit]');
    const modeButtons=form.querySelectorAll('[data-account-mode],.account-switch,.account-forgot');
    button.disabled=true;modeButtons.forEach(item=>item.disabled=true);
    form.setAttribute('aria-busy','true');
    form.querySelector('.account-error').textContent='';
    form.querySelector('.account-notice').textContent='';
    button.querySelector('span').textContent=register?'Creating your account…':forgot?'Sending verification code…':reset?'Resetting your password…':'Signing in…';
    const payload=Object.fromEntries(new FormData(form));
    if(payload.email)payload.email=payload.email.trim();
    if(register){
      payload.accountType=payload.accountType==='organisation'?'organisation':'player';
      if(payload.accountType==='player')delete payload.organisationName;
      else payload.organisationName=(payload.organisationName||'').trim();
    }
    try{
      if(reset){
        if(payload.password!==payload.passwordConfirm)throw new Error('The new passwords do not match.');
        if(code&&!/^[0-9]{6}$/.test(payload.code||''))throw new Error('Enter the six-digit verification code from your email.');
        const result=await accountRequest(path,code?{challengeId:accountRecoveryChallenge,code:payload.code,password:payload.password}:{token:accountResetToken,password:payload.password});
        accountResetToken='';accountRecoveryChallenge='';accountRecoveryReturnToProfile=false;setAccountIdentity({});
        showAccountForm('login','',result.message);
        return;
      }
      const result=await accountRequest(path,payload);
      if(forgot){
        if(typeof result.challengeId!=='string'||!/^[A-Za-z0-9_-]{43}$/.test(result.challengeId))throw new Error('Could not request a verification code. Please try again.');
        accountRecoveryChallenge=result.challengeId;accountRecoveryEmail=payload.email;
        showAccountForm('code','',result.message);return;
      }
      if(result.activationRequired){
        const enteredEmail=result.email||payload.email||'';
        const passwordField=form.querySelector('[name="password"]');if(passwordField)passwordField.value='';
        if(window.DhoyoOnboarding)window.DhoyoOnboarding.pending(enteredEmail,result.message);
        else showAccountForm('login','',result.message||'Check your email and activate your account before signing in.');
        return;
      }
      setAccountIdentity(result);
      await rememberAccountPassword(payload);
      // The authenticated credential has been handed to the browser's password
      // manager; do not leave a second copy in the outgoing form.
      for(const name of ['password','passwordConfirm']){
        const field=form.querySelector(`[name="${name}"]`);if(field)field.value='';
      }
      form.remove();
      location.replace(accountDestination());
    }
    catch(error){
      if(error.response?.activationRequired&&window.DhoyoOnboarding){
        const passwordField=form.querySelector('[name="password"]');if(passwordField)passwordField.value='';
        window.DhoyoOnboarding.pending(payload.email||'',error.message);
      }else form.querySelector('.account-error').textContent=error.message;
    }
    finally{
      // Secrets are needed only for this request and optional browser saving.
      for(const name of ['password','passwordConfirm','code','token'])delete payload[name];
      button.disabled=false;modeButtons.forEach(item=>item.disabled=false);
      form.setAttribute('aria-busy','false');
      button.querySelector('span').textContent=submitLabel;
    }
  };
  if(window.DhoyoOnboarding)window.DhoyoOnboarding.mount(overlay,mode);
  if(window.matchMedia('(min-width: 761px)').matches)overlay.querySelector('input').focus({preventScroll:true});
}
(async()=>{
  if(accountActivationToken){
    const token=accountActivationToken;accountActivationToken='';
    if(window.DhoyoOnboarding)window.DhoyoOnboarding.activate(token);
    else showAccountForm('login','Could not open account activation. Refresh this page.');
    return;
  }
  if(accountResetToken){showAccountForm('reset');return;}
  if(accountRecoveryRequested){showAccountForm('forgot');return;}
  try{const result=await accountRequest('me');setAccountIdentity(result);if(!result.userId){showAccountForm(accountSignupRequested?'register':'login');return;}
    if(account.accountType==='organisation'&&(!location.hash||location.hash==='#ring'))history.replaceState(null,'',location.pathname+location.search+'#organisation');
    document.body.classList.remove('account-pending');
    document.querySelector('[data-bottom-route="profile"]').href='#player/'+encodeURIComponent(result.userId);
    const logout=document.createElement('button');logout.className='account-logout';logout.textContent='Sign out';logout.onclick=async()=>{try{await accountRequest('logout',{});location.reload();}catch(error){logout.textContent=error.message;}};document.querySelector('.topbar').append(logout);
    releaseAccount();
  }catch(error){showAccountForm('login','Could not reach the server. Check the connection and try signing in.');}
})();
