// Google identity and email activation share the same required account details.
// Google credentials and activation tokens stay in memory and encrypted requests.
(() => {
  let epoch = 0, configuration, library, googleChallenge, googleCallback;
  const escapeText = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
  const sports = ['Football', 'Cricket', 'Basketball', 'Badminton', 'Tennis', 'Running', 'Esports', 'Swimming', 'Volleyball'];

  async function config() {
    if (!configuration) configuration = nativeFetch('/api/auth/google/config', {cache: 'no-store'})
      .then(async response => {
        if (!response.ok) return {enabled: false, unavailable: true};
        const result = await response.json();
        return result?.enabled === true && typeof result.clientId === 'string' ? result : {enabled: false};
      }).catch(() => { configuration = undefined; return {enabled: false, unavailable: true}; });
    return configuration;
  }

  function loadGoogle() {
    if (window.google?.accounts?.id) return Promise.resolve(window.google.accounts.id);
    if (!library) library = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://accounts.google.com/gsi/client';
      script.async = true;
      script.onload = () => window.google?.accounts?.id ? resolve(window.google.accounts.id) : reject(new Error('Google sign-in could not load. Try again.'));
      script.onerror = () => { script.remove(); reject(new Error('Google sign-in could not load. Check your connection.')); };
      document.head.append(script);
    }).catch(error => { library = undefined; throw error; });
    return library;
  }

  async function prepareGoogle(clientId) {
    const api = await loadGoogle();
    if (!googleChallenge || googleChallenge.until <= Date.now()) {
      requireAccountSecureTransport();
      const response = await nativeFetch('/api/auth/google/challenge', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-Dhoyo-Request': '1'}, body: '{}'
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not prepare Google sign-in. Try again.');
      if (typeof result.challengeId !== 'string' || typeof result.nonce !== 'string') throw new Error('Could not prepare Google sign-in. Try again.');
      googleChallenge = {...result, until: Date.now() + Math.max(1, Number(result.expiresIn) || 300) * 1000};
      api.initialize({client_id: clientId, nonce: result.nonce, auto_select: false,
        callback: response => { if (googleCallback) googleCallback(response); }});
    }
    return api;
  }

  async function googleButton(container, {current, error, linked = false, succeeded}) {
    try {
      requireAccountSecureTransport();
      const settings = await config();
      if (!current()) return;
      if (!settings.enabled) { container.hidden = true; return; }
      container.hidden = false;
      const api = await prepareGoogle(settings.clientId);
      if (!current()) return;
      let busy = false;
      googleCallback = async response => {
        if (!current() || busy) return;
        busy = true; error.textContent = ''; container.setAttribute('aria-busy', 'true');
        const challengeId = googleChallenge?.challengeId;
        googleChallenge = undefined;
        try {
          if (typeof response?.credential !== 'string') throw new Error('Google sign-in was cancelled. Try again.');
          const result = await accountRequest(linked ? 'google/link' : 'google', {credential: response.credential, challengeId});
          if (!current()) return;
          if (linked) { account.googleLinked = true; succeeded(result); }
          else if (result.onboardingRequired) registerGoogle(result);
          else if (result.activationRequired) pending(result.email || '', result.message);
          else if (result.userId) {
            setAccountIdentity(result);
            location.replace(accountDestination(result));
          } else throw new Error('Google sign-in could not finish. Try again.');
        } catch (problem) {
          if (!current()) return;
          if (problem.response?.activationRequired) { pending(problem.response.email || '', problem.message); return; }
          error.textContent = problem.message;
          // A credential challenge is single-use. A retry renders a fresh button.
          container.replaceChildren();
          googleButton(container, {current, error, linked, succeeded});
        } finally { busy = false; container.setAttribute('aria-busy', 'false'); }
      };
      api.renderButton(container, {theme: 'outline', size: 'large', shape: 'rectangular', text: linked ? 'continue_with' : 'signin_with', width: 300});
    } catch (problem) { if (current()) error.textContent = problem.message; }
  }

  function mount(overlay, mode) {
    const version = ++epoch;
    if (!['login', 'register'].includes(mode)) return;
    const form = overlay.querySelector('form');
    const existingSlot = form.querySelector('.account-google');
    const slot = existingSlot || document.createElement('div');
    slot.className = 'account-google'; slot.hidden = false;
    const label = document.createElement('p'); label.className = 'account-google-label'; label.textContent = 'Google sign-in';
    const button = document.createElement('div'); button.className = 'account-google-button';
    const status = document.createElement('p'); status.className = 'account-google-status'; status.setAttribute('role', 'status');
    status.textContent = 'Checking Google sign-in availability…';
    slot.replaceChildren(label, button, status);
    if (!existingSlot) form.append(slot);
    const current = () => version === epoch && form.isConnected;
    config().then(settings => {
      if (!current()) return;
      if (!settings.enabled) {
        const unavailable = document.createElement('button'); unavailable.type = 'button'; unavailable.disabled = true;
        unavailable.className = 'account-google-unavailable'; unavailable.textContent = 'Google sign-in · Not available yet';
        button.append(unavailable);
        status.textContent = settings.unavailable ? 'Google sign-in is temporarily unavailable. Use email and password to continue.' : 'Google sign-in is being set up. Use email and password to continue.';
        return;
      }
      status.hidden = true;
      googleButton(button, {current, error: form.querySelector('.account-error')});
    });
  }

  function flow(title, intro, fields, label) {
    showAccountForm('login');
    const version = ++epoch;
    const form = document.getElementById('account-screen').querySelector('form');
    form.classList.add('account-onboarding-form');
    form.innerHTML = `<span class="account-access">YOUR DHOYO ACCOUNT</span><h2 id="account-title">${escapeText(title)}</h2><p class="account-form-intro">${escapeText(intro)}</p>${fields}<p class="account-error" role="alert"></p><p class="account-notice" role="status"></p><button type="submit" class="primary account-submit"><span>${escapeText(label)}</span></button><p class="account-switch-line"><button type="button" class="account-back">Back to log in</button></p>`;
    form.querySelector('.account-back').onclick = () => { ++epoch; showAccountForm('login'); };
    const current = () => version === epoch && form.isConnected;
    return {form, current};
  }

  function submitFlow(context, action) {
    context.form.onsubmit = async event => {
      event.preventDefault();
      const {form, current} = context;
      if (!current() || form.getAttribute('aria-busy') === 'true') return;
      const values = Object.fromEntries(new FormData(form));
      form.querySelector('.account-error').textContent = '';
      form.setAttribute('aria-busy', 'true');
      form.querySelectorAll('button').forEach(button => { button.disabled = true; });
      try { await action(values, current); }
      catch (problem) { if (current()) form.querySelector('.account-error').textContent = problem.message; }
      finally {
        if (current()) { form.setAttribute('aria-busy', 'false'); form.querySelectorAll('button').forEach(button => { button.disabled = false; }); }
      }
    };
  }

  function pending(email, message) {
    const context = flow('Check your email.', message || 'Open the activation link in your email, then sign in. Your account stays inactive until you confirm.',
      `<label for="activation-email">Email address<input id="activation-email" name="email" type="email" autocomplete="email" value="${escapeText(email)}" maxlength="254" required></label>`, 'Resend activation link');
    context.form.id = 'account-activation-pending-form';
    context.form.action = '/api/auth/resend-activation';
    submitFlow(context, async (values, current) => {
      const result = await accountRequest('resend-activation', {email: String(values.email || '').trim()});
      if (current()) context.form.querySelector('.account-notice').textContent = result.message;
    });
  }

  function activate(token) {
    const context = flow('Activate your account.', 'Confirm your email to finish activating your account. You can then sign in to dhoyo.', '', 'Activate account');
    context.form.id = 'account-activation-form';
    context.form.action = '/api/auth/activate-account';
    submitFlow(context, async (_values, current) => {
      const result = await accountRequest('activate-account', {token});
      token = '';
      if (current()) showAccountForm('login', '', result.message || 'Account activated. You can sign in now.');
    });
  }

  function registerGoogle(profile) {
    const context = flow('Complete your profile.', 'Add your details to create your account. We’ll send an email activation link before your first sign-in.',
      `<p class="account-google-identity">Google account: <strong>${escapeText(profile.email)}</strong></p>
       <label for="onboarding-type">Account type<select id="onboarding-type" name="accountType"><option value="player">Player</option><option value="organisation">Organisation</option></select></label>
       <label class="account-onboarding-organisation" hidden for="onboarding-organisation">Organisation name<input id="onboarding-organisation" name="organisationName" autocomplete="organization" maxlength="100" disabled></label>
       <label for="onboarding-name">Full name<input id="onboarding-name" name="name" autocomplete="name" value="${escapeText(profile.name)}" maxlength="100" required></label>
       <label for="onboarding-phone">Phone number<input id="onboarding-phone" name="phone" type="tel" autocomplete="tel" placeholder="+91 98765 43210" maxlength="24" required aria-describedby="onboarding-phone-help"></label><small id="onboarding-phone-help" class="account-password-help">Include your country code. Your phone number stays private on your account.</small>
       <div class="account-location"><label for="onboarding-city">City<input id="onboarding-city" name="city" autocomplete="address-level2" maxlength="80" required></label><label for="onboarding-state">State / region<input id="onboarding-state" name="state" autocomplete="address-level1" maxlength="80" required></label></div>
       <div class="account-location"><label for="onboarding-country">Country<input id="onboarding-country" name="country" autocomplete="country-name" maxlength="80" required></label><label for="onboarding-sport">Your sport<select id="onboarding-sport" name="sport" required>${sports.map(sport => `<option>${sport}</option>`).join('')}</select></label></div>`, 'Create account & send activation');
    context.form.id = 'account-google-register-form';
    context.form.action = '/api/auth/google/register';
    const type = context.form.querySelector('[name="accountType"]');
    type.onchange = () => {
      const organisation = type.value === 'organisation';
      const field = context.form.querySelector('[name="organisationName"]');
      field.disabled = !organisation; field.required = organisation;
      context.form.querySelector('.account-onboarding-organisation').hidden = !organisation;
    };
    submitFlow(context, async (values, current) => {
      const payload = Object.fromEntries(['name', 'phone', 'city', 'state', 'country', 'sport', 'accountType'].map(key => [key, String(values[key] || '').trim()]));
      if (payload.accountType === 'organisation') payload.organisationName = String(values.organisationName || '').trim();
      const result = await accountRequest('google/register', payload);
      if (!result.activationRequired) throw new Error('Account setup could not finish. Please try again.');
      if (current()) pending(result.email || profile.email, result.message);
    });
  }

  async function link() {
    if (!account.userId) return;
    const settings = await config();
    if (!settings.enabled) { toast('Google sign-in is not available yet. You can keep using your email and password.'); return; }
    const userId = account.userId;
    const dialog = document.createElement('dialog'); dialog.className = 'account-google-dialog';
    dialog.setAttribute('aria-label', 'Connect your Google account');
    dialog.innerHTML = '<h2>Connect your Google account</h2><p>Choose the Google account with the same email address as your dhoyo account.</p><div class="account-google-button"></div><p class="account-error" role="alert"></p><button type="button" class="org-button">Close</button>';
    dialog.querySelector('button').onclick = () => dialog.close();
    dialog.addEventListener('close', () => { googleCallback = undefined; dialog.remove(); });
    document.body.append(dialog); dialog.showModal();
    googleButton(dialog.querySelector('.account-google-button'), {
      current: () => dialog.isConnected && dialog.open && account.userId === userId,
      error: dialog.querySelector('.account-error'), linked: true,
      succeeded: result => { dialog.close(); document.querySelector('[data-connect-google]')?.remove(); toast(result.message || 'Google account connected.'); }
    });
  }

  function profileAction() {
    if (!account.userId || account.googleLinked || document.body.classList.contains('account-visible') || typeof view === 'undefined' || view !== 'player') return;
    const actions = document.querySelector('.hub-profile-actions');
    if (!actions || typeof arena === 'undefined' || actions.querySelector('[data-connect-google]')) return;
    let playerId; try { playerId = decodeURIComponent(arena.route.split('/')[1] || ''); } catch { return; }
    if (playerId !== account.userId) return;
    const button = document.createElement('button'); button.type = 'button'; button.dataset.connectGoogle = '';
    button.textContent = 'Connect Google account'; button.onclick = link; actions.append(button);
  }

  // Account UI loads before the application renderer. Install the profile action
  // once the remaining deferred scripts and their render wrappers are ready.
  document.addEventListener('DOMContentLoaded', () => {
    if (typeof render === 'function') { const previous = render; render = function () { previous(); profileAction(); }; }
    accountReady.then(profileAction);
  });
  window.DhoyoOnboarding = {mount, pending, activate, link, registerGoogle};
})();
